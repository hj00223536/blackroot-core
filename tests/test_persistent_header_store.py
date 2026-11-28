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

        reopened = self.open_store()
        self.assertEqual(reopened.chain.best_hash, expected_best)
        self.assertEqual(reopened.chain.height, 2)
        disconnect, connect = reopened.chain.reorganization(main_one.hash)
        self.assertEqual([h.hash for h in disconnect], [main_one.hash])
        self.assertEqual([h.hash for h in connect], [side_one.hash, side_two.hash])


    def test_add_to_branch_rejects_caller_supplied_time_override(self):
        store = self.open_store()
        child = mine(self.genesis.hash, 2)
        with self.assertRaisesRegex(ValueError, "must use its configured adjusted-time provider"):
            store.add_to_branch(child, adjusted_time=1_000_000)
        self.assertEqual(store.chain.height, 0)
        self.assertIsNone(store.chain.node(child.hash))

    def test_side_branch_rebuild_uses_one_clock_sample_per_admission(self):
        clock_calls = []
        store = PersistentHeaderStore(
            self.path,
            POW_LIMIT,
            self.genesis,
            adjusted_time_provider=lambda: clock_calls.append(1_000_000) or 1_000_000,
        )
        main = mine(self.genesis.hash, 2)
        side = mine(self.genesis.hash, 3)
        store.add_to_branch(main)
        self.assertEqual(len(clock_calls), 1)
        store.add_to_branch(side)
        self.assertEqual(len(clock_calls), 2)
        reopened = PersistentHeaderStore(
            self.path,
            POW_LIMIT,
            self.genesis,
            adjusted_time_provider=lambda: clock_calls.append(1_000_000) or 1_000_000,
        )
        self.assertEqual(reopened.chain.height, 1)
        self.assertEqual(len(clock_calls), 3)

    def test_persistent_admission_enforces_inclusive_future_time_boundary(self):
        clock_state = {"now": 1_000}
        store = PersistentHeaderStore(
            self.path,
            POW_LIMIT,
            self.genesis,
            adjusted_time_provider=lambda: clock_state["now"],
        )

        # The existing prototype's default 7,200-second allowance is inclusive.
        boundary = mine(self.genesis.hash, 8_200)
        store.add_to_branch(boundary)
        self.assertEqual(store.chain.height, 1)

        beyond = mine(boundary.hash, 8_201)
        before_nodes = tuple(store.chain.nodes)
        with self.assertRaisesRegex(ValueError, "future"):
            store.add_to_branch(beyond)

        self.assertEqual(tuple(store.chain.nodes), before_nodes)
        self.assertIsNone(store.chain.node(beyond.hash))

        reopened = PersistentHeaderStore(
            self.path,
            POW_LIMIT,
            self.genesis,
            adjusted_time_provider=lambda: clock_state["now"],
        )
        self.assertEqual(reopened.chain.height, 1)
        self.assertIsNotNone(reopened.chain.node(boundary.hash))
        self.assertIsNone(reopened.chain.node(beyond.hash))

    def test_clock_provider_failure_during_reload_preserves_live_chain(self):
        clock_state = {"broken": False}

        def clock():
            if clock_state["broken"]:
                raise RuntimeError("clock unavailable during replay")
            return 1_000_000

        store = PersistentHeaderStore(
            self.path, POW_LIMIT, self.genesis,
            adjusted_time_provider=clock,
        )
        child = mine(self.genesis.hash, 2)
        store.add_to_branch(child)
        before_chain = store.chain
        before_nodes = tuple(store.chain.nodes)
        before_tip = store.chain.best_hash
        before_work = store.chain.node(before_tip).chainwork

        clock_state["broken"] = True
        with self.assertRaisesRegex(RuntimeError, "clock unavailable during replay"):
            store.reload()

        self.assertIs(store.chain, before_chain)
        self.assertEqual(tuple(store.chain.nodes), before_nodes)
        self.assertEqual(store.chain.best_hash, before_tip)
        self.assertEqual(store.chain.node(before_tip).chainwork, before_work)

    def test_persist_chain_rejects_different_proof_of_work_limit(self):
        from src.blackroot_chain import HeaderChain

        store = self.open_store()
        foreign_chain = HeaderChain(POW_LIMIT + 1, self.genesis)
        with self.assertRaisesRegex(ValueError, "different proof-of-work limit"):
            store.persist_chain(foreign_chain)

    def test_persist_chain_rejects_different_adjusted_time_provider(self):
        from src.blackroot_chain import HeaderChain

        store = self.open_store()
        foreign_chain = HeaderChain(POW_LIMIT, self.genesis)
        with self.assertRaisesRegex(ValueError, "different adjusted-time provider"):
            store.persist_chain(foreign_chain)

    def test_persist_chain_rejects_test_only_unchecked_time_chain(self):
        from src.blackroot_chain import HeaderChain

        store = self.open_store()
        unchecked_chain = HeaderChain(
            POW_LIMIT, self.genesis, allow_unchecked_time_for_tests=True
        )
        with self.assertRaisesRegex(ValueError, "test-only unchecked-time"):
            store.persist_chain(unchecked_chain)

    def test_rejects_network_parameter_mismatch(self):
        self.open_store()
        with self.assertRaisesRegex(RuntimeError, "parameters do not match"):
            PersistentHeaderStore(self.path, POW_LIMIT - 1, self.genesis, adjusted_time_provider=lambda: 1_000_000)

    def test_replay_fails_closed_on_corrupt_chainwork(self):
        self.open_store()
        with managed_sqlite(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE headers SET chainwork='999' WHERE height=0")
        with self.assertRaisesRegex(RuntimeError, "metadata mismatch"):
            self.open_store()

    def test_replay_fails_closed_when_genesis_header_is_missing(self):
        self.open_store()
        with managed_sqlite(sqlite3.connect(self.path)) as db:
            db.execute("DELETE FROM headers WHERE block_hash=?", (self.genesis.hash,))
        with self.assertRaisesRegex(RuntimeError, "missing its genesis header"):
            self.open_store()

    def test_replay_fails_closed_when_header_rows_exist_without_metadata(self):
        self.open_store()
        with managed_sqlite(sqlite3.connect(self.path)) as db:
            db.execute("DELETE FROM header_metadata")

        with self.assertRaisesRegex(
            RuntimeError, "headers but no initialization metadata"
        ):
            self.open_store()

        with managed_sqlite(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM headers").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM header_metadata").fetchone()[0], 0
            )

    def test_stale_writer_fails_closed_after_concurrent_header_commit(self):
        first = self.open_store()
        stale = self.open_store()
        first_child = mine(self.genesis.hash, 2)
        stale_child = mine(self.genesis.hash, 3)

        first.add_to_branch(first_child)
        with self.assertRaisesRegex(RuntimeError, "changed concurrently"):
            stale.add_to_branch(stale_child)

        refreshed = self.open_store()
        refreshed.add_to_branch(stale_child)
        self.assertEqual(refreshed.chain.height, 1)
        self.assertIsNotNone(refreshed.chain.node(first_child.hash))
        self.assertIsNotNone(refreshed.chain.node(stale_child.hash))

    def test_duplicate_header_is_rejected_without_mutating_store(self):
        store = self.open_store()
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
                store = self.open_store(path, connection=connection)
            with self.assertRaisesRegex(RuntimeError, "abort header write"):
                with coordinator.transaction():
                    store.add_to_branch(child)
                    self.assertEqual(store.chain.height, 0)
                    raise RuntimeError("abort header write")
            self.assertEqual(store.reload().height, 0)
            self.assertEqual(store.chain.best_hash, self.genesis.hash)


    def test_clock_provider_failure_during_admission_preserves_live_and_durable_state(self):
        clock_state = {"broken": False}

        def clock():
            if clock_state["broken"]:
                raise RuntimeError("clock unavailable during admission")
            return 1_000_000

        store = PersistentHeaderStore(
            self.path, POW_LIMIT, self.genesis,
            adjusted_time_provider=clock,
        )
        accepted = mine(self.genesis.hash, 2)
        store.add_to_branch(accepted)
        before_nodes = tuple(store.chain.nodes)
        before_tip = store.chain.best_hash
        before_work = store.chain.chainwork

        clock_state["broken"] = True
        rejected = mine(accepted.hash, 3)
        with self.assertRaisesRegex(RuntimeError, "clock unavailable during admission"):
            store.add_to_branch(rejected)

        self.assertEqual(tuple(store.chain.nodes), before_nodes)
        self.assertEqual(store.chain.best_hash, before_tip)
        self.assertEqual(store.chain.chainwork, before_work)
        self.assertIsNone(store.chain.node(rejected.hash))

        clock_state["broken"] = False
        reopened = PersistentHeaderStore(
            self.path, POW_LIMIT, self.genesis,
            adjusted_time_provider=clock,
        )
        self.assertEqual(reopened.chain.best_hash, before_tip)
        self.assertIsNone(reopened.chain.node(rejected.hash))


    def test_replay_fails_closed_when_persisted_header_bytes_do_not_match_hash(self):
        store = self.open_store()
        child = mine(self.genesis.hash, 2)
        store.add_to_branch(child)
        with managed_sqlite(sqlite3.connect(self.path)) as db:
            db.execute(
                "UPDATE headers SET merkle_root=? WHERE block_hash=?",
                (bytes([0xA5]) * 32, child.hash),
            )

        with self.assertRaisesRegex(RuntimeError, "header hash mismatch"):
            self.open_store()

    def test_reload_corruption_does_not_replace_live_chain(self):
        store = self.open_store()
        child = mine(self.genesis.hash, 2)
        store.add_to_branch(child)
        before_chain = store.chain
        before_nodes = tuple(before_chain.nodes)
        before_tip = before_chain.best_hash

        with managed_sqlite(sqlite3.connect(self.path)) as db:
            db.execute(
                "UPDATE headers SET nonce=nonce+1 WHERE block_hash=?",
                (child.hash,),
            )

        with self.assertRaisesRegex(RuntimeError, "header hash mismatch"):
            store.reload()

        self.assertIs(store.chain, before_chain)
        self.assertEqual(tuple(store.chain.nodes), before_nodes)
        self.assertEqual(store.chain.best_hash, before_tip)


if __name__ == "__main__":
    unittest.main()
