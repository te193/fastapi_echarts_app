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


def test_baseline_plan_preserves_outputs_before_test_recalculation():
    plan = {item.table: item for item in replenishment_test_db.BASELINE_TABLES}

    assert plan["dashboard_pur_plan_replenish_data"].backup_table == "baseline_dashboard_pur_plan_replenish_data"
    assert plan["dashboard_pur_plan_replenish_data"].where_sql == "cur_date in (%(snapshot_date)s, %(previous_snapshot_date)s)"
    assert plan["dashboard_replenishment_country_metrics"].backup_table == "baseline_dashboard_replenishment_country_metrics"


def test_verification_checks_moq_warning_rows_and_equal_moq_release():
    queries = replenishment_test_db.build_verification_queries(
        "etl_datasync_test",
        "etl_datasync_replenishment_test",
    )

    assert "moq_status_summary" in queries
    assert "moq_gate_zero_check" in queries
    assert "moq_equal_release_check" in queries
    assert "executable_replenish_qty" in queries["test_summary"]
    assert "moq_status = 'below_minimum'" in queries["moq_gate_zero_check"]
    assert "calculated_replenish_qty = supplier_moq" in queries["moq_equal_release_check"]


def test_promotion_plan_moves_verified_outputs_by_snapshot_in_one_direction():
    plan = {item.table: item for item in replenishment_test_db.PROMOTION_TABLES}

    assert plan["dashboard_replenishment_supplier_moq_sync"].date_column == "snapshot_date"
    assert plan["dashboard_pur_plan_replenish_data"].date_column == "cur_date"
    assert "dashboard_replenishment_country_metrics" not in plan
    assert "dashboard_replenishment_tracking_snapshot" not in plan
    assert "dashboard_replenishment_tracking_detail" not in plan


def test_promotion_sql_deletes_only_selected_snapshot_and_copies_common_columns():
    item = replenishment_test_db.PromotionTable("example_table", "snapshot_date")
    delete_sql, insert_sql = replenishment_test_db.build_promotion_sql(
        "prod_schema",
        "test_schema",
        item,
        ("snapshot_date", "sku", "moq_status"),
    )

    assert "delete from `prod_schema`.`example_table` where `snapshot_date` = %(snapshot_date)s" in delete_sql
    assert "insert into `prod_schema`.`example_table` (`snapshot_date`, `sku`, `moq_status`)" in insert_sql
    assert "from `test_schema`.`example_table`" in insert_sql
    assert "where `snapshot_date` = %(snapshot_date)s" in insert_sql


def test_result_promotion_updates_only_moq_fields_and_preserves_legacy_calculation():
    sql = replenishment_test_db.build_result_moq_update_sql(
        "prod_schema",
    )

    assert "`prod_schema`.`dashboard_replenishment_supplier_moq_sync` m" in sql
    assert "r.supplier_moq = m.supplier_moq" in sql
    assert "r.history_recovery_flag" in sql
    assert "r.max_cg_box_pcs" in sql
    assert "r.executable_replenish_qty" in sql
    assert "r.calculated_replenish_box_qty" in sql
    assert "r.calculated_replenish_cost" in sql
    assert "r.moq_shortfall_qty" in sql
    assert "test_schema" not in sql
    assert "r.replenish_qty =" not in sql
    assert "r.replenish_cost =" not in sql


def test_result_promotion_history_recovery_respects_existing_replenishment_blocks():
    sql = replenishment_test_db.build_result_moq_update_sql("prod_schema")

    assert sql.count("coalesce(r.replenish_block_reason, '') <> '被跟卖点不补货'") >= 3
    assert sql.count(
        "not (coalesce(r.asin_merge_flag, 0) = 1 "
        "and coalesce(r.replenish_qty, 0) = 0)"
    ) >= 3
