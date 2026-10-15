"""Read-only ODS facts for the current problem-product cohort; no legacy recommendations."""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from inspect_sources import connect
from extract_inputs import write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--aov-only", action="store_true")
    args = parser.parse_args()
    root = args.root
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    label_day = date.fromisoformat(str(manifest["sources"]["labels"]["date"])[:10])
    report_end = label_day
    month_start = report_end.replace(day=1)
    week_start = report_end - timedelta(days=report_end.weekday())
    bids = json.loads((root / "bid_objects.json").read_text(encoding="utf-8"))
    products = json.loads((root / "product_base.json").read_text(encoding="utf-8"))
    problem_skus = {r["msku"] for r in products if r["source_roles"] == ["problem"]}
    groups = sorted({str(r["ad_group_id"]) for r in bids if r["msku"] in problem_skus and r.get("ad_group_id")})
    skus = sorted(problem_skus)
    results = {}

    def placeholders(values):
        return ",".join(["%s"] * len(values))

    with connect() as conn, conn.cursor() as cur:
        if args.aov_only:
            mature_end = report_end - timedelta(days=7)
            start = mature_end - timedelta(days=59)
            cur.execute(
                "select profile_id,sku,sum(same_orders_7d) as same_orders_7d,"
                "sum(same_sales_7d) as same_sales_7d,count(distinct report_date) as observed_days "
                "from ods_datasync.lx_advertising_sp_product_ad_reports "
                f"where sku in ({placeholders(skus)}) and report_date between %s and %s "
                "and delete_flag=0 group by profile_id,sku",
                (*skus, start, mature_end),
            )
            rows = cur.fetchall()
            write_json(root / "current_sp_aov_60d.json", rows)
            print(f"60d SP AOV facts: {len(rows)}", flush=True)
            return
        for name, table, columns in (
            ("targets", "lx_advertising_sp_targets", "id,profile_id,campaign_id,ad_group_id,target_id,expression_type,expression,resolved_expression,bid,state,serving_status,delete_flag,create_time,update_time"),
            ("keywords", "lx_advertising_sp_keywords", "id,profile_id,campaign_id,ad_group_id,keyword_id,keyword_text,match_type,bid,state,serving_status,delete_flag,create_time,update_time"),
            ("negatives", "lx_advertising_sp_negative_targets_or_keywords", "id,profile_id,campaign_id,ad_group_id,target_id,negative_type,negative_text,negative_match_type,state,serving_status,delete_flag,create_time,update_time"),
        ):
            print(f"extracting {name}", flush=True)
            cur.execute(
                f"select {columns} from ods_datasync.{table} where ad_group_id in ({placeholders(groups)})",
                groups,
            )
            results[name] = cur.fetchall()
            write_json(root / f"current_{name}.json", results[name])
            print(f"{name}: {len(results[name])}", flush=True)

        print("extracting product spend", flush=True)
        cur.execute(
            "select profile_id,sku,campaign_id,ad_group_id,"
            "sum(case when report_date between %s and %s then cost else 0 end) as month_spend,"
            "sum(case when report_date between %s and %s then cost else 0 end) as week_spend,"
            "count(distinct case when report_date between %s and %s then report_date end) as month_days,"
            "max(report_date) as latest_report_date "
            "from ods_datasync.lx_advertising_sp_product_ad_reports "
            f"where sku in ({placeholders(skus)}) and report_date between %s and %s "
            "and delete_flag=0 group by profile_id,sku,campaign_id,ad_group_id",
            (month_start, report_end, week_start, report_end, month_start, report_end, *skus, month_start, report_end),
        )
        results["product_spend"] = cur.fetchall()
        write_json(root / "current_product_spend.json", results["product_spend"])
        print(f"product spend: {len(results['product_spend'])}", flush=True)

        print("extracting search-term facts", flush=True)
        mature_end = report_end - timedelta(days=7)
        mature_start = mature_end - timedelta(days=29)
        cur.execute(
            "select profile_id,campaign_id,ad_group_id,target_id,query,match_type,target_text,"
            "sum(clicks) as clicks,sum(cost) as cost,sum(orders_7d) as orders_7d,"
            "sum(sales_7d) as sales_7d,sum(same_orders_7d) as same_orders_7d,"
            "sum(same_sales_7d) as same_sales_7d,count(distinct report_date) as observed_days "
            "from ods_datasync.lx_advertising_sp_query_word_reports "
            f"where ad_group_id in ({placeholders(groups)}) and report_date between %s and %s "
            "and delete_flag=0 group by profile_id,campaign_id,ad_group_id,target_id,query,match_type,target_text",
            (*groups, mature_start, mature_end),
        )
        results["search_terms"] = cur.fetchall()
        write_json(root / "current_search_terms.json", results["search_terms"])
        print(f"search terms: {len(results['search_terms'])}", flush=True)

    write_json(root / "current_ads_manifest.json", {
        "label_date": label_day,
        "spend_window": [month_start, report_end],
        "week_window": [week_start, report_end],
        "mature_window": [mature_start, mature_end],
        "counts": {name: len(rows) for name, rows in results.items()},
        "notes": ["source facts only", "no legacy suggested bids, add terms, or negative recommendations"],
    })


if __name__ == "__main__":
    main()
