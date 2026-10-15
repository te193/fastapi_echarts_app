"""Pure, review-only rules for problem-product SP advertising actions.

This module intentionally does not call advertising APIs.  Its output is a
structured ``MANUAL_REVIEW`` recommendation which the decision-base exporter
can persist and an operator can review.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


TACOS_NORMAL_LIMIT = 0.05
TACOS_EXPANSION_LIMIT = 0.10
ADD_EXACT_ACOS_LIMIT = 0.20


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_bid(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _tacos_status(tacos: Any) -> str:
    value = _number(tacos)
    if value is None:
        return "缺失"
    if value <= TACOS_NORMAL_LIMIT:
        return "正常放量"
    if value < TACOS_EXPANSION_LIMIT:
        return "受控放量"
    return "禁止自动放量"


def _budget_available(value: Any) -> bool:
    text = str(value or "").strip()
    return text in {"预算充足", "可用", "正常", "支持"} or "充足" in text


def _base_action(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": row.get("path", ""),
        "action": "观察",
        "execution_control": "MANUAL_REVIEW",
        "search_term": row.get("search_term"),
        "object_id": row.get("object_id"),
        "object_text": row.get("object_text"),
        "tacos_status": _tacos_status(row.get("tacos")),
        "budget_status": str(row.get("budget_status") or "预算状态缺失"),
        "profit_guardrail_status": "价格不低于P10",
        "blocked_reasons": [],
        "rounding_policy": "",
    }


def _scale_blockers(row: dict[str, Any], action: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    tacos = _number(row.get("tacos"))
    if tacos is None:
        reasons.append("TACOS缺失，不能自动放量")
    elif tacos >= TACOS_EXPANSION_LIMIT:
        reasons.append("TACOS≥10%，不自动放量")
    if not _budget_available(row.get("budget_status")):
        reasons.append("预算受限，涨竞价或加精准词转人工")
    return reasons


def _set_bid(action: dict[str, Any], row: dict[str, Any], change_rate: float, *, automatic: bool) -> dict[str, Any]:
    bid = _number(row.get("current_bid"))
    if bid is None or bid <= 0:
        action["blocked_reasons"].append("当前竞价缺失或异常")
        return action
    candidate = _round_bid(max(0.0, bid * (1 + change_rate)))
    if candidate == bid:
        if automatic:
            candidate = _round_bid(max(0.0, bid + (0.01 if change_rate > 0 else -0.01)))
        else:
            action["blocked_reasons"].append("两位小数后无有效变动")
            return action
    if candidate == bid:
        action["blocked_reasons"].append("竞价已达可调整边界")
        return action
    action.update({
        "action": "提高竞价" if change_rate > 0 else "降低竞价",
        "change_rate": change_rate,
        "current_bid": _round_bid(bid),
        "suggested_bid": candidate,
        "rounding_policy": "自动路径最小变动0.01" if automatic else "手动词路径仅两位小数，不补最小变动",
    })
    return action


def _manual_keyword(row: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    clicks = _number(row.get("clicks"))
    orders = _number(row.get("orders"))
    if clicks is None or orders is None:
        action["blocked_reasons"].append("成熟30天点击或订单缺失，待核数据")
        return action
    acos = _number(row.get("acos"))
    if orders >= 2 and acos is not None:
        if acos >= 0.50:
            return _set_bid(action, row, -0.20, automatic=False)
        if acos > 0.30:
            return _set_bid(action, row, -0.10, automatic=False)
        blockers = _scale_blockers(row, action)
        if blockers:
            action["blocked_reasons"].extend(blockers)
            return action
        if clicks >= 10 and acos <= 0.20:
            rate = 0.10 if (_number(row.get("tacos")) or 0) <= TACOS_NORMAL_LIMIT else 0.05
            return _set_bid(action, row, rate, automatic=False)
    if orders == 0:
        if clicks >= 34:
            return _set_bid(action, row, -0.15, automatic=False)
        if clicks >= 12:
            return _set_bid(action, row, -0.10, automatic=False)
    action["blocked_reasons"].append("未满足成熟30天手动关键词调整条件")
    return action


def _auto_bid(row: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    clicks = _number(row.get("clicks")) or 0
    orders = _number(row.get("orders")) or 0
    acos = _number(row.get("acos"))
    cvr = _number(row.get("cvr")) or 0
    if orders == 0:
        if clicks >= 63:
            return _set_bid(action, row, -0.20, automatic=True)
        if clicks >= 34:
            return _set_bid(action, row, -0.10, automatic=True)
    elif orders == 1:
        if clicks >= 63:
            return _set_bid(action, row, -0.10, automatic=True)
        if clicks >= 34 and ((acos is not None and acos > 0.50) or cvr < 0.03):
            return _set_bid(action, row, -0.05, automatic=True)
    elif acos is not None:
        if acos > 0.65:
            return _set_bid(action, row, -0.20, automatic=True)
        if acos >= 0.50:
            return _set_bid(action, row, -0.10, automatic=True)
        if acos >= 0.40 and cvr < 0.03:
            return _set_bid(action, row, -0.05, automatic=True)
        blockers = _scale_blockers(row, action)
        if blockers:
            action["blocked_reasons"].extend(blockers)
            return action
        if clicks >= 80 and orders >= 5 and acos <= 0.20 and cvr >= 0.07:
            return _set_bid(action, row, 0.15, automatic=True)
        if clicks >= 40 and orders >= 3 and acos <= 0.30 and cvr >= 0.07:
            return _set_bid(action, row, 0.10, automatic=True)
        if clicks >= 15 and orders >= 2 and acos <= 0.40 and cvr >= 0.05:
            return _set_bid(action, row, 0.05, automatic=True)
    action["blocked_reasons"].append("未满足成熟30天自动投放竞价调整条件")
    return action


def _auto_to_exact(row: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    clicks = _number(row.get("clicks")) or 0
    orders = _number(row.get("orders")) or 0
    sales = _number(row.get("sales")) or 0
    cost = _number(row.get("cost")) or 0
    acos = _number(row.get("acos"))
    protected = bool(row.get("term_protection_complete"))
    if not bool(row.get("is_auto_campaign")):
        action["blocked_reasons"].append("非自动广告来源，不创建手动精准词")
    if str(row.get("search_term_type") or "").lower() == "asin":
        action["blocked_reasons"].append("ASIN搜索词不走手动精准加词")
    if not protected:
        action["blocked_reasons"].append("搜索词保护校验不完整")
    if bool(row.get("has_manual_exact")):
        action["blocked_reasons"].append("已存在同词手动精准投放")
    if bool(row.get("negative_conflict")):
        action["blocked_reasons"].append("与现有否词冲突")
    if acos is None and sales > 0:
        acos = cost / sales
    if clicks < 10 or orders < 1 or acos is None or acos > 0.30:
        action["blocked_reasons"].append("未满足稳定加词门槛")
    action["blocked_reasons"].extend(_scale_blockers({**row, "acos": acos}, action))
    if action["blocked_reasons"]:
        return action
    source_cpc = _number(row.get("source_cpc"))
    cpc_cap = sales / clicks * ADD_EXACT_ACOS_LIMIT if clicks else None
    if source_cpc is None or cpc_cap is None:
        action["blocked_reasons"].append("缺少来源CPC或可计算CPC上限")
        return action
    action.update({
        "action": "创建手动精准词",
        "suggested_bid": _round_bid(min(source_cpc, cpc_cap)),
        "rounding_policy": "手动词路径仅两位小数，不补最小变动",
        "review_metric": "汇总原自动词与新精准词的订单、销售额、花费",
    })
    return action


def _auto_negative(row: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    clicks = _number(row.get("clicks")) or 0
    orders = _number(row.get("orders")) or 0
    if not bool(row.get("term_protection_complete")):
        action["blocked_reasons"].append("搜索词保护校验不完整")
    if any(bool(row.get(field)) for field in ("is_brand_term", "is_core_category_term", "is_new_product_term")):
        action["blocked_reasons"].append("品牌/核心类目/新品词转人工")
    if orders > 0:
        action["blocked_reasons"].append("有订单搜索词不自动否定")
    if clicks < 49:
        action["blocked_reasons"].append("点击未达否词候选门槛49")
    if action["blocked_reasons"]:
        return action
    is_asin = str(row.get("search_term_type") or "").lower() == "asin"
    action.update({
        "action": "添加否定商品投放" if is_asin else "添加精准否定词",
        "confidence": "高" if clicks >= 63 else "常规",
        "negative_reason": "零订单且点击≥63" if clicks >= 63 else "零订单且点击49–62",
    })
    return action


def _zero_spend_exposure(row: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Allow one small bid test only for an enabled entity with no ad spend."""
    inventory_status = str(row.get("inventory_status") or "库存状态缺失").strip()
    if not _budget_available(row.get("budget_status")):
        action["blocked_reasons"].append("预算受限")
    if inventory_status != "库存充足":
        action["blocked_reasons"].append(inventory_status)
    if action["blocked_reasons"]:
        return action
    action = _set_bid(action, row, 0.10, automatic=True)
    if action["action"] != "观察":
        action["exposure_test"] = True
        action["review_metric"] = "7天内检查曝光、点击、花费与预算状态；不以零花费期判断ACOS"
    return action


