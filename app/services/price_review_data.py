from __future__ import annotations

import hashlib
import math
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pymysql


# ---------------------------------------------------------------------------
# Deterministic seeded random so the same inputs always give the same data
# ---------------------------------------------------------------------------
def _seeded_random(seed_str: str) -> random.Random:
    h = hashlib.md5(seed_str.encode("utf-8")).hexdigest()
    return random.Random(int(h, 16))


def safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, float) and math.isnan(value):
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def safe_int(value: Any) -> int:
    return int(round(safe_float(value)))


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class PriceReviewData:
    overall: list[dict[str, Any]] = field(default_factory=list)
    sku_list: list[dict[str, Any]] = field(default_factory=list)
    sales_band_matrix: dict[str, Any] = field(default_factory=dict)
    daily_sales_band_matrix: dict[str, Any] = field(default_factory=dict)
    margin_band_matrix: dict[str, Any] = field(default_factory=dict)
    rank_band_matrix: dict[str, Any] = field(default_factory=dict)
    drop_range_analysis: list[dict[str, Any]] = field(default_factory=list)
    country_stats: list[dict[str, Any]] = field(default_factory=list)
    top_sales_up: list[dict[str, Any]] = field(default_factory=list)
    top_sales_down: list[dict[str, Any]] = field(default_factory=list)
    top_rank_improve: list[dict[str, Any]] = field(default_factory=list)
    top_rank_worsen: list[dict[str, Any]] = field(default_factory=list)
    sessions_band_matrix: dict[str, Any] = field(default_factory=dict)
    risk_levels: list[dict[str, Any]] = field(default_factory=list)
    issue_tags: list[dict[str, Any]] = field(default_factory=list)
    # Extra filter options derived from data
    filter_options: dict[str, list[str]] = field(default_factory=dict)
    period_incomplete: bool = False
    latest_data_date: date | None = None


# ---------------------------------------------------------------------------
# Mock data generator
# ---------------------------------------------------------------------------

_COUNTRIES = ["美国", "加拿大", "英国", "德国", "法国", "西班牙", "意大利", "荷兰", "比利时", "瑞典", "波兰", "爱尔兰"]
_STORE_PREFIXES = ["StoreA", "StoreB", "StoreC", "StoreD", "StoreE"]
_PRODUCT_WORDS = [
    "Wireless", "Bluetooth", "Smart", "Pro", "Ultra", "Mini", "Max",
    "Premium", "Essential", "Travel", "Home", "Office", "Gaming",
    "Fitness", "Kids", "Outdoor", "Kitchen", "Bedroom", "Studio",
]
_PRODUCT_TYPES = [
    "Earbuds", "Speaker", "Charger", "Cable", "Case", "Stand",
    "Hub", "Adapter", "Battery", "Light", "Mat", "Holder",
    "Mount", "Pad", "Kit", "Set", "Bag", "Cover",
]

_DROP_RANGES = [
    "涨价>30%", "涨价20-30%", "涨价15-20%", "涨价10-15%", "涨价5-10%", "涨价0-5%",
    "持平",
    "降价0-5%", "降价5-10%", "降价10-15%", "降价15-20%", "降价20-30%", "降价>30%",
]
# Excel real band definitions
_SALES_BANDS = ["0个", "1-2个", "3-5个", "6-10个", "11-20个", ">20个"]
_DAILY_SALES_BANDS = ["日销 0", "日销 <1", "日销 1-5", "日销 >5"]
_MARGIN_BANDS = ["无销售", "毛利率 <0%", "毛利率 0-10%", "毛利率 10-15%", "毛利率 15-25%", "毛利率 25-35%", "毛利率 >35%"]
_RANK_BANDS = ["无排名", "1-50", "51-100", "101-200", "201-500", ">500"]
_RISK_LEVELS = ["高", "中", "低", "观察"]
_ISSUE_TAGS_POOL = ["销量下滑", "利润下降", "排名恶化", "ACOS升高", "转化率下降", "库存不足", "广告花费高", "退货率高"]


def _fmt_price(v: float) -> float:
    return round(v, 2)


def _band_for_sales(v: float) -> str:
    if v == 0:
        return _SALES_BANDS[0]
    if v <= 2:
        return _SALES_BANDS[1]
    if v <= 5:
        return _SALES_BANDS[2]
    if v <= 10:
        return _SALES_BANDS[3]
    if v <= 20:
        return _SALES_BANDS[4]
    return _SALES_BANDS[5]


def _band_for_daily_sales(v: float) -> str:
    if v == 0:
        return _DAILY_SALES_BANDS[0]
    if v < 1:
        return _DAILY_SALES_BANDS[1]
    if v <= 5:
        return _DAILY_SALES_BANDS[2]
    return _DAILY_SALES_BANDS[3]


def _band_for_margin(sales: int, margin: float) -> str:
    if sales == 0:
        return _MARGIN_BANDS[0]
    if margin < 0:
        return _MARGIN_BANDS[1]
    if margin < 0.10:
        return _MARGIN_BANDS[2]
    if margin < 0.15:
        return _MARGIN_BANDS[3]
    if margin < 0.25:
        return _MARGIN_BANDS[4]
    if margin < 0.35:
        return _MARGIN_BANDS[5]
    return _MARGIN_BANDS[6]


def _band_for_rank(v: int) -> str:
    if v <= 0:
        return _RANK_BANDS[0]
    if v <= 50:
        return _RANK_BANDS[1]
    if v <= 100:
        return _RANK_BANDS[2]
    if v <= 200:
        return _RANK_BANDS[3]
    if v <= 500:
        return _RANK_BANDS[4]
    return _RANK_BANDS[5]


def _drop_range_for(ratio: float) -> str:
    if ratio < 0:
        abs_ratio = abs(ratio)
        if abs_ratio <= 0.05:
            return "涨价0-5%"
        if abs_ratio <= 0.10:
            return "涨价5-10%"
        if abs_ratio <= 0.15:
            return "涨价10-15%"
        if abs_ratio <= 0.20:
            return "涨价15-20%"
        if abs_ratio <= 0.30:
            return "涨价20-30%"
        return "涨价>30%"
    if ratio == 0:
        return "持平"
    if ratio <= 0.05:
        return "降价0-5%"
    if ratio <= 0.10:
        return "降价5-10%"
    if ratio <= 0.15:
        return "降价10-15%"
    if ratio <= 0.20:
        return "降价15-20%"
    if ratio <= 0.30:
        return "降价20-30%"
    return "降价>30%"


