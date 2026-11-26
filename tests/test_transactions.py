import unittest

from src.blackroot_transactions import (
    OutPoint,
    Transaction,
    TxInput,
    TxOutput,
    apply_transaction,
    compact_size,
    merkle_root,
    validate_transaction,
)


class CompactSizeTests(unittest.TestCase):
    def test_boundary_encodings(self):
        self.assertEqual(compact_size(252), b"\xfc")
        self.assertEqual(compact_size(253), b"\xfd\xfd\x00")
        self.assertEqual(compact_size(65536), b"\xfe\x00\x00\x01\x00")

    def test_rejects_invalid_values(self):
        for value in (-1, 1.2, True, 2**64):
            with self.assertRaises(ValueError):
                compact_size(value)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.funding = OutPoint(bytes.fromhex("11" * 32), 0)
        self.utxos = {self.funding: TxOutput(5 * 100_000_000, b"previous-script")}

    def test_legacy_transaction_round_trip(self):
        tx = Transaction(
            2,
            (TxInput(self.funding, b"\x01\x02", 0xFFFFFFFE),),
            (TxOutput(123456, b"\x51\x21"),),
            42,
        )
        decoded = Transaction.deserialize(tx.serialize())
        self.assertEqual(decoded, tx)
        self.assertEqual(decoded.txid, tx.txid)

    def test_deserializer_rejects_trailing_truncated_and_noncanonical_data(self):
        tx = Transaction(1, (TxInput(self.funding),), (TxOutput(1, b"x"),))
        raw = tx.serialize()
        with self.assertRaisesRegex(ValueError, "trailing bytes"):
            Transaction.deserialize(raw + b"\x00")
        with self.assertRaisesRegex(ValueError, "truncated"):
            Transaction.deserialize(raw[:-1])
        noncanonical = raw[:4] + b"\xfd\x01\x00" + raw[5:]
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            Transaction.deserialize(noncanonical)

    def test_deserializer_rejects_input_count_that_cannot_fit_transaction_limit(self):
        # 100,000 minimum-size inputs alone exceed the 4 MB transaction cap.
        raw = (1).to_bytes(4, "little", signed=True) + compact_size(100_000)
        with self.assertRaisesRegex(ValueError, "exceeds prototype size limit"):
            Transaction.deserialize(raw)

    def test_serialization_and_txid_are_deterministic(self):
        tx = Transaction(
            1,
            (TxInput(self.funding, b"signature-placeholder"),),
            (TxOutput(4 * 100_000_000, b"destination-script"),),
        )
        self.assertEqual(tx.serialize(), tx.serialize())
        self.assertEqual(len(tx.txid), 32)
        self.assertEqual(tx.display_txid, tx.txid[::-1].hex())

    def test_validate_value_conservation_and_fee(self):
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(4 * 100_000_000, b"script"),),
        )
        self.assertEqual(validate_transaction(tx, self.utxos), (500_000_000, 400_000_000))

    def test_apply_transaction_spends_and_creates_utxos(self):
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(4 * 100_000_000, b"new-script"),),
        )
        fee = apply_transaction(tx, self.utxos)
        self.assertEqual(fee, 100_000_000)
        self.assertNotIn(self.funding, self.utxos)
        self.assertEqual(self.utxos[OutPoint(tx.txid, 0)].value, 400_000_000)

    def test_rejects_missing_and_duplicate_inputs(self):
        missing = OutPoint(bytes.fromhex("22" * 32), 1)
        tx_missing = Transaction(1, (TxInput(missing),), (TxOutput(1, b"x"),))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            validate_transaction(tx_missing, self.utxos)
        tx_duplicate = Transaction(
            1,
            (TxInput(self.funding), TxInput(self.funding)),
            (TxOutput(1, b"x"),),
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_transaction(tx_duplicate, self.utxos)

    def test_rejects_outputs_exceeding_inputs(self):
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(500_000_001, b"x"),),
        )
        with self.assertRaisesRegex(ValueError, "exceed inputs"):
            validate_transaction(tx, self.utxos)

    def test_rejects_existing_created_outpoint_without_mutating_utxos(self):
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(400_000_000, b"new-script"),),
        )
        collision = OutPoint(tx.txid, 0)
        self.utxos[collision] = TxOutput(7, b"pre-existing")
        before = dict(self.utxos)

        with self.assertRaisesRegex(ValueError, "overwrite an existing UTXO"):
            apply_transaction(tx, self.utxos)

        self.assertEqual(self.utxos, before)

    def test_does_not_mutate_utxos_on_validation_failure(self):
        before = dict(self.utxos)
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(600_000_000, b"x"),),
        )
        with self.assertRaises(ValueError):
            apply_transaction(tx, self.utxos)
        self.assertEqual(self.utxos, before)


class MerkleTests(unittest.TestCase):
    def test_empty_root_is_zero(self):
        self.assertEqual(merkle_root([]), bytes(32))

    def test_single_item_root_is_item(self):
        leaf = bytes.fromhex("ab" * 32)
        self.assertEqual(merkle_root([leaf]), leaf)

    def test_odd_leaf_is_duplicated(self):
        from src.blackroot_consensus import sha256d
        a, b, c = (bytes([i]) * 32 for i in (1, 2, 3))
        expected = sha256d(sha256d(a + b) + sha256d(c + c))
        self.assertEqual(merkle_root([a, b, c]), expected)


if __name__ == "__main__":
    unittest.main()
