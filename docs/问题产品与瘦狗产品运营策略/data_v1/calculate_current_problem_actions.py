"""Recalculate current problem-product actions from facts and the current framework.

No database writes or advertising API calls. Old wide-table recommendations are ignored.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from pathlib import Path

from extract_inputs import write_json

D = Decimal
CENT = D("0.01")
COUNTRY = {"德国": "DE", "法国": "FR", "意大利": "IT", "西班牙": "ES", "荷兰": "NL", "英国": "UK", "美国": "US"}
CURRENCY = {"美国": "USD", "英国": "GBP", **{c: "EUR" for c in COUNTRY if c not in ("美国", "英国")}}


def n(value):
    try:
        result = D(str(value))
        return result if result.is_finite() else None
    except (TypeError, ValueError, ArithmeticError):
        return None


def active(row):
    return row is not None and row.get("delete_flag") in (0, False, "b'\\x00'") and str(row.get("state", "")).lower() == "enabled"


def newest(rows, fields):
    result = {}
    for row in rows:
        key = tuple(str(row.get(f)) for f in fields)
        rank = (str(row.get("update_time") or row.get("create_time") or ""), int(row.get("id") or 0))
        if key not in result or rank > result[key][0]:
            result[key] = (rank, row)
    return {key: value[1] for key, value in result.items()}


def bid_rule(auto, clicks, orders, cost, sales, tacos):
    if None in (clicks, orders, cost, sales) or min(clicks, orders, cost, sales) < 0:
        return None, "对象指标缺失或异常"
    acos = cost / sales if sales > 0 else None
    cvr = orders / clicks if clicks > 0 else None
    if auto:
        if orders == 0 and clicks >= 63: return ("100202", D("-.20")), None
        if orders == 0 and clicks >= 34: return ("100201", D("-.10")), None
        if orders == 1 and clicks >= 63: return ("100204", D("-.10")), None
        if orders == 1 and 34 <= clicks <= 62 and ((acos is not None and acos > D(".5")) or (cvr is not None and cvr < D(".03"))):
            return ("100203", D("-.05")), None
        if orders >= 2 and acos is not None:
            if acos > D(".65"): return ("100206", D("-.20")), None
            if acos >= D(".5"): return ("100205", D("-.10")), None
            if acos >= D(".4") and cvr is not None and cvr < D(".03"): return ("100207", D("-.05")), None
            if tacos is not None and tacos < D(".1"):
                if clicks >= 80 and orders >= 5 and acos <= D(".2") and cvr >= D(".07"): return ("100210", D(".15")), None
                if clicks >= 40 and orders >= 3 and acos <= D(".3") and cvr >= D(".07"): return ("100209", D(".10")), None
                if clicks >= 15 and acos <= D(".4") and cvr >= D(".05"): return ("100208", D(".05")), None
    else:
        if orders >= 2 and acos is not None:
            if acos >= D(".5"): return ("100302", D("-.20")), None
            if acos > D(".3"): return ("100301", D("-.10")), None
            if clicks >= 10 and acos <= D(".2") and tacos is not None and tacos < D(".1"):
                return ("100306", D(".10")) if tacos <= D(".05") else ("100307", D(".05")), None
    return None, None


def suggested_bid(current, rate, auto):
    if current is None or current <= 0:
        return None
    proposed = (current * (1 + rate)).quantize(CENT, rounding=ROUND_HALF_UP)
    if auto and proposed == current:
        proposed += CENT if rate > 0 else -CENT
    if proposed <= 0 or (rate > 0 and proposed <= current) or (rate < 0 and proposed >= current):
        return None
    return proposed


def next_price_target(current, p10, p15, p20, p25):
    """Step down one valid margin-price tier, rounded up to a payable cent."""
    if None in (current, p10, p15, p20, p25) or not (0 < p10 < p15 < p20 < p25):
        return None
    target = p25 if current > p25 else p20 if current > p20 else p15 if current > p15 else p10
    proposed = target.quantize(CENT, rounding=ROUND_CEILING)
    return proposed if p10 <= proposed < current else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root
    out = root / "problem_actions_current"
    out.mkdir(exist_ok=True)

    def read(name):
        return json.loads((root / f"{name}.json").read_text(encoding="utf-8"))

    source_manifest = read("manifest")
    label_day = str(source_manifest["sources"]["labels"]["date"])
    bid_day = str(source_manifest["sources"]["bid_objects"]["date"])
    raw_products = [p for p in read("product_base") if p["source_roles"] == ["problem"]]
    products = {(p["country"], p["store"], p["msku"]): p for p in raw_products}
    metrics_rows = defaultdict(list)
    for row in read("support_metrics"):
        metrics_rows[(row["country"], row["store"], row["msku"])].append(row)
    aliases = defaultdict(set)
    for p in read("pricing"):
        if p["国家"] in COUNTRY and p.get("新店铺"):
            aliases[(COUNTRY[p["国家"]], str(p["店铺名"]).casefold())].add(p["新店铺"])

    def resolve(code, store, sku, base=None):
        code = str(code).upper().replace("GB", "UK")
        country = next((c for c, v in COUNTRY.items() if v == code), None)
        stores = {base} if base else aliases.get((code, str(store).casefold()), set())
        if len(stores) != 1:
            return None
        key = (country, next(iter(stores)), sku)
        return key if key in products else None

    accounts = newest(read("support_accounts"), ("profile_id",))
    campaigns = newest(read("support_campaigns"), ("profile_id", "entity_id"))
    groups = newest(read("support_ad_groups"), ("profile_id", "entity_id"))
    ads = newest(read("support_product_ads"), ("profile_id", "ad_id"))
    targets = newest(read("current_targets"), ("profile_id", "target_id"))
    keywords = newest(read("current_keywords"), ("profile_id", "keyword_id"))
    negatives = newest(read("current_negatives"), ("profile_id", "target_id"))
    bid_attrs = {r["row_key"]: r for r in read("support_bid_attribution")}
    term_attrs = {r["row_key"]: r for r in read("support_term_attribution")}
    budgets = defaultdict(list)
    for row in read("budget"):
        budgets[(row["country"], row["seller_name_new"], row["seller_sku_adj"])].append(row)
    spend_by_profile_sku = defaultdict(lambda: [D(0), D(0)])
    for row in read("current_product_spend"):
        key = (str(row["profile_id"]), row["sku"])
        spend_by_profile_sku[key][0] += n(row["month_spend"]) or D(0)
        spend_by_profile_sku[key][1] += n(row["week_spend"]) or D(0)
    sp_aov = {}
    if (root / "current_sp_aov_60d.json").exists():
        for row in read("current_sp_aov_60d"):
            orders, sales = n(row["same_orders_7d"]), n(row["same_sales_7d"])
            if orders is not None and orders > 0 and sales is not None and sales > 0:
                sp_aov[(str(row["profile_id"]), row["sku"])] = sales / orders

    profile_keys = defaultdict(set)
    for (profile,), account in accounts.items():
        if account.get("delete_flag") not in (0, False, "b'\\x00'"):
            continue
        code = str(account["country_code"]).upper().replace("GB", "UK")
        for store in aliases.get((code, str(account["name"]).casefold()), set()):
            profile_keys[(code, store.casefold())].add(profile)

    def budget_evidence(key, estimated_increment):
        rows = budgets.get(key, [])
        profiles = profile_keys.get((COUNTRY[key[0]], key[1].casefold()), set())
        if len(rows) != 1 or len(profiles) != 1:
            return False, "预算或广告账号映射不唯一", {}
        row = rows[0]
        if row["currency_code"] != CURRENCY[key[0]]:
            return False, "预算币种与站点不一致", {}
        month_budget, week_budget = n(row["monthly_ad_budget_original"]), n(row["weekly_ad_budget_original"])
        if month_budget is None or week_budget is None or month_budget <= 0 or week_budget <= 0:
            return False, "商品月周预算缺失或非正", {}
        profile = next(iter(profiles))
        month_spend, week_spend = spend_by_profile_sku[(profile, key[2])]
        label_date = date.fromisoformat(label_day)
        elapsed_month = label_date.day
        elapsed_week = label_date.weekday() + 1
        month_days = (label_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        remaining_month = (month_days - label_date).days - 1
        remaining_week = 7 - elapsed_week
        baseline_month = month_spend / elapsed_month * remaining_month
        baseline_week = week_spend / elapsed_week * remaining_week
        available_month = month_budget - month_spend - baseline_month
        available_week = week_budget - week_spend - baseline_week
        evidence = {"month_budget": month_budget, "week_budget": week_budget,
                    "month_spend": month_spend, "week_spend": week_spend,
                    "future_baseline_month": baseline_month, "future_baseline_week": baseline_week,
                    "available_month": available_month, "available_week": available_week,
                    "budget_method": "本月/本周已花费÷已过天数×剩余天数，预留基础消耗"}
        if min(available_month, available_week) < estimated_increment:
            return False, "扣除未来基础消耗后月或周预算不足", evidence
        return True, None, evidence

    ads_by_product = defaultdict(list)
    for ad in ads.values():
        account = accounts.get((str(ad["profile_id"]),))
        if not account:
            continue
        key = resolve(account["country_code"], ad["seller_name"], ad["sku"])
        if key:
            ads_by_product[key].append(ad)

    # Each ODS search-term row is a factual observation. Coverage against the
    # wide table's ad-group traffic is checked before target-level bid decisions.
    target_facts = defaultdict(lambda: [D(0), D(0), D(0), D(0)])
    group_facts = defaultdict(lambda: [D(0), D(0)])
    for row in read("current_search_terms"):
        key = (str(row["profile_id"]), str(row["campaign_id"]), str(row["ad_group_id"]), str(row["target_id"]))
        values = target_facts[key]
        for idx, field in enumerate(("clicks", "cost", "same_orders_7d", "same_sales_7d")):
            values[idx] += n(row[field]) or D(0)
        group_facts[key[:3]][0] += n(row["clicks"]) or D(0)
        group_facts[key[:3]][1] += n(row["cost"]) or D(0)

    actions, blocked, coverage = [], [], []
    seen_action = set()

    def emit(key, kind, rule, entity, *, blocker=None, **facts):
        row = {"country": key[0], "store": key[1], "msku": key[2], "action_type": kind,
               "rule_code": rule, "entity": entity, "label_date": label_day,
               "bid_snapshot_date": bid_day, "status": "BLOCKED" if blocker else "MANUAL_REVIEW", **facts}
        if blocker:
            row["blocker"] = blocker
            blocked.append(row)
        elif (key, kind, entity) not in seen_action:
            seen_action.add((key, kind, entity))
            actions.append(row)

    eligible = set()
    for key, product in products.items():
        metrics = metrics_rows.get(key, [])
        metric = metrics[0] if len(metrics) == 1 and n(metrics[0]["period_days"]) == 30 else None
        qty = n(metric["sales_volume"]) if metric else None
        price = product["pricing_input"]
        reasons = []
        if qty is None or qty < 0:
            reasons.append("30天销量缺失或重复")
        elif qty / 30 > 1:
            reasons.append("日销已高于1")
        else:
            eligible.add(key)
            if not price or product["pricing_match_count"] != 1:
                reasons.append("定价缺失或不唯一")
            elif price.get("币种") != CURRENCY[key[0]] or price.get("数据异常备注"):
                reasons.append("币种或定价异常")
            elif n(metric.get("fba_available_inventory")) is None or n(metric["fba_available_inventory"]) <= 0:
                reasons.append("FBA可售缺失或断货，价格测试待核")
            else:
                current, p10, p15, p20, p25 = (n(price.get(f)) for f in
                                                ("listing价格", "10毛利润价格", "15毛利润价格",
                                                 "20毛利润价格", "25毛利润价格"))
                if None in (current, p10, p15, p20, p25) or not (0 < p10 < p15 < p20 < p25):
                    reasons.append("价格线缺失或反向")
                elif current <= p10:
                    reasons.append("已到P10")
                else:
                    rule = "100101" if current > p25 else "100102"
                    target_tier = "P25" if current > p25 else "P20" if current > p20 else "P15" if current > p15 else "P10"
                    value = next_price_target(current, p10, p15, p20, p25)
                    if value is None:
                        reasons.append("取整后无降价空间")
                    else:
                        emit(key, "调价", rule, "price", current_value=current, suggested_value=value,
                             currency=price["币种"], price_date=price["数据日期"],
                             target_tier=target_tier, p10=p10, p15=p15, p20=p20, p25=p25)

            profiles = profile_keys.get((COUNTRY[key[0]], key[1].casefold()), set())
            ad_rows = [a for a in ads_by_product.get(key, []) if a.get("delete_flag") in (0, False, "b'\\x00'")]
            ad_states = []
            for ad in ad_rows:
                profile = str(ad["profile_id"])
                campaign = campaigns.get((profile, str(ad["campaign_id"])))
                group = groups.get((profile, str(ad["ad_group_id"])))
                if campaign and group:
                    ad_states.append(all(active(r) for r in (ad, campaign, group)))
            if not any(ad_states):
                if len(profiles) != 1 or len(ad_states) != len(ad_rows) or not ad_rows:
                    reasons.append("广告实体或账号同步完整性待核")
                else:
                    structures = []
                    for ad in ad_rows:
                        profile = str(ad["profile_id"])
                        campaign = campaigns[(profile, str(ad["campaign_id"]))]
                        group = groups[(profile, str(ad["ad_group_id"]))]
                        structures.append({"profile_id": profile, "ad_id": str(ad["ad_id"]),
                                           "campaign_id": str(ad["campaign_id"]),
                                           "ad_group_id": str(ad["ad_group_id"]),
                                           "ad_state": ad["state"], "campaign_state": campaign["state"],
                                           "group_state": group["state"]})
                    emit(key, "开启广告", "100801", "ad_enable", profile_id=next(iter(profiles)),
                         evidence="有停用商品广告及完整父实体，执行前核验启用或重建",
                         existing_structures=structures)
            elif n(metric.get("ad_spend")) == 0:
                reasons.append("已开启但30天零花费；曝光测试须核验预算、库存及首次测试状态")
                emit(key, "曝光测试待核", "100601", "zero_spend_exposure",
                     blocker="首次曝光测试状态及有效竞价对象未核实", ad_spend_30d=0,
                     fba_available_inventory=metric.get("fba_available_inventory"))

        coverage.append({"country": key[0], "store": key[1], "msku": key[2], "label_date": label_day,
                         "metric_date": metric["data_date"] if metric else None, "sales_30d": qty,
                         "daily_sales": qty / 30 if qty is not None else None, "reasons": reasons})

    # Resolve and audit the wide table's factual attribution, not its suggestions.
    for row in read("bid_objects"):
        key = resolve(row["country_code"], row["seller_name"], row["msku"], row.get("base_store_name"))
        if key not in eligible:
            continue
        if row["msku_mapping_status"] != "mapped" or any(n(row[f]) != 1 for f in
              ("associated_msku_count", "period_msku_count", "current_enabled_msku_count")):
            continue
        if any(str(row[f]).lower() != "enabled" for f in
               ("campaign_state_current", "ad_group_state_current", "object_state_current")):
            continue
        if any(n(row[f]) != 30 for f in ("source_keyword_days", "source_ad_group_days", "source_product_ad_days")):
            continue
        if not row.get("mature_end") or (date.fromisoformat(row["snapshot_date"]) - date.fromisoformat(row["mature_end"])).days < 7:
            continue
        profile, campaign, group = (str(row[f]) for f in ("profile_id", "campaign_id", "ad_group_id"))
        if not active(campaigns.get((profile, campaign))) or not active(groups.get((profile, group))):
            continue
        metric_rows = metrics_rows.get(key, [])
        tacos = n(metric_rows[0].get("tacos")) if len(metric_rows) == 1 else None
        auto = row["targeting_type"] == "auto" and row["object_type"] == "ad_group"
        manual = row["targeting_type"] == "manual" and row["object_type"] == "keyword"
        if not (auto or manual):
            continue
        if auto:
            expected_clicks, expected_cost = n(row["clicks"]), n(row["cost"])
            observed_clicks, observed_cost = group_facts[(profile, campaign, group)]
            if expected_clicks is None or expected_cost is None or observed_clicks != expected_clicks or abs(observed_cost - expected_cost) > D(".02"):
                emit(key, "竞价待核", "", f"group:{profile}:{group}", blocker="搜索词对自动组流量覆盖不一致，不能分配到target",
                     expected_clicks=expected_clicks, observed_clicks=observed_clicks,
                     expected_cost=expected_cost, observed_cost=observed_cost)
                continue
            target_rows = [t for (p, _), t in targets.items() if p == profile and str(t["ad_group_id"]) == group and active(t)]
            for target in target_rows:
                target_id = str(target["target_id"])
                clicks, cost, orders, sales = target_facts[(profile, campaign, group, target_id)]
                rule, reason = bid_rule(True, clicks, orders, cost, sales, tacos)
                if reason:
                    emit(key, "竞价待核", "", target_id, blocker=reason)
                if not rule:
                    continue
                code, rate = rule
                current = n(target["bid"]) or n(groups[(profile, group)].get("default_bid"))
                value = suggested_bid(current, rate, True)
                blocker = None
                budget_details = {}
                if n(target["bid"]) is None:
                    blocker = "target未设独立bid，须核实默认bid继承与执行对象"
                elif value is None:
                    blocker = "当前bid或舍入后建议值无效"
                elif rate > 0:
                    days_left = min(7, 7 - date.fromisoformat(label_day).weekday())
                    increment = (cost / 30 * D(days_left) * rate).quantize(CENT, rounding=ROUND_CEILING)
                    allowed, budget_reason, budget_details = budget_evidence(key, increment)
                    blocker = budget_reason if not allowed else None
                else:
                    budget_details = {}
                emit(key, "降低竞价" if rate < 0 else "提高竞价", code, f"target:{profile}:{target_id}",
                     blocker=blocker, profile_id=profile, campaign_id=campaign, ad_group_id=group,
                     object_id=target_id, object_text=target["expression"], current_value=current,
                     suggested_value=value if not blocker else None, change_rate=rate,
                     clicks=clicks, orders=orders, cost=cost, sales=sales, tacos=tacos,
                     attribution="ODS搜索词同MSKU 7天归因、成熟30天窗口",
                     budget_evidence=budget_details if rate > 0 else {},
                     platform_bid_bounds="待平台最终核验")
        else:
            keyword_id = str(row["object_id"])
            keyword = keywords.get((profile, keyword_id))
            if not active(keyword):
                continue
            attrs = bid_attrs.get(row["row_key"])
            if not attrs:
                continue
            clicks, cost = n(row["clicks"]), n(row["cost"])
            orders, sales = n(attrs["same_sku_attributed_orders_7d"]), n(attrs["same_sku_attributed_sales_7d"])
            rule, reason = bid_rule(False, clicks, orders, cost, sales, tacos)
            if rule is None and orders == 0 and clicks is not None and cost is not None and clicks >= 12:
                aov = sp_aov.get((profile, key[2]))
                if aov is None:
                    reason = "60天SP客单价没有有效订单或销售额"
                else:
                    ratio = cost / aov
                    if 12 <= clicks <= 33:
                        if ratio >= D(".5"): rule, reason = ("100304", D("-.20")), None
                        elif ratio >= D(".2"): rule, reason = ("100303", D("-.10")), None
                    elif clicks >= 34 and D(".2") <= ratio <= D(".5"):
                        rule, reason = ("100305", D("-.15")), None
            if reason:
                emit(key, "竞价待核", "", f"keyword:{profile}:{keyword_id}", blocker=reason)
            if not rule:
                continue
            code, rate = rule
            current = n(keyword["bid"])
            value = suggested_bid(current, rate, False)
            blocker = "当前bid或舍入后建议值无效" if value is None else None
            if rate > 0 and value is not None:
                days_left = min(7, 7 - date.fromisoformat(label_day).weekday())
                increment = (cost / 30 * D(days_left) * rate).quantize(CENT, rounding=ROUND_CEILING)
                allowed, budget_reason, budget_details = budget_evidence(key, increment)
                blocker = budget_reason if not allowed else None
            else:
                budget_details = {}
            emit(key, "降低竞价" if rate < 0 else "提高竞价", code, f"keyword:{profile}:{keyword_id}",
                 blocker=blocker, profile_id=profile, campaign_id=campaign, ad_group_id=group,
                 object_id=keyword_id, object_text=keyword["keyword_text"], current_value=current,
                 suggested_value=value if not blocker else None, change_rate=rate,
                 clicks=clicks, orders=orders, cost=cost, sales=sales, tacos=tacos,
                 attribution="宽表成熟30天观察、同MSKU 7天归因事实",
                 budget_evidence=budget_details, platform_bid_bounds="待平台最终核验")

    term_groups = defaultdict(list)
    for row in read("search_terms"):
        key = resolve(row["country_code"], row["seller_name"], row["msku"])
        if key not in eligible or n(row.get("is_auto_campaign")) != 1 or not row.get("search_term_normalized"):
            continue
        if row.get("msku_mapping_status") != "mapped" or row.get("period_msku_candidates") != key[2] or row.get("current_msku_candidates") != key[2]:
            continue
        term_groups[(key, str(row["profile_id"]), str(row["campaign_id"]),
                     str(row["ad_group_id"]), row["search_term_normalized"])].append(row)

    for (key, profile, campaign, group, word), rows in term_groups.items():
        if not active(campaigns.get((profile, campaign))) or not active(groups.get((profile, group))):
            continue
        attrs = [term_attrs.get(r["row_key"]) for r in rows]
        if any(a is None or n(a.get("attribution_7d_mature")) != 1 for a in attrs):
            continue
        if any(n(r.get("source_search_term_days")) != 30 or n(r.get("source_product_ad_days")) != 30 for r in rows):
            continue
        clicks = sum((n(r["clicks"]) or D(0)) for r in rows)
        cost = sum((n(r["cost"]) or D(0)) for r in rows)
        orders_7d = sum((n(a["same_orders_7d"]) or D(0)) for a in attrs)
        sales_7d = sum((n(a["same_sales_7d"]) or D(0)) for a in attrs)
        all_orders_7d = sum((n(a["orders_7d"]) or D(0)) for a in attrs)
        orders_30d = sum((n(r["orders_30d"]) or D(0)) for r in rows)
        if clicks < 10 or any(n(r["clicks"]) is None or n(r["cost"]) is None or n(r["orders_30d"]) is None for r in rows):
            continue
        entity = f"term:{profile}:{campaign}:{group}:{word}"
        keyword_term = all(r["search_term_type"] == "keyword" for r in rows)
        normalized = word.casefold().strip()
        existing_exact = any(active(k) and str(k["profile_id"]) == profile and
                             str(k["keyword_text"]).casefold().strip() == normalized and
                             str(k["match_type"]).lower() == "exact" for k in keywords.values())
        existing_negative = any(active(t) and str(t["profile_id"]) == profile and
                                str(t["campaign_id"]) == campaign and
                                str(t["negative_text"]).casefold().strip() == normalized
                                for t in negatives.values())

        if keyword_term and clicks >= 49 and all_orders_7d == 0 and orders_30d == 0:
            protection = all(n(r["term_protection_complete"]) == 1 and
                             all(n(r[f]) == 0 for f in ("is_brand_term", "is_core_category_term", "is_new_product_term"))
                             for r in rows)
            if protection and not existing_negative:
                code = "100502" if clicks >= 63 else "100501"
                emit(key, "否定关键词", code, entity, profile_id=profile, campaign_id=campaign,
                     ad_group_id=group, object_text=word, negative_match_type="negativeExact",
                     clicks=clicks, orders=0, cost=cost, attribution="成熟30天观察及同MSKU 7天归因")
            elif not protection:
                emit(key, "否词待核", "", entity, blocker="品牌/核心/新品保护信息不足或命中保护")

        if not keyword_term or clicks < 10 or orders_7d < 1 or sales_7d <= 0 or cost / sales_7d > D(".3"):
            continue
        metric_rows = metrics_rows.get(key, [])
        tacos = n(metric_rows[0].get("tacos")) if len(metric_rows) == 1 else None
        if tacos is None or tacos >= D(".1") or existing_exact or existing_negative:
            continue
        source_cpc = cost / clicks
        sales_per_click = sales_7d / clicks
        initial_bid = min(source_cpc, sales_per_click * D(".2")).quantize(CENT, rounding=ROUND_HALF_UP)
        if initial_bid <= 0:
            continue
        manual_groups = {
            (str(ad["profile_id"]), str(ad["campaign_id"]), str(ad["ad_group_id"]))
            for ad in ads_by_product.get(key, [])
            if active(ad) and str(ad["profile_id"]) == profile and
            active(campaigns.get((profile, str(ad["campaign_id"])))) and
            str(campaigns[(profile, str(ad["campaign_id"]))].get("targeting_type", "")).lower() == "manual" and
            active(groups.get((profile, str(ad["ad_group_id"]))))
        }
        if len(manual_groups) != 1:
            emit(key, "新增精准词", "100503", entity, blocker="目标手动广告组不唯一或不存在",
                 object_text=word, clicks=clicks, orders=orders_7d, cost=cost, sales=sales_7d)
            continue
        target_profile, target_campaign, target_group = next(iter(manual_groups))
        future_week_clicks = clicks / 30 * min(7, 7 - date.fromisoformat(label_day).weekday())
        estimated_increment = (initial_bid * future_week_clicks).quantize(CENT, rounding=ROUND_CEILING)
        allowed, budget_reason, budget_details = budget_evidence(key, estimated_increment)
        # Source orders are evidence for potential relevance, not a semantic
        # or listing-level confirmation of the user's relevance rule.
        blocker = budget_reason if not allowed else "词与商品相关性尚未核验"
        emit(key, "新增精准词", "100503", entity, blocker=blocker,
             profile_id=target_profile, campaign_id=target_campaign, ad_group_id=target_group,
             source_campaign_id=campaign, source_ad_group_id=group,
             object_text=word, suggested_value=initial_bid, clicks=clicks, orders=orders_7d,
             cost=cost, sales=sales_7d, budget_evidence=budget_details,
             attribution="成熟30天自动来源词、同MSKU 7天归因")

    # Product-level action limit: at most one price action and two ad actions.
    priority = {"降低竞价": 0, "否定关键词": 0, "开启广告": 1, "提高竞价": 2, "新增精准词": 2}
    price_actions = [a for a in actions if a["action_type"] == "调价"]
    ad_rows = sorted((a for a in actions if a["action_type"] != "调价"),
                     key=lambda a: (priority.get(a["action_type"], 9), -(n(a.get("cost")) or D(0)), a["entity"]))
    ad_counts = Counter()
    selected_ads = []
    for row in ad_rows:
        key = (row["country"], row["store"], row["msku"])
        if ad_counts[key] < 2:
            selected_ads.append(row)
            ad_counts[key] += 1
        else:
            row["blocker"] = "同产品最多2个广告原子动作"
            row["status"] = "BLOCKED"
            blocked.append(row)
    final = price_actions + selected_ads
    counts = Counter((r["country"], r["store"], r["msku"]) for r in final)
    blocked_counts = Counter((r["country"], r["store"], r["msku"]) for r in blocked)
    for row in coverage:
        key = (row["country"], row["store"], row["msku"])
        row["action_count"] = counts[key]
        row["blocked_count"] = blocked_counts[key]
        if not counts[key] and not blocked_counts[key] and not row["reasons"]:
            row["reasons"] = ["未命中已验证的首轮动作"]

    output_manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "label_date": label_day, "source_dates": {k: v["date"] for k, v in source_manifest["sources"].items()},
        "products": len(products), "eligible_products": len(eligible),
        "products_with_actions": len(counts), "action_count": len(final),
        "action_counts": dict(Counter(r["action_type"] for r in final)),
        "blocked_count": len(blocked), "blocked_reasons": dict(Counter(r["blocker"] for r in blocked)),
        "scope": "local manual-review preview; no database or platform writes",
        "limitations": ["positive bid budget uses explicit remaining-days baseline estimate; review against platform before execution",
                        "platform bid bounds require final platform check; no empty reserved DWS bounds used as a false blocker",
                        "new exact terms require a unique destination group and product relevance confirmation",
                        "zero-spend exposure requires first-test history and valid target verification"],
    }
    for name, rows in (("final_actions", final), ("blocked_candidates", blocked),
                       ("products", coverage), ("manifest", output_manifest)):
        write_json(out / f"{name}.json", rows)
    for filename, rows in (("问题产品动作.csv", final), ("问题产品待核.csv", blocked), ("问题产品全量覆盖.csv", coverage)):
        fields = sorted(set().union(*(r.keys() for r in rows))) if rows else ["country", "store", "msku"]
        with (out / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (list, dict)) else value
                                 for field, value in row.items()})
    print(json.dumps(output_manifest, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    main()
