import unittest

from src.blackroot_consensus import (
    COIN,
    HALVING_INTERVAL,
    block_subsidy,
    check_proof_of_work,
    decode_compact_target,
    format_hash,
    serialize_header,
    sha256d,
)


class SubsidyTests(unittest.TestCase):
    def test_initial_and_halving_subsidies(self):
        self.assertEqual(block_subsidy(0), 50 * COIN)
        self.assertEqual(block_subsidy(HALVING_INTERVAL - 1), 50 * COIN)
        self.assertEqual(block_subsidy(HALVING_INTERVAL), 25 * COIN)
        self.assertEqual(block_subsidy(2 * HALVING_INTERVAL), 1_250_000_000)
        self.assertEqual(block_subsidy(64 * HALVING_INTERVAL), 0)

    def test_invalid_height(self):
        for height in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                block_subsidy(height)


class HashAndHeaderTests(unittest.TestCase):
    def test_sha256d_known_empty_vector(self):
        self.assertEqual(
            sha256d(b"").hex(),
            "5df6e0e2761359d30a8275058e299fcc0381534545f55cf43e41983f5d4c9456",
        )

    def test_header_is_80_bytes(self):
        header = serialize_header(1, bytes(32), bytes(32), 1, 0x207FFFFF, 0)
        self.assertEqual(len(header), 80)

    def test_reject_bad_hash_lengths(self):
        with self.assertRaises(ValueError):
            serialize_header(1, b"short", bytes(32), 1, 1, 0)

    def test_display_hash_reverses_bytes(self):
        self.assertEqual(format_hash(bytes(range(32))), bytes(range(32))[::-1].hex())


class TargetAndPowTests(unittest.TestCase):
    def test_decode_regtest_style_target(self):
        self.assertEqual(decode_compact_target(0x207FFFFF), 0x7FFFFF << (8 * 29))

    def test_reject_zero_and_negative_targets(self):
        for bits in (0, 0x01800001):
            with self.assertRaises(ValueError):
                decode_compact_target(bits)

    def test_pow_limit_is_enforced(self):
        header = serialize_header(1, bytes(32), bytes(32), 1, 0x207FFFFF, 0)
        self.assertFalse(check_proof_of_work(header, 0x207FFFFF, 1))


class RetargetAndWorkTests(unittest.TestCase):
    def test_compact_target_round_trip_for_regtest_limit(self):
        target = decode_compact_target(0x207FFFFF)
        from src.blackroot_consensus import encode_compact_target
        self.assertEqual(encode_compact_target(target), 0x207FFFFF)

    def test_block_work_decreases_as_target_increases(self):
        from src.blackroot_consensus import block_work
        easier = decode_compact_target(0x207FFFFF)
        harder = easier // 2
        self.assertGreater(block_work(harder), block_work(easier))

    def test_retarget_clamps_fast_and_slow_timespans(self):
        from src.blackroot_consensus import retarget_compact
        bits = 0x207FFFFF
        limit = decode_compact_target(bits)
        target_span = 2016 * 600
        quarter = decode_compact_target(retarget_compact(bits, 1, limit, target_span))
        four_x = decode_compact_target(retarget_compact(bits, target_span * 20, limit, target_span))
        self.assertEqual(quarter, limit // 4)
        self.assertEqual(four_x, limit)

    def test_retarget_rejects_bad_inputs(self):
        from src.blackroot_consensus import retarget_compact
        bits = 0x207FFFFF
        limit = decode_compact_target(bits)
        for actual in (0, -1, True):
            with self.assertRaises(ValueError):
                retarget_compact(bits, actual, limit)


if __name__ == "__main__":
    unittest.main()
