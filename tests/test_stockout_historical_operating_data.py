from app.services.stockout_historical_operating_data import (
    build_stockout_historical_summary,
    decorate_stockout_snapshot_status,
    filter_stockout_historical_members,
)


def _result(msku, **overrides):
    row = {
        "scope_mode": "business_unit",
        "country_category": "欧洲",
        "store": "DE店",
        "msku": msku,
        "country": "",
        "current_gate_status": "evaluable",
        "current_gate_reason": "",
        "historical_evaluable_status": "historical_operating_evaluable",
        "historical_evaluable_reason": "all_thresholds_met",
        "historical_operating_level": "good",
        "historical_stability": "basically_stable",
        "historical_role_pattern": "maintained",
        "pre_oos_role_change": "maintained",
        "role_7d": "star",
        "role_14d": "star",
        "role_30d": "potential",
        "role_90d": "potential",
        "low_stock_constrained": 0,
        "inventory_sales_conflict_flag": 0,
        "missing_date_gap_flag": 0,
        "few_selling_days_flag": 0,
        "single_day_concentrated_flag": 0,
        "extreme_single_day_concentrated_flag": 0,
        "event_boundary_incomplete_flag": 0,
        "one_day_recovery_then_oos_flag": 0,
        "rule_version": "v1",
    }
    row.update(overrides)
    return row


def test_summary_uses_current_gate_and_historical_evaluable_denominators_separately():
    rows = [
        _result("A"),
        _result("B", historical_operating_level="excellent", historical_stability="highly_stable"),
        _result(
            "C",
            historical_evaluable_status="stockout_history_only",
            historical_evaluable_reason="effective_days_or_weeks_insufficient",
            historical_operating_level=None,
            historical_stability=None,
        ),
        _result(
            "D",
            current_gate_status="not_evaluable",
            current_gate_reason="low_inventory_edge",
            historical_evaluable_status="historical_evidence_insufficient",
            historical_evaluable_reason="low_inventory_edge",
            historical_operating_level=None,
            historical_stability=None,
        ),
    ]

    payload = build_stockout_historical_summary(rows, scope_mode="business_unit", data_date="2026-08-20")

    assert payload["eligibility_path"] == {
        "current_stockout_count": 4,
        "current_gate_evaluable_count": 3,
        "historical_operating_evaluable_count": 2,
        "stockout_history_only_count": 1,
        "historical_evidence_insufficient_count": 1,
        "exclusion_reasons": [
            {"code": "effective_days_or_weeks_insufficient", "label": "有效经营日或有效周不足", "count": 1, "share": 0.25},
            {"code": "low_inventory_edge", "label": "低量库存边缘断货", "count": 1, "share": 0.25},
        ],
    }
    level = next(item for item in payload["outcomes"] if item["dimension"] == "historical_operating_level")
    assert level["denominator"] == 2
    assert {item["code"]: item["count"] for item in level["items"]}["good"] == 1


def test_quality_flags_are_non_exclusive_and_period_matrix_returns_all_periods():
    rows = [
        _result("A", low_stock_constrained=1, single_day_concentrated_flag=1),
        _result("B", low_stock_constrained=1, inventory_sales_conflict_flag=1, role_7d="dog"),
    ]

    payload = build_stockout_historical_summary(rows, scope_mode="business_unit", data_date="2026-08-20")

    quality = {item["code"]: item["count"] for item in payload["quality_flags"]}
    assert quality["low_stock_constrained"] == 2
    assert quality["single_day_concentrated"] == 1
    assert quality["inventory_sales_conflict"] == 1
    assert [row["period"] for row in payload["period_role_matrix"]] == ["7d", "14d", "30d", "90d"]


def test_member_filter_supports_outcome_quality_and_period_dimensions():
    rows = [
        _result("A", historical_operating_level="excellent", low_stock_constrained=1, role_7d="star"),
        _result("B", historical_operating_level="good", low_stock_constrained=0, role_7d="dog"),
    ]

    assert filter_stockout_historical_members(rows, "historical_operating_level", "excellent") == {("\u6b27\u6d32", "DE\u5e97", "A")}
    assert filter_stockout_historical_members(rows, "quality_flag", "low_stock_constrained") == {("\u6b27\u6d32", "DE\u5e97", "A")}
    assert filter_stockout_historical_members(rows, "period_role", "dog", period="7d") == {("\u6b27\u6d32", "DE\u5e97", "B")}


