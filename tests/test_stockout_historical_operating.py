from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.stockout_historical_operating import (
    _gap_ranges,
    _weekly_metrics,
    classify_country_role,
    classify_historical_level,
    classify_msku_role,
    classify_pre_oos_role_change,
    classify_role_pattern,
    classify_stability,
    evaluate_stockout_history,
    find_current_oos_event,
)


def _row(day: date, inventory: float | None, sales: float = 1, margin: float = 0.2) -> dict:
    amount = sales * 10
    return {
        "dt_date": day,
        "fba_available": inventory,
        "sales_qty": sales,
        "sales_amount": amount,
        "order_gross_profit": amount * margin,
        "ranking": 20,
    }


def test_current_oos_event_keeps_inventory_one_to_five_inside_same_event():
    start = date(2026, 4, 1)
    rows = [_row(start + timedelta(days=index), inventory) for index, inventory in enumerate([12, 0, 3, 2, 0])]

    event = find_current_oos_event(rows, current_date=start + timedelta(days=4))

    assert event["oos_start_date"] == date(2026, 4, 2)
    assert event["oos_start_confidence"] == "complete"


def test_current_oos_event_starts_again_after_inventory_above_five():
    start = date(2026, 4, 1)
    rows = [_row(start + timedelta(days=index), inventory) for index, inventory in enumerate([12, 0, 7, 0])]

    event = find_current_oos_event(rows, current_date=start + timedelta(days=3))

    assert event["oos_start_date"] == date(2026, 4, 4)
    assert event["one_day_recovery_then_oos"] is True


def test_one_day_recovery_flag_requires_the_previous_oos_day_to_be_contiguous():
    start = date(2026, 4, 1)
    rows = [_row(start, 0), _row(start + timedelta(days=2), 7), _row(start + timedelta(days=3), 0)]

    event = find_current_oos_event(rows, current_date=start + timedelta(days=3))

    assert event["oos_start_date"] == start + timedelta(days=3)
    assert event["one_day_recovery_then_oos"] is False


def test_current_oos_event_without_prior_inventory_above_five_has_incomplete_left_boundary():
    start = date(2026, 1, 1)
    rows = [_row(start + timedelta(days=index), inventory) for index, inventory in enumerate([0, 2, 0])]

    event = find_current_oos_event(rows, current_date=start + timedelta(days=2))

    assert event["oos_start_date"] is None
    assert event["observed_oos_since_date"] == start
    assert event["minimum_current_oos_days"] == 3
    assert event["oos_start_confidence"] == "left_boundary_incomplete"


def test_current_oos_event_is_incomplete_when_a_day_is_missing_after_first_zero():
    start = date(2026, 4, 1)
    rows = [
        _row(start, 8),
        _row(start + timedelta(days=1), 0),
        _row(start + timedelta(days=3), 0),
    ]

    event = find_current_oos_event(rows, current_date=start + timedelta(days=3))

    assert event["oos_start_date"] is None
    assert event["oos_start_confidence"] == "event_boundary_incomplete"


@pytest.mark.parametrize(
    ("daily_sales", "margin", "expected"),
    [
        (5, 0.15, "star"),
        (1, 0.25, "star"),
        (5, 0.05, "potential"),
        (1, 0.10, "potential"),
        (1, 0.05, "dog"),
        (0.5, 0.05, "dog"),
        (0, None, "in_stock_zero_sales"),
        (5, 0.0499, "problem"),
    ],
)
def test_msku_role_uses_documented_daily_sales_boundaries(daily_sales, margin, expected):
    assert classify_msku_role(daily_sales, margin) == expected


def test_period_role_uses_total_sales_divided_by_fixed_calendar_days():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    rows = []
    for index in range(100):
        in_last_thirty = index >= 70
        inventory = 0 if 70 <= index <= 78 else 10
        sales = 1 if in_last_thirty and inventory > 0 else 0
        rows.append(_row(history_start + timedelta(days=index), inventory, sales=sales))
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    role = result["period_roles"]["30d"]
    assert role["sales_qty"] == 21
    assert role["in_stock_daily_sales"] == 1
    assert role["natural_daily_sales"] == pytest.approx(0.7)
    assert role["role_daily_sales"] == pytest.approx(0.7)
    assert role["role_daily_sales_basis"] == "calendar_period_days"
    assert role["role"] == "dog"


def test_period_role_keeps_zero_inventory_sales_in_calendar_daily_sales_and_flags_conflict():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    rows = []
    for index in range(100):
        inventory = 0 if 70 <= index <= 78 else 10
        sales = 1 if 70 <= index <= 78 else 0
        rows.append(_row(history_start + timedelta(days=index), inventory, sales=sales))
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    role = result["period_roles"]["30d"]
    assert role["sales_qty"] == 9
    assert role["natural_daily_sales"] == pytest.approx(0.3)
    assert role["role"] == "dog"
    assert result["inventory_sales_conflict_days"] == 9


