import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.blackroot_storage_migration import (
    create_consistent_sqlite_snapshot,
    inspect_legacy_node_databases,
    snapshot_legacy_node_databases,
)


class LegacyStoragePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.header = self.root / "headers.sqlite"
        self.utxo = self.root / "utxo.sqlite"
        self.journal = self.root / "journal.sqlite"
        self._make_sources()

    def _make_sources(self):
        with sqlite3.connect(self.header) as db:
            db.execute("CREATE TABLE header_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO header_metadata VALUES('schema_version', '1')")
            db.execute("INSERT INTO header_metadata VALUES('pow_limit', '123')")
            db.execute("INSERT INTO header_metadata VALUES('genesis_hash', '00')")
            db.execute("CREATE TABLE headers(block_hash BLOB PRIMARY KEY, height INTEGER)")
            db.execute("INSERT INTO headers VALUES(?, 0)", (bytes(32),))

        with sqlite3.connect(self.utxo) as db:
            db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO metadata VALUES('schema_version', '2')")
            for table in (
                "utxos", "blocks", "block_transactions", "block_bodies",
                "block_undo_spent", "block_undo_created",
            ):
                db.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')

        with sqlite3.connect(self.journal) as db:
            db.execute("""
                CREATE TABLE recovery_intent (
                    singleton INTEGER PRIMARY KEY,
                    old_height INTEGER, old_hash BLOB,
                    new_height INTEGER, new_hash BLOB
                )
            """)

    def test_preflight_reports_clean_sources_without_modifying_them(self):
        before = {p: p.read_bytes() for p in (self.header, self.utxo, self.journal)}
        result = inspect_legacy_node_databases(self.header, self.utxo, self.journal)
        self.assertEqual(result["status"], "preflight_passed")
        self.assertFalse(result["migration_performed"])
        self.assertFalse(result["source_files_modified"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_rejects_aliases_before_opening_databases(self):
        with self.assertRaisesRegex(ValueError, "same file"):
            inspect_legacy_node_databases(self.header, self.utxo, self.header)

    def test_rejects_unresolved_recovery_intent(self):
        with sqlite3.connect(self.journal) as db:
            db.execute(
                "INSERT INTO recovery_intent VALUES(1, NULL, NULL, 0, ?)",
                (bytes(32),),
            )
        with self.assertRaisesRegex(RuntimeError, "unresolved intent"):
            inspect_legacy_node_databases(self.header, self.utxo, self.journal)

    def test_rejects_unknown_utxo_schema(self):
        with sqlite3.connect(self.utxo) as db:
            db.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
        with self.assertRaisesRegex(RuntimeError, "unsupported UTXO schema"):
            inspect_legacy_node_databases(self.header, self.utxo, self.journal)

    def test_rejects_missing_source_file(self):
        self.journal.unlink()
        with self.assertRaises(FileNotFoundError):
            inspect_legacy_node_databases(self.header, self.utxo, self.journal)


if __name__ == "__main__":
    unittest.main()
