from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Literal, Mapping


ASIN_RE = re.compile(r"^B[0-9A-Z]{9}$", re.IGNORECASE)
CENT = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return numerator / denominator if denominator else None


def mature_window(cutoff: date) -> tuple[date, date]:
    end = cutoff - timedelta(days=7)
    return end - timedelta(days=29), end


def classify_search_term(text: str) -> Literal["keyword", "product_target"]:
    return "product_target" if ASIN_RE.fullmatch((text or "").strip()) else "keyword"


def _mapping_reason(row: Mapping[str, Any]) -> str | None:
    status = str(row.get("msku_mapping_status") or "").strip()
    if status == "mapped":
        return None
    if status in {
        "msku_missing",
        "period_multiple_msku",
        "current_multiple_msku",
        "msku_changed",
    }:
        return status
    count = int(row.get("associated_msku_count", 1) or 0)
    if count == 0:
        return "msku_missing"
    if count != 1:
        return "multiple_msku"
    return None


def calculate_add_recommendation(row: Mapping[str, Any]) -> dict[str, Any]:
    term = str(row.get("search_term") or "").strip()
    kind = classify_search_term(term)
    suggestion_type = "product_target" if kind == "product_target" else "exact_keyword"
    orders = _decimal(row.get("orders")) or Decimal(0)
    cost = _decimal(row.get("cost")) or Decimal(0)
    sales = _decimal(row.get("sales")) or Decimal(0)
    acos = _ratio(cost, sales)
    mapping_reason = _mapping_reason(row)
    warnings = [mapping_reason] if mapping_reason else []

    existing_state = str(row.get("existing_state") or "")
    if row.get("existing_enabled") or existing_state == "enabled":
        return {
            "status": "existing",
            "priority": "none",
            "suggestion_type": suggestion_type,
            "suggestion_value": term,
            "acos": acos,
            "reason_codes": ["existing_enabled", *warnings],
        }
    if existing_state == "inactive":
        return {
            "status": "existing_inactive",
            "priority": "none",
            "suggestion_type": suggestion_type,
            "suggestion_value": term,
            "acos": acos,
            "reason_codes": ["existing_inactive", *warnings],
        }

    if orders >= 10 and acos is not None and acos <= Decimal("0.10"):
        status, priority = "recommended", "highest"
        decision_reason = "orders_ge_10_acos_le_10"
    elif orders >= 10 and acos is not None and acos <= Decimal("0.15"):
        status, priority = "recommended", "medium"
        decision_reason = "orders_ge_10_acos_le_15"
    else:
        status, priority = "observe", "none"
        decision_reason = "threshold_not_met"
    return {
        "status": status,
        "priority": priority,
        "suggestion_type": suggestion_type,
        "suggestion_value": term,
        "acos": acos,
        "reason_codes": [decision_reason, *warnings],
    }


def calculate_negative_recommendation(row: Mapping[str, Any]) -> dict[str, Any]:
    term = str(row.get("search_term") or "").strip()
    kind = classify_search_term(term)
    suggestion_type = (
        "negative_product_target" if kind == "product_target" else "negative_exact"
    )
    clicks = _decimal(row.get("clicks")) or Decimal(0)
    orders = _decimal(row.get("orders")) or Decimal(0)
    base = {
        "suggestion_type": suggestion_type,
        "suggestion_value": term,
        "priority": "none",
    }
    mapping_reason = _mapping_reason(row)
    warnings = [mapping_reason] if mapping_reason else []
    if clicks < 10 or orders != 0:
        return {**base, "status": "observe", "reason_codes": ["threshold_not_met", *warnings]}

    if mapping_reason:
        return {
            **base,
            "status": "manual_review",
            "priority": "high",
            "reason_codes": warnings,
        }
    if row.get("term_protection_complete", True) is False:
        missing_codes = list(row.get("protection_missing_codes") or ["term_protection_context_missing"])
        return {
            **base,
            "status": "manual_review",
            "priority": "high",
            "reason_codes": missing_codes,
        }

    protected_reasons = []
    for field, reason in (
        ("is_brand_term", "brand_term"),
        ("is_core_category_term", "core_category_term"),
        ("is_new_product_term", "new_product_term"),
    ):
        if row.get(field):
            protected_reasons.append(reason)
    if protected_reasons:
        return {
            **base,
            "status": "manual_review",
            "priority": "high",
            "reason_codes": protected_reasons,
        }
    return {
        **base,
        "status": "recommended",
        "priority": "high",
        "reason_codes": ["clicks_ge_10_orders_zero", *warnings],
    }


