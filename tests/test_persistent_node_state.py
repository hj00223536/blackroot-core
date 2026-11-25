import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_node_state import PersistentNodeState
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore


BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine_header(prev_hash, merkle, timestamp):
    for nonce in range(10_000):
        header = BlockHeader(1, prev_hash, merkle, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("nonce search exhausted")


def coinbase(height):
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), script_sig=bytes([height + 1, 1])),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )


def make_block(previous, height, timestamp):
    tx = coinbase(height)
    header = mine_header(previous, merkle_root([tx.txid]), timestamp)
    return Block(header, (tx,))


class PersistentNodeStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.genesis_block = make_block(ZERO_HASH, 0, 1)

    def state(self):
        return PersistentNodeState(
            self.root / "headers.sqlite",
            self.root / "utxos.sqlite",
            POW_LIMIT,
            self.genesis_block.header,
        )

    def test_rejects_shared_header_and_utxo_database_path(self):
        shared = self.root / "shared.sqlite"
        with self.assertRaisesRegex(ValueError, "sharing a SQLite file"):
            PersistentNodeState(
                shared,
                shared,
                POW_LIMIT,
                self.genesis_block.header,
            )
        self.assertFalse(shared.exists())

    def test_rejects_recovery_journal_alias_of_utxo_database(self):
        shared = self.root / "utxos.sqlite"
        with self.assertRaisesRegex(ValueError, "recovery journal databases"):
            PersistentNodeState(
                self.root / "headers.sqlite",
                shared,
                POW_LIMIT,
                self.genesis_block.header,
                recovery_journal_path=shared,
            )
        self.assertFalse(shared.exists())

    def test_rejects_path_aliases_through_relative_components(self):
        headers = self.root / "headers.sqlite"
        alias = self.root / "nested" / ".." / "headers.sqlite"
        with self.assertRaisesRegex(ValueError, "header and UTXO databases"):
            PersistentNodeState(
                headers,
                alias,
                POW_LIMIT,
                self.genesis_block.header,
            )
        self.assertFalse(headers.exists())

    def test_rejects_hard_link_aliases_of_existing_database_files(self):
        original = self.root / "original.sqlite"
        alias = self.root / "hard-link.sqlite"
        original.write_bytes(b"existing database placeholder")
        alias.hardlink_to(original)
        with self.assertRaisesRegex(ValueError, "header and UTXO databases"):
            PersistentNodeState(
                original,
                alias,
                POW_LIMIT,
                self.genesis_block.header,
            )
        self.assertEqual(original.read_bytes(), b"existing database placeholder")

    def test_connects_and_recovers_matching_persistent_tip(self):
        state = self.state()
        self.assertEqual(state.connect_best_block(self.genesis_block, 0), 0)
        point = OutPoint(self.genesis_block.transactions[0].txid, 0)
        self.assertEqual(state.utxos.get(point), TxOutput(block_subsidy(0), b"miner"))

        reopened = self.state()
        self.assertEqual(reopened.utxos.tip(), (0, self.genesis_block.header.hash))
        self.assertEqual(reopened.headers.chain.node(self.genesis_block.header.hash).height, 0)

    def test_connect_best_block_archives_body_automatically(self):
        state = self.state()
        self.assertEqual(state.connect_best_block(self.genesis_block, 0), 0)
        reopened = UTXOStore(self.root / "utxos.sqlite")
        self.assertEqual(
            reopened.load_block_body(self.genesis_block.header.hash),
            self.genesis_block,
        )

    def test_archive_detects_merkle_corruption_after_storage(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        with sqlite3.connect(self.root / "utxos.sqlite") as db:
            db.execute(
                "UPDATE block_bodies SET raw_block=? WHERE block_hash=?",
                (self.genesis_block.serialize()[:-1] + bytes([self.genesis_block.serialize()[-1] ^ 1]),
                 self.genesis_block.header.hash),
            )
        with self.assertRaisesRegex(RuntimeError, "merkle root is corrupt"):
            state.utxos.load_block_body(self.genesis_block.header.hash)

    def test_recovers_when_persisted_headers_are_ahead_of_utxo_tip(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)

        candidate = make_block(self.genesis_block.header.hash, 1, 2)
        state.add_header(candidate.header, adjusted_time=2)

        # Simulate a crash after the header DB commit but before body/UTXO commit.
        reopened = self.state()
        self.assertEqual(
            reopened.utxos.tip(),
            (0, self.genesis_block.header.hash),
        )
        self.assertEqual(
            reopened.headers.chain.best_hash,
            candidate.header.hash,
        )

        # Recovery is explicit: supply the body, then let normal validation/reorg run.
        reopened.archive_block_body(candidate)
        self.assertEqual(
            reopened.reorganize_best(),
            (1, candidate.header.hash),
        )
        self.assertEqual(
            reopened.utxos.tip(),
            (1, candidate.header.hash),
        )

    def test_recovery_journal_discards_intent_when_utxo_commit_never_happened(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        candidate = make_block(self.genesis_block.header.hash, 1, 2)
        state.add_header(candidate.header, adjusted_time=2)
        old_tip = state.utxos.tip()
        new_tip = (1, candidate.header.hash)
        state.recovery_journal.prepare(old_tip, new_tip)

        reopened = self.state()
        self.assertEqual(reopened.utxos.tip(), old_tip)
        self.assertFalse(reopened.recovery_journal.pending())
        reopened.archive_block_body(candidate)
        self.assertEqual(reopened.reorganize_best(), new_tip)

    def test_recovery_journal_recognizes_utxo_commit_before_restart(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        candidate = make_block(self.genesis_block.header.hash, 1, 2)
        state.add_header(candidate.header, adjusted_time=2)
        old_tip = state.utxos.tip()
        new_tip = (1, candidate.header.hash)
        state.recovery_journal.prepare(old_tip, new_tip)

        # Simulate process death after the UTXO transaction committed but before
        # the journal intent could be cleared.
        state.utxos.store_block_body(candidate)
        state.utxos.connect_validated_block(candidate, 1, state.headers.chain)
        reopened = self.state()
        self.assertEqual(reopened.utxos.tip(), new_tip)
        self.assertFalse(reopened.recovery_journal.pending())

    def test_recovery_journal_fails_closed_on_unexpected_utxo_tip(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        first = make_block(self.genesis_block.header.hash, 1, 2)
        second = make_block(first.header.hash, 2, 3)
        state.add_header(first.header, adjusted_time=2)
        state.add_header(second.header, adjusted_time=3)
        state.recovery_journal.prepare(
            state.utxos.tip(), (1, first.header.hash)
        )
        state.utxos.store_block_body(first)
        state.utxos.connect_validated_block(first, 1, state.headers.chain)
        state.utxos.store_block_body(second)
        state.utxos.connect_validated_block(second, 2, state.headers.chain)

        with self.assertRaisesRegex(
            RuntimeError, "neither endpoint of pending recovery intent"
        ):
            self.state()

    def test_reorganizes_to_archived_best_branch_after_reopen(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)

        first = make_block(self.genesis_block.header.hash, 1, 2)
        second = make_block(first.header.hash, 2, 3)
        state.add_header(first.header, adjusted_time=2)
        state.add_header(second.header, adjusted_time=3)
        state.archive_block_body(first)
        state.archive_block_body(second)

        reopened = self.state()
        self.assertEqual(reopened.reorganize_best(), (2, second.header.hash))
        self.assertEqual(reopened.utxos.tip(), (2, second.header.hash))
        self.assertEqual(reopened.utxos.load_block_body(first.header.hash), first)
        self.assertEqual(reopened.utxos.load_block_body(second.header.hash), second)

    def test_reorganization_revalidates_archived_candidate_body(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)

        bad_coinbase = Transaction(
            1,
            (TxInput(OutPoint(ZERO_HASH, 0xFFFFFFFF), script_sig=b"\\x02\\x01"),),
            (TxOutput(block_subsidy(1) + 1, b"miner"),),
        )
        bad_header = mine_header(
            self.genesis_block.header.hash,
            merkle_root([bad_coinbase.txid]),
            2,
        )
        bad_block = Block(bad_header, (bad_coinbase,))
        state.add_header(bad_header, adjusted_time=2)
        state.archive_block_body(bad_block)

        reopened = self.state()
        with self.assertRaisesRegex(ValueError, "coinbase reward exceeds"):
            reopened.reorganize_best()
        self.assertEqual(
            reopened.utxos.tip(),
            (0, self.genesis_block.header.hash),
        )

    def test_reorganization_fails_closed_on_corrupt_archived_body(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        candidate = make_block(self.genesis_block.header.hash, 1, 2)
        state.add_header(candidate.header, adjusted_time=2)
        state.archive_block_body(candidate)

        raw = candidate.serialize()
        corrupted = raw[:-1] + bytes([raw[-1] ^ 1])
        with sqlite3.connect(self.root / "utxos.sqlite") as db:
            db.execute(
                "UPDATE block_bodies SET raw_block=? WHERE block_hash=?",
                (corrupted, candidate.header.hash),
            )

        reopened = self.state()
        with self.assertRaisesRegex(RuntimeError, "merkle root is corrupt"):
            reopened.reorganize_best()
        self.assertEqual(
            reopened.utxos.tip(),
            (0, self.genesis_block.header.hash),
        )

    def test_refuses_to_archive_body_for_unknown_header(self):
        state = self.state()
        unknown = make_block(ZERO_HASH, 0, 2)
        with self.assertRaisesRegex(ValueError, "unknown header"):
            state.archive_block_body(unknown)

    def test_rejects_invalid_height_before_header_chain_comparison(self):
        state = self.state()
        for invalid_height in (True, -1, "0", 0.5):
            with self.subTest(height=invalid_height):
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    state.connect_best_block(self.genesis_block, invalid_height)
        self.assertIsNone(state.utxos.tip())

    def test_refuses_body_not_selected_by_persistent_headers(self):
        state = self.state()
        other = make_block(ZERO_HASH, 0, 2)
        with self.assertRaisesRegex(ValueError, "not selected"):
            state.connect_best_block(other, 0)
        self.assertIsNone(state.utxos.tip())

    def test_startup_fails_closed_when_persisted_body_header_is_corrupt(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        with sqlite3.connect(self.root / "utxos.sqlite") as db:
            db.execute("UPDATE blocks SET header=? WHERE height=0", (b"corrupt",))
        with self.assertRaisesRegex(RuntimeError, "block header does not match"):
            self.state()

    def test_startup_fails_closed_when_active_block_sequence_has_a_gap(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        second = make_block(self.genesis_block.header.hash, 1, 2)
        state.add_header(second.header, adjusted_time=2)
        state.connect_best_block(second, 1)
        with sqlite3.connect(self.root / "utxos.sqlite") as db:
            db.execute("DELETE FROM blocks WHERE height=0")
        with self.assertRaisesRegex(RuntimeError, "heights are not contiguous"):
            self.state()

    def test_startup_fails_closed_when_active_parent_link_is_corrupt(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        second = make_block(self.genesis_block.header.hash, 1, 2)
        state.add_header(second.header, adjusted_time=2)
        state.connect_best_block(second, 1)
        with sqlite3.connect(self.root / "utxos.sqlite") as db:
            db.execute("UPDATE blocks SET prev_hash=? WHERE height=1", (bytes([0x11]) * 32,))
        with self.assertRaisesRegex(RuntimeError, "parent linkage is corrupt"):
            self.state()

    def test_startup_fails_closed_when_utxo_tip_is_not_in_header_dag(self):
        other = make_block(ZERO_HASH, 0, 2)
        UTXOStore(self.root / "utxos.sqlite").connect_block(other, 0)
        with self.assertRaisesRegex(RuntimeError, "absent or inconsistent"):
            self.state()


    def test_startup_fails_closed_when_active_transaction_record_is_corrupt(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        with sqlite3.connect(self.root / "utxos.sqlite") as db:
            db.execute(
                "UPDATE block_transactions SET raw_transaction=? WHERE height=0 AND position=0",
                (b"corrupt",),
            )
        with self.assertRaisesRegex(RuntimeError, "stored active transaction is malformed"):
            self.state()

    def test_archived_body_corruption_is_detected_when_body_is_loaded(self):
        state = self.state()
        state.connect_best_block(self.genesis_block, 0)
        raw = self.genesis_block.serialize()
        with sqlite3.connect(self.root / "utxos.sqlite") as db:
            db.execute(
                "UPDATE block_bodies SET raw_block=? WHERE block_hash=?",
                (raw[:-1] + bytes([raw[-1] ^ 1]), self.genesis_block.header.hash),
            )
        reopened = self.state()
        with self.assertRaisesRegex(RuntimeError, "archived block body merkle root is corrupt"):
            reopened.utxos.load_block_body(self.genesis_block.header.hash)


if __name__ == "__main__":
    unittest.main()
