import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_node_state import PersistentNodeState
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore


BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine_header(prev_hash, merkle, timestamp):
    for nonce in range(10_000):
        header = BlockHeader(1, prev_hash, merkle, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("nonce search exhausted")


def coinbase(height):
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), script_sig=bytes([height + 1, 1])),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )


def make_block(previous, height, timestamp):
    tx = coinbase(height)
    header = mine_header(previous, merkle_root([tx.txid]), timestamp)
    return Block(header, (tx,))


class PersistentNodeStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.genesis_block = make_block(ZERO_HASH, 0, 1)

    def state(self):
        return PersistentNodeState(
            self.root / "headers.sqlite",
            self.root / "utxos.sqlite",
            POW_LIMIT,
            self.genesis_block.header,
        )

    def test_connects_and_recovers_matching_persistent_tip(self):
        state = self.state()
        self.assertEqual(state.connect_best_block(self.genesis_block, 0), 0)
        point = OutPoint(self.genesis_block.transactions[0].txid, 0)
        self.assertEqual(state.utxos.get(point), TxOutput(block_subsidy(0), b"miner"))

        reopened = self.state()
        self.assertEqual(reopened.utxos.tip(), (0, self.genesis_block.header.hash))
        self.assertEqual(reopened.headers.chain.node(self.genesis_block.header.hash).height, 0)

    def test_rejects_invalid_height_before_header_chain_comparison(self):
        state = self.state()
        for invalid_height in (True, -1, "0", 0.5):
            with self.subTest(height=invalid_height):
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    state.connect_best_block(self.genesis_block, invalid_height)
        self.assertIsNone(state.utxos.tip())

    def test_refuses_body_not_selected_by_persistent_headers(self):
        state = self.state()
        other = make_block(ZERO_HASH, 0, 2)
        with self.assertRaisesRegex(ValueError, "not selected"):
            state.connect_best_block(other, 0)
        self.assertIsNone(state.utxos.tip())

    def test_startup_fails_closed_when_utxo_tip_is_not_in_header_dag(self):
        other = make_block(ZERO_HASH, 0, 2)
        UTXOStore(self.root / "utxos.sqlite").connect_block(other, 0)
        with self.assertRaisesRegex(RuntimeError, "absent or inconsistent"):
            self.state()


if __name__ == "__main__":
    unittest.main()
