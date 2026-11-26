import sqlite3
from contextlib import contextmanager
import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_script import N, _mul, _hash160, _push, legacy_sighash_all, p2pkh_script
from src.blackroot_utxo_db import UTXOStore


@contextmanager
def managed_sqlite(path):
    """Commit test writes and always close the owned SQLite handle."""
    db = sqlite3.connect(path)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def coinbase(value, tag, script_pubkey=b'miner'):
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), script_sig=tag),),
        (TxOutput(value, script_pubkey),),
    )


def der_integer(value):
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big") or b"\x00"
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return b"\x02" + bytes([len(raw)]) + raw


def der_signature(r, s):
    body = der_integer(r) + der_integer(s)
    return b"\x30" + bytes([len(body)]) + body


def signed_spend(previous, previous_output, value, private_key=1):
    point = _mul(private_key)
    pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
    unsigned = Transaction(1, (TxInput(previous),), (TxOutput(value, b"recipient"),))
    digest = legacy_sighash_all(unsigned, 0, previous_output.script_pubkey)
    nonce = 2
    nonce_point = _mul(nonce)
    r = nonce_point[0] % N
    s = (pow(nonce, N - 2, N) *
         (int.from_bytes(digest, "big") + r * private_key)) % N
    if s > N // 2:
        s = N - s
    signature = der_signature(r, s) + b"\x01"
    return Transaction(1, (TxInput(previous, _push(signature) + _push(pubkey)),),
                       unsigned.outputs)


def block_for(txs, previous=bytes(32), timestamp=1):
    header = BlockHeader(1, previous, merkle_root([tx.txid for tx in txs]),
                         timestamp, 0x207fffff, 0)
    return Block(header, tuple(txs))


