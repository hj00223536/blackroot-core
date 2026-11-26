import sqlite3
from contextlib import contextmanager
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_utxo_db import UTXOStore
from src.blackroot_sqlite import SQLiteTransactionCoordinator


@contextmanager
def _managed_sqlite(path):
    connection = sqlite3.connect(path)
    try:
        yield connection
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

class UTXOStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "utxos.sqlite"
        self.store = UTXOStore(self.db_path)
        self.funding = OutPoint(bytes.fromhex("31" * 32), 0)
        self.store.add_genesis_output(self.funding, TxOutput(900, b"funding-script"))

    def test_invalid_p2pkh_signature_cannot_mutate_active_chain_or_utxos(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_script import (
            N, _mul, _hash160, _push, legacy_sighash_all, p2pkh_script,
        )
        from src.blackroot_transactions import merkle_root

        private_key = 7
        point = _mul(private_key)
        pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        spend_funding = OutPoint(bytes.fromhex("41" * 32), 0)
        funding_output = TxOutput(900, p2pkh_script(_hash160(pubkey)))
        self.store.add_genesis_output(spend_funding, funding_output)

        def block(previous, timestamp, transactions):
            header = BlockHeader(
                1, previous, merkle_root(tx.txid for tx in transactions),
                timestamp, 0x207fffff, 0,
            )
            return Block(header, tuple(transactions))

        genesis_coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\x01\x01"),),
            (TxOutput(block_subsidy(0), b"genesis-miner"),),
        )
        genesis = block(bytes(32), 1, (genesis_coinbase,))
        self.store.connect_block(genesis, 0)

        unsigned = Transaction(
            1, (TxInput(spend_funding),), (TxOutput(800, b"recipient"),)
        )
        digest = legacy_sighash_all(unsigned, 0, funding_output.script_pubkey)
        nonce = 11
        nonce_point = _mul(nonce)
        r = nonce_point[0] % N
        s = (pow(nonce, N - 2, N) *
             (int.from_bytes(digest, "big") + r * private_key)) % N
        if s > N // 2:
            s = N - s

        def der_integer(value):
            raw = value.to_bytes((value.bit_length() + 7) // 8, "big") or b"\x00"
            if raw[0] & 0x80:
                raw = b"\x00" + raw
            return b"\x02" + bytes([len(raw)]) + raw

        body = der_integer(r) + der_integer(s)
        signature = b"\x30" + bytes([len(body)]) + body + b"\x01"
        signed_input = TxInput(spend_funding, _push(signature) + _push(pubkey))
        invalid_signature = bytearray(signed_input.script_sig)
        invalid_signature[2] ^= 1
        invalid_spend = Transaction(
            1, (TxInput(spend_funding, bytes(invalid_signature)),), unsigned.outputs
        )
        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\x01\x02"),),
            (TxOutput(block_subsidy(1) + 100, b"miner"),),
        )
        candidate = block(genesis.header.hash, 2, (coinbase, invalid_spend))
        before_tip = self.store.tip()
        before_count = self.store.count()
        before_funding = self.store.get(spend_funding)

        with self.assertRaisesRegex(ValueError, "script verification failed"):
            self.store.connect_block(candidate, 1)

        self.assertEqual(self.store.tip(), before_tip)
        self.assertEqual(self.store.count(), before_count)
        self.assertEqual(self.store.get(spend_funding), before_funding)
        self.assertIsNone(self.store.get(OutPoint(invalid_spend.txid, 0)))
        self.store.verify_integrity()

    def test_concurrent_processes_cannot_spend_same_utxo_twice(self):
        ready = [Path(self.tempdir.name) / f"ready-{i}" for i in range(2)]
        release = Path(self.tempdir.name) / "release"
        worker = """
import sys, time
from pathlib import Path
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_utxo_db import UTXOStore
database, ready, release, writer = sys.argv[1:]
store = UTXOStore(database)
Path(ready).write_text("ready")
deadline = time.monotonic() + 10
while not Path(release).exists():
    if time.monotonic() > deadline:
        raise SystemExit("timed out waiting for concurrent-spend release")
    time.sleep(0.01)
funding = OutPoint(bytes.fromhex("31" * 32), 0)
tx = Transaction(1, (TxInput(funding),), (TxOutput(800, ("writer-" + writer).encode()),))
store.apply(tx)
"""
        workers = [
            subprocess.Popen(
                [sys.executable, "-c", worker, str(self.db_path), str(ready[i]),
                 str(release), str(i)],
                cwd=Path(__file__).resolve().parents[1],
            )
            for i in range(2)
        ]
        try:
            deadline = time.monotonic() + 10
            while not all(path.exists() for path in ready):
                if any(process.poll() is not None for process in workers):
                    self.fail("a concurrent spender exited before the release barrier")
                if time.monotonic() > deadline:
                    self.fail("concurrent spenders did not reach the barrier")
                time.sleep(0.01)
            release.write_text("go")
            results = [process.wait(timeout=15) for process in workers]
        finally:
            release.touch()
            for process in workers:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

        self.assertEqual(sorted(results), [0, 1])
        reopened = UTXOStore(self.db_path)
        self.assertIsNone(reopened.get(self.funding))
        self.assertEqual(reopened.count(), 1)
        outputs = [
            OutPoint(bytes.fromhex("31" * 32), 0),
        ]
        with _managed_sqlite(self.db_path) as db:
            scripts = db.execute("SELECT script_pubkey FROM utxos").fetchall()
        self.assertEqual(
            scripts,
            [(b"writer-0",)] if results[0] == 0 else [(b"writer-1",)],
        )

    def test_creation_mtp_persists_and_is_restored_by_disconnect_undo(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        def coinbase(height):
            return Transaction(
                1,
                (TxInput(OutPoint(bytes(32), COINBASE_INDEX), bytes([height + 1, 1])),),
                (TxOutput(block_subsidy(height), b"miner"),),
            )

        genesis_tx = coinbase(0)
        genesis_header = BlockHeader(
            1, bytes(32), merkle_root((genesis_tx.txid,)), 1, 0x207fffff, 0
        )
        genesis = Block(genesis_header, (genesis_tx,))
        self.store.connect_block(genesis, 0)

        next_tx = coinbase(1)
        next_header = BlockHeader(
            1, genesis.header.hash, merkle_root((next_tx.txid,)),
            2, 0x207fffff, 0,
        )
        next_block = Block(next_header, (next_tx,))
        self.store.connect_block(next_block, 1, median_time_past=1_234)

        created = OutPoint(next_tx.txid, 0)
        with _managed_sqlite(self.db_path) as db:
            row = db.execute(
                "SELECT created_mtp FROM utxos WHERE txid=? AND output_index=?",
                (created.txid, created.index),
            ).fetchone()
        self.assertEqual(row, (1_234,))

        reopened = UTXOStore(self.db_path)
        with _managed_sqlite(self.db_path) as db:
            self.assertEqual(
                db.execute(
                    "SELECT created_mtp FROM utxos WHERE txid=? AND output_index=?",
                    (created.txid, created.index),
                ).fetchone(),
                (1_234,),
            )
        reopened.disconnect_tip(next_block.header.hash)
        with _managed_sqlite(self.db_path) as db:
            restored = db.execute(
                "SELECT created_mtp FROM utxos WHERE txid=? AND output_index=?",
                (genesis_tx.txid, 0),
            ).fetchone()
        self.assertEqual(restored, (None,))

    def test_bootstrap_output_keeps_unknown_creation_mtp_null(self):
        with _managed_sqlite(self.db_path) as db:
            row = db.execute(
                "SELECT created_mtp FROM utxos WHERE txid=? AND output_index=?",
                (self.funding.txid, self.funding.index),
            ).fetchone()
        self.assertEqual(row, (None,))

    def test_persists_output_across_instances(self):
        reopened = UTXOStore(self.db_path)
        self.assertEqual(reopened.get(self.funding), TxOutput(900, b"funding-script"))
        self.assertEqual(reopened.count(), 1)

    def test_coordinator_owned_connection_initializes_and_commits_bootstrap_state(self):
        shared_path = Path(self.tempdir.name) / "shared.sqlite"
        funding = OutPoint(bytes.fromhex("51" * 32), 0)
        with SQLiteTransactionCoordinator(shared_path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(shared_path, connection=connection)
                self.assertIs(store._external_connection, connection)
                store.add_genesis_output(funding, TxOutput(700, b"shared"))
                self.assertEqual(store.get(funding), TxOutput(700, b"shared"))
        reopened = UTXOStore(shared_path)
        self.assertEqual(reopened.get(funding), TxOutput(700, b"shared"))

    def test_coordinator_rolls_back_utxo_schema_and_bootstrap_state_together(self):
        shared_path = Path(self.tempdir.name) / "rollback.sqlite"
        funding = OutPoint(bytes.fromhex("52" * 32), 0)
        with SQLiteTransactionCoordinator(shared_path) as coordinator:
            with self.assertRaisesRegex(ValueError, "abort coordinated setup"):
                with coordinator.transaction() as connection:
                    store = UTXOStore(shared_path, connection=connection)
                    store.add_genesis_output(funding, TxOutput(701, b"rollback"))
                    raise ValueError("abort coordinated setup")
        with _managed_sqlite(shared_path) as db:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='utxos'"
            ).fetchall()
        self.assertEqual(tables, [])

    def test_apply_commits_inside_coordinator_transaction(self):
        shared_path = Path(self.tempdir.name) / "coordinated-apply.sqlite"
        funding = OutPoint(bytes.fromhex("53" * 32), 0)
        tx = Transaction(1, (TxInput(funding),), (TxOutput(650, b"recipient"),))
        with SQLiteTransactionCoordinator(shared_path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(shared_path, connection=connection)
                store.add_genesis_output(funding, TxOutput(700, b"funding"))
            with coordinator.transaction() as connection:
                store = UTXOStore(shared_path, connection=connection)
                self.assertEqual(store.apply(tx), 50)
        reopened = UTXOStore(shared_path)
        self.assertIsNone(reopened.get(funding))
        self.assertEqual(reopened.get(OutPoint(tx.txid, 0)), TxOutput(650, b"recipient"))

    def test_outer_rollback_reverts_coordinated_apply(self):
        shared_path = Path(self.tempdir.name) / "rollback-apply.sqlite"
        funding = OutPoint(bytes.fromhex("54" * 32), 0)
        tx = Transaction(1, (TxInput(funding),), (TxOutput(650, b"recipient"),))
        with SQLiteTransactionCoordinator(shared_path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(shared_path, connection=connection)
                store.add_genesis_output(funding, TxOutput(700, b"funding"))
            with self.assertRaisesRegex(RuntimeError, "abort coordinated apply"):
                with coordinator.transaction() as connection:
                    store = UTXOStore(shared_path, connection=connection)
                    store.apply(tx)
                    raise RuntimeError("abort coordinated apply")
        reopened = UTXOStore(shared_path)
        self.assertEqual(reopened.get(funding), TxOutput(700, b"funding"))
        self.assertIsNone(reopened.get(OutPoint(tx.txid, 0)))

    def test_applies_spend_atomically_and_returns_fee(self):
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(800, b"recipient"),),
        )
        self.assertEqual(self.store.apply(tx), 100)
        self.assertIsNone(self.store.get(self.funding))
        self.assertEqual(self.store.get(OutPoint(tx.txid, 0)), TxOutput(800, b"recipient"))
        self.assertEqual(self.store.count(), 1)

    def test_missing_input_does_not_change_database(self):
        missing = OutPoint(bytes.fromhex("42" * 32), 2)
        tx = Transaction(1, (TxInput(missing),), (TxOutput(1, b"x"),))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.apply(tx)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get(self.funding), TxOutput(900, b"funding-script"))

    def test_value_failure_rolls_back(self):
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(901, b"too-much"),),
        )
        with self.assertRaisesRegex(ValueError, "exceed inputs"):
            self.store.apply(tx)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get(self.funding), TxOutput(900, b"funding-script"))

    def test_rejects_duplicate_bootstrap_outpoint(self):
        with self.assertRaises(Exception):
            self.store.add_genesis_output(self.funding, TxOutput(900, b"duplicate"))
        self.assertEqual(self.store.count(), 1)


    def test_refuses_unsafe_schema_v1_database_with_live_utxos(self):
        legacy_path = Path(self.tempdir.name) / "legacy-v1.sqlite"
        with _managed_sqlite(legacy_path) as db:
            db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO metadata(key, value) VALUES('schema_version', '1')")
            db.execute("""
                CREATE TABLE utxos (
                    txid BLOB NOT NULL,
                    output_index INTEGER NOT NULL,
                    value INTEGER NOT NULL,
                    script_pubkey BLOB NOT NULL,
                    PRIMARY KEY(txid, output_index)
                )
            """)
            db.execute(
                "INSERT INTO utxos VALUES(?, ?, ?, ?)",
                (bytes.fromhex("66" * 32), 0, 50, b"legacy"),
            )
        with self.assertRaisesRegex(RuntimeError, "unsafe schema-v1 migration"):
            UTXOStore(legacy_path)


    def _database_snapshot(self, path):
        with _managed_sqlite(path) as db:
            tables = [
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            return {
                table: db.execute(
                    f'SELECT * FROM "{table}"'
                ).fetchall()
                for table in tables
            }

    def test_schema_v2_rejection_preserves_existing_database_without_migration(self):
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "UPDATE metadata SET value='2' WHERE key='schema_version'"
            )
        before = self._database_snapshot(self.db_path)

        with self.assertRaisesRegex(
            RuntimeError,
            "schema-v2 migration requires a verified reindex from genesis",
        ):
            UTXOStore(self.db_path)

        self.assertEqual(self._database_snapshot(self.db_path), before)
        with _managed_sqlite(self.db_path) as db:
            self.assertEqual(
                db.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone(),
                ("2",),
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM utxos").fetchone(),
                (1,),
            )

    def test_schema_v3_rejection_preserves_database_with_ambiguous_creation_mtp(self):
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "UPDATE metadata SET value='3' WHERE key='schema_version'"
            )
        before = self._database_snapshot(self.db_path)

        with self.assertRaisesRegex(
            RuntimeError,
            "schema-v3 migration requires a verified reindex from genesis",
        ):
            UTXOStore(self.db_path)

        self.assertEqual(self._database_snapshot(self.db_path), before)
        with _managed_sqlite(self.db_path) as db:
            self.assertEqual(
                db.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone(),
                ("3",),
            )

    def test_schema_v5_rejects_missing_bootstrap_issuance_metadata(self):
        with _managed_sqlite(self.db_path) as db:
            db.execute("DELETE FROM metadata WHERE key='bootstrap_issued_sats'")
        with self.assertRaisesRegex(
            RuntimeError, "missing bootstrap issuance metadata"
        ):
            UTXOStore(self.db_path)

    def test_schema_v5_rejects_malformed_bootstrap_issuance_metadata(self):
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "UPDATE metadata SET value='not-an-integer' "
                "WHERE key='bootstrap_issued_sats'"
            )
        with self.assertRaisesRegex(
            RuntimeError, "bootstrap issuance metadata is malformed"
        ):
            UTXOStore(self.db_path)

    def test_unknown_future_schema_rejection_preserves_existing_database(self):
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "UPDATE metadata SET value='999' WHERE key='schema_version'"
            )
        before = self._database_snapshot(self.db_path)

        with self.assertRaisesRegex(
            RuntimeError, "unsupported UTXO database schema version"
        ):
            UTXOStore(self.db_path)

        self.assertEqual(self._database_snapshot(self.db_path), before)
        with _managed_sqlite(self.db_path) as db:
            self.assertEqual(
                db.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone(),
                ("999",),
            )


if __name__ == "__main__":
    unittest.main()
