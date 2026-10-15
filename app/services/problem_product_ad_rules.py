from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping


OBJECT_DIAGNOSIS_RULES = frozenset({1024, 1025, 1028})
ACTIVATION_RULES = frozenset({1014, 2021, 2031})
BUDGET_FOLLOW_UP_RULES = frozenset({1015, 1026, 2022, 2023, 2033})
MANUAL_REVIEW_RULES = frozenset({1016, 1027, 2024})
EXCLUDED_RULES = frozenset({2032, 2053})


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def classify_problem_product_strategy(rule_code: Any) -> str:
    """Classify only the product-strategy actions approved for ad handling."""
    try:
        code = int(rule_code)
    except (TypeError, ValueError):
        return "excluded"
    if code in OBJECT_DIAGNOSIS_RULES:
        return "object_diagnosis"
    if code in ACTIVATION_RULES:
        return "activation"
    if code in BUDGET_FOLLOW_UP_RULES:
        return "budget_follow_up"
    if code in MANUAL_REVIEW_RULES:
        return "manual_review"
    return "excluded"


def _stage(enabled_days: int) -> tuple[str, Decimal]:
    if enabled_days <= 14:
        return "new", Decimal("0.28")
    if enabled_days <= 30:
        return "growth", Decimal("0.23")
    return "mature", Decimal("0.20")


def _cvr_adjustment(rate: Decimal, cvr: Decimal | None) -> Decimal:
    if cvr is None:
        return rate
    if cvr >= Decimal("0.11"):
        return rate + Decimal("0.05") if rate > 0 else rate - Decimal("0.05")
    if cvr >= Decimal("0.08"):
        return rate + Decimal("0.03") if rate > 0 else rate - Decimal("0.03")
    if cvr < Decimal("0.05"):
        return rate - Decimal("0.03") if rate > 0 else rate - Decimal("0.03")
    return rate


def _increase_rate(deviation: Decimal, orders: Decimal, saturation: Decimal, improving: bool) -> tuple[Decimal, str] | None:
    rules = (
        (Decimal("-0.08"), Decimal("10"), Decimal("0.95"), Decimal("0.35"), "hot_large_increase_1"),
        (Decimal("-0.06"), Decimal("10"), Decimal("0.90"), Decimal("0.28"), "hot_large_increase_2"),
        (Decimal("-0.04"), Decimal("10"), Decimal("0.85"), Decimal("0.22"), "hot_medium_increase"),
        (Decimal("-0.03"), Decimal("0"), Decimal("0.90"), Decimal("0.18"), "quality_medium_increase_1"),
        (Decimal("-0.02"), Decimal("0"), Decimal("0.85"), Decimal("0.15"), "quality_medium_increase_2"),
        (Decimal("-0.01"), Decimal("0"), Decimal("0.80"), Decimal("0.12"), "quality_small_increase_1"),
    )
    for deviation_limit, order_limit, saturation_limit, rate, reason in rules:
        if deviation < deviation_limit and orders >= order_limit and saturation >= saturation_limit:
            return rate, reason
    if abs(deviation) <= Decimal("0.01") and saturation >= Decimal("0.75"):
        return Decimal("0.10"), "stable_small_increase"
    if abs(deviation) <= Decimal("0.02") and saturation >= Decimal("0.70") and improving:
        return Decimal("0.08"), "improving_increase"
    if abs(deviation) <= Decimal("0.03") and saturation >= Decimal("0.65"):
        return Decimal("0.05"), "stable_micro_increase"
    return None


def _decrease_rate(deviation: Decimal, cvr: Decimal | None, ctr: Decimal | None) -> tuple[Decimal, str] | None:
    for threshold, rate, reason in (
        (Decimal("0.12"), Decimal("-0.45"), "acos_severe_decrease"),
        (Decimal("0.10"), Decimal("-0.35"), "acos_heavy_decrease"),
        (Decimal("0.07"), Decimal("-0.25"), "acos_medium_decrease"),
        (Decimal("0.05"), Decimal("-0.15"), "acos_light_decrease"),
        (Decimal("0.03"), Decimal("-0.08"), "acos_micro_decrease"),
    ):
        if deviation > threshold:
            return rate, reason
    if cvr is not None and cvr < Decimal("0.05"):
        return Decimal("-0.12"), "cvr_poor_decrease"
    if ctr is not None and ctr < Decimal("0.002"):
        return Decimal("-0.10"), "ctr_low_decrease"
    return None


def calculate_campaign_budget_recommendation(row: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the approved lifecycle budget rules using only the current daily budget."""
    current = _decimal(row.get("current_daily_budget"))
    if current is None or current <= 0:
        return {"status": "insufficient_data", "suggested_daily_budget": None, "change_rate": None, "reason_code": "current_budget_missing"}
    if row.get("enabled_last_10_days") is not True:
        return {"status": "ineligible", "suggested_daily_budget": None, "change_rate": None, "reason_code": "not_enabled_continuously_10_days"}

    clicks = _decimal(row.get("clicks_7d")) or Decimal(0)
    if clicks < 10:
        return {"status": "ineligible", "suggested_daily_budget": None, "change_rate": None, "reason_code": "clicks_lt_10"}
    if row.get("changed_last_3_days"):
        return {"status": "skip", "suggested_daily_budget": None, "change_rate": None, "reason_code": "budget_changed_last_3_days"}

    enabled_days = int(row.get("enabled_days") or 0)
    stage, target_acos = _stage(enabled_days)
    orders = _decimal(row.get("orders_7d")) or Decimal(0)
    cost = _decimal(row.get("cost_7d")) or Decimal(0)
    sales = _decimal(row.get("sales_7d")) or Decimal(0)
    impressions = _decimal(row.get("impressions_7d")) or Decimal(0)
    acos = cost / sales if sales > 0 else None
    cvr = orders / clicks if clicks > 0 else None
    ctr = clicks / impressions if impressions > 0 else None
    saturation = cost / (current * Decimal(7))

    if orders == 0:
        protected = stage != "mature" and (enabled_days <= 20 or cost <= Decimal("100") or clicks < 50)
        if protected:
            return {"status": "keep", "suggested_daily_budget": current.quantize(Decimal("0.01")), "change_rate": Decimal(0), "reason_code": f"{stage}_zero_order_protected"}
        return {"status": "pause", "suggested_daily_budget": Decimal(0), "change_rate": Decimal("-1"), "reason_code": f"{stage}_zero_order_pause"}

    if acos is None:
        return {"status": "insufficient_data", "suggested_daily_budget": None, "change_rate": None, "reason_code": "sales_missing"}
    deviation = acos - target_acos
    decision = _decrease_rate(deviation, cvr, ctr) or _increase_rate(
        deviation, orders, saturation, bool(row.get("acos_improving"))
    )
    if decision is None:
        return {"status": "keep", "suggested_daily_budget": current.quantize(Decimal("0.01")), "change_rate": Decimal(0), "reason_code": f"{stage}_keep"}

    rate, reason = decision
    rate = _cvr_adjustment(rate, cvr)
    suggested = max(Decimal("1"), current * (Decimal(1) + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "status": "increase" if rate > 0 else "decrease",
        "suggested_daily_budget": suggested,
        "change_rate": rate,
        "reason_code": f"{stage}_{reason}",
    }
