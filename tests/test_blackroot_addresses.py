import unittest

from src.blackroot_addresses import (
    b58decode,
    b58encode,
    decode_base58check,
    encode_base58check,
    p2pkh_address,
    p2pkh_script_from_address,
)


class Base58Tests(unittest.TestCase):
    def test_base58_preserves_leading_zero_bytes(self):
        for raw in (b"", b"\x00", b"\x00\x00abc", bytes(range(1, 33))):
            self.assertEqual(b58decode(b58encode(raw)), raw)

    def test_base58_rejects_ambiguous_characters(self):
        for value in ("0", "O", "I", "l"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                b58decode(value)

    def test_base58_rejects_oversized_untrusted_input(self):
        with self.assertRaisesRegex(ValueError, "maximum length"):
            b58decode("1" * 513)

    def test_base58_accepts_documented_maximum_length(self):
        decoded = b58decode("1" * 512)
        self.assertEqual(len(decoded), 512)
        self.assertEqual(decoded, b"\x00" * 512)


class Base58CheckTests(unittest.TestCase):
    def test_round_trip_with_explicit_version(self):
        digest = bytes.fromhex("592fc3990026334c8c6fb2b9da457179cdb5c688")
        address = p2pkh_address(digest, version=0x26)
        self.assertEqual(
            decode_base58check(address, expected_version=0x26, payload_length=20),
            (0x26, digest),
        )

    def test_rejects_wrong_version(self):
        address = encode_base58check(0x26, b"\x11" * 20)
        with self.assertRaisesRegex(ValueError, "version"):
            decode_base58check(address, expected_version=0x00)

    def test_rejects_bad_checksum(self):
        address = encode_base58check(0x26, b"\x22" * 20)
        replacement = "1" if address[-1] != "1" else "2"
        with self.assertRaisesRegex(ValueError, "checksum"):
            decode_base58check(address[:-1] + replacement)

    def test_p2pkh_script_matches_hash(self):
        digest = bytes.fromhex("592fc3990026334c8c6fb2b9da457179cdb5c688")
        address = p2pkh_address(digest, version=0x26)
        script = p2pkh_script_from_address(address, expected_version=0x26)
        self.assertEqual(script, bytes.fromhex(
            "76a914592fc3990026334c8c6fb2b9da457179cdb5c68888ac"
        ))

    def test_rejects_wrong_payload_length(self):
        address = encode_base58check(0x26, b"short")
        with self.assertRaisesRegex(ValueError, "payload length"):
            p2pkh_script_from_address(address, expected_version=0x26)

    def test_requires_explicit_uint8_version(self):
        digest = b"\x33" * 20
        for version in (-1, 256, True, "38"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                p2pkh_address(digest, version=version)

    def test_requires_exact_hash160(self):
        for digest in (b"", b"\x00" * 19, b"\x00" * 21):
            with self.subTest(length=len(digest)), self.assertRaises(ValueError):
                p2pkh_address(digest, version=0x26)


if __name__ == "__main__":
    unittest.main()
