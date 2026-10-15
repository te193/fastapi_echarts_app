"""Read-only decision functions for the fixed 2026-09-13 problem-product cohort.

The mind map supplies preconditions, never its suggested bid percentages.
All numeric bids here are estimates for human review, not causal lift estimates.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from statistics import median
from typing import Any, Mapping


def d(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def cohort_group(metrics: Mapping[str, Any]) -> str | None:
    sales = d(metrics.get("daily_sales_30d"))
    if sales is None:
        return None
    if sales == 0:
        price, p15 = d(metrics.get("current_price")), d(metrics.get("p15_price"))
        return "无销量售价不高于P15" if price is not None and p15 is not None and price <= p15 else None
    margin = d(metrics.get("margin_rate_30d"))
    return "日销0至1毛利低于5%" if 0 < sales < 1 and margin is not None and margin < Decimal("0.05") else None


def classify_ad_state(ads: list[Mapping[str, Any]], *, ambiguous: bool = False) -> str:
    if ambiguous:
        return "待核对"
    if not ads:
        return "待开启广告"
    enabled = [a for a in ads if all(str(a.get(k) or "").lower() == "enabled" for k in ("ad_state", "group_state", "campaign_state"))]
    if not enabled:
        return "待开启广告"
    if any(str(a.get("serving_status") or "") == "AD_STATUS_LIVE" for a in enabled):
        return "可投放"
    return "待排查投放状态"


def bid_condition(row: Mapping[str, Any], euro_to_native: Decimal | None) -> tuple[str, str]:
    clicks, cost, sales = d(row.get("clicks")) or Decimal(0), d(row.get("cost")) or Decimal(0), d(row.get("sales")) or Decimal(0)
    impressions = d(row.get("impressions")) or Decimal(0)
    currency = str(row.get("currency") or "").upper()
    if currency == "EUR":
        euro_to_native = Decimal(1)
    if impressions == 0 and cost > 0:
        return "暂停_有花费无曝光", "导图暂停条件"
    if sales == 0 and clicks >= 50 and cost > 0 and euro_to_native is None:
        return "待核对汇率", "无法判断20欧元暂停门槛"
    if sales == 0 and clicks >= 50 and cost >= Decimal(20) * (euro_to_native or 1):
        return "暂停_高点击零销售", "点击≥50、零销售、花费≥20欧元"
    if cost == 0:
        return "维持_零花费", "导图维持条件"
    if sales == 0 and clicks < 10 and euro_to_native is None:
        return "待核对汇率", "无法判断5欧元维持门槛"
    if sales == 0 and clicks < 10 and cost < Decimal(5) * (euro_to_native or 1):
        return "维持_低样本", "导图维持条件"
    bid, max_bid = d(row.get("current_bid")), d(row.get("max_bid"))
    acos = cost / sales if sales > 0 else None
    if bid is not None and max_bid is not None and max_bid > 0 and bid > max_bid * Decimal("1.2") and (sales == 0 or acos is not None and acos > Decimal("0.2")):
        return "降价_超MaxBid", "导图超上限条件"
    if sales == 0:
        if clicks >= 40:
            return "降价_零销售点击40", "导图点击≥40"
        if clicks >= 25:
            return "降价_零销售点击25", "导图点击≥25"
        if clicks >= 15:
            return "降价_零销售点击15或花费15欧", "导图点击≥15"
        if euro_to_native is None:
            return "待核对汇率", "无法判断15欧元花费门槛"
        if cost >= Decimal(15) * euro_to_native:
            return "降价_零销售点击15或花费15欧", "导图花费≥15欧元"
    if acos is not None:
        for threshold, label in (("0.5", "50"), ("0.4", "40"), ("0.3", "30"), ("0.2", "20")):
            if acos > Decimal(threshold):
                return f"降价_ACOS{label}", f"导图ACOS>{label}%"
    if sales > 0 and acos is not None and acos <= Decimal("0.2"):
        cvr = (d(row.get("same_orders")) or Decimal(0)) / clicks if clicks > 0 else Decimal(0)
        group = str(row.get("match_group") or "other")
        tiers = {
            "exact_phrase": (("0.10", "0.18", 50), ("0.15", "0.15", 35), ("0.20", "0.12", 20), ("0.20", "0.12", 2)),
            "broad_close_complements": (("0.10", "0.18", 50), ("0.15", "0.15", 35), ("0.20", "0.12", 3)),
            "other": (("0.15", "0.15", 30), ("0.20", "0.12", 15)),
        }
        for i, (a, v, n) in enumerate(tiers.get(group, tiers["other"]), 1):
            if acos <= Decimal(a) and cvr >= Decimal(v) and clicks >= n:
                return f"提价_{group}_{i}", f"导图ACOS≤{a}、直接CVR≥{v}、点击≥{n}"
        return "维持_盈利但未达提价条件", "销售>0且ACOS≤20%"
    return "观察", "未命中导图操作条件"


def peer_reference(rows: list[Mapping[str, Any]], country: str, currency: str, match_group: str) -> dict[str, Any] | None:
    """Borrow only from converting objects in the same currency, widening by level."""
    for level, predicate in (
        ("同国家同币种同匹配类型", lambda r: r.get("country") == country and r.get("currency") == currency and r.get("match_group") == match_group),
        ("同币种同匹配类型", lambda r: r.get("currency") == currency and r.get("match_group") == match_group),
        ("同币种", lambda r: r.get("currency") == currency),
    ):
        samples = []
        for r in rows:
            if not predicate(r):
                continue
            clicks = (d(r.get("clicks")) or 0) + (d(r.get("previous_clicks")) or 0)
            orders = (d(r.get("orders")) or 0) + (d(r.get("previous_orders")) or 0)
            same = (d(r.get("same_orders")) or 0) + (d(r.get("previous_same_orders")) or 0)
            sales = (d(r.get("sales")) or 0) + (d(r.get("previous_sales")) or 0)
            if clicks >= 10 and orders > 0 and same > 0 and sales > 0:
                samples.append((sales / orders, same / clicks, clicks))
        if len(samples) >= 5:
            return {"level": level, "n": len(samples), "aov": median(x[0] for x in samples), "cvr": median(x[1] for x in samples), "prior_clicks": median(x[2] for x in samples)}
    return None


def propose_bid(row: Mapping[str, Any], peer: Mapping[str, Any] | None = None) -> dict[str, Any]:
    condition = str(row.get("condition") or "")
    bid = d(row.get("current_bid"))
    none = {"new_bid": None, "change_rate": None, "basis": "", "reason": ""}
    if not condition.startswith(("降价", "提价")):
        return {**none, "reason": "非调价条件"}
    if bid is None or bid <= 0:
        return {**none, "reason": "当前竞价缺失"}
    maximum = d(row.get("max_bid"))
    cost, sales = d(row.get("cost")) or Decimal(0), d(row.get("sales")) or Decimal(0)
    prev_cost, prev_sales = d(row.get("previous_cost")) or Decimal(0), d(row.get("previous_sales")) or Decimal(0)
    pooled_acos = d(row.get("pooled_acos"))
    if pooled_acos is None and sales + prev_sales > 0:
        pooled_acos = (cost + prev_cost) / (sales + prev_sales)
    if condition == "降价_超MaxBid":
        if maximum is None or maximum <= 0:
            return {**none, "reason": "MaxBid缺失"}
        rate = max(Decimal("-0.50"), maximum / bid - 1)
        basis = "当前竞价与MaxBid差距"
    elif condition.startswith("降价_ACOS"):
        if pooled_acos is None:
            return {**none, "reason": "两期销售额缺失"}
        if pooled_acos <= Decimal("0.20"):
            return {**none, "reason": "两期合并ACOS已≤20%，待复核"}
        rate = max(Decimal("-0.50"), Decimal("0.20") / pooled_acos - 1)
        basis = "两期合并ACOS与20%边界"
    elif condition.startswith("降价_零销售"):
        clicks = d(row.get("clicks")) or Decimal(0)
        if not peer or clicks <= 0 or cost <= 0:
            return {**none, "reason": "同币种转化借样不足或CPC缺失"}
        previous_clicks = d(row.get("previous_clicks")) or Decimal(0)
        previous_same = d(row.get("previous_same_orders")) or Decimal(0)
        aov = d(row.get("aov_60d")) or d(peer.get("aov"))
        if aov is None or aov <= 0:
            return {**none, "reason": "客单价缺失"}
        prior_clicks = d(peer["prior_clicks"]) or Decimal(0)
        estimated_cvr = (previous_same + d(peer["cvr"]) * prior_clicks) / (previous_clicks + clicks + prior_clicks)
        affordable_cpc = Decimal("0.20") * aov * estimated_cvr
        rate = max(Decimal("-0.50"), min(Decimal(0), affordable_cpc / (cost / clicks) - 1))
        basis = f"借样估计CPC；{peer['level']}，n={peer['n']}"
        if rate >= 0:
            return {**none, "basis": basis, "reason": "借样CPC不支持降价，待复核"}
    elif condition.startswith("提价"):
        if maximum is None or maximum <= 0 or pooled_acos is None:
            return {**none, "reason": "MaxBid或两期ACOS缺失"}
        if pooled_acos >= Decimal("0.20"):
            return {**none, "reason": "历史合并ACOS不支持提价"}
        rate = min(Decimal("0.20"), (Decimal("0.20") - pooled_acos) / Decimal("0.20"))
        basis = "两期合并ACOS盈利空间"
    else:
        return {**none, "reason": "未定义的调价条件"}
    if rate < 0:
        if bid <= Decimal("0.10"):
            return {**none, "basis": basis, "reason": "当前竞价≤0.10，禁止继续降价"}
        new = max(Decimal("0.10"), (bid * (1 + rate)).quantize(Decimal("0.01"), rounding=ROUND_CEILING))
    else:
        new = min(maximum.quantize(Decimal("0.01"), rounding=ROUND_FLOOR), (bid * (1 + rate)).quantize(Decimal("0.01"), rounding=ROUND_FLOOR))
    if new == bid or (rate > 0 and new < bid):
        return {**none, "basis": basis, "reason": "MaxBid或最小报价刻度阻止调整"}
    return {"new_bid": new, "change_rate": (new / bid - 1).quantize(Decimal("0.0001")), "basis": basis, "reason": "待审核试算"}


def budget_decision(row: Mapping[str, Any]) -> dict[str, Any]:
    """Excel campaign-budget rules, with evidence gates and native-currency budget."""
    current = d(row.get("current_daily_budget"))
    historical = d(row.get("historical_budget_7d"))
    none = {"status": "待复核", "new_budget": None, "change_rate": None, "reason": ""}
    if current is None or current <= 0:
        return {**none, "reason": "当前活动日预算缺失"}
    if row.get("shared_outside_cohort") is not False:
        return {**none, "reason": "活动包含范围外产品或归属未核清"}
    if historical is None or historical <= 0:
        return {**none, "reason": "成熟7天历史预算不足"}
    if row.get("enabled_last_10_days") is not True:
        return {**none, "reason": "连续启用10天未核实"}
    if row.get("changed_last_3_days") is not False:
        return {**none, "reason": "近3天改动未核清或存在改动"}
    clicks = d(row.get("clicks_7d")) or Decimal(0)
    if clicks < 10:
        return {"status": "维持", "new_budget": current, "change_rate": Decimal(0), "reason": "7天点击不足10"}
    days = int(row.get("enabled_days") or 0)
    if days <= 0:
        return {**none, "reason": "启用天数缺失"}
    stage, target = ("新品", Decimal("0.28")) if days <= 14 else (("成长期", Decimal("0.23")) if days <= 30 else ("成熟期", Decimal("0.20")))
    orders, cost, sales = d(row.get("orders_7d")), d(row.get("cost_7d")), d(row.get("sales_7d"))
    impressions = d(row.get("impressions_7d"))
    if any(v is None for v in (orders, cost, sales, impressions)):
        return {**none, "reason": "7天活动表现缺失"}
    if orders == 0:
        if days > 30:
            return {"status": "暂停活动", "new_budget": None, "change_rate": None, "reason": "成熟期零订单"}
        fx = d(row.get("currency_rate_cny"))
        if fx is None or fx <= 0:
            return {**none, "reason": "100元花费门槛缺汇率"}
        if days <= 30 and (days <= 20 or cost * fx <= 100 or clicks < 50):
            return {"status": "维持", "new_budget": current, "change_rate": Decimal(0), "reason": f"{stage}零订单保护"}
        return {"status": "暂停活动", "new_budget": None, "change_rate": None, "reason": f"{stage}零订单且超过保护门槛"}
    if sales <= 0:
        return {**none, "reason": "有订单但销售额为零"}
    acos = cost / sales
    cvr = orders / clicks
    ctr = clicks / impressions if impressions > 0 else None
    saturation = cost / historical
    deviation = acos - target
    rate = None
    reason = "未命中调整门槛"
    for bound, candidate in (("0.12", "-0.45"), ("0.10", "-0.35"), ("0.07", "-0.25"), ("0.05", "-0.15"), ("0.03", "-0.08")):
        if deviation > Decimal(bound):
            rate, reason = Decimal(candidate), f"ACOS高于{stage}目标超过{Decimal(bound)*100}个百分点"
            break
    if rate is None and cvr < Decimal("0.05"):
        rate, reason = Decimal("-0.12"), "CVR低于5%"
    if rate is None and ctr is not None and ctr < Decimal("0.002"):
        rate, reason = Decimal("-0.10"), "CTR低于0.2%"
    if rate is None:
        for bound, min_orders, min_saturation, candidate in (
            ("-0.08", 10, "0.95", "0.35"), ("-0.06", 10, "0.90", "0.28"),
            ("-0.04", 10, "0.85", "0.22"), ("-0.03", 1, "0.90", "0.18"),
            ("-0.02", 1, "0.85", "0.15"), ("-0.01", 1, "0.80", "0.12"),
        ):
            if deviation < Decimal(bound) and orders >= min_orders and saturation >= Decimal(min_saturation):
                rate, reason = Decimal(candidate), "ACOS低于目标且预算饱和"
                break
        if rate is None and abs(deviation) <= Decimal("0.01") and saturation >= Decimal("0.75"):
            rate, reason = Decimal("0.10"), "ACOS稳定且预算饱和"
        if rate is None and abs(deviation) <= Decimal("0.02") and saturation >= Decimal("0.70") and row.get("acos_improving") is True:
            rate, reason = Decimal("0.08"), "ACOS改善且预算饱和"
        if rate is None and abs(deviation) <= Decimal("0.03") and saturation >= Decimal("0.65"):
            rate, reason = Decimal("0.05"), "接近目标且预算饱和"
    if rate is None:
        return {"status": "维持", "new_budget": current, "change_rate": Decimal(0), "reason": reason}
    if cvr >= Decimal("0.11"):
        rate += Decimal("0.05") if rate > 0 else Decimal("-0.05")
    elif cvr >= Decimal("0.08"):
        rate += Decimal("0.03") if rate > 0 else Decimal("-0.03")
    elif cvr < Decimal("0.05"):
        rate -= Decimal("0.03")
    new = max(Decimal(1), current * (1 + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"status": "加预算" if rate > 0 else "降预算", "new_budget": new, "change_rate": new / current - 1, "reason": reason}
