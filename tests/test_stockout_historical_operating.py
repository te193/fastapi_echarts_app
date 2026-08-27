from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services import stockout_historical_operating as historical_operating

from app.services.stockout_historical_operating import (
    _gap_ranges,
    _weekly_metrics,
    classify_country_role,
    classify_historical_level,
    classify_msku_role,
    classify_pre_oos_role_change,
    classify_role_pattern,
    classify_stability,
    build_rolling_role_nodes,
    classify_historical_stability,
    classify_metric_direction,
    classify_recent_trend,
    compose_operating_label,
    evaluate_stockout_history,
    find_current_oos_event,
    select_non_overlapping_windows,
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


def test_current_oos_event_uses_most_recent_continuous_zero_run():
    start = date(2026, 4, 1)
    rows = [_row(start + timedelta(days=index), inventory) for index, inventory in enumerate([12, 0, 0, 2, 0])]

    event = find_current_oos_event(rows, current_date=start + timedelta(days=4))

    assert event["oos_start_date"] == date(2026, 4, 5)
    assert event["oos_start_confidence"] == "complete"


def test_current_oos_event_starts_again_after_any_positive_inventory():
    start = date(2026, 4, 1)
    rows = [_row(start + timedelta(days=index), inventory) for index, inventory in enumerate([12, 0, 1, 0])]

    event = find_current_oos_event(rows, current_date=start + timedelta(days=3))

    assert event["oos_start_date"] == date(2026, 4, 4)
    assert event["one_day_recovery_then_oos"] is True


def test_one_day_recovery_flag_requires_the_previous_oos_day_to_be_contiguous():
    start = date(2026, 4, 1)
    rows = [_row(start, 0), _row(start + timedelta(days=2), 1), _row(start + timedelta(days=3), 0)]

    event = find_current_oos_event(rows, current_date=start + timedelta(days=3))

    assert event["oos_start_date"] == start + timedelta(days=3)
    assert event["one_day_recovery_then_oos"] is False


def test_current_oos_event_without_prior_inventory_above_five_has_incomplete_left_boundary():
    start = date(2026, 1, 1)
    rows = [_row(start + timedelta(days=index), inventory) for index, inventory in enumerate([0, 0, 0])]

    event = find_current_oos_event(rows, current_date=start + timedelta(days=2))

    assert event["oos_start_date"] is None
    assert event["observed_oos_since_date"] == start
    assert event["minimum_current_oos_days"] == 3
    assert event["oos_start_confidence"] == "left_boundary_incomplete"


def test_oos_from_history_left_boundary_has_its_own_evidence_status():
    rows = [_row(date(2026, 1, 1) + timedelta(days=index), 0, sales=0) for index in range(40)]

    result = evaluate_stockout_history(
        rows,
        current_date=date(2026, 2, 9),
        current_gate_status="evaluable",
        scope_mode="business_unit",
        current_oos_confirmed=True,
    )

    assert result["role_evidence_status"] == "oos_start_history_insufficient"
    assert result["combined_label_code"] == "oos_start_history_insufficient"
    assert result["combined_label"] == "断货起点历史不足"
    assert result["inventory_first_observed_date"] == date(2026, 1, 1)


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
        (5.01, 0.151, "star"),
        (5, 0.251, "star"),
        (5, 0.15, "potential"),
        (1, 0.10, "potential"),
        (1, 0.05, "dog"),
        (0.5, 0.051, "dog"),
        (0, None, "problem"),
        (-0.01, 0.20, "problem"),
        (5, 0.0499, "problem"),
    ],
)
def test_msku_role_uses_documented_daily_sales_boundaries(daily_sales, margin, expected):
    assert classify_msku_role(daily_sales, margin) == expected


def test_positive_daily_sales_without_margin_is_data_error():
    with pytest.raises(ValueError, match="日销大于0但毛利率缺失"):
        classify_msku_role(1, None)


