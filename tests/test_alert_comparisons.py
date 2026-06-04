import unittest
from datetime import date

from app.services.dashboard_db import normalize_alert_comparison_code
from etl.dashboard_daily_update import build_alert_comparison_params


class AlertComparisonTests(unittest.TestCase):
    def test_build_alert_comparison_params_includes_day_windows_and_month_to_date(self):
        params = {
            "biz_date": date(2026, 6, 3),
            "snapshot_date": date(2026, 6, 4),
        }

        comparisons = build_alert_comparison_params(params)
        by_code = {item["comparison_code"]: item for item in comparisons}

        self.assertEqual(list(by_code)[:5], ["d7", "d14", "d30", "d60", "d90"])
        self.assertEqual(by_code["d60"]["recent_start"], date(2026, 4, 5))
        self.assertEqual(by_code["d60"]["previous_start"], date(2026, 2, 4))
        self.assertEqual(by_code["m2026_01_vs_mtd"]["comparison_type"], "month_to_date")
        self.assertEqual(by_code["m2026_01_vs_mtd"]["recent_start"], date(2026, 6, 1))
        self.assertEqual(by_code["m2026_01_vs_mtd"]["recent_end"], date(2026, 6, 3))
        self.assertEqual(by_code["m2026_01_vs_mtd"]["previous_start"], date(2026, 1, 1))
        self.assertEqual(by_code["m2026_01_vs_mtd"]["previous_end"], date(2026, 1, 31))

    def test_build_alert_comparison_params_skips_current_month_as_history(self):
        params = {
            "biz_date": date(2026, 1, 15),
            "snapshot_date": date(2026, 1, 16),
        }

        comparisons = build_alert_comparison_params(params)

        self.assertEqual([item["comparison_code"] for item in comparisons], ["d7", "d14", "d30", "d60", "d90"])

    def test_normalize_alert_comparison_code_preserves_new_code_and_maps_legacy_days(self):
        self.assertEqual(normalize_alert_comparison_code("m2026_01_vs_mtd", 7), "m2026_01_vs_mtd")
        self.assertEqual(normalize_alert_comparison_code("", 60), "d60")
        self.assertEqual(normalize_alert_comparison_code("", 90), "d90")
        self.assertEqual(normalize_alert_comparison_code("", 31), "d30")


if __name__ == "__main__":
    unittest.main()
