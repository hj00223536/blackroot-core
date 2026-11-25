import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.blackroot_chain import BlockHeader
from src.blackroot_consensus import block_work, decode_compact_target

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
            pow_limit = decode_compact_target(0x207fffff)
            db.execute("INSERT INTO header_metadata VALUES('pow_limit', ?)", (str(pow_limit),))
            genesis = BlockHeader(1, bytes(32), bytes(32), 1, 0x207fffff, 0)
            db.execute("INSERT INTO header_metadata VALUES('genesis_hash', ?)",
                       (genesis.hash.hex(),))
            db.execute("""CREATE TABLE headers(
                block_hash BLOB PRIMARY KEY, height INTEGER, version INTEGER,
                prev_hash BLOB, merkle_root BLOB, timestamp INTEGER, bits INTEGER,
                nonce INTEGER, chainwork TEXT)""")
            db.execute(
                "INSERT INTO headers VALUES(?, 0, ?, ?, ?, ?, ?, ?, ?)",
                (genesis.hash, genesis.version, genesis.prev_hash,
                 genesis.merkle_root, genesis.timestamp, genesis.bits, genesis.nonce,
                 str(block_work(pow_limit))),
            )

        with sqlite3.connect(self.utxo) as db:
            db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO metadata VALUES('schema_version', '2')")
            db.execute("""CREATE TABLE blocks(
                height INTEGER PRIMARY KEY, block_hash BLOB, prev_hash BLOB,
                header BLOB, tx_count INTEGER, total_fees INTEGER)""")
            for table in (
                "utxos", "block_bodies", "block_undo_spent", "block_undo_created",
            ):
                db.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
            db.execute(
                "CREATE TABLE block_transactions (id INTEGER PRIMARY KEY, "
                "height INTEGER REFERENCES blocks(height) ON DELETE CASCADE)"
            )

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

    def test_preflight_exposes_schema_ddl_columns_and_foreign_keys(self):
        report = inspect_legacy_node_databases(self.header, self.utxo, self.journal)
        inventory = report["databases"]["utxo"]["schema_inventory"]
        self.assertIn("block_transactions", inventory["tables"])
        columns = inventory["tables"]["block_transactions"]["columns"]
        self.assertEqual([column["name"] for column in columns],
                         ["id", "height"])
        foreign_keys = inventory["tables"]["block_transactions"]["foreign_keys"]
        self.assertEqual(len(foreign_keys), 1)
        self.assertEqual(foreign_keys[0]["referenced_table"], "blocks")
        self.assertEqual(foreign_keys[0]["from_column"], "height")
        self.assertEqual(foreign_keys[0]["on_delete"], "CASCADE")
        self.assertTrue(any(
            item["type"] == "table" and item["name"] == "blocks"
            for item in inventory["objects"]
        ))

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



