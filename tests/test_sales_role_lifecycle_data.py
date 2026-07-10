import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.dashboard_db import DashboardDbService


class SalesRoleLifecycleDataTests(unittest.TestCase):
    def setUp(self):
        self.service = DashboardDbService()
        self.options = self.service._default_lifecycle_options()
        self.rows = [
            {
                "lifecycle_label_id": 201,
                "sales_role_code": "star",
                "sales_amount": 100,
                "sales_qty": 10,
                "daily_sales": 0.33,
                "order_gross_profit": 20,
            },
            {
                "lifecycle_label_id": 202,
                "sales_role_code": "potential",
                "sales_amount": 200,
                "sales_qty": 18,
                "daily_sales": 0.2,
                "order_gross_profit": 30,
            },
            {
                "lifecycle_label_id": 204,
                "sales_role_code": "eliminate",
                "sales_amount": 0,
                "sales_qty": 0,
                "daily_sales": 0,
                "order_gross_profit": 0,
            },
        ]

    def test_lifecycle_summary_uses_full_rows(self):
        summary = self.service._build_sales_role_lifecycle_summary(self.rows)

        self.assertEqual(3, summary["sku_count"])
        self.assertEqual(300, summary["sales_amount"])
        self.assertEqual(28, summary["sales_qty"])
        self.assertEqual(50, summary["order_gross_profit"])
        self.assertEqual(1, summary["mature_count"])
        self.assertEqual(1, summary["problem_count"])

    def test_lifecycle_distribution_keeps_empty_decline_option(self):
        distribution = self.service._build_sales_role_lifecycle_distribution(self.rows, self.options)
        by_id = {item["id"]: item for item in distribution}

        self.assertEqual(set([201, 202, 203, 204, 205]), set(by_id))
        self.assertEqual(0, by_id[205]["count"])
        self.assertEqual(1, by_id[201]["count"])
        self.assertEqual(100, by_id[201]["sales_amount"])

    def test_lifecycle_options_use_listing_age_rules(self):
        by_id = {item["id"]: item for item in self.options}

        self.assertEqual("上架≤30天", by_id[201]["label_period"])
        self.assertEqual("上架31-120天", by_id[202]["label_period"])
        self.assertEqual("上架121-300天", by_id[203]["label_period"])
        self.assertEqual("上架>300天", by_id[204]["label_period"])
        self.assertEqual("人工判断", by_id[205]["label_period"])

    def test_lifecycle_role_matrix_total_matches_detail_rows(self):
        matrix = self.service._build_sales_role_lifecycle_matrix(self.rows, self.options)

        self.assertEqual(3, matrix["total"])
        self.assertEqual(5 * 4, len(matrix["cells"]))
        self.assertEqual(3, sum(cell["count"] for cell in matrix["cells"]))

    def test_lifecycle_filter_applies_lifecycle_and_role(self):
        rows = self.service._filter_sales_role_lifecycle_rows(self.rows, lifecycle_label="202", sales_role="potential")

        self.assertEqual(1, len(rows))
        self.assertEqual(202, rows[0]["lifecycle_label_id"])
        self.assertEqual("potential", rows[0]["sales_role_code"])

    def test_source_connection_does_not_fall_back_to_target_database(self):
        with patch.dict(
            "os.environ",
            {"DASHBOARD_DB_NAME": "etl_datasync_test"},
            clear=True,
        ):
            service = DashboardDbService()

        self.assertIsNone(service.source_database)


if __name__ == "__main__":
    unittest.main()
