"""Subprocess termination tests for the persistent node recovery journal.

These tests terminate a child process at deterministic protocol checkpoints.
They exercise process-crash recovery, not physical power-loss or storage-device
failure guarantees.
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
state = PersistentNodeState(root / "headers.sqlite", root / "utxos.sqlite", limit, genesis.header, adjusted_time_provider=lambda: 1_000_000)
candidate = make_block(genesis.header.hash, 1, 2)
state.add_header(candidate.header)
state.utxos.store_block_body(candidate)
old_tip = state.utxos.tip()
new_tip = (1, candidate.header.hash)
state.recovery_journal.prepare(old_tip, new_tip)

if mode == "after_prepare":
    os._exit(73)

if mode == "after_utxo_commit":
    state.utxos.connect_validated_block(candidate, 1, state.headers.chain)
    os._exit(74)

raise RuntimeError("unknown crash mode")
"""


def mine_header(previous, merkle, timestamp):
    for nonce in range(10_000):
        header = BlockHeader(1, previous, merkle, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("nonce search exhausted")


def make_genesis():
    tx = Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX),
                 script_sig=bytes([1, 1])),),
        (TxOutput(block_subsidy(0), b"miner"),),
    )
    return Block(mine_header(ZERO_HASH, merkle_root([tx.txid]), 1), (tx,))


class RecoveryJournalProcessCrashTests(unittest.TestCase):
    def run_crash_case(self, mode, expected_exit):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            genesis = make_genesis()
            initial = PersistentNodeState(root / "headers.sqlite", root / "utxos.sqlite",
                POW_LIMIT, genesis.header, adjusted_time_provider=lambda: 1_000_000)
            initial.connect_best_block(genesis, 0)

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

            reopened = PersistentNodeState(root / "headers.sqlite", root / "utxos.sqlite",
                POW_LIMIT, genesis.header, adjusted_time_provider=lambda: 1_000_000)
            self.assertFalse(reopened.recovery_journal.pending())
            return reopened.utxos.tip(), reopened.headers.chain.best_hash

    def test_child_process_exit_after_intent_before_utxo_commit(self):
        tip, best_header = self.run_crash_case("after_prepare", 73)
        self.assertEqual(tip[0], 0)
        self.assertEqual(tip[1], make_genesis().header.hash)
        self.assertNotEqual(best_header, tip[1])

    def test_child_process_exit_after_utxo_commit_before_journal_reconcile(self):
        tip, best_header = self.run_crash_case("after_utxo_commit", 74)
        self.assertEqual(tip, (1, best_header))


if __name__ == "__main__":
    unittest.main()
