import asyncio
import unittest

from src.blackroot_p2p import encode_message
from src.blackroot_p2p_handshake import VersionMessage, encode_version
from src.blackroot_p2p_handshake_v2 import Version2Message, decode_version2, encode_version2
from src.blackroot_p2p_transport import PeerConnection, PeerProtocolError

MAGIC = bytes.fromhex("b2a1c3d4")
NETWORK = bytes.fromhex("11" * 32)
GENESIS = bytes.fromhex("22" * 32)
OTHER_NETWORK = bytes.fromhex("33" * 32)
OTHER_GENESIS = bytes.fromhex("44" * 32)


class FakeWriter:
    def __init__(self):
        self.frames = []
        self.closed = False

    def write(self, frame):
        self.frames.append(frame)

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


def version(nonce, protocol=7):
    return VersionMessage(protocol, 0, 1_800_000_000, nonce, 0, "/blackroot:v2/")


class Version2CodecTests(unittest.TestCase):
    def test_round_trip_identity_and_version_fields(self):
        message = Version2Message(NETWORK, GENESIS, version(42))
        self.assertEqual(decode_version2(encode_version2(message)), message)

    def test_rejects_truncated_marker_and_bad_identity_width(self):
        with self.assertRaisesRegex(ValueError, "truncated"):
            decode_version2(b"BRP2" + bytes(63))
        with self.assertRaisesRegex(ValueError, "marker"):
            decode_version2(b"NOPE" + NETWORK + GENESIS + encode_version(version(42)))
        with self.assertRaisesRegex(ValueError, "network_id"):
            Version2Message(b"short", GENESIS, version(42))
        with self.assertRaisesRegex(ValueError, "genesis_hash"):
            Version2Message(NETWORK, b"short", version(42))


class Version2TransportTests(unittest.IsolatedAsyncioTestCase):
    def make_peer(self, on_message=None):
        self.writer = FakeWriter()
        self.peer = PeerConnection(
            asyncio.StreamReader(), self.writer, magic=MAGIC,
            local_version=version(101), min_protocol_version=7,
            network_id=NETWORK, genesis_hash=GENESIS, on_message=on_message,
        )
        self.peer.handshake.mark_local_version_sent()
        return self.peer

    async def test_matching_identity_completes_and_dispatches_only_after_verack(self):
        received = []
        peer = self.make_peer(lambda command, payload: received.append((command, payload)))
        payload = encode_version2(Version2Message(NETWORK, GENESIS, version(202)))
        await peer.handle_message("version2", payload)
        self.assertEqual(len(self.writer.frames), 1)
        self.assertFalse(peer.connected)
        await peer.handle_message("verack", b"")
        self.assertTrue(peer.connected)
        await peer.handle_message("headers", b"header-data")
        self.assertEqual(received, [("headers", b"header-data")])

    async def test_same_magic_different_network_id_rejected_before_verack(self):
        peer = self.make_peer()
        payload = encode_version2(Version2Message(OTHER_NETWORK, GENESIS, version(202)))
        with self.assertRaisesRegex(PeerProtocolError, "network_id mismatch"):
            await peer.handle_message("version2", payload)
        self.assertEqual(self.writer.frames, [])
        self.assertIsNone(peer.remote_version)
        self.assertFalse(peer.connected)

    async def test_same_magic_and_network_different_genesis_rejected(self):
        peer = self.make_peer()
        payload = encode_version2(Version2Message(NETWORK, OTHER_GENESIS, version(202)))
        with self.assertRaisesRegex(PeerProtocolError, "genesis_hash mismatch"):
            await peer.handle_message("version2", payload)
        self.assertEqual(self.writer.frames, [])
        self.assertIsNone(peer.remote_version)
        self.assertFalse(peer.connected)

    async def test_legacy_version_fallback_is_rejected(self):
        peer = self.make_peer()
        with self.assertRaisesRegex(PeerProtocolError, "legacy version-1"):
            await peer.handle_message("version", encode_version(version(202)))
        self.assertEqual(self.writer.frames, [])
        self.assertFalse(peer.connected)

    async def test_version_must_match_exactly_in_v2(self):
        peer = self.make_peer()
        payload = encode_version2(Version2Message(NETWORK, GENESIS, version(202, protocol=8)))
        with self.assertRaisesRegex(PeerProtocolError, "exact match"):
            await peer.handle_message("version2", payload)
        self.assertEqual(self.writer.frames, [])

    async def test_v2_command_requires_local_identity_configuration(self):
        writer = FakeWriter()
        peer = PeerConnection(asyncio.StreamReader(), writer, magic=MAGIC, local_version=version(101))
        peer.handshake.mark_local_version_sent()
        payload = encode_version2(Version2Message(NETWORK, GENESIS, version(202)))
        with self.assertRaisesRegex(PeerProtocolError, "not configured"):
            await peer.handle_message("version2", payload)

    async def test_identity_configuration_must_be_complete(self):
        with self.assertRaisesRegex(ValueError, "configured together"):
            PeerConnection(
                asyncio.StreamReader(), FakeWriter(), magic=MAGIC,
                local_version=version(101), network_id=NETWORK,
            )


if __name__ == "__main__":
    unittest.main()
