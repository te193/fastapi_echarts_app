import unittest
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etl.dashboard_daily_update import SchemaConfig
from etl.return_goods_update import (
    CREATE_RETURN_EVENTS_SQL,
    INSERT_STAGE_DAILY_SUMMARY_SQL,
    INSERT_STOCKOUT_POOL_SQL,
    INSERT_RETURN_EVENT_SQL,
    SELECT_PRODUCT_DAILY_SQL,
    avg_sales,
    build_events,
    build_stockout_pool_row,
    ensure_return_events_schema,
    merge_stockout_pool_row,
    salable_sales_qty,
    sales_role,
    source_history_start_date,
)


def product_row(
    day,
    fba,
    sales=1,
    item_key="store|site|msku",
    store="店铺A",
    site="北美站",
    msku="MSKU1",
    sales_amount=100,
    order_gross_profit=20,
):
    return {
        "dt_date": day,
        "item_key": item_key,
        "seller_name_new": store,
        "country_category": site,
        "seller_sku_adj": msku,
        "local_sku": "SKU1",
        "sales_qty": Decimal(str(sales)),
        "sales_amount": Decimal(str(sales_amount)),
        "order_gross_profit": Decimal(str(order_gross_profit)),
        "afn_fulfillable_quantity": Decimal(str(fba)),
    }


