from __future__ import annotations

import importlib
import json
from datetime import date, datetime

import pytest


def cache_module():
    return importlib.import_module("etl.station_sales_role_cache")


def remote_row(data_date: date, period_days: int, msku: str = "A1") -> dict:
    return {
        "data_date": data_date,
        "country": "德国",
        "store": "StoreA",
        "msku": msku,
        "label_id": 1301,
        "label_period": f"{period_days}d",
        "created_time": datetime(2026, 8, 17, 7, 19),
        "evidence_json": json.dumps(
            {
                "metrics": {
                    "daily_sales": 4,
                    "sales_amount": 400,
                    "tag_gross_profit": 80,
                    "tag_margin_rate": 20,
                    "small_rank": 10,
                    "small_rank_stat_date": data_date.isoformat(),
                },
                "rule_version": "v47",
            }
        ),
    }


def complete_rows() -> list[dict]:
    return [
        remote_row(data_date, period_days)
        for data_date in (date(2026, 8, 15), date(2026, 8, 16))
        for period_days in (7, 14, 30, 90)
    ]


def test_recent_cache_ddl_uses_exact_station_business_key():
    ddl = " ".join(cache_module().station_role_recent_cache_ddl("etl_datasync_test").split())

    assert "station_sales_role_recent_cache" in ddl
    assert "primary key (data_date, period_days, country, station_store, msku)" in ddl
    assert "source_created_time" in ddl
    assert "evidence_json" in ddl


def test_validate_remote_rows_rejects_duplicate_business_keys():
    rows = complete_rows()
    rows.append(dict(rows[0]))

    with pytest.raises(ValueError, match="duplicate"):
        cache_module().validate_remote_rows(rows, [date(2026, 8, 15), date(2026, 8, 16)])


def test_validate_remote_rows_requires_every_remote_period_for_each_date():
    rows = [row for row in complete_rows() if not (row["data_date"] == date(2026, 8, 15) and row["label_period"] == "90d")]

    with pytest.raises(ValueError, match="missing periods"):
        cache_module().validate_remote_rows(rows, [date(2026, 8, 15), date(2026, 8, 16)])


class SourceCursor:
    def __init__(self, rows):
        self.rows = rows
        self.result = []
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))
        if "select distinct data_date" in sql.lower():
            self.result = [{"data_date": date(2026, 8, 16)}, {"data_date": date(2026, 8, 15)}]
        else:
            assert set(params["label_ids"]) == {1301, 1302, 1303, 1304}
            assert set(params["periods"]) == {"7d", "14d", "30d", "90d"}
            self.result = self.rows

    def fetchall(self):
        return list(self.result)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SourceConnection:
    def __init__(self, rows):
        self.cursor_instance = SourceCursor(rows)

    def cursor(self):
        return self.cursor_instance


class TargetCursor:
    def __init__(self):
        self.executions = []
        self.inserted = []

    def execute(self, sql, params=None):
        self.executions.append((" ".join(sql.split()), params))

    def executemany(self, sql, rows):
        self.executions.append((" ".join(sql.split()), None))
        self.inserted.extend(rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TargetConnection:
    def __init__(self):
        self.cursor_instance = TargetCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_sync_recent_cache_replaces_only_after_complete_validation():
    source = SourceConnection(complete_rows())
    target = TargetConnection()

    result = cache_module().sync_recent_station_role_cache(
        source,
        target,
        "etl_datasync_test",
        batch_size=3,
    )

    assert result.data_dates == (date(2026, 8, 15), date(2026, 8, 16))
    assert result.row_count == 8
    assert target.commits == 1
    assert target.rollbacks == 0
    assert len(target.cursor_instance.inserted) == 8
    statements = " ".join(sql.lower() for sql, _ in target.cursor_instance.executions)
    assert "delete from `etl_datasync_test`.`station_sales_role_recent_cache`" in statements
    assert "insert into `etl_datasync_test`.`station_sales_role_recent_cache`" in statements
