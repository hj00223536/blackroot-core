import sqlite3
from contextlib import contextmanager
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from src.blackroot_sqlite import SQLiteTransactionCoordinator



@contextmanager
def managed_sqlite(connection):
    try:
        yield connection
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

class SQLiteTransactionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "node.sqlite"

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

    def test_store_facade_cannot_commit_rollback_or_close_owner_connection(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            db = coordinator.connection
            with self.assertRaisesRegex(RuntimeError, "cannot commit"):
                db.commit()
            with self.assertRaisesRegex(RuntimeError, "cannot roll back"):
                db.rollback()
            with self.assertRaisesRegex(RuntimeError, "cannot close"):
                db.close()
            self.assertEqual(db.execute("SELECT 1").fetchone(), (1,))

    def test_executescript_cannot_escape_and_commit_outer_transaction(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            with self.assertRaisesRegex(ValueError, "abort outer transaction"):
                with coordinator.transaction() as db:
                    db.execute("CREATE TABLE protected (value INTEGER)")
                    with self.assertRaisesRegex(RuntimeError, "executescript is disabled"):
                        db.executescript(
                            "INSERT INTO protected(value) VALUES(1);"
                        )
                    self.assertTrue(db.in_transaction)
                    raise ValueError("abort outer transaction")
            self.assertEqual(
                db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='protected'"
                ).fetchall(),
                [],
            )

    def test_cursor_facades_do_not_expose_raw_connection(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            db = coordinator.connection
            execute_cursor = db.execute("SELECT 7")
            direct_cursor = db.cursor()
            self.assertEqual(execute_cursor.fetchone(), (7,))
            with self.assertRaises(AttributeError):
                _ = execute_cursor.connection
            with self.assertRaises(AttributeError):
                _ = direct_cursor.connection
            direct_cursor.close()

    def test_store_context_manager_does_not_commit_outer_transaction(self):
        with SQLiteTransactionCoordinator(self.path) as coordinator:
            with coordinator.transaction() as db:
                db.execute("CREATE TABLE sample (value INTEGER PRIMARY KEY)")
                with db:
                    db.execute("INSERT INTO sample(value) VALUES(9)")
                self.assertTrue(db.in_transaction)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute("SELECT value FROM sample").fetchall(), [(9,)])

    def test_multiple_processes_complete_repeated_coordinated_writes_without_loss(self):
        with managed_sqlite(sqlite3.connect(self.path)) as db:
            db.execute(
                "CREATE TABLE writes (writer INTEGER NOT NULL, sequence INTEGER NOT NULL, "
                "PRIMARY KEY(writer, sequence))"
            )

        worker_code = """
import sys
from src.blackroot_sqlite import SQLiteTransactionCoordinator
database, writer, iterations = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
with SQLiteTransactionCoordinator(database, timeout=20) as owner:
    for sequence in range(iterations):
        with owner.transaction() as db:
            db.execute(
                "INSERT INTO writes(writer, sequence) VALUES(?, ?)",
                (writer, sequence),
            )
"""
        workers = [
            subprocess.Popen(
                [sys.executable, "-c", worker_code, str(self.path), str(writer), "12"],
                cwd=Path(__file__).resolve().parents[1],
            )
            for writer in range(4)
        ]
        try:
            for process in workers:
                self.assertEqual(process.wait(timeout=35), 0)
        finally:
            for process in workers:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

        with managed_sqlite(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM writes").fetchone()[0], 48)
            self.assertEqual(
                db.execute(
                    "SELECT writer, COUNT(*) FROM writes GROUP BY writer ORDER BY writer"
                ).fetchall(),
                [(0, 12), (1, 12), (2, 12), (3, 12)],
            )

    def test_independent_process_writers_are_serialized_by_begin_immediate(self):
        with managed_sqlite(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE writes (value INTEGER PRIMARY KEY)")

        release = self.root / "release-writer"
        acquired = self.root / "first-writer-acquired"
        first_code = """
import sys, time
from pathlib import Path
from src.blackroot_sqlite import SQLiteTransactionCoordinator
database, acquired, release = map(Path, sys.argv[1:])
with SQLiteTransactionCoordinator(database, timeout=5) as owner:
    with owner.transaction() as db:
        db.execute("INSERT INTO writes(value) VALUES(1)")
        acquired.write_text("ready")
        deadline = time.monotonic() + 8
        while not release.exists():
            if time.monotonic() > deadline:
                raise SystemExit("timed out waiting for parent release")
            time.sleep(0.01)
"""
        second_code = """
import sys
from src.blackroot_sqlite import SQLiteTransactionCoordinator
with SQLiteTransactionCoordinator(sys.argv[1], timeout=5) as owner:
    with owner.transaction() as db:
        db.execute("INSERT INTO writes(value) VALUES(2)")
"""
        first = subprocess.Popen(
            [sys.executable, "-c", first_code, str(self.path), str(acquired), str(release)],
            cwd=Path(__file__).resolve().parents[1],
        )
        second = None
        try:
            deadline = time.monotonic() + 5
            while not acquired.exists() and time.monotonic() < deadline:
                if first.poll() is not None:
                    self.fail("first writer exited before acquiring its transaction")
                time.sleep(0.01)
            self.assertTrue(acquired.exists(), "first writer did not acquire its transaction")

            second = subprocess.Popen(
                [sys.executable, "-c", second_code, str(self.path)],
                cwd=Path(__file__).resolve().parents[1],
            )
            time.sleep(0.25)
            self.assertIsNone(
                second.poll(),
                "second process should wait while the first holds BEGIN IMMEDIATE",
            )
            release.write_text("commit")
            self.assertEqual(first.wait(timeout=5), 0)
            self.assertEqual(second.wait(timeout=5), 0)
        finally:
            release.touch()
            if first.poll() is None:
                first.kill()
                first.wait(timeout=5)
            if second is not None and second.poll() is None:
                second.kill()
                second.wait(timeout=5)

        with managed_sqlite(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT value FROM writes ORDER BY value").fetchall(),
                [(1,), (2,)],
            )


if __name__ == "__main__":
    unittest.main()
