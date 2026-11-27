import sqlite3
from contextlib import contextmanager
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_utxo_db import UTXOStore
from src.blackroot_sqlite import SQLiteTransactionCoordinator
from src.blackroot_monetary import TOTAL_SUPPLY_CAP


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

    def test_connect_block_rejects_invalid_mtp_without_mutation(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"miner"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        candidate = Block(header, (coinbase,))
        before_count = self.store.count()
        for invalid in (-1, True, 1.5, "123"):
            with self.subTest(median_time_past=invalid):
                with self.assertRaisesRegex(ValueError, "median_time_past"):
                    self.store.connect_block(candidate, 0, median_time_past=invalid)
                self.assertIsNone(self.store.tip())
                self.assertEqual(self.store.count(), before_count)

    def test_reorganize_rejects_invalid_mtp_vector_before_mutation(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"miner"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        candidate = Block(header, (coinbase,))
        before_count = self.store.count()
        for invalid in (-1, True, 1.5, "123"):
            with self.subTest(median_time_past=invalid):
                with self.assertRaisesRegex(ValueError, "median-time-past"):
                    self.store.reorganize(
                        (), (candidate,), median_time_past_values=(invalid,)
                    )
                self.assertIsNone(self.store.tip())
                self.assertEqual(self.store.count(), before_count)

    def test_invalid_p2pkh_signature_cannot_mutate_active_chain_or_utxos(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_script import _hash160, _push, legacy_sighash_all, p2pkh_script
        from src.blackroot_transactions import merkle_root

        private_key = ec.derive_private_key(7, ec.SECP256K1())
        pubkey = private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        )
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
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"genesis-miner"),),
        )
        genesis = block(bytes(32), 1, (genesis_coinbase,))
        self.store.connect_block(genesis, 0)

        unsigned = Transaction(
            1, (TxInput(spend_funding),), (TxOutput(800, b"recipient"),)
        )
        digest = legacy_sighash_all(unsigned, 0, funding_output.script_pubkey)
        der_signature = private_key.sign(
            digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))
        )
        r_value, s_value = utils.decode_dss_signature(der_signature)
        from src.blackroot_script import N
        if s_value > N // 2:
            s_value = N - s_value
        der_signature = utils.encode_dss_signature(r_value, s_value)
        signature = der_signature + b"\\x01"
        signed_input = TxInput(spend_funding, _push(signature) + _push(pubkey))
        invalid_signature = bytearray(signed_input.script_sig)
        invalid_signature[5] ^= 1
        invalid_spend = Transaction(
            1, (TxInput(spend_funding, bytes(invalid_signature)),), unsigned.outputs
        )
        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x02"),),
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

    def test_bootstrap_insertion_is_rejected_after_chain_activation_without_mutation(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\x01\x01"),),
            (TxOutput(block_subsidy(0), b"miner"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        self.store.connect_block(Block(header, (coinbase,)), 0)

        candidate = OutPoint(bytes.fromhex("55" * 32), 0)
        with _managed_sqlite(self.db_path) as db:
            issued_before = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]
        count_before = self.store.count()

        with self.assertRaisesRegex(
            RuntimeError, "bootstrap outputs cannot be added after chain activation"
        ):
            self.store.add_genesis_output(candidate, TxOutput(100, b"late-bootstrap"))

        self.assertIsNone(self.store.get(candidate))
        self.assertEqual(self.store.count(), count_before)
        with _managed_sqlite(self.db_path) as db:
            issued_after = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]
        self.assertEqual(issued_after, issued_before)
        self.store.verify_integrity()


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


    def test_reopening_preserves_bootstrap_accounting_without_reissuing_outputs(self):
        with _managed_sqlite(self.db_path) as db:
            before = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]

        reopened = UTXOStore(self.db_path)
        reopened.verify_integrity()
        self.assertEqual(reopened.get(self.funding), TxOutput(900, b"funding-script"))
        self.assertEqual(reopened.count(), 1)

        with _managed_sqlite(self.db_path) as db:
            after_reopen = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]
        self.assertEqual(after_reopen, before)

        with self.assertRaises(sqlite3.IntegrityError):
            reopened.add_genesis_output(self.funding, TxOutput(900, b"duplicate"))
        with _managed_sqlite(self.db_path) as db:
            after_duplicate = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]
        self.assertEqual(after_duplicate, before)
        reopened.verify_integrity()


    def test_spending_bootstrap_output_does_not_rewrite_historical_issuance_on_reopen(self):
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(800, b"recipient-after-spend"),),
        )
        self.assertEqual(self.store.apply(tx), 100)
        self.assertIsNone(self.store.get(self.funding))

        reopened = UTXOStore(self.db_path)
        self.assertEqual(
            reopened.get(OutPoint(tx.txid, 0)),
            TxOutput(800, b"recipient-after-spend"),
        )
        reopened.verify_integrity()
        with _managed_sqlite(self.db_path) as db:
            issued = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]
        self.assertEqual(issued, "900")

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
        # The coordinated first-time setup must roll back the entire schema,
        # not merely the UTXO rows or bootstrap accounting metadata.
        with _managed_sqlite(shared_path) as db:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            indexes = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        self.assertEqual(tables, [])
        self.assertEqual(indexes, [])

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
        reopened.verify_integrity()
        with _managed_sqlite(shared_path) as db:
            issued = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]
        self.assertEqual(issued, "700")

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
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_genesis_output(self.funding, TxOutput(900, b"duplicate"))
        self.assertEqual(self.store.count(), 1)
        self.store.verify_integrity()

    def test_bootstrap_issuance_cap_is_cumulative_and_atomic(self):
        final_outpoint = OutPoint(bytes.fromhex("61" * 32), 0)
        self.store.add_genesis_output(
            final_outpoint,
            TxOutput(TOTAL_SUPPLY_CAP - 900, b"cap-boundary"),
        )
        with _managed_sqlite(self.db_path) as db:
            issued = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]
        self.assertEqual(int(issued), TOTAL_SUPPLY_CAP)
        before_count = self.store.count()
        with self.assertRaisesRegex(ValueError, "cumulative bootstrap issuance exceeds total supply cap"):
            self.store.add_genesis_output(
                OutPoint(bytes.fromhex("62" * 32), 0),
                TxOutput(1, b"over-cap"),
            )
        self.assertEqual(self.store.count(), before_count)
        with _managed_sqlite(self.db_path) as db:
            after = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]
        self.assertEqual(int(after), TOTAL_SUPPLY_CAP)
        self.store.verify_integrity()


    def test_bootstrap_issuance_is_rejected_after_chain_activation_atomically(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"genesis-miner"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)), 1, 0x207fffff, 0
        )
        genesis = Block(header, (coinbase,))
        self.store.connect_block(genesis, 0)

        before_count = self.store.count()
        with _managed_sqlite(self.db_path) as db:
            before_issued = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]

        with self.assertRaisesRegex(
            RuntimeError, "bootstrap outputs cannot be added after chain activation"
        ):
            self.store.add_genesis_output(
                OutPoint(bytes.fromhex("63" * 32), 0),
                TxOutput(20_000_000, b"late-founder-credit"),
            )

        self.assertEqual(self.store.count(), before_count)
        self.assertIsNone(
            self.store.get(OutPoint(bytes.fromhex("63" * 32), 0))
        )
        with _managed_sqlite(self.db_path) as db:
            after_issued = db.execute(
                "SELECT value FROM metadata WHERE key='bootstrap_issued_sats'"
            ).fetchone()[0]
        self.assertEqual(after_issued, before_issued)


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


    def test_zero_bootstrap_counter_does_not_create_initialization_marker(self):
        fresh_path = Path(self.tempdir.name) / "fresh-uninitialized.sqlite"
        UTXOStore(fresh_path)
        with _managed_sqlite(fresh_path) as db:
            metadata = dict(db.execute(
                "SELECT key, value FROM metadata"
            ).fetchall())

        self.assertEqual(metadata["bootstrap_issued_sats"], "0")
        self.assertNotIn("genesis_initialization", metadata)
        self.assertNotIn("genesis_manifest_digest", metadata)

    def test_bootstrap_counter_is_not_genesis_initialization_marker(self):
        # The counter tracks only aggregate trusted bootstrap value. Its
        # presence (including zero) must never be treated as proof that a
        # canonical genesis manifest was authenticated and initialized.
        with _managed_sqlite(self.db_path) as db:
            metadata = dict(db.execute(
                "SELECT key, value FROM metadata"
            ).fetchall())

        self.assertEqual(metadata["bootstrap_issued_sats"], "900")
        self.assertNotIn("genesis_initialization", metadata)
        self.assertNotIn("genesis_manifest_digest", metadata)


    def test_verify_integrity_rejects_corrupted_bootstrap_issuance_metadata(self):
        cases = (
            ("not-an-integer", "persisted bootstrap issuance metadata is malformed"),
            ("-1", "persisted cumulative issuance exceeds total supply cap"),
            (str(TOTAL_SUPPLY_CAP + 1), "persisted cumulative issuance exceeds total supply cap"),
        )
        for value, expected_error in cases:
            with self.subTest(value=value):
                with _managed_sqlite(self.db_path) as db:
                    db.execute(
                        "UPDATE metadata SET value=? WHERE key='bootstrap_issued_sats'",
                        (value,),
                    )
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    self.store.verify_integrity()
                with _managed_sqlite(self.db_path) as db:
                    db.execute(
                        "UPDATE metadata SET value='900' WHERE key='bootstrap_issued_sats'"
                    )


    def test_verify_integrity_rejects_missing_bootstrap_issuance_metadata(self):
        # A missing accounting record must not be interpreted as zero issuance.
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "DELETE FROM metadata WHERE key='bootstrap_issued_sats'"
            )

        with self.assertRaisesRegex(
            RuntimeError, "persisted bootstrap issuance metadata is malformed"
        ):
            self.store.verify_integrity()


    def test_bootstrap_insertion_rejects_missing_issuance_metadata_without_mutation(self):
        candidate = OutPoint(bytes.fromhex("51" * 32), 1)
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "DELETE FROM metadata WHERE key='bootstrap_issued_sats'"
            )

        with self.assertRaisesRegex(
            RuntimeError, "bootstrap issuance metadata is missing"
        ):
            self.store.add_genesis_output(candidate, TxOutput(100, b"candidate-script"))

        self.assertIsNone(self.store.get(candidate))


    def test_bootstrap_insertion_rejects_corrupt_issuance_metadata_without_mutation(self):
        candidate = OutPoint(bytes.fromhex("52" * 32), 1)
        cases = (
            ("not-an-integer", "bootstrap issuance metadata is malformed"),
            ("-1", "bootstrap issuance metadata exceeds total supply cap"),
            (str(TOTAL_SUPPLY_CAP + 1), "bootstrap issuance metadata exceeds total supply cap"),
        )
        for value, expected_error in cases:
            with self.subTest(value=value):
                with _managed_sqlite(self.db_path) as db:
                    db.execute(
                        "UPDATE metadata SET value=? WHERE key='bootstrap_issued_sats'",
                        (value,),
                    )
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    self.store.add_genesis_output(
                        candidate, TxOutput(100, b"candidate-script")
                    )
                self.assertIsNone(self.store.get(candidate))
                with _managed_sqlite(self.db_path) as db:
                    db.execute(
                        "UPDATE metadata SET value='900' WHERE key='bootstrap_issued_sats'"
                    )


    def test_verify_integrity_rejects_malformed_persisted_utxo_outpoint(self):
        with _managed_sqlite(self.db_path) as db:
            db.execute("PRAGMA ignore_check_constraints = ON")
            db.execute(
                "UPDATE utxos SET txid=? WHERE txid=? AND output_index=?",
                (b"\\x01", self.funding.txid, self.funding.index),
            )

        with self.assertRaisesRegex(
            RuntimeError, "persisted UTXO transaction ID is malformed"
        ):
            self.store.verify_integrity()


    def test_verify_integrity_rejects_out_of_range_persisted_utxo_fields(self):
        cases = (
            ("value", str(TOTAL_SUPPLY_CAP + 1), "persisted UTXO value is malformed"),
            ("created_height", "-1", "persisted UTXO creation height is malformed"),
            ("is_coinbase", "2", "persisted UTXO coinbase flag is malformed"),
            ("created_mtp", "-1", "persisted UTXO creation median-time-past is malformed"),
        )
        for column, value, message in cases:
            with self.subTest(column=column):
                with _managed_sqlite(self.db_path) as db:
                    db.execute("PRAGMA ignore_check_constraints = ON")
                    db.execute(
                        f"UPDATE utxos SET {column}=? WHERE txid=? AND output_index=?",
                        (value, self.funding.txid, self.funding.index),
                    )
                with self.assertRaisesRegex(RuntimeError, message):
                    self.store.verify_integrity()
                with _managed_sqlite(self.db_path) as db:
                    db.execute(
                        f"UPDATE utxos SET {column}=? WHERE txid=? AND output_index=?",
                        ({"value": "900", "created_height": "0", "is_coinbase": "0", "created_mtp": None}[column],
                         self.funding.txid, self.funding.index),
                    )


    def test_verify_integrity_rejects_live_utxo_output_and_provenance_tampering(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"active-miner-script"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        self.store.connect_block(Block(header, (coinbase,)), 0)
        outpoint = OutPoint(coinbase.txid, 0)

        corruptions = (
            ("value", 1, "persisted UTXO output does not match its active transaction"),
            ("script_pubkey", b"tampered-script", "persisted UTXO output does not match its active transaction"),
            ("is_coinbase", 0, "persisted UTXO provenance does not match its active transaction"),
            ("output_index", 1, "persisted UTXO output index is absent from its active transaction"),
        )
        original = {
            "value": block_subsidy(0),
            "script_pubkey": b"active-miner-script",
            "is_coinbase": 1,
            "output_index": 0,
        }
        for column, value, expected_error in corruptions:
            with self.subTest(column=column):
                with _managed_sqlite(self.db_path) as db:
                    db.execute(
                        f"UPDATE utxos SET {column}=? WHERE txid=? AND output_index=0",
                        (value, outpoint.txid),
                    )
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    self.store.verify_integrity()
                with _managed_sqlite(self.db_path) as db:
                    db.execute(
                        f"UPDATE utxos SET {column}=? WHERE txid=? AND output_index=?",
                        (original[column], outpoint.txid, value if column == "output_index" else 0),
                    )
        self.store.verify_integrity()


    def test_verify_integrity_rejects_missing_or_extra_undo_created_records(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"undo-audit-miner"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        self.store.connect_block(Block(header, (coinbase,)), 0)

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "DELETE FROM block_undo_created WHERE height=0 AND txid=? AND output_index=0",
                (coinbase.txid,),
            )
        with self.assertRaisesRegex(
            RuntimeError, "undo-created records do not match"
        ):
            self.store.verify_integrity()

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "INSERT INTO block_undo_created(height, txid, output_index) VALUES(0, ?, 0)",
                (coinbase.txid,),
            )
            db.execute(
                "INSERT INTO block_undo_created(height, txid, output_index) VALUES(0, ?, 1)",
                (coinbase.txid,),
            )
        with self.assertRaisesRegex(
            RuntimeError, "undo-created records do not match"
        ):
            self.store.verify_integrity()

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "DELETE FROM block_undo_created WHERE height=0 AND txid=? AND output_index=1",
                (coinbase.txid,),
            )
        self.store.verify_integrity()


    def test_verify_integrity_rejects_missing_and_corrupt_known_spent_undo(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_script import _hash160, _push, legacy_sighash_all, p2pkh_script, N
        from src.blackroot_transactions import merkle_root

        private_key = ec.derive_private_key(11, ec.SECP256K1())
        pubkey = private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        )
        locking_script = p2pkh_script(_hash160(pubkey))
        funding = OutPoint(bytes.fromhex("42" * 32), 0)
        self.store.add_genesis_output(funding, TxOutput(900, locking_script))

        def signed_spend(previous, amount):
            unsigned = Transaction(1, (TxInput(previous),), (TxOutput(amount, locking_script),))
            digest = legacy_sighash_all(unsigned, 0, locking_script)
            der = private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            r_value, s_value = utils.decode_dss_signature(der)
            if s_value > N // 2:
                s_value = N - s_value
            signature = utils.encode_dss_signature(r_value, s_value) + b"\\x01"
            return Transaction(
                1, (TxInput(previous, _push(signature) + _push(pubkey)),), unsigned.outputs
            )

        def make_block(previous_hash, height, transactions):
            coinbase = Transaction(
                1,
                (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
                (TxOutput(block_subsidy(height) + (100 if height == 1 else 10 if height == 2 else 0), b"miner"),),
            )
            all_transactions = (coinbase,) + tuple(transactions)
            header = BlockHeader(
                1, previous_hash, merkle_root(tx.txid for tx in all_transactions),
                height + 1, 0x207fffff, 0,
            )
            return Block(header, all_transactions)

        genesis = make_block(bytes(32), 0, ())
        self.store.connect_block(genesis, 0)
        first_spend = signed_spend(funding, 800)
        block_one = make_block(genesis.header.hash, 1, (first_spend,))
        self.store.connect_block(block_one, 1)

        second_spend = signed_spend(OutPoint(first_spend.txid, 0), 790)
        block_two = make_block(block_one.header.hash, 2, (second_spend,))
        self.store.connect_block(block_two, 2)

        with _managed_sqlite(self.db_path) as db:
            original = db.execute(
                "SELECT value, script_pubkey, created_height, is_coinbase, created_mtp "
                "FROM block_undo_spent WHERE height=2 AND txid=? AND output_index=0",
                (first_spend.txid,),
            ).fetchone()
        self.assertIsNotNone(original)

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "DELETE FROM block_undo_spent WHERE height=2 AND txid=? AND output_index=0",
                (first_spend.txid,),
            )
        with self.assertRaisesRegex(RuntimeError, "missing historical inputs"):
            self.store.verify_integrity()

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "INSERT INTO block_undo_spent(height, txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) "
                "VALUES(2, ?, 0, ?, ?, ?, ?, ?)",
                (first_spend.txid, *original),
            )
            db.execute(
                "UPDATE block_undo_spent SET value=value+1 WHERE height=2 AND txid=? AND output_index=0",
                (first_spend.txid,),
            )
        with self.assertRaisesRegex(RuntimeError, "does not match its source output"):
            self.store.verify_integrity()

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "UPDATE block_undo_spent SET value=? WHERE height=2 AND txid=? AND output_index=0",
                (original[0], first_spend.txid),
            )
        self.store.verify_integrity()


    def test_verify_integrity_rejects_active_transaction_merkle_mismatch(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import compact_size, merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"miner"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        block = Block(header, (coinbase,))
        self.store.connect_block(block, 0)

        with _managed_sqlite(self.db_path) as db:
            stored_header = bytearray(db.execute(
                "SELECT header FROM blocks WHERE height=0"
            ).fetchone()[0])
            stored_header[36] ^= 1
            reconstructed = Block.deserialize(
                bytes(stored_header) + compact_size(1) + coinbase.serialize()
            )
            db.execute(
                "UPDATE blocks SET header=?, block_hash=? WHERE height=0",
                (bytes(stored_header), reconstructed.header.hash),
            )

        with self.assertRaisesRegex(RuntimeError, "merkle root"):
            self.store.verify_integrity()


    def test_verify_integrity_rejects_same_block_forward_transaction_reference(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_script import _hash160, _push, legacy_sighash_all, p2pkh_script, N
        from src.blackroot_transactions import merkle_root

        private_key = ec.derive_private_key(17, ec.SECP256K1())
        pubkey = private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        )
        script = p2pkh_script(_hash160(pubkey))
        funding = OutPoint(bytes.fromhex("53" * 32), 0)
        self.store.add_genesis_output(funding, TxOutput(900, script))

        def signed_spend(previous, amount):
            unsigned = Transaction(1, (TxInput(previous),), (TxOutput(amount, script),))
            digest = legacy_sighash_all(unsigned, 0, script)
            der = private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            rv, sv = utils.decode_dss_signature(der)
            if sv > N // 2:
                sv = N - sv
            sig = utils.encode_dss_signature(rv, sv) + b"\\x01"
            return Transaction(
                1, (TxInput(previous, _push(sig) + _push(pubkey)),), unsigned.outputs
            )

        first = signed_spend(funding, 850)
        second = signed_spend(OutPoint(first.txid, 0), 800)
        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0) + 100, b"miner"),),
        )
        transactions = (coinbase, first, second)
        header = BlockHeader(
            1, bytes(32), merkle_root(tx.txid for tx in transactions),
            1, 0x207fffff, 0,
        )
        self.store.connect_block(Block(header, transactions), 0)

        reordered = (coinbase, second, first)
        altered_header = BlockHeader(
            header.version, header.prev_hash,
            merkle_root(tx.txid for tx in reordered),
            header.timestamp, header.bits, header.nonce,
        )
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "UPDATE block_transactions SET position=3 WHERE height=0 AND position=1"
            )
            db.execute(
                "UPDATE block_transactions SET position=1 WHERE height=0 AND position=2"
            )
            db.execute(
                "UPDATE block_transactions SET position=2 WHERE height=0 AND position=3"
            )
            db.execute(
                "UPDATE block_transactions SET txid=?, raw_transaction=? "
                "WHERE height=0 AND position=1",
                (bytes.fromhex("ff" * 32), first.serialize()),
            )
            db.execute(
                "UPDATE block_transactions SET txid=?, raw_transaction=? "
                "WHERE height=0 AND position=2",
                (first.txid, first.serialize()),
            )
            db.execute(
                "UPDATE block_transactions SET txid=?, raw_transaction=? "
                "WHERE height=0 AND position=1",
                (second.txid, second.serialize()),
            )
            db.execute(
                "UPDATE blocks SET header=?, block_hash=? WHERE height=0",
                (altered_header.serialize(), altered_header.hash),
            )

        with self.assertRaisesRegex(RuntimeError, "not earlier in chain order"):
            self.store.verify_integrity()


    def test_reorganization_failure_restores_original_chain_and_utxos(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        def coinbase(height, tag):
            return Transaction(
                1,
                (TxInput(OutPoint(bytes(32), COINBASE_INDEX), bytes((tag, 1))),),
                (TxOutput(block_subsidy(height), b"miner-" + bytes((tag,))),),
            )

        def make_block(parent_hash, height, transactions, timestamp, nonce):
            all_transactions = (coinbase(height, nonce % 250 + 1),) + tuple(transactions)
            header = BlockHeader(
                1, parent_hash, merkle_root(tx.txid for tx in all_transactions),
                timestamp, 0x207fffff, nonce,
            )
            return Block(header, all_transactions)

        genesis = make_block(bytes(32), 0, (), 1, 1)
        old_tip = make_block(genesis.header.hash, 1, (), 2, 2)
        self.store.connect_block(genesis, 0)
        self.store.connect_block(old_tip, 1)
        original_output = OutPoint(old_tip.transactions[0].txid, 0)
        self.assertIsNotNone(self.store.get(original_output))
        original_count = self.store.count()

        replacement_one = make_block(genesis.header.hash, 1, (), 3, 3)
        missing_input = OutPoint(bytes.fromhex("ab" * 32), 0)
        invalid_spend = Transaction(
            1, (TxInput(missing_input),), (TxOutput(1, b"invalid"),)
        )
        replacement_two = make_block(
            replacement_one.header.hash, 2, (invalid_spend,), 4, 4
        )

        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.reorganize(
                (old_tip.header.hash,), (replacement_one, replacement_two)
            )

        self.assertEqual(self.store.tip(), (1, old_tip.header.hash))
        self.assertEqual(self.store.count(), original_count)
        self.assertIsNotNone(self.store.get(original_output))
        self.assertIsNone(
            self.store.get(OutPoint(replacement_one.transactions[0].txid, 0))
        )
        self.store.verify_integrity()


    def test_reorganization_rejects_missing_created_undo_without_mutation(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        def make_block(parent_hash, height, timestamp, nonce):
            coinbase = Transaction(
                1,
                (TxInput(OutPoint(bytes(32), COINBASE_INDEX), bytes((nonce, 1))),),
                (TxOutput(block_subsidy(height), b"undo-guard-miner"),),
            )
            header = BlockHeader(
                1, parent_hash, merkle_root((coinbase.txid,)),
                timestamp, 0x207fffff, nonce,
            )
            return Block(header, (coinbase,))

        genesis = make_block(bytes(32), 0, 1, 1)
        old_tip = make_block(genesis.header.hash, 1, 2, 2)
        self.store.connect_block(genesis, 0)
        self.store.connect_block(old_tip, 1)
        original_output = OutPoint(old_tip.transactions[0].txid, 0)
        original_tip = self.store.tip()
        original_count = self.store.count()

        replacement = make_block(genesis.header.hash, 1, 3, 3)
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "DELETE FROM block_undo_created WHERE height=1 AND txid=? AND output_index=0",
                (old_tip.transactions[0].txid,),
            )

        with self.assertRaisesRegex(RuntimeError, "undo-created records do not match"):
            self.store.reorganize((old_tip.header.hash,), (replacement,))

        self.assertEqual(self.store.tip(), original_tip)
        self.assertEqual(self.store.count(), original_count)
        self.assertIsNotNone(self.store.get(original_output))
        self.assertIsNone(
            self.store.get(OutPoint(replacement.transactions[0].txid, 0))
        )

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "INSERT INTO block_undo_created(height, txid, output_index) VALUES(1, ?, 0)",
                (old_tip.transactions[0].txid,),
            )
        self.store.verify_integrity()


    def test_reorganization_rejects_unrelated_spent_undo_record(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        def make_block(parent_hash, height, timestamp, nonce):
            coinbase = Transaction(
                1,
                (TxInput(OutPoint(bytes(32), COINBASE_INDEX), bytes((nonce, 1))),),
                (TxOutput(block_subsidy(height), b"spent-undo-guard"),),
            )
            header = BlockHeader(
                1, parent_hash, merkle_root((coinbase.txid,)),
                timestamp, 0x207fffff, nonce,
            )
            return Block(header, (coinbase,))

        genesis = make_block(bytes(32), 0, 1, 1)
        old_tip = make_block(genesis.header.hash, 1, 2, 2)
        self.store.connect_block(genesis, 0)
        self.store.connect_block(old_tip, 1)
        replacement = make_block(genesis.header.hash, 1, 3, 3)
        before_tip = self.store.tip()
        before_count = self.store.count()

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "INSERT INTO block_undo_spent(height, txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) "
                "VALUES(1, ?, 0, 1, ?, 0, 0, NULL)",
                (bytes.fromhex("de" * 32), b"forged"),
            )

        with self.assertRaisesRegex(RuntimeError, "undo-spent records do not match"):
            self.store.reorganize((old_tip.header.hash,), (replacement,))

        self.assertEqual(self.store.tip(), before_tip)
        self.assertEqual(self.store.count(), before_count)
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "DELETE FROM block_undo_spent WHERE height=1 AND txid=? AND output_index=0",
                (bytes.fromhex("de" * 32),),
            )
        self.store.verify_integrity()


    def test_reorganization_rejects_missing_known_spent_undo_without_mutation(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_script import _hash160, _push, legacy_sighash_all, p2pkh_script, N
        from src.blackroot_transactions import merkle_root

        private_key = ec.derive_private_key(23, ec.SECP256K1())
        pubkey = private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        )
        locking_script = p2pkh_script(_hash160(pubkey))
        funding = OutPoint(bytes.fromhex("64" * 32), 0)
        self.store.add_genesis_output(funding, TxOutput(900, locking_script))

        def signed_spend(previous, amount):
            unsigned = Transaction(1, (TxInput(previous),), (TxOutput(amount, locking_script),))
            digest = legacy_sighash_all(unsigned, 0, locking_script)
            der = private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            r_value, s_value = utils.decode_dss_signature(der)
            if s_value > N // 2:
                s_value = N - s_value
            signature = utils.encode_dss_signature(r_value, s_value) + b"\\x01"
            return Transaction(
                1, (TxInput(previous, _push(signature) + _push(pubkey)),), unsigned.outputs
            )

        def make_block(previous_hash, height, transactions, nonce):
            fee = 100 if height == 1 else 10 if height == 2 else 0
            coinbase = Transaction(
                1,
                (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
                (TxOutput(block_subsidy(height) + fee, b"miner"),),
            )
            all_transactions = (coinbase,) + tuple(transactions)
            header = BlockHeader(
                1, previous_hash, merkle_root(tx.txid for tx in all_transactions),
                height + 1, 0x207fffff, nonce,
            )
            return Block(header, all_transactions)

        genesis = make_block(bytes(32), 0, (), 1)
        self.store.connect_block(genesis, 0)
        first_spend = signed_spend(funding, 800)
        block_one = make_block(genesis.header.hash, 1, (first_spend,), 2)
        self.store.connect_block(block_one, 1)
        second_spend = signed_spend(OutPoint(first_spend.txid, 0), 790)
        block_two = make_block(block_one.header.hash, 2, (second_spend,), 3)
        self.store.connect_block(block_two, 2)

        before_tip = self.store.tip()
        before_count = self.store.count()
        restored_output = OutPoint(first_spend.txid, 0)
        self.assertIsNone(self.store.get(restored_output))
        with _managed_sqlite(self.db_path) as db:
            original = db.execute(
                "SELECT value, script_pubkey, created_height, is_coinbase, created_mtp "
                "FROM block_undo_spent WHERE height=2 AND txid=? AND output_index=0",
                (first_spend.txid,),
            ).fetchone()
            self.assertIsNotNone(original)
            db.execute(
                "DELETE FROM block_undo_spent WHERE height=2 AND txid=? AND output_index=0",
                (first_spend.txid,),
            )

        replacement = make_block(block_one.header.hash, 2, (), 4)
        with self.assertRaisesRegex(RuntimeError, "missing known historical inputs"):
            self.store.reorganize((block_two.header.hash,), (replacement,))

        self.assertEqual(self.store.tip(), before_tip)
        self.assertEqual(self.store.count(), before_count)
        self.assertIsNone(self.store.get(restored_output))
        self.assertIsNone(self.store.get(OutPoint(replacement.transactions[0].txid, 0)))

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "INSERT INTO block_undo_spent(height, txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) "
                "VALUES(2, ?, 0, ?, ?, ?, ?, ?)",
                (first_spend.txid, *original),
            )
        self.store.verify_integrity()


    def test_integrity_dependency_audit_rejects_cross_block_forward_reference(self):
        from src.blackroot_utxo_db import _validate_active_transaction_order

        source = Transaction(
            1, (TxInput(OutPoint(bytes.fromhex("71" * 32), 0)),),
            (TxOutput(500, b"source"),),
        )
        spender = Transaction(
            1, (TxInput(OutPoint(source.txid, 0)),),
            (TxOutput(400, b"spender"),),
        )

        # The spending transaction is in an earlier block than its source.
        with self.assertRaisesRegex(RuntimeError, "not earlier in chain order"):
            _validate_active_transaction_order({
                spender.txid: (4, 1, spender),
                source.txid: (5, 1, source),
            })

        # The same dependency is valid when the source is in an earlier block.
        _validate_active_transaction_order({
            source.txid: (4, 1, source),
            spender.txid: (5, 1, spender),
        })


    def test_disconnect_tip_rejects_invalid_active_transaction_order_without_mutation(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"disconnect-order-guard"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        block = Block(header, (coinbase,))
        self.store.connect_block(block, 0)
        before_tip = self.store.tip()
        before_count = self.store.count()
        before_output = self.store.get(OutPoint(coinbase.txid, 0))

        with patch(
            "src.blackroot_utxo_db._validate_active_transaction_order",
            side_effect=RuntimeError("forward reference"),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid active transaction order"):
                self.store.disconnect_tip(block.header.hash)

        self.assertEqual(self.store.tip(), before_tip)
        self.assertEqual(self.store.count(), before_count)
        self.assertEqual(self.store.get(OutPoint(coinbase.txid, 0)), before_output)


    def test_disconnect_tip_rejects_missing_transaction_and_matching_undo_without_mutation(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_script import _hash160, _push, legacy_sighash_all, p2pkh_script
        from src.blackroot_transactions import merkle_root

        private_key = ec.derive_private_key(11, ec.SECP256K1())
        pubkey = private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        )
        funding = OutPoint(bytes.fromhex("51" * 32), 0)
        funding_output = TxOutput(900, p2pkh_script(_hash160(pubkey)))
        self.store.add_genesis_output(funding, funding_output)

        genesis_coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"disconnect-count-genesis"),),
        )
        genesis_header = BlockHeader(
            1, bytes(32), merkle_root((genesis_coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        genesis = Block(genesis_header, (genesis_coinbase,))
        self.store.connect_block(genesis, 0)

        unsigned_spend = Transaction(
            1, (TxInput(funding),), (TxOutput(800, b"disconnect-count-recipient"),)
        )
        digest = legacy_sighash_all(unsigned_spend, 0, funding_output.script_pubkey)
        der_signature = private_key.sign(
            digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))
        )
        r_value, s_value = utils.decode_dss_signature(der_signature)
        from src.blackroot_script import N
        if s_value > N // 2:
            s_value = N - s_value
        signature = utils.encode_dss_signature(r_value, s_value) + b"\\x01"
        spend = Transaction(
            1,
            (TxInput(funding, _push(signature) + _push(pubkey)),),
            unsigned_spend.outputs,
        )
        next_coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x02"),),
            (TxOutput(block_subsidy(1) + 100, b"disconnect-count-miner"),),
        )
        next_header = BlockHeader(
            1, genesis.header.hash, merkle_root((next_coinbase.txid, spend.txid)),
            2, 0x207fffff, 0,
        )
        next_block = Block(next_header, (next_coinbase, spend))
        self.store.connect_block(next_block, 1)

        before_tip = self.store.tip()
        before_count = self.store.count()
        spend_output = OutPoint(spend.txid, 0)
        before_spend_output = self.store.get(spend_output)
        self.assertIsNotNone(before_spend_output)

        # Simulate coordinated corruption: remove the body row and all inverse
        # records associated with that transaction, leaving block.tx_count intact.
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "DELETE FROM block_transactions WHERE height=1 AND position=1"
            )
            db.execute(
                "DELETE FROM block_undo_created WHERE height=1 AND txid=?",
                (spend.txid,),
            )
            db.execute(
                "DELETE FROM block_undo_spent WHERE height=1 AND txid=? AND output_index=?",
                (funding.txid, funding.index),
            )

        with self.assertRaisesRegex(RuntimeError, "transaction count does not match"):
            self.store.disconnect_tip(next_block.header.hash)

        self.assertEqual(self.store.tip(), before_tip)
        self.assertEqual(self.store.count(), before_count)
        self.assertEqual(self.store.get(spend_output), before_spend_output)


    def test_disconnect_tip_rejects_missing_created_undo_without_mutation(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"disconnect-guard"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        block = Block(header, (coinbase,))
        self.store.connect_block(block, 0)
        before_tip = self.store.tip()
        before_count = self.store.count()
        coinbase_output = OutPoint(coinbase.txid, 0)
        self.assertIsNotNone(self.store.get(coinbase_output))

        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "DELETE FROM block_undo_created WHERE height=0 AND txid=? AND output_index=0",
                (coinbase.txid,),
            )

        with self.assertRaisesRegex(RuntimeError, "undo-created records do not match"):
            self.store.disconnect_tip(block.header.hash)

        self.assertEqual(self.store.tip(), before_tip)
        self.assertEqual(self.store.count(), before_count)
        self.assertIsNotNone(self.store.get(coinbase_output))


    def test_disconnect_tip_rejects_unrelated_spent_undo_without_mutation(self):
        from src.blackroot_blocks import Block, COINBASE_INDEX
        from src.blackroot_chain import BlockHeader
        from src.blackroot_consensus import block_subsidy
        from src.blackroot_transactions import merkle_root

        coinbase = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"disconnect-spent-guard"),),
        )
        header = BlockHeader(
            1, bytes(32), merkle_root((coinbase.txid,)),
            1, 0x207fffff, 0,
        )
        block = Block(header, (coinbase,))
        self.store.connect_block(block, 0)
        before_tip = self.store.tip()
        before_count = self.store.count()
        with _managed_sqlite(self.db_path) as db:
            db.execute(
                "INSERT INTO block_undo_spent(height, txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp) "
                "VALUES(0, ?, 0, 1, ?, 0, 0, NULL)",
                (bytes.fromhex("dc" * 32), b"forged-disconnect"),
            )

        with self.assertRaisesRegex(RuntimeError, "undo-spent records do not match"):
            self.store.disconnect_tip(block.header.hash)

        self.assertEqual(self.store.tip(), before_tip)
        self.assertEqual(self.store.count(), before_count)
        self.assertIsNotNone(self.store.get(OutPoint(coinbase.txid, 0)))


if __name__ == "__main__":
    unittest.main()
