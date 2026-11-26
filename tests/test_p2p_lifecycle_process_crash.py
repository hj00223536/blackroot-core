"""Process-crash coverage for P2P-triggered persistent-node reorganization."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_node_runtime import BITS, MAGIC, POW_LIMIT, genesis_block
from src.blackroot_blocks import Block
from src.blackroot_chain import BlockHeader
from src.blackroot_consensus import block_subsidy, check_proof_of_work
from src.blackroot_node_state import PersistentNodeState
from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_manager import PeerManager
from src.blackroot_transactions import (
    OutPoint, Transaction, TxInput, TxOutput, merkle_root,
)


def coinbase(height):
    return Transaction(
        1,
        (TxInput(
            OutPoint(bytes(32), 0xFFFFFFFF),
            height.to_bytes(2, "little"),
        ),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )


def mined(height, previous, timestamp):
    tx = coinbase(height)
    root = merkle_root([tx.txid])
    for nonce in range(10_000):
        header = BlockHeader(1, previous, root, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return Block(header, (tx,))
    raise AssertionError("nonce search exhausted")


class P2PLifecycleProcessCrashTests(unittest.TestCase):
    def test_runtime_lifecycle_adapter_recovers_after_process_exit_mid_reorg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            headers_path = root / "headers.sqlite"
            utxos_path = root / "utxos.sqlite"
            genesis = genesis_block()
            state = PersistentNodeState(
                headers_path, utxos_path, POW_LIMIT, genesis.header,
                adjusted_time_provider=lambda: 1_800_000_100,
            )
            state.connect_best_block(genesis, 0)
            old = mined(1, genesis.header.hash, 2)
            state.headers.chain.add(old.header)
            state.connect_best_block(old, 1)

            fork_one = mined(1, genesis.header.hash, 3)
            state.headers.chain.add_to_branch(fork_one.header)
            fork_two = mined(2, fork_one.header.hash, 4)
            state.headers.chain.add_to_branch(fork_two.header)
            state.persist_synced_headers(state.headers.chain)
            state.archive_block_body(fork_one)
            state.archive_block_body(fork_two)
            state.close()

            crash_script = r"""
import os, sys
from tests.test_node_runtime import MAGIC, POW_LIMIT
from src.blackroot_node_runtime import BlackrootNodeRuntime
from src.blackroot_node_state import PersistentNodeState
from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_manager import PeerManager
from src.blackroot_utxo_db import UTXOStore

root = sys.argv[1]
state = PersistentNodeState(
    root + "/headers.sqlite", root + "/utxos.sqlite",
    POW_LIMIT, __import__("tests.test_node_runtime", fromlist=["genesis_block"]).genesis_block().header,
    adjusted_time_provider=lambda: 1_800_000_100,
)
manager = PeerManager(
    magic=MAGIC,
    local_version=VersionMessage(1, 0, 1_800_000_000, 707, 0, "/blackroot:crash-test/"),
    max_peers=2, handshake_timeout=1, idle_timeout=2,
)
runtime = BlackrootNodeRuntime(
    state, manager, protocol_version=1, request_timeout=1,
    adjusted_time=state.headers.adjusted_time_provider,
)
original = UTXOStore._advance_provenance
def crash_after_provenance_step(block, parent, height, created_mtp):
    result = original(block, parent, height, created_mtp)
    os._exit(74)
UTXOStore._advance_provenance = staticmethod(crash_after_provenance_step)
runtime._sync_store.reorganize_to_best(state.headers.chain)
raise SystemExit("expected abrupt exit did not occur")
"""
            result = subprocess.run(
                [sys.executable, "-c", crash_script, str(root)],
                check=False,
            )
            self.assertEqual(result.returncode, 74)

            recovered = PersistentNodeState(
                headers_path, utxos_path, POW_LIMIT, genesis.header,
                adjusted_time_provider=lambda: 1_800_000_100,
            )
            try:
                # The SQLite UTXO transaction rolls back; startup reconciles the
                # durable recovery journal against the surviving old active tip.
                self.assertEqual(
                    recovered.utxos.tip(), (1, old.header.hash)
                )
                self.assertFalse(recovered.recovery_journal.pending())
                self.assertEqual(
                    recovered.headers.chain.tip.hash, fork_two.header.hash
                )
                recovered.utxos.verify_integrity()
            finally:
                recovered.close()


if __name__ == "__main__":
    unittest.main()