def calculate_bid_recommendation(row: Mapping[str, Any]) -> dict[str, Any]:
    mapping_reason = _mapping_reason(row)
    current = _decimal(row.get("current_bid"))
    aov = _decimal(row.get("aov"))
    cvr = _decimal(row.get("cvr"))
    margin = _decimal(row.get("margin_rate"))
    reasons: list[str] = []

    if mapping_reason:
        reasons.append(mapping_reason)
    if row.get("price_mapped", True) is False:
        reasons.append("price_not_mapped")
    if row.get("margin_ladder_complete", True) is False:
        reasons.append("margin_ladder_missing")
    if row.get("below_zero_margin_price", False):
        reasons.append("below_zero_margin_price")
    if reasons:
        return {
            "status": "manual_review",
            "suggested_bid": None,
            "change_direction": None,
            "change_amount": None,
            "change_rate": None,
            "theoretical_cpc": None,
            "reference_cpc_20": None,
            "reference_cpc_333": None,
            "reason_codes": reasons,
        }

    if current is None or current <= 0:
        return {
            "status": "insufficient_data",
            "suggested_bid": None,
            "change_direction": None,
            "change_amount": None,
            "change_rate": None,
            "theoretical_cpc": None,
            "reference_cpc_20": None,
            "reference_cpc_333": None,
            "reason_codes": ["metric_missing"],
        }

    clicks = _decimal(row.get("clicks")) or Decimal(0)
    orders = _decimal(row.get("orders")) or Decimal(0)
    cost = _decimal(row.get("cost")) or Decimal(0)
    sales = _decimal(row.get("sales")) or Decimal(0)
    acos = cost / sales if sales > 0 else None
    theoretical = aov * cvr * margin if aov is not None and cvr is not None and margin is not None else None
    reference_20 = aov * cvr * Decimal("0.20") if aov is not None and cvr is not None else None
    reference_333 = aov * cvr * Decimal("0.333") if aov is not None and cvr is not None else None

    def result(suggested: Decimal | None, status: str, reason_codes: list[str]) -> dict[str, Any]:
        change = suggested - current if suggested is not None else None
        effective_status = status
        effective_reasons = list(reason_codes)
        if change == 0 and status in {"increase", "decrease"}:
            effective_status = "keep"
            effective_reasons.append("minimum_bid_increment_blocks_change")
        return {
            "status": effective_status,
            "suggested_bid": suggested,
            "change_direction": "increase" if change is not None and change > 0 else "decrease" if change is not None and change < 0 else "keep" if change is not None else None,
            "change_amount": change.quantize(CENT) if change is not None else None,
            "change_rate": (change / current).quantize(FOUR_PLACES) if change is not None else None,
            "theoretical_cpc": theoretical.quantize(FOUR_PLACES) if theoretical is not None else None,
            "reference_cpc_20": reference_20.quantize(FOUR_PLACES) if reference_20 is not None else None,
            "reference_cpc_333": reference_333.quantize(FOUR_PLACES) if reference_333 is not None else None,
            "reason_codes": effective_reasons,
        }

    def decrease(min_rate: Decimal, max_rate: Decimal, reason: str) -> dict[str, Any]:
        ideal_rate = max_rate if theoretical is None else max(Decimal(0), (current - theoretical) / current)
        rate = min(max(ideal_rate, min_rate), max_rate)
        suggested = (current * (Decimal(1) - rate)).quantize(CENT, rounding=ROUND_CEILING)
        return result(suggested, "decrease", [reason, "theoretical_cpc_guard"] if theoretical is not None else [reason])

    if clicks >= 15 and orders == 0:
        return decrease(Decimal("0.20"), Decimal("0.30"), "clicks_ge_15_orders_zero")
    if clicks >= 20 and orders >= 1 and acos is not None and acos > Decimal("0.50"):
        return decrease(Decimal("0.20"), Decimal("0.30"), "acos_gt_50")
    if clicks >= 20 and orders >= 1 and acos is not None and acos > Decimal("0.333"):
        return decrease(Decimal("0.10"), Decimal("0.20"), "acos_gt_333")

    if theoretical is None:
        return result(None, "insufficient_data", ["metric_missing"])

    site_avg = _decimal(row.get("site_cvr_avg"))
    site_p75 = _decimal(row.get("site_cvr_p75"))
    high_increase = clicks >= 20 and orders >= 3 and acos is not None and acos <= Decimal("0.15") and site_p75 is not None and cvr >= site_p75 and theoretical > current
    small_increase = clicks >= 20 and orders >= 3 and acos is not None and acos <= Decimal("0.20") and site_avg is not None and cvr >= site_avg and theoretical > current
    if (high_increase or small_increase) and (
        row.get("inventory_sufficient", True) is False
        or row.get("budget_sufficient", True) is False
    ):
        protection = []
        if row.get("inventory_sufficient", True) is False:
            protection.append("inventory_blocks_increase")
        if row.get("budget_sufficient", True) is False:
            protection.append("budget_blocks_increase")
        return result(current.quantize(CENT), "keep", protection)

    if high_increase or small_increase:
        increase_cap = Decimal("1.20") if high_increase else Decimal("1.10")
        raw_suggestion = min(theoretical, current * increase_cap)
        suggested = raw_suggestion.quantize(CENT, rounding=ROUND_FLOOR)
        return result(suggested, "increase", ["high_cvr_increase" if high_increase else "site_avg_cvr_increase", "theoretical_cpc_guard"])
    if clicks >= 10 and acos is not None and acos <= Decimal("0.333"):
        return result(current.quantize(CENT), "keep", ["performance_within_guardrail"])
    return result(None, "insufficient_data", ["threshold_not_met"])
