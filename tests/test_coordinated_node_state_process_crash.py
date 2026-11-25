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
                 script_sig=bytes([height + 1, 1])),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )
    return Block(mine(previous, merkle_root([tx.txid]), timestamp), (tx,))

genesis = make_block(bytes(32), 0, 1)
state = PersistentNodeState.open_coordinated(root / "node.sqlite", limit, genesis.header)
candidate = make_block(genesis.header.hash, 1, 2)
state.add_header(candidate.header, adjusted_time=2)

if mode == "during_transaction":
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
                 script_sig=bytes([height + 1, 1])),),
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
