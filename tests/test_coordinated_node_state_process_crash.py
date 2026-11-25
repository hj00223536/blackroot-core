"""Process-exit checks for the opt-in single-database node transaction.

These cover process termination at SQLite transaction boundaries, not physical
power loss or storage-device failure.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_node_state import PersistentNodeState
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)

CHILD = r"""
import os
import sys
from pathlib import Path
from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_node_state import PersistentNodeState
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root

root = Path(sys.argv[1])
mode = sys.argv[2]
bits = 0x207FFFFF
limit = decode_compact_target(bits)

def mine(previous, merkle, timestamp):
    for nonce in range(10000):
        header = BlockHeader(1, previous, merkle, timestamp, bits, nonce)
        if check_proof_of_work(header.serialize(), bits, limit):
            return header
    raise RuntimeError("nonce search exhausted")

def make_block(previous, height, timestamp):
    tx = Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, 0xFFFFFFFF),
                 script_sig=bytes([height + 1, timestamp])),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )
    return Block(mine(previous, merkle_root([tx.txid]), timestamp), (tx,))

genesis = make_block(bytes(32), 0, 1)
state = PersistentNodeState.open_coordinated(root / "node.sqlite", limit, genesis.header)
candidate = make_block(genesis.header.hash, 1, 2)
if mode in ("during_transaction", "after_commit"):
    state.add_header(candidate.header, adjusted_time=2)

if mode in ("reorg_during_transaction", "reorg_after_commit", "reorg_crash_with_waiter"):
    state.connect_best_block(genesis, 0)
    old = make_block(genesis.header.hash, 1, 2)
    state.add_header(old.header, adjusted_time=2)
    state.connect_best_block(old, 1)
    side_one = make_block(genesis.header.hash, 1, 3)
    state.add_header(side_one.header, adjusted_time=3)
    side_two = make_block(side_one.header.hash, 2, 4)
    state.add_header(side_two.header, adjusted_time=4)
    replacements = {side_one.header.hash: side_one, side_two.header.hash: side_two}
    if mode == "reorg_after_intent":
        original_prepare = state.recovery_journal.prepare
        def crash_after_intent(old_tip, new_tip):
            original_prepare(old_tip, new_tip)
            os._exit(80)
        state.recovery_journal.prepare = crash_after_intent
        state.reorganize_best(replacements)
    elif mode == "reorg_during_transaction":
        original = state.recovery_journal.reconcile
        def crash_after_reorg_writes(observed_tip):
            original(observed_tip)
            os._exit(77)
        state.recovery_journal.reconcile = crash_after_reorg_writes
        state.reorganize_best(replacements)
    elif mode == "reorg_crash_with_waiter":
        # Archive candidate bodies in their own committed operations so the
        # waiting process can retry the same best-chain switch after rollback.
        state.archive_block_body(side_one)
        state.archive_block_body(side_two)
        marker, release = Path(sys.argv[3]), Path(sys.argv[4])
        original = state.recovery_journal.reconcile
        def pause_after_reorg_writes(observed_tip):
            original(observed_tip)
            marker.write_text("transaction has applied reorg writes")
            deadline = __import__("time").monotonic() + 20
            while not release.exists():
                if __import__("time").monotonic() >= deadline:
                    raise RuntimeError("crash coordination timed out")
                __import__("time").sleep(0.01)
            os._exit(79)
        state.recovery_journal.reconcile = pause_after_reorg_writes
        state.reorganize_best(replacements)
    else:
        state.reorganize_best(replacements)
        os._exit(78)
elif mode == "during_transaction":
    original = state.recovery_journal.reconcile
    def crash_after_writes(observed_tip):
        original(observed_tip)
        os._exit(75)
    state.recovery_journal.reconcile = crash_after_writes
    state.connect_best_block(candidate, 1)
elif mode == "after_commit":
    state.connect_best_block(candidate, 1)
    os._exit(76)
else:
    raise RuntimeError("unknown crash mode")
