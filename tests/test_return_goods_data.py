import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.return_goods_data import ReturnGoodsDataService


class ReturnGoodsServiceSqlTests(unittest.TestCase):
    def test_build_where_filters_country_store_keyword_stage_and_warning(self):
        service = ReturnGoodsDataService()

        where_sql, params = service._build_where(
            snapshot_date=date(2026, 6, 30),
            country_category="北美站",
            seller_name_new="店铺A",
            keyword="MSKU1",
            stage="运营干预期",
            warning_type="干预期未恢复",
            quick_filter="receiving",
        )

        self.assertIn("snapshot_date = %(snapshot_date)s", where_sql)
        self.assertIn("seller_sku_adj not like %(excluded_msku_pattern)s", where_sql)
        self.assertNotIn("dashboard_return_goods_stockout_pool", where_sql)
        self.assertIn("country_category = %(country_category)s", where_sql)
        self.assertIn("seller_name_new = %(seller_name_new)s", where_sql)
        self.assertIn("seller_sku_adj like %(keyword)s", where_sql)
        self.assertIn("stage = %(stage)s", where_sql)
        self.assertIn("warning_type = %(warning_type)s", where_sql)
        self.assertNotIn("return_start_date <= %(end_date)s", where_sql)
        self.assertNotIn("exit_date is null or exit_date > %(end_date)s", where_sql)
        self.assertIn("coalesce(current_fba_sellable, 0) > 0", where_sql)
        self.assertEqual("%MSKU1%", params["keyword"])

    def test_period_days_resolves_from_snapshot_date(self):
        service = ReturnGoodsDataService()

        snapshot_day, start_day, end_day = service._resolve_period("2026-06-30", 7, date(2026, 6, 30))

        self.assertEqual(date(2026, 6, 30), snapshot_day)
        self.assertEqual(date(2026, 6, 24), start_day)
        self.assertEqual(date(2026, 6, 30), end_day)

    def test_empty_snapshot_date_uses_latest_snapshot(self):
        service = ReturnGoodsDataService()

        snapshot_day, start_day, end_day = service._resolve_period("", 1, date(2026, 6, 30))

        self.assertEqual(date(2026, 6, 30), snapshot_day)
        self.assertEqual(date(2026, 6, 30), start_day)
        self.assertEqual(date(2026, 6, 30), end_day)

    def test_price_snapshots_use_database_current_date(self):
        class Cursor:
            def __init__(self):
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                self.statements.append((" ".join(sql.lower().split()), params))

            def fetchone(self):
                return {"snapshot_date": date(2026, 7, 14)}

        class Connection:
            def __init__(self):
                self.cursors = []

            def cursor(self):
                cursor = Cursor()
                self.cursors.append(cursor)
                return cursor

        service = ReturnGoodsDataService()
        conn = Connection()

        self.assertEqual(date(2026, 7, 14), service._latest_price_snapshot(conn))
        self.assertEqual(date(2026, 7, 14), service._latest_listing_price_snapshot(conn))

        statements = [statement for cursor in conn.cursors for statement in cursor.statements]
        self.assertEqual(2, len(statements))
        for sql, params in statements:
            self.assertIn("snapshot_date <= current_date", sql)
            self.assertIsNone(params)

    def test_build_where_supports_pre_stockout_sales_role_filter(self):
        service = ReturnGoodsDataService()

        where_sql, _ = service._build_where(snapshot_date=date(2026, 6, 30), quick_filter="role_star")

        self.assertIn("pre_stockout_sales_role = '明星产品'", where_sql)

    def test_serialize_item_formats_rate_as_percent(self):
        service = ReturnGoodsDataService()

        item = service._serialize_item(
            {
                "sales_recovery_rate": 0.756,
                "return_start_date": date(2026, 6, 10),
                "exit_date": None,
            }
        )

        self.assertEqual("75.6%", item["sales_recovery_rate_text"])
        self.assertEqual("2026-06-10", item["return_start_date"])
        self.assertIsNone(item["exit_date"])

    def test_serialize_item_only_exposes_return_to_snapshot_sales_for_active_event(self):
        service = ReturnGoodsDataService()

        active = service._serialize_item(
            {
                "exit_date": None,
                "post_recovery_sales_qty": 70,
                "post_cumulative_sales_qty": 134,
            }
        )
        active_before_d21 = service._serialize_item(
            {
                "exit_date": None,
                "post_recovery_sales_qty": 16,
                "post_cumulative_sales_qty": None,
            }
        )
        exited = service._serialize_item(
            {
                "exit_date": date(2026, 7, 20),
                "post_recovery_sales_qty": 153,
            }
        )

        self.assertEqual(134, active["return_to_snapshot_sales_qty"])
        self.assertEqual(16, active_before_d21["return_to_snapshot_sales_qty"])
        self.assertIsNone(exited["return_to_snapshot_sales_qty"])

    def test_serialize_item_marks_post_return_inventory_without_overwriting_warning(self):
        service = ReturnGoodsDataService()

        stockout = service._serialize_item(
            {"current_fba_sellable": 0, "warning_type": "持续干预严重低恢复"}
        )
        low_stock = service._serialize_item(
            {"current_fba_sellable": 5, "warning_type": "干预期未恢复"}
        )
        healthy = service._serialize_item(
            {"current_fba_sellable": 6, "warning_type": None}
        )

        self.assertEqual("返场后再次断货", stockout["post_return_inventory_status"])
        self.assertEqual("持续干预严重低恢复", stockout["warning_type"])
        self.assertEqual("返场后库存不足", low_stock["post_return_inventory_status"])
        self.assertEqual("干预期未恢复", low_stock["warning_type"])
        self.assertIsNone(healthy["post_return_inventory_status"])

    def test_serialize_item_includes_continuous_recovery_fields(self):
        service = ReturnGoodsDataService()

        item = service._serialize_item(
            {
                "d21_recovery_rate": 0.42,
                "recovery_followup_flag": 1,
                "post_cumulative_sales_qty": 126,
                "cumulative_avg_recovery_rate": 0.6,
                "recovery_followup_status": "恢复提升中",
                "stable_recovery_start_date": date(2026, 6, 25),
                "current_stable_recovery_flag": 0,
                "recovery_fallback_flag": 1,
                "days_to_standard": None,
                "return_days": 35,
                "recovery_window_days": 21,
            }
        )

        self.assertEqual("42.0%", item["d21_recovery_rate_text"])
        self.assertEqual("60.0%", item["cumulative_avg_recovery_rate_text"])
        self.assertEqual("2026-06-25", item["stable_recovery_start_date"])
        self.assertTrue(item["recovery_followup_flag"])
        self.assertFalse(item["current_stable_recovery_flag"])
        self.assertTrue(item["recovery_fallback_flag"])
        self.assertEqual(35, item["recovery_statistics_days"])

    def test_serialize_item_uses_frozen_days_for_late_standard_exit(self):
        service = ReturnGoodsDataService()

        item = service._serialize_item(
            {
                "recovery_followup_flag": 1,
                "days_to_standard": 28,
                "return_days": 40,
                "recovery_window_days": 21,
            }
        )

        self.assertEqual(28, item["recovery_statistics_days"])

    def test_summary_serializer_includes_first_version_extra_metrics(self):
        service = ReturnGoodsDataService()

        summary = service._serialize_summary(
            {
                "total_return_msku_count": 18,
                "total_return_event_count": 24,
                "new_count": 12,
                "exit_count": 5,
                "current_pool_count": 20,
                "current_pool_msku_count": 17,
                "receiving_count": 2,
                "not_arrived_count": 3,
                "success_exit_count": 3,
                "failed_exit_count": 1,
                "manual_judgment_count": 1,
                "overdue_count": 2,
                "today_observe_to_operating_count": 4,
                "secondary_stockout_count": 6,
                "avg_sales_recovery_rate": 0.8123,
            }
        )

        self.assertEqual(18, summary["total_return_msku_count"])
        self.assertEqual(24, summary["total_return_event_count"])
        self.assertEqual(17, summary["current_pool_msku_count"])
        self.assertEqual(2, summary["receiving_count"])
        self.assertEqual(3, summary["not_arrived_count"])
        self.assertEqual(4, summary["today_observe_to_operating_count"])
        self.assertEqual(6, summary["secondary_stockout_count"])
        self.assertEqual(0.8123, summary["avg_sales_recovery_rate"])
        self.assertEqual("81.2%", summary["avg_sales_recovery_rate_text"])

    def test_overview_summary_serializer_returns_latest_event_metrics(self):
        service = ReturnGoodsDataService()

        overview = service._serialize_overview_summary(
            {
                "stockout_msku_count": 18,
                "returned_msku_count": 17,
                "observe_msku_count": 5,
                "observe_d1_3_msku_count": 2,
                "observe_d4_7_msku_count": 3,
                "observe_ordered_msku_count": 4,
                "observe_not_ordered_msku_count": 1,
                "operating_msku_count": 7,
                "operating_d8_14_msku_count": 4,
                "operating_d15_21_msku_count": 3,
                "operating_success_recovery_msku_count": 1,
                "operating_low_recovery_msku_count": 5,
                "operating_recovery_insufficient_msku_count": 2,
                "operating_data_insufficient_msku_count": 0,
                "active_stockout_or_stopped_msku_count": 6,
                "exited_msku_count": 6,
                "success_exit_msku_count": 3,
                "failed_exit_msku_count": 1,
                "recovery_insufficient_msku_count": 2,
                "no_recovery_21d_msku_count": 11,
                "low_recovery_msku_count": 12,
                "weak_recovery_msku_count": 13,
                "high_value_failed_msku_count": 14,
                "data_insufficient_msku_count": 15,
                "manual_judgment_msku_count": 2,
                "secondary_stockout_msku_count": 4,
                "overdue_msku_count": 8,
                "receiving_msku_count": 9,
                "not_arrived_msku_count": 10,
                "avg_sales_recovery_rate": 0.701,
                "current_severe_low_recovery_msku_count": 16,
                "recovery_improving_msku_count": 17,
                "followup_active_msku_count": 54,
                "started_stable_recovery_msku_count": 18,
                "recovery_fallback_msku_count": 19,
                "late_standard_exit_msku_count": 20,
                "followup_data_insufficient_msku_count": 21,
                "followup_no_sales_since_return_msku_count": 22,
                "severe_no_sales_msku_count": 2,
                "severe_rate_0_10_msku_count": 3,
                "severe_rate_10_30_msku_count": 4,
                "severe_rate_30_50_msku_count": 7,
            }
        )

        self.assertEqual(18, overview["stockout_msku_count"])
        self.assertEqual(17, overview["returned_msku_count"])
        self.assertEqual(2, overview["observe_d1_3_msku_count"])
        self.assertEqual(3, overview["observe_d4_7_msku_count"])
        self.assertEqual(4, overview["observe_ordered_msku_count"])
        self.assertEqual(1, overview["observe_not_ordered_msku_count"])
        self.assertEqual(7, overview["operating_msku_count"])
        self.assertEqual(4, overview["operating_d8_14_msku_count"])
        self.assertEqual(3, overview["operating_d15_21_msku_count"])
        self.assertEqual(1, overview["operating_success_recovery_msku_count"])
        self.assertEqual(5, overview["operating_low_recovery_msku_count"])
        self.assertEqual(2, overview["operating_recovery_insufficient_msku_count"])
        self.assertEqual(0, overview["operating_data_insufficient_msku_count"])
        self.assertEqual(6, overview["active_stockout_or_stopped_msku_count"])
        self.assertEqual(6, overview["exited_msku_count"])
        self.assertEqual(2, overview["recovery_insufficient_msku_count"])
        self.assertEqual(11, overview["no_recovery_21d_msku_count"])
        self.assertEqual(12, overview["low_recovery_msku_count"])
        self.assertEqual(13, overview["weak_recovery_msku_count"])
        self.assertEqual(14, overview["high_value_failed_msku_count"])
        self.assertEqual(15, overview["data_insufficient_msku_count"])
        self.assertEqual(9, overview["receiving_msku_count"])
        self.assertEqual(16, overview["current_severe_low_recovery_msku_count"])
        self.assertEqual(17, overview["recovery_improving_msku_count"])
        self.assertEqual(54, overview["followup_active_msku_count"])
        self.assertEqual(
            overview["followup_active_msku_count"],
            overview["current_severe_low_recovery_msku_count"]
            + overview["recovery_improving_msku_count"]
            + overview["followup_data_insufficient_msku_count"],
        )
        self.assertEqual(18, overview["started_stable_recovery_msku_count"])
        self.assertEqual(19, overview["recovery_fallback_msku_count"])
        self.assertEqual(20, overview["late_standard_exit_msku_count"])
        self.assertEqual(21, overview["followup_data_insufficient_msku_count"])
        self.assertEqual(22, overview["followup_no_sales_since_return_msku_count"])
        self.assertEqual(2, overview["severe_no_sales_msku_count"])
        self.assertEqual(3, overview["severe_rate_0_10_msku_count"])
        self.assertEqual(4, overview["severe_rate_10_30_msku_count"])
        self.assertEqual(7, overview["severe_rate_30_50_msku_count"])
        self.assertEqual(
            overview["current_severe_low_recovery_msku_count"],
            overview["severe_no_sales_msku_count"]
            + overview["severe_rate_0_10_msku_count"]
            + overview["severe_rate_10_30_msku_count"]
            + overview["severe_rate_30_50_msku_count"],
        )
        self.assertEqual("70.1%", overview["avg_sales_recovery_rate_text"])

    def test_overview_quick_filters_use_latest_event_subquery(self):
        service = ReturnGoodsDataService()

        where_sql, _ = service._build_where(snapshot_date=date(2026, 6, 30), quick_filter="overview_operating")

        self.assertIn("row_number() over", where_sql)
        self.assertIn("partition by item_key", where_sql)
        self.assertIn("latest_rank = 1", where_sql)
        self.assertNotIn("dashboard_return_goods_stockout_pool", where_sql)
        self.assertIn("return_start_date <= %(end_date)s", where_sql)
        self.assertIn("exit_date is null or exit_date > %(end_date)s", where_sql)

    def test_stockout_overview_filter_still_uses_stockout_pool(self):
        service = ReturnGoodsDataService()

        where_sql, _ = service._build_where(
            snapshot_date=date(2026, 6, 30),
            quick_filter="overview_stockout_msku",
        )

        self.assertIn("dashboard_return_goods_stockout_pool", where_sql)

    def test_active_stockout_or_stopped_quick_filter_matches_all_active_return_stages(self):
        service = ReturnGoodsDataService()

        where_sql, _ = service._build_where(
            snapshot_date=date(2026, 6, 30),
            quick_filter="overview_active_stockout_or_stopped",
        )

        self.assertIn("latest_rank = 1", where_sql)
        self.assertIn("stage in ('观察期', '运营干预期', '持续干预期')", where_sql)
        self.assertNotIn("return_days between 1 and 21", where_sql)
        self.assertIn("coalesce(current_fba_sellable, 0) = 0", where_sql)
        self.assertIn("exit_date is null or exit_date > %(end_date)s", where_sql)

    def test_build_where_supports_return_day_filter(self):
        service = ReturnGoodsDataService()

        where_sql, params = service._build_where(snapshot_date=date(2026, 6, 30), return_day=6)

        self.assertIn("return_days = %(return_day)s", where_sql)
        self.assertEqual(6, params["return_day"])

    def test_detail_inventory_status_filters_split_sellable_and_inbound(self):
        service = ReturnGoodsDataService()
        base_where = "snapshot_date = %(snapshot_date)s"

        cases = {
            "post_stockout_inbound": [
                "exit_date is null or exit_date > %(end_date)s",
                "coalesce(current_fba_sellable, 0) = 0",
                "coalesce(current_fba_inbound, 0) > 0",
            ],
            "post_stockout_no_inbound": [
                "coalesce(current_fba_sellable, 0) = 0",
                "coalesce(current_fba_inbound, 0) = 0",
            ],
            "post_low_stock_inbound": [
                "coalesce(current_fba_sellable, 0) > 0",
                "coalesce(current_fba_sellable, 0) <= 5",
                "coalesce(current_fba_inbound, 0) > 0",
            ],
            "post_low_stock_no_inbound": [
                "coalesce(current_fba_sellable, 0) > 0",
                "coalesce(current_fba_sellable, 0) <= 5",
                "coalesce(current_fba_inbound, 0) = 0",
            ],
        }

        for filter_key, fragments in cases.items():
            with self.subTest(filter_key=filter_key):
                detail_where = service._detail_where(base_where, filter_key)
                for fragment in fragments:
                    self.assertIn(fragment, detail_where)

    def test_latest_event_filter_uses_item_key_latest_round(self):
        service = ReturnGoodsDataService()

        where_sql = service._latest_event_filter()

        self.assertIn("partition by item_key", where_sql)
        self.assertIn("order by return_start_date desc, return_round desc", where_sql)
        self.assertIn("latest_rank = 1", where_sql)

    def test_status_matrix_uses_continuous_recovery_columns(self):
        service = ReturnGoodsDataService()

        matrix = service._status_matrix([], date(2026, 6, 1), date(2026, 6, 30))

        self.assertEqual(
            ["not_arrived", "observe", "operating", "followup_severe", "followup_improving", "followup_data_insufficient"],
            [item["key"] for item in matrix["statuses"]],
        )

    def test_status_matrix_counts_each_msku_once_by_priority(self):
        service = ReturnGoodsDataService()
        row = {
            "item_key": "store|site|sku",
            "pre_stockout_sales_role": "潜力产品",
            "current_fba_sellable": 0,
            "current_fba_inbound": 100,
            "return_start_date": date(2026, 6, 1),
            "exit_date": None,
            "recovery_followup_flag": 1,
            "cumulative_avg_recovery_rate": 0.4,
            "stable_recovery_start_date": date(2026, 6, 24),
            "current_stable_recovery_flag": 1,
            "stage": "持续干预期",
        }

        exited_without_matrix_status = {
            "item_key": "store|site|exited",
            "pre_stockout_sales_role": "明星产品",
            "current_fba_sellable": 20,
            "current_fba_inbound": 0,
            "return_start_date": date(2026, 5, 1),
            "exit_date": date(2026, 6, 1),
            "stage": "已退出",
        }

        matrix = service._status_matrix([row, exited_without_matrix_status], date(2026, 6, 1), date(2026, 6, 30))
        cells = {(cell["role_key"], cell["status_key"]): cell["count"] for cell in matrix["cells"]}

        self.assertEqual(1, cells[("potential", "followup_severe")])
        self.assertEqual(0, cells[("potential", "not_arrived")])
        self.assertEqual(1, sum(cell["count"] for cell in matrix["cells"]))
        self.assertEqual(1, matrix["total"])

    def test_continuous_recovery_quick_filters_use_followup_fields(self):
        service = ReturnGoodsDataService()
        cases = {
            "overview_current_severe_low_recovery": ["recovery_followup_flag = 1", "cumulative_avg_recovery_rate < 0.5", "exit_date is null"],
            "overview_recovery_improving": ["cumulative_avg_recovery_rate >= 0.5", "cumulative_avg_recovery_rate < 0.7"],
            "overview_started_stable_recovery": ["stable_recovery_start_date is not null", "exit_date is null"],
            "overview_recovery_fallback": ["recovery_fallback_flag = 1", "exit_date is null"],
            "overview_late_standard_exit": ["recovery_followup_flag = 1", "recovery_followup_status = '21天后恢复达标'"],
            "overview_followup_data_insufficient": ["recovery_followup_flag = 1", "cumulative_avg_recovery_rate is null", "exit_date is null"],
            "overview_followup_active": ["recovery_followup_flag = 1", "exit_date is null"],
            "overview_followup_no_sales_since_return": [
                "recovery_followup_flag = 1",
                "coalesce(post_cumulative_sales_qty, 0) = 0",
                "exit_date is null",
            ],
            "overview_severe_no_sales": [
                "cumulative_avg_recovery_rate < 0.5",
                "coalesce(post_cumulative_sales_qty, 0) = 0",
            ],
            "overview_severe_rate_0_10": [
                "cumulative_avg_recovery_rate > 0",
                "cumulative_avg_recovery_rate < 0.1",
            ],
            "overview_severe_rate_10_30": [
                "cumulative_avg_recovery_rate >= 0.1",
                "cumulative_avg_recovery_rate < 0.3",
            ],
            "overview_severe_rate_30_50": [
                "cumulative_avg_recovery_rate >= 0.3",
                "cumulative_avg_recovery_rate < 0.5",
            ],
            "overview_severe_never_stable": [
                "cumulative_avg_recovery_rate < 0.5",
                "coalesce(post_cumulative_sales_qty, 0) > 0",
                "coalesce(recovery_fallback_flag, 0) = 0",
                "coalesce(current_stable_recovery_flag, 0) = 0",
            ],
            "overview_severe_recovery_fallback": [
                "cumulative_avg_recovery_rate < 0.5",
                "coalesce(post_cumulative_sales_qty, 0) > 0",
                "recovery_fallback_flag = 1",
            ],
            "overview_severe_current_stable": [
                "cumulative_avg_recovery_rate < 0.5",
                "coalesce(post_cumulative_sales_qty, 0) > 0",
                "coalesce(recovery_fallback_flag, 0) = 0",
                "current_stable_recovery_flag = 1",
            ],
        }

        for quick_filter, fragments in cases.items():
            where_sql, _ = service._build_where(snapshot_date=date(2026, 6, 30), quick_filter=quick_filter)
            for fragment in fragments:
                self.assertIn(fragment, where_sql, quick_filter)

    def test_overview_recovery_insufficient_filter_uses_50_to_70_percent_rate(self):
        service = ReturnGoodsDataService()

        where_sql, _ = service._build_where(snapshot_date=date(2026, 6, 30), quick_filter="overview_recovery_insufficient")

        self.assertNotIn("dashboard_return_goods_stockout_pool", where_sql)
        self.assertIn("sales_recovery_rate >= 0.5", where_sql)
        self.assertIn("sales_recovery_rate < 0.7", where_sql)

    def test_overview_no_recovery_21d_filter_uses_sales_through_snapshot_date(self):
        service = ReturnGoodsDataService()

        where_sql, _ = service._build_where(snapshot_date=date(2026, 6, 30), quick_filter="overview_no_recovery_21d")

        self.assertNotIn("dashboard_return_goods_stockout_pool", where_sql)
        self.assertIn("coalesce(post_return_sales_qty, 0) = 0", where_sql)
        self.assertNotIn("coalesce(post_recovery_sales_qty, 0) = 0", where_sql)

    def test_overview_high_value_failed_filter_uses_role_and_under_50_percent_rate(self):
        service = ReturnGoodsDataService()

        where_sql, _ = service._build_where(snapshot_date=date(2026, 6, 30), quick_filter="overview_high_value_failed")

        self.assertIn("pre_stockout_sales_role in ('明星产品', '潜力产品')", where_sql)
        self.assertIn("recovery_followup_flag = 1", where_sql)
        self.assertIn("cumulative_avg_recovery_rate < 0.5", where_sql)

    def test_overview_data_insufficient_filter_uses_empty_recovery_rate(self):
        service = ReturnGoodsDataService()

        where_sql, _ = service._build_where(snapshot_date=date(2026, 6, 30), quick_filter="overview_data_insufficient")

        self.assertNotIn("dashboard_return_goods_stockout_pool", where_sql)
        self.assertIn("sales_recovery_rate is null", where_sql)

    def test_overview_summary_uses_latest_events_without_stockout_pool_gate(self):
        class Cursor:
            def __init__(self):
                self.sql = ""

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                self.sql = " ".join(sql.lower().split())

            def fetchone(self):
                return {}

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

        service = ReturnGoodsDataService()
        conn = Connection()

        service._overview_summary(
            conn,
            "snapshot_date = %(snapshot_date)s",
            {"snapshot_date": date(2026, 6, 30), "end_date": date(2026, 6, 30)},
        )

        self.assertIn("row_number() over", conn.cursor_instance.sql)
        self.assertIn("where latest_rows.latest_rank = 1", conn.cursor_instance.sql)
        self.assertNotIn("dashboard_return_goods_stockout_pool", conn.cursor_instance.sql)

    def test_stage_business_compare_uses_active_observe_and_operating_rows(self):
        service = ReturnGoodsDataService()

        rows = [
            {
                "item_key": "a",
                "return_start_date": date(2026, 6, 25),
                "exit_date": None,
                "stage": "观察期",
                "pre_7d_sales_qty": 70,
                "observe_7d_sales_qty": 42,
                "post_7d_sales_qty": 30,
                "pre_7d_sales_avg": 10,
                "observe_7d_sales_avg": 6,
                "post_7d_sales_avg": 6,
                "sales_recovery_rate": 0.6,
                "pre_7d_gross_margin_rate": 0.2,
            },
            {
                "item_key": "b",
                "return_start_date": date(2026, 6, 10),
                "exit_date": None,
                "stage": "运营干预期",
                "pre_7d_sales_qty": 56,
                "observe_7d_sales_qty": 35,
                "post_7d_sales_qty": 21,
                "pre_7d_sales_avg": 8,
                "observe_7d_sales_avg": 5,
                "post_7d_sales_avg": 4,
                "sales_recovery_rate": 0.5,
                "pre_7d_gross_margin_rate": 0.1,
            },
            {
                "item_key": "c",
                "return_start_date": date(2026, 6, 10),
                "exit_date": date(2026, 6, 20),
                "stage": "已退出",
                "pre_7d_sales_qty": 100,
                "observe_7d_sales_qty": 100,
                "post_7d_sales_qty": 100,
                "pre_7d_sales_avg": 100,
                "observe_7d_sales_avg": 100,
                "post_7d_sales_avg": 100,
            },
        ]

        compare = service._stage_business_compare(rows, date(2026, 6, 30))

        self.assertEqual("观察期", compare[0]["stage"])
        self.assertEqual("断货前7天销量", compare[0]["baseline_label"])
        self.assertEqual(1, compare[0]["count"])
        self.assertEqual(70, compare[0]["baseline_sales"])
        self.assertEqual(-40, compare[0]["sales_delta"])
        self.assertEqual("运营干预期", compare[1]["stage"])
        self.assertEqual("观察期7天销量", compare[1]["baseline_label"])
        self.assertEqual(1, compare[1]["count"])
        self.assertEqual(35, compare[1]["baseline_sales"])
        self.assertEqual(-14, compare[1]["sales_delta"])
        self.assertEqual(0.6, compare[1]["sales_recovery_rate"])

    def test_stage_daily_groups_include_observe_segment_for_operating_pool(self):
        service = ReturnGoodsDataService()
        events = [
            {"return_event_id": "e1", "return_start_date": "2026-06-01", "return_days": 8},
            {"return_event_id": "e2", "return_start_date": "2026-06-02", "return_days": 1},
        ]
        daily_by_event = {
            "e1": [
                {"dt_date": "2026-06-01", "sales_qty": 2, "fba_sellable": 10},
                {"dt_date": "2026-06-08", "sales_qty": 3, "fba_sellable": 8},
            ],
            "e2": [
                {"dt_date": "2026-06-02", "sales_qty": 1, "fba_sellable": 5},
            ],
        }

        groups = service._stage_daily_groups(events, daily_by_event, "operating")

        self.assertEqual(["观察段", "干预段"], [group["title"] for group in groups])
        self.assertEqual(7, len(groups[0]["rows"]))
        self.assertEqual(14, len(groups[1]["rows"]))
        self.assertEqual(1, groups[0]["rows"][0]["observable_msku"])
        self.assertEqual(1, groups[0]["rows"][0]["ordered_msku"])
        self.assertEqual(2, groups[0]["rows"][0]["cumulative_ordered_msku"])
        self.assertEqual(0, groups[0]["rows"][0]["not_ordered_msku"])
        self.assertEqual(1, groups[1]["rows"][0]["observable_msku"])
        self.assertEqual(1, groups[1]["rows"][0]["ordered_msku"])
        self.assertEqual(1, groups[1]["rows"][0]["cumulative_ordered_msku"])
        self.assertEqual(1, groups[1]["rows"][0]["not_ordered_msku"])
        self.assertEqual(3, groups[1]["rows"][0]["sales_qty"])

    def test_stockout_pool_where_filters_snapshot_and_excludes_amazon_generated_sku(self):
        service = ReturnGoodsDataService()

        where_sql, params = service._stockout_pool_where(
            snapshot_date=date(2026, 6, 30),
            country_category="欧洲站",
            seller_name_new="店铺A",
            keyword="MSKU1",
        )

        self.assertIn("snapshot_date = %(snapshot_date)s", where_sql)
        self.assertIn("seller_sku_adj not like %(excluded_msku_pattern)s", where_sql)
        self.assertIn("country_category = %(country_category)s", where_sql)
        self.assertIn("seller_name_new = %(seller_name_new)s", where_sql)
        self.assertIn("seller_sku_adj like %(keyword)s", where_sql)
        self.assertEqual("amzn.gr.%", params["excluded_msku_pattern"])
        self.assertEqual("%MSKU1%", params["keyword"])

    def test_attach_period_comparison_adds_previous_values_and_deltas(self):
        service = ReturnGoodsDataService()
        summary = {"new_count": 7, "exit_count": 5, "net_count": 2}
        previous_summary = {"new_count": 4, "exit_count": 6, "net_count": -2}

        service._attach_period_comparison(summary, previous_summary)

        self.assertEqual(4, summary["previous_new_count"])
        self.assertEqual(3, summary["new_count_delta"])
        self.assertEqual(6, summary["previous_exit_count"])
        self.assertEqual(-1, summary["exit_count_delta"])
        self.assertEqual(-2, summary["previous_net_count"])
        self.assertEqual(4, summary["net_count_delta"])

    def test_serialize_item_includes_sales_average_fields(self):
        service = ReturnGoodsDataService()

        item = service._serialize_item(
            {
                "pre_7d_sales_avg": 2.25,
                "post_7d_sales_avg": 3.5,
                "recovery_window_days": 12,
                "pre_recovery_sales_qty": 42,
                "post_recovery_sales_qty": 28,
                "current_fba_inbound": 9,
                "sales_recovery_rate": None,
                "return_start_date": date(2026, 6, 10),
                "exit_date": None,
            }
        )

        self.assertEqual(2.25, item["pre_7d_sales_avg"])
        self.assertEqual(3.5, item["post_7d_sales_avg"])
        self.assertEqual(12, item["recovery_window_days"])
        self.assertEqual(42, item["pre_recovery_sales_qty"])
        self.assertEqual(28, item["post_recovery_sales_qty"])
        self.assertEqual(9, item["current_fba_inbound"])
        self.assertEqual("", item["sales_recovery_rate_text"])

    def test_serialize_country_metric_adds_price_and_ad_fields(self):
        service = ReturnGoodsDataService()

        item = service._serialize_country_metric(
            {
                "country": "DE",
                "local_sku_list": "SKU-A",
                "currency": "EUR",
                "listing_price": 18,
                "margin_price_35": 20,
                "margin_price_10": 12,
                "sales_qty": 8,
                "sales_amount": 180,
                "order_gross_profit": 36,
                "order_gross_margin": 0.2,
                "sessions_total": 100,
                "conversion_rate": 0.08,
                "ad_spend": 10,
                "ad_sales": 50,
                "ad_orders": 2,
                "ad_clicks": 20,
                "ad_impressions": 1000,
                "ctr": 0.02,
            }
        )

        self.assertEqual("DE", item["country"])
        self.assertEqual("EUR", item["currency"])
        self.assertTrue(item["price_risk"])
        self.assertEqual(-2, item["price_gap_to_35"])
        self.assertEqual(0.2, item["acos"])
        self.assertEqual("20.0%", item["acos_text"])
        self.assertEqual(0.055556, item["tacos"])
        self.assertEqual("5.6%", item["tacos_text"])
        self.assertEqual("20.0%", item["order_gross_margin_text"])

    def test_listing_preview_keeps_top_three_countries_and_ad_summary(self):
        service = ReturnGoodsDataService()
        rows = [
            {"period_start": date(2026, 6, 1), "period_end": date(2026, 6, 30), "country": "DE", "listing_price": 10, "margin_price_35": 9, "sales_qty": 10, "sales_amount": 100, "ad_spend": 5, "ad_sales": 20},
            {"period_start": date(2026, 6, 1), "period_end": date(2026, 6, 30), "country": "FR", "listing_price": 8, "margin_price_35": 9, "sales_qty": 8, "sales_amount": 80, "ad_spend": 3, "ad_sales": 10},
            {"period_start": date(2026, 6, 1), "period_end": date(2026, 6, 30), "country": "IT", "listing_price": 7, "margin_price_35": 8, "sales_qty": 6, "sales_amount": 60, "ad_spend": 2, "ad_sales": 10},
            {"period_start": date(2026, 6, 1), "period_end": date(2026, 6, 30), "country": "ES", "listing_price": 7, "margin_price_35": 8, "sales_qty": 4, "sales_amount": 40, "ad_spend": 1, "ad_sales": 5},
        ]

        preview = service._listing_preview_from_rows(rows)

        self.assertEqual(4, preview["country_count"])
        self.assertEqual(3, len(preview["top_countries"]))
        self.assertEqual(["DE", "FR", "IT"], [item["country"] for item in preview["top_countries"]])
        self.assertEqual(3, preview["price_risk_country_count"])
        self.assertEqual(11, preview["ad_spend"])
        self.assertEqual(45, preview["ad_sales"])
        self.assertEqual("24.4%", preview["acos_text"])
        self.assertEqual("3.9%", preview["tacos_text"])

    def test_serialize_daily_detail_adds_day_tag_and_margin(self):
        service = ReturnGoodsDataService()

        row = {
            "dt_date": date(2026, 6, 22),
            "sales_qty": 3,
            "sales_amount": 100,
            "order_gross_profit": 20,
            "fba_sellable": 0,
            "fba_inbound": 8,
        }
        event = {"stockout_date": "2026-06-22", "return_start_date": "2026-06-24"}

        item = service._serialize_daily_detail(row, event)

        self.assertEqual("2026-06-22", item["dt_date"])
        self.assertEqual("断货日", item["day_tag"])
        self.assertEqual("20.0%", item["gross_margin_rate_text"])
        row["dt_date"] = date(2026, 6, 23)
        self.assertEqual("断货中", service._serialize_daily_detail(row, event)["day_tag"])

    def test_attach_followup_trend_calculates_d22_daily_and_cumulative_rates(self):
        service = ReturnGoodsDataService()
        event = {
            "return_start_date": "2026-06-01",
            "pre_21d_sales_qty": 210,
            "recovery_followup_flag": True,
        }
        rows = [
            {"dt_date": "2026-06-21", "sales_qty": 5},
            {"dt_date": "2026-06-22", "sales_qty": 6},
            {"dt_date": "2026-06-23", "sales_qty": 8},
        ]

        service._attach_followup_trend(rows, event)

        self.assertIsNone(rows[0]["daily_recovery_rate"])
        self.assertEqual(0.6, rows[1]["daily_recovery_rate"])
        self.assertEqual("60.0%", rows[1]["daily_recovery_rate_text"])
        self.assertEqual(0.8, rows[2]["daily_recovery_rate"])
        self.assertEqual(19 / 230, rows[2]["cumulative_avg_recovery_rate"])

    def test_attach_followup_trend_fills_missing_natural_days_with_zero_sales(self):
        service = ReturnGoodsDataService()
        event = {
            "return_start_date": "2026-06-01",
            "pre_21d_sales_qty": 210,
            "recovery_followup_flag": True,
        }
        rows = [
            {"dt_date": "2026-06-21", "sales_qty": 5},
            {"dt_date": "2026-06-23", "sales_qty": 8},
        ]

        service._attach_followup_trend(rows, event)

        self.assertEqual(["2026-06-21", "2026-06-22", "2026-06-23"], [row["dt_date"] for row in rows])
        self.assertEqual(0, rows[1]["sales_qty"])
        self.assertTrue(rows[1]["source_missing"])
        self.assertEqual(0, rows[1]["daily_recovery_rate"])

    def test_attach_followup_trend_labels_all_return_days_and_standard_exit(self):
        service = ReturnGoodsDataService()
        event = {
            "return_start_date": "2026-06-01",
            "exit_date": "2026-06-22",
            "exit_reason": "达标退出",
            "recovery_followup_flag": False,
        }
        rows = [
            {"dt_date": "2026-05-31", "sales_qty": 1},
            {"dt_date": "2026-06-01", "sales_qty": 2},
            {"dt_date": "2026-06-20", "sales_qty": 3},
            {"dt_date": "2026-06-21", "sales_qty": 4},
            {"dt_date": "2026-06-22", "sales_qty": 5},
        ]

        service._attach_followup_trend(rows, event)

        self.assertEqual(
            ["-", "D1", "D20", "D21", "达标退出"],
            [row["return_day_label"] for row in rows],
        )

    def test_daily_detail_stops_at_exit_date(self):
        service = ReturnGoodsDataService()

        class Cursor:
            def __init__(self):
                self.params = None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, _sql, params):
                self.params = params

            def fetchall(self):
                return []

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

        conn = Connection()
        event = {
            "stockout_date": "2026-05-01",
            "exit_date": "2026-06-28",
            "seller_name_new": "店铺A",
            "country_category": "欧洲站",
            "seller_sku_adj": "MSKU1",
        }

        service._daily_detail(conn, event, date(2026, 7, 14))

        self.assertEqual(date(2026, 6, 28), conn.cursor_instance.params["source_end_date"])


if __name__ == "__main__":
    unittest.main()