def test_nodes_carry_last_role_until_thirty_complete_recovery_days():
    history_start = date(2026, 1, 1)
    rows = [_row(history_start + timedelta(days=index), 10, sales=6) for index in range(33)]
    rows.extend(_row(date(2026, 2, 3) + timedelta(days=index), 0, sales=0) for index in range(4))
    rows.extend(_row(date(2026, 2, 7) + timedelta(days=index), 10, sales=6) for index in range(30))

    nodes = build_rolling_role_nodes(
        rows,
        start_date=history_start,
        end_date=date(2026, 3, 8),
    )
    by_day = {node["node_date"]: node for node in nodes}

    assert by_day[date(2026, 2, 2)]["state"] == "normal"
    assert by_day[date(2026, 2, 3)]["state"] == "carried_oos"
    assert by_day[date(2026, 2, 3)]["source_node_date"] == date(2026, 2, 2)
    assert by_day[date(2026, 3, 7)]["state"] == "recovery_observation"
    assert by_day[date(2026, 3, 8)]["state"] == "normal"
    assert by_day[date(2026, 3, 8)]["source_node_date"] == date(2026, 3, 8)


def test_recovery_counter_resets_when_stockout_recurs_before_day_thirty():
    history_start = date(2026, 1, 1)
    rows = [_row(history_start + timedelta(days=index), 10, sales=6) for index in range(33)]
    rows.extend(_row(date(2026, 2, 3) + timedelta(days=index), 0, sales=0) for index in range(4))
    rows.extend(_row(date(2026, 2, 7) + timedelta(days=index), 10, sales=6) for index in range(29))
    rows.append(_row(date(2026, 3, 8), 0, sales=0))
    rows.extend(_row(date(2026, 3, 9) + timedelta(days=index), 10, sales=6) for index in range(29))

    nodes = build_rolling_role_nodes(
        rows,
        start_date=history_start,
        end_date=date(2026, 4, 6),
    )
    by_day = {node["node_date"]: node for node in nodes}

    assert by_day[date(2026, 3, 8)]["state"] == "carried_oos"
    assert by_day[date(2026, 4, 6)]["state"] == "recovery_observation"


def test_stockout_without_prior_valid_role_is_unavailable():
    rows = [_row(date(2026, 1, 1) + timedelta(days=index), 0, sales=0) for index in range(10)]

    nodes = build_rolling_role_nodes(
        rows,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 10),
    )

    assert nodes[-1]["state"] == "unavailable"
    assert nodes[-1]["role"] == "unavailable"


def _normal_node(day: date, role: str) -> dict:
    return {
        "node_date": day,
        "window_start": day - timedelta(days=29),
        "window_end": day,
        "role": role,
        "state": "normal",
        "source_node_date": day,
        "daily_sales": 6.0,
        "margin_rate": 0.20,
    }


def test_daily_role_change_requires_five_consecutive_normal_nodes():
    first = date(2026, 1, 1)
    nodes = [_normal_node(first + timedelta(days=index), "star") for index in range(10)]
    nodes.extend(_normal_node(first + timedelta(days=10 + index), "potential") for index in range(4))
    nodes.append(_normal_node(first + timedelta(days=14), "star"))
    nodes.extend(_normal_node(first + timedelta(days=15 + index), "potential") for index in range(5))

    selected = historical_operating.select_confirmed_daily_role_nodes(
        nodes, t0=first + timedelta(days=19)
    )

    assert [item["stability_role"] for item in selected[10:15]] == ["star"] * 5
    assert [item["stability_role"] for item in selected[15:20]] == ["potential"] * 5
    assert selected[19]["confirmed_role_change"] is True


def test_carried_and_recovery_nodes_do_not_join_or_count_toward_confirmation():
    first = date(2026, 1, 1)
    nodes = [_normal_node(first + timedelta(days=index), "star") for index in range(5)]
    nodes.extend(_normal_node(first + timedelta(days=5 + index), "potential") for index in range(2))
    nodes.extend(
        {
            **_normal_node(first + timedelta(days=7 + index), "star"),
            "state": state,
        }
        for index, state in enumerate(("carried_oos", "recovery_observation"))
    )
    nodes.extend(_normal_node(first + timedelta(days=9 + index), "potential") for index in range(3))
    nodes.append(
        {
            **_normal_node(first + timedelta(days=12), "star"),
            "state": "carried_oos",
        }
    )
    nodes.extend(_normal_node(first + timedelta(days=13 + index), "potential") for index in range(5))

    selected = historical_operating.select_confirmed_daily_role_nodes(
        nodes, t0=first + timedelta(days=17)
    )

    assert len(selected) == 15
    assert all(item["state"] == "normal" for item in selected)
    assert [item["stability_role"] for item in selected[5:10]] == ["star"] * 5
    assert [item["stability_role"] for item in selected[-5:]] == ["potential"] * 5
    assert sum(item["confirmed_role_change"] for item in selected) == 1


