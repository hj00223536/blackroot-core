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

if mode in ("reorg_during_transaction", "reorg_after_commit"):
    state.connect_best_block(genesis, 0)
    old = make_block(genesis.header.hash, 1, 2)
    state.add_header(old.header, adjusted_time=2)
    state.connect_best_block(old, 1)
    side_one = make_block(genesis.header.hash, 1, 3)
    state.add_header(side_one.header, adjusted_time=3)
    side_two = make_block(side_one.header.hash, 2, 4)
    state.add_header(side_two.header, adjusted_time=4)
    replacements = {side_one.header.hash: side_one, side_two.header.hash: side_two}
    if mode == "reorg_during_transaction":
        original = state.recovery_journal.reconcile
        def crash_after_reorg_writes(observed_tip):
            original(observed_tip)
            os._exit(77)
        state.recovery_journal.reconcile = crash_after_reorg_writes
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
