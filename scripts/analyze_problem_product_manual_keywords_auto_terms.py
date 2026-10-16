"""Calibrate problem-product ad rules from ODS advertising source tables only."""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pymysql


OUTPUT = Path(__file__).resolve().parents[1] / "outputs" / "问题产品手动关键词与自动搜索词策略分析" / "ODS校准结果.json"
COUNTRY_CODES = {
    "美国": "US", "加拿大": "CA", "墨西哥": "MX", "巴西": "BR", "英国": "UK",
    "德国": "DE", "法国": "FR", "意大利": "IT", "西班牙": "ES", "荷兰": "NL",
    "瑞典": "SE", "波兰": "PL", "比利时": "BE", "爱尔兰": "IE", "土耳其": "TR",
}


def number(value: Any) -> float:
    return float(value or 0)


def normalize_store(value: Any, country_code: Any) -> str:
    text = str(value or "").strip().casefold()
    code = str(country_code or "").strip().casefold()
    for suffix in (f"-eu-{code}", f"-{code}") if code else ():
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return re.sub(r"-(?:eu-)?[a-z]{2}$", "", text)


def normalize_term(value: Any) -> str:
    text = str(value or "").strip().casefold().replace("_", " ")
    return " ".join(re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).split())


def cohort_key(country_code: Any, store: Any, msku: Any) -> tuple[str, str, str]:
    code = str(country_code or "").strip().upper()
    return code, normalize_store(store, code), str(msku or "").strip().casefold()


def percentile(values: list[float], fraction: float) -> float | None:
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (index - low)


def percentiles(values: list[float]) -> dict[str, float | None]:
    return {name: percentile(values, value) for name, value in (("p25", .25), ("p50", .5), ("p75", .75))}


def zero_order_click_threshold(cvr: float, probability: float) -> int | None:
    if cvr <= 0 or cvr >= 1:
        return None
    return math.ceil(math.log(probability) / math.log(1 - cvr))


