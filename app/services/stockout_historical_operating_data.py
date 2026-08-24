from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from .stockout_historical_operating import (
    HISTORICAL_LEVEL_LABELS,
    PRE_OOS_CHANGE_LABELS,
    ROLE_LABELS,
    ROLE_PATTERN_LABELS,
    STABILITY_LABELS,
)


RESULT_TABLE = "etl_datasync_test.dashboard_stockout_historical_operating_snapshot"
PERIODS = ("7d", "14d", "30d", "90d")
OPERATING_QUALITY_LEVELS = frozenset({"excellent", "good"})
OPERATING_STABLE_LEVELS = frozenset({"highly_stable", "basically_stable"})
OPERATING_RISK_LEVELS = frozenset({"in_stock_zero_sales", "loss", "poor"})
RECENT_RECOVERY_QUALITY_ROLES = frozenset({"star", "potential"})
RECENT_RECOVERY_BLOCKING_CHANGES = frozenset(
    {"stopped_7d", "downgraded_7d", "downgraded_30d", "downgraded_90d"}
)
RECOVERY_GAP_REASON_DEFINITIONS = {
    "stability_insufficient": (
        "历史稳定性不足",
        "历史表现达到良好或优秀，但综合稳定性为波动或高度波动。",
    ),
    "recent_role_deterioration": (
        "临近断货角色退化",
        "历史表现和稳定性达标，但断货前命中近7天停滞或7/30/90天退化保护。",
    ),
    "historical_operating_risk": (
        "历史经营存在风险",
        "当前30天角色较好，但历史经营等级仍为有货无销量、亏损或较差。",
    ),
    "historical_quality_insufficient": (
        "历史表现未达良好",
        "当前30天角色较好，但历史经营等级尚未达到优秀或良好。",
    ),
    "current_gate_not_passed": (
        "未通过评价门槛",
        "当前评价门槛未通过，需要先核查库存边缘状态或现有评价证据。",
    ),
    "historical_evidence_insufficient": (
        "历史证据不足",
        "历史跨度、覆盖率、有效经营日或有效周尚不足以形成历史经营结论。",
    ),
}
PRIMARY_DIAGNOSIS_DEFINITIONS = (
    ("quality_stable", "优质稳定", "优先恢复库存，检查断货损失"),
    ("quality_non_stable", "优质非稳定", "优先复核近期趋势，再确定补货量"),
    ("operating_risk", "经营风险", "谨慎补货，先处理亏损、零销量或经营较差问题"),
    ("stable_base", "稳定基础盘", "按常规节奏恢复并持续观察"),
    ("watch", "常规待观察", "结合利润和近期销量复核"),
    ("history_insufficient", "历史证据不足", "检查历史覆盖、断档和有效经营日"),
    ("gate_not_passed", "门槛未通过", "检查低库存边缘断货及当前评价条件"),
)
ACTION_QUEUE_DEFINITIONS = (
    ("priority_recovery", "优先恢复候选", "历史表现较好且稳定，近期角色健康", "优先检查补货与恢复条件", "priority"),
    ("review_recovery", "复核后恢复", "历史表现较好，但稳定性或近期角色需复核", "先复核近期趋势，再确定补货量", "review"),
    ("cautious_recovery", "谨慎恢复", "存在零销量、亏损或历史经营较差", "先处理经营问题，不建议盲目补货", "risk"),
    ("observe", "普通观察", "暂未发现明显优势或风险", "按常规节奏处理并持续观察", "neutral"),
    ("unassessable", "暂不可判断", "历史证据不足或未通过评价门槛", "先核查数据、库存与评价条件", "unknown"),
)
FULL_POPULATION_STATUS_DEFINITIONS = (
    ("history_insufficient", "历史证据不足"),
    ("gate_not_passed", "门槛未通过"),
)
OPERATING_OVERVIEW_DEFINITIONS = (
    ("quality", "断货前经营优质", "历史经营等级为优秀或良好。"),
    ("stable", "断货前经营稳定", "历史经营稳定性为高度稳定或基本稳定。"),
    ("quality_stable", "优质且稳定", "同时命中断货前经营优质与断货前经营稳定。"),
    ("risk", "经营风险", "历史经营等级为有货无销量、亏损或较差。"),
)
OUTCOME_DEFINITIONS = (
    ("historical_operating_level", "历史经营等级", HISTORICAL_LEVEL_LABELS),
    ("historical_stability", "历史经营稳定性", STABILITY_LABELS),
    ("historical_role_pattern", "历史角色形态", ROLE_PATTERN_LABELS),
    ("pre_oos_role_change", "断货前角色变化", PRE_OOS_CHANGE_LABELS),
)
QUALITY_DEFINITIONS = (
    ("low_stock_constrained", "low_stock_constrained", "历史经营受低库存约束"),
    ("inventory_sales_conflict", "inventory_sales_conflict_flag", "库存为0但存在销量"),
    ("missing_date_gap", "missing_date_gap_flag", "历史日期存在缺口"),
    ("few_selling_days", "few_selling_days_flag", "销量集中在极少日期"),
    ("single_day_concentrated", "single_day_concentrated_flag", "最高单日销量占比达50%"),
    ("extreme_single_day_concentrated", "extreme_single_day_concentrated_flag", "最高单日销量占比达80%"),
    ("event_boundary_incomplete", "event_boundary_incomplete_flag", "断货事件边界不完整"),
    ("one_day_recovery_then_oos", "one_day_recovery_then_oos_flag", "恢复次日再断货"),
)
OUTCOME_RULE_DESCRIPTIONS = {
    "historical_operating_level": {
        "unavailable": "有效滚动30天角色节点少于8个。",
        "in_stock_zero_sales": "有效节点≥8，且有货零销量节点占比≥60%；按等级优先级先判定。",
        "loss": "未命中有货零销量，且历史利润率<0。",
        "poor": "未命中更高优先级结果，且历史利润率为0%–5%，或问题类节点占比≥50%。",
        "excellent": "明星节点占比≥60%，明星+潜力节点占比≥80%，且历史利润率≥15%。",
        "good": "未命中历史优秀，明星+潜力节点占比≥60%，问题类节点占比<25%，且历史利润率≥5%。",
        "normal": "有效节点≥8，且未命中有货零销量、亏损、较差、优秀或良好。",
    },
    "historical_stability": {
        "highly_stable": "角色、销量、利润三项均稳定。",
        "basically_stable": "三项均非高度波动，且至少两项稳定。",
        "volatile": "具备稳定性判断条件，但未命中高度稳定、基本稳定或高度波动。",
        "highly_volatile": "角色项高度波动，或角色、销量、利润中至少两项高度波动。",
        "unavailable": "有效角色节点<8、有效经营周不足，或角色/销量/利润任一分项证据不足。",
    },
    "historical_role_pattern": {
        "unavailable": "可排序角色节点少于9个，无法比较前后各三分之一。",
        "repeated_switching": "确认后的方向反转≥3次；或确认切换≥5次且升级、退化均出现。角色变化需连续2个节点才确认。",
        "maintained": "主导角色占比≥70%，确认切换≤2次且方向反转≤1次。角色变化需连续2个节点才确认。",
        "gradual_upgrade": "后1/3角色中位数比前1/3至少高1级，确认升级多于退化且反转≤1次。",
        "gradual_downgrade": "后1/3角色中位数比前1/3至少低1级，确认退化多于升级且反转≤1次。",
        "mixed": "具备前后分段证据，但未命中反复切换、保持、逐步升级或逐步退化。",
    },
    "pre_oos_role_change": {
        "stopped_7d": "A窗口（断货日前1–7天）为有货零销量，且B或C窗口存在可排序角色。",
        "started_7d": "A窗口存在可排序角色，且B窗口（断货日前8–14天）为有货零销量。",
        "upgraded_90d": "D→C→B→A角色等级不下降，且至少两个阶段升级。",
        "downgraded_90d": "D→C→B→A角色等级不上升，且至少两个阶段退化。",
        "upgraded_30d": "A≥B≥C 且 A>C；A/B/C分别为断货日前1–7、8–14、15–30天。",
        "downgraded_30d": "A≤B≤C 且 A<C；A/B/C分别为断货日前1–7、8–14、15–30天。",
        "upgraded_7d": "A窗口角色等级高于B窗口。",
        "downgraded_7d": "A窗口角色等级低于B窗口。",
        "maintained": "A、B、C三个窗口的可排序角色等级相同。",
        "unclear": "A、B、C证据完整，但不符合持续升级、持续退化、近7天变化或保持。",
        "unavailable": "A、B、C任一窗口不是可排序角色，且未命中近7天启动或停滞。",
    },
}
QUALITY_RULE_DESCRIPTIONS = {
    "low_stock_constrained": "历史有效经营日中，FBA 库存 1–5 的天数占比≥30%。",
    "inventory_sales_conflict": "历史窗口内至少一天 FBA 库存为0但销量>0。",
    "missing_date_gap": "2026-01-01 至断货前一日 T0 的历史窗口存在缺失日期。",
    "few_selling_days": "历史有效经营日有销量，但产生销量的日期≤2天。",
    "single_day_concentrated": "历史有效经营日中，最高单日销量占总销量≥50%。",
    "extreme_single_day_concentrated": "历史有效经营日中，最高单日销量占总销量≥80%。",
    "event_boundary_incomplete": "当前断货事件未找到完整左边界，断货起点仅能按已观察范围解释。",
    "one_day_recovery_then_oos": "断货期间库存曾恢复到>5，但仅持续1天，次日再次断货。",
}
REASON_LABELS = {
    "low_inventory_edge": "低量库存边缘断货",
    "pre_oos_evidence_insufficient": "断货前依据不足",
    "current_gate_evidence_missing": "现有评价证据缺失",
    "left_boundary_incomplete": "断货事件左边界不完整",
    "event_boundary_incomplete": "断货事件边界不完整",
    "event_start_missing": "未识别到断货事件起点",
    "not_current_oos": "经营日表当日库存与断货标签不一致",
    "current_gate_not_evaluable": "未通过现有评价门槛",
    "oos_before_history_start": "断货发生在历史窗口起点之前",
    "history_span_lt_90": "历史跨度少于90天",
    "daily_coverage_lt_80pct": "日级数据覆盖率低于80%",
    "effective_days_or_weeks_insufficient": "有效经营日或有效周不足",
}