def test_weekly_sales_stability_uses_week_sales_divided_by_seven_calendar_days():
    monday = date(2026, 1, 5)
    rows = [
        _row(monday + timedelta(days=index), 10 if index < 3 else 0, sales=7 if index < 3 else 0)
        for index in range(7)
    ]

    metrics = _weekly_metrics(rows)

    assert len(metrics["effective_weeks"]) == 1
    assert metrics["effective_weeks"][0]["effective_days"] == 3
    assert metrics["effective_weeks"][0]["calendar_days"] == 7
    assert metrics["effective_weeks"][0]["daily_sales"] == 3


@pytest.mark.parametrize(
    ("daily_sales", "margin", "rank", "expected", "rank_status"),
    [
        (3.01, 0.15, 50, "star", "valid"),
        (1, 0.25, 50, "star", "valid"),
        (3.01, 0.10, 100, "potential", "valid"),
        (3.01, 0.15, 51, "potential", "valid"),
        (0.5, 0.05, 101, "dog", "valid"),
        (1, 0.20, None, "problem", "missing"),
        (1, 0.20, 99999, "problem", "gte_99999"),
    ],
)
def test_country_role_uses_last_effective_day_rank_and_invalid_rank_reason(
    daily_sales, margin, rank, expected, rank_status
):
    result = classify_country_role(daily_sales, margin, rank)

    assert result["role"] == expected
    assert result["rank_status"] == rank_status


def test_history_eligibility_hits_exact_span_coverage_day_and_week_thresholds():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=90)
    distributed_days = [
        index for index in range(89)
        if (history_start + timedelta(days=index)).weekday() < 3
    ][:29]
    rows = []
    for index in range(90):
        day = history_start + timedelta(days=index)
        inventory = 10 if index in distributed_days or index == 89 else 0
        rows.append(_row(day, inventory))
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["history_span_days"] == 90
    assert result["daily_coverage_rate"] == 1
    assert result["effective_operating_days"] == 30
    assert result["effective_operating_weeks"] >= 8
    assert result["historical_evaluable_status"] == "historical_operating_evaluable"


@pytest.mark.parametrize(
    ("observed_days", "expected_status", "expected_reason"),
    [
        (80, "historical_operating_evaluable", "all_thresholds_met"),
        (79, "historical_evidence_insufficient", "daily_coverage_lt_80pct"),
    ],
)
def test_history_coverage_uses_exact_eighty_percent_boundary(observed_days, expected_status, expected_reason):
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    first_observed = 100 - observed_days
    rows = [_row(history_start + timedelta(days=index), 10) for index in range(first_observed, 100)]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(rows, current_date=oos_start, current_gate_status="evaluable", scope_mode="business_unit")

    assert result["daily_coverage_rate"] == observed_days / 100
    assert result["historical_evaluable_status"] == expected_status
    assert result["historical_evaluable_reason"] == expected_reason


def test_history_requires_thirty_effective_days_and_eight_effective_weeks():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    effective_indices = set(range(28)) | {99}
    rows = [
        _row(history_start + timedelta(days=index), 10 if index in effective_indices else 0)
        for index in range(100)
    ]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(rows, current_date=oos_start, current_gate_status="evaluable", scope_mode="business_unit")

    assert result["effective_operating_days"] == 29
    assert result["historical_evaluable_status"] == "stockout_history_only"

    early_weeks = {}
    for index in range(90):
        iso = (history_start + timedelta(days=index)).isocalendar()
        early_weeks.setdefault((iso.year, iso.week), []).append(index)
    target_counts = (4, 5, 5, 5, 4, 4)
    seven_week_indices = {
        index
        for indices, count in zip(list(early_weeks.values())[:6], target_counts)
        for index in indices[:count]
    } | {97, 98, 99}
    rows = [
        _row(history_start + timedelta(days=index), 10 if index in seven_week_indices else 0)
        for index in range(100)
    ]
    rows.append(_row(oos_start, 0, sales=0))
    result = evaluate_stockout_history(rows, current_date=oos_start, current_gate_status="evaluable", scope_mode="business_unit")

    assert result["effective_operating_days"] == 30
    assert result["effective_operating_weeks"] == 7
    assert result["historical_evaluable_status"] == "stockout_history_only"


def test_history_with_good_coverage_but_few_operating_days_is_stockout_history_only():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    rows = [_row(history_start + timedelta(days=index), 10 if index < 10 or index == 99 else 0) for index in range(100)]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["historical_evaluable_status"] == "stockout_history_only"
    assert result["historical_operating_level"] is None


