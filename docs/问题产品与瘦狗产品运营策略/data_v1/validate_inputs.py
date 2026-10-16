"""本地校验取数完整性；只报告输入质量，不把质量状态作为动作标签。"""
from collections import Counter
from datetime import date
import argparse
import json
from pathlib import Path

from extract_inputs import COUNTRIES, FIELDS, write_json


def validate(folder: Path):
    def read(name):
        return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))

    manifest = read("manifest")
    cohort, base = read("cohort"), read("product_base")
    errors = []
    expected_countries = {"美国", "英国", "德国", "法国", "意大利", "西班牙", "荷兰"}
    if set(COUNTRIES) != expected_countries:
        errors.append("七国范围与策略不一致")
    if any(row["country"] not in expected_countries for row in cohort):
        errors.append("样本含范围外国家")
    keys = [(row["country"], row["store"], row["msku"]) for row in base]
    if len(keys) != len(set(keys)):
        errors.append("产品底表关联膨胀")
    if len(base) != manifest["products"]:
        errors.append("产品数量与批次清单不一致")
    if len(cohort) != manifest["sources"]["labels"]["rows"]:
        errors.append("标签导出不完整")
    observed = {}
    for alias, fields in FIELDS.items():
        rows = read(alias)
        if len(rows) != manifest["sources"][alias]["rows"]:
            errors.append(f"{alias}: 导出行数不一致")
        if any(set(row) != set(fields) for row in rows):
            errors.append(f"{alias}: 字段与输入契约不一致")
        detail = {"rows": len(rows)}
        if alias in ("bid_objects", "search_terms"):
            detail["mapping_status"] = dict(Counter(str(row["msku_mapping_status"]) for row in rows))
            detail["windows"] = dict(Counter(f'{row["mature_start"]}~{row["mature_end"]}' for row in rows))
            detail["non_30_day_rows"] = sum(
                (date.fromisoformat(str(row["mature_end"])[:10]) - date.fromisoformat(str(row["mature_start"])[:10])).days + 1 != 30
                for row in rows if row["mature_start"] and row["mature_end"])
            detail["missing_window_rows"] = sum(not row["mature_start"] or not row["mature_end"] for row in rows)
        if alias == "search_terms":
            detail["protection_complete"] = dict(Counter(str(row["term_protection_complete"]) for row in rows))
        if alias == "inventory":
            inventory_keys = [(row["sid"], row["seller_sku"], row["asin"], row["fnsku"]) for row in rows]
            detail["repeated_entity_keys"] = sum(count > 1 for count in Counter(inventory_keys).values())
            detail["note"] = "重复仅提示核对批次/共享库存，未自动叠加或去重"
        observed[alias] = detail
    report = {"passed": not errors, "errors": errors,
              "scope": "文件完整性及样本粒度校验；不代表动作业务校验通过",
              "country_counts": dict(Counter(row["country"] for row in base)),
              "diagnostic_counts": manifest["diagnostic_counts"], "sources": observed}
    write_json(folder / "validation.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    raise SystemExit(validate(parser.parse_args().folder))
