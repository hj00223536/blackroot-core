import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def coinbase(height):
    tag = height.to_bytes(2, "little")
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), tag),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )


def mined_block(height, previous, timestamp):
    txs = (coinbase(height),)
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
        self.headers = HeaderChain(POW_LIMIT, self.genesis.header)
        self.old_one = mined_block(1, self.genesis.header.hash, 2)
        self.headers.add(self.old_one.header)
        self.store.connect_validated_block(self.genesis, 0, self.headers)
        self.store.connect_validated_block(self.old_one, 1, self.headers)

        self.side_one = mined_block(1, self.genesis.header.hash, 3)
        self.headers.add_to_branch(self.side_one.header)
        self.side_two = mined_block(2, self.side_one.header.hash, 4)
        self.headers.add_to_branch(self.side_two.header)

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


if __name__ == "__main__":
    unittest.main()
