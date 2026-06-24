import unittest

from app.services.replenishment_data import (
    FLOW_ENTRY_LABEL,
    LEVEL_HISTORY_RECOVERY,
    LEVEL_PLANNED,
    LEVEL_SUGGESTED,
    LEVEL_SUFFICIENT,
    LEVEL_URGENT,
    LEVEL_ZERO_SALES,
    ReplenishmentDataService,
)


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return FakeCursor(self.rows)


class RecordingCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.conn.queries.append(str(query))
        self.conn.params.append(params or {})

    def fetchall(self):
        return self.conn.rows


class RecordingConnection:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.params = []

    def cursor(self):
        return RecordingCursor(self)


class ReplenishmentDataServiceTests(unittest.TestCase):
    def test_export_columns_excludes_empty_gmv_and_gross_profit_fields(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        service.database = "etl_datasync_test"
        conn = FakeConnection(
            [
                {"column_name": "seller_sku_adj", "column_comment": ""},
                {"column_name": "stockout_status", "column_comment": ""},
                {"column_name": "fllow_flag", "column_comment": ""},
                {"column_name": "gamount_30d", "column_comment": ""},
                {"column_name": "gamount_14d", "column_comment": ""},
                {"column_name": "gamount_7d", "column_comment": ""},
                {"column_name": "gamount_3d", "column_comment": ""},
                {"column_name": "gprofit_30d", "column_comment": ""},
                {"column_name": "gprofit_14d", "column_comment": ""},
                {"column_name": "gprofit_7d", "column_comment": ""},
                {"column_name": "gprofit_3d", "column_comment": ""},
                {"column_name": "gprofit_ratio_30d", "column_comment": ""},
                {"column_name": "gprofit_ratio_14d", "column_comment": ""},
                {"column_name": "gprofit_ratio_7d", "column_comment": ""},
                {"column_name": "gprofit_ratio_3d", "column_comment": ""},
                {"column_name": "pre_1m_predict_abcd_category", "column_comment": ""},
                {"column_name": "pre_1q_predict_abcd_category", "column_comment": ""},
                {"column_name": "replenish_qty", "column_comment": ""},
            ]
        )

        columns = service._export_columns(conn)

        names = [column["name"] for column in columns]
        self.assertEqual(["seller_sku_adj", "fllow_flag", "replenish_qty"], names)
        labels = {column["name"]: column["label"] for column in columns}
        self.assertEqual("是否跟卖", labels["fllow_flag"])

    def test_serialize_item_exposes_follow_status(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        item = service._serialize_item(
            {
                "cur_date": None,
                "support_replenish_level_sort": 1,
                "daily_avg_sales": 0,
                "category_daily_sales_30d": 0,
                "pprofit_ratio_30d": 0,
                "inventory_support_days": 0,
                "support_inventory_qty": 0,
                "available_total": 0,
                "stock_up_num": 0,
                "local_quantity": 0,
                "sc_quantity_purchase_plan": 0,
                "final_sales_30d": 0,
                "replenish_need_qty": 0,
                "replenish_qty": 0,
                "replenish_box_qty": 0,
                "replenish_cost": 0,
                "fllow_flag": 0,
            }
        )

        self.assertEqual("是", item["follow_status"])
        self.assertNotIn("stockout_status", item)

    def test_export_items_formats_follow_flag(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        conn = FakeConnection([{"seller_sku_adj": "OYJ078a", "fllow_flag": 0}])

        rows = service._export_items(
            conn,
            filters="cur_date = %(snapshot_date)s",
            params={"snapshot_date": "2026-06-22"},
            sort_field="",
            sort_dir="",
            columns=["seller_sku_adj", "fllow_flag"],
        )

        self.assertEqual("是", rows[0]["fllow_flag"])


    def test_export_items_uses_selected_period_category_expression(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        conn = RecordingConnection([{"abcd_category": "x", "gp_margin_range": "y"}])
        metrics = service._product_category_metric_sql(90)

        service._export_items(
            conn,
            filters="cur_date = %(snapshot_date)s",
            params={"snapshot_date": "2026-06-24"},
            sort_field="category",
            sort_dir="asc",
            columns=["abcd_category", "gp_margin_range"],
            period_metrics=metrics,
        )

        sql = conn.queries[0]
        self.assertIn("sales_90d / r_90d_salable_days", sql)
        self.assertIn("as `abcd_category`", sql)
        self.assertIn("as `gp_margin_range`", sql)
        self.assertIn("order by", sql)

    def test_normalize_country_period_days_allows_only_supported_periods(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        self.assertEqual(30, service._normalize_country_period_days(None))
        self.assertEqual(7, service._normalize_country_period_days(7))
        self.assertEqual(90, service._normalize_country_period_days("90"))
        self.assertEqual(30, service._normalize_country_period_days(21))

    def test_product_category_period_days_supports_90_and_180(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        self.assertEqual(30, service._normalize_product_category_period_days(None))
        self.assertEqual(90, service._normalize_product_category_period_days("90"))
        self.assertEqual(180, service._normalize_product_category_period_days(180))
        self.assertEqual(30, service._normalize_product_category_period_days(365))

        metrics_90 = service._product_category_metric_sql(90)
        metrics_180 = service._product_category_metric_sql(180)
        self.assertIn("sales_90d / r_90d_salable_days", metrics_90["daily_sales_expr"])
        self.assertEqual("pprofit_ratio_90d", metrics_90["margin_col"])
        self.assertIn("sales_180d / r_180d_salable_days", metrics_180["daily_sales_expr"])
        self.assertEqual("pprofit_ratio_180d", metrics_180["margin_col"])

    def test_history_recovery_display_layer_only_covers_passive_rows(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        condition = service._history_recovery_display_condition()
        level_expr = service._display_level_expr()
        sort_expr = service._display_level_sort_expr()

        self.assertIn("history_recovery_flag", condition)
        self.assertIn("support_replenish_level_sort, 99) not in (1, 2, 3)", condition)
        self.assertIn("then %(level_history_recovery)s", level_expr)
        self.assertIn("then 6", sort_expr)
        self.assertEqual(
            {"level_history_recovery": LEVEL_HISTORY_RECOVERY, "snapshot_date": "2026-06-24"},
            service._with_display_level_params({"snapshot_date": "2026-06-24"}),
        )

    def test_history_recovery_display_replenish_qty_restores_one_box(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        qty_expr = service._display_replenish_qty_expr()
        box_expr = service._display_replenish_box_qty_expr()
        cost_expr = service._display_replenish_cost_expr()

        self.assertIn("max_cg_box_pcs", qty_expr)
        self.assertIn("else 50", qty_expr)
        self.assertIn("then 1 else 0", box_expr)
        self.assertIn("max_cg_price", cost_expr)
        self.assertIn("max_cg_transport_costs", cost_expr)

    def test_serialize_country_metric_formats_display_fields(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        item = service._serialize_country_metric(
            {
                "country": "\u5fb7\u56fd",
                "local_sku_list": "GQ1177a-de,GQ1177a-de-2",
                "listing_price": 19.995,
                "sales_qty": 10,
                "natural_daily_sales": 1.428571,
                "salable_days": 5,
                "salable_daily_sales": 2,
                "sales_amount": 1000,
                "order_gross_profit": 200,
                "order_gross_margin": 0.2,
                "avg_ranking": 12.345,
                "best_ranking": 5,
                "worst_ranking": 30,
                "sessions_total": 100,
                "conversion_rate": 0.1,
                "ad_spend": 50,
                "ad_orders": 2,
                "ad_sales": 500,
                "ad_clicks": 20,
                "ad_impressions": 1000,
                "acos": 0.1,
                "ctr": 0.02,
            }
        )

        self.assertEqual("\u5fb7\u56fd", item["country"])
        self.assertEqual("GQ1177a-de,GQ1177a-de-2", item["local_sku_list"])
        self.assertEqual(19.995, item["listing_price"])
        self.assertEqual(0.2, item["order_gross_margin"])
        self.assertEqual(12.35, item["avg_ranking"])

    def test_build_level_flow_payload_classifies_level_changes(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        rows = [
            {
                "country_category": "欧洲站",
                "seller_name_new": "StoreA",
                "seller_sku_adj": "A001",
                "prev_level": "紧急补货",
                "prev_level_sort": 1,
                "cur_level": "建议补货",
                "cur_level_sort": 2,
                "prev_replenish_qty": 10,
                "cur_replenish_qty": 5,
                "prev_replenish_cost": 100,
                "cur_replenish_cost": 50,
                "prev_inventory_support_days": 30,
                "cur_inventory_support_days": 40,
                "prev_support_inventory_qty": 100,
                "cur_support_inventory_qty": 120,
                "prev_daily_avg_sales": 3,
                "cur_daily_avg_sales": 3,
            },
            {
                "country_category": "欧洲站",
                "seller_name_new": "StoreA",
                "seller_sku_adj": "B001",
                "prev_level": None,
                "prev_level_sort": None,
                "cur_level": "紧急补货",
                "cur_level_sort": 1,
                "prev_replenish_qty": None,
                "cur_replenish_qty": 12,
                "prev_replenish_cost": None,
                "cur_replenish_cost": 120,
            },
            {
                "country_category": "欧洲站",
                "seller_name_new": "StoreA",
                "seller_sku_adj": "C001",
                "prev_level": "计划补货",
                "prev_level_sort": 3,
                "cur_level": None,
                "cur_level_sort": None,
                "prev_replenish_qty": 7,
                "cur_replenish_qty": None,
                "prev_replenish_cost": 70,
                "cur_replenish_cost": None,
            },
            {
                "country_category": "欧洲站",
                "seller_name_new": "StoreA",
                "seller_sku_adj": "D001",
                "prev_level": "建议补货",
                "prev_level_sort": 2,
                "cur_level": "紧急补货",
                "cur_level_sort": 1,
                "prev_replenish_qty": 3,
                "cur_replenish_qty": 8,
                "prev_replenish_cost": 30,
                "cur_replenish_cost": 80,
            },
            {
                "country_category": "欧洲站",
                "seller_name_new": "StoreA",
                "seller_sku_adj": "E001",
                "prev_level": LEVEL_URGENT,
                "prev_level_sort": 1,
                "cur_level": LEVEL_SUFFICIENT,
                "cur_level_sort": 4,
                "prev_replenish_qty": 9,
                "cur_replenish_qty": 0,
                "prev_replenish_cost": 90,
                "cur_replenish_cost": 0,
            },
            {
                "country_category": "欧洲站",
                "seller_name_new": "StoreA",
                "seller_sku_adj": "F001",
                "prev_level": LEVEL_ZERO_SALES,
                "prev_level_sort": 5,
                "cur_level": LEVEL_URGENT,
                "cur_level_sort": 1,
                "prev_replenish_qty": 0,
                "cur_replenish_qty": 11,
                "prev_replenish_cost": 0,
                "cur_replenish_cost": 110,
            },
        ]

        payload = service._build_level_flow_payload(rows, "2026-06-21", "2026-06-22")

        urgent = next(item for item in payload["level_changes"] if item["level"] == "紧急补货")
        suggested = next(item for item in payload["level_changes"] if item["level"] == "建议补货")
        planned = next(item for item in payload["level_changes"] if item["level"] == "计划补货")
        self.assertEqual(1, urgent["new_count"])
        self.assertEqual(2, urgent["in_count"])
        self.assertEqual(1, urgent["exit_count"])
        self.assertEqual(1, suggested["out_count"])
        self.assertEqual(-1, planned["delta_count"])
        self.assertEqual(0, planned["exit_count"])
        self.assertEqual(1, planned["out_count"])
        self.assertIn(
            {"source": "昨天建议补货", "target": "今天紧急补货", "value": 1, "replenish_qty": 8.0, "replenish_cost": 80.0},
            payload["sankey"]["links"],
        )
        self.assertEqual(
            [
                f"昨天{LEVEL_URGENT}",
                f"昨天{LEVEL_SUGGESTED}",
                f"昨天{LEVEL_PLANNED}",
                f"昨天{LEVEL_ZERO_SALES}",
                f"昨天{FLOW_ENTRY_LABEL}",
                f"今天{LEVEL_URGENT}",
                f"今天{LEVEL_SUGGESTED}",
                f"今天{LEVEL_SUFFICIENT}",
                f"今天{FLOW_ENTRY_LABEL}",
            ],
            [node["name"] for node in payload["sankey"]["nodes"]],
        )
        detail = next(item for item in payload["items"] if item["msku"] == "A001")
        self.assertEqual("流出", detail["flow_type"])
        self.assertEqual("库存增加", detail["reason"])
        exit_detail = next(item for item in payload["items"] if item["msku"] == "E001")
        self.assertEqual("退出", exit_detail["flow_type"])
        self.assertEqual("转入基础池", exit_detail["reason"])
        new_detail = next(item for item in payload["items"] if item["msku"] == "F001")
        self.assertEqual("新增", new_detail["flow_type"])
        self.assertEqual("转入补货计算", new_detail["reason"])


if __name__ == "__main__":
    unittest.main()
