from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping


RULE_VERSION = "stockout_historical_operating_v8_daily_confirmed_stability_20260827"
HISTORY_START_DATE = date(2026, 1, 1)
PERIOD_MIN_EFFECTIVE_DAYS = {"7d": 5, "14d": 10, "30d": 21, "90d": 63}
ROLE_CHANGE_CONFIRM_DAYS = 5
STABILITY_MIN_DAILY_NODES = 30
STABILITY_MIN_SPAN_DAYS = 60
ROLE_LEVEL = {"problem": 0, "dog": 1, "potential": 2, "star": 3}
ROLE_SHORT_LABELS = {"star": "明星", "potential": "潜力", "dog": "瘦狗", "problem": "问题"}

ROLE_LABELS = {
    "star": "明星产品",
    "potential": "潜力产品",
    "dog": "瘦狗产品",
    "problem": "问题产品",
    "in_stock_zero_sales": "有货零销量",
    "unavailable": "周期角色不可判",
}
HISTORICAL_LEVEL_LABELS = {
    "in_stock_zero_sales": "历史有货无销量",
    "loss": "历史亏损",
    "poor": "历史较差",
    "excellent": "历史优秀",
    "good": "历史良好",
    "normal": "历史一般",
    "unavailable": "历史不可判",
}
STABILITY_LABELS = {
    "highly_stable": "高度稳定",
    "basically_stable": "基本稳定",
    "volatile": "波动经营",
    "highly_volatile": "高度波动",
    "unavailable": "稳定性不可判",
}
ROLE_PATTERN_LABELS = {
    "unavailable": "历史变化不可判",
    "repeated_switching": "历史反复切换",
    "maintained": "历史角色保持",
    "gradual_upgrade": "历史逐步升级",
    "gradual_downgrade": "历史逐步退化",
    "mixed": "历史角色混合",
}
PRE_OOS_CHANGE_LABELS = {
    "stopped_7d": "断货日前7天停滞",
    "started_7d": "断货日前7天启动",
    "upgraded_90d": "断货日前90天持续升级",
    "downgraded_90d": "断货日前90天持续退化",
    "upgraded_30d": "断货日前30天持续升级",
    "downgraded_30d": "断货日前30天持续退化",
    "upgraded_7d": "断货日前7天升级",
    "downgraded_7d": "断货日前7天退化",
    "maintained": "断货前角色保持",
    "unclear": "断货前变化不明确",
    "unavailable": "角色变化不可判",
}


def _day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _normalized_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for source in rows:
        row = dict(source)
        row["dt_date"] = _day(row["dt_date"])
        row["fba_available"] = _number(row.get("fba_available", row.get("afn_fulfillable_quantity")))
        row["sales_qty"] = float(row.get("sales_qty") or 0)
        row["sales_amount"] = float(row.get("sales_amount") or 0)
        row["order_gross_profit"] = float(row.get("order_gross_profit") or 0)
        row["ranking"] = _number(row.get("ranking"))
        normalized.append(row)
    return sorted(normalized, key=lambda item: item["dt_date"])


def _gap_ranges(
    rows: list[dict[str, Any]], *, window_start: date | None = None, window_end: date | None = None
) -> list[dict[str, Any]]:
    observed_dates = sorted({row["dt_date"] for row in rows})
    gaps = []
    if window_start is not None and (not observed_dates or observed_dates[0] > window_start):
        end = (observed_dates[0] - timedelta(days=1)) if observed_dates else (window_end or window_start)
        gaps.append({"start": window_start.isoformat(), "end": end.isoformat(), "days": (end - window_start).days + 1})
    for previous, current in zip(observed_dates, observed_dates[1:]):
        missing = (current - previous).days - 1
        if missing > 0:
            gaps.append(
                {
                    "start": (previous + timedelta(days=1)).isoformat(),
                    "end": (current - timedelta(days=1)).isoformat(),
                    "days": missing,
                }
            )
    if window_end is not None and observed_dates and observed_dates[-1] < window_end:
        start = observed_dates[-1] + timedelta(days=1)
        gaps.append({"start": start.isoformat(), "end": window_end.isoformat(), "days": (window_end - start).days + 1})
    return gaps


def find_current_oos_event(
    rows: Iterable[Mapping[str, Any]],
    *,
    current_date: date,
    current_oos_confirmed: bool = False,
) -> dict[str, Any]:
    ordered = [row for row in _normalized_rows(rows) if row["dt_date"] <= current_date]
    by_day = {row["dt_date"]: row for row in ordered}
    current = by_day.get(current_date)
    base = {
        "current_oos_flag": current_oos_confirmed or bool(
            current and current["fba_available"] is not None and current["fba_available"] <= 0
        ),
        "oos_start_date": None,
        "oos_start_method": (
            "label_304_current_plus_most_recent_inventory_zero_run"
            if current_oos_confirmed
            else "most_recent_continuous_zero_run"
        ),
        "oos_start_confidence": "not_current_oos",
        "observed_oos_since_date": None,
        "minimum_current_oos_days": 0,
        "one_day_recovery_then_oos": False,
        "event_boundary_incomplete": False,
        "sellable_inventory": None,
    }
    if not base["current_oos_flag"]:
        return base
    if not ordered:
        base.update(
            oos_start_confidence="event_boundary_incomplete",
            observed_oos_since_date=current_date,
            minimum_current_oos_days=1,
            event_boundary_incomplete=True,
        )
        return base

    event_start = current_date
    cursor = current_date - timedelta(days=1) if current_oos_confirmed else current_date
    boundary_row = None
    boundary_incomplete = False
    while True:
        row = by_day.get(cursor)
        if row is None or row["fba_available"] is None:
            boundary_incomplete = True
            break
        if row["fba_available"] > 0:
            boundary_row = row
            break
        event_start = cursor
        cursor -= timedelta(days=1)
        if cursor < ordered[0]["dt_date"]:
            boundary_incomplete = True
            break

    if boundary_incomplete:
        base.update(
            oos_start_confidence=(
                "left_boundary_incomplete"
                if cursor < ordered[0]["dt_date"]
                else "event_boundary_incomplete"
            ),
            observed_oos_since_date=event_start,
            minimum_current_oos_days=(current_date - event_start).days + 1,
            event_boundary_incomplete=True,
            sellable_inventory=by_day.get(event_start, {}).get("fba_available"),
        )
        return base

    previous = by_day.get(boundary_row["dt_date"] - timedelta(days=1)) if boundary_row else None
    one_day_recovery = bool(
        previous
        and previous["fba_available"] is not None
        and previous["fba_available"] <= 0
        and boundary_row["dt_date"] + timedelta(days=1) == event_start
    )
    base.update(
        oos_start_date=event_start,
        oos_start_confidence="complete",
        observed_oos_since_date=event_start,
        minimum_current_oos_days=(current_date - event_start).days + 1,
        one_day_recovery_then_oos=one_day_recovery,
        sellable_inventory=by_day.get(event_start, {}).get("fba_available"),
    )
    return base