def _share(count: int, denominator: int) -> float:
    return round(count / denominator, 4) if denominator else 0


def _period_role_rule_description(*, scope_mode: str, period: str, code: str) -> str:
    minimum_days = {"7d": 5, "14d": 10, "30d": 21, "90d": 63}[period]
    window_days = period[:-1]
    prefix = (
        f"{window_days}天窗口有效经营日至少{minimum_days}天；"
        f"角色日销＝周期总销量÷{window_days}天；"
    )
    if code == "unavailable":
        return f"{window_days}天窗口有效经营日少于{minimum_days}天。"
    if code == "in_stock_zero_sales":
        return prefix + "周期总销量=0。"
    if scope_mode == "country":
        rules = {
            "problem": "角色日销>0，且利润率缺失或<5%，或最近有效日排名无效。",
            "star": "最近有效日排名≤50，且角色日销>3、利润率≥15%，或角色日销1–3、利润率≥25%。",
            "potential": "未命中明星，最近有效日排名≤100，且角色日销>3、利润率≥5%，或角色日销1–3、利润率≥10%。",
            "dog": "角色日销>0且利润率、排名有效，但未命中明星、潜力或问题产品。",
        }
    else:
        rules = {
            "problem": "角色日销>0，且利润率缺失或<5%。",
            "star": "角色日销≥5且利润率≥15%，或角色日销1–<5且利润率≥25%。",
            "potential": "未命中明星，且角色日销≥5、利润率≥5%，或角色日销1–<5、利润率≥10%。",
            "dog": "角色日销>0且利润率≥5%，但未命中明星或潜力产品。",
        }
    return prefix + rules[code]