"""


def mine_header(previous, merkle, timestamp):
    for nonce in range(10_000):
        header = BlockHeader(1, previous, merkle, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("nonce search exhausted")


def make_block(previous, height, timestamp):
    tx = Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX),
                 script_sig=bytes([height + 1, timestamp])),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )
    header = mine_header(previous, merkle_root([tx.txid]), timestamp)
    return Block(header, (tx,))


class CoordinatedNodeStateProcessCrashTests(unittest.TestCase):
    def run_case(self, mode, expected_exit):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            genesis = make_block(ZERO_HASH, 0, 1)
            initial = PersistentNodeState.open_coordinated(
                root / "node.sqlite", POW_LIMIT, genesis.header
            )
            initial.connect_best_block(genesis, 0)
            initial.close()

            completed = subprocess.run(
                [sys.executable, "-c", CHILD, str(root), mode],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                completed.returncode, expected_exit,
                msg=f"child stdout={completed.stdout!r} stderr={completed.stderr!r}",
            )

            reopened = PersistentNodeState.open_coordinated(
                root / "node.sqlite", POW_LIMIT, genesis.header
            )
            try:
                candidate = make_block(genesis.header.hash, 1, 2)
                self.assertFalse(reopened.recovery_journal.pending())
                return (
                    reopened.utxos.tip(),
                    reopened.utxos.load_block_body(candidate.header.hash),
                    reopened.headers.chain.best_hash,
                    genesis.header.hash,
                    candidate.header.hash,
                )
            finally:
                reopened.close()

    def test_process_exit_during_reorganization_rolls_back_whole_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            genesis = make_block(ZERO_HASH, 0, 1)
            completed = subprocess.run(
                [sys.executable, "-c", CHILD, str(root), "reorg_during_transaction"],
                cwd=Path(__file__).resolve().parents[1],
                check=False, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                completed.returncode, 77,
                msg=f"child stdout={completed.stdout!r} stderr={completed.stderr!r}",
            )
            reopened = PersistentNodeState.open_coordinated(
                root / "node.sqlite", POW_LIMIT, genesis.header
            )
            try:
                old = make_block(genesis.header.hash, 1, 2)
                side_one = make_block(genesis.header.hash, 1, 3)
                side_two = make_block(side_one.header.hash, 2, 4)
                self.assertEqual(reopened.utxos.tip(), (1, old.header.hash))
                self.assertFalse(reopened.recovery_journal.pending())
                self.assertEqual(reopened.headers.chain.best_hash, side_two.header.hash)
                self.assertIsNone(reopened.utxos.load_block_body(side_one.header.hash))
                self.assertIsNone(reopened.utxos.load_block_body(side_two.header.hash))
                reopened.utxos.verify_integrity()
            finally:
                reopened.close()

    def test_process_exit_after_recovery_intent_rolls_back_intent_and_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            genesis = make_block(ZERO_HASH, 0, 1)
            completed = subprocess.run(
                [sys.executable, "-c", CHILD, str(root), "reorg_after_intent"],
                cwd=Path(__file__).resolve().parents[1],
                check=False, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                completed.returncode, 80,
                msg=f"child stdout={completed.stdout!r} stderr={completed.stderr!r}",
            )
            reopened = PersistentNodeState.open_coordinated(
                root / "node.sqlite", POW_LIMIT, genesis.header
            )
            try:
                old = make_block(genesis.header.hash, 1, 2)
                side_one = make_block(genesis.header.hash, 1, 3)
                side_two = make_block(side_one.header.hash, 2, 4)
                self.assertEqual(reopened.utxos.tip(), (1, old.header.hash))
                self.assertEqual(reopened.headers.chain.best_hash, side_two.header.hash)
                self.assertFalse(reopened.recovery_journal.pending())
                self.assertIsNone(reopened.utxos.load_block_body(side_one.header.hash))
                self.assertIsNone(reopened.utxos.load_block_body(side_two.header.hash))
                reopened.utxos.verify_integrity()
            finally:
                reopened.close()

    def test_waiting_process_retries_reorganization_after_writer_crashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "writer-applied-reorg"
            release = root / "allow-writer-crash"
            first = subprocess.Popen(
                [sys.executable, "-c", CHILD, str(root), "reorg_crash_with_waiter",
                 str(marker), str(release)],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            second = None
            try:
                deadline = __import__("time").monotonic() + 20
                while not marker.exists():
                    if first.poll() is not None:
                        stdout, stderr = first.communicate()
                        self.fail(f"crashing writer exited early: {stdout!r} {stderr!r}")
                    if __import__("time").monotonic() >= deadline:
                        self.fail("first process did not reach the in-transaction crash point")
                    __import__("time").sleep(0.01)

                ready = root / "retry-process-ready"
                attempted = root / "retry-process-attempted"
                result = root / "retry-process-result"
                retry_worker = r"""
import sys
import time
import sqlite3
from pathlib import Path
from src.blackroot_chain import BlockHeader
from src.blackroot_consensus import decode_compact_target
from src.blackroot_node_state import PersistentNodeState
root, ready, attempted, result = map(Path, sys.argv[1:])
bits = 0x207FFFFF
# Reconstruct the deterministic genesis header used by the first process.
from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_consensus import block_subsidy, check_proof_of_work
genesis_tx = Transaction(1, (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), bytes([1, 1])),),
                         (TxOutput(block_subsidy(0), b"miner"),))
limit = decode_compact_target(bits)
for nonce in range(10000):
    genesis_header = BlockHeader(1, bytes(32), merkle_root([genesis_tx.txid]), 1, bits, nonce)
    if check_proof_of_work(genesis_header.serialize(), bits, limit):
        break
