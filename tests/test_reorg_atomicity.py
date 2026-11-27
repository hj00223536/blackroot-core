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
    if tx is None:
        transactions = (coinbase(height),)
    elif isinstance(tx, tuple):
        transactions = tx
    else:
        transactions = (tx,)
    if not transactions or not all(
        isinstance(item, Transaction) for item in transactions
    ):
        raise TypeError("tx must be a Transaction or a non-empty tuple of Transactions")
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
            chain = HeaderChain(POW_LIMIT, genesis.header, adjusted_time_provider=lambda: 1_000_000)
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


    def test_reorganization_rejects_noncontiguous_persisted_transaction_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = UTXOStore(Path(directory) / "chain.sqlite")
            genesis = mined_block(0, ZERO_HASH, 1)
            chain = HeaderChain(
                POW_LIMIT, genesis.header,
                adjusted_time_provider=lambda: 1_000_000,
            )
            old = mined_block(1, genesis.header.hash, 2)
            chain.add(old.header)
            store.connect_validated_block(genesis, 0, chain)
            store.connect_validated_block(old, 1, chain)

            fork_one = mined_block(1, genesis.header.hash, 3)
            fork_two = mined_block(2, fork_one.header.hash, 4)
            chain.add_to_branch(fork_one.header)
            chain.add_to_branch(fork_two.header)
            store.store_block_body(fork_one)
            store.store_block_body(fork_two)

            before_tip = store.tip()
            before_headers = store.active_block_headers()
            with store._connection_scope() as db:
                before_utxos = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                    "FROM utxos ORDER BY txid, output_index"
                ).fetchall()
            with store._connection_scope() as db:
                db.execute(
                    "UPDATE block_transactions SET position=position + 1 WHERE height=1"
                )

            with self.assertRaisesRegex(
                RuntimeError, "transaction positions are not contiguous"
            ):
                store.reorganize_to_best(chain)

            self.assertEqual(store.tip(), before_tip)
            self.assertEqual(store.active_block_headers(), before_headers)
            with store._connection_scope() as db:
                after_utxos = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                    "FROM utxos ORDER BY txid, output_index"
                ).fetchall()
            self.assertEqual(after_utxos, before_utxos)

    def test_invalid_p2pkh_signature_on_replacement_branch_rolls_back_all_state(self):
        from src.blackroot_script import _hash160, _push, p2pkh_script
        from src.blackroot_transactions import TxInput

        with tempfile.TemporaryDirectory() as directory:
            store = UTXOStore(Path(directory) / "chain.sqlite")
            # Derive the compressed secp256k1 public key with the same
            # maintained cryptography backend used by production verification.
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            private_key = ec.derive_private_key(7, ec.SECP256K1())
            pubkey = private_key.public_key().public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.CompressedPoint,
            )
            funding = OutPoint(bytes.fromhex("71" * 32), 0)
            funding_output = TxOutput(10_000, p2pkh_script(_hash160(pubkey)))
            store.add_genesis_output(funding, funding_output)

            genesis = mined_block(0, ZERO_HASH, 1)
            chain = HeaderChain(POW_LIMIT, genesis.header, adjusted_time_provider=lambda: 1_000_000)
            old = mined_block(1, genesis.header.hash, 2)
            chain.add(old.header)
            store.connect_validated_block(genesis, 0, chain)
            store.connect_validated_block(old, 1, chain)

            # Structurally valid DER + SIGHASH_ALL, but deliberately not a
            # valid ECDSA signature for this transaction and public key.
            signature = bytes.fromhex("300602010102010101")
            well_formed_script_sig = _push(signature) + _push(pubkey)
            corrupted = bytearray(well_formed_script_sig)
            corrupted[5] ^= 1
            unsigned = Transaction(
                1, (TxInput(funding),), (TxOutput(9_000, b"recipient"),)
            )
            invalid_spend = Transaction(
                1, (TxInput(funding, bytes(corrupted)),), unsigned.outputs
            )

            # First replacement block is valid and must be rolled back when
            # the later replacement block fails script authorization.
            fork_one = mined_block(1, genesis.header.hash, 3)
            fork_two = mined_block(
                2, fork_one.header.hash, 4,
                (coinbase(2), invalid_spend),
            )
            chain.add_to_branch(fork_one.header)
            chain.add_to_branch(fork_two.header)
            for block in (fork_one, fork_two):
                store.store_block_body(block)

            before_tip = store.tip()
            before_headers = store.active_block_headers()
            with store._connection_scope() as db:
                before_utxos = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                    "FROM utxos ORDER BY txid, output_index"
                ).fetchall()

            with self.assertRaisesRegex(ValueError, "script verification failed"):
                store.reorganize_to_best(chain)

            self.assertEqual(store.tip(), before_tip)
            self.assertEqual(store.active_block_headers(), before_headers)
            with store._connection_scope() as db:
                after_utxos = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                    "FROM utxos ORDER BY txid, output_index"
                ).fetchall()
            self.assertEqual(after_utxos, before_utxos)
            self.assertEqual(store.get(funding), funding_output)
            self.assertIsNone(store.get(OutPoint(invalid_spend.txid, 0)))
            self.assertEqual(store.load_block_body(fork_one.header.hash).serialize(), fork_one.serialize())
            self.assertEqual(store.load_block_body(fork_two.header.hash).serialize(), fork_two.serialize())
            store.verify_integrity()


    def test_successful_reorganization_state_survives_store_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "chain.sqlite"
            store = UTXOStore(database)
            genesis = mined_block(0, ZERO_HASH, 1)
            chain = HeaderChain(POW_LIMIT, genesis.header, adjusted_time_provider=lambda: 1_000_000)
            old = mined_block(1, genesis.header.hash, 2)
            chain.add(old.header)
            store.connect_validated_block(genesis, 0, chain)
            store.connect_validated_block(old, 1, chain)

            fork_one = mined_block(1, genesis.header.hash, 3)
            fork_two = mined_block(2, fork_one.header.hash, 4)
            chain.add_to_branch(fork_one.header)
            chain.add_to_branch(fork_two.header)
            for block in (fork_one, fork_two):
                store.store_block_body(block)

            expected_tip = store.reorganize_to_best(chain)
            self.assertEqual(expected_tip, (2, fork_two.header.hash))
            expected_headers = store.active_block_headers()
            with store._connection_scope() as db:
                expected_utxos = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                    "FROM utxos ORDER BY txid, output_index"
                ).fetchall()
                expected_blocks = db.execute(
                    "SELECT height, block_hash, prev_hash, header, tx_count, total_fees "
                    "FROM blocks ORDER BY height"
                ).fetchall()

            reopened = UTXOStore(database)
            self.assertEqual(reopened.tip(), expected_tip)
            self.assertEqual(reopened.active_block_headers(), expected_headers)
            with reopened._connection_scope() as db:
                self.assertEqual(
                    db.execute(
                        "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp "
                        "FROM utxos ORDER BY txid, output_index"
                    ).fetchall(),
                    expected_utxos,
                )
                self.assertEqual(
                    db.execute(
                        "SELECT height, block_hash, prev_hash, header, tx_count, total_fees "
                        "FROM blocks ORDER BY height"
                    ).fetchall(),
                    expected_blocks,
                )
            reopened.verify_integrity()


if __name__ == "__main__":
    unittest.main()
