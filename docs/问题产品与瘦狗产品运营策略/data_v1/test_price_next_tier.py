"""Boundary checks for problem-product price steps."""
import unittest
from decimal import Decimal as D

from calculate_current_problem_actions import next_price_target


class NextPriceTargetTests(unittest.TestCase):
    def test_above_p25_goes_to_p25(self):
        self.assertEqual(next_price_target(D("17"), D("10.12"), D("11.45"), D("12.80"), D("14.15")), D("14.15"))

    def test_between_p20_and_p25_goes_to_p20(self):
        self.assertEqual(next_price_target(D("13"), D("10.12"), D("11.45"), D("12.802"), D("14.15")), D("12.81"))

    def test_between_p15_and_p20_goes_to_p15(self):
        self.assertEqual(next_price_target(D("12"), D("10.12"), D("11.452"), D("12.80"), D("14.15")), D("11.46"))

    def test_at_or_below_p15_goes_to_p10(self):
        self.assertEqual(next_price_target(D("11.45"), D("10.123"), D("11.45"), D("12.80"), D("14.15")), D("10.13"))
        self.assertEqual(next_price_target(D("10.50"), D("10.123"), D("11.45"), D("12.80"), D("14.15")), D("10.13"))

    def test_p10_is_floor(self):
        self.assertIsNone(next_price_target(D("10.12"), D("10.12"), D("11.45"), D("12.80"), D("14.15")))

    def test_invalid_tier_order_is_not_priced(self):
        self.assertIsNone(next_price_target(D("13"), D("10.12"), D("11.45"), D("11.40"), D("14.15")))


if __name__ == "__main__":
    unittest.main()
