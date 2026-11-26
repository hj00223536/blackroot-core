import os
import sqlite3
from contextlib import contextmanager
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

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

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore
from src.blackroot_sqlite import SQLiteTransactionCoordinator
from src.blackroot_script import _mul, _hash160, p2pkh_script
from test_blocks import signed_spend

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def coinbase(height, timestamp):
    tag = height.to_bytes(2, "little") + timestamp.to_bytes(4, "little")
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), tag),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )


def mined_block(height, previous, timestamp):
    txs = (coinbase(height, timestamp),)
    root = merkle_root([tx.txid for tx in txs])
    for nonce in range(10000):
        header = BlockHeader(1, previous, root, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return Block(header, txs)
    raise AssertionError("test nonce search exhausted")


class UTXOReorganizationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = UTXOStore(Path(self.temp.name) / "chain.sqlite")
        self.genesis = mined_block(0, ZERO_HASH, 1)
        self.headers = HeaderChain(POW_LIMIT, self.genesis.header, adjusted_time_provider=lambda: 1_000_000)
        self.old_one = mined_block(1, self.genesis.header.hash, 2)
        self.headers.add(self.old_one.header)
        self.store.connect_validated_block(self.genesis, 0, self.headers)
        self.store.connect_validated_block(self.old_one, 1, self.headers)

        self.side_one = mined_block(1, self.genesis.header.hash, 3)
        self.headers.add_to_branch(self.side_one.header)
        self.side_two = mined_block(2, self.side_one.header.hash, 4)
        self.headers.add_to_branch(self.side_two.header)

    def test_concurrent_processes_archive_identical_block_body_once(self):
        path = Path(self.temp.name) / "concurrent-body-archive.sqlite"
        UTXOStore(path)  # Initialize schema before worker processes race.
        block = self.side_one
        barrier = Path(self.temp.name) / "release-archive-writers"
        results = [Path(self.temp.name) / ("archive-" + str(i) + ".result") for i in range(4)]
        worker = r'''\
import sys
import time
from pathlib import Path
from src.blackroot_blocks import Block
from src.blackroot_utxo_db import UTXOStore
db, raw, barrier, result = sys.argv[1:]
store = UTXOStore(db)
Path(result + ".ready").write_text("ready")
deadline = time.monotonic() + 15
while not Path(barrier).exists():
    if time.monotonic() >= deadline:
        raise SystemExit("archive barrier timeout")
    time.sleep(0.005)
stored = store.store_block_body(Block.deserialize(bytes.fromhex(raw)))
Path(result).write_text(stored.hex())
'''
        workers = []
        try:
            for result in results:
                workers.append(subprocess.Popen(
                    [sys.executable, "-c", worker, str(path), block.serialize().hex(), str(barrier), str(result)],
                    cwd=Path.cwd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ))
            ready = [Path(str(result) + ".ready") for result in results]
            deadline = time.monotonic() + 15
            while not all(item.exists() for item in ready):
                if time.monotonic() >= deadline:
                    self.fail("archive workers did not become ready")
                if any(process.poll() not in (None, 0) for process in workers):
                    self.fail("archive worker exited before barrier release")
                time.sleep(0.005)
            barrier.write_text("go")
            for process in workers:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, msg=f"{stdout!r} {stderr!r}")
        finally:
            for process in workers:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        self.assertEqual([bytes.fromhex(result.read_text()) for result in results], [block.header.hash] * 4)
        reopened = UTXOStore(path)
        archived = reopened.load_block_body(block.header.hash)
        self.assertEqual(archived.serialize(), block.serialize())
        with reopened._connection_scope() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM block_bodies").fetchone()[0], 1)
        reopened.verify_integrity()

    def test_conflicting_archived_body_for_same_header_fails_closed(self):
        path = Path(self.temp.name) / "conflicting-body-archive.sqlite"
        store = UTXOStore(path)
        block = self.side_one
        original = block.serialize()
        conflicting = original + b"\x00"
        with _managed_sqlite(store.path) as db:
            db.execute(
                "INSERT INTO block_bodies(block_hash, raw_block, serialized_size) VALUES(?, ?, ?)",
                (block.header.hash, conflicting, len(conflicting)),
            )
        with self.assertRaisesRegex(RuntimeError, "conflicting archived body"):
            store.store_block_body(block)
        with store._connection_scope() as db:
            row = db.execute(
                "SELECT raw_block, serialized_size FROM block_bodies WHERE block_hash=?",
                (block.header.hash,),
            ).fetchone()
        self.assertEqual(bytes(row[0]), conflicting)
        self.assertEqual(row[1], len(conflicting))
        with self.assertRaises((ValueError, RuntimeError)):
            store.load_block_body(block.header.hash)
        with self.assertRaisesRegex(RuntimeError, "archived block body is malformed"):
            store.verify_integrity()

    def test_verify_integrity_detects_corrupt_archived_body_metadata(self):
        self.store.store_block_body(self.side_one)
        with _managed_sqlite(self.store.path) as db:
            db.execute(
                "UPDATE block_bodies SET serialized_size=serialized_size + 1 WHERE block_hash=?",
                (self.side_one.header.hash,),
            )
        with self.assertRaisesRegex(RuntimeError, "size metadata is corrupt"):
            self.store.verify_integrity()

    def test_idempotent_archive_rejects_corrupt_size_metadata(self):
        path = Path(self.temp.name) / "corrupt-size-archive.sqlite"
        store = UTXOStore(path)
        block = self.side_one
        store.store_block_body(block)
        with _managed_sqlite(store.path) as db:
            db.execute(
                "UPDATE block_bodies SET serialized_size=serialized_size + 1 WHERE block_hash=?",
                (block.header.hash,),
            )
        with self.assertRaisesRegex(RuntimeError, "size metadata is corrupt"):
            store.store_block_body(block)
        with store._connection_scope() as db:
            raw, size = db.execute(
                "SELECT raw_block, serialized_size FROM block_bodies WHERE block_hash=?",
                (block.header.hash,),
            ).fetchone()
        self.assertEqual(bytes(raw), block.serialize())
        self.assertEqual(size, len(block.serialize()) + 1)
        with self.assertRaisesRegex(RuntimeError, "size metadata is corrupt"):
            store.load_block_body(block.header.hash)

    def test_archiving_same_block_body_is_idempotent(self):
        first = self.store.store_block_body(self.side_one)
        second = self.store.store_block_body(self.side_one)
        self.assertEqual(first, self.side_one.header.hash)
        self.assertEqual(second, first)
        loaded = self.store.load_block_body(first)
        self.assertEqual(loaded.serialize(), self.side_one.serialize())

    def test_duplicate_active_block_is_rejected_without_state_change(self):
        before_tip = self.store.tip()
        before_count = self.store.count()
        before_headers = self.store.active_block_headers()
        with self.assertRaisesRegex(ValueError, "directly extend stored tip"):
            self.store.connect_block(self.old_one, 1)
        self.assertEqual(self.store.tip(), before_tip)
        self.assertEqual(self.store.count(), before_count)
        self.assertEqual(self.store.active_block_headers(), before_headers)


    def test_concurrent_writers_cannot_connect_the_same_extension(self):
        path = Path(self.temp.name) / "concurrent-extension.sqlite"
        # Initialize and populate the database before workers race to open it;
        # this isolates the test to competing block-connection transactions,
        # rather than concurrent first-time schema/WAL initialization.
        setup_store = UTXOStore(path)
        setup_headers = HeaderChain(POW_LIMIT, self.genesis.header, adjusted_time_provider=lambda: 1_000_000)
        setup_headers.add(self.old_one.header)
        setup_store.connect_validated_block(self.genesis, 0, setup_headers)
        setup_store.connect_validated_block(self.old_one, 1, setup_headers)
        contender = mined_block(2, self.old_one.header.hash, 5)
        barrier = Path(self.temp.name) / "release-writers"
        ready_a = Path(self.temp.name) / "writer-a.ready"
        ready_b = Path(self.temp.name) / "writer-b.ready"
        result_a = Path(self.temp.name) / "writer-a.result"
        result_b = Path(self.temp.name) / "writer-b.result"
        worker = r"""
import sys
import time
from pathlib import Path
from src.blackroot_blocks import Block
from src.blackroot_utxo_db import UTXOStore

db, raw, barrier, ready, result = sys.argv[1:]
store = UTXOStore(db)
Path(ready).write_text("ready")
deadline = time.monotonic() + 15
while not Path(barrier).exists():
    if time.monotonic() >= deadline:
        raise SystemExit("barrier timeout")
    time.sleep(0.01)
try:
    store.connect_block(Block.deserialize(bytes.fromhex(raw)), 2)
    outcome = "accepted"
except ValueError:
    outcome = "rejected"
Path(result).write_text(outcome)
"""
        raw_block = contender.serialize().hex()
        processes = [
            subprocess.Popen(
                [
                    sys.executable, "-c", worker, str(path), raw_block,
                    str(barrier), str(ready_a), str(result_a),
                ],
                cwd=Path.cwd(),
            ),
            subprocess.Popen(
                [
                    sys.executable, "-c", worker, str(path), raw_block,
                    str(barrier), str(ready_b), str(result_b),
                ],
                cwd=Path.cwd(),
            ),
        ]
        try:
            deadline = time.monotonic() + 15
            while not (ready_a.exists() and ready_b.exists()):
                if time.monotonic() >= deadline:
                    self.fail("concurrent writers did not become ready")
                if any(process.poll() not in (None, 0) for process in processes):
                    self.fail("a concurrent writer exited before the barrier")
                time.sleep(0.01)
            barrier.write_text("go")
            for process in processes:
                self.assertEqual(process.wait(timeout=20), 0)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()

        outcomes = [result_a.read_text(), result_b.read_text()]
        self.assertCountEqual(outcomes, ["accepted", "rejected"])
        expected_tip = (2, contender.header.hash)
        final_store = UTXOStore(path)
        self.assertEqual(final_store.tip(), expected_tip)
        active = final_store.active_block_headers()
        self.assertEqual(len(active), 3)
        self.assertEqual(active[-1][:2], (2, contender.header.hash))
        final_store.verify_integrity()

    def test_reorganizes_utxo_store_when_header_chain_selects_equal_work_tie_break(self):
        # Rebuild a DAG containing only equal-work height-1 alternatives.
        # HeaderChain deterministically chooses the lexicographically smallest
        # raw hash; the persistent UTXO tip must follow that exact choice.
        headers = HeaderChain(
            POW_LIMIT,
            self.genesis.header,
            adjusted_time_provider=lambda: 1_000_000,
        )
        headers.add(self.old_one.header)
        self.store.store_block_body(self.old_one)

        candidates = []
        for timestamp in range(10, 30):
            candidate = mined_block(1, self.genesis.header.hash, timestamp)
            headers.add_to_branch(candidate.header)
            self.store.store_block_body(candidate)
            candidates.append(candidate)

        selected_hash = headers.best_hash
        self.assertNotEqual(selected_hash, self.old_one.header.hash)
        self.assertEqual(
            headers.node(selected_hash).chainwork,
            headers.node(self.old_one.header.hash).chainwork,
        )

        switched = self.store.reorganize_to_best(headers)
        self.assertEqual(switched, (1, selected_hash))
        self.assertEqual(self.store.tip(), switched)
        selected_block = next(
            block for block in candidates
            if block.header.hash == selected_hash
        )
        self.assertIsNotNone(
            self.store.get(OutPoint(selected_block.transactions[0].txid, 0))
        )
        self.store.verify_integrity()

    def test_reorganizes_utxo_store_to_greater_work_branch(self):
        self.assertEqual(self.headers.tip.hash, self.side_two.header.hash)
        tip = self.store.reorganize_to_best(
            self.headers,
            {
                self.side_one.header.hash: self.side_one,
                self.side_two.header.hash: self.side_two,
            },
        )
        self.assertEqual(tip, (2, self.side_two.header.hash))
        self.assertEqual(self.store.tip(), tip)
        side_output = OutPoint(self.side_two.transactions[0].txid, 0)
        with _managed_sqlite(self.store.path) as db:
            created_mtp = db.execute(
                "SELECT created_mtp FROM utxos WHERE txid=? AND output_index=?",
                (side_output.txid, side_output.index),
            ).fetchone()
        self.assertEqual(
            created_mtp,
            (self.headers.median_time_past(self.side_two.header.prev_hash),),
        )

    def test_reorganization_restores_spent_ordinary_output(self):
        path = Path(self.temp.name) / "ordinary-spend-reorg.sqlite"
        store = UTXOStore(path)
        genesis = mined_block(0, ZERO_HASH, 1)
        headers = HeaderChain(POW_LIMIT, genesis.header, adjusted_time_provider=lambda: 1_000_000)

        point = _mul(1)
        pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        funding = OutPoint(bytes.fromhex("a1" * 32), 0)
        previous_output = TxOutput(10_000, p2pkh_script(_hash160(pubkey)))
        store.add_genesis_output(funding, previous_output)
        store.connect_validated_block(genesis, 0, headers)

        recipient_script = p2pkh_script(_hash160(pubkey))
        spend = signed_spend(
            funding, previous_output, output_script=recipient_script
        )
        chained_outpoint = OutPoint(spend.txid, 0)
        chained_previous = TxOutput(9_000, recipient_script)
        chained_spend = signed_spend(
            chained_outpoint, chained_previous, output_script=b"final-recipient"
        )
        coinbase_tx = coinbase(1, 2)
        txs = (coinbase_tx, spend, chained_spend)
        root = merkle_root(tx.txid for tx in txs)
        old_one = None
        for nonce in range(10_000):
            header = BlockHeader(1, genesis.header.hash, root, 2, BITS, nonce)
            if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
                old_one = Block(header, txs)
                break
        self.assertIsNotNone(old_one)
        headers.add(old_one.header)
        store.connect_validated_block(old_one, 1, headers)

        self.assertIsNone(store.get(funding))
        recipient = OutPoint(spend.txid, 0)
        final_recipient = OutPoint(chained_spend.txid, 0)
        self.assertIsNone(store.get(recipient))
        self.assertEqual(
            store.get(final_recipient), TxOutput(9_000, b"final-recipient")
        )

        side_one = mined_block(1, genesis.header.hash, 3)
        side_two = mined_block(2, side_one.header.hash, 4)
        headers.add_to_branch(side_one.header)
        headers.add_to_branch(side_two.header)
        switched = store.reorganize_to_best(
            headers,
            {side_one.header.hash: side_one, side_two.header.hash: side_two},
        )
        self.assertEqual(switched, (2, side_two.header.hash))
        self.assertEqual(store.get(funding), previous_output)
        self.assertIsNone(store.get(recipient))
        self.assertIsNone(store.get(final_recipient))
        store.verify_integrity()

    def test_reorganization_back_to_old_branch_restores_exact_coinbase_utxo_state(self):
        side_tip_utxo = OutPoint(self.side_two.transactions[0].txid, 0)
        old_one_utxo = OutPoint(self.old_one.transactions[0].txid, 0)

        self.store.reorganize_to_best(
            self.headers,
            {
                self.side_one.header.hash: self.side_one,
                self.side_two.header.hash: self.side_two,
            },
        )
        self.assertIsNone(self.store.get(OutPoint(self.old_one.transactions[0].txid, 0)))
        self.assertIsNotNone(self.store.get(side_tip_utxo))

        old_two = mined_block(2, self.old_one.header.hash, 5)
        old_three = mined_block(3, old_two.header.hash, 6)
        self.headers.add_to_branch(old_two.header)
        self.headers.add_to_branch(old_three.header)
        old_tip_utxo = OutPoint(old_three.transactions[0].txid, 0)

        switched = self.store.reorganize_to_best(
            self.headers,
            {
                self.old_one.header.hash: self.old_one,
                old_two.header.hash: old_two,
                old_three.header.hash: old_three,
            },
        )
        self.assertEqual(switched, (3, old_three.header.hash))
        self.assertIsNone(self.store.get(side_tip_utxo))
        self.assertIsNotNone(self.store.get(old_tip_utxo))
        self.assertIsNotNone(self.store.get(old_one_utxo))
        self.assertEqual(self.store.tip(), switched)
        self.store.verify_integrity()

    def test_missing_replacement_body_leaves_active_database_unchanged(self):
        before = self.store.tip()
        with self.assertRaisesRegex(ValueError, "missing replacement block body"):
            self.store.reorganize_to_best(
                self.headers,
                {self.side_one.header.hash: self.side_one},
            )
        self.assertEqual(self.store.tip(), before)
        self.assertEqual(self.store.tip(), (1, self.old_one.header.hash))

    def test_reorganization_is_idempotent_after_switch(self):
        replacement = {
            self.side_one.header.hash: self.side_one,
            self.side_two.header.hash: self.side_two,
        }
        first = self.store.reorganize_to_best(self.headers, replacement)
        second = self.store.reorganize_to_best(self.headers, replacement)
        self.assertEqual(first, second)
        self.assertEqual(second, (2, self.side_two.header.hash))

    def test_coordinated_reorganization_commits_with_outer_transaction(self):
        path = Path(self.temp.name) / "coordinated-reorg.sqlite"
        active_headers = HeaderChain(POW_LIMIT, self.genesis.header, adjusted_time_provider=lambda: 1_000_000)
        active_headers.add(self.old_one.header)
        headers = HeaderChain(POW_LIMIT, self.genesis.header, adjusted_time_provider=lambda: 1_000_000)
        headers.add(self.old_one.header)
        headers.add_to_branch(self.side_one.header)
        headers.add_to_branch(self.side_two.header)
        with SQLiteTransactionCoordinator(path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                store.connect_validated_block(self.genesis, 0, active_headers)
                store.connect_validated_block(self.old_one, 1, active_headers)
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                tip = store.reorganize_to_best(
                    headers,
                    {self.side_one.header.hash: self.side_one,
                     self.side_two.header.hash: self.side_two},
                )
                self.assertEqual(tip, (2, self.side_two.header.hash))
        reopened = UTXOStore(path)
        self.assertEqual(reopened.tip(), (2, self.side_two.header.hash))

    def test_outer_rollback_reverts_entire_coordinated_reorganization(self):
        path = Path(self.temp.name) / "rollback-reorg.sqlite"
        active_headers = HeaderChain(POW_LIMIT, self.genesis.header, adjusted_time_provider=lambda: 1_000_000)
        active_headers.add(self.old_one.header)
        headers = HeaderChain(POW_LIMIT, self.genesis.header, adjusted_time_provider=lambda: 1_000_000)
        headers.add(self.old_one.header)
        headers.add_to_branch(self.side_one.header)
        headers.add_to_branch(self.side_two.header)
        with SQLiteTransactionCoordinator(path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                store.connect_validated_block(self.genesis, 0, active_headers)
                store.connect_validated_block(self.old_one, 1, active_headers)
            with self.assertRaisesRegex(RuntimeError, "abort coordinated reorg"):
                with coordinator.transaction() as connection:
                    store = UTXOStore(path, connection=connection)
                    store.reorganize_to_best(
                        headers,
                        {self.side_one.header.hash: self.side_one,
                         self.side_two.header.hash: self.side_two},
                    )
                    self.assertEqual(store.tip(), (2, self.side_two.header.hash))
                    raise RuntimeError("abort coordinated reorg")
        reopened = UTXOStore(path)
        self.assertEqual(reopened.tip(), (1, self.old_one.header.hash))

    def test_disconnect_tip_uses_coordinator_outer_transaction(self):
        path = Path(self.temp.name) / "coordinated-disconnect.sqlite"
        active_headers = HeaderChain(POW_LIMIT, self.genesis.header, adjusted_time_provider=lambda: 1_000_000)
        active_headers.add(self.old_one.header)
        with SQLiteTransactionCoordinator(path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                store.connect_validated_block(self.genesis, 0, active_headers)
                store.connect_validated_block(self.old_one, 1, active_headers)
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                self.assertEqual(
                    store.disconnect_tip(self.old_one.header.hash),
                    (1, self.old_one.header.hash),
                )
        reopened = UTXOStore(path)
        self.assertEqual(reopened.tip(), (0, self.genesis.header.hash))


if __name__ == "__main__":
    unittest.main()