def test_outcome_and_period_drilldown_exclude_non_evaluable_null_results():
    rows = [
        _result("A", historical_operating_level=None, role_7d=None),
        _result(
            "B",
            historical_evaluable_status="stockout_history_only",
            historical_evaluable_reason="effective_days_or_weeks_insufficient",
            historical_operating_level=None,
            role_7d=None,
        ),
    ]

    assert filter_stockout_historical_members(rows, "historical_operating_level", "unavailable") == {
        ("欧洲", "DE店", "A")
    }
    assert filter_stockout_historical_members(rows, "period_role", "unavailable", period="7d") == {
        ("欧洲", "DE店", "A")
    }


def test_snapshot_status_distinguishes_empty_snapshot_from_lagging_daily_result():
    payload = build_stockout_historical_summary([], scope_mode="business_unit", data_date="2026-08-21")

    decorated = decorate_stockout_snapshot_status(
        payload,
        requested_data_date="2026-08-21",
        latest_result_date="2026-08-20",
        source_data_date="2026-08-21",
    )

    assert decorated["snapshot_status"] == "no_snapshot"
    assert decorated["result_data_date"] == ""
    assert decorated["latest_result_date"] == "2026-08-20"
    assert decorated["is_data_lagging"] is True


def test_all_runtime_exclusion_reasons_have_chinese_labels():
    payload = build_stockout_historical_summary(
        [
            _result(
                "A",
                historical_evaluable_status="historical_evidence_insufficient",
                historical_evaluable_reason="not_current_oos",
            )
        ],
        scope_mode="business_unit",
        data_date="2026-08-20",
    )

    assert payload["eligibility_path"]["exclusion_reasons"][0]["label"] == "经营日表当日库存与断货标签不一致"


def test_summary_exposes_exact_v2_rules_for_hover_cards():
    payload = build_stockout_historical_summary(
        [
            _result(
                "A",
                historical_operating_level="excellent",
                historical_stability="highly_stable",
                historical_role_pattern="maintained",
                pre_oos_role_change="upgraded_30d",
                low_stock_constrained=1,
                role_7d="star",
            )
        ],
        scope_mode="business_unit",
        data_date="2026-08-20",
    )

    outcomes = {
        outcome["dimension"]: {item["code"]: item for item in outcome["items"]}
        for outcome in payload["outcomes"]
    }
    quality = {item["code"]: item for item in payload["quality_flags"]}
    period_7d = next(row for row in payload["period_role_matrix"] if row["period"] == "7d")
    roles = {item["code"]: item for item in period_7d["items"]}

    assert "明星节点占比≥60%" in outcomes["historical_operating_level"]["excellent"]["rule_description"]
    assert "角色、销量、利润三项均稳定" in outcomes["historical_stability"]["highly_stable"]["rule_description"]
    assert "主导角色占比≥70%" in outcomes["historical_role_pattern"]["maintained"]["rule_description"]
    assert "A≥B≥C 且 A>C" in outcomes["pre_oos_role_change"]["upgraded_30d"]["rule_description"]
    assert quality["low_stock_constrained"]["rule_description"] == "历史有效经营日中，FBA 库存 1–5 的天数占比≥30%。"
    assert "7天窗口有效经营日至少5天" in roles["star"]["rule_description"]
    assert "角色日销＝周期总销量÷7天" in roles["star"]["rule_description"]
    assert "角色日销≥5且利润率≥15%" in roles["star"]["rule_description"]


def test_operating_overview_counts_quality_stability_intersection_and_risk_separately():
    rows = [
        _result("A", historical_operating_level="excellent", historical_stability="highly_stable"),
        _result("B", historical_operating_level="good", historical_stability="volatile"),
        _result("C", historical_operating_level="normal", historical_stability="basically_stable"),
        _result("D", historical_operating_level="poor", historical_stability="highly_volatile"),
        _result(
            "E",
            historical_evaluable_status="historical_evidence_insufficient",
            historical_operating_level=None,
            historical_stability=None,
        ),
    ]

    payload = build_stockout_historical_summary(rows, scope_mode="business_unit", data_date="2026-08-20")
    overview = {item["code"]: item for item in payload["operating_overview"]["items"]}

    assert payload["operating_overview"]["denominator"] == 4
    assert {code: item["count"] for code, item in overview.items()} == {
        "quality": 2,
        "stable": 2,
        "quality_stable": 1,
        "risk": 1,
    }
    assert overview["quality"]["label"] == "断货前经营优质"
    assert overview["quality_stable"]["label"] == "优质且稳定"


