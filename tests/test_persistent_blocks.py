import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader
from src.blackroot_consensus import block_subsidy
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore


def coinbase(value, tag):
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), script_sig=tag),),
        (TxOutput(value, b"miner"),),
    )


def block_for(txs, previous=bytes(32), timestamp=1):
    header = BlockHeader(1, previous, merkle_root([tx.txid for tx in txs]),
                         timestamp, 0x207fffff, 0)
    return Block(header, tuple(txs))


class PersistentBlockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "chain.sqlite"
        self.store = UTXOStore(self.path)

    def test_connect_persists_block_and_utxos(self):
        cb = coinbase(block_subsidy(0), b"\x01\x01")
        block = block_for([cb])
        self.assertEqual(self.store.connect_block(block, 0), 0)
        self.assertEqual(self.store.tip(), (0, block.header.hash))
        point = OutPoint(cb.txid, 0)
        self.assertEqual(self.store.get(point), TxOutput(block_subsidy(0), b"miner"))
        reopened = UTXOStore(self.path)
        self.assertEqual(reopened.tip(), (0, block.header.hash))
        self.assertEqual(reopened.get(point), TxOutput(block_subsidy(0), b"miner"))

    def test_rejects_wrong_height_without_mutation(self):
        cb = coinbase(block_subsidy(0), b"\x01\x01")
        block = block_for([cb])
        with self.assertRaisesRegex(ValueError, "height zero"):
            self.store.connect_block(block, 1)
        self.assertIsNone(self.store.tip())
        self.assertEqual(self.store.count(), 0)

    def test_rejects_wrong_parent_without_mutation(self):
        first_cb = coinbase(block_subsidy(0), b"\x01\x01")
        first = block_for([first_cb])
        self.store.connect_block(first, 0)
        second_cb = coinbase(block_subsidy(1), b"\x01\x02")
        wrong = block_for([second_cb], previous=bytes.fromhex("22" * 32), timestamp=2)
        with self.assertRaisesRegex(ValueError, "does not extend"):
            self.store.connect_block(wrong, 1)
        self.assertEqual(self.store.tip(), (0, first.header.hash))

    def test_rejects_overpay_and_rolls_back_everything(self):
        cb = coinbase(block_subsidy(0) + 1, b"\x01\x01")
        block = block_for([cb])
        with self.assertRaisesRegex(ValueError, "exceeds subsidy"):
            self.store.connect_block(block, 0)
        self.assertIsNone(self.store.tip())
        self.assertEqual(self.store.count(), 0)


    def test_disconnect_tip_restores_spent_parent_utxo(self):
        genesis_cb = coinbase(block_subsidy(0), b"\x01\x01")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)
        genesis_output = OutPoint(genesis_cb.txid, 0)

        spend = Transaction(
            1,
            (TxInput(genesis_output),),
            (TxOutput(block_subsidy(0) - 100, b"recipient"),),
        )
        next_cb = coinbase(block_subsidy(1) + 100, b"\x01\x02")
        second = block_for([next_cb, spend], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(second, 1)
        self.assertIsNone(self.store.get(genesis_output))

        self.assertEqual(self.store.disconnect_tip(second.header.hash), (1, second.header.hash))
        self.assertEqual(self.store.tip(), (0, genesis.header.hash))
        self.assertEqual(self.store.get(genesis_output), TxOutput(block_subsidy(0), b"miner"))
        self.assertIsNone(self.store.get(OutPoint(next_cb.txid, 0)))
        self.assertIsNone(self.store.get(OutPoint(spend.txid, 0)))

    def test_disconnect_rejects_wrong_hash_without_mutation(self):
        cb = coinbase(block_subsidy(0), b"\x01\x01")
        block = block_for([cb])
        self.store.connect_block(block, 0)
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.store.disconnect_tip(bytes.fromhex("44" * 32))
        self.assertEqual(self.store.tip(), (0, block.header.hash))
        self.assertEqual(self.store.count(), 1)

    def test_disconnect_rejects_empty_chain(self):
        with self.assertRaisesRegex(ValueError, "empty chain"):
            self.store.disconnect_tip(bytes.fromhex("44" * 32))
        self.assertIsNone(self.store.tip())

    def test_disconnect_removes_genesis_and_undo_data(self):
        cb = coinbase(block_subsidy(0), b"\x01\x01")
        block = block_for([cb])
        self.store.connect_block(block, 0)
        self.store.disconnect_tip(block.header.hash)
        self.assertIsNone(self.store.tip())
        self.assertEqual(self.store.count(), 0)
        with self.store._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM block_undo_spent").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM block_undo_created").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