def _member_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    if row.get("scope_mode") == "country":
        return (
            str(row.get("country_category") or ""),
            str(row.get("country") or ""),
            str(row.get("store") or ""),
            str(row.get("msku") or ""),
        )
    return (
        str(row.get("country_category") or ""),
        str(row.get("store") or ""),
        str(row.get("msku") or ""),
    )


def _matches_operating_overview(row: Mapping[str, Any], code: str) -> bool:
    quality = str(row.get("historical_operating_level") or "") in OPERATING_QUALITY_LEVELS
    stable = str(row.get("historical_stability") or "") in OPERATING_STABLE_LEVELS
    if code == "quality":
        return quality
    if code == "stable":
        return stable
    if code == "quality_stable":
        return quality and stable
    if code == "risk":
        return str(row.get("historical_operating_level") or "") in OPERATING_RISK_LEVELS
    raise ValueError("断货历史经营运营结论不存在")


def _primary_diagnosis_code(row: Mapping[str, Any]) -> str:
    if row.get("current_gate_status") != "evaluable":
        return "gate_not_passed"
    if row.get("historical_evaluable_status") != "historical_operating_evaluable":
        return "history_insufficient"
    quality = str(row.get("historical_operating_level") or "") in OPERATING_QUALITY_LEVELS
    stable = str(row.get("historical_stability") or "") in OPERATING_STABLE_LEVELS
    risk = str(row.get("historical_operating_level") or "") in OPERATING_RISK_LEVELS
    if quality and stable:
        return "quality_stable"
    if quality:
        return "quality_non_stable"
    if risk:
        return "operating_risk"
    if stable:
        return "stable_base"
    return "watch"


