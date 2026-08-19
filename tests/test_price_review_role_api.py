import json
from datetime import date
from unittest.mock import patch

from app import main
from app.services.price_review_data import PriceReviewService


class FakeRoleMigrationService:
    def __init__(self):
        self.calls = []

    def get_role_migration_payload(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "summary": {"total": 1}}


class FixtureRoleMigrationService(PriceReviewService):
    def _load_role_cache_status(self):
        return {
            "latest_data_date": "2026-08-16",
            "earliest_data_date": "2026-08-15",
            "synced_at": "2026-08-17T07:22:00",
            "cached_dates": 2,
        }

    def _load_role_migration_rows(self, adjust_date, pre_days, post_days):
        return [
            {
                "adjust_date": adjust_date,
                "pre_period_days": pre_days,
                "post_period_days": post_days,
                "country": "德国",
                "store": "StoreA-DE",
                "station_store": "StoreA",
                "msku": "A1",
                "role_before_code": "potential",
                "role_before_label": "潜力产品",
                "role_after_code": "star",
                "role_after_label": "明星产品",
                "role_change": "up",
                "data_status": "complete",
                "finance_band_before_code": "30_35",
                "finance_band_before_label": "30–35%",
                "finance_band_after_code": "20_25",
                "finance_band_after_label": "20–25%",
                "finance_change": "down",
                "pre_period_start": date(2026, 7, 11),
                "pre_period_end": date(2026, 8, 9),
                "post_period_start": date(2026, 8, 11),
                "post_period_end": date(2026, 8, 13),
                "finance_snapshot_date": date(2026, 8, 10),
                "pre_role_source": "remote_cache",
                "post_role_source": "local_v47",
                "pre_source_data_date": date(2026, 8, 9),
                "post_source_data_date": date(2026, 8, 13),
            },
            {
                "adjust_date": adjust_date,
                "pre_period_days": pre_days,
                "post_period_days": post_days,
                "country": "德国",
                "store": "StoreA-DE",
                "station_store": "StoreA",
                "msku": "A2",
                "role_before_code": "dog",
                "role_before_label": "瘦狗产品",
                "role_after_code": "dog",
                "role_after_label": "瘦狗产品",
                "role_change": "stable",
                "data_status": "complete",
                "finance_band_before_code": "unavailable",
                "finance_band_before_label": "无法归类",
                "finance_band_after_code": "unavailable",
                "finance_band_after_label": "无法归类",
                "finance_change": "unavailable",
            },
            {
                "adjust_date": adjust_date,
                "pre_period_days": pre_days,
                "post_period_days": post_days,
                "country": "法国",
                "store": "StoreB-FR",
                "station_store": "StoreB",
                "msku": "B1",
                "role_before_code": "star",
                "role_before_label": "明星产品",
                "role_after_code": None,
                "role_after_label": None,
                "role_change": "unavailable",
                "data_status": "pending",
                "finance_change": "stable",
            },
        ]


def test_role_migration_api_passes_station_filters_to_service():
    service = FakeRoleMigrationService()

    with patch("app.main.price_review_service", service):
        payload = main.api_price_review_role_migration(
            adjust_date="2026-08-10",
            pre_days=14,
            post_days=3,
            comparison_mode=None,
            country="德国",
            store="StoreA",
            role_before="potential",
            role_after="star",
            role_change="up",
            finance_change="down",
            finance_before="30_35",
            finance_after="20_25",
            data_status="complete",
            keyword="A1",
            page=2,
            page_size=50,
            sort_field="post_margin_rate",
            sort_dir="desc",
            column_filters=json.dumps({"msku": {"filterType": "text", "type": "contains", "filter": "A"}}),
        )

    assert payload["ok"] is True
    assert service.calls == [{
        "adjust_date": date(2026, 8, 10),
        "pre_days": 14,
        "post_days": 3,
        "country": "德国",
        "store": "StoreA",
        "role_before": "potential",
        "role_after": "star",
        "role_change_filter": "up",
        "finance_change_filter": "down",
        "finance_before": "30_35",
        "finance_after": "20_25",
        "data_status": "complete",
        "keyword": "A1",
        "page": 2,
        "page_size": 50,
        "sort_field": "post_margin_rate",
        "sort_dir": "desc",
        "column_filters": json.dumps({"msku": {"filterType": "text", "type": "contains", "filter": "A"}}),
    }]


def test_role_migration_payload_keeps_pending_out_of_role_matrix_and_counts():
    service = FixtureRoleMigrationService()

    payload = service.get_role_migration_payload(
        adjust_date=date(2026, 8, 10),
        pre_days=30,
        post_days=3,
    )

    assert payload["summary"] == {
        "total": 3,
        "valid": 2,
        "up": 1,
        "down": 0,
        "stable": 1,
        "pending": 1,
        "source_incomplete": 0,
        "finance_up": 0,
        "finance_down": 1,
        "finance_stable": 0,
        "finance_unavailable": 1,
    }
    assert sum(cell["count"] for cell in payload["role_matrix"]) == 2
    assert {row["msku"] for row in payload["rows"]} == {"A1", "A2", "B1"}