def classify_msku_role(daily_sales: float, margin_rate: float | None) -> str:
    if daily_sales <= 0:
        return "problem"
    if margin_rate is None:
        raise ValueError("日销大于0但毛利率缺失")
    if daily_sales > 5 and margin_rate > 0.15:
        return "star"
    if 1 <= daily_sales <= 5 and margin_rate > 0.25:
        return "star"
    if daily_sales > 5 and 0.05 <= margin_rate <= 0.15:
        return "potential"
    if 1 <= daily_sales <= 5 and 0.10 <= margin_rate <= 0.25:
        return "potential"
    if 1 <= daily_sales <= 5 and 0.05 <= margin_rate < 0.10:
        return "dog"
    if 0 < daily_sales < 1 and margin_rate > 0.05:
        return "dog"
    return "problem"


def classify_country_role(daily_sales: float, margin_rate: float | None, rank: float | None) -> dict[str, Any]:
    if rank is None:
        rank_status = "missing"
    elif rank <= 0:
        rank_status = "lte_zero"
    elif rank >= 99999:
        rank_status = "gte_99999"
    else:
        rank_status = "valid"
    if daily_sales <= 0:
        role = "in_stock_zero_sales"
    elif margin_rate is None or margin_rate < 0.05 or rank_status != "valid":
        role = "problem"
    elif rank <= 50 and ((daily_sales > 3 and margin_rate >= 0.15) or (1 <= daily_sales <= 3 and margin_rate >= 0.25)):
        role = "star"
    elif rank <= 100 and (
        (daily_sales > 3 and margin_rate >= 0.05)
        or (1 <= daily_sales <= 3 and margin_rate >= 0.10)
    ):
        role = "potential"
    else:
        role = "dog"
    return {
        "role": role,
        "label_id": {"star": 2101, "potential": 2102, "dog": 2103}.get(role, 2104),
        "rank_status": rank_status,
    }


def _period_role(
    rows: list[dict[str, Any]],
    scope_mode: str,
    minimum_days: int,
    period_days: int,
) -> dict[str, Any]:
    effective = [row for row in rows if row["fba_available"] is not None and row["fba_available"] > 0]
    effective_sales = sum(row["sales_qty"] for row in effective)
    sales = sum(row["sales_qty"] for row in rows)
    amount = sum(row["sales_amount"] for row in rows)
    gross_profit = sum(row["order_gross_profit"] for row in rows)
    selling_days = sum(1 for row in rows if row["sales_qty"] > 0)
    max_day_share = max((row["sales_qty"] for row in rows), default=0) / sales if sales > 0 else 0
    natural_daily_sales = sales / period_days if period_days > 0 else None
    evidence = {
        "effective_operating_days": len(effective),
        "observed_calendar_days": len({row["dt_date"] for row in rows}),
        "calendar_period_days": period_days,
        "sales_qty": sales,
        "sales_amount": amount,
        "gross_profit": gross_profit,
        "in_stock_daily_sales": effective_sales / len(effective) if effective else None,
        "natural_daily_sales": natural_daily_sales,
        "role_daily_sales": natural_daily_sales,
        "role_daily_sales_basis": "calendar_period_days",
        "margin_rate": gross_profit / amount if amount > 0 else None,
        "selling_day_count": selling_days,
        "max_day_sales_share": max_day_share,
        "role": "unavailable",
        "role_label": ROLE_LABELS["unavailable"],
    }
    if len(effective) < minimum_days:
        evidence["reason"] = "effective_operating_days_insufficient"
        return evidence
    if (evidence["role_daily_sales"] or 0) > 0 and evidence["margin_rate"] is None:
        evidence.update(state="data_anomaly", reason="positive_sales_margin_missing")
        return evidence
    if scope_mode == "country":
        last_effective = effective[-1]
        country = classify_country_role(evidence["role_daily_sales"] or 0, evidence["margin_rate"], last_effective.get("ranking"))
        evidence.update(country)
        evidence["small_rank"] = last_effective.get("ranking")
        evidence["small_rank_stat_date"] = last_effective["dt_date"].isoformat()
    else:
        evidence["role"] = classify_msku_role(evidence["role_daily_sales"] or 0, evidence["margin_rate"])
    evidence["role_label"] = ROLE_LABELS[evidence["role"]]
    return evidence


def calculate_role_window(
    rows: Iterable[Mapping[str, Any]], *, window_start: date, window_end: date
) -> dict[str, Any]:
    ordered = _normalized_rows(rows)
    by_day = {row["dt_date"]: row for row in ordered if window_start <= row["dt_date"] <= window_end}
    expected_days = (window_end - window_start).days + 1
    if expected_days != 30 or len(by_day) != 30:
        return {
            "role": "unavailable",
            "state": "data_anomaly",
            "reason": "incomplete_30d_window",
            "effective_operating_days": sum(
                1 for row in by_day.values() if row["fba_available"] is not None and row["fba_available"] > 0
            ),
        }
    window_rows = [by_day[window_start + timedelta(days=index)] for index in range(30)]
    if any(row["fba_available"] is None for row in window_rows):
        return {
            "role": "unavailable",
            "state": "data_anomaly",
            "reason": "inventory_missing",
            "effective_operating_days": sum(
                1 for row in window_rows if row["fba_available"] is not None and row["fba_available"] > 0
            ),
        }
    if any(row["fba_available"] <= 0 for row in window_rows):
        return {
            "role": "unavailable",
            "state": "recovery_observation",
            "reason": "window_contains_stockout",
            "effective_operating_days": sum(1 for row in window_rows if row["fba_available"] > 0),
        }
    sales = sum(row["sales_qty"] for row in window_rows)
    amount = sum(row["sales_amount"] for row in window_rows)
    profit = sum(row["order_gross_profit"] for row in window_rows)
    daily_sales = sales / 30
    margin_rate = profit / amount if amount > 0 else None
    if daily_sales > 0 and margin_rate is None:
        return {
            "role": "unavailable",
            "state": "data_anomaly",
            "reason": "positive_sales_margin_missing",
            "effective_operating_days": 30,
        }
    role = classify_msku_role(daily_sales, margin_rate)
    return {
        "role": role,
        "role_label": ROLE_LABELS[role],
        "state": "normal",
        "reason": "",
        "daily_sales": daily_sales,
        "margin_rate": margin_rate,
        "sales_qty": sales,
        "sales_amount": amount,
        "gross_profit": profit,
        "effective_operating_days": 30,
    }