def test_gap_evidence_includes_window_start_and_end_boundaries():
    history_start = date(2026, 1, 1)
    window_end = history_start + timedelta(days=99)
    rows = [_row(history_start + timedelta(days=index), 10) for index in range(1, 99)]

    gaps = _gap_ranges(
        rows,
        window_start=history_start,
        window_end=window_end,
    )

    assert gaps == [
        {"start": "2026-01-01", "end": "2026-01-01", "days": 1},
        {"start": "2026-04-10", "end": "2026-04-10", "days": 1},
    ]


def test_zero_sales_history_is_not_mislabelled_as_sales_concentration():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    rows = [_row(history_start + timedelta(days=index), 10, sales=0) for index in range(100)]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["sales_concentration_flags"]["few_selling_days"] is False


@pytest.mark.parametrize(
    ("daily_sales", "single_day", "extreme"),
    [([5, 5], True, False), ([8, 2], True, True)],
)
def test_sales_concentration_uses_exact_fifty_and_eighty_percent_boundaries(daily_sales, single_day, extreme):
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    rows = [_row(history_start + timedelta(days=index), 10, sales=0) for index in range(100)]
    for index, sales in enumerate(daily_sales):
        rows[index] = _row(history_start + timedelta(days=index), 10, sales=sales)
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(rows, current_date=oos_start, current_gate_status="evaluable", scope_mode="business_unit")

    assert result["sales_concentration_flags"]["single_day_concentrated"] is single_day
    assert result["sales_concentration_flags"]["extreme_single_day_concentrated"] is extreme


def test_inventory_sales_conflict_and_low_stock_are_kept_as_non_overwriting_quality_evidence():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    rows = []
    for index in range(100):
        inventory = 3 if index < 30 else 10
        rows.append(_row(history_start + timedelta(days=index), inventory))
    rows[50] = _row(history_start + timedelta(days=50), 0, sales=4)
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["inventory_sales_conflict_days"] == 1
    assert result["inventory_sales_conflict_qty"] == 4
    assert result["low_stock_constrained"] is True
    assert result["historical_evaluable_status"] == "historical_operating_evaluable"


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        ({"valid_node_count": 8, "in_stock_zero_sales_share": 0.60, "historical_margin_rate": None}, "in_stock_zero_sales"),
        ({"valid_node_count": 8, "in_stock_zero_sales_share": 0, "historical_margin_rate": -0.001}, "loss"),
        ({"valid_node_count": 8, "in_stock_zero_sales_share": 0, "historical_margin_rate": 0.04}, "poor"),
        ({"valid_node_count": 8, "star_role_share": 0.60, "quality_role_share": 0.80, "problem_role_share": 0.1, "historical_margin_rate": 0.15}, "excellent"),
        ({"valid_node_count": 8, "quality_role_share": 0.60, "problem_role_share": 0.24, "historical_margin_rate": 0.05}, "good"),
        ({"valid_node_count": 8, "quality_role_share": 0.50, "problem_role_share": 0.30, "historical_margin_rate": 0.10}, "normal"),
        ({"valid_node_count": 7}, "unavailable"),
    ],
)
def test_historical_level_uses_documented_priority(metrics, expected):
    assert classify_historical_level(metrics) == expected


@pytest.mark.parametrize(
    ("role", "sales", "margin", "expected"),
    [
        ("stable", "stable", "stable", "highly_stable"),
        ("stable", "stable", "normal", "basically_stable"),
        ("high", "stable", "stable", "highly_volatile"),
        ("normal", "high", "high", "highly_volatile"),
        ("normal", "stable", "normal", "volatile"),
    ],
)
def test_final_stability_combines_three_transparent_subresults(role, sales, margin, expected):
    assert classify_stability(role, sales, margin) == expected


def test_role_pattern_prioritizes_repeated_switching_over_dominant_role():
    result = classify_role_pattern(
        ["star", "star", "potential", "potential", "star", "star", "dog", "dog", "star", "star"]
    )

    assert result["code"] == "repeated_switching"


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ({"a": "in_stock_zero_sales", "b": "potential", "c": "potential", "d": "dog"}, "stopped_7d"),
        ({"a": "star", "b": "in_stock_zero_sales", "c": "dog", "d": "problem"}, "started_7d"),
        ({"a": "star", "b": "potential", "c": "dog", "d": "problem"}, "upgraded_90d"),
        ({"a": "problem", "b": "dog", "c": "potential", "d": "star"}, "downgraded_90d"),
        ({"a": "potential", "b": "potential", "c": "potential", "d": "star"}, "maintained"),
    ],
)
def test_pre_oos_role_change_uses_non_overlapping_segments_and_priority(roles, expected):
    assert classify_pre_oos_role_change(roles) == expected
