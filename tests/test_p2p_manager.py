import asyncio
import unittest

from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_manager import PeerManager

MAGIC = bytes.fromhex("b2a1c3d4")


def version():
    return VersionMessage(1, 0, 1_800_000_000, 42, 0, "/blackroot:test/")


class PeerManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server_manager = PeerManager(
            magic=MAGIC, local_version=version(), max_peers=2,
            handshake_timeout=1, idle_timeout=5,
        )
        self.client_manager = PeerManager(
            magic=MAGIC, local_version=version(), max_peers=2,
            handshake_timeout=1, idle_timeout=5,
        )

    async def asyncTearDown(self):
        await self.client_manager.close()
        await self.server_manager.close()

    async def test_inbound_and_outbound_peers_complete_handshake(self):
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        outbound = await self.client_manager.connect(host, port)

        async def wait_connected():
            while not (outbound.connected and self.server_manager.peer_count == 1):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_connected(), timeout=2)
        inbound = self.server_manager.peers[0]
        self.assertTrue(inbound.connected)
        self.assertTrue(outbound.connected)
        self.assertNotEqual(
            inbound.handshake.local_version.nonce,
            outbound.handshake.local_version.nonce,
        )

    async def test_enforces_outbound_peer_limit(self):
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        await self.client_manager.connect(host, port)
        await self.client_manager.connect(host, port)
        with self.assertRaisesRegex(RuntimeError, "maximum peer count"):
            await self.client_manager.connect(host, port)

    async def test_disconnect_callback_runs_for_removed_peer(self):
        disconnected = []
        callback_done = asyncio.Event()

        async def on_disconnected(peer):
            disconnected.append(peer)
            callback_done.set()

        self.server_manager.on_peer_disconnected = on_disconnected
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        outbound = await self.client_manager.connect(host, port)

        async def wait_connected():
            while not (outbound.connected and self.server_manager.peer_count == 1):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_connected(), timeout=2)
        await self.client_manager.close()
        await asyncio.wait_for(callback_done.wait(), timeout=2)
        self.assertEqual(len(disconnected), 1)
        self.assertFalse(disconnected[0].connected)

    async def test_close_stops_listener_and_removes_peers(self):
        await self.server_manager.start_server("127.0.0.1", 0)
        self.assertTrue(self.server_manager.listening)
        await self.server_manager.close()
        self.assertFalse(self.server_manager.listening)
        self.assertEqual(self.server_manager.peer_count, 0)


if __name__ == "__main__":
    unittest.main()
