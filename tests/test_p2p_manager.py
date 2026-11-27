import asyncio
import unittest

from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_manager import PeerManager

MAGIC = bytes.fromhex("b2a1c3d4")


def version():
    return VersionMessage(1, 0, 1_800_000_000, 42, 0, "/blackroot:test/")


class PeerManagerConfigurationTests(unittest.TestCase):
    def test_rejects_non_finite_boolean_and_non_positive_timeouts(self):
        for name in ("connect_timeout", "handshake_timeout", "idle_timeout"):
            for value in (True, float("nan"), float("inf"), float("-inf"), 0, -1):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, "finite positive"):
                        PeerManager(magic=MAGIC, local_version=version(), **{name: value})

    def test_rejects_invalid_payload_limits(self):
        for value in (True, -1, "100", 2**32):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "max_payload"):
                    PeerManager(magic=MAGIC, local_version=version(), max_payload=value)

    def test_rejects_invalid_minimum_protocol_version(self):
        for value in (True, 0, -1, "1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "minimum protocol"):
                    PeerManager(magic=MAGIC, local_version=version(), min_protocol_version=value)

    def test_rejects_invalid_rate_limit_settings(self):
        for name in (
            "control_messages_per_second",
            "control_message_burst",
            "data_messages_per_second",
            "data_message_burst",
            "data_bytes_per_second",
            "data_bytes_burst",
        ):
            for value in (True, 0, -1, float("nan"), float("inf")):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, "finite positive"):
                        PeerManager(
                            magic=MAGIC,
                            local_version=version(),
                            **{name: value},
                        )

    def test_rejects_non_callable_rate_limit_clock(self):
        with self.assertRaisesRegex(ValueError, "monotonic_clock must be callable"):
            PeerManager(
                magic=MAGIC,
                local_version=version(),
                monotonic_clock=123,
            )

    def test_rejects_non_callable_handlers(self):
        for kwargs in ({"on_message": 1}, {"on_peer_error": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TypeError):
                PeerManager(magic=MAGIC, local_version=version(), **kwargs)


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

    async def test_manager_propagates_rate_limits_to_inbound_and_outbound_peers(self):
        clock = lambda: 123.0
        self.server_manager = PeerManager(
            magic=MAGIC,
            local_version=version(),
            max_peers=2,
            handshake_timeout=1,
            idle_timeout=5,
            control_messages_per_second=3,
            control_message_burst=4,
            data_messages_per_second=5,
            data_message_burst=6,
            data_bytes_per_second=7,
            data_bytes_burst=8,
            monotonic_clock=clock,
        )
        self.client_manager = PeerManager(
            magic=MAGIC,
            local_version=version(),
            max_peers=2,
            handshake_timeout=1,
            idle_timeout=5,
            control_messages_per_second=9,
            control_message_burst=10,
            data_messages_per_second=11,
            data_message_burst=12,
            data_bytes_per_second=13,
            data_bytes_burst=14,
        )
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        outbound = await self.client_manager.connect(host, port)

        async def wait_connected():
            while not (outbound.connected and self.server_manager.peer_count == 1):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_connected(), timeout=2)
        inbound = self.server_manager.peers[0]
        self.assertEqual(outbound._control_message_bucket.rate, 9)
        self.assertEqual(outbound._data_message_bucket.capacity, 12)
        self.assertEqual(outbound._data_byte_bucket.rate, 13)
        self.assertEqual(inbound._control_message_bucket.rate, 3)
        self.assertEqual(inbound._data_message_bucket.capacity, 6)
        self.assertEqual(inbound._data_byte_bucket.rate, 7)
        self.assertIs(inbound._monotonic_clock, clock)

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