def build_ad_action(row: dict[str, Any]) -> dict[str, Any]:
    """Build one review action; paths are isolated to avoid rule interference."""
    action = _base_action(row)
    path = row.get("path")
    if path == "manual_keyword":
        return _manual_keyword(row, action)
    if path == "auto_bid":
        return _auto_bid(row, action)
    if path == "auto_to_exact":
        return _auto_to_exact(row, action)
    if path == "auto_negative":
        return _auto_negative(row, action)
    if path == "zero_spend_exposure":
        return _zero_spend_exposure(row, action)
    action["blocked_reasons"].append("未知广告路径")
    return action


def resolve_product_actions(actions: list[dict[str, Any]], maximum: int = 2) -> list[dict[str, Any]]:
    """Apply same-term exclusion and keep at most two highest-priority actions."""
    actionable = [item for item in actions if item.get("action") != "观察"]
    negative_terms = {
        str(item.get("search_term") or "").strip().lower()
        for item in actionable
        if item.get("path") == "auto_negative"
    }
    actionable = [
        item for item in actionable
        if not (item.get("path") == "auto_to_exact" and str(item.get("search_term") or "").strip().lower() in negative_terms)
    ]
    priority = {
        "auto_negative": 0,
        "auto_bid": 1,
        "manual_keyword": 2,
        "auto_to_exact": 3,
    }
    return sorted(actionable, key=lambda item: priority.get(str(item.get("path")), 99))[:maximum]