def _action_queue_code(row: Mapping[str, Any]) -> str:
    diagnosis = _primary_diagnosis_code(row)
    if diagnosis == "quality_stable" and (
        str(row.get("role_30d") or "unavailable") not in RECENT_RECOVERY_QUALITY_ROLES
        or str(row.get("pre_oos_role_change") or "unavailable") in RECENT_RECOVERY_BLOCKING_CHANGES
    ):
        return "review_recovery"
    return {
        "quality_stable": "priority_recovery",
        "quality_non_stable": "review_recovery",
        "operating_risk": "cautious_recovery",
        "stable_base": "observe",
        "watch": "observe",
        "history_insufficient": "unassessable",
        "gate_not_passed": "unassessable",
    }[diagnosis]


def _recovery_gap_reason_code(row: Mapping[str, Any]) -> str:
    diagnosis = _primary_diagnosis_code(row)
    if diagnosis == "gate_not_passed":
        return "current_gate_not_passed"
    if diagnosis == "history_insufficient":
        return "historical_evidence_insufficient"
    if diagnosis == "operating_risk":
        return "historical_operating_risk"
    if diagnosis in {"stable_base", "watch"}:
        return "historical_quality_insufficient"
    if diagnosis == "quality_non_stable":
        return "stability_insufficient"
    if str(row.get("pre_oos_role_change") or "unavailable") in RECENT_RECOVERY_BLOCKING_CHANGES:
        return "recent_role_deterioration"
    return ""


def _recovery_gap_attribution(
    rows: list[Mapping[str, Any]], *, queue_code: str
) -> dict[str, Any]:
    eligible_rows = [
        row for row in rows
        if str(row.get("role_30d") or "unavailable") in RECENT_RECOVERY_QUALITY_ROLES
        and queue_code != "priority_recovery"
    ]
    roles = []
    reconciled_count = 0
    for role_code in ("star", "potential"):
        role_rows = [row for row in eligible_rows if str(row.get("role_30d") or "") == role_code]
        reason_counts = Counter(_recovery_gap_reason_code(row) for row in role_rows)
        reasons = []
        for reason_code, (label, description) in RECOVERY_GAP_REASON_DEFINITIONS.items():
            count = reason_counts[reason_code]
            if not count:
                continue
            reconciled_count += count
            reasons.append(
                {
                    "code": f"{queue_code}|{role_code}|{reason_code}",
                    "reason_code": reason_code,
                    "label": label,
                    "description": description,
                    "count": count,
                    "share": _share(count, len(role_rows)),
                }
            )
        roles.append(
            {
                "code": role_code,
                "label": ROLE_LABELS[role_code],
                "count": len(role_rows),
                "reconciled_count": sum(item["count"] for item in reasons),
                "reasons": reasons,
            }
        )
    denominator = len(eligible_rows)
    return {
        "target_label": "优先恢复候选" if queue_code == "review_recovery" else "前两级恢复队列",
        "denominator": denominator,
        "reconciled_count": reconciled_count,
        "is_reconciled": reconciled_count == denominator,
        "roles": roles,
    }


def _full_population_status_code(row: Mapping[str, Any]) -> str:
    if row.get("current_gate_status") != "evaluable":
        return "gate_not_passed"
    if row.get("historical_evaluable_status") != "historical_operating_evaluable":
        return "history_insufficient"
    return ""


