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
    reasons: list[str] = []

    if row.get("existing_enabled"):
        return {
            "status": "existing",
            "priority": "none",
            "suggestion_type": suggestion_type,
            "suggestion_value": term,
            "acos": acos,
            "reason_codes": ["existing_enabled"],
        }

    mapping_reason = _mapping_reason(row)
    if mapping_reason:
        return {
            "status": "manual_review",
            "priority": "none",
            "suggestion_type": suggestion_type,
            "suggestion_value": term,
            "acos": acos,
            "reason_codes": [mapping_reason],
        }

    if orders >= 10 and acos is not None and acos <= Decimal("0.10"):
        status, priority = "recommended", "highest"
        reasons.append("orders_ge_10_acos_le_10")
    elif orders >= 10 and acos is not None and acos <= Decimal("0.15"):
        status, priority = "recommended", "medium"
        reasons.append("orders_ge_10_acos_le_15")
    else:
        status, priority = "observe", "none"
        reasons.append("threshold_not_met")
    return {
        "status": status,
        "priority": priority,
        "suggestion_type": suggestion_type,
        "suggestion_value": term,
        "acos": acos,
        "reason_codes": reasons,
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
    if clicks < 100 or orders != 0:
        return {**base, "status": "observe", "reason_codes": ["threshold_not_met"]}

    reasons = []
    mapping_reason = _mapping_reason(row)
    if mapping_reason:
        reasons.append(mapping_reason)
    if row.get("protection_complete", True) is False:
        reasons.append("protection_missing")
    for field, reason in (
        ("is_brand_term", "brand_term"),
        ("is_core_category_term", "core_category_term"),
        ("is_new_product_term", "new_product_term"),
    ):
        if row.get(field):
            reasons.append(reason)
    if reasons:
        return {**base, "status": "manual_review", "reason_codes": reasons}
    return {
        **base,
        "status": "recommended",
        "priority": "high",
        "reason_codes": ["clicks_ge_100_orders_zero"],
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

    if current is None or current <= 0 or aov is None or cvr is None or margin is None:
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

    theoretical = aov * cvr * margin
    reference_20 = aov * cvr * Decimal("0.20")
    reference_333 = aov * cvr * Decimal("0.333")
    if theoretical > current and (
        row.get("inventory_sufficient", True) is False
        or row.get("budget_sufficient", True) is False
    ):
        protection = []
        if row.get("inventory_sufficient", True) is False:
            protection.append("inventory_blocks_increase")
        if row.get("budget_sufficient", True) is False:
            protection.append("budget_blocks_increase")
        return {
            "status": "keep",
            "suggested_bid": current.quantize(CENT),
            "change_direction": "keep",
            "change_amount": Decimal("0.00"),
            "change_rate": Decimal("0.00"),
            "theoretical_cpc": theoretical.quantize(FOUR_PLACES),
            "reference_cpc_20": reference_20.quantize(FOUR_PLACES),
            "reference_cpc_333": reference_333.quantize(FOUR_PLACES),
            "reason_codes": protection,
        }

    if theoretical > current:
        raw_suggestion = min(theoretical, current * Decimal("1.20"))
        suggested = raw_suggestion.quantize(CENT, rounding=ROUND_FLOOR)
    elif theoretical < current:
        raw_suggestion = max(theoretical, current * Decimal("0.70"))
        suggested = raw_suggestion.quantize(CENT, rounding=ROUND_CEILING)
    else:
        suggested = current.quantize(CENT)

    change = suggested - current
    if change > 0:
        status, direction = "increase", "increase"
    elif change < 0:
        status, direction = "decrease", "decrease"
    else:
        status, direction = "keep", "keep"
    return {
        "status": status,
        "suggested_bid": suggested,
        "change_direction": direction,
        "change_amount": change.quantize(CENT),
        "change_rate": (change / current).quantize(FOUR_PLACES),
        "theoretical_cpc": theoretical.quantize(FOUR_PLACES),
        "reference_cpc_20": reference_20.quantize(FOUR_PLACES),
        "reference_cpc_333": reference_333.quantize(FOUR_PLACES),
        "reason_codes": ["theoretical_cpc_guard"],
    }

