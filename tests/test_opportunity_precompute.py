import unittest

from app.services import dashboard_db
from etl import dashboard_daily_update


class OpportunityPrecomputeTests(unittest.TestCase):
    def test_etl_declares_opportunity_snapshot_tables(self):
        self.assertIn("dashboard_opportunity_comparison_snapshot", dashboard_daily_update.CREATE_OPPORTUNITY_COMPARISON_SNAPSHOT_SQL)
        self.assertIn("dashboard_opportunity_comparison_summary", dashboard_daily_update.CREATE_OPPORTUNITY_COMPARISON_SUMMARY_SQL)

    def test_service_declares_opportunity_snapshot_table(self):
        self.assertEqual(
            dashboard_db.OPPORTUNITY_COMPARISON_TABLE,
            "etl_datasync_test.dashboard_opportunity_comparison_snapshot",
        )


if __name__ == "__main__":
    unittest.main()
