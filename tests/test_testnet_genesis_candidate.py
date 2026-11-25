import unittest

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader
from src.blackroot_consensus import check_proof_of_work, decode_compact_target
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root


class TestnetGenesisCandidateVectorTests(unittest.TestCase):
    """Regression vector only; this does not activate a public network."""

    def test_candidate_genesis_transaction_and_header_vectors(self):
        coinbase = Transaction(
            1,
            (TxInput(
                OutPoint(ZERO_TXID, COINBASE_INDEX),
                script_sig=bytes.fromhex("0101"),
            ),),
            (TxOutput(0, bytes.fromhex("6a")),),
            0,
        )
        self.assertEqual(len(coinbase.serialize()), 63)
        self.assertEqual(
            coinbase.serialize().hex(),
            "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff020101ffffffff010000000000000000016a00000000",
        )
        self.assertEqual(
            coinbase.display_txid,
            "2ea49004101bc7a1b366021340f31f4d0c6abf24476a46723edd5530af3a9935",
        )

        header = BlockHeader(
            1,
            bytes(32),
            merkle_root([coinbase.txid]),
            1_795_564_800,
            0x207FFFFF,
            0,
        )
        self.assertEqual(
            header.serialize().hex(),
            "0100000000000000000000000000000000000000000000000000000000000000000000002ea49004101bc7a1b366021340f31f4d0c6abf24476a46723edd5530af3a99350025066bffff7f2000000000",
        )
        self.assertEqual(
            header.display_hash,
            "12d0a70715fcc771e2228e8a8e2f85b4ada2b1bf2991c2a564553c0b9c922269",
        )
        pow_limit = decode_compact_target(0x207FFFFF)
        self.assertTrue(check_proof_of_work(header.serialize(), 0x207FFFFF, pow_limit))

        block = Block(header, (coinbase,))
        self.assertEqual(Block.deserialize(block.serialize()), block)


if __name__ == "__main__":
    unittest.main()
