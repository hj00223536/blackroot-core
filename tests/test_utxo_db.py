import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_utxo_db import UTXOStore
from src.blackroot_sqlite import SQLiteTransactionCoordinator


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

    def test_coordinator_owned_connection_initializes_and_commits_bootstrap_state(self):
        shared_path = Path(self.tempdir.name) / "shared.sqlite"
        funding = OutPoint(bytes.fromhex("51" * 32), 0)
        with SQLiteTransactionCoordinator(shared_path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(shared_path, connection=connection)
                self.assertIs(store._external_connection, connection)
                store.add_genesis_output(funding, TxOutput(700, b"shared"))
                self.assertEqual(store.get(funding), TxOutput(700, b"shared"))
        reopened = UTXOStore(shared_path)
        self.assertEqual(reopened.get(funding), TxOutput(700, b"shared"))

    def test_coordinator_rolls_back_utxo_schema_and_bootstrap_state_together(self):
        shared_path = Path(self.tempdir.name) / "rollback.sqlite"
        funding = OutPoint(bytes.fromhex("52" * 32), 0)
        with SQLiteTransactionCoordinator(shared_path) as coordinator:
            with self.assertRaisesRegex(ValueError, "abort coordinated setup"):
                with coordinator.transaction() as connection:
                    store = UTXOStore(shared_path, connection=connection)
                    store.add_genesis_output(funding, TxOutput(701, b"rollback"))
                    raise ValueError("abort coordinated setup")
        with sqlite3.connect(shared_path) as db:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='utxos'"
            ).fetchall()
        self.assertEqual(tables, [])

    def test_internal_transaction_methods_reject_coordinator_connection(self):
        shared_path = Path(self.tempdir.name) / "guard.sqlite"
        funding = OutPoint(bytes.fromhex("53" * 32), 0)
        with SQLiteTransactionCoordinator(shared_path) as coordinator:
            with coordinator.transaction() as connection:
                store = UTXOStore(shared_path, connection=connection)
                with self.assertRaisesRegex(RuntimeError, "internal transaction"):
                    store.apply(
                        Transaction(1, (TxInput(funding),), (TxOutput(1, b"x"),))
                    )

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


    def test_refuses_unsafe_schema_v1_database_with_live_utxos(self):
        legacy_path = Path(self.tempdir.name) / "legacy-v1.sqlite"
        with sqlite3.connect(legacy_path) as db:
            db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO metadata(key, value) VALUES('schema_version', '1')")
            db.execute("""
                CREATE TABLE utxos (
                    txid BLOB NOT NULL,
                    output_index INTEGER NOT NULL,
                    value INTEGER NOT NULL,
                    script_pubkey BLOB NOT NULL,
                    PRIMARY KEY(txid, output_index)
                )
            """)
            db.execute(
                "INSERT INTO utxos VALUES(?, ?, ?, ?)",
                (bytes.fromhex("66" * 32), 0, 50, b"legacy"),
            )
        with self.assertRaisesRegex(RuntimeError, "unsafe schema-v1 migration"):
            UTXOStore(legacy_path)


if __name__ == "__main__":
    unittest.main()