def test_daily_stability_requires_thirty_nodes_across_sixty_calendar_days():
    first = date(2026, 1, 1)
    enough = [
        {**_normal_node(first + timedelta(days=index), "star"), "stability_role": "star"}
        for index in range(15)
    ] + [
        {**_normal_node(first + timedelta(days=60 + index), "star"), "stability_role": "star"}
        for index in range(15)
    ]
    short_count = enough[:-1]
    short_span = [
        {**_normal_node(first + timedelta(days=index), "star"), "stability_role": "star"}
        for index in range(30)
    ]

    stable = classify_historical_stability(enough, reference_role="star")
    insufficient_count = classify_historical_stability(short_count, reference_role="star")
    insufficient_span = classify_historical_stability(short_span, reference_role="star")

    assert stable["historical_stability"] == "stable"
    assert stable["valid_window_count"] == 30
    assert stable["evidence_span_days"] == 75
    assert insufficient_count["historical_stability"] == "insufficient"
    assert insufficient_span["historical_stability"] == "insufficient"


def test_non_overlapping_windows_are_selected_backwards_from_t0():
    first = date(2026, 1, 30)
    nodes = [_normal_node(first + timedelta(days=index), "star") for index in range(91)]

    selected = select_non_overlapping_windows(nodes, t0=date(2026, 4, 30))

    assert [item["window_end"] for item in selected] == [
        date(2026, 1, 30),
        date(2026, 3, 1),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]
    assert all(
        left["window_end"] < right["window_start"]
        for left, right in zip(selected, selected[1:])
    )


def test_carried_t0_traces_to_original_normal_window_once():
    source_day = date(2026, 4, 1)
    nodes = [_normal_node(date(2026, 3, 2), "potential"), _normal_node(source_day, "star")]
    nodes.extend(
        {
            **_normal_node(source_day + timedelta(days=index), "star"),
            "state": "carried_oos",
            "source_node_date": source_day,
        }
        for index in range(1, 31)
    )

    selected = select_non_overlapping_windows(nodes, t0=date(2026, 5, 1))

    assert [item["source_node_date"] for item in selected].count(source_day) == 1
    assert selected[-1]["source_node_date"] == source_day


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["star", "star", "star"], "stable"),
        (["star", "star", "potential"], "light_fluctuation"),
        (["star", "potential", "star"], "volatile"),
    ],
)
def test_historical_stability_uses_share_and_switch_rate(roles, expected):
    first = date(2026, 1, 1)
    windows = [
        {
            **_normal_node(first + timedelta(days=30 * role_index + day_index), role),
            "stability_role": role,
        }
        for role_index, role in enumerate(roles)
        for day_index in range(30)
    ]

    result = classify_historical_stability(windows, reference_role=roles[-1])

    assert result["historical_stability"] == expected


def test_historical_stability_requires_daily_evidence_and_uses_reference_role_for_tie():
    first = date(2026, 1, 1)
    insufficient = classify_historical_stability(
        [
            {**_normal_node(first + timedelta(days=index * 3), "star"), "stability_role": "star"}
            for index in range(29)
        ],
        reference_role="star",
    )
    tied = classify_historical_stability(
        [
            {**_normal_node(first + timedelta(days=index), "star"), "stability_role": "star"}
            for index in range(15)
        ]
        + [
            {
                **_normal_node(first + timedelta(days=60 + index), "potential"),
                "stability_role": "potential",
            }
            for index in range(15)
        ],
        reference_role="potential",
    )

    assert insufficient["historical_stability"] == "insufficient"
    assert tied["dominant_role"] == "potential"


@pytest.mark.parametrize(
    ("values", "kind", "expected"),
    [
        ([1.00, 1.19], "daily_sales", "stable"),
        ([1.00, 1.21], "daily_sales", "improving"),
        ([0.00, 0.19], "daily_sales", "stable"),
        ([0.00, 0.20], "daily_sales", "improving"),
        ([0.10, 0.13], "margin", "stable"),
        ([0.10, 0.1301], "margin", "improving"),
    ],
)
def test_metric_direction_uses_confirmed_thresholds(values, kind, expected):
    assert classify_metric_direction(values, kind=kind) == expected