def mined_block_for(txs, previous=bytes(32), timestamp=1):
    root = merkle_root([tx.txid for tx in txs])
    bits = 0x207fffff
    limit = decode_compact_target(bits)
    for nonce in range(1000):
        header = BlockHeader(1, previous, root, timestamp, bits, nonce)
        if check_proof_of_work(header.serialize(), bits, limit):
            return Block(header, tuple(txs))
    raise AssertionError("test block nonce search unexpectedly exhausted")


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

    def test_block_body_archive_survives_reopen(self):
        block = block_for([coinbase(block_subsidy(0), b"\\x01\\x01")])
        block_hash = self.store.store_block_body(block)
        reopened = UTXOStore(self.path)
        self.assertEqual(block_hash, block.header.hash)
        self.assertEqual(reopened.load_block_body(block_hash), block)

    def test_block_body_archive_rejects_corrupt_serialized_size(self):
        block = block_for([coinbase(block_subsidy(0), b"\\x01\\x01")])
        block_hash = self.store.store_block_body(block)
        with managed_sqlite(self.path) as db:
            db.execute(
                "UPDATE block_bodies SET serialized_size=serialized_size+1 WHERE block_hash=?",
                (block_hash,),
            )
        with self.assertRaisesRegex(RuntimeError, "size metadata is corrupt"):
            self.store.load_block_body(block_hash)

    def test_block_body_archive_rejects_unknown_or_mismatched_header(self):
        block = block_for([coinbase(block_subsidy(0), b"\\x01\\x01")])
        self.assertIsNone(self.store.load_block_body(block.header.hash))
        wrong_hash = bytes.fromhex("99" * 32)
        self.store.store_block_body(block)
        with self.assertRaisesRegex(RuntimeError, "header hash does not match"):
            with managed_sqlite(self.path) as db:
                db.execute(
                    "UPDATE block_bodies SET block_hash=? WHERE block_hash=?",
                    (wrong_hash, block.header.hash),
                )
            self.store.load_block_body(wrong_hash)

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
        point = _mul(1)
        pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        locking_script = p2pkh_script(_hash160(pubkey))
        funding = OutPoint(bytes.fromhex("55" * 32), 0)
        previous_output = TxOutput(10_000, locking_script)
        self.store.add_genesis_output(funding, previous_output)

        genesis_cb = coinbase(block_subsidy(0), b"\x01\x01")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)

        spend = signed_spend(funding, previous_output, 9_900)
        next_cb = coinbase(block_subsidy(1) + 100, b"\x01\x02")
        second = block_for([next_cb, spend], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(second, 1)
        self.assertIsNone(self.store.get(funding))

        self.assertEqual(self.store.disconnect_tip(second.header.hash), (1, second.header.hash))
        self.assertEqual(self.store.tip(), (0, genesis.header.hash))
        self.assertEqual(self.store.get(funding), previous_output)
        self.assertIsNone(self.store.get(OutPoint(next_cb.txid, 0)))
        self.assertIsNone(self.store.get(OutPoint(spend.txid, 0)))


    def test_persistent_store_rejects_immature_coinbase_spend_and_persists_origin(self):
        point = _mul(1)
        pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        locking_script = p2pkh_script(_hash160(pubkey))
        genesis_cb = coinbase(0, b"\x00\x00")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)

        reward_cb = coinbase(block_subsidy(1), b"\x01\x01", locking_script)
        reward = block_for([reward_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(reward, 1)
        coinbase_point = OutPoint(reward_cb.txid, 0)
        reward_output = TxOutput(block_subsidy(1), locking_script)
        with self.store._connection_scope() as db:
            row = db.execute(
                "SELECT created_height, is_coinbase FROM utxos WHERE txid=? AND output_index=?",
                (coinbase_point.txid, coinbase_point.index),
            ).fetchone()
        self.assertEqual(row, (1, 1))
        reopened = UTXOStore(self.path)
        self.assertEqual(reopened.get(coinbase_point), reward_output)

        spend = signed_spend(coinbase_point, reward_output, block_subsidy(1) - 100)
        next_cb = coinbase(block_subsidy(2) + 100, b"\x02\x02")
        immature = block_for([next_cb, spend], previous=reward.header.hash, timestamp=3)
        with self.assertRaisesRegex(ValueError, "premature coinbase"):
            reopened.connect_block(immature, 2)
        self.assertEqual(reopened.tip(), (1, reward.header.hash))
        self.assertEqual(reopened.get(coinbase_point), reward_output)


    def test_persistent_store_accepts_coinbase_spend_at_height_101(self):
        point = _mul(1)
        pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        locking_script = p2pkh_script(_hash160(pubkey))
        genesis_cb = coinbase(0, b"\x00\x00")
        previous = block_for([genesis_cb], timestamp=1)
        self.store.connect_block(previous, 0)

        reward_cb = coinbase(block_subsidy(1), b"\x01\x00", locking_script)
        previous = block_for([reward_cb], previous=previous.header.hash, timestamp=2)
        self.store.connect_block(previous, 1)

        for height in range(2, 101):
            cb = coinbase(block_subsidy(height), bytes([height & 255, (height >> 8) & 255]))
            previous = block_for([cb], previous=previous.header.hash, timestamp=height + 1)
            self.store.connect_block(previous, height)

        reward_point = OutPoint(reward_cb.txid, 0)
        reward_output = TxOutput(block_subsidy(1), locking_script)
        spend = signed_spend(reward_point, reward_output, block_subsidy(1) - 100)
        final_cb = coinbase(block_subsidy(101) + 100, b"\x65\x00")
        final_block = block_for(
            [final_cb, spend], previous=previous.header.hash, timestamp=102
        )
        self.assertEqual(self.store.connect_block(final_block, 101), 100)
        self.assertIsNone(self.store.get(reward_point))
        final_point = OutPoint(final_cb.txid, 0)
        with self.store._connection_scope() as db:
            row = db.execute(
                "SELECT created_height, is_coinbase FROM utxos WHERE txid=? AND output_index=?",
                (final_point.txid, final_point.index),
            ).fetchone()
        self.assertEqual(row, (101, 1))

    def test_disconnect_rejects_wrong_hash_without_mutation(self):
        cb = coinbase(block_subsidy(0), b"\x01\x01")
        block = block_for([cb])
        self.store.connect_block(block, 0)
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.store.disconnect_tip(bytes.fromhex("44" * 32))
        self.assertEqual(self.store.tip(), (0, block.header.hash))
        self.assertEqual(self.store.count(), 1)

    def test_reorganize_atomically_replaces_tip_and_utxos(self):
        genesis_cb = coinbase(block_subsidy(0), b"\x01\x01")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)

        old_cb = coinbase(block_subsidy(1), b"\x01\x02")
        old_block = block_for([old_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(old_block, 1)

        replacement_cb = coinbase(block_subsidy(1), b"\x02\x02")
        replacement = block_for([replacement_cb], previous=genesis.header.hash, timestamp=3)
        self.assertEqual(
            self.store.reorganize((old_block.header.hash,), (replacement,)),
            (1, replacement.header.hash),
        )
        self.assertEqual(self.store.tip(), (1, replacement.header.hash))
        self.assertIsNone(self.store.get(OutPoint(old_cb.txid, 0)))
        self.assertEqual(
            self.store.get(OutPoint(replacement_cb.txid, 0)),
            TxOutput(block_subsidy(1), b"miner"),
        )
        self.assertEqual(
            self.store.get(OutPoint(genesis_cb.txid, 0)),
            TxOutput(block_subsidy(0), b"miner"),
        )

    def test_failed_reorganization_rolls_back_disconnect_and_connect(self):
        genesis_cb = coinbase(block_subsidy(0), b"\x01\x01")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)

        active_cb = coinbase(block_subsidy(1), b"\x01\x02")
        active = block_for([active_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(active, 1)

        invalid_cb = coinbase(block_subsidy(1) + 1, b"\x02\x02")
        invalid = block_for([invalid_cb], previous=genesis.header.hash, timestamp=3)
        with self.assertRaisesRegex(ValueError, "exceeds subsidy"):
            self.store.reorganize((active.header.hash,), (invalid,))

        self.assertEqual(self.store.tip(), (1, active.header.hash))
        self.assertEqual(
            self.store.get(OutPoint(active_cb.txid, 0)),
            TxOutput(block_subsidy(1), b"miner"),
        )
        self.assertIsNone(self.store.get(OutPoint(invalid_cb.txid, 0)))


    def test_reorganization_rejects_immature_coinbase_spend_and_rolls_back(self):
        point = _mul(1)
        pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        locking_script = p2pkh_script(_hash160(pubkey))
        genesis_cb = coinbase(0, b"\x00\x00")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)

        reward_cb = coinbase(block_subsidy(1), b"\x01\x01", locking_script)
        reward = block_for([reward_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(reward, 1)

        active_cb = coinbase(block_subsidy(2), b"\x01\x02")
        active = block_for([active_cb], previous=reward.header.hash, timestamp=3)
        self.store.connect_block(active, 2)

        reward_point = OutPoint(reward_cb.txid, 0)
        reward_output = TxOutput(block_subsidy(1), locking_script)
        spend = signed_spend(reward_point, reward_output, block_subsidy(1) - 100)
        replacement_cb = coinbase(block_subsidy(2) + 100, b"\x02\x02")
        replacement = block_for(
            [replacement_cb, spend], previous=reward.header.hash, timestamp=4
        )
        with self.assertRaisesRegex(ValueError, "premature coinbase"):
            self.store.reorganize((active.header.hash,), (replacement,))

        self.assertEqual(self.store.tip(), (2, active.header.hash))
        self.assertEqual(self.store.get(reward_point), reward_output)
        self.assertEqual(
            self.store.get(OutPoint(active_cb.txid, 0)),
            TxOutput(block_subsidy(2), b"miner"),
        )
        self.assertIsNone(self.store.get(OutPoint(replacement_cb.txid, 0)))

    def test_reorganization_requires_tip_first_disconnect_order(self):
        genesis_cb = coinbase(block_subsidy(0), b"\x01\x01")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)
        child_cb = coinbase(block_subsidy(1), b"\x01\x02")
        child = block_for([child_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(child, 1)
        with self.assertRaisesRegex(ValueError, "tip-first"):
            self.store.reorganize((genesis.header.hash,), tuple())
        self.assertEqual(self.store.tip(), (1, child.header.hash))

    def test_reorganize_to_best_uses_header_chain_work_and_matching_bodies(self):
        genesis_cb = coinbase(block_subsidy(0), b"\x01\x01")
        genesis = mined_block_for([genesis_cb], timestamp=1)
        self.store.connect_block(genesis, 0)

        active_cb = coinbase(block_subsidy(1), b"\x01\x02")
        active = mined_block_for([active_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(active, 1)

        headers = HeaderChain(decode_compact_target(0x207fffff), genesis.header)
        headers.add(active.header)

        fork_one_cb = coinbase(block_subsidy(1), b"\x02\x02")
        fork_one = mined_block_for([fork_one_cb], previous=genesis.header.hash, timestamp=3)
        headers.add_to_branch(fork_one.header)
        fork_two_cb = coinbase(block_subsidy(2), b"\x02\x03")
        fork_two = mined_block_for([fork_two_cb], previous=fork_one.header.hash, timestamp=4)
        headers.add_to_branch(fork_two.header)

        result = self.store.reorganize_to_best(
            headers,
            {fork_one.header.hash: fork_one, fork_two.header.hash: fork_two},
        )
        self.assertEqual(result, (2, fork_two.header.hash))
        self.assertEqual(self.store.tip(), result)
        self.assertIsNone(self.store.get(OutPoint(active_cb.txid, 0)))
        self.assertEqual(self.store.get(OutPoint(fork_one_cb.txid, 0)),
                         TxOutput(block_subsidy(1), b"miner"))
        self.assertEqual(self.store.get(OutPoint(fork_two_cb.txid, 0)),
                         TxOutput(block_subsidy(2), b"miner"))

    def test_reorganize_to_best_requires_all_connecting_bodies(self):
        genesis_cb = coinbase(block_subsidy(0), b"\x01\x01")
        genesis = mined_block_for([genesis_cb], timestamp=1)
        self.store.connect_block(genesis, 0)
        active_cb = coinbase(block_subsidy(1), b"\x01\x02")
        active = mined_block_for([active_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(active, 1)

        headers = HeaderChain(decode_compact_target(0x207fffff), genesis.header)
        headers.add(active.header)
        fork_one_cb = coinbase(block_subsidy(1), b"\x02\x02")
        fork_one = mined_block_for([fork_one_cb], previous=genesis.header.hash, timestamp=3)
        headers.add_to_branch(fork_one.header)
        fork_two_cb = coinbase(block_subsidy(2), b"\x02\x03")
        fork_two = mined_block_for([fork_two_cb], previous=fork_one.header.hash, timestamp=4)
        headers.add_to_branch(fork_two.header)

        with self.assertRaisesRegex(ValueError, "missing replacement block body"):
            self.store.reorganize_to_best(headers, {fork_one.header.hash: fork_one})
        self.assertEqual(self.store.tip(), (1, active.header.hash))
        self.assertEqual(self.store.get(OutPoint(active_cb.txid, 0)),
                         TxOutput(block_subsidy(1), b"miner"))

    def test_reorganize_to_best_rejects_header_body_mismatch(self):
        genesis_cb = coinbase(block_subsidy(0), b"\x01\x01")
        genesis = mined_block_for([genesis_cb], timestamp=1)
        self.store.connect_block(genesis, 0)
        active_cb = coinbase(block_subsidy(1), b"\x01\x02")
        active = mined_block_for([active_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(active, 1)

        headers = HeaderChain(decode_compact_target(0x207fffff), genesis.header)
        headers.add(active.header)
        fork_cb = coinbase(block_subsidy(1), b"\x02\x02")
        fork = mined_block_for([fork_cb], previous=genesis.header.hash, timestamp=3)
        headers.add_to_branch(fork.header)
        longer_cb = coinbase(block_subsidy(2), b"\x02\x03")
        longer = mined_block_for([longer_cb], previous=fork.header.hash, timestamp=4)
        headers.add_to_branch(longer.header)
        altered = mined_block_for(
            [coinbase(block_subsidy(1), b"\x03\x02")],
            previous=genesis.header.hash, timestamp=3,
        )
        with self.assertRaisesRegex(ValueError, "header does not match"):
            self.store.reorganize_to_best(
                headers,
                {fork.header.hash: altered, longer.header.hash: longer},
            )
        self.assertEqual(self.store.tip(), (1, active.header.hash))

    def test_cumulative_issued_subsidy_tracks_active_chain_and_disconnect(self):
        genesis_cb = coinbase(0, b"\\x00\\x00")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)
        self.assertEqual(self.store.issued_subsidy(), 0)

        reward_cb = coinbase(block_subsidy(1), b"\\x01\\x01")
        reward = block_for([reward_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(reward, 1)
        self.assertEqual(self.store.issued_subsidy(), block_subsidy(1))
        self.store.verify_integrity()

        self.assertEqual(self.store.disconnect_tip(reward.header.hash), (1, reward.header.hash))
        self.assertEqual(self.store.issued_subsidy(), 0)
        self.store.verify_integrity()

    def test_cumulative_issued_subsidy_reorganization_replaces_branch_amount(self):
        genesis_cb = coinbase(0, b"\\x00\\x00")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)

        old_cb = coinbase(block_subsidy(1), b"\\x01\\x01")
        old_block = block_for([old_cb], previous=genesis.header.hash, timestamp=2)
        self.store.connect_block(old_block, 1)

        replacement_cb = coinbase(block_subsidy(1) - 123, b"\\x02\\x01")
        replacement = block_for([replacement_cb], previous=genesis.header.hash, timestamp=3)
        self.store.reorganize((old_block.header.hash,), (replacement,))
        self.assertEqual(self.store.issued_subsidy(), block_subsidy(1) - 123)
        self.store.verify_integrity()

    def test_transaction_fees_are_not_counted_as_new_subsidy(self):
        point = _mul(1)
        pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        locking_script = p2pkh_script(_hash160(pubkey))
        funding = OutPoint(bytes.fromhex("55" * 32), 0)
        previous_output = TxOutput(10_000, locking_script)
        self.store.add_genesis_output(funding, previous_output)

        genesis_cb = coinbase(0, b"\\x00\\x00")
        genesis = block_for([genesis_cb])
        self.store.connect_block(genesis, 0)
        spend = signed_spend(funding, previous_output, 9_900)
        next_cb = coinbase(block_subsidy(1) + 100, b"\\x01\\x01")
        next_block = block_for([next_cb, spend], previous=genesis.header.hash, timestamp=2)
        self.assertEqual(self.store.connect_block(next_block, 1), 100)
        self.assertEqual(self.store.issued_subsidy(), block_subsidy(1))
        self.store.verify_integrity()

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
        with self.store._connection_scope() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM block_undo_spent").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM block_undo_created").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