def find_short_period_fallback(
    rows: Iterable[Mapping[str, Any]], *, t0: date, minimum_days: int = 14
) -> dict[str, Any] | None:
    by_day = {row["dt_date"]: row for row in _normalized_rows(rows) if row["dt_date"] <= t0}
    consecutive: list[dict[str, Any]] = []
    candidate: list[dict[str, Any]] | None = None
    current_day = HISTORY_START_DATE
    while current_day <= t0:
        row = by_day.get(current_day)
        if row is None or row["fba_available"] is None or row["fba_available"] <= 0:
            consecutive = []
        else:
            consecutive.append(row)
            if len(consecutive) >= minimum_days:
                candidate = consecutive[-minimum_days:]
        current_day += timedelta(days=1)
    if candidate is None:
        return None

    sales = sum(row["sales_qty"] for row in candidate)
    amount = sum(row["sales_amount"] for row in candidate)
    profit = sum(row["order_gross_profit"] for row in candidate)
    daily_sales = sales / minimum_days
    margin_rate = profit / amount if amount > 0 else None
    if daily_sales > 0 and margin_rate is None:
        return {"state": "data_anomaly", "reason": "positive_sales_margin_missing"}
    role = classify_msku_role(daily_sales, margin_rate)
    return {
        "state": "short_period_fallback",
        "role": role,
        "role_label": ROLE_LABELS[role],
        "window_start": candidate[0]["dt_date"],
        "window_end": candidate[-1]["dt_date"],
        "daily_sales": daily_sales,
        "margin_rate": margin_rate,
    }


def build_rolling_role_nodes(
    rows: Iterable[Mapping[str, Any]], *, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    ordered = _normalized_rows(rows)
    by_day = {row["dt_date"]: row for row in ordered}
    nodes: list[dict[str, Any]] = []
    last_valid: dict[str, Any] | None = None
    consecutive_recovery_days = 0
    current_day = start_date
    while current_day <= end_date:
        row = by_day.get(current_day)
        node = {
            "node_date": current_day,
            "window_start": current_day - timedelta(days=29),
            "window_end": current_day,
            "role": "unavailable",
            "role_label": ROLE_LABELS["unavailable"],
            "state": "unavailable",
            "source_node_date": None,
            "daily_sales": None,
            "margin_rate": None,
            "recovery_day_count": 0,
            "reason": "no_complete_30d_window",
            "sellable_inventory": row.get("fba_available") if row is not None else None,
        }
        if row is None or row["fba_available"] is None:
            consecutive_recovery_days = 0
            node.update(state="data_anomaly", reason="inventory_missing")
        elif row["fba_available"] <= 0:
            consecutive_recovery_days = 0
            if last_valid is not None:
                node.update(
                    role=last_valid["role"],
                    role_label=last_valid["role_label"],
                    state="carried_oos",
                    source_node_date=last_valid["node_date"],
                    daily_sales=last_valid["daily_sales"],
                    margin_rate=last_valid["margin_rate"],
                    reason="stockout_carry",
                )
            else:
                node["reason"] = "no_prior_valid_role"
        else:
            consecutive_recovery_days += 1
            evidence = calculate_role_window(
                ordered,
                window_start=current_day - timedelta(days=29),
                window_end=current_day,
            )
            if evidence["state"] == "normal":
                node.update(evidence)
                node["source_node_date"] = current_day
                node["recovery_day_count"] = consecutive_recovery_days
                last_valid = node.copy()
            elif last_valid is not None:
                node.update(
                    role=last_valid["role"],
                    role_label=last_valid["role_label"],
                    state="recovery_observation",
                    source_node_date=last_valid["node_date"],
                    daily_sales=last_valid["daily_sales"],
                    margin_rate=last_valid["margin_rate"],
                    recovery_day_count=consecutive_recovery_days,
                    reason=evidence["reason"],
                )
            else:
                node.update(
                    state=evidence["state"],
                    recovery_day_count=consecutive_recovery_days,
                    reason=evidence["reason"],
                )
        nodes.append(node)
        current_day += timedelta(days=1)
    return nodes


def select_non_overlapping_windows(
    nodes: Iterable[Mapping[str, Any]], *, t0: date
) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(node) for node in nodes if _day(node["node_date"]) <= t0),
        key=lambda node: _day(node["node_date"]),
    )
    if not ordered:
        return []
    normal_by_date = {
        _day(node["node_date"]): node
        for node in ordered
        if node.get("state") == "normal" and node.get("role") in ROLE_LEVEL
    }
    latest = ordered[-1]
    source_date = latest.get("source_node_date")
    anchor_date = _day(source_date) if source_date else _day(latest["node_date"])
    anchor = normal_by_date.get(anchor_date)
    if anchor is None:
        eligible = [node for day, node in normal_by_date.items() if day <= anchor_date]
        anchor = max(eligible, key=lambda node: _day(node["node_date"]), default=None)
    if anchor is None:
        return []

    selected = []
    current = anchor
    while current is not None:
        item = dict(current)
        item["source_node_date"] = _day(item.get("source_node_date") or item["node_date"])
        item["selected_for_stability"] = True
        selected.append(item)
        current_start = _day(current["window_start"])
        candidates = [
            node
            for node in normal_by_date.values()
            if _day(node["window_end"]) < current_start
        ]
        current = max(candidates, key=lambda node: _day(node["window_end"]), default=None)
    return list(reversed(selected))


