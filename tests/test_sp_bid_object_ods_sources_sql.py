from pathlib import Path


SQL_PATH = Path(__file__).resolve().parents[1] / "sqlcode" / "SP竞价对象DWS宽表_每日快照刷新.sql"
DDL_PATH = Path(__file__).resolve().parents[1] / "sqlcode" / "SP竞价对象DWS宽表_建表.sql"

ATTRIBUTION_FIELDS = tuple(
    f"{prefix}_{window}d"
    for prefix in (
        "attributed_orders",
        "attributed_sales",
        "attributed_units",
        "same_sku_attributed_orders",
        "same_sku_attributed_sales",
        "same_sku_attributed_units",
    )
    for window in (1, 7, 14, 30)
)


def test_bid_snapshot_uses_ods_for_every_advertising_upstream():
    sql = SQL_PATH.read_text(encoding="utf-8").lower()

    assert "dwd_datasync.lx_advertising_" not in sql
    assert "d.relate_id" not in sql
    for source in (
        "ods_datasync.lx_advertising_account_list",
        "ods_datasync.lx_advertising_sp_campaigns",
        "ods_datasync.lx_advertising_sp_ad_groups",
        "ods_datasync.lx_advertising_sp_keywords",
        "ods_datasync.lx_advertising_sp_product_ads",
        "ods_datasync.lx_advertising_sp_keyword_reports",
        "ods_datasync.lx_advertising_sp_ad_group_reports",
        "ods_datasync.lx_advertising_sp_product_ad_reports",
    ):
        assert source in sql


def test_bid_snapshot_bounded_types_for_indexed_temp_table_join_keys():
    """CTAS must not infer TEXT for columns subsequently used in temporary-table indexes."""
    sql = SQL_PATH.read_text(encoding="utf-8").lower()

    assert sql.count("as char(255)) as base_store_name") >= 4
    assert sql.count("as char(20)) as country_code") >= 4
    assert sql.count("as char(100)) as msku_key") >= 4


def test_listing_lookup_includes_the_snapshot_next_day_sync():
    """Listing is synchronized after midnight for the performance snapshot date."""
    sql = SQL_PATH.read_text(encoding="utf-8").lower()

    assert "l.create_time < date_add(v_snapshot_date, interval 2 day)" in sql


def test_budget_lookup_includes_the_snapshot_next_day_sync():
    """Budget DWS is published on the day after the performance snapshot date."""
    sql = SQL_PATH.read_text(encoding="utf-8").lower()

    assert "b2.biz_date <= date_add(v_snapshot_date, interval 1 day)" in sql


def test_attribution_windows_are_defined_aggregated_and_inserted_for_both_grains():
    """Keyword and auto-ad-group rows must carry every approved attribution field."""
    refresh_sql = SQL_PATH.read_text(encoding="utf-8").lower()
    ddl_sql = DDL_PATH.read_text(encoding="utf-8").lower()

    for field in ATTRIBUTION_FIELDS:
        assert field in ddl_sql
        assert field in refresh_sql

    assert refresh_sql.count("sum(coalesce(o.orders_1d, 0)) as attributed_orders_1d") == 2
    assert refresh_sql.count("sum(coalesce(o.same_units_30d, 0)) as same_sku_attributed_units_30d") == 2


def test_ddl_migrates_existing_table_with_compatible_attribution_columns():
    ddl_sql = DDL_PATH.read_text(encoding="utf-8").lower()

    assert "alter table dws_datasync.dws_sp_bid_object_snapshot_daily" in ddl_sql
    assert "add column if not exists" not in ddl_sql
    for field in ATTRIBUTION_FIELDS:
        assert f"add column {field}" in ddl_sql
