import unittest

from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import decode_compact_target

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine_header(prev_hash, timestamp):
    for nonce in range(1000):
        candidate = BlockHeader(
            version=1,
            prev_hash=prev_hash,
            merkle_root=bytes([timestamp % 256]) * 32,
            timestamp=timestamp,
            bits=BITS,
            nonce=nonce,
        )
        from src.blackroot_consensus import check_proof_of_work
        if check_proof_of_work(candidate.serialize(), BITS, POW_LIMIT):
            return candidate
    raise AssertionError("test nonce search unexpectedly exhausted")


class HeaderChainTests(unittest.TestCase):
    def test_accepts_linked_headers(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)
        next_header = mine_header(genesis.hash, 2)
        chain.add(next_header)
        self.assertEqual(chain.height, 1)
        self.assertEqual(chain.tip.hash, next_header.hash)

    def test_rejects_wrong_parent(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)
        wrong_parent = mine_header(bytes([1]) * 32, 2)
        with self.assertRaisesRegex(ValueError, "does not extend"):
            chain.add(wrong_parent)

    def test_rejects_non_increasing_timestamp(self):
        genesis = mine_header(ZERO_HASH, 5)
        chain = HeaderChain(POW_LIMIT, genesis)
        same_time = mine_header(genesis.hash, 5)
        with self.assertRaisesRegex(ValueError, "timestamp"):
            chain.add(same_time)

    def test_rejects_target_above_pow_limit(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT // 2, genesis)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            chain.add(mine_header(genesis.hash, 2))


if __name__ == "__main__":
    unittest.main()
