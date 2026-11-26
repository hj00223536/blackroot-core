import asyncio
import unittest

from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import check_proof_of_work, decode_compact_target
from src.blackroot_p2p_getheaders import GetHeadersMessage, decode_getheaders, encode_getheaders
from src.blackroot_p2p_headers import decode_headers, encode_headers
from src.blackroot_p2p_header_sync import PeerHeaderSync, build_block_locator

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine(prev_hash, timestamp):
    for nonce in range(1000):
        header = BlockHeader(1, prev_hash, bytes([timestamp % 256]) * 32, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("test mining exhausted")


class FakePeer:
    connected = True

    def __init__(self):
        self.sent = []

    async def send(self, command, payload):
        self.sent.append((command, payload))


class PeerHeaderSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.genesis = mine(ZERO_HASH, 1)
        self.chain = HeaderChain(POW_LIMIT, self.genesis, adjusted_time_provider=lambda: 100_000)
        self.sync = PeerHeaderSync(self.chain, protocol_version=70001, adjusted_time=lambda: 100_000)

    def test_locator_starts_at_tip_and_ends_at_genesis(self):
        parent = self.genesis
        for timestamp in range(2, 15):
            parent = mine(parent.hash, timestamp)
            self.chain.add(parent)
        locator = build_block_locator(self.chain)
        self.assertEqual(locator[0], self.chain.tip.hash)
        self.assertEqual(locator[-1], self.genesis.hash)
        self.assertEqual(len(locator), len(set(locator)))

    async def test_request_headers_sends_current_locator(self):
        peer = FakePeer()
        payload = await self.sync.request_headers(peer)
        self.assertEqual(peer.sent, [("getheaders", payload)])
        request = decode_getheaders(payload)
        self.assertEqual(request.locator_hashes[0], self.genesis.hash)
        self.assertEqual(request.stop_hash, ZERO_HASH)

    async def test_serves_headers_after_first_known_locator(self):
        first = mine(self.genesis.hash, 2)
        second = mine(first.hash, 3)
        self.chain.add(first)
        self.chain.add(second)
        request = GetHeadersMessage(70001, (b"x" * 32, self.genesis.hash), ZERO_HASH)
        response = self.sync.make_headers_response(encode_getheaders(request))
        self.assertEqual(decode_headers(response), [first, second])

    async def test_serves_empty_when_no_locator_matches(self):
        request = GetHeadersMessage(70001, (b"x" * 32,), ZERO_HASH)
        response = self.sync.make_headers_response(encode_getheaders(request))
        self.assertEqual(decode_headers(response), [])

    async def test_rejects_messages_before_handshake(self):
        peer = FakePeer()
        peer.connected = False
        with self.assertRaisesRegex(ConnectionError, "handshake"):
            await self.sync.handle_message(peer, "headers", encode_headers([]))

    async def test_header_sync_fails_closed_without_clock_provider(self):
        sync = PeerHeaderSync(self.chain, protocol_version=70001)
        with self.assertRaisesRegex(RuntimeError, "requires an adjusted-time provider"):
            await sync.handle_message(FakePeer(), "headers", encode_headers([]))

    async def test_header_sync_rejects_invalid_clock_value(self):
        sync = PeerHeaderSync(
            self.chain, protocol_version=70001, adjusted_time=lambda: -1
        )
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            await sync.handle_message(FakePeer(), "headers", encode_headers([]))

    async def test_header_sync_clock_provider_exception_does_not_mutate_chain(self):
        def broken_clock():
            raise RuntimeError("clock unavailable")

        sync = PeerHeaderSync(
            self.chain, protocol_version=70001, adjusted_time=broken_clock
        )
        candidate = mine(self.genesis.hash, 2)
        before_nodes = self.chain.nodes
        before_tip = self.chain.best_hash
        before_work = self.chain.chainwork

        with self.assertRaisesRegex(RuntimeError, "clock unavailable"):
            await sync.handle_message(
                FakePeer(), "headers", encode_headers([candidate])
            )

        self.assertEqual(self.chain.nodes, before_nodes)
        self.assertEqual(self.chain.best_hash, before_tip)
        self.assertEqual(self.chain.chainwork, before_work)
        self.assertIsNone(self.chain.node(candidate.hash))

    async def test_header_at_exact_future_time_boundary_is_accepted(self):
        boundary = mine(self.genesis.hash, 107_200)

        await self.sync.handle_message(
            FakePeer(), "headers", encode_headers([boundary])
        )

        self.assertIsNotNone(self.chain.node(boundary.hash))
        self.assertEqual(self.chain.best_hash, boundary.hash)

    async def test_future_header_is_rejected_without_mutating_chain(self):
        too_far = mine(self.genesis.hash, 107_201)
        before_nodes = self.chain.nodes
        before_tip = self.chain.best_hash
        before_work = self.chain.chainwork

        with self.assertRaisesRegex(ValueError, "future-time limit"):
            await self.sync.handle_message(
                FakePeer(), "headers", encode_headers([too_far])
            )

        self.assertEqual(self.chain.nodes, before_nodes)
        self.assertEqual(self.chain.best_hash, before_tip)
        self.assertEqual(self.chain.chainwork, before_work)
        self.assertIsNone(self.chain.node(too_far.hash))

    async def test_batch_with_valid_prefix_and_future_header_rolls_back_entire_batch(self):
        valid_prefix = mine(self.genesis.hash, 2)
        invalid_suffix = mine(valid_prefix.hash, 107_201)
        before_nodes = self.chain.nodes
        before_tip = self.chain.best_hash
        before_work = self.chain.chainwork

        with self.assertRaisesRegex(ValueError, "future-time limit"):
            await self.sync.handle_message(
                FakePeer(),
                "headers",
                encode_headers([valid_prefix, invalid_suffix]),
            )

        self.assertEqual(self.chain.nodes, before_nodes)
        self.assertEqual(self.chain.best_hash, before_tip)
        self.assertEqual(self.chain.chainwork, before_work)
        self.assertIsNone(self.chain.node(valid_prefix.hash))
        self.assertIsNone(self.chain.node(invalid_suffix.hash))

    async def test_rejects_unknown_sync_command(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            await self.sync.handle_message(FakePeer(), "inv", b"")


if __name__ == "__main__":
    unittest.main()
