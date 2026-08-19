from datetime import date

from app.services.price_review_data import PriceReviewService, _build_role_performance_trend


def test_role_performance_trend_includes_adjustment_day_in_pre_summary():
    trend = _build_role_performance_trend(
        adjust_date=date(2026, 8, 10),
        pre_days=2,
        post_days=2,
        latest_data_date=date(2026, 8, 12),
        sku_count=2,
        daily_rows=[
            {"dt_date": date(2026, 8, 8), "sales_qty": 10, "revenue": 100, "order_profit": 20, "source_rows": 2},
            {"dt_date": date(2026, 8, 9), "sales_qty": 20, "revenue": 200, "order_profit": 20, "source_rows": 2},
            {"dt_date": date(2026, 8, 10), "sales_qty": 5, "revenue": 50, "order_profit": 5, "source_rows": 2},
            {"dt_date": date(2026, 8, 11), "sales_qty": 30, "revenue": 300, "order_profit": 45, "source_rows": 2},
            {"dt_date": date(2026, 8, 12), "sales_qty": 40, "revenue": 400, "order_profit": 40, "source_rows": 2},
        ],
    )

    assert [point["relative_day"] for point in trend["points"]] == ["D-1", "D", "D+1", "D+2"]
    assert [point["period"] for point in trend["points"]] == ["before", "before", "after", "after"]
    assert [point["sales_qty"] for point in trend["points"]] == [20.0, 5.0, 30.0, 40.0]
    assert [point["margin_rate"] for point in trend["points"]] == [0.1, 0.1, 0.15, 0.1]
    assert trend["summary"] == {
        "sales_before": 25.0,
        "sales_after": 70.0,
        "margin_before": 0.1,
        "margin_after": 0.1214,
        "available_pre_days": 2,
        "available_post_days": 2,
        "expected_pre_days": 2,
        "expected_post_days": 2,
    }


def test_role_performance_trend_keeps_future_days_empty_instead_of_zero():
    trend = _build_role_performance_trend(
        adjust_date=date(2026, 8, 10),
        pre_days=1,
        post_days=2,
        latest_data_date=date(2026, 8, 11),
        sku_count=1,
        daily_rows=[
            {"dt_date": date(2026, 8, 9), "sales_qty": 3, "revenue": 30, "order_profit": 6, "source_rows": 1},
            {"dt_date": date(2026, 8, 11), "sales_qty": 4, "revenue": 40, "order_profit": 8, "source_rows": 1},
        ],
    )

    assert trend["points"][-1]["relative_day"] == "D+2"
    assert trend["points"][-1]["sales_qty"] is None
    assert trend["points"][-1]["margin_rate"] is None
    assert trend["points"][-1]["available"] is False
    assert trend["summary"]["available_post_days"] == 1


def test_role_performance_trend_reads_the_populated_dashboard_daily_columns():
    class Cursor:
        def __init__(self):
            self.row = None
            self.rows = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, _params=None):
            normalized = " ".join(sql.split()).lower()
            if "select max(dt_date)" in normalized and "dashboard_product_performance_daily" in normalized:
                self.row = {"latest_data_date": date(2026, 8, 11)}
                self.rows = []
            elif (
                "from dashboard_product_performance_daily" in normalized
                and "sales_amount" in normalized
                and "order_gross_profit" in normalized
            ):
                self.row = None
                self.rows = [{
                    "dt_date": date(2026, 8, 11),
                    "sales_qty": 5,
                    "revenue": 100,
                    "order_profit": 20,
                    "source_rows": 1,
                }]
            else:
                self.row = None
                self.rows = []

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.cursor_instance

    class Service(PriceReviewService):
        def connect(self):
            return Connection()

    trend = Service()._load_role_performance_trend(
        adjust_date=date(2026, 8, 10),
        pre_days=1,
        post_days=1,
        rows=[{"country": "德国", "station_store": "StoreA", "msku": "A1"}],
    )

    assert trend["latest_data_date"] == "2026-08-11"
    assert trend["points"][-1]["sales_qty"] == 5.0
    assert trend["points"][-1]["margin_rate"] == 0.2


def test_role_migration_filters_the_trend_sku_batch_before_loading_daily_data():
    class Service(PriceReviewService):
        def _load_role_cache_status(self):
            return {}

        def _load_role_migration_rows(self, adjust_date, pre_days, post_days):
            return [
                {
                    "adjust_date": adjust_date,
                    "country": "德国",
                    "station_store": "StoreA",
                    "msku": "A1",
                    "role_before_code": "star",
                    "role_after_code": "star",
                    "role_change": "stable",
                    "finance_change": "unavailable",
                    "data_status": "complete",
                },
                {
                    "adjust_date": adjust_date,
                    "country": "法国",
                    "station_store": "StoreB",
                    "msku": "B1",
                    "role_before_code": "dog",
                    "role_after_code": "problem",
                    "role_change": "down",
                    "finance_change": "unavailable",
                    "data_status": "complete",
                },
            ]

        def _load_role_performance_trend(self, adjust_date, pre_days, post_days, rows):
            self.trend_rows = list(rows)
            return {"sku_count": len(rows), "points": [], "summary": {}}

    service = Service()
    payload = service.get_role_migration_payload(
        adjust_date=date(2026, 8, 10),
        country="德国",
    )

    assert payload["performance_trend"]["sku_count"] == 1
    assert [row["msku"] for row in service.trend_rows] == ["A1"]
