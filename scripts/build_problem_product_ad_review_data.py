"""Build read-only, auditable JSON for the 2026-09-13 ad review workbook."""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median

import pymysql

from app.services.problem_product_ad_review import (
    bid_condition, budget_decision, classify_ad_state, cohort_group, d,
    peer_reference, propose_bid,
)


SNAPSHOT = date(2026, 9, 13)
MATURE_END = date(2026, 9, 6)
MATURE_START = MATURE_END - timedelta(days=29)
PRIOR_END = MATURE_START - timedelta(days=1)
PRIOR_START = PRIOR_END - timedelta(days=29)
COUNTRY = {"德国": "DE", "法国": "FR", "意大利": "IT", "西班牙": "ES", "荷兰": "NL", "英国": "UK", "美国": "US"}
OUT = Path("outputs/问题产品广告待审核建议-20260914")


def key(country, store, msku):
    country = COUNTRY.get(str(country or "").strip(), str(country or "").strip().upper())
    store = re.sub(r"-(?:eu-)?[a-z]{2}$", "", str(store or "").strip(), flags=re.I).casefold()
    return country, store, str(msku or "").strip().casefold()


def query(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


def by_chunks(cur, table, columns, name, ids, extra=""):
    rows = []
    ids = sorted(set(ids))
    for offset in range(0, len(ids), 250):
        batch = ids[offset:offset + 250]
        placeholders = ",".join(["%s"] * len(batch))
        rows.extend(query(cur, f"select {columns} from {table} where {name} in ({placeholders}) {extra} limit 200000", batch))
    return rows


def as_json(value):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    try:
        return json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}


