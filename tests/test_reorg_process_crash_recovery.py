import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_reorg_atomicity import POW_LIMIT, mined_block
from src.blackroot_chain import HeaderChain, ZERO_HASH
from src.blackroot_utxo_db import UTXOStore


class ReorganizationProcessCrashRecoveryTests(unittest.TestCase):
    def test_process_exit_during_real_reorganization_restores_pre_reorg_state(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'chain.sqlite'
            store = UTXOStore(database)
            genesis = mined_block(0, ZERO_HASH, 1)
            old = mined_block(1, genesis.header.hash, 2)
            chain = HeaderChain(POW_LIMIT, genesis.header, adjusted_time_provider=lambda: 1_000_000)
            chain.add(old.header)
            store.connect_validated_block(genesis, 0, chain)
            store.connect_validated_block(old, 1, chain)

            fork_one = mined_block(1, genesis.header.hash, 3)
            fork_two = mined_block(2, fork_one.header.hash, 4)
            store.store_block_body(fork_one)
            store.store_block_body(fork_two)

            tables = (
                'blocks', 'block_transactions', 'block_undo_spent',
                'block_undo_created', 'utxos', 'block_bodies', 'metadata',
            )
            before = {}
            with store._connection_scope() as db:
                for table in tables:
                    before[table] = db.execute(
                        f'SELECT * FROM {table} ORDER BY 1, 2'
                    ).fetchall()

            crash_script = r'''
import os, sys
from tests.test_reorg_atomicity import POW_LIMIT, mined_block
from src.blackroot_chain import HeaderChain, ZERO_HASH
from src.blackroot_utxo_db import UTXOStore
database = sys.argv[1]
store = UTXOStore(database)
genesis = mined_block(0, ZERO_HASH, 1)
old = mined_block(1, genesis.header.hash, 2)
fork_one = mined_block(1, genesis.header.hash, 3)
fork_two = mined_block(2, fork_one.header.hash, 4)
chain = HeaderChain(POW_LIMIT, genesis.header, adjusted_time_provider=lambda: 1_000_000)
chain.add(old.header)
chain.add_to_branch(fork_one.header)
chain.add_to_branch(fork_two.header)
original = UTXOStore._advance_provenance
def crash_after_disconnect_and_candidate_validation(block, parent, height, created_mtp):
    result = original(block, parent, height, created_mtp)
    os._exit(74)
UTXOStore._advance_provenance = staticmethod(crash_after_disconnect_and_candidate_validation)
store.reorganize_to_best(chain)
raise SystemExit('expected abrupt exit did not occur')
'''
            result = subprocess.run(
                [sys.executable, '-c', crash_script, str(database)],
                check=False,
            )
            self.assertEqual(result.returncode, 74)

            recovered = UTXOStore(database)
            with recovered._connection_scope() as db:
                for table in tables:
                    after = db.execute(
                        f'SELECT * FROM {table} ORDER BY 1, 2'
                    ).fetchall()
                    self.assertEqual(after, before[table], table)
            recovered.verify_integrity()


if __name__ == '__main__':
    unittest.main()
