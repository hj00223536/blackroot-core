import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_consensus import check_proof_of_work, decode_compact_target
from src.blackroot_header_store import PersistentHeaderStore

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine(prev_hash, timestamp):
    for nonce in range(10_000):
        header = BlockHeader(1, prev_hash, bytes([timestamp % 256]) * 32,
                             timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("nonce search exhausted")


class PersistentHeaderStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "headers.sqlite"
        self.genesis = mine(ZERO_HASH, 1)

    def tearDown(self):
        self.temp.cleanup()

    def test_reopens_and_replays_best_chain_and_side_branches(self):
        store = PersistentHeaderStore(self.path, POW_LIMIT, self.genesis)
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
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE headers SET chainwork='999' WHERE height=0")
        with self.assertRaisesRegex(RuntimeError, "metadata mismatch"):
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
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM headers").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
