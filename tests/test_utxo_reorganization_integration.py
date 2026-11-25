import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore
from src.blackroot_sqlite import SQLiteTransactionCoordinator
from src.blackroot_script import _mul, _hash160, p2pkh_script
from test_blocks import signed_spend

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def coinbase(height, timestamp):
    tag = height.to_bytes(2, "little") + timestamp.to_bytes(4, "little")
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), tag),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )


def mined_block(height, previous, timestamp):
    txs = (coinbase(height, timestamp),)
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

    def test_archiving_same_block_body_is_idempotent(self):
        first = self.store.store_block_body(self.side_one)
        second = self.store.store_block_body(self.side_one)
        self.assertEqual(first, self.side_one.header.hash)
        self.assertEqual(second, first)
        loaded = self.store.load_block_body(first)
        self.assertEqual(loaded.serialize(), self.side_one.serialize())

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

    def test_reorganization_restores_spent_ordinary_output(self):
        path = Path(self.temp.name) / "ordinary-spend-reorg.sqlite"
        store = UTXOStore(path)
        genesis = mined_block(0, ZERO_HASH, 1)
        headers = HeaderChain(POW_LIMIT, genesis.header)

        point = _mul(1)
        pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        funding = OutPoint(bytes.fromhex("a1" * 32), 0)
        previous_output = TxOutput(10_000, p2pkh_script(_hash160(pubkey)))
        store.add_genesis_output(funding, previous_output)
        store.connect_validated_block(genesis, 0, headers)

        recipient_script = p2pkh_script(_hash160(pubkey))
        spend = signed_spend(
            funding, previous_output, output_script=recipient_script
        )
        chained_outpoint = OutPoint(spend.txid, 0)
        chained_previous = TxOutput(9_000, recipient_script)
        chained_spend = signed_spend(
            chained_outpoint, chained_previous, output_script=b"final-recipient"
        )
        coinbase_tx = coinbase(1, 2)
        txs = (coinbase_tx, spend, chained_spend)
        root = merkle_root(tx.txid for tx in txs)
        old_one = None
        for nonce in range(10_000):
            header = BlockHeader(1, genesis.header.hash, root, 2, BITS, nonce)
            if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
                old_one = Block(header, txs)
                break
        self.assertIsNotNone(old_one)
        headers.add(old_one.header)
        store.connect_validated_block(old_one, 1, headers)

        self.assertIsNone(store.get(funding))
        recipient = OutPoint(spend.txid, 0)
        final_recipient = OutPoint(chained_spend.txid, 0)
        self.assertIsNone(store.get(recipient))
        self.assertEqual(
            store.get(final_recipient), TxOutput(9_000, b"final-recipient")
        )

        side_one = mined_block(1, genesis.header.hash, 3)
        side_two = mined_block(2, side_one.header.hash, 4)
        headers.add_to_branch(side_one.header)
        headers.add_to_branch(side_two.header)
        switched = store.reorganize_to_best(
            headers,
            {side_one.header.hash: side_one, side_two.header.hash: side_two},
        )
        self.assertEqual(switched, (2, side_two.header.hash))
        self.assertEqual(store.get(funding), previous_output)
        self.assertIsNone(store.get(recipient))
        self.assertIsNone(store.get(final_recipient))
        store.verify_integrity()

    def test_reorganization_back_to_old_branch_restores_exact_coinbase_utxo_state(self):
        side_tip_utxo = OutPoint(self.side_two.transactions[0].txid, 0)
        old_one_utxo = OutPoint(self.old_one.transactions[0].txid, 0)

        self.store.reorganize_to_best(
            self.headers,
            {
                self.side_one.header.hash: self.side_one,
                self.side_two.header.hash: self.side_two,
            },
        )
        self.assertIsNone(self.store.get(OutPoint(self.old_one.transactions[0].txid, 0)))
        self.assertIsNotNone(self.store.get(side_tip_utxo))

        old_two = mined_block(2, self.old_one.header.hash, 5)
        old_three = mined_block(3, old_two.header.hash, 6)
        self.headers.add_to_branch(old_two.header)
        self.headers.add_to_branch(old_three.header)
        old_tip_utxo = OutPoint(old_three.transactions[0].txid, 0)

        switched = self.store.reorganize_to_best(
            self.headers,
            {
                self.old_one.header.hash: self.old_one,
                old_two.header.hash: old_two,
                old_three.header.hash: old_three,
            },
        )
        self.assertEqual(switched, (3, old_three.header.hash))
        self.assertIsNone(self.store.get(side_tip_utxo))
        self.assertIsNotNone(self.store.get(old_tip_utxo))
        self.assertIsNotNone(self.store.get(old_one_utxo))
        self.assertEqual(self.store.tip(), switched)
        self.store.verify_integrity()

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

    def test_coordinated_reorganization_commits_with_outer_transaction(self):
        path = Path(self.temp.name) / "coordinated-reorg.sqlite"
        active_headers = HeaderChain(POW_LIMIT, self.genesis.header)
        active_headers.add(self.old_one.header)
        headers = HeaderChain(POW_LIMIT, self.genesis.header)
        headers.add(self.old_one.header)
        headers.add_to_branch(self.side_one.header)
        headers.add_to_branch(self.side_two.header)
        with SQLiteTransactionCoordinator(path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                store.connect_validated_block(self.genesis, 0, active_headers)
                store.connect_validated_block(self.old_one, 1, active_headers)
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                tip = store.reorganize_to_best(
                    headers,
                    {self.side_one.header.hash: self.side_one,
                     self.side_two.header.hash: self.side_two},
                )
                self.assertEqual(tip, (2, self.side_two.header.hash))
        reopened = UTXOStore(path)
        self.assertEqual(reopened.tip(), (2, self.side_two.header.hash))

    def test_outer_rollback_reverts_entire_coordinated_reorganization(self):
        path = Path(self.temp.name) / "rollback-reorg.sqlite"
        active_headers = HeaderChain(POW_LIMIT, self.genesis.header)
        active_headers.add(self.old_one.header)
        headers = HeaderChain(POW_LIMIT, self.genesis.header)
        headers.add(self.old_one.header)
        headers.add_to_branch(self.side_one.header)
        headers.add_to_branch(self.side_two.header)
        with SQLiteTransactionCoordinator(path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                store.connect_validated_block(self.genesis, 0, active_headers)
                store.connect_validated_block(self.old_one, 1, active_headers)
            with self.assertRaisesRegex(RuntimeError, "abort coordinated reorg"):
                with coordinator.transaction() as connection:
                    store = UTXOStore(path, connection=connection)
                    store.reorganize_to_best(
                        headers,
                        {self.side_one.header.hash: self.side_one,
                         self.side_two.header.hash: self.side_two},
                    )
                    self.assertEqual(store.tip(), (2, self.side_two.header.hash))
                    raise RuntimeError("abort coordinated reorg")
        reopened = UTXOStore(path)
        self.assertEqual(reopened.tip(), (1, self.old_one.header.hash))

    def test_disconnect_tip_uses_coordinator_outer_transaction(self):
        path = Path(self.temp.name) / "coordinated-disconnect.sqlite"
        active_headers = HeaderChain(POW_LIMIT, self.genesis.header)
        active_headers.add(self.old_one.header)
        with SQLiteTransactionCoordinator(path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                store.connect_validated_block(self.genesis, 0, active_headers)
                store.connect_validated_block(self.old_one, 1, active_headers)
            with coordinator.transaction() as connection:
                store = UTXOStore(path, connection=connection)
                self.assertEqual(
                    store.disconnect_tip(self.old_one.header.hash),
                    (1, self.old_one.header.hash),
                )
        reopened = UTXOStore(path)
        self.assertEqual(reopened.tip(), (0, self.genesis.header.hash))


if __name__ == "__main__":
    unittest.main()
