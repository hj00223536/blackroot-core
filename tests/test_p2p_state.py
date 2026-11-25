import unittest

from src.blackroot_p2p_handshake import VersionMessage, encode_version
from src.blackroot_p2p_state import PeerHandshake, encode_local_version


def version(nonce, height=0):
    return VersionMessage(1, 0, 1_800_000_000, nonce, height, "/blackroot:test/")


class PeerHandshakeStateTests(unittest.TestCase):
    def test_handshake_completes_only_after_both_version_and_verack_directions(self):
        state = PeerHandshake(version(11))
        local_payload = encode_local_version(state)
        self.assertEqual(local_payload, encode_version(version(11)))
        self.assertFalse(state.complete)

        remote = state.receive_version(encode_version(version(22, 7)))
        self.assertEqual(remote.nonce, 22)
        self.assertFalse(state.complete)

        state.mark_local_verack_sent()
        self.assertFalse(state.complete)
        state.receive_verack(b"")
        self.assertTrue(state.complete)

    def test_rejects_verack_before_remote_version(self):
        state = PeerHandshake(version(11))
        encode_local_version(state)
        with self.assertRaisesRegex(ValueError, "before remote version"):
            state.receive_verack(b"")

    def test_rejects_self_connection(self):
        state = PeerHandshake(version(11))
        encode_local_version(state)
        with self.assertRaisesRegex(ValueError, "self-connection"):
            state.receive_version(encode_version(version(11)))

    def test_rejects_duplicate_messages_and_nonempty_verack(self):
        state = PeerHandshake(version(11))
        encode_local_version(state)
        remote = encode_version(version(22))
        state.receive_version(remote)
        with self.assertRaisesRegex(ValueError, "already received"):
            state.receive_version(remote)
        with self.assertRaisesRegex(ValueError, "must be empty"):
            state.receive_verack(b"x")
        state.mark_local_verack_sent()
        state.receive_verack(b"")
        with self.assertRaisesRegex(ValueError, "already received"):
            state.receive_verack(b"")

    def test_rejects_verack_send_before_local_version(self):
        state = PeerHandshake(version(11))
        state.receive_version(encode_version(version(22)))
        with self.assertRaisesRegex(ValueError, "before local version"):
            state.mark_local_verack_sent()

    def test_local_version_send_is_single_use(self):
        state = PeerHandshake(version(11))
        encode_local_version(state)
        with self.assertRaisesRegex(ValueError, "already sent"):
            encode_local_version(state)


if __name__ == "__main__":
    unittest.main()
