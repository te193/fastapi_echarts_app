import os
import tempfile
import unittest
from argparse import Namespace
from datetime import date
from pathlib import Path

from etl import replenishment_update


class ReplenishmentUpdateSqlTests(unittest.TestCase):
    def test_local_table_ddl_contains_required_dashboard_fields(self):
        ddl = "\n".join(replenishment_update.DDL_STATEMENTS)

        self.assertIn("dashboard_pur_plan_replenish_data", ddl)
        self.assertIn("pur_plan_prod_perf_salable_days_stat", ddl)
        self.assertIn("dashboard_replenishment_history_daily_sync", ddl)
        self.assertIn("dashboard_replenishment_self_asin_sync", ddl)
        self.assertIn("support_inventory_qty", ddl)
        self.assertIn("inventory_support_days", ddl)
        self.assertIn("support_replenish_level", ddl)
        self.assertIn("support_replenish_level_sort", ddl)
        self.assertIn("pre_daily_avg_sales", ddl)
        self.assertIn("pre_normal_replenish_need_qty", ddl)
        self.assertIn("pre_replenish_trigger_qty", ddl)
        self.assertIn("dashboard_replenishment_listing_basic_sync", ddl)
        self.assertIn("dashboard_replenishment_country_metrics", ddl)
        self.assertIn("listing_price", ddl)
        self.assertIn("primary key (snapshot_date, period_days, country_category, country, seller_name_new, seller_sku_adj)", ddl)
        self.assertIn("max_cg_price", ddl)
        self.assertIn("principal", ddl)

    def test_history_daily_sync_step_loads_fixed_remote_history(self):
        step = replenishment_update.STEPS["history_daily_sync"]

        self.assertIn("dashboard_replenishment_history_daily_sync", step.target_table)
        self.assertIn("etl_dispose_lx_statistics_product_performance_2024", replenishment_update.HISTORY_SOURCE_TABLES[2024])
        self.assertIn("etl_dispose_lx_statistics_product_performance_2025", replenishment_update.HISTORY_SOURCE_TABLES[2025])
        self.assertIn("etl_dispose_lx_statistics_product_performance_2026", replenishment_update.HISTORY_SOURCE_TABLES[2026])
        self.assertIn("{history_source_table}", step.source_select_statement)
        self.assertIn("start_date between %(history_start_date)s and %(history_end_date)s", step.source_select_statement)
        self.assertIn("day_volume", step.target_columns)
        self.assertIn("afn_fulfillable_quantity", step.target_columns)
        self.assertNotIn("history_daily_sync", replenishment_update.DEFAULT_STEP_ORDER)

    def test_self_asin_sync_step_loads_follow_mapping_source(self):
        step = replenishment_update.STEPS["self_asin_sync"]

        self.assertIn("dashboard_replenishment_self_asin_sync", step.target_table)
        self.assertIn("dwd_datasync.lx_sales_mws_listing", step.source_select_statement)
        self.assertIn("opt_db.store_brand_relation", step.source_select_statement)
        self.assertIn("asin", step.target_columns)
        self.assertIn("seller_name_new", step.target_columns)
        self.assertIn("self_asin_sync", replenishment_update.DEFAULT_STEP_ORDER)

    def test_fba_shipment_sync_calculates_receiving_count_from_detail(self):
        sql = replenishment_update.SELECT_FBA_SHIPMENT_SYNC_SQL

        self.assertIn("etl_dispose_lx_fba_shipment", sql)
        self.assertIn("count(*) as receiving_cnt", sql)
        self.assertIn("group by msku, store_name", sql)
        self.assertIn("str_to_date(receiving_time, '%%Y-%%m-%%d %%H:%%i:%%s')", sql)
        self.assertNotIn("ops_rpt_fba_shipment_basic_data", sql)

    def test_listing_basic_sync_prefers_real_eu_store_from_inventory(self):
        sql = replenishment_update.SELECT_LISTING_BASIC_SYNC_SQL

        self.assertIn("dwd_datasync.lx_storage_inventory_details", sql)
        self.assertIn("inv_store.sku = sml.local_sku", sql)
        self.assertIn("inv_store.msku = sml.seller_sku", sql)
        self.assertIn("upper(substring_index(store_name, '-', -1)) = 'DE'", sql)
        self.assertIn("else coalesce(max(inventory_seller_name_copy), concat(max(seller_name_ue), '-DE'))", sql)

    def test_listing_basic_sync_derives_sales_status(self):
        sql = replenishment_update.SELECT_LISTING_BASIC_SYNC_SQL

        self.assertIn("when max(onsale_sites) = 0 then '停售中'", sql)
        self.assertIn("else '在售中'", sql)
        self.assertNotIn("null as sales_status", sql)

    def test_listing_basic_sync_derives_new_old_product_from_brand_year(self):
        sql = replenishment_update.SELECT_LISTING_BASIC_SYNC_SQL

        self.assertIn("max(max_brand_name) regexp '2027|2026|2025'", sql)
        self.assertIn("then '新品'", sql)
        self.assertIn("else '老品'", sql)
        self.assertNotIn("null as new_old_product", sql)

    def test_salable_days_sql_uses_local_daily_sources(self):
        sql = replenishment_update.INSERT_SALABLE_DAYS_SQL

        self.assertIn("dashboard_product_performance_daily", sql)
        self.assertIn("dashboard_inventory_daily_snapshot", sql)
        self.assertIn("candidate_start_date", sql)
        self.assertIn("available_salable_days", sql)
        self.assertNotIn("ops_weekly_rpt_prod_perf_interim", sql)
        self.assertNotIn("ops_weekly_rpt_prod_perf_data_2026", sql)
        self.assertNotIn("etl_dispose_lx_statistics_product_performance_2026", sql)
        self.assertNotIn("yearweek(date_sub(curdate()", sql.lower())

    def test_replenishment_result_sql_uses_daily_pool_and_support_layers(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("dashboard_pur_plan_replenish_data", sql)
        self.assertIn("dashboard_product_performance_daily", sql)
        self.assertIn("dashboard_inventory_daily_snapshot", sql)
        self.assertIn("dashboard_restock_daily_snapshot", sql)
        self.assertIn("pur_plan_prod_perf_salable_days_stat", sql)
        self.assertIn("support_replenish_level", sql)
        self.assertIn("紧急补货", sql)
        self.assertIn("建议补货", sql)
        self.assertIn("计划补货", sql)
        self.assertIn("库存充足", sql)
        self.assertIn("日销为0", sql)
        self.assertIn("create temporary table tmp_pur_plan_support_layer_all", sql)
        self.assertIn("create temporary table tmp_pur_plan_replenish_calc", sql)
        self.assertIn("from tmp_pur_plan_replenish_calc;", sql)
        self.assertNotIn("where support_replenish_level_sort in (1, 2, 3)", sql)
        self.assertNotIn("ops_weekly_rpt_prod_perf_interim", sql)
        self.assertNotIn("ops_weekly_rpt_prod_perf_data_2026", sql)

    def test_replenishment_result_sql_calculates_cost_from_synced_original_sources(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("dashboard_replenishment_listing_basic_sync", sql)
        self.assertIn("l.max_cg_price", sql)
        self.assertIn("l.max_cg_transport_costs", sql)
        self.assertIn("l.max_cg_box_pcs", sql)
        self.assertIn("* (max_cg_price + max_cg_transport_costs)", sql)
        self.assertNotIn("0 as max_cg_price", sql)
        self.assertNotIn("0 as max_cg_transport_costs", sql)
        self.assertNotIn("0 as replenish_cost", sql)

    def test_replenishment_result_sql_keeps_original_replenishment_calculation_rules(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("as sales_change_rate_adj", sql)
        self.assertIn("else 1 + sales_change_rate_adj", sql)
        self.assertIn("as sales_adj_factor", sql)
        self.assertIn("hist_90d_instock_daily_sales", sql)
        self.assertIn("hist_90d_instock_daily_sales * 120", sql)
        self.assertIn("as history_recovery_need_qty", sql)
        self.assertIn("as history_recovery_flag", sql)
        self.assertIn("l.max_cg_box_pcs", sql)
        self.assertIn("when coalesce(max_cg_box_pcs, 0) > 0 then max_cg_box_pcs", sql)
        self.assertIn("and (max_cg_box_pcs = 0 or max_cg_box_pcs is null)", sql)
        self.assertIn("greatest(round(normal_replenish_need_qty * sales_adj_factor, 0), 50)", sql)
        self.assertIn("normal_replenish_need_qty * sales_adj_factor /", sql)
        self.assertNotIn("50 as pre_replenish_trigger_qty", sql)
        self.assertNotIn("1 as sales_adj_factor", sql)
        self.assertNotIn("0 as history_recovery_flag", sql)

    def test_replenishment_result_sql_uses_original_daily_sales_smoothing_rules(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("when coalesce(ks.r_30d_salable_days, 0) >= 7", sql)
        self.assertIn("least(", sql)
        self.assertIn("ks.r_7d_salable_days / (ks.r_7d_salable_days + 3)", sql)
        self.assertIn("ks.r_14d_salable_days / (ks.r_14d_salable_days + 7)", sql)
        self.assertIn("coalesce(m.sales_30, 0) / greatest(coalesce(ks.r_30d_salable_days, 0), 15)", sql)
        self.assertIn("max_brand_name like '%%2025%%'", sql)
        self.assertIn("max_brand_name like '%%2026%%'", sql)
        self.assertIn("adjusted_daily_sales_3d * 0.5 + adjusted_daily_sales_7d * 0.5", sql)
        self.assertIn("adjusted_daily_sales_7d * 0.6 + adjusted_daily_sales_14d * 0.2 + adjusted_daily_sales_30d * 0.2", sql)

    def test_replenishment_result_sql_classifies_new_product_by_brand_year_and_receiving_count(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("max_brand_name like '%%2025%%' and (receiving_cnt <= 1 or receiving_cnt is null)", sql)
        self.assertIn("then '2025新品'", sql)
        self.assertIn("max_brand_name like '%%2026%%' and (receiving_cnt <= 1 or receiving_cnt is null)", sql)
        self.assertIn("then '2026新品'", sql)
        self.assertNotIn("'老品' as new_old_prod_jg", sql)

    def test_replenishment_result_sql_restores_follow_sales_logic(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("tmp_prod_perf_sku_asin_metrics", sql)
        self.assertIn("tmp_prod_perf_follow_origin", sql)
        self.assertIn("dashboard_replenishment_self_asin_sync", sql)
        self.assertIn("origin_sales_30", sql)
        self.assertIn("when coalesce(fo.fllow_flag, 1) = 1 then coalesce(m.sales_30, 0)", sql)
        self.assertIn("else coalesce(m.sales_30, 0) + coalesce(fo.origin_sales_30, 0)", sql)
        self.assertIn("coalesce(fo.fllow_flag, 1) as fllow_flag", sql)
        self.assertNotIn("1 as fllow_flag", sql)

    def test_follow_sales_only_affects_replenishment_qty_not_support_layer(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("left join tmp_prod_perf_sku_metrics m", sql)
        self.assertIn("left join tmp_prod_perf_sku_follow_metrics fm", sql)
        self.assertIn("coalesce(m.sales_30, 0) as sales_30", sql)
        self.assertIn("coalesce(fm.sales_30, m.sales_30, 0) as final_sales_30", sql)
        self.assertIn("as final_adjusted_daily_sales_30d", sql)
        self.assertIn("end as daily_avg_sales", sql)
        self.assertIn("pre_replenish_comp_months * 30 * coalesce(daily_avg_sales, 0)", sql)
        self.assertIn("base.support_inventory_qty / base.pre_daily_avg_sales", sql)
        self.assertNotIn("left join tmp_prod_perf_sku_follow_metrics m", sql)

    def test_replenishment_need_qty_does_not_double_subtract_purchase_plan_support(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("coalesce(r.sc_quantity_purchase_plan, 0) as sc_quantity_purchase_plan", sql)
        self.assertNotIn("- sc_quantity_purchase_plan as normal_replenish_need_qty", sql)
        self.assertNotIn("- sc_quantity_purchase_plan as pre_normal_replenish_need_qty", sql)
        self.assertNotIn("- sc_quantity_purchase_plan as history_recovery_need_qty", sql)

    def test_replenishment_qty_only_uses_support_candidate_layers(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("when support_replenish_level_sort in (1, 2, 3) and coalesce(history_recovery_flag, 0) = 1", sql)
        self.assertNotIn("when coalesce(history_recovery_flag, 0) = 1 then max_cg_box_pcs", sql)
        self.assertNotIn("when coalesce(history_recovery_flag, 0) = 1 then 1", sql)

    def test_country_metrics_sql_is_display_only_by_period(self):
        sql = replenishment_update.BUILD_COUNTRY_METRICS_SQL

        self.assertIn("dashboard_replenishment_country_metrics", sql)
        self.assertIn("dashboard_product_performance_daily", sql)
        self.assertIn("dashboard_pur_plan_replenish_data", sql)
        self.assertIn("period_days", sql)
        self.assertIn("period_days in (7, 14, 30, 90, 180)", sql)
        self.assertIn("group_concat(distinct nullif(p.local_sku, '')", sql)
        self.assertIn("null as listing_price", sql)
        self.assertIn("avg(case when p.dt_date = %(biz_date)s then nullif(p.ranking, 0) end) as avg_ranking", sql)
        self.assertIn("group by", sql.lower())
        self.assertIn("p.country_category", sql)
        self.assertIn("p.country", sql)
        self.assertIn("p.seller_name_new", sql)
        self.assertIn("p.seller_sku_adj", sql)
        self.assertNotIn("group by\n    p.country_category,\n    p.country,\n    p.seller_name_new,\n    p.seller_sku_adj,\n    coalesce(nullif(p.local_sku", sql)
        self.assertIn("country_metrics", replenishment_update.DEFAULT_STEP_ORDER)
        self.assertIn("dashboard_listing_price_daily_snapshot", replenishment_update.INSERT_COUNTRY_LISTING_PRICE_SQL)
        self.assertIn("where snapshot_date = %(biz_date)s", replenishment_update.INSERT_COUNTRY_LISTING_PRICE_SQL)
        self.assertIn("tmp_replenishment_country_listing_price", replenishment_update.UPDATE_COUNTRY_METRICS_LISTING_PRICE_SQL)
        self.assertIn("set m.listing_price = lp.price", replenishment_update.UPDATE_COUNTRY_METRICS_LISTING_PRICE_SQL)

    def test_replenishment_category_uses_30d_margin_and_salable_day_daily_sales(self):
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL

        self.assertIn("coalesce(m.sales_30, 0) / ks.r_30d_salable_days", sql)
        self.assertIn("adjusted_daily_sales_30d >= 5 and pprofit_ratio_30 >= 0.15", sql)
        self.assertIn("adjusted_daily_sales_30d >= 1 and adjusted_daily_sales_30d < 5 and pprofit_ratio_30 >= 0.25", sql)
        self.assertIn("'明星产品'", sql)
        self.assertIn("'潜力产品'", sql)
        self.assertIn("'瘦狗产品'", sql)
        self.assertIn("'问题产品'", sql)

    def test_replenishment_result_stores_90d_and_180d_category_metrics(self):
        ddl = "\n".join(replenishment_update.DDL_STATEMENTS)
        sql = replenishment_update.REPLENISHMENT_RESULT_SQL
        salable_sql = replenishment_update.INSERT_SALABLE_DAYS_SQL

        self.assertIn("r_180d_salable_days", ddl)
        self.assertIn("sales_180d", ddl)
        self.assertIn("pprofit_ratio_90d", ddl)
        self.assertIn("pprofit_ratio_180d", ddl)
        self.assertIn("interval 179 day", salable_sql)
        self.assertIn("sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 179 day) then coalesce(p.sales_qty, 0) else 0 end) as sales_180", sql)
        self.assertIn("sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 89 day) then coalesce(p.sales_amount, 0) else 0 end) as amount_90", sql)
        self.assertIn("m.pprofit_180 / nullif(m.amount_180, 0) as pprofit_ratio_180", sql)

    def test_build_params_defaults_and_candidate_window(self):
        args = Namespace(biz_date="2026-06-17", snapshot_date="2026-06-18", candidate_days=1)

        params = replenishment_update.build_params(args)

        self.assertEqual(date(2026, 6, 17), params["biz_date"])
        self.assertEqual(date(2026, 6, 18), params["snapshot_date"])
        self.assertEqual(date(2025, 12, 20), params["product_start_date"])
        self.assertEqual(date(2026, 6, 17), params["candidate_start_date"])
        self.assertEqual(1, params["candidate_days"])
        self.assertEqual(date(2024, 10, 3), params["history_start_date"])
        self.assertEqual(date(2026, 3, 31), params["history_end_date"])

    def test_history_sync_runs_by_year_source_table(self):
        ranges = list(
            replenishment_update.iter_history_source_ranges(
                date(2024, 10, 3),
                date(2026, 3, 31),
            )
        )

        self.assertEqual(
            [
                (
                    "etl_datasync.etl_dispose_lx_statistics_product_performance_2024",
                    date(2024, 10, 3),
                    date(2024, 12, 31),
                ),
                (
                    "etl_datasync.etl_dispose_lx_statistics_product_performance_2025",
                    date(2025, 1, 1),
                    date(2025, 12, 31),
                ),
                (
                    "etl_datasync.etl_dispose_lx_statistics_product_performance_2026",
                    date(2026, 1, 1),
                    date(2026, 3, 31),
                ),
            ],
            ranges,
        )

    def test_render_replenishment_sql_maps_pur_plan_tables_to_target_schema(self):
        schemas = replenishment_update.SchemaConfig(
            target_schema="etl_datasync_test",
            etl_source_schema="etl_datasync",
            dwd_source_schema="dwd_datasync",
            pricing_source_schema="temporary_dwd",
        )

        rendered = replenishment_update.render_replenishment_sql(
            "create table if not exists etl_datasync.pur_plan_prod_perf_salable_days_stat (id int);",
            schemas,
        )

        self.assertIn("etl_datasync_test.pur_plan_prod_perf_salable_days_stat", rendered)
        self.assertNotIn("etl_datasync.pur_plan_prod_perf_salable_days_stat", rendered)

    def test_apply_database_ini_env_skips_placeholder_source_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "database.ini"
            config_path.write_text(
                "\n".join(
                    [
                        "[target]",
                        "host = 192.168.112.235",
                        "port = 3306",
                        "user = dashboard_user",
                        "password = secret",
                        "database = etl_datasync_test",
                        "target_schema = ",
                        "",
                        "[source]",
                        "host = REMOTE_DB_HOST",
                        "port = 3306",
                        "user = REMOTE_DB_USER",
                        "password = REMOTE_DB_PASSWORD",
                        "database = REMOTE_DB_NAME",
                    ]
                ),
                encoding="utf-8",
            )
            old_env = dict(os.environ)
            try:
                for name in (
                    "DASHBOARD_DB_HOST",
                    "DASHBOARD_DB_PORT",
                    "DASHBOARD_DB_USER",
                    "DASHBOARD_DB_PASSWORD",
                    "DASHBOARD_DB_NAME",
                    "DASHBOARD_TARGET_SCHEMA",
                    "DASHBOARD_SOURCE_DB_HOST",
                    "DASHBOARD_SOURCE_DB_USER",
                    "DASHBOARD_SOURCE_DB_PASSWORD",
                    "OPT_LYT_DB_HOST",
                    "OPT_LYT_DB_PORT",
                    "OPT_LYT_DB_USER",
                    "OPT_LYT_DB_PASSWORD",
                ):
                    os.environ.pop(name, None)

                replenishment_update.apply_database_ini_env(config_path)

                self.assertEqual("192.168.112.235", os.environ["DASHBOARD_DB_HOST"])
                self.assertEqual("3306", os.environ["DASHBOARD_DB_PORT"])
                self.assertEqual("dashboard_user", os.environ["DASHBOARD_DB_USER"])
                self.assertEqual("secret", os.environ["DASHBOARD_DB_PASSWORD"])
                self.assertEqual("etl_datasync_test", os.environ["DASHBOARD_DB_NAME"])
                self.assertEqual("etl_datasync_test", os.environ["DASHBOARD_TARGET_SCHEMA"])
                self.assertNotIn("DASHBOARD_SOURCE_DB_HOST", os.environ)
                self.assertNotIn("DASHBOARD_SOURCE_DB_USER", os.environ)
            finally:
                os.environ.clear()
                os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
