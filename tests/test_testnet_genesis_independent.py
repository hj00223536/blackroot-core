"""Second, deliberately independent stdlib-only reproduction of the testnet
candidate vector. This guards byte order and serialization drift; it is not an
external audit or an independent client implementation.
"""
import hashlib
import struct
import unittest


def _sha256d(raw):
    return hashlib.sha256(hashlib.sha256(raw).digest()).digest()


def _compact_size(n):
    if n < 253:
        return bytes((n,))
    if n <= 0xffff:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xffffffff:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def _coinbase_bytes():
    # version, one null-prevout input, scriptSig 01 01, final sequence,
    # one zero-value OP_RETURN output, lock time.
    return (
        struct.pack("<i", 1)
        + _compact_size(1)
        + bytes(32)
        + struct.pack("<I", 0xffffffff)
        + _compact_size(2)
        + bytes.fromhex("0101")
        + struct.pack("<I", 0xffffffff)
        + _compact_size(1)
        + struct.pack("<Q", 0)
        + _compact_size(1)
        + b"\x6a"
        + struct.pack("<I", 0)
    )


class IndependentGenesisCandidateTests(unittest.TestCase):
    def test_stdlib_only_reproduction_of_candidate(self):
        tx = _coinbase_bytes()
        self.assertEqual(len(tx), 63)
        self.assertEqual(
            tx.hex(),
            "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff020101ffffffff010000000000000000016a00000000",
        )
        txid = _sha256d(tx)
        self.assertEqual(
            txid[::-1].hex(),
            "35993aaf3055dd3e72466a4724bf6a0c4d1ff340130266b3a1c71b100490a42e",
        )

        # One-leaf merkle tree is exactly the transaction's raw txid.
        merkle = txid
        header = (
            struct.pack("<I", 1)
            + bytes(32)
            + merkle
            + struct.pack("<III", 1_795_564_800, 0x207fffff, 0)
        )
        self.assertEqual(len(header), 80)
        self.assertEqual(
            header.hex(),
            "0100000000000000000000000000000000000000000000000000000000000000000000002ea49004101bc7a1b366021340f31f4d0c6abf24476a46723edd5530af3a99350025066bffff7f2000000000",
        )
        block_hash = _sha256d(header)
        self.assertEqual(
            block_hash[::-1].hex(),
            "12d0a70715fcc771e2228e8a8e2f85b4ada2b1bf2991c2a564553c0b9c922269",
        )

        target = 0x7fffff << (8 * (0x20 - 3))
        self.assertLessEqual(int.from_bytes(block_hash, "little"), target)


if __name__ == "__main__":
    unittest.main()
