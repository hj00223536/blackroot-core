import ipaddress
import unittest

from src.blackroot_p2p_addr import (
    MAX_ADDRESSES_PER_MESSAGE,
    PeerAddress,
    decode_addr,
    decode_getaddr,
    encode_addr,
    encode_getaddr,
)


class PeerAddressCodecTests(unittest.TestCase):
    def test_round_trip_ipv4_and_ipv6(self):
        addresses = [
            PeerAddress(1_800_000_000, 1, ipaddress.ip_address("192.0.2.10"), 8333),
            PeerAddress(1_800_000_001, 9, ipaddress.ip_address("2001:db8::1"), 18333),
        ]
        self.assertEqual(decode_addr(encode_addr(addresses)), addresses)

    def test_ipv4_mapped_ipv6_normalizes_to_ipv4(self):
        address = PeerAddress(1, 0, ipaddress.ip_address("::ffff:192.0.2.1"), 8333)
        decoded = decode_addr(encode_addr([address]))
        self.assertEqual(decoded[0].ip, ipaddress.ip_address("192.0.2.1"))

    def test_empty_and_getaddr(self):
        self.assertEqual(decode_addr(encode_addr([])), [])
        self.assertEqual(encode_getaddr(), b"")
        self.assertIsNone(decode_getaddr(b""))
        with self.assertRaisesRegex(ValueError, "empty"):
            decode_getaddr(b"x")

    def test_rejects_truncated_and_trailing_payloads(self):
        encoded = encode_addr([PeerAddress(1, 0, ipaddress.ip_address("127.0.0.1"), 8333)])
        with self.assertRaisesRegex(ValueError, "truncated"):
            decode_addr(encoded[:-1])
        with self.assertRaisesRegex(ValueError, "trailing"):
            decode_addr(encoded + b"x")

    def test_rejects_noncanonical_and_excessive_counts(self):
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            decode_addr(b"\xfd\x01\x00")
        excessive = b"\xfd" + (MAX_ADDRESSES_PER_MESSAGE + 1).to_bytes(2, "little")
        with self.assertRaisesRegex(ValueError, "count exceeds"):
            decode_addr(excessive)

    def test_rejects_invalid_address_fields(self):
        with self.assertRaises(ValueError):
            PeerAddress(-1, 0, ipaddress.ip_address("127.0.0.1"), 8333)
        with self.assertRaises(ValueError):
            PeerAddress(0, 0, ipaddress.ip_address("127.0.0.1"), 0)


if __name__ == "__main__":
    unittest.main()