def primitive(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): primitive(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [primitive(v) for v in value]
    return value


def as_business_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        return datetime.fromtimestamp(number / 1000 if number >= 10**11 else number, timezone(timedelta(hours=8))).date()
    if isinstance(value, str) and value:
        return date.fromisoformat(value[:10])
    return None


def report_aggregates(cur, table, object_id_column, object_ids):
    result = {}
    for offset in range(0, len(object_ids), 200):
        batch = object_ids[offset:offset + 200]
        if not batch:
            continue
        placeholders = ",".join(["%s"] * len(batch))
        sql = f"""
          select profile_id,{object_id_column} object_id,
          sum(case when report_date between %s and %s then impressions else 0 end) impressions,
          sum(case when report_date between %s and %s then clicks else 0 end) clicks,
          sum(case when report_date between %s and %s then cost else 0 end) cost,
          sum(case when report_date between %s and %s then orders_7d else 0 end) orders,
          sum(case when report_date between %s and %s then sales_7d else 0 end) sales,
          sum(case when report_date between %s and %s then same_orders_7d else 0 end) same_orders,
          sum(case when report_date between %s and %s then clicks else 0 end) previous_clicks,
          sum(case when report_date between %s and %s then cost else 0 end) previous_cost,
          sum(case when report_date between %s and %s then orders_7d else 0 end) previous_orders,
          sum(case when report_date between %s and %s then sales_7d else 0 end) previous_sales,
          sum(case when report_date between %s and %s then same_orders_7d else 0 end) previous_same_orders
          from ods_datasync.{table}
          where {object_id_column} in ({placeholders}) and report_date between %s and %s
            and (delete_flag=0 or delete_flag is null)
          group by profile_id,{object_id_column} limit 200000
        """
        windows = [(MATURE_START, MATURE_END)] * 6 + [(PRIOR_START, PRIOR_END)] * 5
        args = [value for pair in windows for value in pair] + batch + [PRIOR_START, MATURE_END]
        for r in query(cur, sql, args):
            result[(int(r["profile_id"]), int(r["object_id"]))] = r
    return result


def campaign_reports(cur, ids):
    result = {}
    for offset in range(0, len(ids), 200):
        batch = ids[offset:offset + 200]
        if not batch:
            continue
        placeholders = ",".join(["%s"] * len(batch))
        sql = f"""
          select profile_id,campaign_id,
          sum(case when report_date between %s and %s then impressions else 0 end) impressions_7d,
          sum(case when report_date between %s and %s then clicks else 0 end) clicks_7d,
          sum(case when report_date between %s and %s then cost else 0 end) cost_7d,
          sum(case when report_date between %s and %s then orders_7d else 0 end) orders_7d,
          sum(case when report_date between %s and %s then sales_7d else 0 end) sales_7d,
          sum(case when report_date between %s and %s then cost else 0 end) previous_cost_7d,
          sum(case when report_date between %s and %s then sales_7d else 0 end) previous_sales_7d,
          count(distinct case when report_date between %s and %s then report_date end) report_days_7d
          from ods_datasync.lx_advertising_sp_campaign_reports
          where campaign_id in ({placeholders}) and report_date between %s and %s
            and (delete_flag=0 or delete_flag is null)
          group by profile_id,campaign_id limit 200000
        """
        current = (MATURE_END - timedelta(days=6), MATURE_END)
        previous = (MATURE_END - timedelta(days=13), MATURE_END - timedelta(days=7))
        args = [v for pair in [current] * 5 + [previous] * 2 + [current] for v in pair] + batch + [previous[0], MATURE_END]
        for r in query(cur, sql, args):
            result[(int(r["profile_id"]), int(r["campaign_id"]))] = r
    return result


def budget_history(current, logs):
    """Reverse each logged budget change to recover each of the mature seven days."""
    current = d(current)
    if current is None:
        return None, "当前预算缺失"
    changes = []
    for log in logs:
        before, after = as_json(log.get("operate_before")), as_json(log.get("operate_after"))
        if not isinstance(before, list) or not isinstance(after, list):
            continue
        old = next((d(x.get("value")) for x in before if x.get("code") == "BUDGET_AMOUNT"), None)
        new = next((d(x.get("value")) for x in after if x.get("code") == "BUDGET_AMOUNT"), None)
        if old is not None and new is not None:
            changes.append((log["operate_time"], old, new))
    changes.sort(reverse=True)
    value = current
    for _, old, new in changes:
        if abs(value - new) > Decimal("0.011"):
            return None, "预算日志与当前值无法衔接"
        value = old
    total = Decimal(0)
    for day in (MATURE_END - timedelta(days=i) for i in range(6, -1, -1)):
        day_value = value
        for when, _, new in reversed(changes):
            if when.date() <= day:
                day_value = new
        total += day_value
    return total, "ODS活动变更日志逆推；日内改动按当日末预算"


def main():
    read_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    db = pymysql.connect(host=os.environ["OPT_LYT_DB_HOST"], port=int(os.environ.get("OPT_LYT_DB_PORT", "3306")),
                         user=os.environ["OPT_LYT_DB_USER"], password=os.environ["OPT_LYT_DB_PASSWORD"],
                         charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, read_timeout=240,
                         autocommit=False)
    try:
        with db.cursor() as cur:
            hits = query(cur, "select country,store,msku,asin,rule_code,evidence_json from dws_datasync.`dws_产品策略命中结果表` where data_date=%s limit 10000", (SNAPSHOT,))
            products = {}
            rates = defaultdict(list)
            for hit in hits:
                evidence = as_json(hit["evidence_json"])
                group = cohort_group(evidence.get("metrics") or {})
                if group is None:
                    continue
                k = key(hit["country"], hit["store"], hit["msku"])
                if k in products:
                    raise ValueError(f"重复产品键：{k}")
                hit["group"] = group
                hit["metrics"] = evidence.get("metrics") or {}
                hit["currency_context"] = evidence.get("currency_context") or {}
                products[k] = hit
            groups = Counter(p["group"] for p in products.values())
            if groups != {"无销量售价不高于P15": 1037, "日销0至1毛利低于5%": 829}:
                raise ValueError(f"固定产品名单核对失败：{groups}")
            accounts = {int(x["profile_id"]): x for x in query(cur, "select profile_id,country_code,currency_code,sid,name from ods_datasync.lx_advertising_account_list where (delete_flag=0 or delete_flag is null) limit 2000")}
            ads = query(cur, "select profile_id,campaign_id,ad_group_id,ad_id,state,sku,asin,serving_status,seller_name,creation_date from ods_datasync.lx_advertising_sp_product_ads where (delete_flag=0 or delete_flag is null) limit 150000")
            ad_by_key, asin_by_key, campaign_all_ads = defaultdict(list), defaultdict(list), defaultdict(list)
            for ad in ads:
                account = accounts.get(int(ad["profile_id"]))
                if not account:
                    continue
                country = account["country_code"]
                k = key(country, ad["seller_name"], ad["sku"])
                if k in products:
                    ad_by_key[k].append(ad)
                if ad.get("asin"):
                    asin_by_key[(country, key(country, ad["seller_name"], "")[1], str(ad["asin"]).upper())].append(ad)
                campaign_all_ads[(int(ad["profile_id"]), int(ad["campaign_id"]))].append(ad)
            campaign_ids = {int(a["campaign_id"]) for arr in ad_by_key.values() for a in arr}
            group_ids = {int(a["ad_group_id"]) for arr in ad_by_key.values() for a in arr}
            campaigns = {(int(x["profile_id"]), int(x["campaign_id"])): x for x in by_chunks(cur, "ods_datasync.lx_advertising_sp_campaigns", "profile_id,campaign_id,name,state,serving_status,daily_budget,creation_date,last_updated_date,targeting_type,seller_name", "campaign_id", campaign_ids, "and (delete_flag=0 or delete_flag is null)")}
            adgroups = {(int(x["profile_id"]), int(x["ad_group_id"])): x for x in by_chunks(cur, "ods_datasync.lx_advertising_sp_ad_groups", "profile_id,ad_group_id,state,serving_status,default_bid", "ad_group_id", group_ids, "and (delete_flag=0 or delete_flag is null)")}
            for k, p in products.items():
                fx = d(p["currency_context"].get("exchange_rate"))
                stamp = p["currency_context"].get("exchange_rate_date")
                for a in ad_by_key.get(k, []):
                    account = accounts.get(int(a["profile_id"])) or {}
                    if fx and stamp == "2026-09" and account.get("currency_code"):
                        rates[account["currency_code"]].append(fx)
            fx_by_currency = {c: (median(v) if max(v) - min(v) <= Decimal("0.0001") else None) for c, v in rates.items()}
            euro_rate = fx_by_currency.get("EUR")
            statuses = []
            live_keys = set()
            live_campaigns = set()
            for k, p in products.items():
                rows = []
                for ad in ad_by_key.get(k, []):
                    identity = (int(ad["profile_id"]), int(ad["campaign_id"]))
                    camp = campaigns.get(identity) or {}
                    group = adgroups.get((int(ad["profile_id"]), int(ad["ad_group_id"]))) or {}
                    rows.append({"ad_state": ad["state"], "group_state": group.get("state"), "campaign_state": camp.get("state"), "serving_status": ad["serving_status"], "profile_id": ad["profile_id"], "campaign_id": ad["campaign_id"], "ad_group_id": ad["ad_group_id"], "ad_id": ad["ad_id"], "campaign_serving_status": camp.get("serving_status")})
                asin_key = (k[0], k[1], str(p.get("asin") or "").upper())
                ambiguous = len({int(x["profile_id"]) for x in ad_by_key.get(k, [])}) > 1 or (not rows and bool(asin_by_key.get(asin_key)))
                status = classify_ad_state(rows, ambiguous=ambiguous)
                if status == "可投放":
                    live_keys.add(k)
                    live_campaigns.update((int(a["profile_id"]), int(a["campaign_id"])) for a in ad_by_key[k] if a["serving_status"] == "AD_STATUS_LIVE")
                statuses.append({"国家": p["country"], "店铺": p["store"], "MSKU": p["msku"], "ASIN": p.get("asin"), "产品组": p["group"], "日销30天": p["metrics"].get("daily_sales_30d"), "当前售价": p["metrics"].get("current_price"), "P15售价": p["metrics"].get("p15_price"), "毛利率30天": p["metrics"].get("margin_rate_30d"), "广告状态": status, "SP对象数": len(rows), "对象标识": ";".join(f"{x['profile_id']}/{x['campaign_id']}/{x['ad_group_id']}/{x['ad_id']}" for x in rows), "复核原因": "多账号或ASIN仅疑似匹配" if ambiguous else ("" if status == "可投放" else "当前ODS配置与投放状态"), "ODS读取时间": read_at})
            print("status", Counter(s["广告状态"] for s in statuses), flush=True)
            snapshot = query(cur, "select max(snapshot_date) as dt from dws_datasync.dws_sp_bid_object_snapshot_daily where snapshot_date<=%s limit 1", (SNAPSHOT,))[0]["dt"]
            bid_source = query(cur, "select profile_id,campaign_id,ad_group_id,object_type,object_id,object_text,match_type,seller_name,country_code,currency_code,msku,msku_mapping_status,associated_msku_count,listing_price,margin_rate,mature_start,mature_end from dws_datasync.dws_sp_bid_object_snapshot_daily where snapshot_date=%s and msku is not null limit 30000", (snapshot,))
            bid_candidates = []
            for x in bid_source:
                k = key(x["country_code"], x["seller_name"], x["msku"])
                if k in live_keys and (int(x["profile_id"]), int(x["campaign_id"])) in live_campaigns:
                    x["product_key"] = k
                    bid_candidates.append(x)
            keyword_ids = {int(x["object_id"]) for x in bid_candidates if x["object_type"] == "keyword"}
            keyword_now = {(int(x["profile_id"]), int(x["keyword_id"])): x for x in by_chunks(cur, "ods_datasync.lx_advertising_sp_keywords", "profile_id,keyword_id,ad_group_id,campaign_id,keyword_text,bid,state,serving_status,match_type", "keyword_id", keyword_ids, "and (delete_flag=0 or delete_flag is null)")}
            keyword_metrics = report_aggregates(cur, "lx_advertising_sp_keyword_reports", "keyword_id", sorted(keyword_ids))
            auto_ids = {int(x["ad_group_id"]) for x in bid_candidates if x["object_type"] == "ad_group"}
            auto_metrics = report_aggregates(cur, "lx_advertising_sp_ad_group_reports", "ad_group_id", sorted(auto_ids))
            bid_rows = []
            for x in bid_candidates:
                k = x["product_key"]
                identity = (int(x["profile_id"]), int(x["object_id"]))
                metric = (keyword_metrics if x["object_type"] == "keyword" else auto_metrics).get(identity) or {}
                now = keyword_now.get(identity) if x["object_type"] == "keyword" else adgroups.get((int(x["profile_id"]), int(x["ad_group_id"])))
                match = str(x.get("match_type") or "").upper()
                group = "exact_phrase" if match in ("EXACT", "PHRASE") else "broad_close_complements" if match == "BROAD" or x["object_type"] == "ad_group" else "other"
                currency = accounts[int(x["profile_id"])]["currency_code"]
                native_rate = fx_by_currency.get(currency)
                euro_to_native = euro_rate / native_rate if euro_rate and native_rate else None
                clicks, orders, sales = d(metric.get("clicks")) or 0, d(metric.get("orders")) or 0, d(metric.get("sales")) or 0
                same = d(metric.get("same_orders")) or 0
                prev_clicks, prev_orders, prev_sales = d(metric.get("previous_clicks")) or 0, d(metric.get("previous_orders")) or 0, d(metric.get("previous_sales")) or 0
                prev_same = d(metric.get("previous_same_orders")) or 0
                aov = (sales + prev_sales) / (orders + prev_orders) if orders + prev_orders > 0 else None
                cvr = (same + prev_same) / (clicks + prev_clicks) if clicks + prev_clicks > 0 else None
                margin = d(x.get("margin_rate"))
                max_bid = aov * cvr * margin if aov and cvr and margin and margin > 0 else None
                row = {"country": k[0], "store": products[k]["store"], "msku": products[k]["msku"], "product_group": products[k]["group"],
                       "profile_id": x["profile_id"], "campaign_id": x["campaign_id"], "ad_group_id": x["ad_group_id"], "object_type": x["object_type"], "object_id": x["object_id"], "object_text": x["object_text"], "match_group": group, "currency": currency,
                       "current_bid": now.get("bid") if x["object_type"] == "keyword" and now else now.get("default_bid") if now else None,
                       "object_state": now.get("state") if now else None, "mapping_status": x["msku_mapping_status"], "associated_msku_count": x["associated_msku_count"],
                       "listing_price": x["listing_price"], "margin_rate": margin, "max_bid": max_bid, "aov_60d": aov,
                       "impressions": metric.get("impressions", 0), "clicks": clicks, "cost": metric.get("cost", 0), "orders": orders, "sales": sales, "same_orders": same,
                       "previous_clicks": prev_clicks, "previous_cost": metric.get("previous_cost", 0), "previous_orders": prev_orders, "previous_sales": prev_sales, "previous_same_orders": prev_same,
                       "mature_start": MATURE_START, "mature_end": MATURE_END, "prior_start": PRIOR_START, "prior_end": PRIOR_END,
                       "bid_snapshot_date": snapshot, "ods_read_at": read_at}
                condition, reason = bid_condition(row, euro_to_native)
                row.update(condition=condition, condition_reason=reason, euro_to_native=euro_to_native)
                bid_rows.append(row)
            for row in bid_rows:
                peer = peer_reference(bid_rows, row["country"], row["currency"], row["match_group"]) if row["condition"].startswith("降价_零销售") else None
                proposal = propose_bid(row, peer)
                if row["mapping_status"] != "mapped" or int(row["associated_msku_count"] or 0) != 1:
                    proposal = {"new_bid": None, "change_rate": None, "basis": "", "reason": "竞价对象非单一MSKU安全归属"}
                if row["object_state"] != "enabled":
                    proposal = {"new_bid": None, "change_rate": None, "basis": "", "reason": "竞价对象当前未启用"}
                row.update(proposal)
                row["borrow_level"] = peer["level"] if peer else ""
                row["borrow_n"] = peer["n"] if peer else None
            report = campaign_reports(cur, sorted({c for _, c in live_campaigns}))
            logs = by_chunks(cur, "ods_datasync.lx_advertising_api_log_standard", "profile_id,campaign_id,operate_type,operate_before,operate_after,operate_time", "campaign_id", {c for _, c in live_campaigns}, "and operate_time>='2026-08-30' and (delete_flag=0 or delete_flag is null)")
            logs_by_campaign = defaultdict(list)
            for x in logs:
                logs_by_campaign[(int(x["profile_id"]), int(x["campaign_id"]))].append(x)
            budget_rows = []
            for ident in sorted(live_campaigns):
                camp = campaigns.get(ident) or {}
                perf = report.get(ident) or {}
                account = accounts[ident[0]]
                group_keys = {key(account["country_code"], a["seller_name"], a["sku"]) for a in campaign_all_ads[ident]}
                outside = bool(group_keys - set(products))
                history, history_reason = budget_history(camp.get("daily_budget"), logs_by_campaign[ident])
                current_state = str(camp.get("state") or "").lower() == "enabled"
                created = as_business_date(camp.get("creation_date"))
                enabled_days = (SNAPSHOT - created).days + 1 if isinstance(created, date) else 0
                status_changes = [x for x in logs_by_campaign[ident] if x.get("operate_type") == "campaigns" and ("STATUS" in str(x.get("operate_before")) or "STATUS" in str(x.get("operate_after")))]
                last3 = any(x["operate_time"].date() >= SNAPSHOT - timedelta(days=2) for x in logs_by_campaign[ident])
                eligible_keys = group_keys & set(products)
                native_rates = {fx_by_currency.get(account["currency_code"])}
                fx = next(iter(native_rates))
                previous_acos = d(perf.get("previous_cost_7d")) / d(perf.get("previous_sales_7d")) if d(perf.get("previous_sales_7d")) and d(perf.get("previous_sales_7d")) > 0 else None
                current_acos = d(perf.get("cost_7d")) / d(perf.get("sales_7d")) if d(perf.get("sales_7d")) and d(perf.get("sales_7d")) > 0 else None
                row = {"profile_id": ident[0], "campaign_id": ident[1], "campaign_name": camp.get("name"), "country": account["country_code"], "currency": account["currency_code"], "cohort_msku_count": len(eligible_keys), "outside_msku_count": len(group_keys - set(products)), "shared_outside_cohort": outside,
                       "current_daily_budget": camp.get("daily_budget"), "historical_budget_7d": history, "history_reason": history_reason,
                       "enabled_days": enabled_days, "enabled_last_10_days": current_state and enabled_days >= 10 and not any(x["operate_time"].date() >= SNAPSHOT - timedelta(days=9) for x in status_changes),
                       "changed_last_3_days": last3, "currency_rate_cny": fx,
                       "impressions_7d": perf.get("impressions_7d"), "clicks_7d": perf.get("clicks_7d"), "cost_7d": perf.get("cost_7d"), "orders_7d": perf.get("orders_7d"), "sales_7d": perf.get("sales_7d"),
                       "report_days_7d": perf.get("report_days_7d"), "previous_acos_7d": previous_acos, "acos_improving": current_acos is not None and previous_acos is not None and current_acos < previous_acos,
                       "mature_start": MATURE_END - timedelta(days=6), "mature_end": MATURE_END, "ods_read_at": read_at}
                decision = budget_decision(row)
                if perf.get("report_days_7d") != 7:
                    decision = {"status": "待复核", "new_budget": None, "change_rate": None, "reason": "成熟7天报表缺日"}
                if decision["status"] == "暂停活动":
                    for b in bid_rows:
                        if (int(b["profile_id"]), int(b["campaign_id"])) == ident:
                            b.update(new_bid=None, change_rate=None, reason="活动暂停建议优先，竞价试算不执行")
                row.update(decision)
                row["linked_bid_raise_review"] = any(b["condition"].startswith("提价") and (int(b["profile_id"]), int(b["campaign_id"])) == ident for b in bid_rows)
                budget_rows.append(row)
            term_snapshot = query(cur, "select max(snapshot_date) as dt from dws_datasync.dws_sp_search_term_analysis_daily where snapshot_date<=%s limit 1", (SNAPSHOT,))[0]["dt"]
            terms = []
            for offset in range(0, len(products), 200):
                mskus = sorted({k[2] for k in products})[offset:offset + 200]
                if not mskus:
                    continue
                placeholders = ",".join(["%s"] * len(mskus))
                terms.extend(query(cur, f"select profile_id,campaign_id,ad_group_id,country_code,seller_name,msku,search_term,search_term_normalized,search_term_type,match_type,clicks,cost,orders_7d,same_orders_7d,sales_7d,term_protection_complete,is_brand_term,is_core_category_term,is_new_product_term,existing_object_state,msku_mapping_status,associated_msku_count from dws_datasync.dws_sp_search_term_analysis_daily where snapshot_date=%s and lower(msku) in ({placeholders}) and (clicks>=10 or orders_7d>0) limit 100000", [term_snapshot] + mskus))
            live_groups = {(int(a["profile_id"]), int(a["ad_group_id"])) for k in live_keys for a in ad_by_key[k] if a["serving_status"] == "AD_STATUS_LIVE"}
            existing_keywords = by_chunks(cur, "ods_datasync.lx_advertising_sp_keywords", "profile_id,ad_group_id,keyword_text,state", "ad_group_id", {g for _, g in live_groups}, "and (delete_flag=0 or delete_flag is null)")
            existing_negative = by_chunks(cur, "ods_datasync.lx_advertising_sp_negative_targets_or_keywords", "profile_id,ad_group_id,negative_text,state", "ad_group_id", {g for _, g in live_groups}, "and (delete_flag=0 or delete_flag is null)")
            positive = {(int(x["profile_id"]), int(x["ad_group_id"]), str(x["keyword_text"] or "").strip().casefold()) for x in existing_keywords}
            negative = {(int(x["profile_id"]), int(x["ad_group_id"]), str(x["negative_text"] or "").strip().casefold()) for x in existing_negative}
            term_rows = {}
            for t in terms:
                k = key(t["country_code"], t["seller_name"], t["msku"])
                ident = (int(t["profile_id"]), int(t["ad_group_id"]))
                if k not in live_keys or ident not in live_groups:
                    continue
                word = str(t["search_term_normalized"] or t["search_term"] or "").strip().casefold()
                if not word:
                    continue
                dedup = (*ident, word)
                old = term_rows.get(dedup)
                if old and (d(old["点击30天"]) or 0) >= (d(t["clicks"]) or 0):
                    continue
                clicks, orders, cost, sales = d(t["clicks"]) or 0, d(t["orders_7d"]) or 0, d(t["cost"]) or 0, d(t["sales_7d"]) or 0
                acos = cost / sales if sales > 0 else None
                add = "候选加词" if orders > 0 and acos is not None and acos <= Decimal("0.15") else "加词待复核" if orders > 0 and acos is not None and acos <= Decimal("0.20") else "不加词"
                neg = "候选否词" if clicks >= 100 and orders == 0 else "不否词"
                reasons = []
                if dedup in positive or t["existing_object_state"]:
                    add, reasons = "已有投放", ["ODS已有关键词或DWS已有投放标识"]
                if dedup in negative:
                    neg = "已有否词"
                if neg == "候选否词" and (not t["term_protection_complete"] or t["is_brand_term"] or t["is_core_category_term"] or t["is_new_product_term"]):
                    neg, reasons = "否词待复核", reasons + ["品牌/类目/新品保护或保护资料不全"]
                if t["msku_mapping_status"] != "mapped" or int(t["associated_msku_count"] or 0) != 1:
                    add, neg, reasons = "待核对归属", "待核对归属", reasons + ["搜索词非单一MSKU安全归属"]
                if add.startswith("候选") and neg.startswith("候选"):
                    add, neg, reasons = "方向冲突待复核", "方向冲突待复核", reasons + ["同词加否方向冲突"]
                term_rows[dedup] = {"国家": k[0], "店铺": products[k]["store"], "MSKU": products[k]["msku"], "Profile ID": ident[0], "活动ID": t["campaign_id"], "广告组ID": ident[1], "搜索词": t["search_term"], "类型": t["search_term_type"], "点击30天": clicks, "花费30天": cost, "订单30天": orders, "销售额30天": sales, "ACOS": acos, "加词建议": add, "否词建议": neg, "已有正向投放": dedup in positive, "已有否词": dedup in negative, "受保护": bool(t["is_brand_term"] or t["is_core_category_term"] or t["is_new_product_term"]), "复核原因": ";".join(reasons), "表现截止": MATURE_END, "ODS读取时间": read_at}
    finally:
        db.close()
    output = {"meta": {"product_snapshot": SNAPSHOT, "ods_read_at": read_at, "bid_mature_start": MATURE_START, "bid_mature_end": MATURE_END, "prior_start": PRIOR_START, "prior_end": PRIOR_END, "budget_mature_start": MATURE_END - timedelta(days=6), "budget_mature_end": MATURE_END, "bid_mapping_snapshot": snapshot, "term_snapshot": term_snapshot, "fx_by_currency": fx_by_currency, "source_tables": ["dws_datasync.dws_产品策略命中结果表", "ods_datasync.lx_advertising_sp_product_ads", "ods_datasync.lx_advertising_sp_campaigns", "ods_datasync.lx_advertising_sp_ad_groups", "ods_datasync.lx_advertising_sp_keyword_reports", "ods_datasync.lx_advertising_sp_ad_group_reports", "ods_datasync.lx_advertising_sp_campaign_reports", "ods_datasync.lx_advertising_api_log_standard", "dws_datasync.dws_sp_search_term_analysis_daily"]}, "products": statuses, "bids": bid_rows, "budgets": budget_rows, "terms": list(term_rows.values())}
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "广告建议只读数据.json"
    target.write_text(json.dumps(primitive(output), ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(target), "products": len(statuses), "bids": len(bid_rows), "budgets": len(budget_rows), "terms": len(term_rows), "statuses": dict(Counter(s["广告状态"] for s in statuses))}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
