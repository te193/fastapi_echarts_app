"""Clone one completed input snapshot and add the omitted P20 source column."""
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from extract_inputs import FIELDS, finish_snapshot, write_json
from inspect_sources import connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source, output = args.source, args.output
    if output.exists():
        raise FileExistsError(output)

    def read(name):
        return json.loads((source / f"{name}.json").read_text(encoding="utf-8"))

    original = read("pricing")
    manifest = read("manifest")
    price_date = str(manifest["sources"]["pricing"]["date"])
    if {str(row["数据日期"]) for row in original} != {price_date}:
        raise ValueError("输入定价快照存在多个日期")
    skus = sorted({row["msku"] for row in original})
    fields = FIELDS["pricing"]
    compare_fields = [field for field in fields if field != "20毛利润价格"]
    columns = ",".join(f"`{field}`" for field in fields)
    latest = []
    with connect() as connection, connection.cursor() as cursor:
        for offset in range(0, len(skus), 200):
            batch = skus[offset:offset + 200]
            placeholders = ",".join(["%s"] * len(batch))
            cursor.execute(
                f"select {columns} from temporary_dwd.`在库节点_输出定价表` "
                f"where `数据日期`=%s and `msku` in ({placeholders})",
                (price_date, *batch),
            )
            latest.extend(cursor.fetchall())

    def signature(row):
        return tuple(str(row.get(field)) for field in compare_fields)

    if Counter(map(signature, original)) != Counter(map(signature, latest)):
        raise ValueError("源表同日期记录已经变化；不能仅补 P20，需重新提取完整快照")
    p20_by_signature = defaultdict(set)
    for row in latest:
        p20_by_signature[signature(row)].add(row["20毛利润价格"])
    if any(len(values) != 1 for values in p20_by_signature.values()):
        raise ValueError("相同定价记录对应多个 P20，无法唯一回填")
    enriched = [dict(row, **{"20毛利润价格": next(iter(p20_by_signature[signature(row)]))})
                for row in original]

    shutil.copytree(source, output, ignore=shutil.ignore_patterns("problem_actions_current"))
    write_json(output / "pricing.json", enriched)
    manifest.setdefault("notes", []).append(
        "同一数据日期从定价源表补取P20；原字段逐行比对一致，其他来源快照保持不变。")
    manifest["sources"]["pricing"]["p20_backfill_rows"] = len(enriched)
    raw = {"pricing": enriched, "cost": read("cost")}
    finish_snapshot(output, manifest, read("cohort"), raw)


if __name__ == "__main__":
    main()
