import unittest

from src.blackroot_maturity import (
    COINBASE_MATURITY,
    UTXOProvenance,
    validate_coinbase_maturity,
)


class CoinbaseMaturityTests(unittest.TestCase):
    def test_network_maturity_is_100_blocks(self):
        self.assertEqual(COINBASE_MATURITY, 100)

    def test_rejects_coinbase_spend_one_block_before_maturity(self):
        with self.assertRaisesRegex(ValueError, "premature"):
            validate_coinbase_maturity(UTXOProvenance(0, True), 99)

    def test_accepts_coinbase_spend_at_exact_maturity(self):
        validate_coinbase_maturity(UTXOProvenance(0, True), 100)

    def test_accepts_non_coinbase_output_without_maturity_delay(self):
        validate_coinbase_maturity(UTXOProvenance(99, False), 99)

    def test_rejects_coinbase_spending_height_before_creation(self):
        with self.assertRaisesRegex(ValueError, "before its creation"):
            validate_coinbase_maturity(UTXOProvenance(10, True), 9)

    def test_rejects_non_coinbase_spending_height_before_creation(self):
        with self.assertRaisesRegex(ValueError, "before its creation"):
            validate_coinbase_maturity(UTXOProvenance(10, False), 9)

    def test_missing_or_untrusted_provenance_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "provenance"):
            validate_coinbase_maturity(None, 100)

    def test_rejects_invalid_metadata(self):
        with self.assertRaises(ValueError):
            UTXOProvenance(-1, True)
        with self.assertRaises(TypeError):
            UTXOProvenance(0, 1)


if __name__ == "__main__":
    unittest.main()
