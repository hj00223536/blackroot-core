import hashlib
import src.blackroot_storage_migration as migration_module
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_consensus import block_subsidy, block_work, check_proof_of_work, decode_compact_target
from src.blackroot_node_state import PersistentNodeState

from src.blackroot_storage_migration import (
    create_consistent_sqlite_snapshot,
    inspect_legacy_node_databases,
    import_snapshot_set_to_coordinated_database,
    plan_coordinated_schema_merge,
    snapshot_legacy_node_databases,
    validate_coordinated_staging_database,
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

    def test_schema_merge_plan_orders_fk_parents_before_children_without_writes(self):
        before = {p: p.read_bytes() for p in (self.header, self.utxo, self.journal)}
        plan = plan_coordinated_schema_merge(self.header, self.utxo, self.journal)
        self.assertEqual(plan["status"], "schema_merge_plan_ready")
        self.assertFalse(plan["migration_performed"])
        self.assertFalse(plan["source_files_modified"])
        self.assertLess(
            plan["table_order"].index("blocks"),
            plan["table_order"].index("block_transactions"),
        )
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_schema_merge_plan_rejects_virtual_tables(self):
        with sqlite3.connect(self.journal) as db:
            try:
                db.execute("CREATE VIRTUAL TABLE unsupported_search USING fts5(content)")
            except sqlite3.OperationalError as exc:
                self.skipTest(f"SQLite FTS5 module unavailable: {exc}")
        with self.assertRaisesRegex(RuntimeError, "virtual table"):
            plan_coordinated_schema_merge(self.header, self.utxo, self.journal)

    def test_schema_merge_plan_rejects_global_index_name_collisions(self):
        with sqlite3.connect(self.header) as db:
            db.execute("CREATE INDEX shared_name ON headers(height)")
        with sqlite3.connect(self.journal) as db:
            db.execute("CREATE INDEX shared_name ON recovery_intent(singleton)")
        with self.assertRaisesRegex(RuntimeError, "schema object name collision"):
            plan_coordinated_schema_merge(self.header, self.utxo, self.journal)

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




    def test_staged_import_preserves_rows_and_never_modifies_snapshots(self):
        snapshot_dir = self.root / "snapshots-for-import"
        snapshot_dir.mkdir()
        snapshot_legacy_node_databases(
            self.header, self.utxo, self.journal, snapshot_dir
        )
        snapshots = {
            "header": snapshot_dir / "blackroot-header-snapshot.sqlite",
            "utxo": snapshot_dir / "blackroot-utxo-snapshot.sqlite",
            "journal": snapshot_dir / "blackroot-journal-snapshot.sqlite",
        }
        before = {kind: path.read_bytes() for kind, path in snapshots.items()}
        destination = self.root / "coordinated-staging.sqlite"
        result = import_snapshot_set_to_coordinated_database(
            snapshots["header"], snapshots["utxo"], snapshots["journal"],
            destination, batch_size=2,
        )
        self.assertEqual(result["status"], "coordinated_staging_database_created")
        self.assertTrue(result["migration_performed"])
        self.assertFalse(result["production_cutover_performed"])
        self.assertFalse(result["source_files_modified"])
        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(result["foreign_key_check"], "ok")
        self.assertEqual(result["completion_manifest"], "complete")
        with sqlite3.connect(destination) as db:
            marker = db.execute(
                "SELECT format_version, status FROM blackroot_import_manifest WHERE singleton=1"
            ).fetchone()
        self.assertEqual(marker, (1, "complete"))
        self.assertEqual(before, {kind: path.read_bytes() for kind, path in snapshots.items()})
        with sqlite3.connect(destination) as db:
            self.assertEqual(
                db.execute("SELECT value FROM header_metadata WHERE key='schema_version'").fetchone()[0],
                "1",
            )
            self.assertEqual(
                db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],
                "2",
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM block_transactions").fetchone()[0], 0
            )

    def test_real_legacy_stores_snapshot_import_and_reopen_with_active_genesis(self):
        pow_limit = decode_compact_target(0x207fffff)
        coinbase = Transaction(
            1,
            (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), script_sig=b"\\x01\\x01"),),
            (TxOutput(block_subsidy(0), b"\\x51"),),
        )
        merkle = merkle_root([coinbase.txid])
        genesis = None
        for nonce in range(10000):
            candidate = BlockHeader(1, ZERO_HASH, merkle, 1, 0x207fffff, nonce)
            if check_proof_of_work(candidate.serialize(), candidate.bits, pow_limit):
                genesis = candidate
                break
        self.assertIsNotNone(genesis)
        block = Block(genesis, (coinbase,))

        header_path = self.root / "legacy-header.sqlite"
        utxo_path = self.root / "legacy-utxo.sqlite"
        journal_path = self.root / "legacy-journal.sqlite"
        state = PersistentNodeState(
            header_path, utxo_path, pow_limit, genesis,
            recovery_journal_path=journal_path,
        )
        self.assertEqual(state.connect_best_block(block, 0), 0)

        # Build and activate two descendants so the snapshot/import/reopen
        # exercise a multi-block active history, not just the genesis row.
        parent = genesis
        for height in (1, 2):
            next_coinbase = Transaction(
                1,
                (TxInput(
                    OutPoint(ZERO_TXID, COINBASE_INDEX),
                    script_sig=b"\\x01" + bytes([height]),
                ),),
                (TxOutput(block_subsidy(height), b"\\x51"),),
            )
            next_merkle = merkle_root([next_coinbase.txid])
            next_header = None
            for nonce in range(10000):
                candidate = BlockHeader(
                    1, parent.hash, next_merkle, height + 1,
                    0x207fffff, nonce,
                )
                if check_proof_of_work(candidate.serialize(), candidate.bits, pow_limit):
                    next_header = candidate
                    break
            self.assertIsNotNone(next_header)
            state.add_header(next_header, adjusted_time=height + 1)
            self.assertEqual(
                state.headers.chain.get(height).hash,
                next_header.hash,
            )
            next_block = Block(next_header, (next_coinbase,))
            self.assertEqual(state.connect_best_block(next_block, height), 0)
            parent = next_header

        expected_tip = state.utxos.tip()
        self.assertEqual(expected_tip[0], 2)
        state.close()

        snapshots_dir = self.root / "real-store-snapshots"
        snapshots_dir.mkdir()
        snapshot_report = snapshot_legacy_node_databases(
            header_path, utxo_path, journal_path, snapshots_dir
        )
        self.assertEqual(snapshot_report["status"], "snapshots_validated")

        staged = self.root / "real-store-coordinated.sqlite"
        imported = import_snapshot_set_to_coordinated_database(
            snapshots_dir / "blackroot-header-snapshot.sqlite",
            snapshots_dir / "blackroot-utxo-snapshot.sqlite",
            snapshots_dir / "blackroot-journal-snapshot.sqlite",
            staged,
            batch_size=2,
        )
        self.assertEqual(imported["status"], "coordinated_staging_database_created")
        reopened = validate_coordinated_staging_database(
            staged, pow_limit=pow_limit, genesis=genesis,
            require_import_manifest=True,
        )
        self.assertEqual(reopened["status"], "coordinated_node_reopen_passed")
        self.assertEqual(reopened["utxo_tip"], (expected_tip[0], expected_tip[1].hex()))
        self.assertEqual(reopened["header_height"], 2)
        self.assertEqual(reopened["header_best_hash"], parent.hash.hex())
        self.assertFalse(reopened["production_cutover_performed"])

        # Prove the imported staging database is operational, not merely
        # readable: connect one further valid block, close, and reopen again.
        resumed = PersistentNodeState.open_coordinated(staged, pow_limit, genesis)
        height = 3
        resumed_coinbase = Transaction(
            1,
            (TxInput(
                OutPoint(ZERO_TXID, COINBASE_INDEX),
                script_sig=b"\\x01" + bytes([height]),
            ),),
            (TxOutput(block_subsidy(height), b"\\x51"),),
        )
        resumed_merkle = merkle_root([resumed_coinbase.txid])
        resumed_header = None
        for nonce in range(10000):
            candidate = BlockHeader(
                1, parent.hash, resumed_merkle, 4, 0x207fffff, nonce
            )
            if check_proof_of_work(candidate.serialize(), candidate.bits, pow_limit):
                resumed_header = candidate
                break
        self.assertIsNotNone(resumed_header)
        resumed.add_header(resumed_header, adjusted_time=4)
        self.assertEqual(
            resumed.connect_best_block(Block(resumed_header, (resumed_coinbase,)), 3),
            0,
        )
        self.assertEqual(resumed.utxos.tip(), (3, resumed_header.hash))
        resumed.close()

        reopened_again = validate_coordinated_staging_database(
            staged, pow_limit=pow_limit, genesis=genesis,
            require_import_manifest=True,
        )
        self.assertEqual(reopened_again["status"], "coordinated_node_reopen_passed")
        self.assertEqual(reopened_again["utxo_tip"], (3, resumed_header.hash.hex()))
        self.assertEqual(reopened_again["header_best_hash"], resumed_header.hash.hex())

    def test_strict_staging_validation_rejects_missing_import_completion_manifest(self):
        genesis = BlockHeader(1, bytes(32), bytes(32), 1, 0x207fffff, 0)
        pow_limit = decode_compact_target(0x207fffff)
        database = self.root / "node-without-import-marker.sqlite"
        state = PersistentNodeState.open_coordinated(database, pow_limit, genesis)
        state.close()
        with self.assertRaisesRegex(RuntimeError, "no completed import manifest"):
            validate_coordinated_staging_database(
                database, pow_limit=pow_limit, genesis=genesis,
                require_import_manifest=True,
            )

    def test_coordinated_staging_validator_reopens_real_node_stores(self):
        genesis = BlockHeader(1, bytes(32), bytes(32), 1, 0x207fffff, 0)
        pow_limit = decode_compact_target(0x207fffff)
        database = self.root / "node-reopen.sqlite"
        state = PersistentNodeState.open_coordinated(database, pow_limit, genesis)
        state.close()
        report = validate_coordinated_staging_database(
            database, pow_limit=pow_limit, genesis=genesis
        )
        self.assertEqual(report["status"], "coordinated_node_reopen_passed")
        self.assertTrue(report["coordinated"])
        self.assertEqual(report["header_height"], 0)
        self.assertIsNone(report["utxo_tip"])
        self.assertEqual(report["recovery_intents_pending"], 0)
        self.assertFalse(report["production_cutover_performed"])

    def test_staged_import_rejects_source_snapshot_changed_during_copy(self):
        snapshot_dir = self.root / "snapshots-source-change"
        snapshot_dir.mkdir()
        snapshot_legacy_node_databases(
            self.header, self.utxo, self.journal, snapshot_dir
        )
        snapshots = (
            snapshot_dir / "blackroot-header-snapshot.sqlite",
            snapshot_dir / "blackroot-utxo-snapshot.sqlite",
            snapshot_dir / "blackroot-journal-snapshot.sqlite",
        )
        before = tuple(path.read_bytes() for path in snapshots)
        destination = self.root / "must-not-survive-source-change.sqlite"
        real_hash = migration_module._sha256_file
        calls = {"count": 0}

        def changed_hash(path):
            calls["count"] += 1
            digest = real_hash(path)
            # First three calls capture the pre-copy fingerprints; the fourth
            # is the post-copy header fingerprint and simulates source drift.
            if calls["count"] == 4:
                return "0" * 64
            return digest

        with patch.object(migration_module, "_sha256_file", side_effect=changed_hash):
            with self.assertRaisesRegex(RuntimeError, "source snapshot changed"):
                import_snapshot_set_to_coordinated_database(
                    *snapshots, destination, batch_size=2
                )

        self.assertFalse(destination.exists())
        self.assertEqual(before, tuple(path.read_bytes() for path in snapshots))

    def test_staged_import_cleans_up_when_later_source_open_fails(self):
        snapshot_dir = self.root / "snapshots-open-failure"
        snapshot_dir.mkdir()
        snapshot_legacy_node_databases(
            self.header, self.utxo, self.journal, snapshot_dir
        )
        snapshots = [
            snapshot_dir / f"blackroot-{kind}-snapshot.sqlite"
            for kind in ("header", "utxo", "journal")
        ]
        before = [path.read_bytes() for path in snapshots]
        destination = self.root / "must-not-survive.sqlite"

        from src import blackroot_storage_migration as migration

        original_open = migration._readonly_connection
        opened = []

        def fail_on_second_source(path):
            if opened:
                raise OSError("injected second-source open failure")
            connection = original_open(path)
            opened.append(connection)
            return connection

        with patch(
            "src.blackroot_storage_migration._readonly_connection",
            side_effect=fail_on_second_source,
        ):
            with self.assertRaisesRegex(OSError, "injected second-source"):
                import_snapshot_set_to_coordinated_database(
                    *snapshots, destination
                )

        self.assertEqual(len(opened), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")
        self.assertFalse(destination.exists())
        self.assertFalse(Path(str(destination) + "-wal").exists())
        self.assertFalse(Path(str(destination) + "-shm").exists())
        self.assertEqual(before, [path.read_bytes() for path in snapshots])

    def test_staged_import_refuses_existing_destination_without_overwrite(self):
        snapshot_dir = self.root / "snapshots-existing"
        snapshot_dir.mkdir()
        snapshot_legacy_node_databases(
            self.header, self.utxo, self.journal, snapshot_dir
        )
        snapshots = [snapshot_dir / f"blackroot-{kind}-snapshot.sqlite"
                     for kind in ("header", "utxo", "journal")]
        destination = self.root / "keep.sqlite"
        destination.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            import_snapshot_set_to_coordinated_database(*snapshots, destination)
        self.assertEqual(destination.read_bytes(), b"keep")

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
