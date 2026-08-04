import unittest

from app.services.replenishment_data import (
    FLOW_ENTRY_LABEL,
    LEVEL_BELOW_MOQ,
    LEVEL_HISTORY_RECOVERY,
    LEVEL_PLANNED,
    LEVEL_SUGGESTED,
    LEVEL_SUFFICIENT,
    LEVEL_URGENT,
    LEVEL_ZERO_SALES,
    REPLENISHMENT_COLUMN_LABELS,
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

    def fetchone(self):
        return self.conn.rows[0] if self.conn.rows else None


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
                {"column_name": "followed_flag", "column_comment": ""},
                {"column_name": "followed_by_links", "column_comment": ""},
                {"column_name": "replenish_block_reason", "column_comment": ""},
                {"column_name": "asin_merge_flag", "column_comment": ""},
                {"column_name": "asin_merge_target", "column_comment": ""},
                {"column_name": "asin_merge_reason", "column_comment": ""},
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
                {"column_name": "final_profit_rate", "column_comment": "最终利润率"},
                {"column_name": "replenish_qty", "column_comment": ""},
            ]
        )

        columns = service._export_columns(conn)

        names = [column["name"] for column in columns]
        self.assertEqual(
            [
                "seller_sku_adj",
                "fllow_flag",
                "followed_flag",
                "followed_by_links",
                "replenish_block_reason",
                "asin_merge_flag",
                "asin_merge_target",
                "asin_merge_reason",
                "final_profit_rate",
                "replenish_qty",
            ],
            names,
        )
        labels = {column["name"]: column["label"] for column in columns}
        self.assertEqual("是否跟卖", labels["fllow_flag"])
        self.assertEqual("是否被跟卖", labels["followed_flag"])
        self.assertEqual("订单原始毛利率", labels["final_profit_rate"])

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
                "followed_flag": 1,
                "followed_by_count": 2,
                "followed_by_links": "store-a/MSKU-A | store-b/MSKU-B",
                "follow_origin_link": "origin-store/ORIGIN-MSKU",
                "replenish_block_reason": "被跟卖点不补货",
                "asin_merge_flag": 1,
                "asin_merge_target": "store-a/MSKU-A",
                "asin_merge_reason": "同ASIN已合并补货",
                "global_tags": "德国:清货8.8 | 英国:高风险产品",
            }
        )

        self.assertEqual("是", item["follow_status"])
        self.assertEqual("是", item["followed_status"])
        self.assertEqual(2, item["followed_by_count"])
        self.assertEqual("store-a/MSKU-A | store-b/MSKU-B", item["followed_by_links"])
        self.assertEqual("origin-store/ORIGIN-MSKU", item["follow_origin_link"])
        self.assertEqual("被跟卖点不补货", item["replenish_block_reason"])
        self.assertEqual("是", item["asin_merge_status"])
        self.assertEqual("store-a/MSKU-A", item["asin_merge_target"])
        self.assertEqual("同ASIN已合并补货", item["asin_merge_reason"])
        self.assertEqual("德国:清货8.8 | 英国:高风险产品", item["listing_tags"])
        self.assertNotIn("stockout_status", item)

    def test_items_query_selects_and_sorts_listing_tags(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        conn = RecordingConnection([])
        metrics = service._product_category_metric_sql(30)

        service._items(
            conn,
            filters="cur_date = %(snapshot_date)s",
            params={"snapshot_date": "2026-07-07"},
            sort_field="listing_tags",
            sort_dir="asc",
            page=1,
            page_size=20,
            period_metrics=metrics,
        )

        sql = conn.queries[1]
        self.assertIn("global_tags", sql)
        self.assertIn("order by global_tags asc", sql)

    def test_export_items_formats_follow_flag(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        conn = FakeConnection([{"seller_sku_adj": "OYJ078a", "fllow_flag": 0, "followed_flag": 1}])

        rows = service._export_items(
            conn,
            filters="cur_date = %(snapshot_date)s",
            params={"snapshot_date": "2026-06-22"},
            sort_field="",
            sort_dir="",
            columns=["seller_sku_adj", "fllow_flag", "followed_flag"],
        )

        self.assertEqual("是", rows[0]["fllow_flag"])
        self.assertEqual("是", rows[0]["followed_flag"])

    def test_export_items_formats_moq_status_in_chinese(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        conn = FakeConnection(
            [
                {"moq_status": "met"},
                {"moq_status": "below_minimum"},
                {"moq_status": "unconfigured"},
                {"moq_status": "not_applicable"},
            ]
        )

        rows = service._export_items(
            conn,
            filters="cur_date = %(snapshot_date)s",
            params={"snapshot_date": "2026-07-22"},
            sort_field="",
            sort_dir="",
            columns=["moq_status"],
        )

        self.assertEqual(
            ["已达起订量", "低于最小起订量", "MOQ未配置", "补货数量为0"],
            [row["moq_status"] for row in rows],
        )

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
        self.assertIn("sales_90d / greatest(r_90d_salable_days, 45)", sql)
        self.assertIn("as `abcd_category`", sql)
        self.assertIn("as `gp_margin_range`", sql)
        self.assertIn("order by", sql)

    def test_export_uses_calculated_values_for_below_moq_existing_quantity_columns(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        metrics = service._product_category_metric_sql(30)

        qty_expr = service._export_select_expression("replenish_qty", metrics)
        box_expr = service._export_select_expression("replenish_box_qty", metrics)
        cost_expr = service._export_select_expression("replenish_cost", metrics)

        self.assertIn("moq_status = 'below_minimum'", qty_expr)
        self.assertIn("calculated_replenish_qty", qty_expr)
        self.assertIn("calculated_replenish_box_qty", box_expr)
        self.assertIn("calculated_replenish_cost", cost_expr)
        self.assertIn("executable_replenish_qty", qty_expr)

    def test_export_uses_independent_below_moq_display_layer(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        metrics = service._product_category_metric_sql(30)

        level_expr = service._export_select_expression("support_replenish_level", metrics)
        sort_expr = service._export_select_expression("support_replenish_level_sort", metrics)

        self.assertIn("moq_status = 'below_minimum'", level_expr)
        self.assertIn("level_below_moq", level_expr)
        self.assertIn("then 7", sort_expr)

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
        self.assertIn("sales_90d / greatest(r_90d_salable_days, 45)", metrics_90["daily_sales_expr"])
        self.assertEqual("pprofit_ratio_90d", metrics_90["margin_col"])
        self.assertIn("sales_180d / greatest(r_180d_salable_days, 90)", metrics_180["daily_sales_expr"])
        self.assertEqual("pprofit_ratio_180d", metrics_180["margin_col"])

    def test_product_category_daily_sales_uses_half_period_salable_day_floor(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        expected_floors = {
            7: ("final_sales_7d", "r_7d_salable_days", 4),
            14: ("final_sales_14d", "r_14d_salable_days", 7),
            30: ("final_sales_30d", "r_30d_salable_days", 15),
            90: ("sales_90d", "r_90d_salable_days", 45),
            180: ("sales_180d", "r_180d_salable_days", 90),
        }

        for period, (sales_col, salable_col, floor_days) in expected_floors.items():
            with self.subTest(period=period):
                metrics = service._product_category_metric_sql(period)
                expr = metrics["daily_sales_expr"]

                self.assertIn(f"case when {salable_col} > 0", expr)
                self.assertIn(f"{sales_col} / greatest({salable_col}, {floor_days})", expr)
                self.assertIn("else 0 end", expr)

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
            {
                "level_below_moq": LEVEL_BELOW_MOQ,
                "level_history_recovery": LEVEL_HISTORY_RECOVERY,
                "level_sufficient": "库存充足",
                "level_followed_block": "被跟卖点不补货",
                "asin_merge_consolidated_block": "同ASIN已合并至主链接",
                "asin_merge_sufficient_block": "同ASIN库存充足不补货",
                "snapshot_date": "2026-06-24",
            },
            service._with_display_level_params({"snapshot_date": "2026-06-24"}),
        )

    def test_followed_block_does_not_override_display_layer(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        condition = service._followed_block_display_condition()
        level_expr = service._display_level_expr()
        sort_expr = service._display_level_sort_expr()

        self.assertIn(
            "coalesce(replenish_block_reason, '') = %(level_followed_block)s",
            condition,
        )
        self.assertNotIn("then %(level_followed_block)s", level_expr)
        self.assertNotIn("replenish_block_reason = %(level_followed_block)s then 7", sort_expr)

    def test_asin_merge_zero_qty_displays_as_sufficient_layer(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        condition = service._asin_merge_zero_qty_display_condition()
        level_expr = service._display_level_expr()
        sort_expr = service._display_level_sort_expr()

        self.assertIn("asin_merge_flag", condition)
        self.assertIn("replenish_qty", condition)
        self.assertIn(
            "not (coalesce(replenish_block_reason, '') = %(level_followed_block)s)",
            condition,
        )
        self.assertIn("then %(level_sufficient)s", level_expr)
        self.assertIn("then 4", sort_expr)
        self.assertEqual(
            {
                "level_below_moq": LEVEL_BELOW_MOQ,
                "level_history_recovery": LEVEL_HISTORY_RECOVERY,
                "level_sufficient": "库存充足",
                "level_followed_block": "被跟卖点不补货",
                "asin_merge_consolidated_block": "同ASIN已合并至主链接",
                "asin_merge_sufficient_block": "同ASIN库存充足不补货",
                "snapshot_date": "2026-07-07",
            },
            service._with_display_level_params({"snapshot_date": "2026-07-07"}),
        )

    def test_below_moq_overrides_original_replenishment_layer(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        level_expr = service._display_level_expr("r")
        sort_expr = service._display_level_sort_expr("r")

        self.assertIn("r.moq_status = 'below_minimum'", level_expr)
        self.assertIn("then %(level_below_moq)s", level_expr)
        self.assertLess(level_expr.index("below_minimum"), level_expr.index("asin_merge_flag"))
        self.assertIn("r.moq_status = 'below_minimum'", sort_expr)
        self.assertIn("then 7", sort_expr)

    def test_level_filter_uses_display_layer_expression(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        filters, params = service._build_where(
            snapshot_date="2026-07-07",
            level="库存充足",
            category="all",
            site="all",
            store="all",
            keyword="",
        )

        self.assertIn(service._display_level_expr(), filters)
        self.assertNotIn("support_replenish_level = %(level)s", filters)
        self.assertEqual("库存充足", params["level"])

    def test_level_flow_query_uses_display_layer_expression(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        captured = {}

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def fetchall(self):
                return []

        class Conn:
            def cursor(self):
                return Cursor()

        service._level_flow_rows(
            Conn(),
            selected_date="2026-07-08",
            prev_date="2026-07-07",
            category="all",
            site="all",
            store="all",
            keyword="",
            category_expr="abcd_category",
            level="all",
            flow_type="all",
        )

        sql = captured["sql"]
        self.assertIn("case when p.seller_sku_adj is null then null else case when", sql)
        self.assertIn("when coalesce(c.asin_merge_flag, 0) = 1", sql)
        self.assertIn("when coalesce(p.asin_merge_flag, 0) = 1", sql)
        self.assertNotIn("p.support_replenish_level as prev_level", sql)
        self.assertNotIn("c.support_replenish_level as cur_level", sql)
        self.assertNotIn("p.support_replenish_level_sort as prev_level_sort", sql)
        self.assertNotIn("c.support_replenish_level_sort as cur_level_sort", sql)
        self.assertIn("level_sufficient", captured["params"])

    def test_history_recovery_display_replenish_qty_restores_one_box(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        condition = service._history_recovery_display_condition()
        qty_expr = service._display_replenish_qty_expr()
        box_expr = service._display_replenish_box_qty_expr()
        cost_expr = service._display_replenish_cost_expr()

        self.assertIn(
            "not (coalesce(replenish_block_reason, '') = %(level_followed_block)s)",
            condition,
        )
        self.assertIn("not (coalesce(asin_merge_flag, 0) = 1", condition)
        self.assertIn("coalesce(replenish_qty, 0) = 0", condition)
        self.assertIn("max_cg_box_pcs", qty_expr)
        self.assertIn("else 50", qty_expr)
        self.assertIn("then 1 else 0", box_expr)
        self.assertIn("max_cg_price", cost_expr)
        self.assertIn("max_cg_transport_costs", cost_expr)

    def test_display_replenishment_prefers_moq_executable_fields_with_legacy_fallback(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        qty_expr = service._display_replenish_qty_expr("r")
        box_expr = service._display_replenish_box_qty_expr("r")
        cost_expr = service._display_replenish_cost_expr("r")

        self.assertIn("r.executable_replenish_qty", qty_expr)
        self.assertIn("r.executable_replenish_box_qty", box_expr)
        self.assertIn("r.executable_replenish_cost", cost_expr)
        self.assertIn("r.moq_status is not null", qty_expr)
        self.assertIn("history_recovery_flag", qty_expr)

        calculated_expr = service._calculated_replenish_qty_expr("r")
        self.assertIn("r.calculated_replenish_qty", calculated_expr)
        self.assertIn("r.moq_status is not null", calculated_expr)
        self.assertIn("history_recovery_flag", calculated_expr)

    def test_detail_replenishment_uses_calculated_values_only_for_below_moq(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        qty_expr = service._detail_replenish_qty_expr("r")
        box_expr = service._detail_replenish_box_qty_expr("r")
        cost_expr = service._detail_replenish_cost_expr("r")

        self.assertIn("r.moq_status = 'below_minimum'", qty_expr)
        self.assertIn("r.calculated_replenish_qty", qty_expr)
        self.assertIn("r.calculated_replenish_box_qty", box_expr)
        self.assertIn("r.calculated_replenish_cost", cost_expr)
        self.assertIn("r.executable_replenish_qty", qty_expr)

    def test_calculated_box_and_cost_fall_back_for_existing_snapshots(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        box_expr = service._calculated_replenish_box_qty_expr("r")
        cost_expr = service._calculated_replenish_cost_expr("r")

        self.assertIn("r.calculated_replenish_box_qty", box_expr)
        self.assertIn("r.replenish_box_qty", box_expr)
        self.assertIn("r.calculated_replenish_cost", cost_expr)
        self.assertIn("r.replenish_cost", cost_expr)
        self.assertIn("history_recovery_flag", box_expr)

    def test_summary_history_count_uses_mutually_exclusive_display_layer(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        conn = RecordingConnection([{}])

        service._summary(conn, "cur_date = %(snapshot_date)s", {"snapshot_date": "2026-07-21"})

        sql = conn.queries[0]
        self.assertIn(
            f"sum(case when {service._display_level_expr()} = %(level_history_recovery)s then 1 else 0 end) as history_recovery_count",
            sql,
        )

    def test_calculated_box_and_cost_have_export_labels(self):
        self.assertEqual("计算补货箱数", REPLENISHMENT_COLUMN_LABELS["calculated_replenish_box_qty"])
        self.assertEqual("计算补货货值", REPLENISHMENT_COLUMN_LABELS["calculated_replenish_cost"])

    def test_purchase_lead_time_fields_have_export_labels(self):
        expected_labels = {
            "purchase_lead_days_raw": "采购交期原始天数",
            "effective_purchase_lead_days": "有效采购交期天数",
            "purchase_lead_status": "采购交期状态",
            "arrival_inventory_support_days": "到货时库存可支撑天数",
            "arrival_inventory_qty": "到货时预计库存",
            "lead_time_demand_qty": "采购交期需求量",
            "base_replenish_need_qty": "原补货需求量",
            "lead_adjusted_replenish_need_qty": "交期调整后补货需求量",
            "lead_time_stockout_flag": "交期内断货标记",
            "lead_time_stockout_days": "交期内预计断货天数",
            "lead_time_lost_sales_qty": "交期内预计损失销量",
        }

        for field, label in expected_labels.items():
            self.assertEqual(label, REPLENISHMENT_COLUMN_LABELS[field])

    def test_items_query_selects_purchase_lead_time_detail_fields(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        conn = RecordingConnection([])

        service._items(
            conn,
            filters="cur_date = %(snapshot_date)s",
            params={"snapshot_date": "2026-08-03"},
            sort_field="support_days",
            sort_dir="asc",
            page=1,
            page_size=20,
        )

        sql = conn.queries[1]
        for field in (
            "effective_purchase_lead_days",
            "purchase_lead_status",
            "arrival_inventory_support_days",
            "arrival_inventory_qty",
            "lead_time_demand_qty",
            "lead_time_stockout_flag",
            "lead_time_stockout_days",
        ):
            self.assertIn(field, sql)

    def test_serialize_item_exposes_purchase_lead_time_details_and_keeps_negative_values(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        item = service._serialize_item(
            {
                "cur_date": None,
                "daily_avg_sales": 6.6,
                "inventory_support_days": 7.4,
                "effective_purchase_lead_days": 10,
                "purchase_lead_status": "configured",
                "arrival_inventory_support_days": -2.6,
                "arrival_inventory_qty": -17.16,
                "lead_time_demand_qty": 66,
                "lead_time_stockout_flag": 1,
                "lead_time_stockout_days": 2.6,
            }
        )

        self.assertEqual(10, item["effective_purchase_lead_days"])
        self.assertEqual(-2.6, item["arrival_inventory_support_days"])
        self.assertEqual(-17.16, item["arrival_inventory_qty"])
        self.assertEqual(66, item["lead_time_demand_qty"])
        self.assertEqual(1, item["lead_time_stockout_flag"])
        self.assertEqual(2.6, item["lead_time_stockout_days"])
        self.assertEqual("configured", item["purchase_lead_status"])

    def test_serialize_item_keeps_missing_support_and_lead_time_values_nullable(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        item = service._serialize_item(
            {
                "cur_date": None,
                "daily_avg_sales": 1,
                "inventory_support_days": None,
                "effective_purchase_lead_days": None,
                "arrival_inventory_support_days": None,
                "arrival_inventory_qty": None,
                "lead_time_demand_qty": None,
                "lead_time_stockout_days": None,
            }
        )

        self.assertIsNone(item["support_days"])
        self.assertIsNone(item["effective_purchase_lead_days"])
        self.assertIsNone(item["arrival_inventory_support_days"])
        self.assertIsNone(item["arrival_inventory_qty"])
        self.assertIsNone(item["lead_time_demand_qty"])
        self.assertIsNone(item["lead_time_stockout_days"])

    def test_items_query_uses_detail_values_without_changing_summary_values(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        self.assertNotEqual(service._detail_replenish_qty_expr(), service._display_replenish_qty_expr())
        self.assertIn("calculated_replenish_qty", service._detail_replenish_qty_expr())
        self.assertNotIn("below_minimum", service._display_replenish_qty_expr())

    def test_build_where_supports_moq_warning_filter(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        filters, params = service._build_where(
            snapshot_date="2026-07-21",
            level="all",
            category="all",
            site="all",
            store="all",
            keyword="",
            moq_status="below_minimum",
        )

        self.assertIn("moq_status = %(moq_status)s", filters)
        self.assertEqual("below_minimum", params["moq_status"])

    def test_serialize_item_exposes_moq_warning_details(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        item = service._serialize_item(
            {
                "seller_sku_adj": "MSKU-1",
                "calculated_replenish_qty": 80,
                "replenish_qty": 0,
                "replenish_box_qty": 0,
                "replenish_cost": 0,
                "supplier_moq": 100,
                "moq_shortfall_qty": 20,
                "moq_status": "below_minimum",
            }
        )

        self.assertEqual(80, item["calculated_replenish_qty"])
        self.assertEqual(100, item["supplier_moq"])
        self.assertEqual(20, item["moq_shortfall_qty"])
        self.assertEqual("below_minimum", item["moq_status"])
        self.assertEqual(0, item["replenish_qty"])
    def test_history_recovery_display_cost_uses_restored_qty_and_unit_cost(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        qty_expr = service._history_recovery_restore_qty_expr("r")
        cost_expr = service._display_replenish_cost_expr("r")

        self.assertIn("r.max_cg_price is not null", cost_expr)
        self.assertIn("r.max_cg_transport_costs is not null", cost_expr)
        self.assertIn(f"then {qty_expr} *", cost_expr)
        self.assertIn("(r.max_cg_price + r.max_cg_transport_costs)", cost_expr)
        self.assertIn("else 0 end", cost_expr)

    def test_normal_display_rows_preserve_stored_replenishment_cost(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        cost_expr = service._display_replenish_cost_expr("r")

        self.assertIn("else coalesce(r.replenish_cost, 0) end", cost_expr)
        self.assertEqual(1, cost_expr.count("r.replenish_cost"))

    def test_display_replenishment_prefers_moq_executable_fields_with_legacy_fallback(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        qty_expr = service._display_replenish_qty_expr("r")
        box_expr = service._display_replenish_box_qty_expr("r")
        cost_expr = service._display_replenish_cost_expr("r")

        self.assertIn("r.executable_replenish_qty", qty_expr)
        self.assertIn("r.executable_replenish_box_qty", box_expr)
        self.assertIn("r.executable_replenish_cost", cost_expr)
        self.assertIn("r.moq_status is not null", qty_expr)
        self.assertIn("history_recovery_flag", qty_expr)

        calculated_expr = service._calculated_replenish_qty_expr("r")
        self.assertIn("r.calculated_replenish_qty", calculated_expr)
        self.assertIn("r.moq_status is not null", calculated_expr)
        self.assertIn("history_recovery_flag", calculated_expr)

    def test_detail_replenishment_uses_calculated_values_only_for_below_moq(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        qty_expr = service._detail_replenish_qty_expr("r")
        box_expr = service._detail_replenish_box_qty_expr("r")
        cost_expr = service._detail_replenish_cost_expr("r")

        self.assertIn("r.moq_status = 'below_minimum'", qty_expr)
        self.assertIn("r.calculated_replenish_qty", qty_expr)
        self.assertIn("r.calculated_replenish_box_qty", box_expr)
        self.assertIn("r.calculated_replenish_cost", cost_expr)
        self.assertIn("r.executable_replenish_qty", qty_expr)

    def test_calculated_box_and_cost_fall_back_for_existing_snapshots(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        box_expr = service._calculated_replenish_box_qty_expr("r")
        cost_expr = service._calculated_replenish_cost_expr("r")

        self.assertIn("r.calculated_replenish_box_qty", box_expr)
        self.assertIn("r.replenish_box_qty", box_expr)
        self.assertIn("r.calculated_replenish_cost", cost_expr)
        self.assertIn("r.replenish_cost", cost_expr)
        self.assertIn("history_recovery_flag", box_expr)

    def test_summary_history_count_uses_mutually_exclusive_display_layer(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        conn = RecordingConnection([{}])

        service._summary(conn, "cur_date = %(snapshot_date)s", {"snapshot_date": "2026-07-21"})

        sql = conn.queries[0]
        self.assertIn(
            f"sum(case when {service._display_level_expr()} = %(level_history_recovery)s then 1 else 0 end) as history_recovery_count",
            sql,
        )

    def test_calculated_box_and_cost_have_export_labels(self):
        self.assertEqual("计算补货箱数", REPLENISHMENT_COLUMN_LABELS["calculated_replenish_box_qty"])
        self.assertEqual("计算补货货值", REPLENISHMENT_COLUMN_LABELS["calculated_replenish_cost"])

    def test_items_query_uses_detail_values_without_changing_summary_values(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        self.assertNotEqual(service._detail_replenish_qty_expr(), service._display_replenish_qty_expr())
        self.assertIn("calculated_replenish_qty", service._detail_replenish_qty_expr())
        self.assertNotIn("below_minimum", service._display_replenish_qty_expr())

    def test_build_where_supports_moq_warning_filter(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        filters, params = service._build_where(
            snapshot_date="2026-07-21",
            level="all",
            category="all",
            site="all",
            store="all",
            keyword="",
            moq_status="below_minimum",
        )

        self.assertIn("moq_status = %(moq_status)s", filters)
        self.assertEqual("below_minimum", params["moq_status"])

    def test_serialize_item_exposes_moq_warning_details(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        item = service._serialize_item(
            {
                "seller_sku_adj": "MSKU-1",
                "calculated_replenish_qty": 80,
                "replenish_qty": 0,
                "replenish_box_qty": 0,
                "replenish_cost": 0,
                "supplier_moq": 100,
                "moq_shortfall_qty": 20,
                "moq_status": "below_minimum",
            }
        )

        self.assertEqual(80, item["calculated_replenish_qty"])
        self.assertEqual(100, item["supplier_moq"])
        self.assertEqual(20, item["moq_shortfall_qty"])
        self.assertEqual("below_minimum", item["moq_status"])
        self.assertEqual(0, item["replenish_qty"])

    def test_calc_pool_condition_excludes_zero_qty_asin_merge_rows(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        condition = service._calc_pool_condition()

        self.assertIn("support_replenish_level_sort in (1, 2, 3)", condition)
        self.assertIn("coalesce(moq_status, '') <> 'below_minimum'", condition)
        self.assertIn("asin_merge_flag", condition)
        self.assertIn("replenish_qty", condition)
        self.assertIn("not (", condition)

    def test_asin_merge_display_daily_sales_uses_group_daily_sales(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        period_metrics = service._product_category_metric_sql(30)

        expr = service._display_product_daily_sales_expr(period_metrics, "r")

        self.assertIn("select max(", expr)
        self.assertIn("grp.cur_date = r.cur_date", expr)
        self.assertIn("grp.country_category <=> r.country_category", expr)
        self.assertIn("grp.max_asin <=> r.max_asin", expr)
        self.assertIn("coalesce(r.asin_merge_flag, 0) = 1", expr)

    def test_display_block_reason_uses_final_asin_merge_copy(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        expr = service._display_block_reason_expr("r")

        self.assertIn("%(asin_merge_consolidated_block)s", expr)
        self.assertIn("%(asin_merge_sufficient_block)s", expr)
        self.assertIn("concat(r.seller_name_new, '/', r.seller_sku_adj)", expr)
        self.assertNotIn("同ASIN链接均停售", expr)

    def test_display_asin_merge_reason_uses_final_copy(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        expr = service._display_asin_merge_reason_expr("r")

        self.assertIn("%(asin_merge_consolidated_block)s", expr)
        self.assertIn("%(asin_merge_sufficient_block)s", expr)
        self.assertIn("concat(r.seller_name_new, '/', r.seller_sku_adj)", expr)
        self.assertNotIn("同ASIN链接均停售", expr)

    def test_summary_uses_calc_pool_condition_for_replenishment_pool(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)
        conn = RecordingConnection([{"calc_msku_count": 0}])

        service._summary(conn, "cur_date = %(snapshot_date)s", {"snapshot_date": "2026-07-07"})

        sql = conn.queries[0]
        self.assertIn(service._calc_pool_condition(), sql)
        self.assertNotIn("sum(case when support_replenish_level_sort in (1, 2, 3) then 1 else 0 end) as calc_msku_count", sql)

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

    def test_level_flow_category_filter_uses_sql_parameters(self):
        service = ReplenishmentDataService.__new__(ReplenishmentDataService)

        filters, params = service._level_flow_filters(
            selected_date="2026-06-23",
            prev_date="2026-06-22",
            category="问题产品",
            site="all",
            store="all",
            keyword="",
        )

        self.assertIn("coalesce(cur_category, %(uncategorized)s) = %(category)s", filters)
        self.assertIn("coalesce(prev_category, %(uncategorized)s) = %(category)s", filters)
        self.assertEqual("问题产品", params["category"])
        self.assertEqual("未分类", params["uncategorized"])
        self.assertNotIn("'未分类'", filters)

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
