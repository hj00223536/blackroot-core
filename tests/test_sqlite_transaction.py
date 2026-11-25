import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.blackroot_sqlite import SQLiteTransactionCoordinator


class SQLiteTransactionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "node.sqlite"

    def test_transaction_commits_all_statements_on_owned_connection(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            with coordinator.transaction() as db:
                self.assertIs(db, coordinator.connection)
                db.execute("CREATE TABLE sample (value INTEGER PRIMARY KEY)")
                db.execute("INSERT INTO sample(value) VALUES(1)")
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute("SELECT value FROM sample").fetchall(), [(1,)])

    def test_exception_rolls_back_every_statement(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            with self.assertRaisesRegex(ValueError, "injected"):
                with coordinator.transaction() as db:
                    db.execute("CREATE TABLE sample (value INTEGER PRIMARY KEY)")
                    db.execute("INSERT INTO sample(value) VALUES(1)")
                    raise ValueError("injected")
            self.assertEqual(
                db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='sample'"
                ).fetchall(),
                [],
            )
            self.assertFalse(db.in_transaction)

    def test_nested_or_external_transaction_is_rejected(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            with coordinator.transaction() as db:
                with self.assertRaisesRegex(RuntimeError, "nested or externally-started"):
                    with coordinator.transaction():
                        pass
                self.assertTrue(db.in_transaction)

    def test_connection_is_closed_when_owner_exits(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            db = coordinator.connection
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")
        with self.assertRaisesRegex(RuntimeError, "not open"):
            _ = coordinator.connection

    def test_foreign_keys_are_enabled_on_owned_connection(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            self.assertEqual(
                coordinator.connection.execute("PRAGMA foreign_keys").fetchone(),
                (1,),
            )


if __name__ == "__main__":
    unittest.main()
