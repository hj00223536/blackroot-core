import asyncio
import struct
import unittest

from src.blackroot_p2p import encode_message
from src.blackroot_p2p_handshake import VersionMessage, encode_version
from src.blackroot_p2p_transport import PeerConnection, PeerProtocolError

MAGIC = bytes.fromhex("b2a1c3d4")


class FakeWriter:
    def __init__(self):
        self.frames = []
        self.closed = False

    def write(self, data):
        self.frames.append(data)

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


def version(nonce, protocol=1):
    return VersionMessage(protocol, 0, 1_800_000_000, nonce, 0, "/blackroot:test/")


class PeerConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.writer = FakeWriter()
        self.peer = PeerConnection(
            asyncio.StreamReader(),
            self.writer,
            magic=MAGIC,
            local_version=version(101),
        )

    def test_rejects_boolean_minimum_protocol_version(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            PeerConnection(
                asyncio.StreamReader(),
                FakeWriter(),
                magic=MAGIC,
                local_version=version(101),
                min_protocol_version=True,
            )

    def test_rejects_non_finite_or_boolean_timeouts(self):
        for timeout in (float("nan"), float("inf"), float("-inf"), True, 0, -1):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(ValueError, "finite positive"):
                    PeerConnection(
                        asyncio.StreamReader(),
                        FakeWriter(),
                        magic=MAGIC,
                        local_version=version(101),
                        handshake_timeout=timeout,
                    )

    async def test_version_verack_handshake_completes(self):
        await self.peer.send("version", encode_version(version(101)))
        self.peer.handshake.mark_local_version_sent()
        await self.peer.handle_message("version", encode_version(version(202)))
        self.assertEqual(self.peer.remote_version.nonce, 202)
        self.assertEqual(self.peer.handshake.local_verack_sent, True)
        self.assertEqual(len(self.writer.frames), 2)
        self.peer.handshake.receive_verack(b"")
        self.assertTrue(self.peer.connected)

    async def test_rejects_oversized_version_before_reading_payload(self):
        reader = asyncio.StreamReader()
        reader.feed_data(
            MAGIC + b"version" + bytes(5) + struct.pack("<I", 291) + bytes(4)
        )
        with self.assertRaisesRegex(PeerProtocolError, "version payload exceeds"):
            await self.peer._read_message()
        self.assertEqual(len(reader._buffer), 0)

    async def test_rejects_wrong_control_payload_length_before_reading_body(self):
        for command, length in (("verack", 1), ("ping", 7), ("pong", 9)):
            with self.subTest(command=command, length=length):
                reader = asyncio.StreamReader()
                command_field = command.encode("ascii").ljust(12, b"\\x00")
                reader.feed_data(
                    MAGIC + command_field + struct.pack("<I", length) + bytes(4)
                )
                peer = PeerConnection(
                    reader, FakeWriter(), magic=MAGIC, local_version=version(101)
                )
                with self.assertRaisesRegex(PeerProtocolError, "payload must be exactly"):
                    await peer._read_message()
                self.assertEqual(len(reader._buffer), 0)

    async def test_rejects_block_and_headers_over_limits_before_body_read(self):
        cases = (
            ("block", 1_000_001),
            ("headers", 3 + 2_000 * 81 + 1),
        )
        for command, length in cases:
            with self.subTest(command=command, length=length):
                reader = asyncio.StreamReader()
                command_field = command.encode("ascii").ljust(12, b"\\x00")
                reader.feed_data(
                    MAGIC + command_field + struct.pack("<I", length) + bytes(4)
                )
                peer = PeerConnection(
                    reader, FakeWriter(), magic=MAGIC, local_version=version(101)
                )
                with self.assertRaisesRegex(PeerProtocolError, "command-specific limit"):
                    await peer._read_message()
                self.assertEqual(len(reader._buffer), 0)

    async def test_rejects_oversized_inventory_before_body_read(self):
        reader = asyncio.StreamReader()
        maximum = 5 + 50_000 * 36
        command_field = b"inv" + bytes(9)
        reader.feed_data(
            MAGIC + command_field + struct.pack("<I", maximum + 1) + bytes(4)
        )
        peer = PeerConnection(
            reader, FakeWriter(), magic=MAGIC, local_version=version(101)
        )
        with self.assertRaisesRegex(PeerProtocolError, "command-specific limit"):
            await peer._read_message()
        self.assertEqual(len(reader._buffer), 0)

    async def test_rejects_application_message_before_handshake(self):
        with self.assertRaisesRegex(PeerProtocolError, "before handshake"):
            await self.peer.handle_message("ping", struct.pack("<Q", 7))

    async def test_ping_is_answered_with_same_nonce(self):
        self.peer.handshake.local_version_sent = True
        self.peer.handshake.remote_version = version(202)
        self.peer.handshake.local_verack_sent = True
        self.peer.handshake.remote_verack_received = True
        self.peer.handshake._refresh_complete()
        nonce = struct.pack("<Q", 0x123456789)
        await self.peer.handle_message("ping", nonce)
        self.assertEqual(
            self.writer.frames[-1],
            encode_message(MAGIC, "pong", nonce),
        )

    async def test_rejects_malformed_ping_and_pong(self):
        self.peer.handshake.local_version_sent = True
        self.peer.handshake.remote_version = version(202)
        self.peer.handshake.local_verack_sent = True
        self.peer.handshake.remote_verack_received = True
        self.peer.handshake._refresh_complete()
        with self.assertRaisesRegex(PeerProtocolError, "ping payload"):
            await self.peer.handle_message("ping", b"x")
        with self.assertRaisesRegex(PeerProtocolError, "pong payload"):
            await self.peer.handle_message("pong", b"x")

    async def test_rejects_unsupported_protocol_version(self):
        await self.peer.send("version", encode_version(version(101)))
        self.peer.handshake.mark_local_version_sent()
        self.peer.min_protocol_version = 2
        with self.assertRaisesRegex(PeerProtocolError, "unsupported"):
            await self.peer.handle_message("version", encode_version(version(202, protocol=1)))

    async def test_application_messages_are_forwarded_after_handshake(self):
        received = []
        self.peer.on_message = lambda command, payload: received.append((command, payload))
        self.peer.handshake.local_version_sent = True
        self.peer.handshake.remote_version = version(202)
        self.peer.handshake.local_verack_sent = True
        self.peer.handshake.remote_verack_received = True
        self.peer.handshake._refresh_complete()
        await self.peer.handle_message("headers", b"payload")
        self.assertEqual(received, [("headers", b"payload")])

    async def test_close_is_idempotent(self):
        await self.peer.close()
        await self.peer.close()
        self.assertTrue(self.writer.closed)


if __name__ == "__main__":
    unittest.main()
