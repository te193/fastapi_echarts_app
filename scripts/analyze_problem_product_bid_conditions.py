"""Read-only audit of XMind bid preconditions for problem-product ad objects."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from configparser import ConfigParser
from datetime import date
from decimal import Decimal
from pathlib import Path

import pymysql


COUNTRIES = {
    "德国": "DE", "法国": "FR", "意大利": "IT", "西班牙": "ES", "荷兰": "NL",
    "英国": "UK", "美国": "US", "加拿大": "CA", "日本": "JP", "波兰": "PL",
    "瑞典": "SE", "比利时": "BE", "澳大利亚": "AU",
}


def source_connection():
    config = ConfigParser()
    config.read("config/database.ini", encoding="utf-8")
    settings = config["source"]
    return pymysql.connect(
        host=settings["host"], port=int(settings["port"]), user=settings["user"],
        password=settings["password"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=10, read_timeout=180,
    )


def pricing_connection():
    config = ConfigParser()
    config.read("config/database.ini", encoding="utf-8")
    settings = config["target"]
    return pymysql.connect(
        host=settings["host"], port=int(settings["port"]), user=settings["user"],
        password=settings["password"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=10, read_timeout=180,
    )


def key(store, country, msku):
    store = re.sub(r"-(?:eu-)?[a-z]{2}$", "", str(store or "").strip().casefold())
    country = str(country or "").strip().removesuffix("站")
    country = COUNTRIES.get(country, country.upper())
    return store, country, str(msku or "").strip().casefold()


def dec(value):
    return Decimal(str(value or 0))


def percentile(values, percent):
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * percent
    low = int(index)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * Decimal(str(index - low))


def pricing_lookups(cutoff):
    connection = pricing_connection()
    try:
        with connection.cursor() as cursor:
            listings = {}
            ladders = {}
            for table, result in (
                ("dashboard_listing_price_daily_snapshot", listings),
                ("dashboard_limit_price_daily_snapshot", ladders),
            ):
                cursor.execute(
                    f"select max(snapshot_date) as snapshot_date from etl_datasync_test.{table} where snapshot_date<=%s",
                    (cutoff,),
                )
                snapshot_date = cursor.fetchone()["snapshot_date"]
                if snapshot_date is None:
                    continue
                cursor.execute(f"select * from etl_datasync_test.{table} where snapshot_date=%s", (snapshot_date,))
                for row in cursor.fetchall():
                    stores = (row.get("seller_name_new"), row.get("seller_name")) if result is listings else (row.get("seller_name_new"),)
                    for store in stores:
                        result[key(store, row.get("country"), row.get("seller_sku"))] = row
            return listings, ladders
    finally:
        connection.close()


def margin_band(price, ladder):
    if not price or not ladder or ladder.get("margin_price_0") is None or dec(price) < dec(ladder["margin_price_0"]):
        return None
    matched = 0
    for step in (5, 10, 15, 20, 25, 30, 35):
        threshold = ladder.get(f"margin_price_{step}")
        if threshold is not None and dec(price) >= dec(threshold):
            matched = step
    return Decimal(matched) / Decimal(100)


def condition(row):
    clicks, cost, sales, orders = (dec(row[x]) for x in ("clicks", "cost", "sales", "orders"))
    current, max_bid = dec(row["current_bid"]), dec(row.get("max_bid"))
    acos = cost / sales if sales > 0 else None
    direct_cvr = dec(row["same_orders"]) / clicks if clicks > 0 else Decimal(0)
    group = row["match_group"]
    if clicks >= 50 and sales == 0 and cost >= 20 or row["impressions"] == 0 and cost > 0:
        return "pause_high_click_zero_sale"
    if cost == 0 or sales == 0 and clicks < 10 and cost < 5:
        return "keep_low_evidence"
    if max_bid > 0 and current > max_bid * Decimal("1.2") and (sales == 0 or acos is not None and acos > Decimal("0.2")):
        return "decrease_over_max_bid"
    if sales == 0:
        if clicks >= 40:
            return "decrease_zero_sale_clicks_40"
        if clicks >= 25:
            return "decrease_zero_sale_clicks_25"
        if clicks >= 15 or cost >= 15:
            return "decrease_zero_sale_clicks_15_or_cost_15"
    if acos is not None:
        for threshold, name in (("0.5", "50"), ("0.4", "40"), ("0.3", "30"), ("0.2", "20")):
            if acos > Decimal(threshold):
                return f"decrease_acos_gt_{name}"
    if sales > 0 and acos is not None and acos <= Decimal("0.2"):
        tiers = {
            "exact_phrase": (("0.1", "0.18", 50), ("0.15", "0.15", 35), ("0.2", "0.12", 20), ("0.2", "0.12", 2)),
            "broad_close_complements": (("0.1", "0.18", 50), ("0.15", "0.15", 35), ("0.2", "0.12", 3)),
            "loose_substitutes_unknown": (("0.15", "0.15", 30), ("0.2", "0.12", 15)),
        }
        for index, (acos_limit, cvr_limit, click_limit) in enumerate(tiers[group], 1):
            if acos <= Decimal(acos_limit) and direct_cvr >= Decimal(cvr_limit) and clicks >= click_limit:
                return f"increase_{group}_{index}"
        return "keep_profitable_below_increase_threshold"
    return "observe_no_condition"


def match_group(match_type, target_text):
    match_type = str(match_type or "").upper()
    target_text = str(target_text or "").lower()
    if match_type in {"EXACT", "PHRASE"}:
        return "exact_phrase"
    if match_type == "BROAD" or "queryhighrelmatches" in target_text or "asincomplement" in target_text:
        return "broad_close_complements"
    return "loose_substitutes_unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs/问题产品广告竞价条件分析")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    connection = source_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                select h.country,h.store,h.msku,h.rule_code,p.tag_name
                from dws_datasync.`dws_产品策略命中结果表` h
                join dws_datasync.`dws_产品策略建议表` p on p.rule_code=h.rule_code
                where h.data_date='2026-09-13' and h.rule_code in (1024,1025,1028)
                limit 1000
            """)
            candidates = {key(x["store"], x["country"], x["msku"]): x for x in cursor.fetchall()}
            cursor.execute("""
                select profile_id,campaign_id,ad_group_id,target_id,target_text,match_type,
                       seller_name,country_code,currency_code,msku,msku_mapping_status,
                       associated_msku_count,campaign_state_current,ad_group_state_current,
                       target_state_current,default_bid_current,impressions,clicks,cost,
                       orders_7d,sales_7d,same_orders_7d
                from dws_datasync.dws_sp_search_term_analysis_daily
                where snapshot_date='2026-09-13' and msku is not null
                limit 200000
            """)
            object_rows = {}
            for source in cursor.fetchall():
                candidate = candidates.get(key(source["seller_name"], source["country_code"], source["msku"]))
                if candidate is None:
                    continue
                object_key = (source["profile_id"], source["campaign_id"], source["ad_group_id"], source["target_id"])
                row = object_rows.setdefault(object_key, {
                    "profile_id": source["profile_id"], "campaign_id": source["campaign_id"],
                    "ad_group_id": source["ad_group_id"], "target_id": source["target_id"],
                    "country": candidate["country"], "store": candidate["store"], "msku": candidate["msku"],
                    "rule_code": candidate["rule_code"], "tag_name": candidate["tag_name"],
                    "country_code": source["country_code"], "currency_code": source["currency_code"],
                    "target_text": source["target_text"], "match_type": source["match_type"],
                    "match_group": match_group(source["match_type"], source["target_text"]),
                    "mapping_status": source["msku_mapping_status"],
                    "associated_msku_count": source["associated_msku_count"],
                    "campaign_state": source["campaign_state_current"],
                    "ad_group_state": source["ad_group_state_current"],
                    "target_state": source["target_state_current"],
                    "default_bid": source["default_bid_current"],
                    "impressions": 0, "clicks": 0, "cost": Decimal(0), "orders": 0,
                    "sales": Decimal(0), "same_orders": 0,
                })
                row["impressions"] += int(source["impressions"] or 0)
                row["clicks"] += int(source["clicks"] or 0)
                row["cost"] += dec(source["cost"])
                row["orders"] += int(source["orders_7d"] or 0)
                row["sales"] += dec(source["sales_7d"])
                row["same_orders"] += int(source["same_orders_7d"] or 0)

            ids = sorted({row["target_id"] for row in object_rows.values() if row["target_id"] is not None})
            bids = {}
            for table, id_col in (("lx_advertising_sp_keywords", "keyword_id"), ("lx_advertising_sp_targets", "target_id")):
                for start in range(0, len(ids), 500):
                    chunk = ids[start:start + 500]
                    cursor.execute(
                        f"select profile_id,ad_group_id,{id_col} as object_id,bid,state "
                        f"from ods_datasync.{table} where {id_col} in ({','.join(['%s'] * len(chunk))}) "
                        "and coalesce(delete_flag,0)=0 limit 1000", chunk,
                    )
                    for item in cursor.fetchall():
                        bids[(item["profile_id"], item["ad_group_id"], item["object_id"])] = item

            # Historical trend: two nonoverlapping 30-day windows, mature through 2026-09-06.
            history = {}
            if ids:
                cursor.execute(
                    f"""select profile_id,campaign_id,ad_group_id,target_id,
                        case when report_date between '2026-08-08' and '2026-09-06' then 'current' else 'previous' end as period,
                        sum(impressions) as impressions,sum(clicks) as clicks,sum(cost) as cost,sum(orders_7d) as orders,sum(sales_7d) as sales,
                        sum(same_orders_7d) as same_orders
                    from ods_datasync.lx_advertising_sp_query_word_reports
                    where report_date between '2026-07-09' and '2026-09-06'
                      and coalesce(delete_flag,0)=0
                      and target_id in ({','.join(['%s'] * len(ids))})
                    group by profile_id,campaign_id,ad_group_id,target_id,period
                    limit 100000""", ids,
                )
                history = {
                    (x["profile_id"], x["campaign_id"], x["ad_group_id"], x["target_id"], x["period"]): x
                    for x in cursor.fetchall()
                }
    finally:
        connection.close()

    listings, ladders = pricing_lookups(date(2026, 9, 13))
    final_rows = []
    for object_key, row in object_rows.items():
        bid = bids.get((row["profile_id"], row["ad_group_id"], row["target_id"]))
        row["current_bid"] = bid["bid"] if bid and bid["bid"] is not None else row["default_bid"]
        row["bid_source"] = "object" if bid and bid["bid"] is not None else "ad_group_default"
        row["object_state"] = bid["state"] if bid else row["target_state"]
        current = history.get((*object_key, "current"), {})
        row["metrics_source"] = "ods_query_word_reports" if current else "missing_ods_report"
        for metric in ("impressions", "clicks", "cost", "orders", "sales", "same_orders"):
            row[metric] = current.get(metric) or 0
        previous = history.get((*object_key, "previous"), {})
        row["previous_clicks"] = previous.get("clicks") or 0
        row["previous_orders"] = previous.get("orders") or 0
        row["previous_same_orders"] = previous.get("same_orders") or 0
        row["previous_sales"] = previous.get("sales") or 0
        row["previous_cost"] = previous.get("cost") or 0
        pricing_key = key(row["store"], row["country"], row["msku"])
        listing, ladder = listings.get(pricing_key), ladders.get(pricing_key)
        row["listing_price"] = listing.get("price") if listing else None
        row["margin_band"] = margin_band(row["listing_price"], ladder)
        total_orders = dec(row["orders"]) + dec(row["previous_orders"])
        total_sales = dec(row["sales"]) + dec(row["previous_sales"])
        total_clicks = dec(row["clicks"]) + dec(row["previous_clicks"])
        row["aov_60d"] = total_sales / total_orders if total_orders else None
        row["cvr_60d"] = (dec(row["same_orders"]) + dec(previous.get("same_orders"))) / total_clicks if total_clicks else None
        row["max_bid"] = (
            row["aov_60d"] * row["cvr_60d"] * row["margin_band"]
            if row["aov_60d"] is not None and row["cvr_60d"] is not None and row["margin_band"] is not None else None
        )
        row["condition"] = condition(row)
        row["acos"] = row["cost"] / row["sales"] if row["sales"] else None
        row["direct_cvr"] = Decimal(row["same_orders"]) / Decimal(row["clicks"]) if row["clicks"] else None
        row["eligible_for_bid"] = (
            row["mapping_status"] == "mapped" and row["associated_msku_count"] == 1
            and str(row["campaign_state"]).lower() == "enabled"
            and str(row["ad_group_state"]).lower() == "enabled"
            and str(row["object_state"]).lower() == "enabled"
            and row["current_bid"] is not None and dec(row["current_bid"]) > 0
        )
        final_rows.append(row)

    conditions = defaultdict(list)
    for row in final_rows:
        conditions[row["condition"]].append(row)
    matched_products = {key(row["store"], row["country"], row["msku"]) for row in final_rows}
    with (output / "问题产品范围.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["country", "store", "msku", "rule_code", "tag_name", "matched_ad_object"])
        writer.writeheader()
        for product_key, candidate in sorted(candidates.items()):
            writer.writerow({
                "country": candidate["country"], "store": candidate["store"], "msku": candidate["msku"],
                "rule_code": candidate["rule_code"], "tag_name": candidate["tag_name"],
                "matched_ad_object": product_key in matched_products,
            })
    summary = []
    for name, rows in sorted(conditions.items()):
        eligible = [row for row in rows if row["eligible_for_bid"]]
        summary.append({
            "condition": name, "objects": len(rows), "eligible_objects": len(eligible),
            "products": len({(row["country"], row["store"], row["msku"]) for row in rows}),
            "clicks": sum(row["clicks"] for row in eligible),
            "cost": sum((row["cost"] for row in eligible), Decimal(0)),
            "sales": sum((row["sales"] for row in eligible), Decimal(0)),
            "current_bid_p25": percentile([dec(row["current_bid"]) for row in eligible], Decimal("0.25")),
            "current_bid_p50": percentile([dec(row["current_bid"]) for row in eligible], Decimal("0.5")),
            "current_bid_p75": percentile([dec(row["current_bid"]) for row in eligible], Decimal("0.75")),
            "previous_orders": sum(int(row["previous_orders"]) for row in eligible),
            "previous_sales": sum((dec(row["previous_sales"]) for row in eligible), Decimal(0)),
        })

    detail_fields = [
        "condition", "eligible_for_bid", "country", "store", "msku", "rule_code", "tag_name",
        "profile_id", "campaign_id", "ad_group_id", "target_id", "target_text", "match_type",
        "match_group", "mapping_status", "campaign_state", "ad_group_state", "object_state",
        "currency_code", "current_bid", "bid_source", "metrics_source", "listing_price", "margin_band",
        "aov_60d", "cvr_60d", "max_bid", "impressions", "clicks", "cost", "orders",
        "sales", "same_orders", "acos", "direct_cvr", "previous_clicks", "previous_orders", "previous_same_orders",
        "previous_sales", "previous_cost",
    ]
    with (output / "对象条件明细.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in detail_fields} for row in final_rows)
    with (output / "条件汇总.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(summary[0]) if summary else ["condition"])
        writer.writeheader()
        writer.writerows(summary)
    print(json.dumps({"candidate_products": len(candidates), "objects": len(final_rows), "conditions": summary}, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
