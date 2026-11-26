import unittest

from src.blackroot_monetary import (
    BLOCK_SUBSIDY,
    COIN,
    FOUNDER_ALLOCATION,
    FIRST_MINING_HEIGHT,
    LAST_MINING_HEIGHT,
    MINING_ALLOCATION,
    MAX_MONEY,
    TOTAL_SUPPLY_CAP,
    block_subsidy,
    mining_issuance_through_height,
    total_supply_cap,
)


class MonetaryScheduleTests(unittest.TestCase):
    def test_founder_and_mining_allocations_sum_to_cap(self):
        self.assertEqual(FOUNDER_ALLOCATION, 20_000_000 * COIN)
        self.assertEqual(MINING_ALLOCATION, 20_000_000 * COIN)
        self.assertEqual(TOTAL_SUPPLY_CAP, 40_000_000 * COIN)
        self.assertEqual(MAX_MONEY, 40_000_000 * COIN)
        self.assertEqual(total_supply_cap(), 40_000_000 * COIN)

    def test_fixed_subsidy_boundaries(self):
        self.assertEqual(block_subsidy(0), 0)
        self.assertEqual(block_subsidy(FIRST_MINING_HEIGHT - 1), 0)
        self.assertEqual(block_subsidy(FIRST_MINING_HEIGHT), 10 * COIN)
        self.assertEqual(block_subsidy(LAST_MINING_HEIGHT), 10 * COIN)
        self.assertEqual(block_subsidy(LAST_MINING_HEIGHT + 1), 0)
        self.assertEqual(BLOCK_SUBSIDY, 10 * COIN)

    def test_exact_mining_emission_cap(self):
        self.assertEqual(
            mining_issuance_through_height(LAST_MINING_HEIGHT),
            MINING_ALLOCATION,
        )
        self.assertEqual(
            mining_issuance_through_height(LAST_MINING_HEIGHT + 10),
            MINING_ALLOCATION,
        )
        self.assertEqual(
            FOUNDER_ALLOCATION + mining_issuance_through_height(LAST_MINING_HEIGHT),
            TOTAL_SUPPLY_CAP,
        )

    def test_partial_mining_issuance(self):
        self.assertEqual(mining_issuance_through_height(0), 0)
        self.assertEqual(mining_issuance_through_height(1), 10 * COIN)
        self.assertEqual(mining_issuance_through_height(100), 1_000 * COIN)
        self.assertEqual(
            mining_issuance_through_height(LAST_MINING_HEIGHT - 1),
            19_999_990 * COIN,
        )
        self.assertEqual(
            mining_issuance_through_height(LAST_MINING_HEIGHT),
            20_000_000 * COIN,
        )
        self.assertEqual(
            mining_issuance_through_height(LAST_MINING_HEIGHT + 1),
            20_000_000 * COIN,
        )

    def test_subsidy_is_zero_outside_the_mining_window(self):
        for height in (0, LAST_MINING_HEIGHT + 1, LAST_MINING_HEIGHT + 10_000):
            with self.subTest(height=height):
                self.assertEqual(block_subsidy(height), 0)

    def test_rejects_invalid_heights(self):
        for height in (-1, 1.5, True, None, "1", 1.0):
            with self.subTest(height=height), self.assertRaises(ValueError):
                block_subsidy(height)
            with self.subTest(height=height), self.assertRaises(ValueError):
                mining_issuance_through_height(height)


if __name__ == "__main__":
    unittest.main()
