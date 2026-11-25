import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.test_reorg_atomicity import POW_LIMIT, mined_block
from src.blackroot_chain import HeaderChain, ZERO_HASH
from src.blackroot_utxo_db import UTXOStore


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
            with source._connect() as db:
                expected_utxos = db.execute(
                    'SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp FROM utxos ORDER BY txid, output_index'
                ).fetchall()
            with sqlite3.connect(source_path) as source_db:
                with sqlite3.connect(backup_path) as backup_db:
                    source_db.backup(backup_db)
            restored = UTXOStore(backup_path)
            self.assertEqual(restored.tip(), expected_tip)
            self.assertEqual(restored.active_block_headers(), expected_headers)
            with restored._connect() as db:
                restored_utxos = db.execute(
                    'SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp FROM utxos ORDER BY txid, output_index'
                ).fetchall()
            self.assertEqual(restored_utxos, expected_utxos)
            restored_body = restored.load_block_body(genesis.header.hash)
            self.assertIsNotNone(restored_body)
            self.assertEqual(restored_body.serialize(), genesis.serialize())
            restored.verify_integrity()


if __name__ == '__main__':
    unittest.main()