def _quality_stability_groups(row: Mapping[str, Any]) -> tuple[str, str]:
    level = str(row.get("historical_operating_level") or "unavailable")
    stability = str(row.get("historical_stability") or "unavailable")
    level_group = "quality" if level in OPERATING_QUALITY_LEVELS else ("risk" if level in OPERATING_RISK_LEVELS else "general")
    stability_group = "stable" if stability in OPERATING_STABLE_LEVELS else (
        "non_stable" if stability in {"volatile", "highly_volatile"} else "unavailable"
    )
    return level_group, stability_group


def _full_population_distribution_code(row: Mapping[str, Any], field: str) -> str:
    status_code = _full_population_status_code(row)
    return status_code or str(row.get(field) or "unavailable")


def _distribution_items(
    rows: list[Mapping[str, Any]], *, field: str, labels: Mapping[str, str], dimension: str
) -> list[dict[str, Any]]:
    counts = Counter(_full_population_distribution_code(row, field) for row in rows)
    denominator = len(rows)
    definitions = list(labels.items()) + list(FULL_POPULATION_STATUS_DEFINITIONS)
    return [
        {
            "code": code,
            "label": label,
            "count": counts[code],
            "share": _share(counts[code], denominator),
            "rule_description": (
                "该记录尚未形成深层历史结论。"
                if code in {item[0] for item in FULL_POPULATION_STATUS_DEFINITIONS}
                else OUTCOME_RULE_DESCRIPTIONS[dimension][code]
            ),
        }
        for code, label in definitions
    ]


def _action_queue_child_groups(
    rows: list[Mapping[str, Any]], *, scope_mode: str
) -> list[dict[str, Any]]:
    denominator = len(rows)
    primary_counts = Counter(_primary_diagnosis_code(row) for row in rows)
    primary = {
        "dimension": "primary_diagnosis",
        "label": "运营判断构成",
        "denominator": denominator,
        "is_mutually_exclusive": True,
        "items": [
            {
                "code": code,
                "label": label,
                "count": primary_counts[code],
                "share": _share(primary_counts[code], denominator),
                "rule_description": action_hint,
            }
            for code, label, action_hint in PRIMARY_DIAGNOSIS_DEFINITIONS
        ],
    }
    outcome_groups: dict[str, Any] = {}
    for field, label, labels in OUTCOME_DEFINITIONS:
        outcome_groups[field] = {
            "dimension": field,
            "label": label,
            "denominator": denominator,
            "is_mutually_exclusive": True,
            "items": _distribution_items(rows, field=field, labels=labels, dimension=field),
        }
    periods: dict[str, list[dict[str, Any]]] = {}
    for period in PERIODS:
        field = f"role_{period}"
        counts = Counter(_full_population_distribution_code(row, field) for row in rows)
        definitions = list(ROLE_LABELS.items()) + list(FULL_POPULATION_STATUS_DEFINITIONS)
        periods[period] = [
            {
                "code": code,
                "label": label,
                "count": counts[code],
                "share": _share(counts[code], denominator),
                "rule_description": (
                    "该记录尚未形成周期角色结论。"
                    if code in {item[0] for item in FULL_POPULATION_STATUS_DEFINITIONS}
                    else _period_role_rule_description(scope_mode=scope_mode, period=period, code=code)
                ),
            }
            for code, label in definitions
        ]
    quality_items = []
    for code, field, label in QUALITY_DEFINITIONS:
        count = sum(bool(row.get(field)) for row in rows)
        quality_items.append(
            {
                "code": code,
                "label": label,
                "count": count,
                "share": _share(count, denominator),
                "rule_description": QUALITY_RULE_DESCRIPTIONS[code],
            }
        )
    return [
        primary,
        outcome_groups["historical_operating_level"],
        outcome_groups["historical_stability"],
        {
            "dimension": "period_role",
            "label": "断货前销售角色",
            "denominator": denominator,
            "is_mutually_exclusive": True,
            "periods": periods,
        },
        outcome_groups["historical_role_pattern"],
        outcome_groups["pre_oos_role_change"],
        {
            "dimension": "quality_flag",
            "label": "数据质量与保护性证据",
            "denominator": denominator,
            "is_mutually_exclusive": False,
            "items": quality_items,
        },
    ]