def select_confirmed_daily_role_nodes(
    nodes: Iterable[Mapping[str, Any]], *, t0: date
) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(node) for node in nodes if _day(node["node_date"]) <= t0),
        key=lambda node: _day(node["node_date"]),
    )
    selected: list[dict[str, Any]] = []
    confirmed_role: str | None = None
    candidate_role: str | None = None
    candidate_indices: list[int] = []
    previous_normal_day: date | None = None

    for source in ordered:
        day = _day(source["node_date"])
        raw_role = str(source.get("role") or "")
        if source.get("state") != "normal" or raw_role not in ROLE_LEVEL:
            candidate_role = None
            candidate_indices = []
            previous_normal_day = None
            continue

        item = dict(source)
        item.update(
            raw_role=raw_role,
            stability_role=confirmed_role or raw_role,
            selected_for_stability=True,
            role_confirmation_state="confirmed" if confirmed_role is None else "unchanged",
            candidate_streak=0,
            confirmed_role_change=False,
        )
        if confirmed_role is None:
            confirmed_role = raw_role
            item["stability_role"] = raw_role
        elif raw_role == confirmed_role:
            candidate_role = None
            candidate_indices = []
        else:
            is_consecutive = previous_normal_day is not None and day == previous_normal_day + timedelta(days=1)
            if candidate_role != raw_role or not is_consecutive:
                candidate_role = raw_role
                candidate_indices = []
            item["role_confirmation_state"] = "candidate"
            candidate_indices.append(len(selected))
            item["candidate_streak"] = len(candidate_indices)
            if len(candidate_indices) >= ROLE_CHANGE_CONFIRM_DAYS:
                confirmed_role = raw_role
                for index in candidate_indices[:-1]:
                    selected[index]["stability_role"] = raw_role
                    selected[index]["role_confirmation_state"] = "confirmed"
                item["stability_role"] = raw_role
                item["role_confirmation_state"] = "confirmed"
                item["confirmed_role_change"] = True
                candidate_role = None
                candidate_indices = []

        selected.append(item)
        previous_normal_day = day
    return selected


def classify_historical_stability(
    windows: Iterable[Mapping[str, Any]], *, reference_role: str | None
) -> dict[str, Any]:
    valid = [dict(window) for window in windows if window.get("role") in ROLE_LEVEL]
    roles = [str(window.get("stability_role") or window["role"]) for window in valid]
    counts = Counter(roles)
    valid_count = len(roles)
    ordered_days = sorted(_day(window["node_date"]) for window in valid)
    evidence_span_days = (
        (ordered_days[-1] - ordered_days[0]).days + 1 if ordered_days else 0
    )
    dominant_role = None
    dominant_share = 0.0
    if counts:
        maximum = max(counts.values())
        tied = {role for role, count in counts.items() if count == maximum}
        if reference_role in tied:
            dominant_role = reference_role
        else:
            dominant_role = next(role for role in reversed(roles) if role in tied)
        dominant_share = maximum / valid_count
    switch_count = sum(left != right for left, right in zip(roles, roles[1:]))
    equivalent_windows = valid_count / 30 if valid_count else 0.0
    switch_rate = switch_count / max(equivalent_windows - 1, 1.0)
    if valid_count < STABILITY_MIN_DAILY_NODES or evidence_span_days < STABILITY_MIN_SPAN_DAYS:
        stability = "insufficient"
    elif dominant_share >= 0.70 and switch_rate <= 0.35:
        stability = "stable"
    elif dominant_share >= 0.60 and switch_rate <= 0.50:
        stability = "light_fluctuation"
    else:
        stability = "volatile"
    return {
        "historical_stability": stability,
        "valid_window_count": valid_count,
        "evidence_span_days": evidence_span_days,
        "dominant_role": dominant_role,
        "dominant_role_share": dominant_share,
        "role_switch_count": switch_count,
        "role_switch_rate": switch_rate,
    }


def _metric_change_direction(previous: float, current: float, *, kind: str) -> int:
    delta = current - previous
    if kind == "daily_sales":
        significant = (
            abs(delta) >= 0.2
            if previous == 0
            else abs(delta) >= 0.2 and abs(delta / previous) > 0.20
        )
    elif kind == "margin":
        significant = abs(delta) > 0.03 + 1e-12
    else:
        raise ValueError("指标类型不存在")
    if not significant:
        return 0
    return 1 if delta > 0 else -1


def classify_metric_direction(values: Iterable[float | None], *, kind: str) -> str:
    ordered = list(values)
    if len(ordered) < 2:
        return "stable"
    if all(value is None for value in ordered):
        return "stable"
    if any(value is None for value in ordered):
        return "unavailable"
    numeric = [float(value) for value in ordered if value is not None]
    pairs = list(zip(numeric, numeric[1:]))
    if len(numeric) >= 3:
        pairs.append((numeric[0], numeric[-1]))
    directions = {
        direction
        for previous, current in pairs
        if (direction := _metric_change_direction(previous, current, kind=kind)) != 0
    }
    if directions == {1, -1}:
        return "fluctuating"
    if directions == {1}:
        return "improving"
    if directions == {-1}:
        return "declining"
    return "stable"


