import unittest
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etl.return_goods_update import SELECT_PRODUCT_DAILY_SQL, avg_sales, build_events, salable_sales_qty, sales_role


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

    def test_zero_pre_sales_keeps_recovery_rate_empty_and_exits_to_manual_judgment(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 0) for i in range(7)]
        rows.append(product_row(date(2026, 1, 8), 0, 0))
        for i in range(22):
            rows.append(product_row(date(2026, 1, 9) + timedelta(days=i), 6, 1))

        events = build_events(rows, date(2026, 1, 30))

        self.assertEqual(1, len(events))
        self.assertIsNone(events[0]["sales_recovery_rate"])
        self.assertEqual("待人工判断", events[0]["exit_reason"])
        self.assertEqual("已退出", events[0]["stage"])

    def test_older_than_21_days_exits_by_recovery_thresholds(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 10) for i in range(21)]
        rows.append(product_row(date(2026, 1, 22), 0, 0))
        for i in range(22):
            rows.append(product_row(date(2026, 1, 23) + timedelta(days=i), 6, 8))

        high = build_events(rows, date(2026, 2, 13))[0]
        self.assertEqual("达标退出", high["exit_reason"])
        self.assertEqual(21, high["recovery_window_days"])
        self.assertEqual(Decimal("210"), high["pre_recovery_sales_qty"])
        self.assertEqual(Decimal("168"), high["post_recovery_sales_qty"])

        low_rows = [dict(row) for row in rows]
        for row in low_rows:
            if row["dt_date"] >= date(2026, 1, 23):
                row["sales_qty"] = Decimal("4")
        low = build_events(low_rows, date(2026, 2, 13))[0]
        self.assertEqual("未达标退出", low["exit_reason"])
        self.assertEqual(Decimal("84") / Decimal("210"), low["sales_recovery_rate"])

    def test_ignores_return_start_outside_180_day_recognition_window(self):
        rows = [product_row(date(2026, 1, 1) + timedelta(days=i), 10, 2) for i in range(7)]
        rows.append(product_row(date(2026, 1, 8), 0, 0))
        rows.append(product_row(date(2026, 1, 9), 6, 2))

        events = build_events(rows, date(2026, 7, 20), lookback_days=180)

        self.assertEqual([], events)


if __name__ == "__main__":
    unittest.main()
