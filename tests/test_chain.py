import unittest

from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import block_work, check_proof_of_work, decode_compact_target, encode_compact_target

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine_header(prev_hash, timestamp, bits=BITS, pow_limit=POW_LIMIT):
    for nonce in range(1000):
        candidate = BlockHeader(
            version=1,
            prev_hash=prev_hash,
            merkle_root=bytes([timestamp % 256]) * 32,
            timestamp=timestamp,
            bits=bits,
            nonce=nonce,
        )
        if check_proof_of_work(candidate.serialize(), bits, pow_limit):
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
        self.assertEqual(chain.chainwork, 2 * block_work(POW_LIMIT))

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

    def test_rejects_noncanonical_compact_target_alias(self):
        canonical_bits = 0x20007F00
        noncanonical_bits = 0x2100007F
        target = decode_compact_target(canonical_bits)
        self.assertEqual(decode_compact_target(noncanonical_bits), target)
        self.assertEqual(encode_compact_target(target), canonical_bits)
        genesis = mine_header(ZERO_HASH, 1, noncanonical_bits, POW_LIMIT)
        with self.assertRaisesRegex(ValueError, "non-canonical compact target"):
            HeaderChain(POW_LIMIT, genesis)

    def test_rejects_target_above_pow_limit(self):
        strict_bits = 0x201FFFFF
        strict_limit = decode_compact_target(strict_bits)
        genesis = mine_header(ZERO_HASH, 1, strict_bits, strict_limit)
        chain = HeaderChain(strict_limit, genesis)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            chain.add(mine_header(genesis.hash, 2, BITS, POW_LIMIT))


    def test_selects_longer_work_fork_and_reports_reorganization(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)

        old_branch = mine_header(genesis.hash, 2)
        chain.add(old_branch)
        old_tip = old_branch.hash

        side_one = mine_header(genesis.hash, 3)
        chain.add_to_branch(side_one)
        side_two = mine_header(side_one.hash, 4)
        chain.add_to_branch(side_two)

        self.assertEqual(chain.tip.hash, side_two.hash)
        self.assertEqual(chain.height, 2)
        disconnect, connect = chain.reorganization(old_tip)
        self.assertEqual([item.hash for item in disconnect], [old_branch.hash])
        self.assertEqual([item.hash for item in connect], [side_one.hash, side_two.hash])

    def test_rejects_unknown_parent_and_duplicate_header(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)
        with self.assertRaisesRegex(ValueError, "unknown parent"):
            chain.add_to_branch(mine_header(bytes.fromhex("55" * 32), 2))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            chain.add_to_branch(genesis)


    def test_median_time_past_allows_time_below_parent_timestamp(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)
        first = mine_header(genesis.hash, 100)
        chain.add(first)
        second = mine_header(first.hash, 200)
        chain.add(second)
        candidate = mine_header(second.hash, 150)
        chain.add(candidate)
        self.assertEqual(chain.tip.hash, candidate.hash)
        self.assertEqual(chain.median_time_past(candidate.hash), 150)

    def test_rejects_header_not_above_median_time_past(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)
        first = mine_header(genesis.hash, 100)
        chain.add(first)
        second = mine_header(first.hash, 200)
        chain.add(second)
        invalid = mine_header(second.hash, 100)
        with self.assertRaisesRegex(ValueError, "median-time-past"):
            chain.add(invalid)


    def test_enforces_difficulty_retarget_at_interval_boundary(self):
        from src.blackroot_consensus import DIFFICULTY_INTERVAL

        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)
        parent = genesis
        for height in range(1, DIFFICULTY_INTERVAL):
            parent = mine_header(parent.hash, 1 + height * 600)
            chain.add(parent)

        candidate_height = DIFFICULTY_INTERVAL
        required = chain.expected_bits(parent.hash, candidate_height)
        self.assertNotEqual(required, BITS)
        wrong = mine_header(parent.hash, 1 + candidate_height * 600, BITS)
        with self.assertRaisesRegex(ValueError, "difficulty bits"):
            chain.add(wrong)

        correct = mine_header(parent.hash, 1 + candidate_height * 600, required)
        chain.add(correct)
        self.assertEqual(chain.tip.hash, correct.hash)

    def test_non_boundary_height_requires_parent_bits(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)
        wrong_bits = 0x2070ffff
        wrong = mine_header(genesis.hash, 2, wrong_bits)
        with self.assertRaisesRegex(ValueError, "difficulty bits"):
            chain.add(wrong)


    def test_network_adjusted_future_time_limit_is_deterministic(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)
        too_far = mine_header(genesis.hash, 7_301)
        with self.assertRaisesRegex(ValueError, "future-time limit"):
            chain.add_to_branch(too_far, adjusted_time=1, max_future_seconds=7_200)

        accepted = mine_header(genesis.hash, 7_201)
        chain.add_to_branch(accepted, adjusted_time=1, max_future_seconds=7_200)
        self.assertEqual(chain.node(accepted.hash).height, 1)

    def test_future_time_limit_rejects_invalid_parameters(self):
        genesis = mine_header(ZERO_HASH, 1)
        chain = HeaderChain(POW_LIMIT, genesis)
        candidate = mine_header(genesis.hash, 2)
        with self.assertRaisesRegex(ValueError, "adjusted_time"):
            chain.add_to_branch(candidate, adjusted_time=-1)
        with self.assertRaisesRegex(ValueError, "max_future_seconds"):
            chain.add_to_branch(candidate, adjusted_time=1, max_future_seconds=-1)


if __name__ == "__main__":
    unittest.main()
