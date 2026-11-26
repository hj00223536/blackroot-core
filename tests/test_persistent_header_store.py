import sqlite3
from contextlib import contextmanager
import tempfile
import unittest
from pathlib import Path

from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_consensus import check_proof_of_work, decode_compact_target
from src.blackroot_header_store import PersistentHeaderStore
from src.blackroot_sqlite import SQLiteTransactionCoordinator

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine(prev_hash, timestamp):
    for nonce in range(10_000):
        header = BlockHeader(1, prev_hash, bytes([timestamp % 256]) * 32,
                             timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("nonce search exhausted")



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

class PersistentHeaderStoreTests(unittest.TestCase):
    def open_store(self, path=None, *, connection=None):
        return PersistentHeaderStore(
            self.path if path is None else path,
            POW_LIMIT,
            self.genesis,
            connection=connection,
            adjusted_time_provider=lambda: 1_000_000,
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "headers.sqlite"
        self.genesis = mine(ZERO_HASH, 1)

    def tearDown(self):
        self.temp.cleanup()

    def test_reopens_and_replays_best_chain_and_side_branches(self):
        store = self.open_store()
        main_one = mine(self.genesis.hash, 2)
        store.add_to_branch(main_one)
        side_one = mine(self.genesis.hash, 3)
        store.add_to_branch(side_one)
        side_two = mine(side_one.hash, 4)
        store.add_to_branch(side_two)
        expected_best = store.chain.best_hash
        self.assertEqual(expected_best, side_two.hash)
        expected_nodes = sorted(
            [(0, self.genesis.hash), (1, main_one.hash), (1, side_one.hash), (2, side_two.hash)],
            key=lambda item: (item[0], item[1]),
        )
        self.assertEqual(
            [(node.height, node.header.hash) for node in store.chain.nodes],
            expected_nodes,
        )

        reopened = PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)
        self.assertEqual(reopened.chain.best_hash, expected_best)
        self.assertEqual(reopened.chain.height, 2)
        disconnect, connect = reopened.chain.reorganization(main_one.hash)
        self.assertEqual([h.hash for h in disconnect], [main_one.hash])
        self.assertEqual([h.hash for h in connect], [side_one.hash, side_two.hash])

    def test_rejects_network_parameter_mismatch(self):
        PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)
        with self.assertRaisesRegex(RuntimeError, "parameters do not match"):
            PersistentHeaderStore(self.path, POW_LIMIT - 1, self.genesis)

    def test_replay_fails_closed_on_corrupt_chainwork(self):
        PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)
        with managed_sqlite(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE headers SET chainwork='999' WHERE height=0")
        with self.assertRaisesRegex(RuntimeError, "metadata mismatch"):
            PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)

    def test_replay_fails_closed_when_genesis_header_is_missing(self):
        PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)
        with managed_sqlite(sqlite3.connect(self.path)) as db:
            db.execute("DELETE FROM headers WHERE block_hash=?", (self.genesis.hash,))
        with self.assertRaisesRegex(RuntimeError, "missing its genesis header"):
            PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)

    def test_stale_writer_fails_closed_after_concurrent_header_commit(self):
        first = PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)
        stale = PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)
        first_child = mine(self.genesis.hash, 2)
        stale_child = mine(self.genesis.hash, 3)

        first.add_to_branch(first_child)
        with self.assertRaisesRegex(RuntimeError, "changed concurrently"):
            stale.add_to_branch(stale_child)

        refreshed = PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)
        refreshed.add_to_branch(stale_child)
        self.assertEqual(refreshed.chain.height, 1)
        self.assertIsNotNone(refreshed.chain.node(first_child.hash))
        self.assertIsNotNone(refreshed.chain.node(stale_child.hash))

    def test_duplicate_header_is_rejected_without_mutating_store(self):
        store = PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)
        child = mine(self.genesis.hash, 2)
        store.add_to_branch(child)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            store.add_to_branch(child)
        self.assertEqual(store.chain.height, 1)
        with managed_sqlite(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM headers").fetchone()[0], 2)

    def test_coordinator_owned_header_store_publishes_after_commit_and_reload(self):
        path = Path(self.temp.name) / "shared.sqlite"
        child = mine(self.genesis.hash, 2)
        with SQLiteTransactionCoordinator(path) as coordinator:
            with coordinator.transaction() as connection:
                store = self.open_store(path, connection=connection)
            with coordinator.transaction():
                store.add_to_branch(child)
                self.assertEqual(store.chain.height, 0)
            self.assertEqual(store.reload().height, 1)
            self.assertEqual(store.chain.best_hash, child.hash)
        reopened = self.open_store(path)
        self.assertEqual(reopened.chain.best_hash, child.hash)

    def test_outer_rollback_does_not_publish_coordinated_header(self):
        path = Path(self.temp.name) / "rollback-shared.sqlite"
        child = mine(self.genesis.hash, 2)
        with SQLiteTransactionCoordinator(path) as coordinator:
            with coordinator.transaction() as connection:
                store = PersistentHeaderStore(
                    path, POW_LIMIT, self.genesis, connection=connection
                )
            with self.assertRaisesRegex(RuntimeError, "abort header write"):
                with coordinator.transaction():
                    store.add_to_branch(child)
                    self.assertEqual(store.chain.height, 0)
                    raise RuntimeError("abort header write")
            self.assertEqual(store.reload().height, 0)
            self.assertEqual(store.chain.best_hash, self.genesis.hash)


if __name__ == "__main__":
    unittest.main()
