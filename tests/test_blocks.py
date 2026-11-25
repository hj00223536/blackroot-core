import unittest

from src.blackroot_blocks import (
    Block, COINBASE_INDEX, ZERO_TXID, validate_block_transactions,
)
from src.blackroot_chain import BlockHeader
from src.blackroot_consensus import block_subsidy
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root


def make_coinbase(value, script=b"\x01\x01"):
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), script_sig=script),),
        (TxOutput(value, b"miner"),),
    )


def make_block(txs):
    return Block(
        BlockHeader(1, bytes(32), merkle_root([tx.txid for tx in txs]), 1, 0x207fffff, 0),
        tuple(txs),
    )


class BlockValidationTests(unittest.TestCase):
    def setUp(self):
        self.funding = OutPoint(bytes.fromhex("11" * 32), 0)
        self.parent = {self.funding: TxOutput(10_000, b"previous-script")}

    def test_valid_block_accounts_fees_and_subsidy(self):
        spend = Transaction(1, (TxInput(self.funding),), (TxOutput(9_000, b"pay"),))
        coinbase = make_coinbase(block_subsidy(1) + 1_000)
        result, fees = validate_block_transactions(make_block([coinbase, spend]), self.parent, 1)
        self.assertEqual(fees, 1_000)
        self.assertNotIn(self.funding, result)
        self.assertIn(OutPoint(spend.txid, 0), result)
        self.assertIn(OutPoint(coinbase.txid, 0), result)
        self.assertIn(self.funding, self.parent)  # parent snapshot remains untouched

    def test_rejects_missing_coinbase_first(self):
        spend = Transaction(1, (TxInput(self.funding),), (TxOutput(9_000, b"pay"),))
        with self.assertRaisesRegex(ValueError, "first transaction"):
            validate_block_transactions(make_block([spend]), self.parent, 1)

    def test_rejects_coinbase_overpayment(self):
        coinbase = make_coinbase(block_subsidy(1) + 1)
        with self.assertRaisesRegex(ValueError, "exceeds subsidy"):
            validate_block_transactions(make_block([coinbase]), self.parent, 1)

    def test_rejects_second_coinbase(self):
        with self.assertRaisesRegex(ValueError, "more than one"):
            validate_block_transactions(make_block([make_coinbase(1), make_coinbase(1)]), self.parent, 1)

    def test_rejects_wrong_merkle_root(self):
        coinbase = make_coinbase(1)
        wrong_header = BlockHeader(1, bytes(32), bytes(32), 1, 0x207fffff, 0)
        block = Block(wrong_header, (coinbase,))
        with self.assertRaisesRegex(ValueError, "merkle root"):
            validate_block_transactions(block, self.parent, 1)

    def test_rejects_coinbase_script_outside_bounds(self):
        coinbase = make_coinbase(1, b"x")
        with self.assertRaisesRegex(ValueError, "script_sig length"):
            validate_block_transactions(make_block([coinbase]), self.parent, 1)

    def test_rejects_invalid_height(self):
        coinbase = make_coinbase(1)
        with self.assertRaisesRegex(ValueError, "height"):
            validate_block_transactions(make_block([coinbase]), self.parent, -1)


if __name__ == "__main__":
    unittest.main()
