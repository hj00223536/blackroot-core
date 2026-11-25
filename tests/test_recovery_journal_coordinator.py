import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.blackroot_recovery_journal import NodeRecoveryJournal
from src.blackroot_sqlite import SQLiteTransactionCoordinator


class RecoveryJournalCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "shared.sqlite"
        self.old_tip = (4, bytes.fromhex("41" * 32))
        self.new_tip = (5, bytes.fromhex("42" * 32))

    def test_prepare_and_reconcile_share_outer_transaction(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            with coordinator.transaction() as connection:
                journal = NodeRecoveryJournal(self.path, connection=connection)
                journal.prepare(self.old_tip, self.new_tip)
                self.assertTrue(journal.pending())
                self.assertEqual(journal.reconcile(self.new_tip), "committed")
                self.assertFalse(journal.pending())
        reopened = NodeRecoveryJournal(self.path)
        self.assertFalse(reopened.pending())

    def test_outer_rollback_reverts_recovery_intent_and_schema(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            with self.assertRaisesRegex(RuntimeError, "abort journal transaction"):
                with coordinator.transaction() as connection:
                    journal = NodeRecoveryJournal(self.path, connection=connection)
                    journal.prepare(self.old_tip, self.new_tip)
                    self.assertTrue(journal.pending())
                    raise RuntimeError("abort journal transaction")
        with sqlite3.connect(self.path) as db:
            table = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='recovery_intent'"
            ).fetchall()
        self.assertEqual(table, [])

    def test_coordinator_mode_requires_active_outer_transaction(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            with self.assertRaisesRegex(RuntimeError, "active outer transaction"):
                NodeRecoveryJournal(self.path, connection=coordinator.connection)


if __name__ == "__main__":
    unittest.main()
