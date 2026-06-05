import unittest
from datetime import date

from app.services.dashboard_db import (
    is_alert_month_mode,
    normalize_alert_comparison_code,
    normalize_alert_month_code,
)
from etl.dashboard_daily_update import build_alert_comparison_params, build_alert_monthly_metric_params


class AlertComparisonTests(unittest.TestCase):
    def test_build_alert_comparison_params_only_includes_fixed_day_windows(self):
        params = {
            "biz_date": date(2026, 6, 3),
            "snapshot_date": date(2026, 6, 4),
        }

        comparisons = build_alert_comparison_params(params)
        by_code = {item["comparison_code"]: item for item in comparisons}

        self.assertEqual(list(by_code), ["d7", "d14", "d30", "d60", "d90"])
        self.assertEqual(by_code["d60"]["recent_start"], date(2026, 4, 5))
        self.assertEqual(by_code["d60"]["previous_start"], date(2026, 2, 4))

    def test_build_alert_monthly_metric_params_includes_current_month_to_biz_date(self):
        params = {
            "biz_date": date(2026, 6, 3),
            "snapshot_date": date(2026, 6, 4),
        }

        months = build_alert_monthly_metric_params(params)
        by_month = {item["month_code"]: item for item in months}

        self.assertEqual(list(by_month), ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"])
        self.assertEqual(by_month["2026-01"]["data_start"], date(2026, 1, 1))
        self.assertEqual(by_month["2026-01"]["data_end"], date(2026, 1, 31))
        self.assertEqual(by_month["2026-01"]["stat_days"], 31)
        self.assertEqual(by_month["2026-01"]["is_month_complete"], 1)
        self.assertEqual(by_month["2026-06"]["data_start"], date(2026, 6, 1))
        self.assertEqual(by_month["2026-06"]["data_end"], date(2026, 6, 3))
        self.assertEqual(by_month["2026-06"]["stat_days"], 3)
        self.assertEqual(by_month["2026-06"]["is_month_complete"], 0)

    def test_normalize_alert_comparison_code_preserves_new_code_and_maps_legacy_days(self):
        self.assertEqual(normalize_alert_comparison_code("d90", 7), "d90")
        self.assertEqual(normalize_alert_comparison_code("", 60), "d60")
        self.assertEqual(normalize_alert_comparison_code("", 90), "d90")
        self.assertEqual(normalize_alert_comparison_code("", 31), "d30")

    def test_normalize_alert_month_code_keeps_valid_months(self):
        self.assertEqual(normalize_alert_month_code("2026-01"), "2026-01")
        self.assertEqual(normalize_alert_month_code("2026-13"), "")
        self.assertEqual(normalize_alert_month_code("m2026_01_vs_mtd"), "")

    def test_month_parameters_do_not_force_month_mode(self):
        self.assertTrue(is_alert_month_mode("month"))
        self.assertFalse(is_alert_month_mode("days"))
        self.assertFalse(is_alert_month_mode(""))


if __name__ == "__main__":
    unittest.main()
