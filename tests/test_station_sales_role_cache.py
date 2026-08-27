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


def fingerprint_rows(rows: list[dict]) -> list[dict]:
    grouped = {}
    for row in rows:
        item = grouped.setdefault(
            row["data_date"],
            {
                "data_date": row["data_date"],
                "source_row_count": 0,
                "source_period_count": 0,
                "source_max_created_time": row["created_time"],
                "source_checksum_sum": 0,
                "source_checksum_xor": 0,
                "_periods": set(),
            },
        )
        item["source_row_count"] += 1
        item["_periods"].add(row["label_period"])
        item["source_max_created_time"] = max(item["source_max_created_time"], row["created_time"])
        checksum = sum(ord(char) for char in f"{row['data_date']}|{row['label_period']}|{row['msku']}")
        item["source_checksum_sum"] += checksum
        item["source_checksum_xor"] ^= checksum
    result = []
    for item in grouped.values():
        item["source_period_count"] = len(item.pop("_periods"))
        result.append(item)
    return sorted(result, key=lambda item: item["data_date"])


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
        self.offset = 0
        self.is_detail_query = False
        self.detail_query_count = 0
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))
        normalized_sql = " ".join(sql.lower().split())
        if "select distinct data_date" in normalized_sql:
            self.is_detail_query = False
            self.result = [{"data_date": date(2026, 8, 16)}, {"data_date": date(2026, 8, 15)}]
        elif "source_checksum_sum" in normalized_sql:
            self.is_detail_query = False
            self.result = fingerprint_rows(self.rows)
        else:
            self.is_detail_query = True
            self.detail_query_count += 1
            assert "json_object" in normalized_sql
            assert "$.metrics" in normalized_sql
            assert "$.rule_version" in normalized_sql
            assert set(params["label_ids"]) == {1301, 1302, 1303, 1304}
            assert set(params["periods"]) == {"7d", "14d", "30d", "90d"}
            self.result = [
                row for row in self.rows
                if row["data_date"] in params["data_dates"]
            ]
        self.offset = 0

    def fetchall(self):
        if self.is_detail_query:
            raise AssertionError("detail query must be consumed in bounded batches")
        return list(self.result)

    def fetchmany(self, size):
        batch = self.result[self.offset:self.offset + size]
        self.offset += len(batch)
        return list(batch)

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
    def __init__(self, local_state=None):
        self.executions = []
        self.result = []
        self.local_state = list(local_state or [])
        self.cache_inserted = []
        self.state_upserted = []

    def execute(self, sql, params=None):
        normalized_sql = " ".join(sql.split())
        self.executions.append((normalized_sql, params))
        if "from `etl_datasync_test`.`station_sales_role_cache_state` s" in normalized_sql:
            self.result = self.local_state
        else:
            self.result = []

    def executemany(self, sql, rows):
        normalized_sql = " ".join(sql.split())
        materialized = list(rows)
        self.executions.append((normalized_sql, None))
        if "tmp_station_sales_role_recent_cache" in normalized_sql:
            self.cache_inserted.extend(materialized)
        elif "station_sales_role_cache_state" in normalized_sql:
            self.state_upserted.extend(materialized)

    def fetchall(self):
        return list(self.result)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TargetConnection:
    def __init__(self, local_state=None):
        self.cursor_instance = TargetCursor(local_state)
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
    assert result.changed_dates == (date(2026, 8, 15), date(2026, 8, 16))
    assert target.commits == 1
    assert target.rollbacks == 0
    assert len(target.cursor_instance.cache_inserted) == 8
    assert len(target.cursor_instance.state_upserted) == 2
    statements = " ".join(sql.lower() for sql, _ in target.cursor_instance.executions)
    assert "delete from `etl_datasync_test`.`station_sales_role_recent_cache` where data_date in" in statements
    assert "insert into `etl_datasync_test`.`station_sales_role_recent_cache`" in statements


def test_sync_recent_cache_skips_detail_download_when_both_dates_are_unchanged():
    rows = complete_rows()
    local_state = [
        {
            **item,
            "local_row_count": item["source_row_count"],
            "local_period_count": item["source_period_count"],
        }
        for item in fingerprint_rows(rows)
    ]
    source = SourceConnection(rows)
    target = TargetConnection(local_state)

    result = cache_module().sync_recent_station_role_cache(
        source,
        target,
        "etl_datasync_test",
        batch_size=3,
    )

    assert result.row_count == 0
    assert result.changed_dates == ()
    assert source.cursor_instance.detail_query_count == 0
    assert target.cursor_instance.cache_inserted == []
    assert target.cursor_instance.state_upserted == []


def test_sync_recent_cache_only_downloads_and_replaces_changed_date():
    rows = complete_rows()
    fingerprints = fingerprint_rows(rows)
    unchanged = fingerprints[0]
    local_state = [
        {
            **unchanged,
            "local_row_count": unchanged["source_row_count"],
            "local_period_count": unchanged["source_period_count"],
        },
        {
            **fingerprints[1],
            "source_checksum_sum": fingerprints[1]["source_checksum_sum"] - 1,
            "local_row_count": fingerprints[1]["source_row_count"],
            "local_period_count": fingerprints[1]["source_period_count"],
        },
    ]
    source = SourceConnection(rows)
    target = TargetConnection(local_state)

    result = cache_module().sync_recent_station_role_cache(
        source,
        target,
        "etl_datasync_test",
        batch_size=3,
    )

    assert result.changed_dates == (date(2026, 8, 16),)
    assert result.row_count == 4
    detail_params = [
        params
        for sql, params in source.cursor_instance.executions
        if "json_object" in " ".join(sql.lower().split())
    ]
    assert detail_params[0]["data_dates"] == (date(2026, 8, 16),)
    statements = [
        (sql.lower(), params)
        for sql, params in target.cursor_instance.executions
        if "delete from `etl_datasync_test`.`station_sales_role_recent_cache` where data_date in" in sql.lower()
    ]
    assert statements[0][1]["changed_dates"] == (date(2026, 8, 16),)


def test_sync_recent_cache_keeps_live_cache_when_stream_is_incomplete():
    rows = [
        row for row in complete_rows()
        if not (row["data_date"] == date(2026, 8, 15) and row["label_period"] == "90d")
    ]
    source = SourceConnection(rows)
    target = TargetConnection()

    with pytest.raises(ValueError, match="missing periods"):
        cache_module().sync_recent_station_role_cache(
            source,
            target,
            "etl_datasync_test",
            batch_size=3,
        )

    statements = " ".join(sql.lower() for sql, _ in target.cursor_instance.executions)
    assert "delete from `etl_datasync_test`.`station_sales_role_recent_cache`" not in statements
    assert target.commits == 0
    assert target.rollbacks == 1