def classify_recent_trend(windows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    recent = [dict(window) for window in windows][-3:]
    result = {
        "recent_trend": "insufficient",
        "daily_sales_trend": None,
        "margin_trend": None,
    }
    if len(recent) < 3:
        return result
    roles = [str(window.get("role") or "") for window in recent]
    directions = []
    for previous, current in zip(roles, roles[1:]):
        if previous not in ROLE_LEVEL or current not in ROLE_LEVEL:
            return result
        delta = ROLE_LEVEL[current] - ROLE_LEVEL[previous]
        if delta:
            directions.append(1 if delta > 0 else -1)
    if directions:
        if 1 in directions and -1 in directions:
            result["recent_trend"] = "fluctuating"
        elif 1 in directions:
            result["recent_trend"] = "improving"
        else:
            result["recent_trend"] = "declining"
        return result
    result.update(
        recent_trend="stable",
        daily_sales_trend=classify_metric_direction(
            [window.get("daily_sales") for window in recent], kind="daily_sales"
        ),
        margin_trend=classify_metric_direction(
            [window.get("margin_rate") for window in recent], kind="margin"
        ),
    )
    return result


def compose_operating_label(reference_role: str, trend: Mapping[str, Any]) -> dict[str, str]:
    role_label = ROLE_SHORT_LABELS.get(reference_role, "无有效历史角色")
    recent = str(trend.get("recent_trend") or "insufficient")
    recent_suffixes = {
        "improving": "近期改善",
        "declining": "近期退化",
        "fluctuating": "近期波动",
        "insufficient": "趋势依据不足",
    }
    if recent in recent_suffixes:
        suffix = recent_suffixes[recent]
        return {
            "combined_label_code": f"{reference_role}.{recent}",
            "combined_label": f"{role_label}·{suffix}" if reference_role in ROLE_SHORT_LABELS else role_label,
            "auxiliary_metric": "",
        }

    daily = str(trend.get("daily_sales_trend") or "stable")
    margin = str(trend.get("margin_trend") or "stable")
    if daily == margin == "stable":
        suffix = "持续稳定"
        auxiliary = ""
    elif daily == margin == "improving":
        suffix = "日销毛利改善"
        auxiliary = ""
    elif daily == margin == "declining":
        suffix = "日销毛利下降"
        auxiliary = ""
    else:
        priority = {"declining": 3, "fluctuating": 2, "improving": 1, "stable": 0, "unavailable": -1}
        metrics = [("日销", daily), ("毛利", margin)]
        metric_name, direction = max(metrics, key=lambda item: priority.get(item[1], -1))
        direction_label = {"declining": "下降", "fluctuating": "波动", "improving": "改善"}.get(direction, "稳定")
        suffix = f"{metric_name}{direction_label}" if direction != "stable" else "持续稳定"
        other_name, other_direction = metrics[1] if metric_name == "日销" else metrics[0]
        other_label = {"declining": "下降", "fluctuating": "波动", "improving": "改善"}.get(other_direction, "")
        auxiliary = f"{other_name}{other_label}" if other_label else ""
    return {
        "combined_label_code": f"{reference_role}.{daily}.{margin}",
        "combined_label": f"{role_label}·{suffix}" if reference_role in ROLE_SHORT_LABELS else role_label,
        "auxiliary_metric": auxiliary,
    }


def evaluate_confirmed_role_model(
    rows: Iterable[Mapping[str, Any]], *, t0: date
) -> dict[str, Any]:
    ordered = _normalized_rows(rows)
    nodes = build_rolling_role_nodes(ordered, start_date=HISTORY_START_DATE, end_date=t0)
    latest = nodes[-1] if nodes else None
    base = {
        "pre_oos_role": None,
        "role_evidence_status": "no_valid_role",
        "role_source_date": None,
        "valid_window_count": 0,
        "dominant_role": None,
        "dominant_role_share": 0.0,
        "role_switch_rate": 0.0,
        "confirmed_historical_stability": "insufficient",
        "recent_trend": "insufficient",
        "daily_sales_trend": None,
        "margin_trend": None,
        "combined_label_code": "no_valid_role",
        "combined_label": "无有效历史角色",
        "auxiliary_metric": "",
        "confirmed_role_nodes": nodes,
        "selected_role_windows": [],
    }
    if latest is None:
        return base
    if (t0 - HISTORY_START_DATE).days + 1 < 30:
        base.update(
            role_evidence_status="pre_oos_period_insufficient",
            combined_label_code="pre_oos_period_insufficient",
            combined_label="断货前周期不足",
        )
        return base
    if latest.get("state") == "data_anomaly":
        base.update(
            role_evidence_status="data_anomaly",
            combined_label_code="data_anomaly",
            combined_label="数据异常待核实",
        )
        return base
    role = str(latest.get("role") or "")
    if role not in ROLE_LEVEL:
        fallback = find_short_period_fallback(ordered, t0=t0)
        if fallback is None:
            return base
        if fallback["state"] == "data_anomaly":
            base.update(
                role_evidence_status="data_anomaly",
                combined_label_code="data_anomaly",
                combined_label="数据异常待核实",
            )
            return base
        role = str(fallback["role"])
        label = compose_operating_label(role, {"recent_trend": "insufficient"})
        base.update(
            pre_oos_role=role,
            role_evidence_status="short_period_fallback",
            role_source_date=fallback["window_end"],
            **label,
        )
        return base
    selected = select_confirmed_daily_role_nodes(nodes, t0=t0)
    selected_by_date = {_day(window["node_date"]): window for window in selected}
    for node in nodes:
        selected_node = selected_by_date.get(_day(node["node_date"]))
        node["selected_for_stability"] = selected_node is not None
        if selected_node is not None:
            for field in (
                "raw_role",
                "stability_role",
                "role_confirmation_state",
                "candidate_streak",
                "confirmed_role_change",
            ):
                node[field] = selected_node[field]
    stability = classify_historical_stability(selected, reference_role=role)
    trend_source = [
        {**window, "role": window["stability_role"]}
        for window in selected
    ]
    trend = classify_recent_trend(select_non_overlapping_windows(trend_source, t0=t0))
    label = compose_operating_label(role, trend)
    source_date = latest.get("source_node_date") or latest.get("node_date")
    base.update(
        pre_oos_role=role,
        role_evidence_status=(
            "carried"
            if latest.get("state") in {"carried_oos", "recovery_observation"}
            else "normal"
        ),
        role_source_date=_day(source_date),
        valid_window_count=stability["valid_window_count"],
        dominant_role=stability["dominant_role"],
        dominant_role_share=stability["dominant_role_share"],
        role_switch_rate=stability["role_switch_rate"],
        confirmed_historical_stability=stability["historical_stability"],
        recent_trend=trend["recent_trend"],
        daily_sales_trend=trend["daily_sales_trend"],
        margin_trend=trend["margin_trend"],
        selected_role_windows=selected,
        **label,
    )
    return base


def classify_historical_level(metrics: Mapping[str, Any]) -> str:
    if int(metrics.get("valid_node_count") or 0) < 8:
        return "unavailable"
    if float(metrics.get("in_stock_zero_sales_share") or 0) >= 0.60:
        return "in_stock_zero_sales"
    margin = metrics.get("historical_margin_rate")
    if margin is not None and float(margin) < 0:
        return "loss"
    if (margin is not None and 0 <= float(margin) < 0.05) or float(metrics.get("problem_role_share") or 0) >= 0.50:
        return "poor"
    if (
        float(metrics.get("star_role_share") or 0) >= 0.60
        and float(metrics.get("quality_role_share") or 0) >= 0.80
        and margin is not None
        and float(margin) >= 0.15
    ):
        return "excellent"
    if (
        float(metrics.get("quality_role_share") or 0) >= 0.60
        and float(metrics.get("problem_role_share") or 0) < 0.25
        and margin is not None
        and float(margin) >= 0.05
    ):
        return "good"
    return "normal"


def classify_stability(role: str, sales: str, margin: str) -> str:
    values = (role, sales, margin)
    if "unavailable" in values:
        return "unavailable"
    if values == ("stable", "stable", "stable"):
        return "highly_stable"
    if role == "high" or sum(value == "high" for value in values) >= 2:
        return "highly_volatile"
    if "high" not in values and sum(value == "stable" for value in values) >= 2:
        return "basically_stable"
    return "volatile"


def _confirmed_role_sequence(roles: Iterable[str]) -> tuple[list[str], int]:
    ranked = [role for role in roles if role in ROLE_LEVEL]
    if not ranked:
        return [], 0
    confirmed = [ranked[0]]
    transient = 0
    index = 1
    while index < len(ranked):
        role = ranked[index]
        if role == confirmed[-1]:
            index += 1
            continue
        run = 1
        while index + run < len(ranked) and ranked[index + run] == role:
            run += 1
        if run >= 2:
            confirmed.append(role)
        else:
            transient += 1
        index += run
    return confirmed, transient


def _role_change_metrics(roles: Iterable[str]) -> dict[str, Any]:
    raw = [role for role in roles if role in ROLE_LEVEL]
    confirmed, transient = _confirmed_role_sequence(raw)
    directions = []
    cross_level = 0
    for previous, current in zip(confirmed, confirmed[1:]):
        delta = ROLE_LEVEL[current] - ROLE_LEVEL[previous]
        directions.append(1 if delta > 0 else -1)
        if abs(delta) >= 2:
            cross_level += 1
    reversals = sum(1 for previous, current in zip(directions, directions[1:]) if previous != current)
    counts = Counter(raw)
    dominant_share = max(counts.values(), default=0) / len(raw) if raw else 0
    return {
        "confirmed": confirmed,
        "confirmed_role_switch_count": max(len(confirmed) - 1, 0),
        "confirmed_upgrade_count": sum(direction > 0 for direction in directions),
        "confirmed_downgrade_count": sum(direction < 0 for direction in directions),
        "role_reversal_count": reversals,
        "cross_level_switch_count": cross_level,
        "transient_role_fluctuation_count": transient,
        "dominant_role_share": dominant_share,
    }


def classify_role_pattern(roles: Iterable[str]) -> dict[str, Any]:
    raw = [role for role in roles if role in ROLE_LEVEL]
    metrics = _role_change_metrics(raw)
    third = len(raw) // 3
    if third < 3:
        code = "unavailable"
        early = late = None
    else:
        early_values = sorted(ROLE_LEVEL[role] for role in raw[:third])
        late_values = sorted(ROLE_LEVEL[role] for role in raw[-third:])
        early = statistics.median(early_values)
        late = statistics.median(late_values)
        if metrics["role_reversal_count"] >= 3 or (
            metrics["confirmed_role_switch_count"] >= 5
            and metrics["confirmed_upgrade_count"] > 0
            and metrics["confirmed_downgrade_count"] > 0
        ):
            code = "repeated_switching"
        elif (
            metrics["dominant_role_share"] >= 0.70
            and metrics["confirmed_role_switch_count"] <= 2
            and metrics["role_reversal_count"] <= 1
        ):
            code = "maintained"
        elif late >= early + 1 and metrics["confirmed_upgrade_count"] > metrics["confirmed_downgrade_count"] and metrics["role_reversal_count"] <= 1:
            code = "gradual_upgrade"
        elif late <= early - 1 and metrics["confirmed_downgrade_count"] > metrics["confirmed_upgrade_count"] and metrics["role_reversal_count"] <= 1:
            code = "gradual_downgrade"
        else:
            code = "mixed"
    return {"code": code, "label": ROLE_PATTERN_LABELS[code], "early_role_median": early, "late_role_median": late, **metrics}


def classify_pre_oos_role_change(roles: Mapping[str, str]) -> str:
    a, b, c, d = (roles.get(key, "unavailable") for key in ("a", "b", "c", "d"))
    if a == "in_stock_zero_sales" and (b in ROLE_LEVEL or c in ROLE_LEVEL):
        return "stopped_7d"
    if a in ROLE_LEVEL and b == "in_stock_zero_sales":
        return "started_7d"
    if not all(role in ROLE_LEVEL for role in (a, b, c)):
        return "unavailable"
    la, lb, lc = ROLE_LEVEL[a], ROLE_LEVEL[b], ROLE_LEVEL[c]
    if d in ROLE_LEVEL:
        ld = ROLE_LEVEL[d]
        values = [ld, lc, lb, la]
        deltas = [right - left for left, right in zip(values, values[1:])]
        if all(delta >= 0 for delta in deltas) and sum(delta > 0 for delta in deltas) >= 2:
            return "upgraded_90d"
        if all(delta <= 0 for delta in deltas) and sum(delta < 0 for delta in deltas) >= 2:
            return "downgraded_90d"
    if la >= lb >= lc and la > lc:
        return "upgraded_30d"
    if la <= lb <= lc and la < lc:
        return "downgraded_30d"
    if la > lb:
        return "upgraded_7d"
    if la < lb:
        return "downgraded_7d"
    if la == lb == lc:
        return "maintained"
    return "unclear"


def _weekly_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        iso = row["dt_date"].isocalendar()
        grouped[(iso.year, iso.week)].append(row)
    weeks = []
    for key in sorted(grouped):
        items = grouped[key]
        effective_days = sum(
            row["fba_available"] is not None and row["fba_available"] > 0
            for row in items
        )
        sales = sum(row["sales_qty"] for row in items)
        amount = sum(row["sales_amount"] for row in items)
        profit = sum(row["order_gross_profit"] for row in items)
        weeks.append(
            {
                "key": key,
                "days": effective_days,
                "effective_days": effective_days,
                "observed_days": len({row["dt_date"] for row in items}),
                "calendar_days": 7,
                "sales": sales,
                "daily_sales": sales / 7,
                "amount": amount,
                "profit": profit,
            }
        )
    effective = [week for week in weeks if week["effective_days"] >= 3]
    daily_sales = [week["daily_sales"] for week in effective]
    mean_sales = statistics.mean(daily_sales) if daily_sales else 0
    cv = statistics.pstdev(daily_sales) / mean_sales if len(daily_sales) >= 2 and mean_sales > 0 else None
    total_sales = sum(week["sales"] for week in effective)
    top3_share = sum(sorted((week["sales"] for week in effective), reverse=True)[:3]) / total_sales if total_sales > 0 else None
    margin_rates = [week["profit"] / week["amount"] for week in effective if week["amount"] > 0 and week["sales"] >= 5]
    margin_stddev = statistics.pstdev(margin_rates) * 100 if len(margin_rates) >= 2 else None
    loss_share = sum(rate < 0 for rate in margin_rates) / len(margin_rates) if margin_rates else None
    margin_reversals = sum(1 for left, right in zip(margin_rates, margin_rates[1:]) if (left < 0) != (right < 0))
    return {
        "effective_weeks": effective,
        "weekly_sales_cv": cv,
        "top_3_weeks_sales_share": top3_share,
        "margin_rates": margin_rates,
        "weekly_margin_stddev_pp": margin_stddev,
        "loss_week_share": loss_share,
        "margin_sign_reversal_count": margin_reversals,
    }


def _sub_stability(role_metrics: Mapping[str, Any], weekly: Mapping[str, Any], *, extreme_day: bool) -> tuple[str, str, str]:
    if (
        role_metrics["dominant_role_share"] >= 0.70
        and role_metrics["confirmed_role_switch_count"] <= 2
        and role_metrics["role_reversal_count"] <= 1
        and role_metrics["cross_level_switch_count"] <= 1
    ):
        role = "stable"
    elif (
        role_metrics["dominant_role_share"] < 0.50
        or role_metrics["confirmed_role_switch_count"] >= 5
        or role_metrics["role_reversal_count"] >= 3
        or role_metrics["cross_level_switch_count"] >= 3
    ):
        role = "high"
    else:
        role = "normal"
    cv = weekly["weekly_sales_cv"]
    top3 = weekly["top_3_weeks_sales_share"]
    week_count = len(weekly["effective_weeks"])
    if cv is None:
        sales = "unavailable"
    elif cv > 0.80 or (week_count >= 12 and top3 is not None and top3 >= 0.40) or extreme_day:
        sales = "high"
    elif cv <= 0.50 and (week_count < 12 or top3 is None or top3 < 0.40):
        sales = "stable"
    else:
        sales = "normal"
    stddev = weekly["weekly_margin_stddev_pp"]
    loss = weekly["loss_week_share"]
    reversals = weekly["margin_sign_reversal_count"]
    if len(weekly["margin_rates"]) < 6 or stddev is None or loss is None:
        margin = "unavailable"
    elif stddev > 10 or loss >= 0.30 or reversals >= 3:
        margin = "high"
    elif stddev <= 5 and loss <= 0.10:
        margin = "stable"
    else:
        margin = "normal"
    return role, sales, margin


def evaluate_stockout_history(
    rows: Iterable[Mapping[str, Any]],
    *,
    current_date: date,
    current_gate_status: str,
    current_gate_reason: str = "",
    scope_mode: str = "business_unit",
    current_oos_confirmed: bool = False,
) -> dict[str, Any]:
    if scope_mode not in {"business_unit", "country"}:
        raise ValueError("历史经营统计粒度不存在")
    ordered = _normalized_rows(rows)
    event = find_current_oos_event(
        ordered,
        current_date=current_date,
        current_oos_confirmed=current_oos_confirmed,
    )
    result: dict[str, Any] = {
        **event,
        "inventory_first_observed_date": ordered[0]["dt_date"] if ordered else None,
        "rule_version": RULE_VERSION,
        "current_gate_status": current_gate_status,
        "current_gate_reason": current_gate_reason,
        "history_window_start": HISTORY_START_DATE,
        "history_window_end": None,
        "historical_evaluable_status": "historical_evidence_insufficient",
        "historical_evaluable_reason": "",
        "historical_operating_level": None,
        "historical_stability": None,
        "historical_role_pattern": None,
        "pre_oos_role_change": None,
        "period_roles": {},
        "pre_oos_role": None,
        "role_evidence_status": "no_valid_role",
        "role_source_date": None,
        "valid_window_count": 0,
        "dominant_role": None,
        "dominant_role_share": 0.0,
        "role_switch_rate": 0.0,
        "confirmed_historical_stability": "insufficient",
        "recent_trend": "insufficient",
        "daily_sales_trend": None,
        "margin_trend": None,
        "combined_label_code": "no_valid_role",
        "combined_label": "无有效历史角色",
        "auxiliary_metric": "",
        "confirmed_role_nodes": [],
        "selected_role_windows": [],
    }
    if not event["current_oos_flag"]:
        result["historical_evaluable_reason"] = "not_current_oos"
        return result
    if event["oos_start_date"] is None:
        result["historical_evaluable_reason"] = event["oos_start_confidence"]
        if event["oos_start_confidence"] == "left_boundary_incomplete":
            result.update(
                role_evidence_status="oos_start_history_insufficient",
                combined_label_code="oos_start_history_insufficient",
                combined_label="断货起点历史不足",
            )
        return result
    t0 = event["oos_start_date"] - timedelta(days=1)
    result["history_window_end"] = t0
    if t0 < HISTORY_START_DATE:
        result["historical_evaluable_reason"] = "oos_before_history_start"
        return result
    history = [row for row in ordered if HISTORY_START_DATE <= row["dt_date"] <= t0]
    result.update(evaluate_confirmed_role_model(history, t0=t0))

    for period, minimum in PERIOD_MIN_EFFECTIVE_DAYS.items():
        days = int(period[:-1])
        window_start = t0 - timedelta(days=days - 1)
        period_rows = [row for row in history if window_start <= row["dt_date"] <= t0]
        evidence = _period_role(period_rows, scope_mode, minimum, days)
        evidence.update(window_start=window_start.isoformat(), window_end=t0.isoformat())
        result["period_roles"][period] = evidence

    fourteen_day_role = str((result["period_roles"].get("14d") or {}).get("role") or "")
    if (
        result["pre_oos_role"] is None
        and result["role_evidence_status"] in {"no_valid_role", "pre_oos_period_insufficient"}
        and fourteen_day_role in ROLE_LEVEL
    ):
        result.update(
            pre_oos_role=fourteen_day_role,
            role_evidence_status="short_period_fallback",
            role_source_date=t0,
            **compose_operating_label(
                fourteen_day_role,
                {"recent_trend": "insufficient"},
            ),
        )

    if current_gate_status != "evaluable":
        result["historical_evaluable_reason"] = current_gate_reason or "current_gate_not_evaluable"
        return result
    expected_days = (t0 - HISTORY_START_DATE).days + 1
    unique_dates = {row["dt_date"] for row in history}
    effective = [row for row in history if row["fba_available"] is not None and row["fba_available"] > 0]
    week_days: dict[tuple[int, int], int] = defaultdict(int)
    for row in effective:
        iso = row["dt_date"].isocalendar()
        week_days[(iso.year, iso.week)] += 1
    effective_weeks = sum(days >= 3 for days in week_days.values())
    gaps = _gap_ranges(history, window_start=HISTORY_START_DATE, window_end=t0)
    conflicts = [row for row in history if row["fba_available"] == 0 and row["sales_qty"] > 0]
    low_stock_days = sum(1 for row in effective if 1 <= row["fba_available"] <= 5)
    low_stock_share = low_stock_days / len(effective) if effective else 0
    history_sales = sum(row["sales_qty"] for row in effective)
    selling_days = sum(row["sales_qty"] > 0 for row in effective)
    max_day_share = max((row["sales_qty"] for row in effective), default=0) / history_sales if history_sales > 0 else 0
    result.update(
        history_span_days=expected_days,
        expected_calendar_days=expected_days,
        observed_daily_days=len(unique_dates),
        daily_coverage_rate=len(unique_dates) / expected_days if expected_days else 0,
        effective_operating_days=len(effective),
        effective_operating_weeks=effective_weeks,
        missing_date_gap_count=len(gaps),
        missing_date_gap_days=sum(gap["days"] for gap in gaps),
        inventory_sales_conflict_days=len(conflicts),
        inventory_sales_conflict_qty=sum(row["sales_qty"] for row in conflicts),
        low_stock_operating_days=low_stock_days,
        low_stock_operating_day_share=low_stock_share,
        low_stock_constrained=low_stock_share >= 0.30,
        selling_day_count=selling_days,
        max_day_sales_share=max_day_share,
        sales_concentration_flags={
            "few_selling_days": history_sales > 0 and selling_days <= 2,
            "single_day_concentrated": max_day_share >= 0.50,
            "extreme_single_day_concentrated": max_day_share >= 0.80,
        },
        missing_date_gaps=gaps,
    )
    if expected_days < 90:
        result["historical_evaluable_reason"] = "history_span_lt_90"
        return result
    if result["daily_coverage_rate"] < 0.80:
        result["historical_evaluable_reason"] = "daily_coverage_lt_80pct"
        return result
    if len(effective) < 30 or effective_weeks < 8:
        result["historical_evaluable_status"] = "stockout_history_only"
        result["historical_evaluable_reason"] = "effective_days_or_weeks_insufficient"
        return result

    result["historical_evaluable_status"] = "historical_operating_evaluable"
    result["historical_evaluable_reason"] = "all_thresholds_met"

    rolling = []
    node_end = HISTORY_START_DATE + timedelta(days=29)
    while node_end <= t0:
        window_start = node_end - timedelta(days=29)
        node_rows = [row for row in history if window_start <= row["dt_date"] <= node_end]
        evidence = _period_role(node_rows, scope_mode, PERIOD_MIN_EFFECTIVE_DAYS["30d"], 30)
        evidence.update(window_start=window_start.isoformat(), window_end=node_end.isoformat())
        rolling.append(evidence)
        node_end += timedelta(days=7)
    valid_roles = [node["role"] for node in rolling if node["role"] != "unavailable"]
    counts = Counter(valid_roles)
    valid_count = len(valid_roles)
    shares = {role: counts[role] / valid_count if valid_count else 0 for role in ROLE_LABELS}
    historical_amount = sum(row["sales_amount"] for row in history)
    historical_profit = sum(row["order_gross_profit"] for row in history)
    level_metrics = {
        "valid_node_count": valid_count,
        "star_role_share": shares["star"],
        "quality_role_share": shares["star"] + shares["potential"],
        "problem_role_share": shares["problem"] + shares["in_stock_zero_sales"],
        "in_stock_zero_sales_share": shares["in_stock_zero_sales"],
        "historical_margin_rate": historical_profit / historical_amount if historical_amount > 0 else None,
    }
    level = classify_historical_level(level_metrics)
    role_pattern = classify_role_pattern(valid_roles)
    role_metrics = _role_change_metrics(valid_roles)
    weekly = _weekly_metrics(history)
    role_stability, sales_stability, margin_stability = _sub_stability(
        role_metrics,
        weekly,
        extreme_day=max_day_share >= 0.80,
    )
    stability = (
        classify_stability(role_stability, sales_stability, margin_stability)
        if valid_count >= 8 and effective_weeks >= 8 and len(weekly["effective_weeks"]) >= 7 and len(weekly["margin_rates"]) >= 6
        else "unavailable"
    )

    segments = {}
    for key, start_offset, end_offset, minimum in (
        ("a", 1, 7, 5),
        ("b", 8, 14, 5),
        ("c", 15, 30, 11),
        ("d", 31, 90, 42),
    ):
        segment_rows = [row for row in history if t0 - timedelta(days=end_offset - 1) <= row["dt_date"] <= t0 - timedelta(days=start_offset - 1)]
        segments[key] = _period_role(
            segment_rows,
            scope_mode,
            minimum,
            end_offset - start_offset + 1,
        )["role"]
    pre_change = classify_pre_oos_role_change(segments)
    result.update(
        historical_operating_level=level,
        historical_operating_level_label=HISTORICAL_LEVEL_LABELS[level],
        historical_margin_rate=level_metrics["historical_margin_rate"],
        valid_role_node_count=valid_count,
        role_node_shares=shares,
        rolling_role_nodes=rolling,
        historical_stability=stability,
        historical_stability_label=STABILITY_LABELS[stability],
        role_stability=role_stability,
        sales_stability=sales_stability,
        margin_stability=margin_stability,
        historical_role_pattern=role_pattern["code"],
        historical_role_pattern_label=role_pattern["label"],
        pre_oos_role_change=pre_change,
        pre_oos_role_change_label=PRE_OOS_CHANGE_LABELS[pre_change],
        segment_roles=segments,
        **role_metrics,
        weekly_sales_cv=weekly["weekly_sales_cv"],
        top_3_weeks_sales_share=weekly["top_3_weeks_sales_share"],
        weekly_margin_stddev_pp=weekly["weekly_margin_stddev_pp"],
        loss_week_share=weekly["loss_week_share"],
        margin_sign_reversal_count=weekly["margin_sign_reversal_count"],
    )
    return result
