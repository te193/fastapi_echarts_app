from datetime import date

from etl.label_rule_evidence_snapshot_update import (
    CREATE_TABLE_SQL,
    LOCAL_LABEL_DETAIL_TABLE,
    LOCAL_LABEL_FACT_TABLE,
    classify_sales_role,
    fact_table_sql,
    parse_periods,
    refresh,
    snapshot_date_plan,
)
from etl.dashboard_daily_update import SchemaConfig


def test_sales_role_evidence_uses_remote_rule_thresholds():
    assert classify_sales_role(6, 0.20) == 101
    assert classify_sales_role(2, 0.12) == 102
    assert classify_sales_role(0.8, 0.08) == 103
    assert classify_sales_role(0, 0.30) == 104
    assert parse_periods("7d,14d,30d,90d") == (7, 14, 30, 90)
    assert "raw_order_gross_profit" not in CREATE_TABLE_SQL
    assert "最近两个标签日期" in CREATE_TABLE_SQL
    assert "idx_label_date" in fact_table_sql(LOCAL_LABEL_FACT_TABLE, include_indexes=True)
    assert "idx_date_unit" in fact_table_sql(LOCAL_LABEL_FACT_TABLE, include_indexes=True)
    assert "evidence_blob mediumblob" in fact_table_sql(LOCAL_LABEL_FACT_TABLE, include_indexes=True)
    assert "evidence_json json" not in fact_table_sql(LOCAL_LABEL_FACT_TABLE, include_indexes=True)
    assert LOCAL_LABEL_DETAIL_TABLE.endswith("dashboard_label_detail_snapshot")


def test_snapshot_date_plan_refreshes_latest_and_reuses_previous_local_date():
    latest = date(2026, 8, 17)
    previous = date(2026, 8, 16)

    remote_dates, reused_dates = snapshot_date_plan(
        (latest, previous),
        {latest, previous},
    )

    assert remote_dates == (latest,)
    assert reused_dates == (previous,)


def test_snapshot_date_plan_fetches_both_dates_when_local_snapshot_is_empty():
    dates = (date(2026, 8, 17), date(2026, 8, 16))

    remote_dates, reused_dates = snapshot_date_plan(dates, set())

    assert remote_dates == dates
    assert reused_dates == ()


class Cursor:
    def __init__(self):
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def executemany(self, sql, rows):
        self.executions.append((sql, rows))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Connection:
    def __init__(self):
        self.cursor_instance = Cursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_refresh_keeps_only_latest_two_label_dates():
    conn = Connection()
    schemas = SchemaConfig("etl_datasync_test", "etl_datasync", "dwd_datasync", "temporary_dwd")
    dates = (date(2026, 7, 19), date(2026, 7, 18))
    affected = refresh(conn, schemas, [], dates)

    assert affected == 0
    assert conn.committed
    delete_sql = [sql for sql, _ in conn.cursor_instance.executions if "delete from" in sql.lower()]
    assert any("label_date not in" in sql.lower() for sql in delete_sql)
    assert all("etl_datasync_test.dashboard_label_rule_evidence_snapshot" in sql for sql in delete_sql)