def _generate_skus(rng: random.Random, adjust_date: date, compare_days: int) -> list[dict[str, Any]]:
    sku_count = 821
    skus: list[dict[str, Any]] = []

    for i in range(sku_count):
        country = rng.choice(_COUNTRIES)
        store = rng.choice(_STORE_PREFIXES) + f"-{country}"
        msku = f"MSKU{rng.randint(10000, 99999)}"
        msku_adj = f"{msku}-ADJ"
        product_name = f"{rng.choice(_PRODUCT_WORDS)} {rng.choice(_PRODUCT_TYPES)} {rng.randint(1, 99)}"

        # Price before: 5 ~ 120 USD
        price_before = round(rng.uniform(5.0, 120.0), 2)
        # Drop ratio: most are 5-25%
        drop_ratio = rng.gauss(0.15, 0.08)
        drop_ratio = max(0.01, min(0.45, drop_ratio))
        price_after = _fmt_price(price_before * (1 - drop_ratio))
        drop_ratio = round((price_before - price_after) / price_before, 4)

        # Sales before: mostly 0-200 with a few outliers
        sales_before = max(0, int(rng.gauss(40, 50)))
        # After price drop, sales usually go up a bit (elasticity)
        elasticity = rng.gauss(1.25, 0.35)  # mean 25% lift
        sales_after = max(0, int(sales_before * elasticity))
        sales_change = sales_after - sales_before
        sales_change_rate = round(sales_change / sales_before, 4) if sales_before > 0 else 0.0

        ds_before = round(sales_before / compare_days, 2)
        ds_after = round(sales_after / compare_days, 2)
        ds_change = round(ds_after - ds_before, 2)

        revenue_before = round(price_before * sales_before, 2)
        revenue_after = round(price_after * sales_after, 2)
        revenue_change = round(revenue_after - revenue_before, 2)

        # Margin before: -5% ~ 50%，使用截断正态分布增加出现负值的概率
        margin_before = round(rng.gauss(0.22, 0.12), 4)
        # 约 8% 的概率出现负毛利
        if rng.random() < 0.08:
            margin_before = -1 * round(rng.uniform(0.001, 0.05), 4)
        else:
            margin_before = max(0.0, min(0.50, margin_before))
        # After price drop, margin compresses a bit
        margin_compression = rng.uniform(0.005, 0.03)
        margin_after = round(margin_before - margin_compression, 4)
        margin_change = round(margin_after - margin_before, 4)

        profit_before = round(revenue_before * margin_before, 2)
        profit_after = round(revenue_after * margin_after, 2)
        profit_change = round(profit_after - profit_before, 2)

        # Sessions
        sessions_before = max(0, int(sales_before * rng.gauss(15, 5)))
        sessions_after = max(0, int(sales_after * rng.gauss(15, 5)))
        sessions_change = sessions_after - sessions_before
        sessions_change_rate = round(sessions_change / sessions_before, 4) if sessions_before > 0 else 0.0

        # Conversion (CVR = 订单量 / sessions)
        conversion_before = round(sales_before / sessions_before, 4) if sessions_before > 0 else 0.0
        conversion_after = round(sales_after / sessions_after, 4) if sessions_after > 0 else 0.0
        conversion_change = round(conversion_after - conversion_before, 4)

        # Clicks and Impressions (for CTR)
        clicks_before = max(0, int(sessions_before * rng.gauss(0.85, 0.10)))
        clicks_after = max(0, int(sessions_after * rng.gauss(0.85, 0.10)))
        impressions_before = max(0, int(clicks_before * rng.gauss(5, 1.5)))
        impressions_after = max(0, int(clicks_after * rng.gauss(5, 1.5)))
        # CTR = clicks / impressions
        ctr_before = round(clicks_before / impressions_before, 4) if impressions_before > 0 else 0.0
        ctr_after = round(clicks_after / impressions_after, 4) if impressions_after > 0 else 0.0
        ctr_change = round(ctr_after - ctr_before, 4)

        # Ad spend
        ad_spend_before = round(revenue_before * rng.gauss(0.12, 0.04), 2)
        ad_spend_after = round(revenue_after * rng.gauss(0.12, 0.04), 2)
        ad_spend_change = round(ad_spend_after - ad_spend_before, 2)

        # Ad revenue (typically 40-70% of total revenue is from ads)
        ad_revenue_before = round(revenue_before * rng.uniform(0.40, 0.70), 2)
        ad_revenue_after = round(revenue_after * rng.uniform(0.40, 0.70), 2)

        # ACOS = ad spend / ad revenue
        acos_before = round(ad_spend_before / ad_revenue_before, 4) if ad_revenue_before > 0 else 0.0
        acos_after = round(ad_spend_after / ad_revenue_after, 4) if ad_revenue_after > 0 else 0.0
        acos_change = round(acos_after - acos_before, 4)

        # TACOS = ad spend / total revenue
        tacos_before = round(ad_spend_before / revenue_before, 4) if revenue_before > 0 else 0.0
        tacos_after = round(ad_spend_after / revenue_after, 4) if revenue_after > 0 else 0.0
        tacos_change = round(tacos_after - tacos_before, 4)

        # CPC
        cpc_before = round(ad_spend_before / max(1, sessions_before), 2)
        cpc_after = round(ad_spend_after / max(1, sessions_after), 2)
        cpc_change = round(cpc_after - cpc_before, 2)

        # Rank: use abs-normal so most fall in 1k~50k range, avoid mass=1
        rank_before = int(abs(rng.gauss(22000, 16000))) + 1
        rank_after = max(1, int(rank_before * rng.gauss(0.90, 0.18)))
        rank_change = rank_after - rank_before

        drop_range = _drop_range_for(drop_ratio)
        price_band = f"${int(price_before // 20) * 20}-{(int(price_before // 20) + 1) * 20}"

        # Risk level
        risk_level = rng.choice(_RISK_LEVELS)
        # Issue tags
        tag_count = rng.randint(0, 3)
        issue_tags = ", ".join(rng.sample(_ISSUE_TAGS_POOL, min(tag_count, len(_ISSUE_TAGS_POOL))))

        # Suggested action
        actions = ["观察", "优化广告", "补货", "降价", "提价", "加大促销", "清仓"]
        suggested_action = rng.choice(actions)

        sku = {
            "country": country,
            "store": store,
            "msku_adj": msku_adj,
            "msku": msku,
            "product_name": product_name,
            "price_before": price_before,
            "price_after": price_after,
            "drop_ratio": drop_ratio,
            "drop_range": drop_range,
            "price_band": price_band,
            "sales_before": sales_before,
            "sales_after": sales_after,
            "sales_change": sales_change,
            "sales_change_rate": sales_change_rate,
            "daily_sales_before": ds_before,
            "daily_sales_after": ds_after,
            "daily_sales_change": ds_change,
            "revenue_before": revenue_before,
            "revenue_after": revenue_after,
            "revenue_change": revenue_change,
            "profit_before": profit_before,
            "profit_after": profit_after,
            "profit_change": profit_change,
            "margin_before": margin_before,
            "margin_after": margin_after,
            "margin_change": margin_change,
            "sessions_before": sessions_before,
            "sessions_after": sessions_after,
            "sessions_change": sessions_change,
            "sessions_change_rate": sessions_change_rate,
            "conversion_before": conversion_before,
            "conversion_after": conversion_after,
            "conversion_change": conversion_change,
            "ctr_before": ctr_before,
            "ctr_after": ctr_after,
            "ctr_change": ctr_change,
            "ad_spend_before": ad_spend_before,
            "ad_spend_after": ad_spend_after,
            "ad_spend_change": ad_spend_change,
            "ad_revenue_before": ad_revenue_before,
            "ad_revenue_after": ad_revenue_after,
            "acos_before": acos_before,
            "acos_after": acos_after,
            "acos_change": acos_change,
            "tacos_before": tacos_before,
            "tacos_after": tacos_after,
            "tacos_change": tacos_change,
            "cpc_before": cpc_before,
            "cpc_after": cpc_after,
            "cpc_change": cpc_change,
            "rank_before": rank_before,
            "rank_after": rank_after,
            "rank_change": rank_change,
            "sales_band_before": _band_for_sales(sales_before),
            "sales_band_after": _band_for_sales(sales_after),
            "daily_sales_band_before": _band_for_daily_sales(ds_before),
            "daily_sales_band_after": _band_for_daily_sales(ds_after),
            "margin_band_before": _band_for_margin(sales_before, margin_before),
            "margin_band_after": _band_for_margin(sales_after, margin_after),
            "rank_band_before": _band_for_rank(rank_before),
            "rank_band_after": _band_for_rank(rank_after),
            "risk_level": risk_level,
            # 暂时移除 issue_tags 和 suggested_action（数据不完整）
            # "issue_tags": issue_tags,
            # "suggested_action": suggested_action,
        }
        skus.append(sku)

    return skus


