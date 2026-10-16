"""Read-only export of the provisional seven-country problem-product decision base."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

import pymysql

from scripts.problem_product_ad_rules import build_ad_action, resolve_product_actions


COUNTRIES = ("德国", "法国", "意大利", "西班牙", "荷兰", "英国", "美国")
COUNTRY_CODES = {"德国": "DE", "法国": "FR", "意大利": "IT", "西班牙": "ES", "荷兰": "NL", "英国": "UK", "美国": "US"}
OUTPUT = Path(__file__).resolve().parents[1] / "outputs" / "01a08f9c-f540-7580-8637-c21961e3c79c" / "problem_product_decision_base.json"


def number(value):
    return None if value is None else float(value)


def as_snapshot_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def latest_date_on_or_before(available_dates, target_date):
    """Return the newest available snapshot no later than target_date."""
    normalized = []
    for value in available_dates:
        if value is None:
            continue
        value = as_snapshot_date(value)
        if value <= target_date:
            normalized.append(value)
    return max(normalized) if normalized else None


def money_up(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_CEILING))


def key(country, store, msku):
    return (str(country or "").strip(), str(store or "").strip(), str(msku or "").strip())


def fetch(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


def cohort(cur, snapshot_date):
    sql = """
    select distinct b.country,b.store,b.msku
    from dws_datasync.dws_标签表汇总 b
    where b.data_date=%s and b.label_id=1304 and b.label_period='30d'
      and b.country in ('德国','法国','意大利','西班牙','荷兰','英国','美国')
      and exists (
        select 1 from dws_datasync.dws_标签表汇总 a
        where a.data_date=b.data_date and a.label_id=301 and a.label_period='current'
          and a.store=b.store and a.msku=b.msku
      )
    """
    return {key(r["country"], r["store"], r["msku"]) for r in fetch(cur, sql, (snapshot_date,))}


def indexed(rows, columns):
    result = {}
    duplicates = []
    for row in rows:
        item_key = key(*(row[c] for c in columns))
        if item_key in result:
            duplicates.append(item_key)
        result[item_key] = row
    return result, duplicates


def price_proposal(price):
    if not price:
        return None, "定价缺失"
    current = number(price["listing_price"])
    p25 = number(price["p25"])
    p10 = number(price.get("p10"))
    if current is None or p25 is None or p10 is None or current <= 0 or p10 <= 0 or p25 < p10:
        return None, "价格线缺失或异常"
    if current > p25:
        proposed = money_up(p25)
        reason = "直接降至25%毛利润价格"
    elif current > p10:
        proposed = money_up(max(current * 0.95, p10))
        reason = "本轮最多降价5%"
    else:
        return current, "已达10%底线，不自动降价"
    if proposed >= current or proposed < p10:
        return current, "取整后无有效降价空间"
    return proposed, reason


def main():
    connection = pymysql.connect(
        host=os.environ["OPT_LYT_DB_HOST"],
        port=int(os.environ.get("OPT_LYT_DB_PORT", "3306")),
        user=os.environ["OPT_LYT_DB_USER"],
        password=os.environ["OPT_LYT_DB_PASSWORD"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        read_timeout=120,
        write_timeout=120,
        autocommit=False,
    )
    try:
        with connection.cursor() as cur:
            label_date = as_snapshot_date(fetch(cur, "select max(data_date) as dt from dws_datasync.dws_标签表汇总")[0]["dt"])
            price_date = as_snapshot_date(fetch(cur, "select max(`数据日期`) as dt from temporary_dwd.`在库节点_输出定价表`")[0]["dt"])
            budget_date = as_snapshot_date(fetch(cur, "select max(biz_date) as dt from dws_datasync.dws_monthly_ad_budget_detail")[0]["dt"])
            metric_date = as_snapshot_date(fetch(cur, "select max(data_date) as dt from dws_datasync.ops_product_site_metric_period where data_date <= %s", (label_date,))[0]["dt"])
            ad_report_date = as_snapshot_date(fetch(cur, "select max(report_date) as dt from dwd_datasync.lx_advertising_sp_product_ad_reports where report_date <= %s", (price_date,))[0]["dt"])
            bid_snapshot_date = as_snapshot_date(fetch(cur, "select max(snapshot_date) as dt from dws_datasync.dws_sp_bid_object_snapshot_daily")[0]["dt"])
            term_snapshot_date = as_snapshot_date(fetch(cur, "select max(snapshot_date) as dt from dws_datasync.dws_sp_search_term_analysis_daily")[0]["dt"])
            if not all((label_date, price_date, budget_date, metric_date, ad_report_date)):
                raise RuntimeError("关键源表缺少最新快照日期，不能生成当期决策底表")
            current_keys = cohort(cur, label_date)
            month_start = ad_report_date.replace(day=1)
            price_rows = fetch(cur, """
              select `国家` country,`国家代码` country_code,`新店铺` store,`店铺名` full_store,
                     msku,`币种` currency_code,`listing价格` listing_price,
                     `25毛利润价格` p25,`10毛利润价格` p10,`数据异常备注` data_warning
              from temporary_dwd.`在库节点_输出定价表`
              where `数据日期`=%s and `国家` in ('德国','法国','意大利','西班牙','荷兰','英国','美国')
            """, (price_date,))
            prices, price_dupes = indexed(price_rows, ("country", "store", "msku"))
            metric_rows = fetch(cur, """
              select country,store,msku,sales_volume,settlement_sales_amount,
                     settlement_gross_profit,settlement_gross_margin,ad_spend,ad_sales,
                     acos,tacos,fba_available_inventory,fba_inbound_inventory,
                     last_zero_inventory_date,inventory_snapshot_time
              from dws_datasync.ops_product_site_metric_period
              where data_date=%s and period_days=30
                and country in ('德国','法国','意大利','西班牙','荷兰','英国','美国')
            """, (metric_date,))
            metrics, metric_dupes = indexed(metric_rows, ("country", "store", "msku"))
            budget_rows = fetch(cur, """
              select country,seller_name_new store,seller_sku_adj msku,
                     monthly_ad_budget_cny,weekly_ad_budget_cny,exchange_rate_cny,
                     currency_code,monthly_ad_budget_original,weekly_ad_budget_original,
                     inventory_sufficient_flag,weekly_inventory_sufficient_flag
              from dws_datasync.dws_monthly_ad_budget_detail
              where biz_date=%s and country in ('德国','法国','意大利','西班牙','荷兰','英国','美国')
            """, (budget_date,))
            budgets, budget_dupes = indexed(budget_rows, ("country", "store", "msku"))
            month_spend_rows = fetch(cur, """
              select seller_name,sku msku,sum(cost) spend_original
              from dwd_datasync.lx_advertising_sp_product_ad_reports
              where report_date between %s and %s
              group by seller_name,sku
            """, (month_start, ad_report_date))
            month_spend = {(str(r["seller_name"] or "").strip(), str(r["msku"] or "").strip()): number(r["spend_original"]) for r in month_spend_rows}
            bid_rows = fetch(cur, """
              select s.country_code,s.base_store_name,s.seller_name,s.msku,s.profile_id,
                     s.campaign_id,s.ad_group_id,s.targeting_type,s.object_type,s.object_id,s.object_text,
                     s.match_type,s.msku_mapping_status,s.associated_msku_count,
                     s.clicks,s.cost,s.same_sku_attributed_orders_30d,s.same_sku_attributed_sales_30d,
                     s.cvr,s.acos,s.current_bid,s.mature_start,s.mature_end,
                     s.campaign_state_current,s.campaign_serving_status,s.monthly_budget_status,
                     s.weekly_budget_status,s.budget_support_status
              from dws_datasync.dws_sp_bid_object_snapshot_daily s
              where s.snapshot_date=%s
                and upper(s.country_code) in ('DE','FR','IT','ES','NL','UK','US')
                and s.msku is not null
            """, (bid_snapshot_date,)) if bid_snapshot_date else []
            term_rows = fetch(cur, """
              select country_code,seller_name,msku,campaign_id,ad_group_id,target_id,
                     search_term,search_term_type,match_type,is_auto_campaign,is_manual_campaign,
                     existing_object_state,clicks,cost,cpc,orders_30d,same_orders_30d,same_sales_30d,
                     acos_30d,is_add_recommended,is_negative_recommended,needs_manual_review,
                     is_brand_term,is_core_category_term,is_new_product_term,term_protection_complete,mature_end
              from dws_datasync.dws_sp_search_term_analysis_daily
              where snapshot_date=%s
                and upper(country_code) in ('DE','FR','IT','ES','NL','UK','US')
                and (clicks>=10 or is_add_recommended=1 or is_negative_recommended=1)
            """, (term_snapshot_date,)) if term_snapshot_date else []
    finally:
        connection.close()

    records = []
    full_store_keys = {}
    for item_key in sorted(current_keys):
        country, store, msku = item_key
        p, m, b = prices.get(item_key), metrics.get(item_key), budgets.get(item_key)
        full_store = str(p["full_store"]).strip() if p and p.get("full_store") else None
        if full_store:
            full_store_keys[(COUNTRY_CODES[country], full_store, msku)] = item_key
        proposed_price, price_reason = price_proposal(p)
        stock = number(m["fba_available_inventory"]) if m else None
        month_budget = number(b["monthly_ad_budget_cny"]) if b else None
        week_budget = number(b["weekly_ad_budget_cny"]) if b else None
        fx = number(b["exchange_rate_cny"]) if b else None
        spend_original = month_spend.get((full_store, msku)) if full_store else None
        month_spend_cny = round(spend_original * fx, 2) if spend_original is not None and fx and fx > 0 else None
        month_balance = round(max(0, month_budget - month_spend_cny), 2) if month_budget is not None and month_spend_cny is not None else None
        # Current week starts on 2026-09-14; the report is only complete through 09-13.
        gross_test_cap = round(min(month_balance, week_budget, month_budget * 0.10, week_budget * 0.25), 2) if month_balance is not None and week_budget is not None and month_budget and month_budget > 0 and week_budget > 0 else None
        actual_margin = number(m["settlement_gross_margin"]) if m else None
        issues = []
        if not p:
            issues.append("定价缺失")
        if not m:
            issues.append("经营指标缺失")
        if stock is None:
            issues.append("站点库存缺失")
        elif stock <= 0:
            issues.append("站点FBA可售为零")
        if not b:
            issues.append("预算配置缺失")
        elif month_budget is None or month_budget <= 0 or week_budget is None or week_budget <= 0:
            issues.append("月或周预算不可增")
        if b and month_spend_cny is None:
            issues.append("月广告花费无法匹配")
        if p and p.get("data_warning"):
            issues.append("定价数据异常备注")
        if actual_margin is not None and actual_margin < 0.05 and m and number(m["settlement_sales_amount"]) and number(m["settlement_sales_amount"]) > 0:
            issues.append("现状结算毛利低于5%（问题产品标签证据，非首轮动作拦截）")
        records.append({
            "country": country,"country_code": COUNTRY_CODES[country],"store": store,"full_store": full_store,"msku": msku,
            "role_source_table": "dws_datasync.dws_标签表汇总",
            "sample_version": f"标签{label_date}｜定价{price_date}","execution_status": "MANUAL_REVIEW",
            "sales_30d": number(m["sales_volume"]) if m else None,"ad_spend_30d": number(m["ad_spend"]) if m else None,"fba_available": stock,
            "fba_inbound": number(m["fba_inbound_inventory"]) if m else None,
            "listing_price": number(p["listing_price"]) if p else None,"p25": number(p["p25"]) if p else None,
            "p10": number(p["p10"]) if p else None,"currency_code": p.get("currency_code") if p else None,
            "proposed_price": proposed_price,"price_reason": price_reason,
            "settlement_margin_30d": actual_margin,"product_tacos_30d": number(m["tacos"]) if m else None,
            "monthly_budget_cny": month_budget,"weekly_budget_cny": week_budget,
            "inventory_status": "库存充足" if b and b.get("inventory_sufficient_flag") else "库存不足或待核",
            "mtd_spend_cny": month_spend_cny,"monthly_balance_upper_cny": month_balance,
            "test_budget_upper_cny_unreserved": gross_test_cap,
            "issues": "、".join(issues),
            "bid_object_count": 0,"term_candidate_count": 0,"ad_spend_status": "待判断","ad_actions": [],
        })
    by_key = {key(r["country"], r["store"], r["msku"]): r for r in records}
    ad_objects = []
    ad_candidates = defaultdict(list)
    ad_dedup = set()
    for s in bid_rows:
        item_key = key(next((c for c, code in COUNTRY_CODES.items() if code == str(s["country_code"]).upper()), ""), s["base_store_name"], s["msku"])
        if item_key not in by_key or str(s.get("msku_mapping_status") or "").lower() != "mapped":
            continue
        identity = (item_key, s["object_type"], s["profile_id"], s["object_id"])
        if identity in ad_dedup:
            continue
        ad_dedup.add(identity)
        product = by_key[item_key]
        product["bid_object_count"] += 1
        is_auto = str(s.get("targeting_type") or "").lower() == "auto"
        is_manual_keyword = not is_auto and str(s.get("object_type") or "").lower() == "keyword"
        path = "auto_bid" if is_auto else "manual_keyword" if is_manual_keyword else ""
        decision = build_ad_action({
            "path": path,
            "object_id": str(s["object_id"]),
            "object_text": s["object_text"],
            "current_bid": number(s["current_bid"]),
            "clicks": number(s["clicks"]),
            "cost": number(s["cost"]),
            "orders": number(s["same_sku_attributed_orders_30d"]),
            "sales": number(s["same_sku_attributed_sales_30d"]),
            "acos": number(s["acos"]),
            "cvr": number(s["cvr"]),
            "tacos": product["product_tacos_30d"],
            "budget_status": s["budget_support_status"] or s["monthly_budget_status"] or s["weekly_budget_status"],
        }) if path else build_ad_action({"path": ""})
        if path:
            ad_candidates[item_key].append(decision)
        if path and product["ad_spend_30d"] == 0 and str(s.get("campaign_state_current") or "").upper() == "ENABLED":
            ad_candidates[item_key].append(build_ad_action({
                "path": "zero_spend_exposure",
                "object_id": str(s["object_id"]),"object_text": s["object_text"],
                "current_bid": number(s["current_bid"]),
                "budget_status": s["budget_support_status"] or s["monthly_budget_status"] or s["weekly_budget_status"],
                "inventory_status": product["inventory_status"],
            }))
        ad_objects.append({
            "country": item_key[0],"store": item_key[1],"msku": item_key[2],
            "profile_id": str(s["profile_id"]),"campaign_id": str(s["campaign_id"]),
            "ad_group_id": str(s["ad_group_id"]),"object_type": s["object_type"],
            "object_id": str(s["object_id"]),"object_text": s["object_text"],"match_type": s["match_type"],
            "targeting_type": s["targeting_type"],"current_bid": number(s["current_bid"]),
            "campaign_state": s["campaign_state_current"],
            "mature_30d_clicks": number(s["clicks"]),"mature_30d_cost": number(s["cost"]),
            "mature_30d_same_orders": number(s["same_sku_attributed_orders_30d"]),
            "mature_30d_same_sales": number(s["same_sku_attributed_sales_30d"]),
            "mature_30d_acos": number(s["acos"]),"mature_30d_cvr": number(s["cvr"]),
            "mature_end": str(s["mature_end"]) if s["mature_end"] else None,
            "ad_path": path or "不在本轮自动/手动关键词规则范围","decision": decision,
        })
    terms = []
    term_dedup = set()
    for s in term_rows:
        code = str(s["country_code"] or "").upper()
        item_key = full_store_keys.get((code, str(s["seller_name"] or "").strip(), str(s["msku"] or "").strip()))
        if not item_key:
            continue
        identity = (item_key, s["campaign_id"], s["ad_group_id"], s["target_id"], s["search_term"])
        if identity in term_dedup:
            continue
        term_dedup.add(identity)
        product = by_key[item_key]
        product["term_candidate_count"] += 1
        common = {
            "search_term": s["search_term"],"search_term_type": s["search_term_type"],
            "clicks": number(s["clicks"]),"cost": number(s["cost"]),
            "orders": number(s["same_orders_30d"]),"sales": number(s["same_sales_30d"]),
            "acos": number(s["acos_30d"]),"source_cpc": number(s["cpc"]),
            "tacos": product["product_tacos_30d"],
            "budget_status": "预算充足" if product["test_budget_upper_cny_unreserved"] and product["test_budget_upper_cny_unreserved"] > 0 else "预算受限",
            "is_auto_campaign": bool(s["is_auto_campaign"]),
            "term_protection_complete": bool(s["term_protection_complete"]),
            "is_brand_term": bool(s["is_brand_term"]),"is_core_category_term": bool(s["is_core_category_term"]),
            "is_new_product_term": bool(s["is_new_product_term"]),
            "has_manual_exact": bool(s["existing_object_state"]),
        }
        decisions = []
        if common["is_auto_campaign"]:
            decisions = [build_ad_action({**common, "path": "auto_to_exact"}), build_ad_action({**common, "path": "auto_negative"})]
            ad_candidates[item_key].extend(decisions)
        terms.append({
            "country": item_key[0],"store": item_key[1],"msku": item_key[2],
            "campaign_id": str(s["campaign_id"]),"ad_group_id": str(s["ad_group_id"]),
            "target_id": str(s["target_id"]),"search_term": s["search_term"],
            "search_term_type": s["search_term_type"],"clicks": number(s["clicks"]),
            "cost": number(s["cost"]),"total_orders_30d": number(s["orders_30d"]),
            "same_orders_30d": number(s["same_orders_30d"]),
            "same_sales_30d": number(s["same_sales_30d"]),"acos_30d": number(s["acos_30d"]),
            "source_add_flag": int(s["is_add_recommended"] or 0),
            "source_negative_flag": int(s["is_negative_recommended"] or 0),
            "protected_or_manual": bool(s["needs_manual_review"] or s["is_brand_term"] or s["is_core_category_term"] or s["is_new_product_term"] or not s["term_protection_complete"]),
            "mature_end": str(s["mature_end"]) if s["mature_end"] else None,
            "ad_path": "自动搜索词→手动精准/否词" if common["is_auto_campaign"] else "非自动来源，仅保留观察",
            "decisions": decisions,
        })
    for item_key, product in by_key.items():
        if product["ad_spend_30d"] is None:
            product["ad_spend_status"] = "广告花费数据缺失"
        elif product["ad_spend_30d"] > 0:
            product["ad_spend_status"] = "有广告花费"
        elif product["bid_object_count"] == 0:
            product["ad_spend_status"] = "广告未开启"
        else:
            product["ad_spend_status"] = "广告已开启但无花费"
        product["ad_actions"] = resolve_product_actions(ad_candidates[item_key])
    diff = []
    summary = {
        "label_date": str(label_date),"price_date": str(price_date),"budget_date": str(budget_date),
        "metric_date": str(metric_date),"ad_report_date": str(ad_report_date),
        "bid_snapshot_date": str(bid_snapshot_date) if bid_snapshot_date else None,
        "term_snapshot_date": str(term_snapshot_date) if term_snapshot_date else None,
        "role_source_table": "dws_datasync.dws_标签表汇总","cohort_count": len(current_keys),
        "price_matched": sum(r["listing_price"] is not None for r in records),
        "metric_matched": sum(key(r["country"],r["store"],r["msku"]) in metrics for r in records),
        "budget_matched": sum(key(r["country"],r["store"],r["msku"]) in budgets for r in records),
        "month_spend_matched": sum(r["mtd_spend_cny"] is not None for r in records),
        "price_reduction_candidates": sum(r["proposed_price"] is not None and r["listing_price"] is not None and r["proposed_price"] < r["listing_price"] for r in records),
        "fba_zero": sum(r["fba_available"] is not None and r["fba_available"] <= 0 for r in records),
        "ad_objects": len(ad_objects),"search_terms": len(terms),
        "price_duplicate_keys": len(price_dupes),"metric_duplicate_keys": len(metric_dupes),"budget_duplicate_keys": len(budget_dupes),
        "by_country": dict(Counter(r["country_code"] for r in records)),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"summary": summary,"rows": records,"ad_objects": ad_objects,"terms": terms,"cohort_diff": diff}, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT),"summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
