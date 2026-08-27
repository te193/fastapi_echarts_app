from __future__ import annotations

from datetime import date, timedelta

import pytest

from etl.stockout_historical_operating_update import (
    CREATE_TABLE_SQL,
    ENSURE_COUNTRY_INDEX_SQL,
    ENSURE_V3_COLUMN_SQL,
    _business_daily_rows,
    build_snapshot_rows,
    replace_snapshot_date,
    resolve_target_date,
    validate_source_dates,
)


def _performance(day, msku, country, sales=1):
    return {
        "dt_date": day,
        "country_category": "欧洲",
        "country": country,
        "store": "DE店",
        "msku": msku,
        "sales_qty": sales,
        "sales_amount": sales * 10,
        "order_gross_profit": sales * 2,
        "ranking": 20,
    }


def _inventory(day, msku, country, inventory):
    return {
        "dt_date": day,
        "country_category": "欧洲",
        "country": country,
        "store": "DE店",
        "msku": msku,
        "fba_available": inventory,
    }


def test_business_daily_rows_take_max_inventory_and_keep_days_without_performance():
    start = date(2026, 8, 24)
    performance = [_performance(start, "A", "DE", sales=3)]
    inventory = [
        _inventory(start, "A", "DE", 0),
        _inventory(start, "A", "FR", 2),
        _inventory(start + timedelta(days=1), "A", "DE", 0),
    ]

    rows = _business_daily_rows(performance, inventory)

    assert rows == [
        {
            "dt_date": start,
            "sales_qty": 3.0,
            "sales_amount": 30.0,
            "order_gross_profit": 6.0,
            "fba_available": 2.0,
            "ranking": None,
        },
        {
            "dt_date": start + timedelta(days=1),
            "sales_qty": 0.0,
            "sales_amount": 0.0,
            "order_gross_profit": 0.0,
            "fba_available": 0.0,
            "ranking": None,
        },
    ]


def test_snapshot_builder_outputs_business_unit_and_each_historical_country_member():
    start = date(2026, 1, 1)
    data_date = start + timedelta(days=100)
    performance = []
    inventory_rows = []
    for offset in range(101):
        day = start + timedelta(days=offset)
        inventory = 0 if day == data_date else 4
        performance.extend(
            [
                _performance(day, "A", "DE", 2),
                _performance(day, "A", "FR", 1),
                _performance(day, "B", "DE", 9),
            ]
        )
        inventory_rows.extend(
            [
                _inventory(day, "A", "DE", inventory),
                _inventory(day, "A", "FR", inventory),
                _inventory(day, "B", "DE", 10),
            ]
        )
    stockouts = [{"country_category": "欧洲", "store": "DE店", "msku": "A"}]
    rows = build_snapshot_rows(stockouts, performance, inventory_rows, data_date=data_date)

    assert {(row["scope_mode"], row["msku"], row["country"]) for row in rows} == {
        ("business_unit", "A", ""),
        ("country", "A", "DE"),
        ("country", "A", "FR"),
    }
    business_row = next(row for row in rows if row["scope_mode"] == "business_unit")
    assert business_row["pre_oos_role"] == "potential"
    assert business_row["valid_window_count"] >= 3
    assert business_row["historical_stability"] == "stable"
    assert business_row["combined_label"] == "潜力·持续稳定"


def test_country_roles_use_country_sales_margin_and_ranking_with_business_inventory_window():
    start = date(2026, 1, 1)
    data_date = start + timedelta(days=100)
    performance = []
    inventory_rows = []
    for offset in range(101):
        day = start + timedelta(days=offset)
        inventory = 0 if day == data_date else 4
        de = _performance(day, "A", "DE", 8)
        de.update(sales_amount=80, order_gross_profit=16, ranking=20)
        fr = _performance(day, "A", "FR", 1)
        fr.update(sales_amount=10, order_gross_profit=0.5, ranking=80)
        performance.append(de)
        if day != data_date:
            performance.append(fr)
        inventory_rows.append(_inventory(day, "A", "DE", inventory))

    rows = build_snapshot_rows(
        [{"country_category": "欧洲", "store": "DE店", "msku": "A"}],
        performance,
        inventory_rows,
        data_date=data_date,
    )

    countries = {row["country"]: row for row in rows if row["scope_mode"] == "country"}
    assert countries["DE"]["pre_oos_role"] == "star"
    assert countries["FR"]["pre_oos_role"] == "dog"
    assert countries["DE"]["oos_start_date"] == data_date
    assert countries["FR"]["oos_start_date"] == data_date
    assert countries["DE"]["evidence_json"].find('"inventory_scope":"inherited_business_unit"') >= 0