def _build_matrix(rows: list[dict[str, Any]], band_key_before: str, band_key_after: str, value_key_before: str, value_key_after: str, matrix_type: str) -> dict[str, Any]:
    band_counts: dict[str, dict[str, Any]] = {}
    for sku in rows:
        band = sku[band_key_before]
        if band not in band_counts:
            band_counts[band] = {
                "sku_before": 0, "sku_after": 0,
                "value_before_sum": 0.0, "value_after_sum": 0.0,
                "value_before_cnt": 0, "value_after_cnt": 0,
            }
        band_counts[band]["sku_before"] += 1
        band_counts[band]["value_before_sum"] += sku[value_key_before]
        band_counts[band]["value_before_cnt"] += 1

        band_a = sku[band_key_after]
        if band_a not in band_counts:
            band_counts[band_a] = {
                "sku_before": 0, "sku_after": 0,
                "value_before_sum": 0.0, "value_after_sum": 0.0,
                "value_before_cnt": 0, "value_after_cnt": 0,
            }
        band_counts[band_a]["sku_after"] += 1
        band_counts[band_a]["value_after_sum"] += sku[value_key_after]
        band_counts[band_a]["value_after_cnt"] += 1

    total_before = len(rows)
    total_after = len(rows)

    # Select band order based on matrix type
    band_order_map: dict[str, list[str]] = {
        "sales": _SALES_BANDS,
        "daily_sales": _DAILY_SALES_BANDS,
        "margin": _MARGIN_BANDS,
        "rank": _RANK_BANDS,
        "sessions": _SALES_BANDS,
    }
    ordered_bands = band_order_map.get(matrix_type, [])
    # 确保所有 ordered_bands 中的分层都显示（包括数据为 0 的）
    all_bands: list[str] = list(ordered_bands)

    use_avg = matrix_type == "rank"

    result_rows: list[dict[str, Any]] = []
    for band in all_bands:
        counts = band_counts.get(band, {"sku_before": 0, "sku_after": 0, "value_before_sum": 0.0, "value_after_sum": 0.0, "value_before_cnt": 0, "value_after_cnt": 0})
        if use_avg:
            vb = round(counts["value_before_sum"] / counts["value_before_cnt"], 2) if counts["value_before_cnt"] else 0.0
            va = round(counts["value_after_sum"] / counts["value_after_cnt"], 2) if counts["value_after_cnt"] else 0.0
        else:
            vb = round(counts["value_before_sum"], 2)
            va = round(counts["value_after_sum"], 2)
        result_rows.append({
            "band": band,
            "sku_before": counts["sku_before"],
            "sku_before_ratio": round(counts["sku_before"] / total_before, 4) if total_before else 0.0,
            "sku_after": counts["sku_after"],
            "sku_after_ratio": round(counts["sku_after"] / total_after, 4) if total_after else 0.0,
            "sku_change": counts["sku_after"] - counts["sku_before"],
            "value_before": vb,
            "value_after": va,
        })

    return {
        "type": matrix_type,
        "bands": all_bands,
        "rows": result_rows,
    }


def _build_country_stats(skus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from collections import defaultdict
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "sku_count": 0, "sales_change": 0, "revenue_change": 0.0,
        "profit_change": 0.0, "margin_before_sum": 0.0, "margin_after_sum": 0.0, "high_risk_count": 0,
        "rank_worsen_count": 0, "rank_improve_count": 0,
        "out_of_stock_count": 0, "profit_down_count": 0,
    })

    for sku in skus:
        c = sku["country"]
        s = stats[c]
        s["sku_count"] += 1
        s["sales_change"] += sku["sales_change"]
        s["revenue_change"] += sku["revenue_change"]
        s["profit_change"] += sku["profit_change"]
        s["margin_before_sum"] += sku["margin_before"]
        s["margin_after_sum"] += sku["margin_after"]
        if sku["risk_level"] == "高":
            s["high_risk_count"] += 1
        if sku["rank_change"] > 0:
            s["rank_worsen_count"] += 1
        if sku["rank_change"] < 0:
            s["rank_improve_count"] += 1
        if sku["sales_after"] == 0 and sku["sales_before"] > 0:
            s["out_of_stock_count"] += 1
        if sku["profit_change"] < 0:
            s["profit_down_count"] += 1

    result = []
    for c in sorted(stats.keys()):
        s = stats[c]
        result.append({
            "country": c,
            "sku_count": s["sku_count"],
            "sales_change": s["sales_change"],
            "revenue_change": round(s["revenue_change"], 2),
            "profit_change": round(s["profit_change"], 2),
            "margin_before": round(s["margin_before_sum"] / s["sku_count"], 4) if s["sku_count"] else 0.0,
            "margin_after": round(s["margin_after_sum"] / s["sku_count"], 4) if s["sku_count"] else 0.0,
            "high_risk_count": s["high_risk_count"],
            "high_risk_ratio": round(s["high_risk_count"] / s["sku_count"], 4) if s["sku_count"] else 0.0,
            "rank_worsen_count": s["rank_worsen_count"],
            "rank_worsen_ratio": round(s["rank_worsen_count"] / s["sku_count"], 4) if s["sku_count"] else 0.0,
            "rank_improve_count": s["rank_improve_count"],
            "rank_improve_ratio": round(s["rank_improve_count"] / s["sku_count"], 4) if s["sku_count"] else 0.0,
            "out_of_stock_count": s["out_of_stock_count"],
            "profit_down_count": s["profit_down_count"],
        })
    return result


