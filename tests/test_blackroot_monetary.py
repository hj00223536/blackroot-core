import unittest

from src.blackroot_monetary import (
    COIN,
    FOUNDER_ALLOCATION,
    MINING_ALLOCATION,
    PROPOSED_BLOCK_SUBSIDY,
    TOTAL_SUPPLY_CAP,
    LAST_MINING_HEIGHT,
    proposed_block_subsidy,
    proposed_mining_issuance_through_height,
    proposed_total_supply_cap,
)


class ProposedMonetaryScheduleTests(unittest.TestCase):
    def test_founder_and_mining_allocations_sum_to_cap(self):
        self.assertEqual(FOUNDER_ALLOCATION, 20_000_000 * COIN)
        self.assertEqual(MINING_ALLOCATION, 20_000_000 * COIN)
        self.assertEqual(TOTAL_SUPPLY_CAP, 40_000_000 * COIN)
        self.assertEqual(proposed_total_supply_cap(), 40_000_000 * COIN)

    def test_fixed_subsidy_boundaries(self):
        self.assertEqual(proposed_block_subsidy(0), 0)
        self.assertEqual(proposed_block_subsidy(1), 10 * COIN)
        self.assertEqual(proposed_block_subsidy(LAST_MINING_HEIGHT), 10 * COIN)
        self.assertEqual(proposed_block_subsidy(LAST_MINING_HEIGHT + 1), 0)
        self.assertEqual(PROPOSED_BLOCK_SUBSIDY, 10 * COIN)

    def test_exact_mining_emission_cap(self):
        self.assertEqual(
            proposed_mining_issuance_through_height(LAST_MINING_HEIGHT),
            MINING_ALLOCATION,
        )
        self.assertEqual(
            proposed_mining_issuance_through_height(LAST_MINING_HEIGHT + 10),
            MINING_ALLOCATION,
        )
        self.assertLessEqual(
            FOUNDER_ALLOCATION
            + proposed_mining_issuance_through_height(LAST_MINING_HEIGHT),
            TOTAL_SUPPLY_CAP,
        )

    def test_partial_mining_issuance(self):
        self.assertEqual(proposed_mining_issuance_through_height(100), 1_000 * COIN)
        self.assertEqual(proposed_mining_issuance_through_height(0), 0)

    def test_rejects_invalid_heights(self):
        for height in (-1, 1.5, True):
            with self.subTest(height=height), self.assertRaises(ValueError):
                proposed_block_subsidy(height)
            with self.subTest(height=height), self.assertRaises(ValueError):
                proposed_mining_issuance_through_height(height)


if __name__ == "__main__":
    unittest.main()