def test_metric_direction_checks_cumulative_change_and_ignores_small_noise():
    assert classify_metric_direction([1.00, 1.11, 1.23], kind="daily_sales") == "improving"
    assert classify_metric_direction([1.00, 1.05, 0.99], kind="daily_sales") == "stable"
    assert classify_metric_direction([1.00, 1.30, 0.90], kind="daily_sales") == "fluctuating"


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["potential", "potential", "star"], "improving"),
        (["star", "potential", "potential"], "declining"),
        (["star", "potential", "star"], "fluctuating"),
    ],
)
def test_recent_role_trend_has_priority_over_metric_changes(roles, expected):
    windows = [
        {
            **_normal_node(date(2026, 1, 30) + timedelta(days=30 * index), role),
            "daily_sales": 6 + index,
            "margin_rate": 0.20,
        }
        for index, role in enumerate(roles)
    ]

    result = classify_recent_trend(windows)

    assert result["recent_trend"] == expected
    assert result["daily_sales_trend"] is None
    assert result["margin_trend"] is None


def test_same_roles_use_metrics_and_decline_has_priority_over_improvement():
    windows = [
        {**_normal_node(date(2026, 1, 30), "star"), "daily_sales": 6.0, "margin_rate": 0.20},
        {**_normal_node(date(2026, 3, 1), "star"), "daily_sales": 6.5, "margin_rate": 0.18},
        {**_normal_node(date(2026, 3, 31), "star"), "daily_sales": 7.5, "margin_rate": 0.16},
    ]

    trend = classify_recent_trend(windows)
    label = compose_operating_label("star", trend)

    assert trend["daily_sales_trend"] == "improving"
    assert trend["margin_trend"] == "declining"
    assert label["combined_label"] == "明星·毛利下降"
    assert label["auxiliary_metric"] == "日销改善"


def test_same_roles_and_stable_metrics_produce_continuous_stability():
    windows = [
        {
            **_normal_node(date(2026, 1, 30) + timedelta(days=30 * index), "star"),
            "daily_sales": 6.0,
            "margin_rate": 0.20,
        }
        for index in range(3)
    ]

    label = compose_operating_label("star", classify_recent_trend(windows))

    assert label["combined_label"] == "明星·持续稳定"


def test_confirmed_role_model_is_not_blocked_by_legacy_current_gate():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    rows = [_row(history_start + timedelta(days=index), 10, sales=6) for index in range(100)]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="not_evaluable",
        current_gate_reason="legacy_gate",
        scope_mode="business_unit",
    )

    assert result["pre_oos_role"] == "star"
    assert result["combined_label"] == "明星·持续稳定"
    assert sum(node.get("selected_for_stability", False) for node in result["confirmed_role_nodes"]) == result["valid_window_count"]


