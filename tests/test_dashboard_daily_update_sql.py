import unittest
from argparse import Namespace
from datetime import date

from etl.dashboard_daily_update import (
    AD_BUDGET_COLUMNS,
    CREATE_AD_BUDGET_SNAPSHOT_SQL,
    CREATE_SCHEMA_SQL,
    DEFAULT_STEP_ORDER,
    DELETE_AD_BUDGET_SNAPSHOT_SQL,
    INSERT_ALERT_COMPARISON_SNAPSHOT_SQL,
    INSERT_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL,
    INSERT_INVENTORY_SQL,
    INSERT_LIMIT_PRICE_SQL,
    INSERT_LISTING_PRICE_SQL,
    INSERT_PERIOD_SNAPSHOT_SQL,
    INSERT_PRODUCT_DAILY_SQL,
    INSERT_RESTOCK_SQL,
    SELECT_AD_BUDGET_SNAPSHOT_SQL,
    STEPS,
    SchemaConfig,
    SourceLoadStep,
    build_params,
    execute_source_load_step,
    render_sql,
    validate_product_performance_result,
)


class DashboardDailyUpdateSqlTests(unittest.TestCase):
    def test_create_schema_sql_uses_canonical_local_target_schema(self):
        self.assertIn("create schema if not exists etl_datasync_test", CREATE_SCHEMA_SQL)

    def test_render_sql_maps_canonical_local_target_schema(self):
        schemas = SchemaConfig(
            target_schema="etl_datasync_replenishment_test",
            etl_source_schema="etl_datasync",
            dwd_source_schema="dwd_datasync",
            pricing_source_schema="temporary_dwd",
        )

        rendered = render_sql(
            "select * from etl_datasync_test.dashboard_inventory_daily_snapshot",
            schemas,
        )

        self.assertEqual(
            "select * from etl_datasync_replenishment_test.dashboard_inventory_daily_snapshot",
            rendered,
        )

        rendered_create = render_sql(CREATE_SCHEMA_SQL, schemas)
        self.assertEqual(
            "create schema if not exists etl_datasync_replenishment_test default character set utf8mb4;",
            rendered_create,
        )

    def test_product_daily_preserves_profit_for_zero_volume_rows(self):
        self.assertIn("sum(predict_gross_profit) as order_gross_profit", INSERT_PRODUCT_DAILY_SQL)
        self.assertNotIn(
            "sum(case when volume = 0 then 0 else predict_gross_profit end) as order_gross_profit",
            INSERT_PRODUCT_DAILY_SQL,
        )

    def test_product_daily_sql_contains_complete_country_rules(self):
        self.assertIn("when country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'", INSERT_PRODUCT_DAILY_SQL)
        self.assertIn("when country = '英国' then '英国站'", INSERT_PRODUCT_DAILY_SQL)
        self.assertIn("when country = '德国' then coalesce(amount, 0) / 1.19", INSERT_PRODUCT_DAILY_SQL)
        self.assertIn("when country = '土耳其' then coalesce(amount, 0) / 1.20", INSERT_PRODUCT_DAILY_SQL)

    def test_listing_price_sql_contains_complete_marketplace_rules(self):
        self.assertIn("when marketplace in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'", INSERT_LISTING_PRICE_SQL)
        self.assertIn("when marketplace = '英国' then '英国站'", INSERT_LISTING_PRICE_SQL)
        self.assertIn("when marketplace in ('德国', '法国', '荷兰', '比利时', '西班牙', '意大利', '爱尔兰') then '欧元'", INSERT_LISTING_PRICE_SQL)
        self.assertIn("when marketplace = '墨西哥' then '墨西哥比索'", INSERT_LISTING_PRICE_SQL)

    def test_limit_price_sql_uses_pricing_schedule_rows(self):
        self.assertIn("from temporary_dwd.`在库节点_输出定价表`", INSERT_LIMIT_PRICE_SQL)
        self.assertIn("`35毛利润价格` as margin_price_35", INSERT_LIMIT_PRICE_SQL)
        self.assertIn("`35毛利润含广告定价` as margin_price_35_adj", INSERT_LIMIT_PRICE_SQL)
        self.assertIn(
            "round(max(margin_price_35), 2) as tax_inclusive_price,\n"
            "    round(max(margin_price_35), 2) as tax_inclusive_price_noad,\n"
            "    round(max(margin_price_35_adj), 2) as tax_inclusive_price_adj,\n"
            "    round(max(margin_price_35), 2) as margin_price_35,\n"
            "    round(max(margin_price_30), 2) as margin_price_30,\n"
            "    round(max(margin_price_25), 2) as margin_price_25,\n"
            "    round(max(margin_price_20), 2) as margin_price_20,\n"
            "    round(max(margin_price_15), 2) as margin_price_15,\n"
            "    round(max(margin_price_10), 2) as margin_price_10,",
            INSERT_LIMIT_PRICE_SQL,
        )

    def test_snapshot_label_sql_uses_readable_chinese_labels(self):
        combined_sql = "\n".join(
            [INSERT_ALERT_COMPARISON_SNAPSHOT_SQL, INSERT_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL, INSERT_PERIOD_SNAPSHOT_SQL]
        )
        self.assertIn("'日销 <1'", combined_sql)
        self.assertIn("'毛利率 >35%%'", combined_sql)
        self.assertIn("'销量下滑'", combined_sql)
        for mojibake in ["鏃ラ攢", "姣涘埄", "浣庢瘺", "鎺掑悕", "搴撳瓨"]:
            self.assertNotIn(mojibake, combined_sql)

    def test_source_snapshot_sql_uses_range_filters_without_wrapping_indexed_columns(self):
        self.assertIn("r.create_time >= %(snapshot_date)s", INSERT_RESTOCK_SQL)
        self.assertIn("r.create_time < %(next_snapshot_date)s", INSERT_RESTOCK_SQL)
        self.assertNotIn("where date(r.create_time) = %(snapshot_date)s", INSERT_RESTOCK_SQL)

        self.assertIn("create_time >= %(snapshot_date)s", INSERT_INVENTORY_SQL)
        self.assertIn("create_time < %(next_snapshot_date)s", INSERT_INVENTORY_SQL)
        self.assertNotIn("where date(create_time) = %(snapshot_date)s", INSERT_INVENTORY_SQL)

        self.assertIn("create_time >= %(snapshot_date)s", INSERT_LISTING_PRICE_SQL)
        self.assertIn("create_time < %(next_snapshot_date)s", INSERT_LISTING_PRICE_SQL)
        self.assertNotIn("where date(create_time) = %(snapshot_date)s", INSERT_LISTING_PRICE_SQL)

    def test_build_params_includes_exclusive_next_day_bounds(self):
        args = Namespace(
            biz_date="2026-06-09",
            snapshot_date="2026-06-10",
            period_end=None,
            period_start=None,
            period_days=90,
            product_refresh_days=50,
            product_full_load=False,
        )

        params = build_params(args)

        self.assertEqual(date(2026, 6, 10), params["snapshot_date"])
        self.assertEqual(date(2026, 6, 11), params["next_snapshot_date"])
        self.assertEqual(date(2026, 6, 9), params["product_end_date"])
        self.assertEqual(date(2026, 6, 10), params["next_product_end_date"])
        self.assertEqual(date(2026, 5, 11), params["budget_start_date"])

    def test_ad_budget_snapshot_is_registered_as_history_preserving_source_load(self):
        self.assertIn("ad_budget_snapshot", DEFAULT_STEP_ORDER)
        step = STEPS["ad_budget_snapshot"]
        self.assertIsInstance(step, SourceLoadStep)
        self.assertEqual("etl_datasync.dashboard_ad_budget_snapshot", step.target_table)
        self.assertEqual(40, len(AD_BUDGET_COLUMNS))
        self.assertIn("primary key (biz_date, country_category, country, seller_name_new, seller_sku_adj)", CREATE_AD_BUDGET_SNAPSHOT_SQL)
        self.assertIn("where biz_date >= %(budget_start_date)s", SELECT_AD_BUDGET_SNAPSHOT_SQL)
        self.assertIn("where biz_date >= %(budget_start_date)s", DELETE_AD_BUDGET_SNAPSHOT_SQL)

    def test_source_load_reconnects_and_retries_after_source_timeout(self):
        step = SourceLoadStep(
            "retry_test",
            "delete from etl_datasync.retry_target where snapshot_date = %(snapshot_date)s;",
            "select %(snapshot_date)s as snapshot_date, 'sku1' as sku;",
            "etl_datasync.retry_target",
            ("snapshot_date", "sku"),
        )
        params = {
            "biz_date": date(2026, 6, 9),
            "snapshot_date": date(2026, 6, 10),
            "period_start": date(2026, 3, 12),
            "period_end": date(2026, 6, 9),
        }
        schemas = SchemaConfig(
            target_schema="etl_datasync",
            etl_source_schema="etl_datasync",
            dwd_source_schema="dwd_datasync",
            pricing_source_schema="temporary_dwd",
        )
        target_conn = FakeTargetConnection()
        source_conn = FakeSourceConnection()

        execute_source_load_step(target_conn, source_conn, schemas, step, params, batch_size=1000)

        self.assertEqual(2, source_conn.execute_attempts)
        self.assertEqual([True], source_conn.ping_reconnect_values)
        self.assertEqual(1, target_conn.rollback_count)
        self.assertEqual(2, target_conn.commit_count)
        self.assertEqual([[{"snapshot_date": date(2026, 6, 10), "sku": "sku1"}]], target_conn.inserted_batches)

    def test_product_performance_validation_rejects_empty_business_date(self):
        conn = ResultCountConnection(0)

        with self.assertRaisesRegex(RuntimeError, "2026-06-26.*0 rows"):
            validate_product_performance_result(
                conn,
                SchemaConfig(
                    target_schema="etl_datasync_test",
                    etl_source_schema="etl_datasync",
                    dwd_source_schema="dwd_datasync",
                    pricing_source_schema="temporary_dwd",
                ),
                {"biz_date": date(2026, 6, 26)},
            )

    def test_ad_budget_empty_source_rolls_back_instead_of_deleting_last_snapshot(self):
        target_conn = FakeTargetConnection()

        with self.assertRaisesRegex(RuntimeError, "ad_budget_snapshot.*0 rows"):
            execute_source_load_step(
                target_conn,
                EmptySourceConnection(),
                SchemaConfig(
                    target_schema="etl_datasync",
                    etl_source_schema="etl_datasync",
                    dwd_source_schema="dwd_datasync",
                    pricing_source_schema="temporary_dwd",
                ),
                STEPS["ad_budget_snapshot"],
                {
                    "biz_date": date(2026, 6, 26),
                    "snapshot_date": date(2026, 6, 27),
                    "period_start": date(2026, 3, 29),
                    "period_end": date(2026, 6, 26),
                    "budget_start_date": date(2026, 5, 28),
                },
                batch_size=1000,
            )

        self.assertGreaterEqual(target_conn.rollback_count, 1)
        self.assertEqual([], target_conn.inserted_batches)


class FakeSourceCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []
        self.fetched = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.conn.execute_attempts += 1
        if self.conn.execute_attempts == 1:
            raise TimeoutError("timed out")
        self.rows = [{"snapshot_date": params["snapshot_date"], "sku": "sku1"}]

    def fetchmany(self, batch_size):
        if self.fetched:
            return []
        self.fetched = True
        return self.rows


class FakeSourceConnection:
    def __init__(self):
        self.execute_attempts = 0
        self.ping_reconnect_values = []

    def cursor(self):
        return FakeSourceCursor(self)

    def ping(self, reconnect=False):
        self.ping_reconnect_values.append(reconnect)


class EmptySourceCursor(FakeSourceCursor):
    def execute(self, sql, params):
        self.rows = []


class EmptySourceConnection(FakeSourceConnection):
    def cursor(self):
        return EmptySourceCursor(self)


class FakeTargetCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        return 1

    def executemany(self, sql, rows):
        self.conn.inserted_batches.append(list(rows))
        return len(rows)


class FakeTargetConnection:
    def __init__(self):
        self.executed = []
        self.inserted_batches = []
        self.rollback_count = 0
        self.commit_count = 0

    def cursor(self):
        return FakeTargetCursor(self)

    def rollback(self):
        self.rollback_count += 1

    def commit(self):
        self.commit_count += 1


class ResultCountCursor:
    def __init__(self, row_count):
        self.row_count = row_count

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        return 1

    def fetchone(self):
        return {"row_count": self.row_count}


class ResultCountConnection:
    def __init__(self, row_count):
        self.row_count = row_count

    def cursor(self):
        return ResultCountCursor(self.row_count)


if __name__ == "__main__":
    unittest.main()