else:
    raise RuntimeError("genesis nonce search exhausted")
attempted.write_text("opening coordinated state while writer holds lock")
deadline = time.monotonic() + 25
while True:
    try:
        state = PersistentNodeState.open_coordinated(root / "node.sqlite", limit, genesis_header)
        break
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
            raise
        # Opening performs a short schema/integrity transaction. Retry a
        # transient lock until the crashed writer releases SQLite's lock.
        time.sleep(0.05)
ready.write_text("connected after writer rollback")
try:
    tip = state.reorganize_best()
    result.write_text(f"accepted:{tip[0]}:{tip[1].hex()}")
finally:
    state.close()
"""
                second = subprocess.Popen(
                    [sys.executable, "-c", retry_worker, str(root), str(ready),
                     str(attempted), str(result)],
                    cwd=Path(__file__).resolve().parents[1],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                while not attempted.exists():
                    if second.poll() is not None:
                        stdout, stderr = second.communicate()
                        self.fail(f"retry process exited before attempting reorganization: {stdout!r} {stderr!r}")
                    if __import__("time").monotonic() >= deadline:
                        self.fail("retry process did not attempt reorganization")
                    __import__("time").sleep(0.01)
                # The contender has attempted to open coordinated state while
                # the first process owns its uncommitted SQLite write transaction.
                # It retries the transient lock and proceeds after rollback.
                release.write_text("crash writer while contender retries SQLite open")
                self.assertEqual(first.wait(timeout=20), 79)
                self.assertEqual(second.wait(timeout=30), 0)
                self.assertTrue(result.read_text().startswith("accepted:2:"))
            finally:
                for process in (first, second):
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                        if process.stdout is not None:
                            process.stdout.close()
                        if process.stderr is not None:
                            process.stderr.close()

            # A fresh open must observe one complete branch and no pending intent.
            from src.blackroot_chain import BlockHeader
            from src.blackroot_consensus import decode_compact_target
            from src.blackroot_node_state import PersistentNodeState
            genesis = make_block(ZERO_HASH, 0, 1)
            reopened = PersistentNodeState.open_coordinated(
                root / "node.sqlite", POW_LIMIT, genesis.header
            )
            try:
                side_one = make_block(genesis.header.hash, 1, 3)
                side_two = make_block(side_one.header.hash, 2, 4)
                self.assertEqual(reopened.utxos.tip(), (2, side_two.header.hash))
                self.assertEqual(reopened.headers.chain.best_hash, side_two.header.hash)
                self.assertFalse(reopened.recovery_journal.pending())
                self.assertIsNotNone(reopened.utxos.load_block_body(side_one.header.hash))
                self.assertIsNotNone(reopened.utxos.load_block_body(side_two.header.hash))
                reopened.utxos.verify_integrity()
            finally:
                reopened.close()

    def test_process_exit_after_reorganization_commit_keeps_new_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            genesis = make_block(ZERO_HASH, 0, 1)
            completed = subprocess.run(
                [sys.executable, "-c", CHILD, str(root), "reorg_after_commit"],
                cwd=Path(__file__).resolve().parents[1],
                check=False, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                completed.returncode, 78,
                msg=f"child stdout={completed.stdout!r} stderr={completed.stderr!r}",
            )
            reopened = PersistentNodeState.open_coordinated(
                root / "node.sqlite", POW_LIMIT, genesis.header
            )
            try:
                side_one = make_block(genesis.header.hash, 1, 3)
                side_two = make_block(side_one.header.hash, 2, 4)
                self.assertEqual(reopened.utxos.tip(), (2, side_two.header.hash))
                self.assertFalse(reopened.recovery_journal.pending())
                self.assertEqual(reopened.headers.chain.best_hash, side_two.header.hash)
                self.assertIsNone(reopened.utxos.load_block_body(side_one.header.hash))
                self.assertIsNone(reopened.utxos.load_block_body(side_two.header.hash))
                reopened.utxos.verify_integrity()
            finally:
                reopened.close()

    def test_process_exit_inside_shared_transaction_restores_old_state(self):
        tip, body, best_hash, genesis_hash, candidate_hash = self.run_case(
            "during_transaction", 75
        )
        self.assertEqual(tip, (0, genesis_hash))
        self.assertIsNone(body)
        # Header acceptance is a preceding, separate committed operation.
        self.assertEqual(best_hash, candidate_hash)

    def test_process_exit_after_shared_commit_restores_new_state(self):
        tip, body, best_hash, genesis_hash, candidate_hash = self.run_case(
            "after_commit", 76
        )
        self.assertEqual(tip, (1, candidate_hash))
        self.assertIsNotNone(body)
        self.assertEqual(best_hash, candidate_hash)


if __name__ == "__main__":
    unittest.main()