def test_confirmed_role_model_counts_daily_normal_nodes_but_excludes_stockout_carry():
    history_start = date(2026, 1, 1)
    rows = [_row(history_start + timedelta(days=index), 10, sales=6) for index in range(33)]
    rows.extend(_row(date(2026, 2, 3) + timedelta(days=index), 0, sales=0) for index in range(4))
    rows.extend(_row(date(2026, 2, 7) + timedelta(days=index), 10, sales=6) for index in range(59))
    current_oos = date(2026, 4, 7)
    rows.append(_row(current_oos, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=current_oos,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    selected = [node for node in result["confirmed_role_nodes"] if node.get("selected_for_stability")]
    assert result["valid_window_count"] == 34
    assert len(selected) == 34
    assert all(node["state"] == "normal" for node in selected)
    assert all(node["effective_operating_days"] == 30 for node in selected)
    assert result["confirmed_historical_stability"] == "stable"


def test_pre_oos_history_shorter_than_thirty_days_uses_valid_fourteen_day_role():
    history_start = date(2026, 1, 1)
    oos_start = date(2026, 1, 25)
    rows = [_row(history_start + timedelta(days=index), 10, sales=2) for index in range(24)]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["role_evidence_status"] == "short_period_fallback"
    assert result["combined_label_code"] == "potential.insufficient"
    assert result["combined_label"] == "潜力·趋势依据不足"
    assert result["pre_oos_role"] == "potential"
    assert result["period_roles"]["14d"]["role"] == "potential"
    assert result["historical_evaluable_reason"] == "history_span_lt_90"
    assert result["confirmed_historical_stability"] == "insufficient"


def test_pre_oos_period_excludes_the_stockout_start_day():
    history_start = date(2026, 1, 1)
    oos_start = date(2026, 1, 30)
    rows = [_row(history_start + timedelta(days=index), 10, sales=2) for index in range(29)]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["role_evidence_status"] == "short_period_fallback"
    assert result["combined_label"] == "潜力·趋势依据不足"
    assert result["role_source_date"] == date(2026, 1, 29)


def test_pre_oos_history_without_a_valid_fourteen_day_period_remains_insufficient():
    history_start = date(2026, 1, 1)
    oos_start = date(2026, 1, 10)
    rows = [_row(history_start + timedelta(days=index), 10, sales=2) for index in range(9)]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["role_evidence_status"] == "pre_oos_period_insufficient"
    assert result["combined_label"] == "断货前周期不足"
    assert result["pre_oos_role"] is None


def test_complete_pre_oos_window_with_unusable_margin_remains_data_anomaly():
    history_start = date(2026, 1, 1)
    oos_start = date(2026, 1, 31)
    rows = [_row(history_start + timedelta(days=index), 10, sales=1) for index in range(30)]
    for row in rows:
        row["sales_amount"] = 0
        row["order_gross_profit"] = 0
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["role_evidence_status"] == "data_anomaly"
    assert result["combined_label"] == "数据异常待核实"
    assert result["period_roles"]["14d"]["role"] == "unavailable"
    assert result["period_roles"]["14d"]["reason"] == "positive_sales_margin_missing"


def test_fourteen_day_window_provides_fallback_when_no_standard_role_exists():
    history_start = date(2026, 1, 1)
    rows = [_row(history_start + timedelta(days=index), 10, sales=2, margin=0.20) for index in range(14)]
    rows.extend(_row(date(2026, 1, 15) + timedelta(days=index), 0, sales=0) for index in range(17))
    rows.extend(_row(date(2026, 2, 1) + timedelta(days=index), 10, sales=2, margin=0.20) for index in range(9))
    rows.append(_row(date(2026, 2, 10), 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=date(2026, 2, 10),
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["role_evidence_status"] == "short_period_fallback"
    assert result["pre_oos_role"] == "potential"
    assert result["role_source_date"] == date(2026, 1, 14)
    assert result["valid_window_count"] == 0
    assert result["confirmed_historical_stability"] == "insufficient"
    assert result["combined_label"] == "潜力·趋势依据不足"


def test_thirteen_day_window_does_not_provide_short_period_fallback():
    history_start = date(2026, 1, 1)
    rows = [_row(history_start + timedelta(days=index), 10, sales=2, margin=0.20) for index in range(13)]
    rows.extend(_row(date(2026, 1, 14) + timedelta(days=index), 0, sales=0) for index in range(18))
    rows.extend(_row(date(2026, 2, 1) + timedelta(days=index), 10, sales=2, margin=0.20) for index in range(9))
    rows.append(_row(date(2026, 2, 10), 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=date(2026, 2, 10),
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["role_evidence_status"] == "no_valid_role"
    assert result["pre_oos_role"] is None


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


def test_fourteen_day_role_is_kept_when_historical_stability_gate_fails():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    rows = [
        _row(
            history_start + timedelta(days=index),
            10 if index >= 90 else 0,
            sales=2 if index >= 90 else 0,
        )
        for index in range(100)
    ]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["historical_evaluable_status"] == "stockout_history_only"
    assert result["historical_evaluable_reason"] == "effective_days_or_weeks_insufficient"
    assert result["period_roles"]["14d"]["role"] == "potential"
    assert result["pre_oos_role"] == "potential"
    assert result["role_evidence_status"] == "short_period_fallback"
    assert result["confirmed_historical_stability"] == "insufficient"


def test_seven_day_role_is_visible_but_does_not_become_the_main_role():
    history_start = date(2026, 1, 1)
    oos_start = history_start + timedelta(days=100)
    rows = [
        _row(
            history_start + timedelta(days=index),
            10 if index >= 95 else 0,
            sales=1 if index >= 95 else 0,
        )
        for index in range(100)
    ]
    rows.append(_row(oos_start, 0, sales=0))

    result = evaluate_stockout_history(
        rows,
        current_date=oos_start,
        current_gate_status="evaluable",
        scope_mode="business_unit",
    )

    assert result["historical_evaluable_status"] == "stockout_history_only"
    assert result["period_roles"]["7d"]["role"] == "dog"
    assert result["period_roles"]["14d"]["role"] == "unavailable"
    assert result["pre_oos_role"] is None
    assert result["role_evidence_status"] == "no_valid_role"


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