def test_operating_overview_drilldown_uses_the_same_intersection_definitions_as_summary():
    rows = [
        _result("A", historical_operating_level="excellent", historical_stability="highly_stable"),
        _result("B", historical_operating_level="good", historical_stability="volatile"),
        _result("C", historical_operating_level="normal", historical_stability="basically_stable"),
        _result("D", historical_operating_level="loss", historical_stability="highly_volatile"),
    ]

    assert filter_stockout_historical_members(rows, "operating_overview", "quality") == {
        ("欧洲", "DE店", "A"),
        ("欧洲", "DE店", "B"),
    }
    assert filter_stockout_historical_members(rows, "operating_overview", "stable") == {
        ("欧洲", "DE店", "A"),
        ("欧洲", "DE店", "C"),
    }
    assert filter_stockout_historical_members(rows, "operating_overview", "quality_stable") == {
        ("欧洲", "DE店", "A")
    }
    assert filter_stockout_historical_members(rows, "operating_overview", "risk") == {
        ("欧洲", "DE店", "D")
    }


def test_primary_diagnosis_is_mutually_exclusive_and_reconciles_to_all_stockouts():
    rows = [
        _result("A", historical_operating_level="excellent", historical_stability="highly_stable"),
        _result("B", historical_operating_level="good", historical_stability="volatile"),
        _result("C", historical_operating_level="poor", historical_stability="basically_stable"),
        _result("D", historical_operating_level="normal", historical_stability="highly_stable"),
        _result("E", historical_operating_level="normal", historical_stability="volatile"),
        _result(
            "F",
            historical_evaluable_status="stockout_history_only",
            historical_evaluable_reason="effective_days_or_weeks_insufficient",
        ),
        _result(
            "G",
            current_gate_status="not_evaluable",
            current_gate_reason="low_inventory_edge",
            historical_evaluable_status="historical_evidence_insufficient",
            historical_evaluable_reason="low_inventory_edge",
        ),
    ]

    payload = build_stockout_historical_summary(rows, scope_mode="business_unit", data_date="2026-08-20")
    diagnosis = payload["primary_diagnosis"]
    counts = {item["code"]: item["count"] for item in diagnosis["items"]}

    assert diagnosis["denominator"] == 7
    assert diagnosis["reconciled_count"] == 7
    assert diagnosis["is_reconciled"] is True
    assert counts == {
        "quality_stable": 1,
        "quality_non_stable": 1,
        "operating_risk": 1,
        "stable_base": 1,
        "watch": 1,
        "history_insufficient": 1,
        "gate_not_passed": 1,
    }


def test_period_roles_and_quality_stability_matrix_expose_complete_denominators():
    rows = [
        _result("A", historical_operating_level="excellent", historical_stability="highly_stable", role_30d="star"),
        _result("B", historical_operating_level="poor", historical_stability="volatile", role_30d="problem"),
        _result(
            "C",
            historical_evaluable_status="stockout_history_only",
            historical_evaluable_reason="history_span_lt_90",
        ),
        _result(
            "D",
            current_gate_status="not_evaluable",
            historical_evaluable_status="historical_evidence_insufficient",
            historical_evaluable_reason="low_inventory_edge",
        ),
    ]

    payload = build_stockout_historical_summary(rows, scope_mode="business_unit", data_date="2026-08-20")
    period_30d = next(item for item in payload["period_role_matrix"] if item["period"] == "30d")
    role_counts = {item["code"]: item["count"] for item in period_30d["items"]}

    assert period_30d["denominator"] == 4
    assert sum(role_counts.values()) == 4
    assert role_counts["star"] == 1
    assert role_counts["problem"] == 1
    assert role_counts["history_insufficient"] == 1
    assert role_counts["gate_not_passed"] == 1
    matrix = payload["quality_stability_matrix"]
    assert matrix["denominator"] == 2
    assert sum(cell["count"] for cell in matrix["cells"]) == 2


