from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from etl.stockout_historical_operating_update import (
    CREATE_TABLE_SQL,
    ENSURE_COUNTRY_INDEX_SQL,
    build_snapshot_rows,
    replace_snapshot_date,
    resolve_target_date,
    validate_source_dates,
)


def _performance(day, msku, country, inventory, sales=1):
    return {
        "dt_date": day,
        "country_category": "欧洲",
        "country": country,
        "store": "DE店",
        "msku": msku,
        "sales_qty": sales,
        "sales_amount": sales * 10,
        "order_gross_profit": sales * 2,
        "fba_available": inventory,
        "ranking": 20,
    }


def test_snapshot_builder_only_outputs_current_label_304_business_units_and_today_countries():
    start = date(2026, 1, 1)
    data_date = start + timedelta(days=100)
    performance = []
    for offset in range(101):
        day = start + timedelta(days=offset)
        inventory = 0 if day == data_date else 4
        performance.extend(
            [
                _performance(day, "A", "DE", inventory, 2),
                _performance(day, "A", "FR", inventory, 1),
                _performance(day, "B", "DE", 10, 9),
            ]
        )
    for row in performance:
        if row["msku"] == "A" and row["dt_date"] == data_date - timedelta(days=1):
            row["fba_available"] = 6
    stockouts = [{"country_category": "欧洲", "store": "DE店", "msku": "A"}]
    gate = {("\u6b27\u6d32", "DE\u5e97", "A"): {"status": "evaluable", "reason": ""}}

    rows = build_snapshot_rows(stockouts, performance, gate, data_date=data_date)

    assert {(row["scope_mode"], row["msku"], row["country"]) for row in rows} == {
        ("business_unit", "A", ""),
        ("country", "A", "DE"),
        ("country", "A", "FR"),
    }


def test_country_results_inherit_business_inventory_event_but_keep_country_sales_independent():
    start = date(2026, 1, 1)
    data_date = start + timedelta(days=100)
    performance = []
    for offset in range(101):
        day = start + timedelta(days=offset)
        inventory = 0 if day == data_date else 4
        performance.extend(
            [
                _performance(day, "A", "DE", inventory, 8),
                _performance(day, "A", "FR", inventory, 0.2),
            ]
        )
    for row in performance:
        if row["dt_date"] == data_date - timedelta(days=1):
            row["fba_available"] = 6
    stockouts = [{"country_category": "欧洲", "store": "DE店", "msku": "A"}]
    gate = {("\u6b27\u6d32", "DE\u5e97", "A"): {"status": "evaluable", "reason": ""}}

    rows = build_snapshot_rows(stockouts, performance, gate, data_date=data_date)
    business = next(row for row in rows if row["scope_mode"] == "business_unit")
    countries = [row for row in rows if row["scope_mode"] == "country"]

    assert all(row["oos_start_date"] == business["oos_start_date"] for row in countries)
    assert all(json.loads(row["evidence_json"])["inventory_scope"] == "inherited_business_unit" for row in countries)
    assert {row["role_30d"] for row in countries} == {"star", "dog"}


def test_result_table_has_daily_scope_primary_key_and_query_indexes():
    normalized = " ".join(CREATE_TABLE_SQL.lower().split())

    assert "primary key (data_date, scope_mode, country_category, store, msku, country)" in normalized
    assert "key idx_date_scope_level" in normalized
    assert "idx_date_scope_country" in ENSURE_COUNTRY_INDEX_SQL
    assert "evidence_json json" in normalized


class _FakeCursor:
    def __init__(self, fail_insert=False):
        self.fail_insert = fail_insert
        self.deleted_dates = []
        self.inserted = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        if sql.lstrip().lower().startswith("delete"):
            self.deleted_dates.append(params["data_date"])

    def executemany(self, _sql, rows):
        if self.fail_insert:
            raise RuntimeError("insert failed")
        self.inserted.extend(rows)


class _FakeConnection:
    def __init__(self, fail_insert=False):
        self.cursor_instance = _FakeCursor(fail_insert)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_replace_snapshot_date_commits_one_date_without_touching_history():
    conn = _FakeConnection()
    target = date(2026, 8, 20)

    replace_snapshot_date(conn, target, [{"data_date": target, "scope_mode": "business_unit"}])

    assert conn.cursor_instance.deleted_dates == [target]
    assert conn.committed is True
    assert conn.rolled_back is False


def test_replace_snapshot_date_rolls_back_failed_rebuild():
    conn = _FakeConnection(fail_insert=True)

    with pytest.raises(RuntimeError, match="insert failed"):
        replace_snapshot_date(conn, date(2026, 8, 20), [{"data_date": date(2026, 8, 20)}])

    assert conn.committed is False
    assert conn.rolled_back is True


def test_daily_runner_business_date_is_used_as_snapshot_date():
    assert resolve_target_date("", "2026-08-20", date(2026, 8, 21)) == date(2026, 8, 20)


def test_historical_target_can_be_rebuilt_after_both_sources_advance():
    validate_source_dates(
        target_date=date(2026, 8, 20),
        label_max_date=date(2026, 8, 21),
        performance_max_date=date(2026, 8, 21),
        label_partition_exists=True,
        performance_partition_exists=True,
    )


def test_source_validation_stops_when_latest_dates_disagree_or_history_partition_is_missing():
    with pytest.raises(RuntimeError, match="latest source date mismatch"):
        validate_source_dates(
            target_date=date(2026, 8, 21),
            label_max_date=date(2026, 8, 21),
            performance_max_date=date(2026, 8, 20),
            label_partition_exists=True,
            performance_partition_exists=True,
        )
    with pytest.raises(RuntimeError, match="target source partition missing"):
        validate_source_dates(
            target_date=date(2026, 8, 20),
            label_max_date=date(2026, 8, 21),
            performance_max_date=date(2026, 8, 21),
            label_partition_exists=True,
            performance_partition_exists=False,
        )


def test_explicit_historical_backfill_allows_newer_source_maximum_when_target_partitions_exist():
    validate_source_dates(
        target_date=date(2026, 8, 22),
        label_max_date=date(2026, 8, 22),
        performance_max_date=date(2026, 8, 23),
        label_partition_exists=True,
        performance_partition_exists=True,
        allow_latest_mismatch=True,
    )
