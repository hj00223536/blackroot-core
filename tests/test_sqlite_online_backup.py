import sqlite3
from contextlib import contextmanager
import tempfile
import unittest
from pathlib import Path

from tests.test_reorg_atomicity import POW_LIMIT, mined_block
from src.blackroot_chain import HeaderChain, ZERO_HASH
from src.blackroot_utxo_db import UTXOStore



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

class SQLiteBackupRecoveryTests(unittest.TestCase):
    def test_online_backup_restores_validated_chain_and_archived_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / 'source.sqlite'
            backup_path = Path(directory) / 'backup.sqlite'
            source = UTXOStore(source_path)
            genesis = mined_block(0, ZERO_HASH, 1)
            chain = HeaderChain(POW_LIMIT, genesis.header)
            source.store_block_body(genesis)
            source.connect_validated_block(genesis, 0, chain)
            expected_tip = source.tip()
            expected_headers = source.active_block_headers()
            with managed_sqlite(source._connect()) as db:
                expected_utxos = db.execute(
                    'SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp FROM utxos ORDER BY txid, output_index'
                ).fetchall()
            with managed_sqlite(sqlite3.connect(source_path)) as source_db:
                with managed_sqlite(sqlite3.connect(backup_path)) as backup_db:
                    source_db.backup(backup_db)
            restored = UTXOStore(backup_path)
            self.assertEqual(restored.tip(), expected_tip)
            self.assertEqual(restored.active_block_headers(), expected_headers)
            with managed_sqlite(restored._connect()) as db:
                restored_utxos = db.execute(
                    'SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp FROM utxos ORDER BY txid, output_index'
                ).fetchall()
            self.assertEqual(restored_utxos, expected_utxos)
            restored_body = restored.load_block_body(genesis.header.hash)
            self.assertIsNotNone(restored_body)
            self.assertEqual(restored_body.serialize(), genesis.serialize())
            restored.verify_integrity()

    def test_online_backup_captures_committed_wal_state_while_source_remains_open(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "wal-source.sqlite"
            backup_path = Path(directory) / "wal-backup.sqlite"
            source = sqlite3.connect(source_path)
            try:
                mode = source.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
                source.execute(
                    "CREATE TABLE ledger (id INTEGER PRIMARY KEY, amount INTEGER NOT NULL CHECK(amount >= 0))"
                )
                source.commit()
                source.execute("INSERT INTO ledger(id, amount) VALUES(1, 40000000)")
                source.commit()

                # The source connection remains open and in WAL mode during
                # backup. The SQLite backup API must include committed frames.
                self.assertEqual(
                    source.execute("SELECT amount FROM ledger WHERE id=1").fetchone(),
                    (40_000_000,),
                )
                # Prove the committed row is still in the live WAL rather than
                # relying on a checkpoint having copied it into the main DB.
                wal_path = Path(str(source_path) + "-wal")
                self.assertTrue(wal_path.exists())
                self.assertGreater(wal_path.stat().st_size, 0)
                backup = sqlite3.connect(backup_path)
                try:
                    source.backup(backup)
                    self.assertEqual(
                        backup.execute("PRAGMA integrity_check").fetchone(),
                        ("ok",),
                    )
                    self.assertEqual(
                        backup.execute("PRAGMA foreign_key_check").fetchall(),
                        [],
                    )
                    self.assertEqual(
                        backup.execute("SELECT amount FROM ledger WHERE id=1").fetchone(),
                        (40_000_000,),
                    )
                finally:
                    backup.close()

                # Backup verification is read-only with respect to the source.
                self.assertEqual(
                    source.execute("SELECT amount FROM ledger WHERE id=1").fetchone(),
                    (40_000_000,),
                )
            finally:
                source.close()

    def test_corrupt_backup_is_rejected_without_mutating_source_database(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / 'source.sqlite'
            backup_path = Path(directory) / 'backup.sqlite'
            source = UTXOStore(source_path)
            genesis = mined_block(0, ZERO_HASH, 2)
            chain = HeaderChain(POW_LIMIT, genesis.header)
            source.store_block_body(genesis)
            source.connect_validated_block(genesis, 0, chain)

            with managed_sqlite(source._connect()) as db:
                source_rows = {
                    table: db.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall()
                    for table in (
                        'blocks', 'block_transactions', 'block_undo_spent',
                        'block_undo_created', 'utxos', 'block_bodies', 'metadata',
                    )
                }

            with managed_sqlite(sqlite3.connect(source_path)) as source_db:
                with managed_sqlite(sqlite3.connect(backup_path)) as backup_db:
                    source_db.backup(backup_db)

            # Keep the SQLite file structurally readable while corrupting the
            # archived block bytes so the domain-level integrity check rejects it.
            with managed_sqlite(sqlite3.connect(backup_path)) as backup_db:
                row = backup_db.execute(
                    'SELECT raw_block FROM block_bodies WHERE block_hash=?',
                    (genesis.header.hash,),
                ).fetchone()
                self.assertIsNotNone(row)
                corrupted = bytearray(row[0])
                corrupted[0] ^= 1
                backup_db.execute(
                    'UPDATE block_bodies SET raw_block=? WHERE block_hash=?',
                    (bytes(corrupted), genesis.header.hash),
                )
                backup_db.commit()

            damaged_restore = UTXOStore(backup_path)
            with self.assertRaisesRegex(RuntimeError, 'archived block body header hash does not match archive key'):
                damaged_restore.verify_integrity()

            # Validation of the damaged copy must never write to the source.
            source.verify_integrity()
            with managed_sqlite(source._connect()) as db:
                source_rows_after = {
                    table: db.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall()
                    for table in (
                        'blocks', 'block_transactions', 'block_undo_spent',
                        'block_undo_created', 'utxos', 'block_bodies', 'metadata',
                    )
                }
            self.assertEqual(source_rows_after, source_rows)
            self.assertEqual(source.tip(), (0, genesis.header.hash))
            self.assertEqual(
                source.load_block_body(genesis.header.hash).serialize(),
                genesis.serialize(),
            )


if __name__ == '__main__':
    unittest.main()