def test_label_304_is_authoritative_for_current_stockout_and_recalculates_role():
    start = date(2026, 1, 1)
    data_date = start + timedelta(days=100)
    performance = [_performance(start + timedelta(days=offset), "A", "DE", 2) for offset in range(101)]
    inventory_rows = [_inventory(start + timedelta(days=offset), "A", "DE", 4) for offset in range(101)]
    stockouts = [{"country_category": "欧洲", "store": "DE店", "msku": "A", "label_id": 304}]
    rows = build_snapshot_rows(stockouts, performance, inventory_rows, data_date=data_date)

    business_row = next(row for row in rows if row["scope_mode"] == "business_unit")
    assert len(rows) == 2
    assert business_row["current_oos_flag"] == 1
    assert business_row["oos_start_date"] == data_date
    assert business_row["current_gate_status"] == "evaluable"
    assert business_row["pre_oos_role"] == "potential"
    assert business_row["combined_label"] == "潜力·持续稳定"


def test_label_304_product_without_inventory_history_is_kept_as_insufficient_evidence():
    data_date = date(2026, 8, 25)
    stockouts = [{"country_category": "欧洲", "store": "DE店", "msku": "A", "label_id": 304}]

    rows = build_snapshot_rows(stockouts, [], [], data_date=data_date)

    assert len(rows) == 1
    assert rows[0]["current_oos_flag"] == 1
    assert rows[0]["oos_start_date"] is None
    assert rows[0]["oos_start_confidence"] == "event_boundary_incomplete"
    assert rows[0]["combined_label"] == "无有效历史角色"


def test_result_table_has_daily_scope_primary_key_and_query_indexes():
    normalized = " ".join(CREATE_TABLE_SQL.lower().split())

    assert "primary key (data_date, scope_mode, country_category, store, msku, country)" in normalized
    assert "key idx_date_scope_level" in normalized
    assert "idx_date_scope_country" in ENSURE_COUNTRY_INDEX_SQL
    assert "evidence_json json" in normalized
    assert "pre_oos_role varchar(32)" in normalized
    assert "role_source_date date" in normalized
    assert "valid_window_count int" in normalized
    assert "dominant_role_share decimal(10,6)" in normalized
    assert "role_switch_rate decimal(10,6)" in normalized
    assert "combined_label varchar(128)" in normalized
    assert "auxiliary_json json" in normalized
    migration_sql = " ".join(ENSURE_V3_COLUMN_SQL).lower()
    assert "add column pre_oos_role" in migration_sql
    assert "add column combined_label" in migration_sql
    assert "add column auxiliary_json" in migration_sql


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
        inventory_max_date=date(2026, 8, 21),
        label_partition_exists=True,
        performance_partition_exists=True,
        inventory_partition_exists=True,
    )


def test_source_validation_stops_when_latest_dates_disagree_or_history_partition_is_missing():
    with pytest.raises(RuntimeError, match="latest source date mismatch"):
        validate_source_dates(
            target_date=date(2026, 8, 21),
            label_max_date=date(2026, 8, 21),
            performance_max_date=date(2026, 8, 20),
            inventory_max_date=date(2026, 8, 21),
            label_partition_exists=True,
            performance_partition_exists=True,
            inventory_partition_exists=True,
        )
    with pytest.raises(RuntimeError, match="target source partition missing"):
        validate_source_dates(
            target_date=date(2026, 8, 20),
            label_max_date=date(2026, 8, 21),
            performance_max_date=date(2026, 8, 21),
            inventory_max_date=date(2026, 8, 21),
            label_partition_exists=True,
            performance_partition_exists=False,
            inventory_partition_exists=True,
        )

    with pytest.raises(RuntimeError, match="target source partition missing"):
        validate_source_dates(
            target_date=date(2026, 8, 20),
            label_max_date=date(2026, 8, 21),
            performance_max_date=date(2026, 8, 21),
            inventory_max_date=date(2026, 8, 21),
            label_partition_exists=True,
            performance_partition_exists=True,
            inventory_partition_exists=False,
        )


def test_explicit_historical_backfill_allows_newer_source_maximum_when_target_partitions_exist():
    validate_source_dates(
        target_date=date(2026, 8, 22),
        label_max_date=date(2026, 8, 22),
        performance_max_date=date(2026, 8, 23),
        inventory_max_date=date(2026, 8, 23),
        label_partition_exists=True,
        performance_partition_exists=True,
        inventory_partition_exists=True,
        allow_latest_mismatch=True,
    )
