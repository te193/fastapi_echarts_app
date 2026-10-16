"""Exercise the actual MySQL projection and V47 latest-snapshot aggregation."""
from datetime import datetime
import os

import pytest

from test_label_local_store_mysql import local_store
from etl.label_fba_source import fba_select_sql

pytestmark = pytest.mark.skipif(
    os.getenv("LABEL_LOCAL_MYSQL_TEST") != "1", reason="isolated MySQL opt-in"
)


@pytest.mark.parametrize("earlier,latest", [(101, 0), (0, 7), (6, 2)])
def test_latest_day_sums_countries_collected_at_different_seconds(
    local_store, earlier, latest
):
    conn, schema = local_store
    raw = f"`{schema}`.raw_fba"
    with conn.cursor() as q:
        q.execute(f"create table {raw} (create_time datetime(6),"
                  "afn_fulfillable_quantity int,stock_up_num int)")
        q.executemany(f"insert into {raw} values (%s,%s,%s)", [
            ("2026-10-13 23:59:59", 999, 999),
            ("2026-10-14 05:04:42", earlier, 126),
            ("2026-10-14 05:04:51.123456", latest, 0),
            ("2026-10-15 00:00:01", 888, 888),
            (None, 777, 777),
        ])
        projection = fba_select_sql([
            "create_time", "afn_fulfillable_quantity", "stock_up_num"
        ]).replace("`dwd_datasync`.`lx_storage_fba_warehouse_detail`", raw)
        q.execute(f"with projected as ({projection}) "
                  "select max(create_time) as snapshot_time,"
                  "sum(afn_fulfillable_quantity) as available,"
                  "sum(stock_up_num) as in_transit from projected "
                  "where create_time=(select max(create_time) from projected "
                  "where create_time<'2026-10-15')")
        result = q.fetchone()
        assert result == {"snapshot_time": datetime(2026, 10, 14),
                          "available": earlier + latest, "in_transit": 126}
        q.execute(f"select max(create_time) as latest from {raw}")
        assert q.fetchone()["latest"] == datetime(2026, 10, 15, 0, 0, 1)


def test_inventory_guard_checks_fallback_history_and_latest_clearance_day(local_store):
    from datetime import date
    from etl.label_local_contracts import validate_inventory_dates

    conn, schema = local_store
    with conn.cursor() as q:
        for name in ("fba", "raw_fba", "restock"):
            q.execute(f"create table `{schema}`.dashboard_label_source_{name} "
                      "(create_time datetime(6),key dt(create_time))")
        q.execute(f"insert into `{schema}`.dashboard_label_source_fba values "
                  "('2026-10-13 05:04:42'),('2026-10-14 00:00:00')")
        q.execute(f"insert into `{schema}`.dashboard_label_source_restock values "
                  "('2026-10-14 05:04:42')")
        q.execute(f"insert into `{schema}`.dashboard_label_source_raw_fba values "
                  "('2026-10-15 05:04:42')")
    # A SKU can fall back to Oct 13 even while Oct 14 exists for other SKUs.
    with pytest.raises(RuntimeError, match="daily normalization"):
        validate_inventory_dates(conn, schema, [date(2026, 10, 14)])
    with conn.cursor() as q:
        q.execute(f"update `{schema}`.dashboard_label_source_fba "
                  "set create_time=date(create_time)")
    with pytest.raises(RuntimeError, match="clearance.*2026-10-15"):
        validate_inventory_dates(conn, schema, [date(2026, 10, 14)])
    with conn.cursor() as q:
        q.execute(f"insert into `{schema}`.dashboard_label_source_fba values "
                  "('2026-10-15'),(null)")
    validate_inventory_dates(conn, schema, [date(2026, 10, 14)])
    with conn.cursor() as q:
        q.execute(f"insert into `{schema}`.dashboard_label_source_raw_fba values "
                  "('2026-10-15 05:04:51')")
    with pytest.raises(RuntimeError, match="clearance.*row count mismatch"):
        validate_inventory_dates(conn, schema, [date(2026, 10, 14)])


def test_fractional_raw_timestamp_projection_has_same_fingerprint_after_copy(local_store):
    from etl.label_fba_source import fba_columns
    from etl.label_incremental_sources import read_fingerprints
    from etl.label_local_sources import SourceSpec, read_metadata, source_table_ddl

    conn, schema = local_store
    spec = SourceSpec(schema, "raw_fba", "dashboard_label_source_fba")
    with conn.cursor() as q:
        q.execute(f"create table `{schema}`.raw_fba (create_time datetime(6),"
                  "name varchar(255),seller_sku varchar(255),total int,"
                  "afn_fulfillable_quantity int,stock_up_num int,"
                  "inv_age_271_to_330_days int,inv_age_331_to_365_days int,"
                  "inv_age_365_plus_days int)")
        q.execute(f"insert into `{schema}`.raw_fba values "
                  "('2026-10-14 05:04:42.123456','booyee美国','SKU',20,10,3,0,0,0)")
        columns = fba_columns(read_metadata(conn, spec)[0])
        names = [c["column_name"] for c in columns]
        projection = fba_select_sql(names).replace(
            "`dwd_datasync`.`lx_storage_fba_warehouse_detail`", f"`{schema}`.raw_fba"
        )
        q.execute(source_table_ddl(f"`{schema}`.copied_fba", columns))
        q.execute(f"insert into `{schema}`.copied_fba {projection}")
    assert read_fingerprints(conn, spec, names, projection) == read_fingerprints(
        conn, spec, names, f"select * from `{schema}`.copied_fba"
    )


@pytest.mark.parametrize("version", ["dwd_fba_label_projection_20261012", None])
def test_old_input_archive_cannot_seed_new_daily_generation(local_store, version):
    from datetime import date
    import json
    from etl.label_fba_source import NORMALIZATION_VERSION
    from etl.label_local_contracts import validate_history_input_versions
    from etl.label_local_sql import BASELINE_SHA256, RULE_VERSION

    conn, schema = local_store
    with conn.cursor() as q:
        q.execute(f"create table `{schema}`.dashboard_label_local_source_batch "
                  "(batch_id varchar(36),local_name varchar(64),contract_json json)")
        q.execute(f"insert into `{schema}`.dashboard_label_local_days "
                  "(data_date,run_id,input_batch,input_hash,rule_version,baseline_sha256,"
                  "history_start,fact_rows,evidence_rows,summary_json) "
                  "values ('2026-10-13','run','old','hash',%s,%s,'2026-10-07',1,1,'{}')",
                  (RULE_VERSION, BASELINE_SHA256))
        if version is not None:
            q.execute(f"insert into `{schema}`.dashboard_label_local_source_batch "
                      "values ('old','dashboard_label_source_fba',%s)",
                      (json.dumps({"normalization_version": version}),))
    with pytest.raises(RuntimeError, match="archive.*normalization.*separate schema"):
        validate_history_input_versions(conn, schema, schema, [date(2026, 10, 13)])
    # Different daily batch IDs are compatible when their projection version agrees.
    with conn.cursor() as q:
        q.execute(f"delete from `{schema}`.dashboard_label_local_source_batch")
        q.execute(f"insert into `{schema}`.dashboard_label_local_source_batch "
                  "values ('old','dashboard_label_source_fba',%s)",
                  (json.dumps({"normalization_version": NORMALIZATION_VERSION}),))
    validate_history_input_versions(conn, schema, schema, [date(2026, 10, 13)])