def fetch(cursor, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor.execute(sql, args)
    return list(cursor.fetchall())


def manual_action(row: dict[str, Any]) -> str:
    clicks, orders = number(row["clicks"]), number(row["orders"])
    cost, sales = number(row["cost"]), number(row["sales"])
    acos = cost / sales if sales > 0 else None
    cvr = orders / clicks if clicks > 0 else None
    if orders == 0:
        return "decrease_20" if clicks >= 63 else "decrease_10" if clicks >= 34 else "observe"
    if orders == 1:
        weak = (acos is not None and acos > .50) or (cvr is not None and cvr < .03)
        return "decrease_10" if clicks >= 63 and weak else "decrease_5" if clicks >= 34 and weak else "keep"
    if clicks >= 20 and acos is not None and acos > .65:
        return "decrease_20"
    if clicks >= 20 and acos is not None and acos > .50:
        return "decrease_10"
    if clicks >= 20 and acos is not None and .40 < acos <= .50 and cvr is not None and cvr < .03:
        return "decrease_5"
    if clicks >= 80 and orders >= 5 and acos is not None and acos <= .20 and cvr is not None and cvr >= .07:
        return "increase_15"
    if clicks >= 40 and orders >= 3 and acos is not None and acos <= .30 and cvr is not None and cvr >= .07:
        return "increase_10"
    if clicks >= 15 and orders >= 2 and acos is not None and acos <= .40 and cvr is not None and cvr >= .05:
        return "increase_5"
    return "keep"


def main() -> None:
    connection = pymysql.connect(
        host=os.environ["OPT_LYT_DB_HOST"], port=int(os.environ.get("OPT_LYT_DB_PORT", "3306")),
        user=os.environ["OPT_LYT_DB_USER"], password=os.environ["OPT_LYT_DB_PASSWORD"],
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, read_timeout=240, autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            label_date = fetch(cursor, "select max(data_date) dt from dws_datasync.dws_标签表")[0]["dt"]
            source_end = fetch(cursor, """
                select least(
                    (select max(report_date) from ods_datasync.lx_advertising_sp_keyword_reports),
                    (select max(report_date) from ods_datasync.lx_advertising_sp_query_word_reports),
                    (select max(report_date) from ods_datasync.lx_advertising_sp_product_ad_reports)
                ) dt
            """)[0]["dt"]
            if isinstance(source_end, str):
                source_end = datetime.strptime(source_end, "%Y-%m-%d").date()
            mature_end = source_end - timedelta(days=7)
            mature_start = mature_end - timedelta(days=29)
            previous_end = mature_start - timedelta(days=1)
            previous_start = previous_end - timedelta(days=29)

            cohort_rows = fetch(cursor, """
                select distinct p.country, p.country_category, p.store, p.msku
                from dws_datasync.dws_标签表 p
                where p.data_date = %s and p.label_id = 1304 and p.label_period = '30d'
                  and exists (
                      select 1 from dws_datasync.dws_标签表 s
                      where s.data_date = p.data_date and s.country_category = p.country_category
                        and s.store = p.store and s.msku = p.msku and s.country is null
                        and s.label_id = 301 and s.label_period = 'current'
                  )
            """, (label_date,))
            print(f"cohort_rows={len(cohort_rows)}", flush=True)

            mapping_cte = """
                with account as (
                    select cast(profile_id as unsigned) profile_id, max(country_code) country_code,
                           max(currency_code) currency_code
                    from ods_datasync.lx_advertising_account_list
                    where coalesce(delete_flag, 0) = 0 and status = 1
                    group by cast(profile_id as unsigned)
                ), current_product as (
                    select profile_id, ad_group_id,
                           count(distinct case when state = 'enabled' then lower(sku) end) current_msku_count,
                           min(case when state = 'enabled' then sku end) current_msku,
                           max(seller_name) seller_name
                    from ods_datasync.lx_advertising_sp_product_ads
                    where coalesce(delete_flag, 0) = 0
                    group by profile_id, ad_group_id
                ), period_product as (
                    select profile_id, ad_group_id, count(distinct lower(sku)) period_msku_count,
                           min(sku) period_msku
                    from ods_datasync.lx_advertising_sp_product_ad_reports
                    where coalesce(delete_flag, 0) = 0 and report_date between %s and %s
                    group by profile_id, ad_group_id
                ), safe_map as (
                    select c.profile_id, c.ad_group_id, c.seller_name, c.current_msku msku,
                           a.country_code, a.currency_code, c.current_msku_count,
                           coalesce(p.period_msku_count, 0) period_msku_count,
                           case when c.current_msku_count = 1 and p.period_msku_count = 1
                                  and lower(c.current_msku) = lower(p.period_msku)
                                then 1 else 0 end mapping_safe
                    from current_product c
                    left join period_product p on p.profile_id = c.profile_id and p.ad_group_id = c.ad_group_id
                    left join account a on a.profile_id = c.profile_id
                ), problem as (
                    select distinct
                           case p.country
                               when '美国' then 'US' when '加拿大' then 'CA' when '墨西哥' then 'MX'
                               when '巴西' then 'BR' when '英国' then 'UK' when '德国' then 'DE'
                               when '法国' then 'FR' when '意大利' then 'IT' when '西班牙' then 'ES'
                               when '荷兰' then 'NL' when '瑞典' then 'SE' when '波兰' then 'PL'
                               when '比利时' then 'BE' when '爱尔兰' then 'IE' when '土耳其' then 'TR'
                           end country_code,
                           lower(p.store) store_key, lower(p.msku) msku_key
                    from dws_datasync.dws_标签表 p
                    where p.data_date = %s and p.label_id = 1304 and p.label_period = '30d'
                      and exists (
                          select 1 from dws_datasync.dws_标签表 s
                          where s.data_date = p.data_date and s.country_category = p.country_category
                            and s.store = p.store and s.msku = p.msku and s.country is null
                            and s.label_id = 301 and s.label_period = 'current'
                      )
                )
            """

            manual_rows = fetch(cursor, mapping_cte + """
                , campaign as (
                    select * from (
                        select c.*, row_number() over (
                            partition by profile_id, campaign_id order by update_time desc, id desc
                        ) rn
                        from ods_datasync.lx_advertising_sp_campaigns c
                        where coalesce(delete_flag, 0) = 0
                    ) x where rn = 1
                ), keyword_perf as (
                    select profile_id, campaign_id, ad_group_id, keyword_id,
                           sum(impressions) impressions, sum(clicks) clicks, sum(cost) cost,
                           sum(orders_7d) orders, sum(sales_7d) sales,
                           sum(same_orders_7d) same_orders, sum(same_sales_7d) same_sales
                    from ods_datasync.lx_advertising_sp_keyword_reports
                    where coalesce(delete_flag, 0) = 0 and report_date between %s and %s
                    group by profile_id, campaign_id, ad_group_id, keyword_id
                ), previous_keyword_perf as (
                    select profile_id, campaign_id, ad_group_id, keyword_id,
                           sum(impressions) impressions, sum(clicks) clicks, sum(cost) cost,
                           sum(orders_7d) orders, sum(sales_7d) sales,
                           sum(same_orders_7d) same_orders, sum(same_sales_7d) same_sales
                    from ods_datasync.lx_advertising_sp_keyword_reports
                    where coalesce(delete_flag, 0) = 0 and report_date between %s and %s
                    group by profile_id, campaign_id, ad_group_id, keyword_id
                )
                select m.country_code, m.currency_code, m.seller_name, m.msku,
                       m.mapping_safe, m.current_msku_count, m.period_msku_count,
                       k.profile_id, k.campaign_id, k.ad_group_id, k.keyword_id,
                       k.keyword_text, k.match_type, k.bid current_bid,
                       k.state keyword_state, k.serving_status keyword_serving_status,
                       c.state campaign_state, c.serving_status campaign_serving_status,
                       g.state ad_group_state, g.serving_status ad_group_serving_status,
                       coalesce(p.impressions, 0) impressions, coalesce(p.clicks, 0) clicks,
                       coalesce(p.cost, 0) cost, coalesce(p.orders, 0) orders,
                       coalesce(p.sales, 0) sales, coalesce(p.same_orders, 0) same_orders,
                       coalesce(p.same_sales, 0) same_sales,
                       coalesce(pp.impressions, 0) previous_impressions,
                       coalesce(pp.clicks, 0) previous_clicks,
                       coalesce(pp.cost, 0) previous_cost,
                       coalesce(pp.orders, 0) previous_orders,
                       coalesce(pp.sales, 0) previous_sales,
                       coalesce(pp.same_orders, 0) previous_same_orders,
                       coalesce(pp.same_sales, 0) previous_same_sales
                from ods_datasync.lx_advertising_sp_keywords k
                join campaign c on c.profile_id = k.profile_id and c.campaign_id = k.campaign_id
                               and lower(c.targeting_type) = 'manual'
                join ods_datasync.lx_advertising_sp_ad_groups g
                  on g.profile_id = k.profile_id and g.ad_group_id = k.ad_group_id
                 and coalesce(g.delete_flag, 0) = 0
                left join safe_map m on m.profile_id = k.profile_id and m.ad_group_id = k.ad_group_id
                join problem pb on pb.country_code = m.country_code
                               and pb.store_key = lower(regexp_replace(m.seller_name, '-(eu-)?[a-z]{2}$', ''))
                               and pb.msku_key = lower(m.msku)
                left join keyword_perf p on p.profile_id = k.profile_id and p.campaign_id = k.campaign_id
                                        and p.ad_group_id = k.ad_group_id and p.keyword_id = k.keyword_id
                left join previous_keyword_perf pp
                  on pp.profile_id = k.profile_id and pp.campaign_id = k.campaign_id
                 and pp.ad_group_id = k.ad_group_id and pp.keyword_id = k.keyword_id
                where coalesce(k.delete_flag, 0) = 0
            """, (mature_start, mature_end, label_date, mature_start, mature_end, previous_start, previous_end))
            print(f"manual_rows={len(manual_rows)}", flush=True)

            auto_term_rows = fetch(cursor, mapping_cte + """
                , campaign as (
                    select * from (
                        select c.*, row_number() over (
                            partition by profile_id, campaign_id order by update_time desc, id desc
                        ) rn
                        from ods_datasync.lx_advertising_sp_campaigns c
                        where coalesce(delete_flag, 0) = 0
                    ) x where rn = 1
                ), term_perf as (
                    select profile_id, campaign_id, ad_group_id, target_id,
                           cast(query as binary) query_binary, max(query) search_term,
                           max(target_text) target_text, max(match_type) match_type,
                           sum(impressions) impressions, sum(clicks) clicks, sum(cost) cost,
                           sum(orders_7d) orders, sum(same_orders_7d) same_orders,
                           sum(sales_7d) sales, sum(same_sales_7d) same_sales
                    from ods_datasync.lx_advertising_sp_query_word_reports
                    where coalesce(delete_flag, 0) = 0 and report_date between %s and %s
                    group by profile_id, campaign_id, ad_group_id, target_id, cast(query as binary)
                )
                select m.country_code, m.currency_code, m.seller_name, m.msku,
                       m.mapping_safe, m.current_msku_count, m.period_msku_count,
                       p.profile_id, p.campaign_id, p.ad_group_id, p.target_id,
                       p.search_term, p.target_text, p.match_type, coalesce(t.bid, g.default_bid) source_bid,
                       t.state target_state, t.serving_status target_serving_status,
                       c.state campaign_state, c.serving_status campaign_serving_status,
                       g.state ad_group_state, g.serving_status ad_group_serving_status,
                       p.impressions, p.clicks, p.cost, p.orders, p.same_orders, p.sales, p.same_sales
                from term_perf p
                join campaign c on c.profile_id = p.profile_id and c.campaign_id = p.campaign_id
                               and lower(c.targeting_type) = 'auto'
                join ods_datasync.lx_advertising_sp_ad_groups g
                  on g.profile_id = p.profile_id and g.ad_group_id = p.ad_group_id
                 and coalesce(g.delete_flag, 0) = 0
                left join ods_datasync.lx_advertising_sp_targets t
                  on t.profile_id = p.profile_id and t.target_id = p.target_id
                 and coalesce(t.delete_flag, 0) = 0
                left join safe_map m on m.profile_id = p.profile_id and m.ad_group_id = p.ad_group_id
                join problem pb on pb.country_code = m.country_code
                               and pb.store_key = lower(regexp_replace(m.seller_name, '-(eu-)?[a-z]{2}$', ''))
                               and pb.msku_key = lower(m.msku)
            """, (mature_start, mature_end, label_date, mature_start, mature_end))
            print(f"auto_term_rows={len(auto_term_rows)}", flush=True)

            negative_rows = fetch(cursor, mapping_cte + """
                select m.country_code, m.seller_name, m.msku, n.profile_id,
                       n.ad_group_id, n.negative_text, n.negative_match_type, n.state
                from ods_datasync.lx_advertising_sp_negative_targets_or_keywords n
                left join safe_map m on m.profile_id = n.profile_id and m.ad_group_id = n.ad_group_id
                join problem pb on pb.country_code = m.country_code
                               and pb.store_key = lower(regexp_replace(m.seller_name, '-(eu-)?[a-z]{2}$', ''))
                               and pb.msku_key = lower(m.msku)
                where coalesce(n.delete_flag, 0) = 0 and n.target_type = 'keyword'
            """, (mature_start, mature_end, label_date))
            print(f"negative_rows={len(negative_rows)}", flush=True)
    finally:
        connection.close()

    cohort = {
        cohort_key(COUNTRY_CODES.get(str(row["country"]), row["country"]), row["store"], row["msku"])
        for row in cohort_rows if row.get("country")
    }
    cohort_countries = Counter(key[0] for key in cohort)
    manual_scope = [r for r in manual_rows if r.get("country_code") and cohort_key(r["country_code"], r["seller_name"], r["msku"]) in cohort]
    manual_eligible = [r for r in manual_scope if int(r["mapping_safe"] or 0) == 1
                       and str(r["campaign_state"] or "").casefold() == "enabled"
                       and str(r["ad_group_state"] or "").casefold() == "enabled"
                       and str(r["keyword_state"] or "").casefold() == "enabled"
                       and number(r["current_bid"]) > 0]
    total_clicks = sum(number(r["clicks"]) for r in manual_eligible)
    total_orders = sum(number(r["orders"]) for r in manual_eligible)
    total_cost = sum(number(r["cost"]) for r in manual_eligible)
    total_sales = sum(number(r["sales"]) for r in manual_eligible)
    weighted_cvr = total_orders / total_clicks if total_clicks else 0
    mature_manual = [r for r in manual_eligible if number(r["clicks"]) >= 20 and number(r["orders"]) >= 2 and number(r["sales"]) > 0]
    previous_manual = [
        {
            **row,
            "impressions": row["previous_impressions"],
            "clicks": row["previous_clicks"],
            "cost": row["previous_cost"],
            "orders": row["previous_orders"],
            "sales": row["previous_sales"],
            "same_orders": row["previous_same_orders"],
            "same_sales": row["previous_same_sales"],
        }
        for row in manual_eligible
    ]
    previous_clicks = sum(number(r["clicks"]) for r in previous_manual)
    previous_orders = sum(number(r["orders"]) for r in previous_manual)
    previous_cost = sum(number(r["cost"]) for r in previous_manual)
    previous_sales = sum(number(r["sales"]) for r in previous_manual)
    previous_cvr = previous_orders / previous_clicks if previous_clicks else 0
    previous_mature = [r for r in previous_manual if number(r["clicks"]) >= 20 and number(r["orders"]) >= 2 and number(r["sales"]) > 0]

    def action_direction(action: str) -> str:
        if action.startswith("increase"):
            return "increase"
        if action.startswith("decrease"):
            return "decrease"
        return "neutral"

    action_pairs = [
        (action_direction(manual_action(current)), action_direction(manual_action(previous)))
        for current, previous in zip(manual_eligible, previous_manual)
    ]
    active_action_pairs = [pair for pair in action_pairs if pair != ("neutral", "neutral")]
    cross_window = {
        "keywords_non_neutral_in_either_window": len(active_action_pairs),
        "same_direction": sum(current == previous and current != "neutral" for current, previous in active_action_pairs),
        "opposite_direction": sum(
            {current, previous} == {"increase", "decrease"} for current, previous in active_action_pairs
        ),
        "current_only_non_neutral": sum(current != "neutral" and previous == "neutral" for current, previous in active_action_pairs),
        "previous_only_non_neutral": sum(current == "neutral" and previous != "neutral" for current, previous in active_action_pairs),
    }

    click_bands = (("0-9", 0, 9), ("10-14", 10, 14), ("15-19", 15, 19),
                   ("20-33", 20, 33), ("34-62", 34, 62), ("63-79", 63, 79), ("80+", 80, None))
    manual_bands = []
    for name, lower, upper in click_bands:
        rows = [r for r in manual_eligible if number(r["clicks"]) >= lower and (upper is None or number(r["clicks"]) <= upper)]
        manual_bands.append({"band": name, "keywords": len(rows),
                             "zero_order": sum(number(r["orders"]) == 0 for r in rows),
                             "one_order": sum(number(r["orders"]) == 1 for r in rows),
                             "orders_ge_2": sum(number(r["orders"]) >= 2 for r in rows)})

    by_match = []
    for match_type in sorted({str(r["match_type"] or "unknown").upper() for r in manual_eligible}):
        rows = [r for r in manual_eligible if str(r["match_type"] or "unknown").upper() == match_type]
        clicks, orders = sum(number(r["clicks"]) for r in rows), sum(number(r["orders"]) for r in rows)
        cost, sales = sum(number(r["cost"]) for r in rows), sum(number(r["sales"]) for r in rows)
        by_match.append({"match_type": match_type, "keywords": len(rows), "clicks": clicks, "orders": orders,
                         "weighted_cvr": orders / clicks if clicks else None,
                         "weighted_acos": cost / sales if sales else None})

    existing_exact_keywords = {
        (str(r["country_code"]).upper(), int(r["profile_id"]), str(r["msku"]).casefold(), normalize_term(r["keyword_text"])):
        str(r["keyword_state"] or "").casefold()
        for r in manual_scope if int(r["mapping_safe"] or 0) == 1
        and str(r["match_type"] or "").upper() == "EXACT" and normalize_term(r["keyword_text"])
    }
    existing_other_match_keywords = {
        (str(r["country_code"]).upper(), int(r["profile_id"]), str(r["msku"]).casefold(), normalize_term(r["keyword_text"]))
        for r in manual_scope if int(r["mapping_safe"] or 0) == 1
        and str(r["match_type"] or "").upper() in {"PHRASE", "BROAD"} and normalize_term(r["keyword_text"])
    }
    negatives = {
        (str(r["country_code"]).upper(), int(r["profile_id"]), str(r["msku"]).casefold(), normalize_term(r["negative_text"]))
        for r in negative_rows if r.get("country_code") and str(r["state"] or "").casefold() == "enabled" and normalize_term(r["negative_text"])
    }
    auto_scope = [r for r in auto_term_rows if r.get("country_code") and cohort_key(r["country_code"], r["seller_name"], r["msku"]) in cohort]
    auto_eligible = [r for r in auto_scope if int(r["mapping_safe"] or 0) == 1
                     and str(r["campaign_state"] or "").casefold() == "enabled"
                     and str(r["ad_group_state"] or "").casefold() == "enabled"
                     and str(r["target_state"] or "").casefold() == "enabled"]

    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in auto_eligible:
        normalized = normalize_term(row["search_term"])
        term_type = "product_target" if re.fullmatch(r"b[0-9a-z]{9}", normalized, re.I) else "keyword"
        key = (str(row["country_code"]).upper(), int(row["profile_id"]), str(row["msku"]).casefold(), term_type, normalized)
        item = grouped.setdefault(key, {"country_code": key[0], "profile_id": key[1], "msku": key[2],
                                        "term_type": key[3], "normalized": key[4], "source_rows": 0,
                                        "impressions": 0.0, "clicks": 0.0, "cost": 0.0, "orders": 0.0,
                                        "same_orders": 0.0, "sales": 0.0, "same_sales": 0.0, "source_bids": []})
        item["source_rows"] += 1
        for source in ("impressions", "clicks", "cost", "orders", "same_orders", "sales", "same_sales"):
            item[source] += number(row[source])
        if row.get("source_bid") is not None:
            item["source_bids"].append(number(row["source_bid"]))

    terms = []
    for item in grouped.values():
        item["cvr"] = item["orders"] / item["clicks"] if item["clicks"] else None
        item["acos"] = item["cost"] / item["sales"] if item["sales"] else None
        item["same_order_share"] = item["same_orders"] / item["orders"] if item["orders"] else None
        item["observed_cpc"] = item["cost"] / item["clicks"] if item["clicks"] else None
        item["source_bid_p50"] = percentile(item.pop("source_bids"), .5)
        identity = (item["country_code"], item["profile_id"], item["msku"], item["normalized"])
        item["existing_exact_state"] = existing_exact_keywords.get(identity)
        item["existing_other_match"] = identity in existing_other_match_keywords
        item["negative_conflict"] = identity in negatives
        terms.append(item)

    keyword_terms = [r for r in terms if r["term_type"] == "keyword"]
    new_keyword_terms = [r for r in keyword_terms if not r["existing_exact_state"] and r["normalized"]]

    def add_tier(row: dict[str, Any]) -> str:
        if row["negative_conflict"]:
            return "negative_conflict_review"
        if row["orders"] >= 3 and row["same_orders"] >= 2 and row["acos"] is not None and row["acos"] <= .30 and row["cvr"] is not None and row["cvr"] >= .07:
            return "high_confidence"
        if row["orders"] >= 2 and row["same_orders"] >= 1 and row["acos"] is not None and row["acos"] <= .40 and row["cvr"] is not None and row["cvr"] >= .05:
            return "standard"
        if row["orders"] == 1 and row["same_orders"] == 1 and row["acos"] is not None and row["acos"] <= .40:
            return "one_order_observe"
        return "observe"

    add_tiers = Counter(add_tier(row) for row in new_keyword_terms)
    ratios = [r["observed_cpc"] / r["source_bid_p50"] for r in new_keyword_terms
              if add_tier(r) in {"high_confidence", "standard"} and r["observed_cpc"] is not None
              and r["source_bid_p50"] and r["source_bid_p50"] > 0]
    result = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"), "label_snapshot": str(label_date),
            "ods_latest_complete_report_date": str(source_end), "mature_start": str(mature_start),
            "mature_end": str(mature_end), "previous_start": str(previous_start),
            "previous_end": str(previous_end), "cohort_source": "dws_datasync.dws_标签表（仅用于圈定产品范围）",
            "advertising_source_policy": "所有广告配置与表现仅来自 ods_datasync，不读取两张 DWS 广告宽表",
            "advertising_source_tables": [
                "ods_datasync.lx_advertising_account_list", "ods_datasync.lx_advertising_sp_campaigns",
                "ods_datasync.lx_advertising_sp_ad_groups", "ods_datasync.lx_advertising_sp_product_ads",
                "ods_datasync.lx_advertising_sp_product_ad_reports", "ods_datasync.lx_advertising_sp_keywords",
                "ods_datasync.lx_advertising_sp_keyword_reports", "ods_datasync.lx_advertising_sp_targets",
                "ods_datasync.lx_advertising_sp_query_word_reports",
                "ods_datasync.lx_advertising_sp_negative_targets_or_keywords",
            ],
        },
        "cohort": {"products": len(cohort), "countries": dict(sorted(cohort_countries.items()))},
        "manual_keywords": {
            "scope_rows": len(manual_scope), "eligible_rows": len(manual_eligible),
            "weighted_clicks": total_clicks, "weighted_orders": total_orders, "weighted_cvr": weighted_cvr,
            "weighted_acos": total_cost / total_sales if total_sales else None,
            "zero_order_click_threshold_probability_20pct": zero_order_click_threshold(weighted_cvr, .20),
            "zero_order_click_threshold_probability_5pct": zero_order_click_threshold(weighted_cvr, .05),
            "mature_sample_rows": len(mature_manual),
            "mature_acos_percentiles": percentiles([number(r["cost"]) / number(r["sales"]) for r in mature_manual]),
            "mature_cvr_percentiles": percentiles([number(r["orders"]) / number(r["clicks"]) for r in mature_manual]),
            "click_order_bands": manual_bands, "by_match_type": by_match,
            "proposed_rule_candidate_counts": dict(Counter(manual_action(r) for r in manual_eligible)),
        },
        "manual_keywords_previous_window": {
            "selection_note": "使用当前仍启用且映射安全的关键词集合复核前一不重叠30天窗口；存在存活者偏差，不是因果回测",
            "eligible_rows": len(previous_manual), "weighted_clicks": previous_clicks,
            "weighted_orders": previous_orders, "weighted_cvr": previous_cvr,
            "weighted_acos": previous_cost / previous_sales if previous_sales else None,
            "zero_order_click_threshold_probability_20pct": zero_order_click_threshold(previous_cvr, .20),
            "zero_order_click_threshold_probability_5pct": zero_order_click_threshold(previous_cvr, .05),
            "mature_sample_rows": len(previous_mature),
            "mature_acos_percentiles": percentiles([number(r["cost"]) / number(r["sales"]) for r in previous_mature]),
            "mature_cvr_percentiles": percentiles([number(r["orders"]) / number(r["clicks"]) for r in previous_mature]),
            "proposed_rule_candidate_counts": dict(Counter(manual_action(r) for r in previous_manual)),
        },
        "manual_keyword_cross_window_stability": cross_window,
        "auto_search_terms": {
            "scope_source_rows": len(auto_scope), "eligible_source_rows": len(auto_eligible),
            "aggregated_product_terms": len(terms), "aggregated_keyword_terms": len(keyword_terms),
            "new_keyword_terms_after_ods_global_dedup": len(new_keyword_terms),
            "proposed_add_tier_counts": dict(add_tiers),
            "recommended_term_cpc_to_source_bid_ratio_percentiles": percentiles(ratios),
            "product_target_terms_kept_separate": sum(r["term_type"] == "product_target" for r in terms),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
