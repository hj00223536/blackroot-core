import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore

BITS = 0x207fffff
POW_LIMIT = decode_compact_target(BITS)


def coinbase(height):
    tag = height.to_bytes(2, "little")
    return Transaction(1, (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), tag),),
                       (TxOutput(block_subsidy(height), b"miner"),))


def mined_block(transactions, previous, timestamp):
    root = merkle_root([tx.txid for tx in transactions])
    for nonce in range(10000):
        header = BlockHeader(1, previous, root, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return Block(header, tuple(transactions))
    raise AssertionError("test nonce search exhausted")


class ValidatedConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = UTXOStore(Path(self.tmp.name) / "chain.sqlite")
        self.genesis = mined_block([coinbase(0)], bytes(32), 1)
        self.headers = HeaderChain(POW_LIMIT, self.genesis.header)

    def test_connects_only_header_selected_by_validated_best_chain(self):
        self.assertEqual(
            self.store.connect_validated_block(self.genesis, 0, self.headers), 0
        )
        child = mined_block([coinbase(1)], self.genesis.header.hash, 2)
        self.headers.add(child.header)
        self.assertEqual(self.store.connect_validated_block(child, 1, self.headers), 0)
        self.assertEqual(self.store.tip(), (1, child.header.hash))

    def test_rejects_header_not_in_validated_chain_without_mutation(self):
        impostor = mined_block([coinbase(0)], bytes(32), 3)
        with self.assertRaisesRegex(ValueError, "not the selected validated"):
            self.store.connect_validated_block(impostor, 0, self.headers)
        self.assertIsNone(self.store.tip())
        self.assertEqual(self.store.count(), 0)

    def test_rejects_nonconsecutive_validated_height(self):
        with self.assertRaisesRegex(ValueError, "genesis at height zero"):
            self.store.connect_validated_block(self.genesis, 1, self.headers)
        self.assertIsNone(self.store.tip())

    def test_rejects_wrong_header_chain_type(self):
        with self.assertRaisesRegex(TypeError, "header_chain"):
            self.store.connect_validated_block(self.genesis, 0, object())


if __name__ == "__main__":
    unittest.main()