def build_stockout_historical_summary(
    rows: Iterable[Mapping[str, Any]], *, scope_mode: str, data_date: str
) -> dict[str, Any]:
    if scope_mode not in {"business_unit", "country"}:
        raise ValueError("断货历史经营维度不存在")
    scoped = [dict(row) for row in rows if str(row.get("scope_mode") or "") == scope_mode]
    total = len(scoped)
    current_gate_evaluable = sum(row.get("current_gate_status") == "evaluable" for row in scoped)
    historical_evaluable = [
        row for row in scoped
        if row.get("historical_evaluable_status") == "historical_operating_evaluable"
    ]
    stockout_only = sum(row.get("historical_evaluable_status") == "stockout_history_only" for row in scoped)
    insufficient = sum(row.get("historical_evaluable_status") == "historical_evidence_insufficient" for row in scoped)
    reason_counts = Counter(
        str(row.get("historical_evaluable_reason") or row.get("current_gate_reason") or "unknown")
        for row in scoped
        if row.get("historical_evaluable_status") != "historical_operating_evaluable"
    )
    outcomes = []
    denominator = len(historical_evaluable)
    primary_counts = Counter(_primary_diagnosis_code(row) for row in scoped)
    primary_reconciled_count = sum(primary_counts.values())
    primary_diagnosis = {
        "denominator": total,
        "reconciled_count": primary_reconciled_count,
        "is_reconciled": primary_reconciled_count == total,
        "items": [
            {
                "code": code,
                "label": label,
                "count": primary_counts[code],
                "share": _share(primary_counts[code], total),
                "action_hint": action_hint,
            }
            for code, label, action_hint in PRIMARY_DIAGNOSIS_DEFINITIONS
        ],
    }
    operating_overview = {
        "denominator": denominator,
        "total_denominator": total,
        "items": [
            {
                "code": code,
                "label": label,
                "count": sum(_matches_operating_overview(row, code) for row in historical_evaluable),
                "share": _share(
                    sum(_matches_operating_overview(row, code) for row in historical_evaluable),
                    total,
                ),
                "evaluable_share": _share(
                    sum(_matches_operating_overview(row, code) for row in historical_evaluable),
                    denominator,
                ),
                "rule_description": description,
            }
            for code, label, description in OPERATING_OVERVIEW_DEFINITIONS
        ],
    }
    for field, label, labels in OUTCOME_DEFINITIONS:
        counts = Counter(str(row.get(field) or "unavailable") for row in historical_evaluable)
        outcomes.append(
            {
                "dimension": field,
                "label": label,
                "denominator": denominator,
                "total_denominator": total,
                "items": [
                    {
                        "code": code,
                        "label": item_label,
                        "count": counts[code],
                        "share": _share(counts[code], total),
                        "rule_description": OUTCOME_RULE_DESCRIPTIONS[field][code],
                    }
                    for code, item_label in labels.items()
                ] + [
                    {
                        "code": status_code,
                        "label": status_label,
                        "count": sum(_full_population_status_code(row) == status_code for row in scoped),
                        "share": _share(sum(_full_population_status_code(row) == status_code for row in scoped), total),
                        "rule_description": "该记录未进入深层历史结论，作为全量断货分母的补齐项。",
                    }
                    for status_code, status_label in FULL_POPULATION_STATUS_DEFINITIONS
                ],
            }
        )
    quality_flags = []
    for code, field, label in QUALITY_DEFINITIONS:
        count = sum(bool(row.get(field)) for row in scoped)
        quality_flags.append(
            {
                "code": code,
                "label": label,
                "count": count,
                "share": _share(count, total),
                "rule_description": QUALITY_RULE_DESCRIPTIONS[code],
            }
        )
    period_role_matrix = []
    for period in PERIODS:
        field = f"role_{period}"
        counts = Counter(str(row.get(field) or "unavailable") for row in historical_evaluable)
        status_counts = Counter(_full_population_status_code(row) for row in scoped)
        period_role_matrix.append(
            {
                "period": period,
                "label": f"断货日前{period[:-1]}天",
                "denominator": total,
                "historical_evaluable_denominator": denominator,
                "items": [
                    {
                        "code": code,
                        "label": label,
                        "count": counts[code],
                        "share": _share(counts[code], total),
                        "evaluable_share": _share(counts[code], denominator),
                        "rule_description": _period_role_rule_description(
                            scope_mode=scope_mode,
                            period=period,
                            code=code,
                        ),
                    }
                    for code, label in ROLE_LABELS.items()
                ] + [
                    {
                        "code": status_code,
                        "label": status_label,
                        "count": status_counts[status_code],
                        "share": _share(status_counts[status_code], total),
                        "evaluable_share": 0,
                        "rule_description": "该记录未形成周期角色结论，作为当前断货全量分母的补齐项。",
                    }
                    for status_code, status_label in FULL_POPULATION_STATUS_DEFINITIONS
                ],
            }
        )
    matrix_rows = (
        ("quality", "经营优质"),
        ("general", "经营一般"),
        ("risk", "经营风险"),
    )
    matrix_columns = (
        ("stable", "稳定"),
        ("non_stable", "非稳定"),
        ("unavailable", "稳定性不可判"),
    )
    matrix_counts: Counter[tuple[str, str]] = Counter()
    for row in historical_evaluable:
        matrix_counts[_quality_stability_groups(row)] += 1
    quality_stability_matrix = {
        "denominator": denominator,
        "total_stockout_denominator": total,
        "rows": [{"code": code, "label": label} for code, label in matrix_rows],
        "columns": [{"code": code, "label": label} for code, label in matrix_columns],
        "cells": [
            {
                "row_code": row_code,
                "column_code": column_code,
                "count": matrix_counts[(row_code, column_code)],
                "share": _share(matrix_counts[(row_code, column_code)], denominator),
            }
            for row_code, _row_label in matrix_rows
            for column_code, _column_label in matrix_columns
        ],
    }
    action_counts = Counter(_action_queue_code(row) for row in scoped)
    action_reconciled_count = sum(action_counts.values())
    action_queue = {
        "denominator": total,
        "reconciled_count": action_reconciled_count,
        "is_reconciled": action_reconciled_count == total,
        "items": [
            {
                "code": code,
                "label": label,
                "count": action_counts[code],
                "share": _share(action_counts[code], total),
                "reason": reason,
                "action_hint": action_hint,
                "tone": tone,
                "child_groups": _action_queue_child_groups(
                    [row for row in scoped if _action_queue_code(row) == code],
                    scope_mode=scope_mode,
                ),
                "recovery_gap": _recovery_gap_attribution(
                    [row for row in scoped if _action_queue_code(row) == code],
                    queue_code=code,
                ),
            }
            for code, label, reason, action_hint, tone in ACTION_QUEUE_DEFINITIONS
        ],
    }
    unique_msku_count = len({str(row.get("msku") or "") for row in scoped})
    rule_versions = sorted({str(row.get("rule_version") or "") for row in scoped if row.get("rule_version")})
    return {
        "data_date": data_date,
        "scope_mode": scope_mode,
        "scope": {
            "business_unit_count": total,
            "country_record_count": total if scope_mode == "country" else 0,
            "unique_msku_count": unique_msku_count,
        },
        "eligibility_path": {
            "current_stockout_count": total,
            "current_gate_evaluable_count": current_gate_evaluable,
            "historical_operating_evaluable_count": denominator,
            "stockout_history_only_count": stockout_only,
            "historical_evidence_insufficient_count": insufficient,
            "exclusion_reasons": [
                {
                    "code": code,
                    "label": REASON_LABELS.get(code, code),
                    "count": count,
                    "share": _share(count, total),
                }
                for code, count in sorted(reason_counts.items())
            ],
        },
        "operating_overview": operating_overview,
        "action_queue": action_queue,
        "primary_diagnosis": primary_diagnosis,
        "quality_stability_matrix": quality_stability_matrix,
        "outcomes": outcomes,
        "quality_flags": quality_flags,
        "period_role_matrix": period_role_matrix,
        "rule_version": rule_versions[-1] if rule_versions else "",
        "inventory_scope_note": (
            "库存及断货起点继承 MSKU，经营与排名按国家独立计算"
            if scope_mode == "country"
            else "MSKU 库存按国家日记录汇总"
        ),
    }