class SQLiteSnapshotTests(unittest.TestCase):
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
            pow_limit = decode_compact_target(0x207fffff)
            db.execute("INSERT INTO header_metadata VALUES('pow_limit', ?)", (str(pow_limit),))
            genesis = BlockHeader(1, bytes(32), bytes(32), 1, 0x207fffff, 0)
            db.execute("INSERT INTO header_metadata VALUES('genesis_hash', ?)",
                       (genesis.hash.hex(),))
            db.execute("""CREATE TABLE headers(
                block_hash BLOB PRIMARY KEY, height INTEGER, version INTEGER,
                prev_hash BLOB, merkle_root BLOB, timestamp INTEGER, bits INTEGER,
                nonce INTEGER, chainwork TEXT)""")
            db.execute(
                "INSERT INTO headers VALUES(?, 0, ?, ?, ?, ?, ?, ?, ?)",
                (genesis.hash, genesis.version, genesis.prev_hash,
                 genesis.merkle_root, genesis.timestamp, genesis.bits, genesis.nonce,
                 str(block_work(pow_limit))),
            )
        with sqlite3.connect(self.utxo) as db:
            db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO metadata VALUES('schema_version', '2')")
            db.execute("""CREATE TABLE blocks(
                height INTEGER PRIMARY KEY, block_hash BLOB, prev_hash BLOB,
                header BLOB, tx_count INTEGER, total_fees INTEGER)""")
            for table in ("utxos", "block_bodies", "block_undo_spent",
                          "block_undo_created"):
                db.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
            db.execute(
                "CREATE TABLE block_transactions (id INTEGER PRIMARY KEY, "
                "height INTEGER REFERENCES blocks(height) ON DELETE CASCADE)"
            )
        with sqlite3.connect(self.journal) as db:
            db.execute("""CREATE TABLE recovery_intent (
                singleton INTEGER PRIMARY KEY, old_height INTEGER, old_hash BLOB,
                new_height INTEGER, new_hash BLOB)""")

    def test_individual_snapshot_captures_wal_without_mutating_source(self):
        source = self.root / "wal.sqlite"
        destination = self.root / "wal-snapshot.sqlite"
        writer = sqlite3.connect(source)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE records(value TEXT)")
        writer.commit()
        writer.execute("INSERT INTO records VALUES('wal-committed')")
        writer.commit()
        before = source.read_bytes()
        report = create_consistent_sqlite_snapshot(source, destination)
        self.assertEqual(report["status"], "snapshot_created")
        self.assertEqual(
            report["snapshot_sha256"],
            hashlib.sha256(destination.read_bytes()).hexdigest(),
        )
        self.assertEqual(len(report["snapshot_sha256"]), 64)
        self.assertEqual(source.read_bytes(), before)
        with sqlite3.connect(destination) as db:
            self.assertEqual(db.execute("SELECT value FROM records").fetchone()[0],
                             "wal-committed")
        writer.close()

    def test_snapshot_refuses_overwrite_and_preserves_existing_file(self):
        source = self.root / "source.sqlite"
        destination = self.root / "existing.sqlite"
        with sqlite3.connect(source) as db:
            db.execute("CREATE TABLE t(value)")
        destination.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            create_consistent_sqlite_snapshot(source, destination)
        self.assertEqual(destination.read_bytes(), b"keep")

    def test_all_store_snapshots_are_revalidated_and_sources_unchanged(self):
        before = {p: p.read_bytes() for p in (self.header, self.utxo, self.journal)}
        out = self.root / "snapshots"
        out.mkdir()
        report = snapshot_legacy_node_databases(
            self.header, self.utxo, self.journal, out
        )
        self.assertEqual(report["status"], "snapshots_validated")
        self.assertFalse(report["migration_performed"])
        self.assertFalse(report["source_files_modified"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(report["snapshot_preflight"]["status"], "snapshot_set_consistent")
        self.assertEqual(len(list(out.glob("*.sqlite"))), 3)




    def test_snapshot_set_rejects_incorrect_genesis_chainwork(self):
        out = self.root / "snapshots"
        out.mkdir()
        with sqlite3.connect(self.header) as db:
            db.execute("UPDATE headers SET chainwork='1' WHERE height=0")
        with self.assertRaisesRegex(RuntimeError, "genesis metadata mismatch during replay"):
            snapshot_legacy_node_databases(
                self.header, self.utxo, self.journal, out
            )
        self.assertEqual(list(out.iterdir()), [])

    def test_snapshot_set_rejects_malformed_genesis_metadata(self):
        out = self.root / "snapshots"
        out.mkdir()
        with sqlite3.connect(self.header) as db:
            db.execute(
                "UPDATE header_metadata SET value='00' WHERE key='genesis_hash'"
            )
        with self.assertRaisesRegex(RuntimeError, "malformed genesis hash"):
            snapshot_legacy_node_databases(
                self.header, self.utxo, self.journal, out
            )
        self.assertEqual(list(out.iterdir()), [])

    def test_snapshot_set_rejects_active_utxo_block_missing_from_header_store(self):
        out = self.root / "snapshots"
        out.mkdir()
        with sqlite3.connect(self.utxo) as db:
            db.execute(
                "INSERT INTO blocks(height, block_hash, prev_hash, header, tx_count, total_fees) "
                "VALUES(0, ?, ?, ?, 1, 0)",
                (bytes.fromhex("11" * 32), bytes(32), bytes(80)),
            )
        with self.assertRaisesRegex(RuntimeError, "missing from the header snapshot"):
            snapshot_legacy_node_databases(
                self.header, self.utxo, self.journal, out
            )
        self.assertEqual(list(out.iterdir()), [])

    def test_all_store_snapshot_refuses_existing_destination_before_any_copy(self):
        out = self.root / "snapshots"
        out.mkdir()
        existing = out / "blackroot-utxo-snapshot.sqlite"
        existing.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            snapshot_legacy_node_databases(
                self.header, self.utxo, self.journal, out
            )
        self.assertEqual(existing.read_bytes(), b"preserve")
        self.assertEqual(list(out.iterdir()), [existing])

    def test_failed_snapshot_removes_only_its_owned_partial_file(self):
        bad = self.root / "bad.sqlite"
        bad.write_bytes(b"not sqlite")
        destination = self.root / "partial.sqlite"
        with self.assertRaises(sqlite3.DatabaseError):
            create_consistent_sqlite_snapshot(bad, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(bad.read_bytes(), b"not sqlite")


if __name__ == "__main__":
    unittest.main()