def _build_drop_range_analysis(skus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from collections import defaultdict
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "sku_count": 0, "sales_before": 0, "sales_after": 0,
        "sales_change": 0, "profit_change": 0.0, "margin_after_sum": 0.0,
    })

    for sku in skus:
        dr = sku["drop_range"]
        s = stats[dr]
        s["sku_count"] += 1
        s["sales_before"] += sku["sales_before"]
        s["sales_after"] += sku["sales_after"]
        s["sales_change"] += sku["sales_change"]
        s["profit_change"] += sku["profit_change"]
        s["margin_after_sum"] += sku["margin_after"]

    # Order known ranges first, then keep any unexpected DB labels visible.
    result = []
    ordered_ranges = list(_DROP_RANGES) + sorted(dr for dr in stats.keys() if dr not in _DROP_RANGES)
    for dr in ordered_ranges:
        if dr not in stats:
            continue
        s = stats[dr]
        result.append({
            "label": dr,
            "sku_count": s["sku_count"],
            "sales_before": s["sales_before"],
            "sales_after": s["sales_after"],
            "sales_change": s["sales_change"],
            "sales_change_rate": round(s["sales_change"] / s["sales_before"], 4) if s["sales_before"] else 0.0,
            "profit_change": round(s["profit_change"], 2),
            "margin_after": round(s["margin_after_sum"] / s["sku_count"], 4) if s["sku_count"] else 0.0,
        })
    return result


def _build_second_adjustment_timing(skus: list[dict[str, Any]]) -> dict[str, Any]:
    from collections import defaultdict

    by_date: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "previous_adjust_date": "",
        "sku_count": 0,
        "gap_days_sum": 0,
        "stores": set(),
        "countries": set(),
    })
    gap_buckets = {
        "1天": 0,
        "2-3天": 0,
        "4-7天": 0,
        "8-14天": 0,
        "15天以上": 0,
    }
    second_rows = [
        s for s in skus
        if s.get("is_second_adjustment") and s.get("previous_adjust_date")
    ]

    for sku in second_rows:
        previous_date = str(sku.get("previous_adjust_date") or "")
        current_date = sku.get("adjust_date")
        gap_days = 0
        try:
            current = date.fromisoformat(str(current_date))
            previous = date.fromisoformat(previous_date)
            gap_days = max((current - previous).days, 0)
        except (TypeError, ValueError):
            gap_days = 0

        row = by_date[previous_date]
        row["previous_adjust_date"] = previous_date
        row["sku_count"] += 1
        row["gap_days_sum"] += gap_days
        if sku.get("store"):
            row["stores"].add(sku["store"])
        if sku.get("country"):
            row["countries"].add(sku["country"])

        if gap_days <= 1:
            gap_buckets["1天"] += 1
        elif gap_days <= 3:
            gap_buckets["2-3天"] += 1
        elif gap_days <= 7:
            gap_buckets["4-7天"] += 1
        elif gap_days <= 14:
            gap_buckets["8-14天"] += 1
        else:
            gap_buckets["15天以上"] += 1

    items = []
    for previous_date in sorted(by_date.keys(), reverse=True):
        row = by_date[previous_date]
        sku_count = row["sku_count"]
        items.append({
            "previous_adjust_date": previous_date,
            "sku_count": sku_count,
            "avg_gap_days": round(row["gap_days_sum"] / sku_count, 1) if sku_count else 0,
            "store_count": len(row["stores"]),
            "country_count": len(row["countries"]),
        })

    total_gap_days = sum(item["avg_gap_days"] * item["sku_count"] for item in items)
    total = len(second_rows)
    return {
        "total": total,
        "date_count": len(items),
        "avg_gap_days": round(total_gap_days / total, 1) if total else 0,
        "items": items,
        "gap_buckets": [{"label": label, "sku_count": count} for label, count in gap_buckets.items()],
    }


def _build_overall(skus: list[dict[str, Any]], compare_days: int) -> list[dict[str, Any]]:
    def _sum(key: str) -> float:
        return sum(s[key] for s in skus)

    def _avg(key: str) -> float:
        values = [s[key] for s in skus if s.get(key)]
        return round(sum(values) / len(values), 4) if values else 0.0

    total_before = _sum("sales_before")
    total_after = _sum("sales_after")
    daily_before = round(total_before / compare_days, 2)
    daily_after = round(total_after / compare_days, 2)
    revenue_before = _sum("revenue_before")
    revenue_after = _sum("revenue_after")
    ad_spend_before = _sum("ad_spend_before")
    ad_spend_after = _sum("ad_spend_after")
    ad_revenue_before = _sum("ad_revenue_before")
    ad_revenue_after = _sum("ad_revenue_after")
    ctr_before = _avg("ctr_before")
    ctr_after = _avg("ctr_after")

    margin_before = round(_sum("profit_before") / revenue_before, 4) if revenue_before else 0.0
    margin_after = round(_sum("profit_after") / revenue_after, 4) if revenue_after else 0.0
    # ACOS = ad spend / ad revenue
    acos_before = round(ad_spend_before / ad_revenue_before, 4) if ad_revenue_before else 0.0
    acos_after = round(ad_spend_after / ad_revenue_after, 4) if ad_revenue_after else 0.0
    # TACOS = ad spend / total revenue
    tacos_before = round(ad_spend_before / revenue_before, 4) if revenue_before else 0.0
    tacos_after = round(ad_spend_after / revenue_after, 4) if revenue_after else 0.0
    # Sessions total
    sessions_before = _sum("sessions_before")
    sessions_after = _sum("sessions_after")
    # CVR = orders / sessions
    cvr_before = round(total_before / sessions_before, 4) if sessions_before else 0.0
    cvr_after = round(total_after / sessions_after, 4) if sessions_after else 0.0

    metrics = [
        ("销量（个）", "sales", total_before, total_after, "number"),
        ("日销（个/天）", "daily_sales", daily_before, daily_after, "number"),
        ("销售额", "revenue", revenue_before, revenue_after, "currency"),
        ("订单毛利率", "margin", margin_before, margin_after, "percent"),
        ("sessions", "sessions", sessions_before, sessions_after, "number"),
        ("CVR（转化率）", "conversion", cvr_before, cvr_after, "percent"),
        ("CTR（点击率）", "ctr", ctr_before, ctr_after, "percent"),
        ("ACOS", "acos", acos_before, acos_after, "percent"),
        ("TACOS", "tacos", tacos_before, tacos_after, "percent"),
        ("广告花费", "ad_spend", ad_spend_before, ad_spend_after, "currency"),
    ]

    result = []
    for metric_name, key, before, after, typ in metrics:
        change = round(after - before, 4)
        change_rate = round(change / before, 4) if before else 0.0
        if key in ("margin", "conversion", "acos"):
            change = round(change, 4)
        # Simple interpretation
        if abs(change_rate) < 0.01:
            interpretation = "基本持平"
        elif change > 0:
            interpretation = "有所上升" if key not in ("returns", "ad_spend", "acos") else "需关注"
        else:
            interpretation = "有所下降" if key not in ("returns", "ad_spend", "acos") else "有所优化"

        result.append({
            "metric": metric_name,
            "before": before,
            "after": after,
            "change": change,
            "change_rate": change_rate,
            "interpretation": interpretation,
        })
    return result


