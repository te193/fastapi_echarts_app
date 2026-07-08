from etl import replenishment_test_db


def test_test_database_defaults_to_dedicated_replenishment_schema():
    assert replenishment_test_db.TEST_SCHEMA == "etl_datasync_replenishment_test"
    assert replenishment_test_db.PRODUCTION_SCHEMA == "etl_datasync_test"


def test_copy_plan_limits_replenishment_tables_to_recent_windows():
    plan = {item.table: item for item in replenishment_test_db.COPY_TABLES}

    assert plan["dashboard_product_performance_daily"].where_sql == "dt_date >= %(product_start_date)s"
    assert plan["dashboard_inventory_daily_snapshot"].where_sql == "snapshot_date = %(snapshot_date)s"
    assert plan["dashboard_restock_daily_snapshot"].where_sql == "snapshot_date = %(snapshot_date)s"
    assert plan["dashboard_limit_price_daily_snapshot"].where_sql == "snapshot_date in (%(snapshot_date)s, %(biz_date)s, %(previous_snapshot_date)s)"
    assert plan["dashboard_pur_plan_replenish_data"].where_sql == "cur_date in (%(snapshot_date)s, %(previous_snapshot_date)s)"
    assert plan["dashboard_replenishment_country_metrics"].where_sql == "snapshot_date in (%(snapshot_date)s, %(previous_snapshot_date)s)"
