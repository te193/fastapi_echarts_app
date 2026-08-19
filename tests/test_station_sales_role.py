from datetime import date, datetime
from decimal import Decimal

import pytest

from app.services import station_sales_role
from app.services.station_sales_role import (
    build_station_role_tracking_row,
    classify_station_sales_role,
    finance_price_band,
    role_change,
    tracking_windows,
)


@pytest.mark.parametrize(
    ("daily_sales", "margin_rate", "rank", "expected"),
    [
        (3.01, 0.15, 50, "star"),
        (3.01, 0.15, 51, "potential"),
        (1.0, 0.25, 50, "star"),
        (3.0, 0.2499, 100, "potential"),
        (3.01, 0.1499, 100, "potential"),
        (0.99, 0.05, 101, "dog"),
        (3.01, 0.15, 101, "dog"),
        (0, 0.40, 1, "problem"),
        (8, 0.0499, 1, "problem"),
        (8, 0.30, None, "problem"),
        (8, 0.30, 0, "problem"),
        (8, 0.30, 99999, "problem"),
    ],
)
def test_station_role_v47_boundaries(daily_sales, margin_rate, rank, expected):
    assert classify_station_sales_role(daily_sales, margin_rate, rank)["code"] == expected


def test_tracking_windows_accept_independent_pre_and_post_periods():
    windows = tracking_windows(date(2026, 8, 10), 14, 3)

    assert windows.pre_start == date(2026, 7, 28)
    assert windows.pre_end == date(2026, 8, 10)
    assert windows.post_start == date(2026, 8, 11)
    assert windows.post_end == date(2026, 8, 13)
    assert windows.pre_days == 14
    assert windows.post_days == 3


def test_tracking_windows_include_adjustment_day_in_pre_period():
    windows = tracking_windows(date(2026, 8, 10), 7, 7)

    assert windows.pre_start == date(2026, 8, 4)
    assert windows.pre_end == date(2026, 8, 10)
    assert windows.post_start == date(2026, 8, 11)
    assert windows.post_end == date(2026, 8, 17)


def test_remote_role_snapshot_normalizes_percent_margin_and_v47_evidence():
    snapshot = station_sales_role.normalize_remote_role_snapshot(
        {
            "data_date": date(2026, 8, 16),
            "label_period": "14d",
            "label_id": 1301,
            "created_time": datetime(2026, 8, 17, 7, 19, 38),
            "evidence_json": {
                "metrics": {
                    "daily_sales": 6,
                    "sales_amount": 8205.75,
                    "tag_gross_profit": 1303.07,
                    "tag_margin_rate": 15.88,
                    "small_rank": 23,
                    "small_rank_stat_date": "2026-08-16",
                },
                "rule_version": "v47",
            },
        }
    )

    assert snapshot["role_code"] == "star"
    assert snapshot["margin_rate"] == Decimal("0.1588")
    assert snapshot["source"] == "remote_dws"
    assert snapshot["source_data_date"] == date(2026, 8, 16)
    assert snapshot["small_rank_date"] == date(2026, 8, 16)


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("potential", "star", "up"),
        ("dog", "dog", "stable"),
        ("star", "problem", "down"),
        (None, "star", "unavailable"),
    ],
)
def test_role_change_uses_business_rank(before, after, expected):
    assert role_change(before, after) == expected


@pytest.fixture
def valid_ladder():
    return {0: 10, 5: 11, 10: 12, 15: 13, 20: 14, 25: 15, 30: 16, 35: 17}


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (9.99, "below_0"),
        (10, "0_5"),
        (11, "5_10"),
        (16.99, "30_35"),
        (17, "at_least_35"),
    ],
)
def test_finance_price_band_assigns_threshold_equal_to_upper_margin(price, expected, valid_ladder):
    assert finance_price_band(price, valid_ladder)["code"] == expected


def test_finance_price_band_rejects_missing_or_non_monotonic_ladder(valid_ladder):
    missing = dict(valid_ladder)
    missing.pop(15)
    non_monotonic = dict(valid_ladder)
    non_monotonic[20] = 12

    assert finance_price_band(13, missing)["code"] == "unavailable"
    assert finance_price_band(13, non_monotonic)["code"] == "invalid_ladder"


