"""只读核对第一版运营数据来源；不执行旧版策略或写数据库。"""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor


SOURCES = [
    ("labels", "dws_datasync", "dws_标签表汇总", "data_date"),
    ("cost", "temporary_dwd", "产品近30天八项成本_每日快照_v4", "数据日期"),
    ("pricing", "temporary_dwd", "在库节点_输出定价表", "数据日期"),
    ("inventory", "dwd_datasync", "lx_storage_fba_warehouse_detail", "create_time"),
    ("bid_objects", "dws_datasync", "dws_sp_bid_object_snapshot_daily", "snapshot_date"),
    ("search_terms", "dws_datasync", "dws_sp_search_term_analysis_daily", "snapshot_date"),
    ("budget", "dws_datasync", "dws_monthly_ad_budget_detail", "biz_date"),
]


def connect():
    helper_path = Path.home() / ".codex/skills/opt-lyt-db/scripts/query_opt_lyt.py"
    spec = importlib.util.spec_from_file_location("readonly_db_helper", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return pymysql.connect(
        host=helper.env_required("OPT_LYT_DB_HOST"),
        port=int(helper.env_optional("OPT_LYT_DB_PORT", "3306")),
        user=helper.env_required("OPT_LYT_DB_USER"),
        password=helper.env_required("OPT_LYT_DB_PASSWORD"),
        charset="utf8mb4", cursorclass=DictCursor,
        connect_timeout=10, read_timeout=180,
    )


def inspect(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    result = {"checked_at": datetime.now().isoformat(timespec="seconds"),
              "scope": "仅来源核对，不沿用来源文档旧策略", "sources": []}
    with connect() as connection, connection.cursor() as cursor:
        for alias, schema, table, date_column in SOURCES:
            print(f"checking {alias}", flush=True)
            item = {"alias": alias, "schema": schema, "table": table,
                    "date_column": date_column}
            cursor.execute(
                "select ordinal_position, column_name, column_type, is_nullable, column_comment "
                "from information_schema.columns where table_schema=%s and table_name=%s "
                "order by ordinal_position", (schema, table))
            item["columns"] = [{key.lower(): value for key, value in row.items()}
                               for row in cursor.fetchall()]
            item["exists"] = bool(item["columns"])
            if item["exists"]:
                cursor.execute(
                    "select index_name, non_unique, seq_in_index, column_name "
                    "from information_schema.statistics where table_schema=%s and table_name=%s "
                    "order by index_name, seq_in_index", (schema, table))
                item["indexes"] = [{key.lower(): value for key, value in row.items()}
                                   for row in cursor.fetchall()]
                names = {row["column_name"] for row in item["columns"]}
                if date_column in names:
                    # 标识符只来自以上固定清单，不接受外部 SQL 输入。
                    cursor.execute(f"select max(`{date_column}`) as latest_date from `{schema}`.`{table}`")
                    item["latest_date"] = cursor.fetchone()["latest_date"]
            result["sources"].append(item)
            (output / "source_inventory.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("source inspection complete", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "outputs")
    args = parser.parse_args()
    inspect(args.output)
