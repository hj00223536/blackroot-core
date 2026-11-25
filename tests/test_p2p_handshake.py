import struct
import unittest

from src.blackroot_p2p_handshake import (
    MAX_USER_AGENT_BYTES,
    VersionMessage,
    decode_version,
    encode_version,
)


class VersionHandshakeCodecTests(unittest.TestCase):
    def test_round_trip_ascii_and_unicode_user_agents(self):
        for agent in ("/blackroot:0.1/", "/جذر:0.1/"):
            message = VersionMessage(1, 3, 1_800_000_000, 42, 123, agent)
            self.assertEqual(decode_version(encode_version(message)), message)

    def test_rejects_truncated_and_trailing_payloads(self):
        payload = encode_version(VersionMessage(1, 0, 0, 1, 0, ""))
        with self.assertRaisesRegex(ValueError, "truncated"):
            decode_version(payload[:-1])
        with self.assertRaisesRegex(ValueError, "length mismatch"):
            decode_version(payload + b"x")

    def test_rejects_oversized_user_agent_before_decode(self):
        payload = struct.pack("<iQqQiH", 1, 0, 0, 1, 0, MAX_USER_AGENT_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            decode_version(payload)

    def test_rejects_invalid_utf8_and_control_characters(self):
        payload = struct.pack("<iQqQiH", 1, 0, 0, 1, 0, 1) + b"\xff"
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            decode_version(payload)
        with self.assertRaisesRegex(ValueError, "control"):
            VersionMessage(1, 0, 0, 1, 0, "bad\nagent")

    def test_rejects_out_of_range_fields(self):
        invalid = (
            {"protocol_version": 0, "services": 0, "timestamp": 0, "nonce": 0, "start_height": 0, "user_agent": ""},
            {"protocol_version": 1, "services": -1, "timestamp": 0, "nonce": 0, "start_height": 0, "user_agent": ""},
            {"protocol_version": 1, "services": 0, "timestamp": 0, "nonce": 0, "start_height": -1, "user_agent": ""},
        )
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                VersionMessage(**fields)


if __name__ == "__main__":
    unittest.main()