def test_tracking_row_builds_complete_role_and_finance_migrations(valid_ladder):
    raw = {
        "adjust_date": date(2026, 8, 10),
        "country": "德国",
        "station_store": "Store-DE",
        "store": "Store",
        "msku": "MSKU1",
        "price_before": 16.5,
        "price_after": 14.5,
        "pre_seen_days": 30,
        "post_seen_days": 3,
        "pre_sales_qty": 120,
        "post_sales_qty": 12,
        "pre_sales_amount": 1000,
        "post_sales_amount": 100,
        "pre_order_profit": 200,
        "post_order_profit": 20,
        "pre_small_rank": 80,
        "post_small_rank": 40,
        "finance_snapshot_date": date(2026, 8, 10),
        **{f"margin_price_{level}": value for level, value in valid_ladder.items()},
    }

    row = build_station_role_tracking_row(raw, 30, 3, date(2026, 8, 17))

    assert row["data_status"] == "complete"
    assert row["role_before_code"] == "potential"
    assert row["role_after_code"] == "star"
    assert row["role_change"] == "up"
    assert row["finance_band_before_code"] == "30_35"
    assert row["finance_band_after_code"] == "20_25"
    assert row["finance_change"] == "down"


def test_tracking_row_keeps_pending_window_out_of_role_change(valid_ladder):
    raw = {
        "adjust_date": date(2026, 8, 10),
        "pre_seen_days": 30,
        "post_seen_days": 2,
        "pre_sales_qty": 120,
        "pre_sales_amount": 1000,
        "pre_order_profit": 200,
        "pre_small_rank": 40,
        **{f"margin_price_{level}": value for level, value in valid_ladder.items()},
    }

    row = build_station_role_tracking_row(raw, 30, 3, date(2026, 8, 12))

    assert row["data_status"] == "pending"
    assert row["role_before_code"] == "star"
    assert row["role_after_code"] is None
    assert row["role_change"] == "unavailable"


def test_tracking_row_marks_mature_but_incomplete_source_data(valid_ladder):
    raw = {
        "adjust_date": date(2026, 8, 10),
        "pre_seen_days": 29,
        "post_seen_days": 3,
        **{f"margin_price_{level}": value for level, value in valid_ladder.items()},
    }

    row = build_station_role_tracking_row(raw, 30, 3, date(2026, 8, 17))

    assert row["data_status"] == "source_incomplete"
    assert row["role_change"] == "unavailable"


def test_tracking_row_prefers_remote_pre_role_and_recomputes_three_day_post(valid_ladder):
    raw = {
        "adjust_date": date(2026, 8, 10),
        "pre_seen_days": 14,
        "post_seen_days": 3,
        "pre_sales_qty": 14,
        "post_sales_qty": 12,
        "pre_sales_amount": 140,
        "post_sales_amount": 100,
        "pre_order_profit": 14,
        "post_order_profit": 20,
        "pre_small_rank": 120,
        "post_small_rank": 40,
        **{f"margin_price_{level}": value for level, value in valid_ladder.items()},
    }
    remote_pre = station_sales_role.normalize_remote_role_snapshot(
        {
            "data_date": date(2026, 8, 9),
            "label_period": "14d",
            "label_id": 1302,
            "created_time": datetime(2026, 8, 10, 7, 19),
            "evidence_json": {
                "metrics": {
                    "daily_sales": 2,
                    "sales_amount": 280,
                    "tag_gross_profit": 56,
                    "tag_margin_rate": 20,
                    "small_rank": 80,
                    "small_rank_stat_date": "2026-08-09",
                },
                "rule_version": "v47",
            },
        }
    )

    row = build_station_role_tracking_row(
        raw,
        14,
        3,
        date(2026, 8, 13),
        pre_snapshot=remote_pre,
    )

    assert row["role_before_code"] == "potential"
    assert row["pre_daily_sales"] == Decimal("2")
    assert row["pre_role_source"] == "remote_dws"
    assert row["role_after_code"] == "star"
    assert row["post_role_source"] == "local_recomputed"
    assert row["role_change"] == "up"
