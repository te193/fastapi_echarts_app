import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.dashboard_db import DashboardDbService
from etl import dashboard_daily_update


class FixedDashboardPeriodTests(unittest.TestCase):
    def setUp(self):
        self.service = DashboardDbService()
        self.bounds = {
            "min_date": date(2025, 12, 11),
            "max_date": date(2026, 7, 19),
        }

    def _resolve(self, filters):
        self.service._get_daily_bounds = lambda conn: self.bounds
        self.service._get_period_snapshot_date = (
            lambda conn, table, start, end: self.bounds["max_date"]
        )
        return self.service._resolve_window(None, filters)

    def test_custom_date_range_falls_back_to_default_90_days(self):
        window = self._resolve(
            {"start_date": "2026-06-01", "end_date": "2026-06-10"}
        )

        self.assertEqual(date(2026, 4, 21), window.start_date)
        self.assertEqual(date(2026, 7, 19), window.end_date)
        self.assertEqual("last_90_days", window.period_code)
        self.assertEqual(
            "etl_datasync_test.dashboard_product_period_90d_snapshot",
            window.period_table,
        )

    def test_fixed_30_day_range_keeps_30_day_snapshot(self):
        window = self._resolve(
            {"start_date": "2026-06-20", "end_date": "2026-07-19"}
        )

        self.assertEqual("last_30_days", window.period_code)
        self.assertEqual(
            "etl_datasync_test.dashboard_product_period_30d_snapshot",
            window.period_table,
        )

    def test_custom_period_table_is_not_allowed(self):
        with self.assertRaises(RuntimeError):
            self.service._render_period_table(
                "etl_datasync_test.dashboard_product_period_snapshot"
            )

    def test_daily_etl_does_not_create_or_run_custom_period_snapshot(self):
        self.assertNotIn(
            dashboard_daily_update.CREATE_PERIOD_SNAPSHOT_SQL,
            dashboard_daily_update.DDL_STATEMENTS,
        )
        self.assertNotIn("period_snapshot", dashboard_daily_update.STEPS)
        self.assertNotIn("period_snapshot", dashboard_daily_update.DEFAULT_STEP_ORDER)


if __name__ == "__main__":
    unittest.main()