def _build_top_lists(skus: list[dict[str, Any]], limit: int = 20) -> dict[str, list[dict[str, Any]]]:
    def _to_item(sku: dict[str, Any]) -> dict[str, Any]:
        return {
            "country": sku["country"],
            "store": sku["store"],
            "msku": sku["msku"],
            "product_name": sku["product_name"],
            "sales_before": sku["sales_before"],
            "sales_after": sku["sales_after"],
            "sales_change": sku["sales_change"],
            "daily_sales_before": sku["daily_sales_before"],
            "daily_sales_after": sku["daily_sales_after"],
            "daily_sales_change": sku["daily_sales_change"],
            "profit_change": sku["profit_change"],
            "margin_before": sku["margin_before"],
            "margin_after": sku["margin_after"],
            "rank_change": sku["rank_change"],
            "rank_after": sku["rank_after"],
            "risk_level": sku["risk_level"],
        }

    sales_up = sorted([s for s in skus if s["sales_change"] > 0], key=lambda x: x["sales_change"], reverse=True)[:limit]
    sales_down = sorted([s for s in skus if s["sales_change"] < 0], key=lambda x: x["sales_change"])[:limit]
    rank_improve = sorted([s for s in skus if s["rank_change"] < 0], key=lambda x: x["rank_change"])[:limit]
    rank_worsen = sorted([s for s in skus if s["rank_change"] > 0], key=lambda x: x["rank_change"], reverse=True)[:limit]

    return {
        "sales_up": [_to_item(s) for s in sales_up],
        "sales_down": [_to_item(s) for s in sales_down],
        "rank_improve": [_to_item(s) for s in rank_improve],
        "rank_worsen": [_to_item(s) for s in rank_worsen],
    }


