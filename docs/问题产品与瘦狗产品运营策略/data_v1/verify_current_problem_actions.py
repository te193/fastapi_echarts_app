"""Independent structural and price checks for one local action batch."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from decimal import Decimal, ROUND_CEILING
from pathlib import Path


def d(value):
    return Decimal(str(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root
    out = root / "problem_actions_current"

    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    actions = read(out / "final_actions.json")
    blocked = read(out / "blocked_candidates.json")
    products = read(out / "products.json")
    source = read(root / "manifest.json")
    result = read(out / "manifest.json")
    cohort = {(p["country"], p["store"], p["msku"]): p for p in read(root / "product_base.json") if p["source_roles"] == ["problem"]}
    assert len(cohort) == len(products) == result["products"]
    assert result["label_date"] == str(source["sources"]["labels"]["date"])
    assert len(actions) == result["action_count"]
    assert len(blocked) == result["blocked_count"]
    assert Counter(a["action_type"] for a in actions) == result["action_counts"]
    seen = set()
    ad_counts = Counter()
    price_counts = Counter()
    for row in actions:
        key = (row["country"], row["store"], row["msku"])
        assert key in cohort and row["label_date"] == result["label_date"]
        assert row["status"] == "MANUAL_REVIEW"
        identity = (*key, row["action_type"], row["entity"])
        assert identity not in seen, identity
        seen.add(identity)
        if row["action_type"] == "调价":
            price_counts[key] += 1
            price = cohort[key]["pricing_input"]
            current, p10, p15, p20, p25 = (d(price[field]) for field in
                                            ("listing价格", "10毛利润价格", "15毛利润价格",
                                             "20毛利润价格", "25毛利润价格"))
            assert 0 < p10 < p15 < p20 < p25
            tier, target = (("P25", p25) if current > p25 else
                            ("P20", p20) if current > p20 else
                            ("P15", p15) if current > p15 else ("P10", p10))
            expected = target.quantize(d(".01"), rounding=ROUND_CEILING)
            assert d(row["current_value"]) == current
            assert d(row["suggested_value"]) == expected
            assert row["target_tier"] == tier
            assert p10 <= expected < current
        else:
            ad_counts[key] += 1
            if row["action_type"] in ("提高竞价", "降低竞价"):
                old, new = d(row["current_value"]), d(row["suggested_value"])
                assert (new > old) == (row["action_type"] == "提高竞价")
                assert row.get("profile_id") and row.get("object_id")
                assert row.get("platform_bid_bounds") == "待平台最终核验"
                if row["action_type"] == "提高竞价":
                    evidence = row["budget_evidence"]
                    assert d(evidence["available_month"]) > 0 and d(evidence["available_week"]) > 0
    assert max(price_counts.values(), default=0) <= 1
    assert max(ad_counts.values(), default=0) <= 2

    def write_csv(name, rows, leading_fields=()):
        fields = list(leading_fields) + sorted(set().union(*(r.keys() for r in rows)) - set(leading_fields))
        with (out / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else v for k, v in row.items()})

    price_rows = [r for r in actions if r["action_type"] == "调价"]
    ad_rows = [r for r in actions if r["action_type"] != "调价"]
    enable_rows = [r for r in ad_rows if r["action_type"] == "开启广告"]
    bid_rows = [r for r in ad_rows if r["action_type"] in ("提高竞价", "降低竞价")]
    negative_rows = [r for r in ad_rows if r["action_type"] == "否定关键词"]
    common = ("country", "store", "msku", "action_type", "rule_code", "status", "label_date")
    write_csv("问题产品调价名单.csv", price_rows, common)
    # Keep the combined export for existing readers, but explain action-specific nulls up front.
    combined = []
    for row in ad_rows:
        item = dict(row)
        if row["action_type"] == "开启广告":
            item["field_note"] = "现有结构见单独明细；竞价涨跌幅不适用；流量和预算尚未核验，不能据此执行"
            item["existing_structure_count"] = len(row["existing_structures"])
        elif row["action_type"] == "否定关键词":
            item["field_note"] = "否词动作无竞价涨跌幅；预算证据不适用"
        else:
            item["field_note"] = "竞价动作；现有结构明细不适用"
        combined.append(item)
    write_csv("问题产品广告动作名单.csv", combined, (*common, "field_note", "existing_structure_count"))
    write_csv("问题产品竞价动作名单.csv", bid_rows,
              (*common, "profile_id", "campaign_id", "ad_group_id", "object_id", "object_text",
               "current_value", "suggested_value", "change_rate", "clicks", "cost", "budget_evidence"))
    write_csv("问题产品否词动作名单.csv", negative_rows,
              (*common, "profile_id", "campaign_id", "ad_group_id", "object_text", "negative_match_type", "clicks", "cost"))
    write_csv("问题产品开启广告名单.csv", [
        {k: v for k, v in row.items() if k != "existing_structures"} |
        {"existing_structure_count": len(row["existing_structures"]),
         "review_note": "流量和预算尚未核验；核验现有广告结构和状态后决定启用或重建，不能直接批量启用"}
        for row in enable_rows
    ], (*common, "profile_id", "existing_structure_count", "evidence", "review_note"))
    structure_rows = []
    for row in enable_rows:
        for structure in row["existing_structures"]:
            structure_rows.append({k: row[k] for k in common} | structure)
    assert len(structure_rows) == sum(len(row["existing_structures"]) for row in enable_rows)
    write_csv("问题产品开启广告结构明细.csv", structure_rows,
              (*common, "profile_id", "campaign_id", "ad_group_id", "ad_id",
               "campaign_state", "group_state", "ad_state"))

    print(json.dumps({"result": "passed", "products": len(cohort), "actions": len(actions),
                      "price_products": len(price_counts), "ad_products": len(ad_counts),
                      "blocked": len(blocked)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
