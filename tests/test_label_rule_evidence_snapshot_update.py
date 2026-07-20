from datetime import date

from etl.label_rule_evidence_snapshot_update import (
    CREATE_TABLE_SQL,
    classify_sales_role,
    parse_periods,
    refresh,
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