def test_primary_diagnosis_and_full_period_role_drilldowns_use_the_same_members():
    rows = [
        _result("A", historical_operating_level="excellent", historical_stability="highly_stable"),
        _result(
            "B",
            historical_evaluable_status="stockout_history_only",
            historical_evaluable_reason="history_span_lt_90",
        ),
        _result(
            "C",
            current_gate_status="not_evaluable",
            historical_evaluable_status="historical_evidence_insufficient",
            historical_evaluable_reason="low_inventory_edge",
        ),
    ]

    assert filter_stockout_historical_members(rows, "primary_diagnosis", "quality_stable") == {
        ("欧洲", "DE店", "A")
    }
    assert filter_stockout_historical_members(rows, "quality_stability", "quality|stable") == {
        ("欧洲", "DE店", "A")
    }
    assert filter_stockout_historical_members(rows, "period_role", "history_insufficient", period="30d") == {
        ("欧洲", "DE店", "B")
    }
    assert filter_stockout_historical_members(rows, "period_role", "gate_not_passed", period="30d") == {
        ("欧洲", "DE店", "C")
    }


def test_action_queue_reconciles_to_all_stockouts_and_exposes_child_distributions():
    rows = [
        _result("A", historical_operating_level="excellent", historical_stability="highly_stable", role_30d="star"),
        _result("B", historical_operating_level="good", historical_stability="volatile", role_30d="potential"),
        _result("C", historical_operating_level="poor", historical_stability="highly_volatile", role_30d="problem"),
        _result("D", historical_operating_level="normal", historical_stability="basically_stable", role_30d="dog"),
        _result("E", historical_operating_level="normal", historical_stability="volatile", role_30d="dog"),
        _result(
            "F",
            historical_evaluable_status="stockout_history_only",
            historical_evaluable_reason="history_span_lt_90",
        ),
        _result(
            "G",
            current_gate_status="not_evaluable",
            current_gate_reason="low_inventory_edge",
            historical_evaluable_status="historical_evidence_insufficient",
            historical_evaluable_reason="low_inventory_edge",
        ),
    ]

    payload = build_stockout_historical_summary(rows, scope_mode="business_unit", data_date="2026-08-20")
    queue = payload["action_queue"]
    by_code = {item["code"]: item for item in queue["items"]}

    assert queue["denominator"] == 7
    assert queue["reconciled_count"] == 7
    assert queue["is_reconciled"] is True
    assert {code: item["count"] for code, item in by_code.items()} == {
        "priority_recovery": 1,
        "review_recovery": 1,
        "cautious_recovery": 1,
        "observe": 2,
        "unassessable": 2,
    }
    priority_groups = {group["dimension"]: group for group in by_code["priority_recovery"]["child_groups"]}
    assert sum(item["count"] for item in priority_groups["historical_operating_level"]["items"]) == 1
    assert sum(item["count"] for item in priority_groups["historical_stability"]["items"]) == 1
    assert sum(item["count"] for item in priority_groups["period_role"]["periods"]["30d"]) == 1
    assert priority_groups["quality_flag"]["is_mutually_exclusive"] is False


def test_action_queue_drilldown_uses_the_same_operational_combinations_as_summary():
    rows = [
        _result("A", historical_operating_level="excellent", historical_stability="highly_stable"),
        _result("B", historical_operating_level="good", historical_stability="volatile"),
        _result("C", historical_operating_level="loss", historical_stability="basically_stable"),
        _result("D", historical_operating_level="normal", historical_stability="volatile"),
        _result(
            "E",
            historical_evaluable_status="stockout_history_only",
            historical_evaluable_reason="history_span_lt_90",
        ),
    ]

    assert filter_stockout_historical_members(rows, "action_queue", "priority_recovery") == {
        ("欧洲", "DE店", "A")
    }
    assert filter_stockout_historical_members(rows, "action_queue", "review_recovery") == {
        ("欧洲", "DE店", "B")
    }
    assert filter_stockout_historical_members(rows, "action_queue", "cautious_recovery") == {
        ("欧洲", "DE店", "C")
    }
    assert filter_stockout_historical_members(rows, "action_queue", "observe") == {
        ("欧洲", "DE店", "D")
    }
    assert filter_stockout_historical_members(rows, "action_queue", "unassessable") == {
        ("欧洲", "DE店", "E")
    }