def _build_risk_levels(skus: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from collections import Counter
    risk_counter = Counter(s["risk_level"] for s in skus if s["risk_level"])
    total = len(skus)
    risk_levels = [
        {"name": name, "count": count, "ratio": round(count / total, 4)}
        for name, count in risk_counter.most_common()
    ]

    tag_counter: Counter = Counter()
    for s in skus:
        tags = s.get("issue_tags", "")
        if tags:
            for tag in tags.split(", "):
                tag = tag.strip()
                if tag:
                    tag_counter[tag] += 1
    issue_tags = [
        {"name": name, "count": count, "ratio": round(count / total, 4)}
        for name, count in tag_counter.most_common()
    ]
    return risk_levels, issue_tags


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class PriceReviewService:
    def __init__(self):
        self._cache: dict[str, PriceReviewData] = {}

    def connect(self):
        return pymysql.connect(
            host=os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", "127.0.0.1")),
            port=int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", "3306"))),
            user=os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", "")),
            password=os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
            database=os.getenv("DASHBOARD_DB_NAME", os.getenv("MYSQL_DATABASE", "etl_datasync_test")),
            charset=os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )

    def load(self, adjust_date: date | None = None, compare_days: int = 14) -> PriceReviewData:
        adjust_date = adjust_date or self._latest_available_adjust_date(compare_days) or date.today()
        skus = self._load_skus_from_db(adjust_date, compare_days)
        overall = _build_overall(skus, compare_days)
        country_stats = _build_country_stats(skus)
        drop_range_analysis = _build_drop_range_analysis(skus)
        top_lists = _build_top_lists(skus)
        risk_levels, issue_tags = _build_risk_levels(skus)

        sales_band_matrix = _build_matrix(skus, "sales_band_before", "sales_band_after", "sales_before", "sales_after", "sales")
        daily_sales_band_matrix = _build_matrix(skus, "daily_sales_band_before", "daily_sales_band_after", "daily_sales_before", "daily_sales_after", "daily_sales")
        margin_band_matrix = _build_matrix(skus, "margin_band_before", "margin_band_after", "revenue_before", "revenue_after", "margin")
        rank_band_matrix = _build_matrix(skus, "rank_band_before", "rank_band_after", "rank_before", "rank_after", "rank")
        sessions_band_matrix = _build_matrix(skus, "sales_band_before", "sales_band_after", "sessions_before", "sessions_after", "sessions")

        countries = sorted({s["country"] for s in skus if s["country"]})
        drop_ranges = sorted({s["drop_range"] for s in skus if s["drop_range"]}, key=lambda x: _DROP_RANGES.index(x) if x in _DROP_RANGES else 99)
        risk_levels_opt = sorted({s["risk_level"] for s in skus if s["risk_level"]})
        stores = sorted({s["store"] for s in skus if s["store"]})
        price_bands = sorted({s["price_band"] for s in skus if s["price_band"]})

        data = PriceReviewData(
            overall=overall,
            sku_list=skus,
            sales_band_matrix=sales_band_matrix,
            daily_sales_band_matrix=daily_sales_band_matrix,
            margin_band_matrix=margin_band_matrix,
            rank_band_matrix=rank_band_matrix,
            drop_range_analysis=drop_range_analysis,
            country_stats=country_stats,
            top_sales_up=top_lists["sales_up"],
            top_sales_down=top_lists["sales_down"],
            top_rank_improve=top_lists["rank_improve"],
            top_rank_worsen=top_lists["rank_worsen"],
            sessions_band_matrix=sessions_band_matrix,
            risk_levels=risk_levels,
            issue_tags=issue_tags,
            filter_options={
                "countries": countries,
                "drop_ranges": drop_ranges,
                "risk_levels": risk_levels_opt,
                "stores": stores,
                "price_bands": price_bands,
                "adjustment_types": ["首次调价", "二次调价"],
            },
            period_incomplete=self._period_incomplete(adjust_date, compare_days, bool(skus)),
            latest_data_date=self._latest_product_data_date(),
        )
        return data

    def _load_skus_from_db(self, adjust_date: date, compare_days: int) -> list[dict[str, Any]]:
        latest = self._latest_product_data_date()
        if latest and latest < adjust_date + timedelta(days=compare_days):
            return []
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        select *
                        from price_review_sku_tracking
                        where adjust_date = %(adjust_date)s
                          and period_days = %(period_days)s
                        order by sales_change desc, revenue_change desc, msku
                        """,
                        {"adjust_date": adjust_date, "period_days": compare_days},
                    )
                    return [self._row_to_sku(row) for row in cursor.fetchall()]
        except pymysql.MySQLError:
            return []

    def _row_to_sku(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "country": safe_str(row.get("country")),
            "adjust_date": row.get("adjust_date").isoformat() if row.get("adjust_date") else "",
            "store": safe_str(row.get("store")),
            "msku_adj": safe_str(row.get("msku")),
            "msku": safe_str(row.get("msku")),
            "product_name": safe_str(row.get("product_name")),
            "price_before": round(safe_float(row.get("price_before")), 2),
            "price_after": round(safe_float(row.get("price_after")), 2),
            "drop_ratio": round(safe_float(row.get("drop_ratio")), 4),
            "is_second_adjustment": safe_int(row.get("is_second_adjustment")) == 1,
            "adjustment_type": "二次调价" if safe_int(row.get("is_second_adjustment")) == 1 else "首次调价",
            "previous_adjust_date": row.get("previous_adjust_date").isoformat() if row.get("previous_adjust_date") else "",
            "drop_range": safe_str(row.get("drop_range")),
            "price_band": safe_str(row.get("price_band")),
            "sales_before": safe_int(row.get("sales_before")),
            "sales_after": safe_int(row.get("sales_after")),
            "sales_change": safe_int(row.get("sales_change")),
            "sales_change_rate": round(safe_float(row.get("sales_change_rate")), 4),
            "daily_sales_before": round(safe_float(row.get("daily_sales_before")), 2),
            "daily_sales_after": round(safe_float(row.get("daily_sales_after")), 2),
            "daily_sales_change": round(safe_float(row.get("daily_sales_change")), 2),
            "revenue_before": round(safe_float(row.get("revenue_before")), 2),
            "revenue_after": round(safe_float(row.get("revenue_after")), 2),
            "revenue_change": round(safe_float(row.get("revenue_change")), 2),
            "profit_before": round(safe_float(row.get("profit_before")), 2),
            "profit_after": round(safe_float(row.get("profit_after")), 2),
            "profit_change": round(safe_float(row.get("profit_change")), 2),
            "margin_before": round(safe_float(row.get("margin_before")), 4),
            "margin_after": round(safe_float(row.get("margin_after")), 4),
            "margin_change": round(safe_float(row.get("margin_change")), 4),
            "sessions_before": safe_int(row.get("sessions_before")),
            "sessions_after": safe_int(row.get("sessions_after")),
            "sessions_change": safe_int(row.get("sessions_change")),
            "sessions_change_rate": round(
                safe_float(row.get("sessions_change")) / safe_float(row.get("sessions_before")),
                4,
            ) if safe_float(row.get("sessions_before")) else 0.0,
            "conversion_before": round(safe_float(row.get("conversion_before")), 4),
            "conversion_after": round(safe_float(row.get("conversion_after")), 4),
            "conversion_change": round(safe_float(row.get("conversion_after")) - safe_float(row.get("conversion_before")), 4),
            "ctr_before": round(safe_float(row.get("ctr_before")), 4),
            "ctr_after": round(safe_float(row.get("ctr_after")), 4),
            "ctr_change": round(safe_float(row.get("ctr_after")) - safe_float(row.get("ctr_before")), 4),
            "ad_spend_before": round(safe_float(row.get("ad_spend_before")), 2),
            "ad_spend_after": round(safe_float(row.get("ad_spend_after")), 2),
            "ad_spend_change": round(safe_float(row.get("ad_spend_after")) - safe_float(row.get("ad_spend_before")), 2),
            "ad_revenue_before": round(safe_float(row.get("ad_revenue_before")), 2),
            "ad_revenue_after": round(safe_float(row.get("ad_revenue_after")), 2),
            "acos_before": round(safe_float(row.get("acos_before")), 4),
            "acos_after": round(safe_float(row.get("acos_after")), 4),
            "acos_change": round(safe_float(row.get("acos_after")) - safe_float(row.get("acos_before")), 4),
            "tacos_before": round(safe_float(row.get("tacos_before")), 4),
            "tacos_after": round(safe_float(row.get("tacos_after")), 4),
            "tacos_change": round(safe_float(row.get("tacos_after")) - safe_float(row.get("tacos_before")), 4),
            "cpc_before": round(safe_float(row.get("cpc_before")), 2),
            "cpc_after": round(safe_float(row.get("cpc_after")), 2),
            "cpc_change": round(safe_float(row.get("cpc_after")) - safe_float(row.get("cpc_before")), 2),
            "rank_before": safe_int(row.get("rank_before")),
            "rank_after": safe_int(row.get("rank_after")),
            "rank_change": safe_int(row.get("rank_change")),
            "sales_band_before": safe_str(row.get("sales_band_before")),
            "sales_band_after": safe_str(row.get("sales_band_after")),
            "daily_sales_band_before": safe_str(row.get("daily_sales_band_before")),
            "daily_sales_band_after": safe_str(row.get("daily_sales_band_after")),
            "margin_band_before": safe_str(row.get("margin_band_before")),
            "margin_band_after": safe_str(row.get("margin_band_after")),
            "rank_band_before": safe_str(row.get("rank_band_before")),
            "rank_band_after": safe_str(row.get("rank_band_after")),
            "risk_level": safe_str(row.get("risk_level")),
            "issue_tags": safe_str(row.get("issue_tags")),
            "suggested_action": safe_str(row.get("suggested_action")),
        }

    def _latest_product_data_date(self) -> date | None:
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("select max(dt_date) as max_date from dashboard_product_performance_daily")
                    return (cursor.fetchone() or {}).get("max_date")
        except pymysql.MySQLError:
            return None

    def _latest_available_adjust_date(self, compare_days: int) -> date | None:
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        select max(adjust_date) as adjust_date
                        from price_review_sku_tracking
                        where period_days = %(period_days)s
                        """,
                        {"period_days": compare_days},
                    )
                    return (cursor.fetchone() or {}).get("adjust_date")
        except pymysql.MySQLError:
            return None

    def _period_incomplete(self, adjust_date: date, compare_days: int, has_rows: bool) -> bool:
        if has_rows:
            return False
        latest = self._latest_product_data_date()
        if latest is None:
            return False
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        select count(*) as total
                        from price_review_adjustment_source
                        where adjust_date = %(adjust_date)s
                        """,
                        {"adjust_date": adjust_date},
                    )
                    has_adjustments = int((cursor.fetchone() or {}).get("total") or 0) > 0
        except pymysql.MySQLError:
            return False
        return has_adjustments and latest < adjust_date + timedelta(days=compare_days)

    def _filter_skus(
        self,
        skus: list[dict[str, Any]],
        country: str = "",
        drop_range: str = "",
        risk_level: str = "",
        store: str = "",
        price_band: str = "",
        adjustment_type: str = "",
        keyword: str = "",
    ) -> list[dict[str, Any]]:
        rows = list(skus)
        if country and country != "all":
            rows = [r for r in rows if r["country"] == country]
        if drop_range and drop_range != "all":
            rows = [r for r in rows if r["drop_range"] == drop_range]
        if risk_level and risk_level != "all":
            rows = [r for r in rows if r["risk_level"] == risk_level]
        if store and store != "all":
            rows = [r for r in rows if r["store"] == store]
        if price_band and price_band != "all":
            rows = [r for r in rows if r["price_band"] == price_band]
        if adjustment_type and adjustment_type != "all":
            rows = [r for r in rows if r["adjustment_type"] == adjustment_type]
        if keyword:
            kw = keyword.lower()
            rows = [
                r for r in rows
                if kw in r["country"].lower()
                or kw in r["store"].lower()
                or kw in r["msku"].lower()
                or kw in r["product_name"].lower()
            ]
        return rows

    # -----------------------------------------------------------------------
    # API payload builders
    # -----------------------------------------------------------------------
    def get_overview_payload(self, adjust_date: date | None = None, compare_days: int = 14, country: str = "", drop_range: str = "", risk_level: str = "", store: str = "", price_band: str = "", adjustment_type: str = "", keyword: str = "") -> dict[str, Any]:
        data = self.load(adjust_date, compare_days)
        filtered = self._filter_skus(data.sku_list, country, drop_range, risk_level, store, price_band, adjustment_type, keyword)
        overall = data.overall if len(filtered) == len(data.sku_list) else _build_overall(filtered, compare_days)
        kpi_keys = {
            "销量（个）": {"key": "sales", "label": "总销量", "type": "number"},
            "日销（个/天）": {"key": "daily_sales", "label": "日销", "type": "number"},
            "销售额": {"key": "revenue", "label": "总销售额", "type": "currency"},
            "订单毛利率": {"key": "margin", "label": "订单毛利率", "type": "percent"},
            "sessions": {"key": "sessions", "label": "Sessions", "type": "number"},
            "CVR（转化率）": {"key": "cvr", "label": "CVR", "type": "percent"},
            "CTR（点击率）": {"key": "ctr", "label": "CTR", "type": "percent"},
            "ACOS": {"key": "acos", "label": "ACOS", "type": "percent"},
            "TACOS": {"key": "tacos", "label": "TACOS", "type": "percent"},
            "广告花费": {"key": "ad_spend", "label": "广告花费", "type": "currency"},
        }
        kpis = []
        for item in overall:
            cfg = kpi_keys.get(item["metric"])
            if not cfg:
                continue
            before = item["before"]
            after = item["after"]
            change = item["change"]
            change_rate = item["change_rate"]
            is_better = change > 0
            if cfg["key"] in ("returns", "ad_spend"):
                is_better = change < 0
            elif cfg["key"] == "acos":
                is_better = abs(change) < 0.01
            tone = "positive" if is_better else "negative" if change != 0 else "warning"
            kpis.append({
                "key": cfg["key"],
                "label": cfg["label"],
                "type": cfg["type"],
                "before": before,
                "after": after,
                "change": change,
                "change_rate": change_rate,
                "interpretation": item["interpretation"],
                "tone": tone,
            })
        return {
            "kpis": kpis,
            "sku_count": len(filtered),
            "country_count": len({s["country"] for s in filtered if s["country"]}),
            "period_incomplete": data.period_incomplete,
            "latest_data_date": data.latest_data_date.isoformat() if data.latest_data_date else None,
        }

    def get_drop_range_payload(self, adjust_date: date | None = None, compare_days: int = 14, country: str = "", drop_range: str = "", risk_level: str = "", store: str = "", price_band: str = "", adjustment_type: str = "", keyword: str = "") -> dict[str, Any]:
        data = self.load(adjust_date, compare_days)
        filtered = self._filter_skus(data.sku_list, country, drop_range, risk_level, store, price_band, adjustment_type, keyword)
        items = data.drop_range_analysis if len(filtered) == len(data.sku_list) else _build_drop_range_analysis(filtered)
        return {
            "items": items,
            "period_incomplete": data.period_incomplete,
            "latest_data_date": data.latest_data_date.isoformat() if data.latest_data_date else None,
        }

    def get_matrices_payload(self, adjust_date: date | None = None, compare_days: int = 14, country: str = "", drop_range: str = "", risk_level: str = "", store: str = "", price_band: str = "", adjustment_type: str = "", keyword: str = "") -> dict[str, Any]:
        data = self.load(adjust_date, compare_days)
        filtered = self._filter_skus(data.sku_list, country, drop_range, risk_level, store, price_band, adjustment_type, keyword)
        if len(filtered) == len(data.sku_list):
            return {
                "sales": data.sales_band_matrix,
                "daily_sales": data.daily_sales_band_matrix,
                "margin": data.margin_band_matrix,
                "rank": data.rank_band_matrix,
                "period_incomplete": data.period_incomplete,
                "latest_data_date": data.latest_data_date.isoformat() if data.latest_data_date else None,
            }
        return {
            "sales": _build_matrix(filtered, "sales_band_before", "sales_band_after", "sales_before", "sales_after", "sales"),
            "daily_sales": _build_matrix(filtered, "daily_sales_band_before", "daily_sales_band_after", "daily_sales_before", "daily_sales_after", "daily_sales"),
            "margin": _build_matrix(filtered, "margin_band_before", "margin_band_after", "revenue_before", "revenue_after", "margin"),
            "rank": _build_matrix(filtered, "rank_band_before", "rank_band_after", "rank_before", "rank_after", "rank"),
            "period_incomplete": data.period_incomplete,
            "latest_data_date": data.latest_data_date.isoformat() if data.latest_data_date else None,
        }

    def get_country_payload(self, adjust_date: date | None = None, compare_days: int = 14, country: str = "", drop_range: str = "", risk_level: str = "", store: str = "", price_band: str = "", adjustment_type: str = "", keyword: str = "") -> dict[str, Any]:
        data = self.load(adjust_date, compare_days)
        filtered = self._filter_skus(data.sku_list, country, drop_range, risk_level, store, price_band, adjustment_type, keyword)
        items = data.country_stats if len(filtered) == len(data.sku_list) else _build_country_stats(filtered)
        return {
            "items": items,
            "period_incomplete": data.period_incomplete,
            "latest_data_date": data.latest_data_date.isoformat() if data.latest_data_date else None,
        }

    def get_second_adjustments_payload(self, adjust_date: date | None = None, compare_days: int = 14, country: str = "", drop_range: str = "", risk_level: str = "", store: str = "", price_band: str = "", adjustment_type: str = "", keyword: str = "") -> dict[str, Any]:
        data = self.load(adjust_date, compare_days)
        filtered = self._filter_skus(data.sku_list, country, drop_range, risk_level, store, price_band, adjustment_type, keyword)
        payload = _build_second_adjustment_timing(filtered)
        payload["period_incomplete"] = data.period_incomplete
        payload["latest_data_date"] = data.latest_data_date.isoformat() if data.latest_data_date else None
        return payload

    def get_top_lists_payload(self, adjust_date: date | None = None, compare_days: int = 14, country: str = "", drop_range: str = "", risk_level: str = "", store: str = "", price_band: str = "", adjustment_type: str = "", keyword: str = "") -> dict[str, Any]:
        data = self.load(adjust_date, compare_days)
        filtered = self._filter_skus(data.sku_list, country, drop_range, risk_level, store, price_band, adjustment_type, keyword)
        if len(filtered) == len(data.sku_list):
            return {
                "sales_up": data.top_sales_up,
                "sales_down": data.top_sales_down,
                "rank_improve": data.top_rank_improve,
                "rank_worsen": data.top_rank_worsen,
                "period_incomplete": data.period_incomplete,
                "latest_data_date": data.latest_data_date.isoformat() if data.latest_data_date else None,
            }
        top_lists = _build_top_lists(filtered)
        top_lists["period_incomplete"] = data.period_incomplete
        top_lists["latest_data_date"] = data.latest_data_date.isoformat() if data.latest_data_date else None
        return top_lists

    def get_sku_list_payload(
        self,
        page: int = 1,
        page_size: int = 20,
        country: str = "",
        drop_range: str = "",
        risk_level: str = "",
        store: str = "",
        price_band: str = "",
        adjustment_type: str = "",
        keyword: str = "",
        adjust_date: date | None = None,
        compare_days: int = 14,
    ) -> dict[str, Any]:
        data = self.load(adjust_date, compare_days)
        rows = list(data.sku_list)

        if country and country != "all":
            rows = [r for r in rows if r["country"] == country]
        if drop_range and drop_range != "all":
            rows = [r for r in rows if r["drop_range"] == drop_range]
        if risk_level and risk_level != "all":
            rows = [r for r in rows if r["risk_level"] == risk_level]
        if store and store != "all":
            rows = [r for r in rows if r["store"] == store]
        if price_band and price_band != "all":
            rows = [r for r in rows if r["price_band"] == price_band]
        if adjustment_type and adjustment_type != "all":
            rows = [r for r in rows if r["adjustment_type"] == adjustment_type]
        if keyword:
            kw = keyword.lower()
            rows = [
                r for r in rows
                if kw in r["country"].lower()
                or kw in r["store"].lower()
                or kw in r["msku"].lower()
                or kw in r["product_name"].lower()
            ]

        total = len(rows)
        total_pages = max(1, math.ceil(total / page_size))
        safe_page = min(max(page, 1), total_pages)
        start = (safe_page - 1) * page_size
        page_rows = rows[start:start + page_size]

        return {
            "rows": page_rows,
            "total": total,
            "page": safe_page,
            "page_size": page_size,
            "total_pages": total_pages,
            "filters": data.filter_options,
            "period_incomplete": data.period_incomplete,
            "latest_data_date": data.latest_data_date.isoformat() if data.latest_data_date else None,
        }

    def get_top_lists_export_payload(self, adjust_date: date | None = None, compare_days: int = 14, country: str = "", drop_range: str = "", risk_level: str = "", store: str = "", price_band: str = "", adjustment_type: str = "", keyword: str = "") -> list[dict[str, Any]]:
        data = self.load(adjust_date, compare_days)
        filtered = self._filter_skus(data.sku_list, country, drop_range, risk_level, store, price_band, adjustment_type, keyword)
        if len(filtered) == len(data.sku_list):
            top_lists = {
                "sales_up": data.top_sales_up,
                "sales_down": data.top_sales_down,
                "rank_improve": data.top_rank_improve,
                "rank_worsen": data.top_rank_worsen,
            }
        else:
            top_lists = _build_top_lists(filtered)
        rows: list[dict[str, Any]] = []
        type_map = {
            "sales_up": "销量增长",
            "sales_down": "销量下降",
            "rank_improve": "排名改善",
            "rank_worsen": "排名恶化",
        }
        for key, label in type_map.items():
            for item in top_lists[key]:
                row = dict(item)
                row["类型"] = label
                rows.append(row)
        return rows

    def get_sku_list_export_payload(
        self,
        country: str = "",
        drop_range: str = "",
        risk_level: str = "",
        store: str = "",
        price_band: str = "",
        adjustment_type: str = "",
        keyword: str = "",
        adjust_date: date | None = None,
        compare_days: int = 14,
    ) -> list[dict[str, Any]]:
        data = self.load(adjust_date, compare_days)
        rows = list(data.sku_list)

        if country and country != "all":
            rows = [r for r in rows if r["country"] == country]
        if drop_range and drop_range != "all":
            rows = [r for r in rows if r["drop_range"] == drop_range]
        if risk_level and risk_level != "all":
            rows = [r for r in rows if r["risk_level"] == risk_level]
        if store and store != "all":
            rows = [r for r in rows if r["store"] == store]
        if price_band and price_band != "all":
            rows = [r for r in rows if r["price_band"] == price_band]
        if adjustment_type and adjustment_type != "all":
            rows = [r for r in rows if r["adjustment_type"] == adjustment_type]
        if keyword:
            kw = keyword.lower()
            rows = [
                r for r in rows
                if kw in r["country"].lower()
                or kw in r["store"].lower()
                or kw in r["msku"].lower()
                or kw in r["product_name"].lower()
            ]
        return rows

    def get_daily_adjustment_counts(self, days: int = 30) -> list[dict[str, Any]]:
        today = date.today()
        start_date = today - timedelta(days=days - 1)
        counts: dict[date, int] = {}
        latest_data_date = self._latest_product_data_date()
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        select adjust_date, count(*) as total
                        from price_review_adjustment_source
                        where adjust_date between %(start_date)s and %(today)s
                        group by adjust_date
                        """,
                        {"start_date": start_date, "today": today},
                    )
                    counts = {row["adjust_date"]: int(row["total"] or 0) for row in cursor.fetchall()}
        except pymysql.MySQLError:
            counts = {}

        result = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            count = counts.get(d, 0)
            clickable = bool(count and latest_data_date and latest_data_date >= d + timedelta(days=7))
            result.append({
                "date": d.isoformat(),
                "display_date": f"{d.month}月{d.day}日",
                "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][d.weekday()],
                "count": count,
                "clickable": clickable,
                "is_today": d == today,
                "is_weekend": d.weekday() >= 5,
            })
        return result


price_review_service = PriceReviewService()
