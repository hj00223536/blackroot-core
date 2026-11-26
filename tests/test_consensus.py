import unittest

from src.blackroot_consensus import (
    COIN,
    MAX_MONEY,
    block_subsidy,
    check_proof_of_work,
    decode_compact_target,
    format_hash,
    serialize_header,
    sha256d,
)
from src.blackroot_monetary import (
    BLOCK_SUBSIDY,
    LAST_MINING_HEIGHT,
    MINING_ALLOCATION,
    mining_issuance_through_height,
)


class SubsidyTests(unittest.TestCase):
    def test_fixed_subsidy_and_boundaries(self):
        self.assertEqual(block_subsidy(0), 0)
        self.assertEqual(block_subsidy(1), 10 * COIN)
        self.assertEqual(block_subsidy(LAST_MINING_HEIGHT), 10 * COIN)
        self.assertEqual(block_subsidy(LAST_MINING_HEIGHT + 1), 0)
        self.assertEqual(BLOCK_SUBSIDY, 10 * COIN)

    def test_invalid_height(self):
        for height in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                block_subsidy(height)

    def test_full_scheduled_mining_issuance_equals_mining_allocation(self):
        self.assertEqual(
            mining_issuance_through_height(LAST_MINING_HEIGHT),
            MINING_ALLOCATION,
        )
        self.assertEqual(MAX_MONEY, 40_000_000 * COIN)
        self.assertEqual(
            mining_issuance_through_height(LAST_MINING_HEIGHT) + 20_000_000 * COIN,
            MAX_MONEY,
        )


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

    def test_reject_compact_target_overflow_encodings(self):
        for bits in (0x23000001, 0x22000100, 0x21010001):
            with self.subTest(bits=hex(bits)):
                with self.assertRaises(ValueError):
                    decode_compact_target(bits)

    def test_reject_compact_target_outside_uint32(self):
        for bits in (-1, 0x1_0000_0000, True):
            with self.subTest(bits=bits):
                with self.assertRaises(ValueError):
                    decode_compact_target(bits)


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
        bits = 0x1F3FFFFF
        limit = decode_compact_target(0x207FFFFF)
        previous_target = decode_compact_target(bits)
        target_span = 2016 * 600
        quarter_bits = retarget_compact(bits, 1, limit, target_span)
        exact_quarter_bits = retarget_compact(bits, target_span // 4, limit, target_span)
        nominal_bits = retarget_compact(bits, target_span, limit, target_span)
        double_bits = retarget_compact(bits, target_span * 2, limit, target_span)
        exact_four_x_bits = retarget_compact(bits, target_span * 4, limit, target_span)
        four_x_bits = retarget_compact(bits, target_span * 20, limit, target_span)
        self.assertEqual(quarter_bits, 0x1F0FFFFF)
        self.assertEqual(exact_quarter_bits, quarter_bits)
        self.assertEqual(nominal_bits, 0x1F3FFFFF)
        self.assertEqual(double_bits, 0x1F7FFFFE)
        self.assertEqual(exact_four_x_bits, 0x2000FFFF)
        self.assertEqual(four_x_bits, exact_four_x_bits)
        quarter_target = decode_compact_target(quarter_bits)
        self.assertLessEqual(quarter_target, previous_target // 4)
        self.assertLess((previous_target // 4) - quarter_target, 1 << 224)
        self.assertEqual(decode_compact_target(nominal_bits), previous_target)
        self.assertLessEqual(decode_compact_target(double_bits), previous_target * 2)
        self.assertLessEqual(decode_compact_target(four_x_bits), min(previous_target * 4, limit))

    def test_retarget_caps_new_target_at_pow_limit(self):
        from src.blackroot_consensus import retarget_compact
        limit_bits = 0x207FFFFF
        limit = decode_compact_target(limit_bits)
        harder_bits = 0x1F3FFFFF
        self.assertEqual(
            retarget_compact(limit_bits, 2016 * 600 * 4, limit),
            limit_bits,
        )
        with self.assertRaisesRegex(ValueError, "previous target exceeds"):
            retarget_compact(limit_bits, 2016 * 600, limit - 1)
        result = retarget_compact(harder_bits, 2016 * 600 * 4, limit)
        self.assertLessEqual(decode_compact_target(result), limit)

    def test_retarget_uses_integer_floor_before_compact_encoding(self):
        from src.blackroot_consensus import encode_compact_target, retarget_compact

        bits = 0x1F3FFFFF
        previous_target = decode_compact_target(bits)
        target_span = 1_000
        actual_timespan = 333
        expected_target = previous_target * actual_timespan // target_span
        expected_bits = encode_compact_target(expected_target)

        self.assertEqual(
            retarget_compact(bits, actual_timespan, decode_compact_target(0x207FFFFF), target_span),
            expected_bits,
        )

    def test_retarget_fails_closed_if_integer_floor_would_make_zero_target(self):
        from src.blackroot_consensus import retarget_compact

        # A deliberately tiny synthetic target exercises the arithmetic edge.
        # Current behavior rejects a zero result rather than inventing a minimum.
        with self.assertRaisesRegex(ValueError, "target must be a positive uint256"):
            retarget_compact(
                0x01010000,
                actual_timespan=1,
                pow_limit=decode_compact_target(0x207FFFFF),
                target_timespan=4,
            )

    def test_retarget_rejects_bad_inputs(self):
        from src.blackroot_consensus import retarget_compact
        bits = 0x207FFFFF
        limit = decode_compact_target(bits)
        for actual in (0, -1, True):
            with self.assertRaises(ValueError):
                retarget_compact(bits, actual, limit)
        for target_span in (0, -1, True):
            with self.assertRaises(ValueError):
                retarget_compact(bits, 600, limit, target_span)
        with self.assertRaises(ValueError):
            retarget_compact(bits, 600, decode_compact_target(0x207FFFFF) - 1)


if __name__ == "__main__":
    unittest.main()
