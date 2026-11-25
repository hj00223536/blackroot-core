import tempfile
import unittest
from pathlib import Path

from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_utxo_db import UTXOStore


class UTXOStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "utxos.sqlite"
        self.store = UTXOStore(self.db_path)
        self.funding = OutPoint(bytes.fromhex("31" * 32), 0)
        self.store.add_genesis_output(self.funding, TxOutput(900, b"funding-script"))

    def test_persists_output_across_instances(self):
        reopened = UTXOStore(self.db_path)
        self.assertEqual(reopened.get(self.funding), TxOutput(900, b"funding-script"))
        self.assertEqual(reopened.count(), 1)

    def test_applies_spend_atomically_and_returns_fee(self):
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(800, b"recipient"),),
        )
        self.assertEqual(self.store.apply(tx), 100)
        self.assertIsNone(self.store.get(self.funding))
        self.assertEqual(self.store.get(OutPoint(tx.txid, 0)), TxOutput(800, b"recipient"))
        self.assertEqual(self.store.count(), 1)

    def test_missing_input_does_not_change_database(self):
        missing = OutPoint(bytes.fromhex("42" * 32), 2)
        tx = Transaction(1, (TxInput(missing),), (TxOutput(1, b"x"),))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.apply(tx)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get(self.funding), TxOutput(900, b"funding-script"))

    def test_value_failure_rolls_back(self):
        tx = Transaction(
            1,
            (TxInput(self.funding),),
            (TxOutput(901, b"too-much"),),
        )
        with self.assertRaisesRegex(ValueError, "exceed inputs"):
            self.store.apply(tx)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get(self.funding), TxOutput(900, b"funding-script"))

    def test_rejects_duplicate_bootstrap_outpoint(self):
        with self.assertRaises(Exception):
            self.store.add_genesis_output(self.funding, TxOutput(900, b"duplicate"))
        self.assertEqual(self.store.count(), 1)


if __name__ == "__main__":
    unittest.main()
