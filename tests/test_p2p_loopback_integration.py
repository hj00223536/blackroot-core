import asyncio
import unittest

from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import decode_compact_target, check_proof_of_work
from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_header_sync import PeerHeaderSync
from src.blackroot_p2p_manager import PeerManager
from src.blackroot_p2p_sync_coordinator import PeerSyncCoordinator

MAGIC = bytes.fromhex("b2a1c3d4")
BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def genesis():
    for nonce in range(10000):
        header = BlockHeader(1, ZERO_HASH, b"g" * 32, 1, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("unable to mine test genesis")


def version(nonce):
    return VersionMessage(1, 0, 1_800_000_000, nonce, 0, "/blackroot:loopback/")


class LoopbackSyncIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.chain = HeaderChain(POW_LIMIT, genesis())
        self.server_sync = PeerSyncCoordinator(
            PeerHeaderSync(self.chain, protocol_version=1, adjusted_time=lambda: 1_800_000_000)
        )
        self.client_sync = PeerSyncCoordinator(
            PeerHeaderSync(self.chain, protocol_version=1, adjusted_time=lambda: 1_800_000_000)
        )
        self.headers_received = asyncio.Event()

        def client_handler(peer):
            dispatch = self.client_sync.bind(peer)
            async def handle(command, payload):
                await dispatch(command, payload)
                if command == "headers":
                    self.headers_received.set()
            return handle
        self.server = PeerManager(
            magic=MAGIC, local_version=version(11), max_peers=2,
            handshake_timeout=2, idle_timeout=5,
            on_peer_message_factory=self.server_sync.bind,
        )
        self.client = PeerManager(
            magic=MAGIC, local_version=version(22), max_peers=2,
            handshake_timeout=2, idle_timeout=5,
            on_peer_message_factory=client_handler,
        )

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_two_nodes_handshake_and_exchange_getheaders(self):
        host, port, *_ = await self.server.start_server("127.0.0.1", 0)
        outbound = await self.client.connect(host, port)

        async def connected():
            return outbound.connected and self.server.peer_count == 1 and self.server.peers[0].connected

        async def wait_connected():
            while not await connected():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_connected(), timeout=2)
        await self.client_sync.header_sync.request_headers(outbound)

        # The remote coordinator answers with a valid empty headers message.
        await asyncio.wait_for(self.headers_received.wait(), timeout=2)
        self.assertTrue(outbound.connected)
        self.assertEqual(self.server.peer_count, 1)
        self.assertEqual(self.client_sync.header_sync._last_locator[0], self.chain.get(0).hash)
