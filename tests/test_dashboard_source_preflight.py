from datetime import date

import pytest

from etl.dashboard_daily_update import SchemaConfig
from etl.dashboard_source_preflight import PreflightFailure, check_source_readiness


def test_source_preflight_rejects_missing_required_business_date():
    conn = FakePreflightConnection(
        {
            "product_performance_daily_source": 0,
            "restock_snapshot_source": 49804,
            "inventory_snapshot_source": 16575,
            "listing_price_snapshot_source": 61000,
            "limit_price_source_current": 3200,
        }
    )

    with pytest.raises(PreflightFailure, match="product_performance_daily_source.*2026-06-26"):
        check_source_readiness(conn, schema_config(), preflight_params())


def test_source_preflight_returns_counts_when_all_required_sources_are_ready():
    conn = FakePreflightConnection(
        {
            "product_performance_daily_source": 18527,
            "restock_snapshot_source": 49804,
            "inventory_snapshot_source": 16575,
            "listing_price_snapshot_source": 61000,
            "limit_price_source_current": 3200,
        }
    )

    results = check_source_readiness(conn, schema_config(), preflight_params())

    assert [result.name for result in results] == [
        "product_performance_daily_source",
        "restock_snapshot_source",
        "inventory_snapshot_source",
        "listing_price_snapshot_source",
        "limit_price_source_current",
    ]
    assert results[0].row_count == 18527
    assert all(call["params"]["biz_date"] == date(2026, 6, 26) for call in conn.calls)


def schema_config():
    return SchemaConfig(
        target_schema="etl_datasync_test",
        etl_source_schema="etl_datasync",
        dwd_source_schema="dwd_datasync",
        pricing_source_schema="temporary_dwd",
    )


def preflight_params():
    return {
        "biz_date": date(2026, 6, 26),
        "snapshot_date": date(2026, 6, 27),
        "next_snapshot_date": date(2026, 6, 28),
        "product_start_date": date(2026, 5, 8),
        "product_end_date": date(2026, 6, 26),
        "next_product_end_date": date(2026, 6, 27),
        "product_full_load": 0,
    }


class FakePreflightCursor:
    def __init__(self, conn):
        self.conn = conn
        self.current_name = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        for name in self.conn.counts:
            if name in sql:
                self.current_name = name
                break
        self.conn.calls.append({"sql": sql, "params": params, "name": self.current_name})
        return 1

    def fetchone(self):
        return {"row_count": self.conn.counts[self.current_name]}


class FakePreflightConnection:
    def __init__(self, counts):
        self.counts = counts
        self.calls = []

    def cursor(self):
        return FakePreflightCursor(self)