class ReturnGoodsEventTests(unittest.TestCase):
    def test_post_return_sales_qty_is_wired_through_schema_migration_and_insert(self):
        class Cursor:
            def __init__(self):
                self.statements = []

            def execute(self, sql, *_):
                self.statements.append(sql)

            def fetchone(self):
                return None

        schemas = SchemaConfig(
            target_schema="etl_datasync_test",
            etl_source_schema="etl_datasync_test",
            dwd_source_schema="etl_datasync_test",
            pricing_source_schema="etl_datasync_test",
        )
        cursor = Cursor()

        ensure_return_events_schema(cursor, schemas)

        self.assertIn("post_return_sales_qty decimal(18,4) null", CREATE_RETURN_EVENTS_SQL)
        self.assertEqual(2, INSERT_RETURN_EVENT_SQL.count("post_return_sales_qty"))
        self.assertTrue(
            any("add column post_return_sales_qty" in statement for statement in cursor.statements)
        )

    def test_source_history_matches_deployed_label_history(self):
        self.assertEqual(
            date(2026, 1, 1),
            source_history_start_date(date(2026, 7, 14), lookback_days=180),
        )

    def test_stockout_pool_does_not_require_positive_sales(self):
        self.assertNotIn("period_sales_qty > 0", INSERT_STOCKOUT_POOL_SQL)

    def test_stockout_pool_is_built_from_the_same_streamed_rows(self):
        snapshot_date = date(2026, 7, 28)
        rows = [
            product_row(date(2026, 1, 20), 0, 4, msku="MSKU1"),
            product_row(date(2026, 1, 30), 6, 5, msku="MSKU1"),
            product_row(date(2026, 7, 27), 0, 2, msku="MSKU1"),
            product_row(date(2026, 7, 28), 8, 3, msku="MSKU1"),
        ]
        rows[2]["local_sku"] = "SKU9"

        pool_row = build_stockout_pool_row(rows, snapshot_date, lookback_days=180)

        self.assertEqual(date(2026, 7, 27), pool_row["first_stockout_date"])
        self.assertEqual(date(2026, 7, 27), pool_row["last_stockout_date"])
        self.assertEqual(1, pool_row["stockout_days"])
        self.assertEqual(Decimal("10"), pool_row["period_sales_qty"])
        self.assertEqual("SKU9", pool_row["local_sku"])

    def test_stockout_pool_skips_products_without_stockout_in_rolling_window(self):
        snapshot_date = date(2026, 7, 28)
        rows = [
            product_row(date(2026, 1, 20), 0, 4),
            product_row(date(2026, 7, 27), 6, 2),
            product_row(date(2026, 7, 28), 8, 3),
        ]

        self.assertIsNone(build_stockout_pool_row(rows, snapshot_date, lookback_days=180))

    def test_stockout_pool_merges_case_variants_like_mysql_collation(self):
        current = {
            "local_sku": "GQ0348a-zu",
            "first_stockout_date": date(2026, 2, 27),
            "last_stockout_date": date(2026, 3, 14),
            "stockout_days": 16,
            "period_sales_qty": Decimal("0"),
        }
        incoming = {
            "local_sku": "GQ0348a-zu",
            "first_stockout_date": date(2026, 3, 15),
            "last_stockout_date": date(2026, 8, 25),
            "stockout_days": 164,
            "period_sales_qty": Decimal("0"),
        }

        merged = merge_stockout_pool_row(current, incoming)

        self.assertEqual(date(2026, 2, 27), merged["first_stockout_date"])
        self.assertEqual(date(2026, 8, 25), merged["last_stockout_date"])
        self.assertEqual(180, merged["stockout_days"])
        self.assertEqual(Decimal("0"), merged["period_sales_qty"])

    def test_stage_summary_uses_window_cumulative_instead_of_range_join(self):
        sql = INSERT_STAGE_DAILY_SUMMARY_SQL.lower()

        self.assertIn("sum(ec.sales_qty) over", sql)
        self.assertIn(
            "partition by ec.stage_key, ec.segment_key, ec.return_event_id",
            sql,
        )
        self.assertNotIn("left join daily_msku p2", sql)

    def test_event_with_old_stockout_is_retained_when_return_start_is_inside_window(self):
        rows = [
            product_row(date(2026, 1, 20), 0, 0),
            product_row(date(2026, 1, 30), 6, 0),
        ]

        events = build_events(rows, date(2026, 7, 28), lookback_days=180)

        self.assertEqual(1, len(events))
        self.assertEqual(date(2026, 1, 20), events[0]["stockout_date"])
        self.assertEqual(date(2026, 1, 30), events[0]["return_start_date"])

    def test_stockout_on_inclusive_180_day_boundary_is_retained(self):
        rows = [
            product_row(date(2026, 1, 30), 0, 0),
            product_row(date(2026, 7, 22), 6, 1),
        ]

        events = build_events(rows, date(2026, 7, 28), lookback_days=180)

        self.assertEqual(1, len(events))
        self.assertEqual(date(2026, 1, 30), events[0]["stockout_date"])
        self.assertEqual(date(2026, 7, 22), events[0]["return_start_date"])

    def test_stockout_before_boundary_is_retained_when_return_start_is_inside_window(self):
        rows = [
            product_row(date(2026, 1, 29), 0, 0),
            product_row(date(2026, 7, 22), 6, 1),
        ]

        events = build_events(rows, date(2026, 7, 28), lookback_days=180)

        self.assertEqual(1, len(events))

    def test_return_start_before_inclusive_180_day_boundary_is_excluded(self):
        rows = [
            product_row(date(2026, 1, 10), 0, 0),
            product_row(date(2026, 1, 29), 6, 1),
        ]

        events = build_events(rows, date(2026, 7, 28), lookback_days=180)

        self.assertEqual([], events)

    def test_zero_sales_event_inside_lookback_window_is_retained(self):
        rows = [
            product_row(date(2026, 2, 1), 0, 0),
            product_row(date(2026, 2, 2), 6, 0),
        ]

        events = build_events(rows, date(2026, 7, 28), lookback_days=180)

        self.assertEqual(1, len(events))
        self.assertEqual(date(2026, 2, 1), events[0]["stockout_date"])
        self.assertEqual(date(2026, 2, 2), events[0]["return_start_date"])

    def test_source_sql_groups_to_store_country_msku_grain(self):
        self.assertIn("concat_ws('|', seller_name_new, country_category, seller_sku_adj) as item_key", SELECT_PRODUCT_DAILY_SQL)
        self.assertIn("group by", SELECT_PRODUCT_DAILY_SQL.lower())
        self.assertIn("seller_name_new, country_category, seller_sku_adj", SELECT_PRODUCT_DAILY_SQL)
        self.assertIn("dashboard_inventory_daily_snapshot", SELECT_PRODUCT_DAILY_SQL)
        self.assertIn("coalesce(p.product_fba_sellable, 0) as afn_fulfillable_quantity", SELECT_PRODUCT_DAILY_SQL)
        self.assertIn("sum(coalesce(sales_amount, 0)) as sales_amount", SELECT_PRODUCT_DAILY_SQL)
        self.assertIn("sum(coalesce(order_gross_profit, 0)) as order_gross_profit", SELECT_PRODUCT_DAILY_SQL)
        self.assertIn("coalesce(i.stock_up_num", SELECT_PRODUCT_DAILY_SQL)
        self.assertNotIn("sum(coalesce(afn_fulfillable_quantity", SELECT_PRODUCT_DAILY_SQL)
        self.assertNotIn("i.afn_fulfillable_quantity", SELECT_PRODUCT_DAILY_SQL)

    def test_avg_sales_uses_only_salable_days_as_denominator(self):
        rows = [
            product_row(date(2026, 1, 1), 10, 2),
            product_row(date(2026, 1, 2), 0, 5),
            product_row(date(2026, 1, 3), 8, 3),
        ]

        self.assertEqual(Decimal("5"), avg_sales(rows, date(2026, 1, 1), date(2026, 1, 3)))

    def test_salable_sales_qty_uses_only_salable_days(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 6, 1) for i in range(25)]
        rows[3]["afn_fulfillable_quantity"] = Decimal("0")
        rows[3]["sales_qty"] = Decimal("99")

        self.assertEqual(
            Decimal("20"),
            salable_sales_qty(rows, date(2026, 1, 1), date(2026, 1, 21)),
        )

    def test_sales_role_uses_pre_stockout_available_daily_sales_and_margin(self):
        self.assertEqual("明星产品", sales_role(Decimal("6"), Decimal("0.16")))
        self.assertEqual("明星产品", sales_role(Decimal("3"), Decimal("0.26")))
        self.assertEqual("潜力产品", sales_role(Decimal("6"), Decimal("0.10")))
        self.assertEqual("潜力产品", sales_role(Decimal("3"), Decimal("0.20")))
        self.assertEqual("瘦狗产品", sales_role(Decimal("3"), Decimal("0.08")))
        self.assertEqual("瘦狗产品", sales_role(Decimal("0.8"), Decimal("0.06")))
        self.assertEqual("问题产品", sales_role(Decimal("0"), Decimal("0.20")))
        self.assertEqual("问题产品", sales_role(Decimal("2"), Decimal("0.04")))

    def test_builds_one_event_after_stockout_recovers(self):
        start = date(2026, 1, 1)
        rows = [product_row(start + timedelta(days=i), 10, 2) for i in range(7)]
        rows.append(product_row(date(2026, 1, 8), 0, 0))
        rows.append(product_row(date(2026, 1, 9), 3, 1))
        rows.append(product_row(date(2026, 1, 10), 6, 4))

        events = build_events(rows, date(2026, 1, 12))

        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual(date(2026, 1, 8), event["stockout_date"])
        self.assertEqual(date(2026, 1, 10), event["return_start_date"])
        self.assertEqual("观察期", event["stage"])
        self.assertIsNone(event["exit_reason"])
        self.assertEqual(Decimal("14"), event["pre_7d_sales_qty"])
        self.assertEqual(Decimal("2"), event["pre_7d_sales_avg"])
        self.assertEqual(Decimal("0.2"), event["pre_7d_gross_margin_rate"])
        self.assertEqual("潜力产品", event["pre_stockout_sales_role"])
        self.assertEqual(Decimal("4"), event["observe_7d_sales_qty"])
        self.assertEqual(Decimal("4"), event["observe_7d_sales_avg"])
        self.assertEqual(Decimal("4"), event["post_7d_sales_qty"])
        self.assertEqual(Decimal("4"), event["post_21d_available_sales_qty"])
        self.assertEqual(3, event["recovery_window_days"])
        self.assertEqual(Decimal("6"), event["pre_recovery_sales_qty"])
        self.assertEqual(Decimal("4"), event["post_recovery_sales_qty"])
        self.assertEqual(Decimal("4") / Decimal("6"), event["sales_recovery_rate"])

    def test_stockout_date_is_first_day_of_continuous_stockout_before_recovery(self):
        start = date(2026, 1, 1)
        rows = [product_row(start + timedelta(days=i), 10, 2) for i in range(7)]
        rows.extend(
            [
                product_row(date(2026, 1, 8), 0, 0),
                product_row(date(2026, 1, 9), 0, 1),
                product_row(date(2026, 1, 10), 3, 1),
                product_row(date(2026, 1, 11), 0, 0),
                product_row(date(2026, 1, 12), 6, 2),
            ]
        )

        events = build_events(rows, date(2026, 1, 12))

        self.assertEqual(1, len(events))
        self.assertEqual(date(2026, 1, 8), events[0]["stockout_date"])
        self.assertEqual(date(2026, 1, 12), events[0]["return_start_date"])

    def test_stockout_inside_21_day_monitor_does_not_close_event(self):
        rows = []
        for i in range(7):
            rows.append(product_row(date(2026, 1, 1) + timedelta(days=i), 10, 2))
        rows.extend(
            [
                product_row(date(2026, 1, 8), 0, 0),
                product_row(date(2026, 1, 9), 6, 3),
                product_row(date(2026, 1, 10), 7, 3),
                product_row(date(2026, 1, 11), 0, 0),
                product_row(date(2026, 1, 12), 4, 1),
                product_row(date(2026, 1, 13), 6, 2),
            ]
        )

        events = build_events(rows, date(2026, 1, 13))

        self.assertEqual(2, len(events))
        self.assertEqual(1, events[0]["return_round"])
        self.assertEqual(date(2026, 1, 8), events[0]["stockout_date"])
        self.assertEqual(date(2026, 1, 9), events[0]["return_start_date"])
        self.assertEqual(2, events[1]["return_round"])
        self.assertEqual(date(2026, 1, 11), events[1]["stockout_date"])
        self.assertEqual(date(2026, 1, 13), events[1]["return_start_date"])
        return

        self.assertEqual(1, len(events))
        self.assertEqual(1, events[0]["return_round"])
        self.assertIsNone(events[0]["exit_reason"])
        self.assertIsNone(events[0]["exit_date"])
        self.assertEqual("观察期", events[0]["stage"])
        self.assertIsNone(events[0]["warning_type"])

    def test_stockout_inside_21_day_monitor_starts_latest_stockout_segment(self):
        rows = []
        for i in range(7):
            rows.append(product_row(date(2026, 1, 1) + timedelta(days=i), 10, 2))
        rows.extend(
            [
                product_row(date(2026, 1, 8), 0, 0),
                product_row(date(2026, 1, 9), 6, 3),
                product_row(date(2026, 1, 10), 7, 3),
                product_row(date(2026, 1, 11), 0, 0),
                product_row(date(2026, 1, 12), 4, 1),
                product_row(date(2026, 1, 13), 6, 2),
            ]
        )

        events = build_events(rows, date(2026, 1, 13))

        self.assertEqual(2, len(events))
        self.assertEqual(1, events[0]["return_round"])
        self.assertEqual(date(2026, 1, 8), events[0]["stockout_date"])
        self.assertEqual(date(2026, 1, 9), events[0]["return_start_date"])
        self.assertEqual(2, events[1]["return_round"])
        self.assertEqual(date(2026, 1, 11), events[1]["stockout_date"])
        self.assertEqual(date(2026, 1, 13), events[1]["return_start_date"])

    def test_latest_return_uses_first_zero_after_previous_return_without_21_day_gap(self):
        rows = []
        for i in range(7):
            rows.append(product_row(date(2026, 4, 19) + timedelta(days=i), 10, 2))
        rows.append(product_row(date(2026, 4, 26), 0, 0))
        rows.extend(product_row(date(2026, 4, 27) + timedelta(days=i), 0, 0) for i in range(9))
        rows.append(product_row(date(2026, 5, 6), 10, 2))
        rows.extend(
            [
                product_row(date(2026, 5, 9), 9, 2),
                product_row(date(2026, 5, 10), 5, 3),
                product_row(date(2026, 5, 11), 3, 3),
                product_row(date(2026, 5, 12), 1, 1),
                product_row(date(2026, 5, 13), 0, 1),
            ]
        )
        rows.extend(product_row(date(2026, 5, 14) + timedelta(days=i), 0, 0) for i in range(43))
        rows.append(product_row(date(2026, 6, 26), 24, 6))

        events = build_events(rows, date(2026, 7, 3))

        self.assertEqual(2, len(events))
        self.assertEqual(date(2026, 5, 13), events[-1]["stockout_date"])
        self.assertEqual(date(2026, 6, 26), events[-1]["return_start_date"])

    def test_next_round_starts_only_after_previous_monitor_window_ends(self):
        rows = []
        for i in range(7):
            rows.append(product_row(date(2026, 1, 1) + timedelta(days=i), 10, 2))
        rows.append(product_row(date(2026, 1, 8), 0, 0))
        for i in range(22):
            rows.append(product_row(date(2026, 1, 9) + timedelta(days=i), 6, 2))
        rows.extend(
            [
                product_row(date(2026, 1, 31), 0, 0),
                product_row(date(2026, 2, 1), 6, 2),
            ]
        )

        events = build_events(rows, date(2026, 2, 1))

        self.assertEqual(2, len(events))
        self.assertEqual("达标退出", events[0]["exit_reason"])
        self.assertEqual(date(2026, 1, 30), events[0]["exit_date"])
        self.assertEqual(2, events[1]["return_round"])
        self.assertEqual(date(2026, 2, 1), events[1]["return_start_date"])

    def test_zero_pre_sales_stays_in_data_insufficient_followup(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 0) for i in range(21)]
        rows.append(product_row(date(2026, 1, 22), 0, 0))
        for i in range(22):
            rows.append(product_row(date(2026, 1, 23) + timedelta(days=i), 6, 1))

        events = build_events(rows, date(2026, 2, 13))

        self.assertEqual(1, len(events))
        self.assertIsNone(events[0]["sales_recovery_rate"])
        self.assertIsNone(events[0]["exit_reason"])
        self.assertEqual("持续干预期", events[0]["stage"])
        self.assertTrue(events[0]["recovery_followup_flag"])
        self.assertEqual("数据不足持续关注", events[0]["recovery_followup_status"])

    def test_d21_standard_product_exits_without_followup(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 10) for i in range(21)]
        rows.append(product_row(date(2026, 1, 22), 0, 0))
        for i in range(22):
            rows.append(product_row(date(2026, 1, 23) + timedelta(days=i), 6, 8))

        high = build_events(rows, date(2026, 2, 13))[0]
        self.assertEqual("达标退出", high["exit_reason"])
        self.assertEqual(date(2026, 2, 13), high["exit_date"])
        self.assertEqual(22, high["days_to_standard"])
        self.assertEqual(Decimal("0.8"), high["d21_recovery_rate"])
        self.assertFalse(high["recovery_followup_flag"])
        self.assertIsNone(high["recovery_followup_status"])
        self.assertEqual(21, high["recovery_window_days"])
        self.assertEqual(Decimal("210"), high["pre_recovery_sales_qty"])
        self.assertEqual(Decimal("168"), high["post_recovery_sales_qty"])

    def test_d21_low_recovery_enters_continuous_followup_instead_of_exiting(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 10) for i in range(21)]
        rows.append(product_row(date(2026, 1, 22), 0, 0))
        for i in range(22):
            rows.append(product_row(date(2026, 1, 23) + timedelta(days=i), 6, 4))

        low = build_events(rows, date(2026, 2, 13))[0]

        self.assertIsNone(low["exit_reason"])
        self.assertIsNone(low["exit_date"])
        self.assertEqual("持续干预期", low["stage"])
        self.assertEqual(Decimal("0.4"), low["d21_recovery_rate"])
        self.assertTrue(low["recovery_followup_flag"])
        self.assertEqual(Decimal("0.4"), low["cumulative_avg_recovery_rate"])
        self.assertEqual("截至目前严重恢复不足", low["recovery_followup_status"])

    def test_followup_product_exits_on_first_late_cumulative_average_recovery_day(self):
        low_rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 10) for i in range(21)]
        low_rows.append(product_row(date(2026, 1, 22), 0, 0))
        low_rows.extend(product_row(date(2026, 1, 23) + timedelta(days=i), 6, 4) for i in range(21))
        low_rows.extend(product_row(date(2026, 2, 13) + timedelta(days=i), 6, 20) for i in range(9))

        recovered = build_events(low_rows, date(2026, 2, 21))[0]

        self.assertEqual("达标退出", recovered["exit_reason"])
        self.assertEqual(date(2026, 2, 17), recovered["exit_date"])
        self.assertEqual(26, recovered["days_to_standard"])
        self.assertTrue(recovered["recovery_followup_flag"])
        self.assertEqual("21天后恢复达标", recovered["recovery_followup_status"])
        self.assertEqual(Decimal("184"), recovered["post_cumulative_sales_qty"])
        self.assertEqual(Decimal("184") / Decimal("260"), recovered["cumulative_avg_recovery_rate"])
        self.assertEqual(date(2026, 2, 13), recovered["stable_recovery_start_date"])
        self.assertTrue(recovered["current_stable_recovery_flag"])
        self.assertFalse(recovered["recovery_fallback_flag"])

    def test_stable_recovery_requires_three_consecutive_days_and_marks_later_fallback(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 10) for i in range(21)]
        rows.append(product_row(date(2026, 1, 22), 0, 0))
        rows.extend(product_row(date(2026, 1, 23) + timedelta(days=i), 6, 4) for i in range(21))
        followup_sales = [5, 4, 5, 5, 5, 0]
        rows.extend(
            product_row(date(2026, 2, 13) + timedelta(days=i), 6, sales)
            for i, sales in enumerate(followup_sales)
        )

        stable = build_events(rows[:-1], date(2026, 2, 17))[0]
        fallback = build_events(rows, date(2026, 2, 18))[0]

        self.assertEqual(date(2026, 2, 15), stable["stable_recovery_start_date"])
        self.assertTrue(stable["current_stable_recovery_flag"])
        self.assertFalse(stable["recovery_fallback_flag"])
        self.assertEqual(date(2026, 2, 15), fallback["stable_recovery_start_date"])
        self.assertFalse(fallback["current_stable_recovery_flag"])
        self.assertTrue(fallback["recovery_fallback_flag"])

    def test_stable_recovery_treats_missing_natural_day_as_zero_sales(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 10) for i in range(21)]
        rows.append(product_row(date(2026, 1, 22), 0, 0))
        rows.extend(product_row(date(2026, 1, 23) + timedelta(days=i), 6, 4) for i in range(21))
        rows.extend(
            [
                product_row(date(2026, 2, 13), 6, 5),
                product_row(date(2026, 2, 15), 6, 5),
                product_row(date(2026, 2, 16), 6, 5),
            ]
        )

        event = build_events(rows, date(2026, 2, 16))[0]

        self.assertIsNone(event["stable_recovery_start_date"])
        self.assertFalse(event["current_stable_recovery_flag"])

    def test_tracks_sales_after_21_day_monitor_separately_from_recovery_sales(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 2) for i in range(7)]
        rows.append(product_row(date(2026, 1, 8), 0, 0))
        rows.extend(product_row(date(2026, 1, 9) + timedelta(days=i), 6, 0) for i in range(21))
        rows.append(product_row(date(2026, 1, 30), 6, 2))

        event = build_events(rows, date(2026, 1, 30))[0]

        self.assertEqual(Decimal("0"), event["post_recovery_sales_qty"])
        self.assertEqual(Decimal("2"), event["post_return_sales_qty"])

    def test_ignores_return_start_outside_180_day_recognition_window(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 2) for i in range(7)]
        rows.append(product_row(date(2026, 1, 8), 0, 0))
        rows.append(product_row(date(2026, 1, 9), 6, 2))

        events = build_events(rows, date(2026, 7, 20), lookback_days=180)

        self.assertEqual([], events)


if __name__ == "__main__":
    unittest.main()
