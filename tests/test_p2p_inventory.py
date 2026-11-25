import unittest

from src.blackroot_p2p_inventory import (
    INV_TYPE_BLOCK,
    INV_TYPE_TX,
    MAX_INVENTORY_ITEMS,
    InventoryVector,
    decode_inventory,
    encode_inventory,
)


class InventoryCodecTests(unittest.TestCase):
    def test_round_trip_empty_and_multiple_vectors(self):
        vectors = [
            InventoryVector(INV_TYPE_TX, b"t" * 32),
            InventoryVector(INV_TYPE_BLOCK, b"b" * 32),
        ]
        self.assertEqual(decode_inventory(encode_inventory([])), [])
        self.assertEqual(decode_inventory(encode_inventory(vectors)), vectors)

    def test_rejects_truncated_and_trailing_payloads(self):
        encoded = encode_inventory([InventoryVector(INV_TYPE_BLOCK, b"x" * 32)])
        with self.assertRaisesRegex(ValueError, "truncated"):
            decode_inventory(encoded[:-1])
        with self.assertRaisesRegex(ValueError, "trailing"):
            decode_inventory(encoded + b"x")

    def test_rejects_noncanonical_and_excessive_counts(self):
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            decode_inventory(b"\xfd\x01\x00")
        excessive = b"\xfd" + MAX_INVENTORY_ITEMS.to_bytes(2, "little") + b"\x00"
        with self.assertRaisesRegex(ValueError, "count exceeds"):
            decode_inventory(excessive)

    def test_rejects_unsupported_types_and_bad_hashes(self):
        with self.assertRaises(ValueError):
            InventoryVector(99, b"x" * 32)
        with self.assertRaises(ValueError):
            InventoryVector(INV_TYPE_TX, b"x")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            decode_inventory(b"\x01" + (99).to_bytes(4, "little") + b"x" * 32)

    def test_rejects_wrong_input_types(self):
        with self.assertRaises(TypeError):
            encode_inventory(())
        with self.assertRaises(TypeError):
            decode_inventory(bytearray())


if __name__ == "__main__":
    unittest.main()
