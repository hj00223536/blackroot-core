import unittest
from unittest.mock import Mock

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import decode_compact_target, check_proof_of_work
from src.blackroot_p2p_block_sync import BlockBodyRequestTracker
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine(previous, timestamp, root):
    for nonce in range(10000):
        header = BlockHeader(1, previous, root, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("nonce search exhausted")


def make_genesis_block():
    coinbase = Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), b"\x01\x01"),),
        (TxOutput(1, b"miner"),),
    )
    header = mine(ZERO_HASH, 1, merkle_root([coinbase.txid]))
    return Block(header, (coinbase,))


class BlockBodyRequestTrackerTests(unittest.TestCase):
    def setUp(self):
        self.block = make_genesis_block()
        self.chain = HeaderChain(POW_LIMIT, self.block.header)
        self.tracker = BlockBodyRequestTracker(max_outstanding=1)
        self.store = Mock()
        self.store.connect_validated_block.return_value = 7

    def test_requests_and_connects_matching_body(self):
        height = self.tracker.request(self.block.header.hash, self.chain)
        self.assertEqual(height, 0)
        result = self.tracker.accept_payload(
            self.block.header.hash, self.block.serialize(), self.chain, self.store
        )
        self.assertEqual(result, (0, 7))
        self.store.connect_validated_block.assert_called_once()
        self.assertEqual(self.tracker.pending_hashes, ())

    def test_rejects_unsolicited_body(self):
        with self.assertRaisesRegex(ValueError, "unsolicited"):
            self.tracker.accept_payload(
                self.block.header.hash, self.block.serialize(), self.chain, self.store
            )
        self.store.connect_validated_block.assert_not_called()

    def test_rejects_body_for_different_requested_hash(self):
        self.tracker.request(self.block.header.hash, self.chain)
        other_header = mine(ZERO_HASH, 2, self.block.header.merkle_root)
        other_block = Block(other_header, self.block.transactions)
        with self.assertRaisesRegex(ValueError, "does not match requested"):
            self.tracker.accept_payload(
                self.block.header.hash, other_block.serialize(), self.chain, self.store
            )
        self.assertEqual(self.tracker.pending_hashes, (self.block.header.hash,))
        self.store.connect_validated_block.assert_not_called()

    def test_rejects_malformed_body_and_keeps_request(self):
        self.tracker.request(self.block.header.hash, self.chain)
        with self.assertRaises(ValueError):
            self.tracker.accept_payload(
                self.block.header.hash, b"bad", self.chain, self.store
            )
        self.assertEqual(self.tracker.pending_hashes, (self.block.header.hash,))
        self.store.connect_validated_block.assert_not_called()

    def test_failed_connection_keeps_request_for_retry(self):
        self.tracker.request(self.block.header.hash, self.chain)
        self.store.connect_validated_block.side_effect = ValueError("invalid body")
        with self.assertRaisesRegex(ValueError, "invalid body"):
            self.tracker.accept_payload(
                self.block.header.hash, self.block.serialize(), self.chain, self.store
            )
        self.assertEqual(self.tracker.pending_hashes, (self.block.header.hash,))

    def test_enforces_outstanding_limit_and_duplicate_requests(self):
        self.tracker.request(self.block.header.hash, self.chain)
        with self.assertRaisesRegex(ValueError, "already outstanding"):
            self.tracker.request(self.block.header.hash, self.chain)
        self.assertEqual(len(self.tracker.pending_hashes), 1)

    def test_rejects_unknown_header(self):
        with self.assertRaisesRegex(ValueError, "unknown header"):
            self.tracker.request(bytes.fromhex("66" * 32), self.chain)

    def test_expire_returns_only_stale_requests(self):
        now = [10.0]
        tracker = BlockBodyRequestTracker(max_outstanding=2, clock=lambda: now[0])
        tracker.request(self.block.header.hash, self.chain)
        self.assertEqual(tracker.expire(5, now=14.9), ())
        self.assertEqual(tracker.expire(5, now=15.0), (self.block.header.hash,))
        self.assertEqual(tracker.pending_hashes, ())

    def test_cancel_is_idempotent(self):
        self.tracker.request(self.block.header.hash, self.chain)
        self.assertTrue(self.tracker.cancel(self.block.header.hash))
        self.assertFalse(self.tracker.cancel(self.block.header.hash))


if __name__ == "__main__":
    unittest.main()