def decorate_stockout_snapshot_status(
    payload: Mapping[str, Any], *, requested_data_date: str, latest_result_date: str, source_data_date: str
) -> dict[str, Any]:
    result = dict(payload)
    has_rows = bool((result.get("eligibility_path") or {}).get("current_stockout_count"))
    result.update(
        requested_data_date=requested_data_date,
        result_data_date=requested_data_date if has_rows else "",
        latest_result_date=latest_result_date,
        source_data_date=source_data_date,
        snapshot_status="ready" if has_rows else "no_snapshot",
        is_data_lagging=bool(
            requested_data_date == source_data_date
            and (not latest_result_date or latest_result_date < source_data_date)
        ),
    )
    return result


def filter_stockout_historical_members(
    rows: Iterable[Mapping[str, Any]], dimension: str, code: str, *, period: str = ""
) -> set[tuple[str, ...]]:
    allowed_dimensions = {field for field, _label, _labels in OUTCOME_DEFINITIONS}
    if dimension == "eligibility_reason":
        return {
            _member_key(row) for row in rows
            if str(row.get("historical_evaluable_reason") or row.get("current_gate_reason") or "") == code
        }
    if dimension == "quality_flag":
        quality_fields = {item_code: field for item_code, field, _label in QUALITY_DEFINITIONS}
        if code not in quality_fields:
            raise ValueError("断货历史经营质量标记不存在")
        return {_member_key(row) for row in rows if bool(row.get(quality_fields[code]))}
    if dimension == "period_role":
        if period not in PERIODS or code not in set(ROLE_LABELS) | {item[0] for item in FULL_POPULATION_STATUS_DEFINITIONS}:
            raise ValueError("断货历史经营周期角色不存在")
        if code in {item[0] for item in FULL_POPULATION_STATUS_DEFINITIONS}:
            return {_member_key(row) for row in rows if _full_population_status_code(row) == code}
        return {
            _member_key(row) for row in rows
            if row.get("historical_evaluable_status") == "historical_operating_evaluable"
            and str(row.get(f"role_{period}") or "unavailable") == code
        }
    if dimension == "operating_overview":
        valid_codes = {item[0] for item in OPERATING_OVERVIEW_DEFINITIONS}
        if code not in valid_codes:
            raise ValueError("断货历史经营运营结论不存在")
        return {
            _member_key(row) for row in rows
            if row.get("historical_evaluable_status") == "historical_operating_evaluable"
            and _matches_operating_overview(row, code)
        }
    if dimension == "primary_diagnosis":
        valid_codes = {item[0] for item in PRIMARY_DIAGNOSIS_DEFINITIONS}
        if code not in valid_codes:
            raise ValueError("断货历史经营主诊断不存在")
        return {_member_key(row) for row in rows if _primary_diagnosis_code(row) == code}
    if dimension == "action_queue":
        valid_codes = {item[0] for item in ACTION_QUEUE_DEFINITIONS}
        if code not in valid_codes:
            raise ValueError("断货历史经营行动队列不存在")
        return {_member_key(row) for row in rows if _action_queue_code(row) == code}
    if dimension == "recovery_gap":
        parts = code.split("|", 2)
        valid_queues = {item[0] for item in ACTION_QUEUE_DEFINITIONS} - {"priority_recovery"}
        valid_reasons = set(RECOVERY_GAP_REASON_DEFINITIONS)
        if (
            len(parts) != 3
            or parts[0] not in valid_queues
            or parts[1] not in RECENT_RECOVERY_QUALITY_ROLES
            or parts[2] not in valid_reasons
        ):
            raise ValueError("断货历史经营晋级差距不存在")
        queue_code, role_code, reason_code = parts
        return {
            _member_key(row) for row in rows
            if _action_queue_code(row) == queue_code
            and str(row.get("role_30d") or "unavailable") == role_code
            and _recovery_gap_reason_code(row) == reason_code
        }
    if dimension == "quality_stability":
        parts = code.split("|", 1)
        if len(parts) != 2 or parts[0] not in {"quality", "general", "risk"} or parts[1] not in {"stable", "non_stable", "unavailable"}:
            raise ValueError("断货历史经营质量稳定性组合不存在")
        return {
            _member_key(row) for row in rows
            if row.get("historical_evaluable_status") == "historical_operating_evaluable"
            and _quality_stability_groups(row) == (parts[0], parts[1])
        }
    if dimension not in allowed_dimensions:
        raise ValueError("断货历史经营结果维度不存在")
    if code in {item[0] for item in FULL_POPULATION_STATUS_DEFINITIONS}:
        return {_member_key(row) for row in rows if _full_population_status_code(row) == code}
    return {
        _member_key(row) for row in rows
        if row.get("historical_evaluable_status") == "historical_operating_evaluable"
        and str(row.get(dimension) or "unavailable") == code
    }
