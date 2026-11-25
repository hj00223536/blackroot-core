import struct
import unittest

from src.blackroot_p2p_getheaders import (
    MAX_BLOCK_LOCATOR_HASHES,
    GetHeadersMessage,
    decode_getheaders,
    encode_getheaders,
)


class GetHeadersCodecTests(unittest.TestCase):
    def test_round_trip_empty_and_populated_locator(self):
        messages = [
            GetHeadersMessage(1, (), b"s" * 32),
            GetHeadersMessage(70001, (b"a" * 32, b"b" * 32), b"z" * 32),
        ]
        for message in messages:
            self.assertEqual(decode_getheaders(encode_getheaders(message)), message)

    def test_rejects_truncated_and_trailing_payloads(self):
        encoded = encode_getheaders(GetHeadersMessage(1, (b"a" * 32,), b"z" * 32))
        with self.assertRaisesRegex(ValueError, "truncated"):
            decode_getheaders(encoded[:-1])
        with self.assertRaisesRegex(ValueError, "trailing"):
            decode_getheaders(encoded + b"x")

    def test_rejects_noncanonical_and_excessive_locator(self):
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            decode_getheaders(struct.pack("<i", 1) + b"\xfd\x01\x00" + b"z" * 32)
        excessive = struct.pack("<i", 1) + bytes((MAX_BLOCK_LOCATOR_HASHES + 1,))
        with self.assertRaisesRegex(ValueError, "locator exceeds"):
            decode_getheaders(excessive + b"z" * 32)

    def test_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            GetHeadersMessage(0, (), b"z" * 32)
        with self.assertRaises(ValueError):
            GetHeadersMessage(1, (b"short",), b"z" * 32)
        with self.assertRaises(ValueError):
            GetHeadersMessage(1, (), b"short")


if __name__ == "__main__":
    unittest.main()
