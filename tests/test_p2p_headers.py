import unittest

from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_p2p_headers import (
    MAX_HEADERS_PER_MESSAGE,
    decode_headers,
    encode_headers,
)


def header(previous, timestamp):
    return BlockHeader(1, previous, bytes([timestamp % 256]) * 32, timestamp, 0x207fffff, timestamp)


class HeadersMessageCodecTests(unittest.TestCase):
    def test_round_trip_empty_and_multiple_headers(self):
        first = header(ZERO_HASH, 1)
        second = header(first.hash, 2)
        self.assertEqual(decode_headers(encode_headers([])), [])
        self.assertEqual(decode_headers(encode_headers([first, second])), [first, second])

    def test_rejects_truncated_header_and_trailing_bytes(self):
        encoded = encode_headers([header(ZERO_HASH, 1)])
        with self.assertRaisesRegex(ValueError, "truncated"):
            decode_headers(encoded[:-1])
        with self.assertRaisesRegex(ValueError, "trailing"):
            decode_headers(encoded + b"x")

    def test_rejects_nonzero_transaction_count(self):
        encoded = bytearray(encode_headers([header(ZERO_HASH, 1)]))
        encoded[-1] = 1
        with self.assertRaisesRegex(ValueError, "must be zero"):
            decode_headers(bytes(encoded))

    def test_rejects_noncanonical_count_and_excessive_count(self):
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            decode_headers(b"\xfd\x01\x00")
        too_many = b"\xfd" + (MAX_HEADERS_PER_MESSAGE + 1).to_bytes(2, "little")
        with self.assertRaisesRegex(ValueError, "header limit"):
            decode_headers(too_many)

    def test_rejects_wrong_types_and_too_many_encoded_headers(self):
        with self.assertRaises(TypeError):
            encode_headers((header(ZERO_HASH, 1),))
        with self.assertRaises(ValueError):
            encode_headers([header(ZERO_HASH, i) for i in range(MAX_HEADERS_PER_MESSAGE + 1)])


if __name__ == "__main__":
    unittest.main()
