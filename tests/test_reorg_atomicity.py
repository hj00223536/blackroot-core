import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import (
    block_subsidy, check_proof_of_work, decode_compact_target,
)
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def coinbase(height, value=None):
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), height.to_bytes(2, "little")),),
        (TxOutput(block_subsidy(height) if value is None else value, b"miner"),),
    )


def mined_block(height, previous, timestamp, tx=None):
    transactions = (coinbase(height) if tx is None else tx,)
    root = merkle_root(item.txid for item in transactions)
    for nonce in range(10000):
        header = BlockHeader(1, previous, root, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return Block(header, transactions)
    raise AssertionError("nonce search exhausted")


class ReorganizationAtomicityTests(unittest.TestCase):
    def test_invalid_replacement_after_disconnect_and_valid_connect_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            store = UTXOStore(Path(directory) / "chain.sqlite")
            genesis = mined_block(0, ZERO_HASH, 1)
            chain = HeaderChain(POW_LIMIT, genesis.header)
            old = mined_block(1, genesis.header.hash, 2)
            chain.add(old.header)
            store.connect_validated_block(genesis, 0, chain)
            store.connect_validated_block(old, 1, chain)

            fork_one = mined_block(1, genesis.header.hash, 3)
            fork_two = mined_block(2, fork_one.header.hash, 4)
            chain.add_to_branch(fork_one.header)
            chain.add_to_branch(fork_two.header)

            invalid_coinbase = coinbase(3, block_subsidy(3) + 1)
            invalid_three = mined_block(
                3, fork_two.header.hash, 5, invalid_coinbase
            )
            chain.add_to_branch(invalid_three.header)
            for block in (fork_one, fork_two, invalid_three):
                store.store_block_body(block)

            original_tip = store.tip()
            original_headers = store.active_block_headers()
            with store._connection_scope() as db:
                original_utxos = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                    "FROM utxos ORDER BY txid, output_index"
                ).fetchall()

            with self.assertRaisesRegex(ValueError, "coinbase reward exceeds"):
                store.reorganize_to_best(chain)

            self.assertEqual(store.tip(), original_tip)
            self.assertEqual(store.active_block_headers(), original_headers)
            with store._connection_scope() as db:
                restored_utxos = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                    "FROM utxos ORDER BY txid, output_index"
                ).fetchall()
            self.assertEqual(restored_utxos, original_utxos)
            store.verify_integrity()


if __name__ == "__main__":
    unittest.main()
