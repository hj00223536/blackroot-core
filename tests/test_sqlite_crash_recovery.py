import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_reorg_atomicity import POW_LIMIT, mined_block
from src.blackroot_chain import HeaderChain, ZERO_HASH
from src.blackroot_utxo_db import UTXOStore


class SQLiteCrashRecoveryTests(unittest.TestCase):
    def test_abrupt_process_exit_rolls_back_uncommitted_chain_state(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "chain.sqlite"
            store = UTXOStore(database)
            genesis = mined_block(0, ZERO_HASH, 1)
            chain = HeaderChain(POW_LIMIT, genesis.header)
            store.connect_validated_block(genesis, 0, chain)
            expected_tip = store.tip()
            expected_headers = store.active_block_headers()
            with store._connect() as db:
                expected_utxos = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp FROM utxos ORDER BY txid, output_index"
                ).fetchall()

            crash_script = (
                "import os, sqlite3, sys; "
                "db=sqlite3.connect(sys.argv[1]); "
                "db.execute('PRAGMA foreign_keys=ON'); "
                "db.execute('BEGIN IMMEDIATE'); "
                "db.execute('DELETE FROM utxos'); "
                "db.execute('DELETE FROM blocks'); "
                "os._exit(73)"
            )
            result = subprocess.run(
                [sys.executable, "-c", crash_script, str(database)],
                check=False,
            )
            self.assertEqual(result.returncode, 73)

            reopened = UTXOStore(database)
            self.assertEqual(reopened.tip(), expected_tip)
            self.assertEqual(reopened.active_block_headers(), expected_headers)
            with reopened._connect() as db:
                recovered_utxos = db.execute(
                    "SELECT txid, output_index, value, script_pubkey, created_height, is_coinbase, created_mtp FROM utxos ORDER BY txid, output_index"
                ).fetchall()
            self.assertEqual(recovered_utxos, expected_utxos)
            reopened.verify_integrity()


if __name__ == "__main__":
    unittest.main()