def test_role_migration_payload_filters_before_summarizing_and_paginating():
    service = FixtureRoleMigrationService()

    payload = service.get_role_migration_payload(
        adjust_date=date(2026, 8, 10),
        pre_days=30,
        post_days=3,
        country="德国",
        role_change_filter="up",
        page=1,
        page_size=20,
    )

    assert payload["summary"]["total"] == 1
    assert payload["summary"]["up"] == 1
    assert payload["total"] == 1
    assert payload["rows"][0]["msku"] == "A1"
    assert payload["filter_options"]["stores"] == ["StoreA", "StoreB"]


def test_role_migration_payload_filters_an_exact_finance_transition():
    service = FixtureRoleMigrationService()

    payload = service.get_role_migration_payload(
        adjust_date=date(2026, 8, 10),
        pre_days=30,
        post_days=3,
        finance_before="30_35",
        finance_after="20_25",
    )

    assert payload["total"] == 1
    assert payload["rows"][0]["msku"] == "A1"


def test_role_migration_payload_applies_ag_grid_filters_before_server_pagination():
    service = FixtureRoleMigrationService()

    payload = service.get_role_migration_payload(
        adjust_date=date(2026, 8, 10),
        pre_days=30,
        post_days=3,
        column_filters=json.dumps({
            "role_before_label": {
                "filterType": "text",
                "type": "contains",
                "filter": "潜力",
            }
        }),
        page=1,
        page_size=20,
    )

    assert payload["total"] == 1
    assert payload["rows"][0]["msku"] == "A1"
    assert payload["summary"]["total"] == 1


def test_role_migration_payload_sorts_the_full_filtered_result_before_paginating():
    service = FixtureRoleMigrationService()

    payload = service.get_role_migration_payload(
        adjust_date=date(2026, 8, 10),
        pre_days=30,
        post_days=3,
        sort_field="msku",
        sort_dir="desc",
        page=1,
        page_size=2,
    )

    assert payload["total"] == 3
    assert [row["msku"] for row in payload["rows"]] == ["B1", "A2"]


def test_role_migration_payload_keeps_window_context_when_filters_return_no_rows():
    service = FixtureRoleMigrationService()

    payload = service.get_role_migration_payload(
        adjust_date=date(2026, 8, 10),
        pre_days=30,
        post_days=3,
        country="英国",
    )

    assert payload["rows"] == []
    assert payload["context"] == {
        "pre_period_start": "2026-07-11",
        "pre_period_end": "2026-08-09",
        "post_period_start": "2026-08-11",
        "post_period_end": "2026-08-13",
        "finance_snapshot_date": "2026-08-10",
        "pre_role_source": "remote_cache",
        "post_role_source": "local_v47",
        "pre_source_data_date": "2026-08-09",
        "post_source_data_date": "2026-08-13",
    }


def test_role_migration_context_uses_available_batch_source_instead_of_first_incomplete_row():
    service = FixtureRoleMigrationService()
    rows = service._load_role_migration_rows(date(2026, 8, 10), 7, 7)
    incomplete = {
        **rows[0],
        "msku": "MISSING",
        "data_status": "source_incomplete",
        "pre_role_source": "unavailable",
        "post_role_source": "unavailable",
    }
    recomputed = {
        **rows[0],
        "msku": "READY",
        "pre_role_source": "local_recomputed",
        "post_role_source": "local_recomputed",
    }

    with patch.object(service, "_load_role_migration_rows", return_value=[incomplete, recomputed]):
        payload = service.get_role_migration_payload(
            adjust_date=date(2026, 8, 10),
            pre_days=7,
            post_days=7,
        )

    assert payload["context"]["pre_role_source"] == "local_recomputed"
    assert payload["context"]["post_role_source"] == "local_recomputed"


def test_role_migration_api_maps_legacy_equal_window_link_to_pre_period():
    service = FakeRoleMigrationService()

    with patch("app.main.price_review_service", service):
        main.api_price_review_role_migration(
            adjust_date="2026-08-10",
            pre_days=None,
            post_days=7,
            comparison_mode="equal_window",
        )

    assert service.calls[0]["pre_days"] == 7
    assert service.calls[0]["post_days"] == 7
    assert "comparison_mode" not in service.calls[0]


def test_role_migration_payload_exposes_independent_period_options():
    service = FixtureRoleMigrationService()

    payload = service.get_role_migration_payload(
        adjust_date=date(2026, 8, 10),
        pre_days=14,
        post_days=7,
    )

    assert payload["pre_days"] == 14
    assert payload["post_days"] == 7
    assert payload["meta"]["default_pre_days"] == 30
    assert payload["meta"]["default_post_days"] == 3
    assert [item["key"] for item in payload["meta"]["periods"]] == [3, 7, 14, 30, 90]
    assert "comparison_modes" not in payload["meta"]
    assert payload["cache_status"] == {
        "latest_data_date": "2026-08-16",
        "earliest_data_date": "2026-08-15",
        "synced_at": "2026-08-17T07:22:00",
        "cached_dates": 2,
    }