def test_priority_recovery_requires_a_healthy_30d_role_without_recent_downgrade():
    rows = [
        _result("A", role_30d="potential", pre_oos_role_change="maintained"),
        _result("B", role_30d="dog", pre_oos_role_change="maintained"),
        _result("C", role_30d="problem", pre_oos_role_change="maintained"),
        _result("D", role_30d="unavailable", pre_oos_role_change="unavailable"),
        _result("E", role_30d="star", pre_oos_role_change="downgraded_30d"),
        _result("F", role_30d="potential", pre_oos_role_change="stopped_7d"),
    ]

    payload = build_stockout_historical_summary(
        rows,
        scope_mode="business_unit",
        data_date="2026-08-23",
    )
    queue_counts = {
        item["code"]: item["count"]
        for item in payload["action_queue"]["items"]
    }

    assert queue_counts["priority_recovery"] == 1
    assert queue_counts["review_recovery"] == 5
    assert filter_stockout_historical_members(
        rows,
        "action_queue",
        "priority_recovery",
    ) == {("欧洲", "DE店", "A")}
    assert filter_stockout_historical_members(
        rows,
        "action_queue",
        "review_recovery",
    ) == {
        ("欧洲", "DE店", "B"),
        ("欧洲", "DE店", "C"),
        ("欧洲", "DE店", "D"),
        ("欧洲", "DE店", "E"),
        ("欧洲", "DE店", "F"),
    }
    assert payload["action_queue"]["reconciled_count"] == 6
    assert payload["action_queue"]["is_reconciled"] is True


def test_star_and_potential_products_expose_one_recovery_gap_reason_each():
    rows = [
        _result("A", role_30d="star", historical_stability="volatile"),
        _result("B", role_30d="potential", pre_oos_role_change="downgraded_30d"),
        _result("C", role_30d="star", historical_operating_level="poor"),
        _result(
            "D",
            role_30d="potential",
            historical_operating_level="normal",
            historical_stability="basically_stable",
        ),
        _result(
            "E",
            role_30d="star",
            current_gate_status="not_evaluable",
            current_gate_reason="low_inventory_edge",
            historical_evaluable_status="historical_evidence_insufficient",
            historical_evaluable_reason="low_inventory_edge",
        ),
        _result(
            "F",
            role_30d="potential",
            historical_evaluable_status="stockout_history_only",
            historical_evaluable_reason="history_span_lt_90",
        ),
        _result("G", role_30d="star"),
        _result("H", role_30d="dog", historical_operating_level="poor"),
    ]

    payload = build_stockout_historical_summary(rows, scope_mode="business_unit", data_date="2026-08-23")
    queue = {item["code"]: item for item in payload["action_queue"]["items"]}

    expected = {
        "review_recovery": {"stability_insufficient": 1, "recent_role_deterioration": 1},
        "cautious_recovery": {"historical_operating_risk": 1},
        "observe": {"historical_quality_insufficient": 1},
        "unassessable": {"current_gate_not_passed": 1, "historical_evidence_insufficient": 1},
    }
    for queue_code, expected_reasons in expected.items():
        gap = queue[queue_code]["recovery_gap"]
        reason_counts = {
            item["reason_code"]: item["count"]
            for role in gap["roles"]
            for item in role["reasons"]
        }
        assert reason_counts == expected_reasons
        assert gap["denominator"] == sum(role["count"] for role in gap["roles"])
        assert gap["reconciled_count"] == gap["denominator"]
        assert gap["is_reconciled"] is True

    assert queue["priority_recovery"]["recovery_gap"]["denominator"] == 0


def test_recovery_gap_drilldown_matches_the_role_and_primary_reason():
    rows = [
        _result("A", role_30d="star", historical_stability="volatile"),
        _result("B", role_30d="star", pre_oos_role_change="downgraded_30d"),
        _result("C", role_30d="potential", historical_stability="volatile"),
        _result("D", role_30d="dog", historical_stability="volatile"),
    ]

    assert filter_stockout_historical_members(
        rows,
        "recovery_gap",
        "review_recovery|star|stability_insufficient",
    ) == {("欧洲", "DE店", "A")}
    assert filter_stockout_historical_members(
        rows,
        "recovery_gap",
        "review_recovery|star|recent_role_deterioration",
    ) == {("欧洲", "DE店", "B")}
