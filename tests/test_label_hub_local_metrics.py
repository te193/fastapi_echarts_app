import unittest

from app.services import label_hub_local_metrics
from app.services.label_hub_local_metrics import LabelHubLocalMetricsService


class FakeCursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sql = []

    def execute(self, sql, params):
        self.sql.append((sql, params))

    def fetchone(self):
        return self.responses.pop(0)

    def fetchall(self):
        return self.responses.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def cursor(self):
        return self.cursor_instance

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeDashboard:
    schemas = None

    def __init__(self, cursor):
        self.connection = FakeConnection(cursor)

    def connect(self):
        return self.connection


class LabelHubLocalMetricsTests(unittest.TestCase):
    def test_sales_trend_rules_compare_same_end_date_7d_and_30d_daily_sales(self):
        cases = [
            ((1.30, 1.00), "accelerating"),
            ((1.10, 1.00), "growing"),
            ((1.00, 1.00), "stable"),
            ((0.80, 1.00), "slowing"),
            ((0.60, 1.00), "declining"),
            ((0.00, 1.00), "stopped"),
            ((0.00, 0.00), "no_sales"),
            ((1.00, 0.00), "recent_start"),
            ((None, 1.00), "insufficient"),
        ]

        actual = [label_hub_local_metrics._sales_trend(*values)[0] for values, _ in cases]

        self.assertEqual([expected for _, expected in cases], actual)

    def test_fetch_uses_latest_non_future_window_and_returns_complete_metric_rows(self):
        cursor = FakeCursor([
            {
                "snapshot_date": "2026-07-14", "period_code": "30d", "period_days": 30,
                "period_start": "2026-06-14", "period_end": "2026-07-13",
            },
            [{
                "country_category": "欧洲站", "seller_name_new": "StoreA", "seller_sku_adj": "A1",
                "sales_qty": 12, "daily_sales": 0.4, "sales_amount": 1000,
                "order_gross_profit": -20, "order_gross_margin": -0.02,
                "sales_role_code": "problem", "sales_role_label": "问题产品",
                "ad_spend": 50, "ad_sales": 200, "return_count": 2,
            }],
            [
                {"country_category": "欧洲站", "seller_name_new": "StoreA", "seller_sku_adj": "A1", "period_code": "7d", "daily_sales": 0.6},
                {"country_category": "欧洲站", "seller_name_new": "StoreA", "seller_sku_adj": "A1", "period_code": "30d", "daily_sales": 0.4},
            ],
        ])
        service = LabelHubLocalMetricsService(FakeDashboard(cursor))

        payload = service.fetch("2026-07-13", "30d")

        self.assertEqual("available", payload["status"])
        self.assertEqual("2026-07-13", payload["window"]["period_end"])
        row = payload["metrics"][("欧洲站", "StoreA", "A1")]
        self.assertEqual("eliminate", row["sales_role_code"])
        self.assertEqual("lt1", row["daily_sales_band_code"])
        self.assertEqual("lt5", row["margin_band_code"])
        self.assertEqual("accelerating", row["sales_trend_code"])
        self.assertEqual(0.5, row["sales_trend_ratio"])
        self.assertTrue(row["negative_profit"])
        window_sql, window_params = cursor.sql[0]
        self.assertIn("period_end <=", window_sql.lower())
        self.assertEqual("2026-07-13", window_params["data_date"])
        self.assertIn("dashboard_sales_role_period_snapshot", cursor.sql[1][0])
        self.assertIn("period_code in ('7d', '30d')", cursor.sql[2][0].lower())

    def test_invalid_metric_period_is_rejected(self):
        service = LabelHubLocalMetricsService(FakeDashboard(FakeCursor([])))

        with self.assertRaises(ValueError):
            service.fetch("2026-07-13", "365d")


if __name__ == "__main__":
    unittest.main()
