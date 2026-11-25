import unittest

from src.blackroot_consensus import (
    COIN,
    HALVING_INTERVAL,
    MAX_MONEY,
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


    def test_full_scheduled_issuance_stays_below_max_money(self):
        # Each halving epoch contains exactly HALVING_INTERVAL block heights.
        # Integer truncation eventually makes the subsidy zero.
        total_issuance = sum(
            HALVING_INTERVAL * block_subsidy(epoch * HALVING_INTERVAL)
            for epoch in range(64)
        )
        self.assertEqual(total_issuance, 2_099_999_997_690_000)
        self.assertEqual(total_issuance, 20_999_999 * COIN + 97_690_000)
        self.assertLess(total_issuance, MAX_MONEY)
        self.assertEqual(block_subsidy(32 * HALVING_INTERVAL), 1)
        self.assertEqual(block_subsidy(33 * HALVING_INTERVAL), 0)


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
        # Bitcoin-style SetCompact overflow boundaries: exponent 35 always
        # overflows for a non-zero mantissa; exponent 34 overflows above 0xff.
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
        bits = 0x207FFFFF
        limit = decode_compact_target(bits)
        target_span = 2016 * 600
        quarter_bits = retarget_compact(bits, 1, limit, target_span)
        nominal_bits = retarget_compact(bits, target_span, limit, target_span)
        double_bits = retarget_compact(bits, target_span * 2, limit, target_span)
        four_x_bits = retarget_compact(bits, target_span * 20, limit, target_span)
        # Fixed expected encodings independently derived from the specified
        # integer formula and compact-target truncation.
        self.assertEqual(quarter_bits, 0x201FFFFF)
        self.assertEqual(nominal_bits, 0x207FFFFF)
        self.assertEqual(double_bits, 0x2100FFFF)
        self.assertEqual(four_x_bits, 0x207FFFFF)
        self.assertEqual(decode_compact_target(quarter_bits), limit // 4)
        self.assertEqual(decode_compact_target(nominal_bits), limit)
        self.assertLessEqual(decode_compact_target(double_bits), limit * 2)
        self.assertEqual(decode_compact_target(four_x_bits), limit)

    def test_retarget_rejects_bad_inputs(self):
        from src.blackroot_consensus import retarget_compact
        bits = 0x207FFFFF
        limit = decode_compact_target(bits)
        for actual in (0, -1, True):
            with self.assertRaises(ValueError):
                retarget_compact(bits, actual, limit)


if __name__ == "__main__":
    unittest.main()
