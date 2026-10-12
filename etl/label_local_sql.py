"""Compile the archived V47 rules for a strictly local MySQL namespace.

Only dependencies, inventory lineage and the advisory lock change. Rule strings
(including JSON paths and label names) retain their original bytes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re


BASELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "sqlcode"
    / "标签表数据插入_修改版_20260915_v47_产品表现前一日最大日期严格校验版.sql"
)
BASELINE_SHA256 = "22e968cb5cba39eba83e2b56a0f3b1d60fa2a313c5976ac5c845e22be70e3055"
RULE_VERSION = "local_v47_20260915"
PROCEDURE_NAME = "dashboard_label_local_v47"
WORK_TABLE = "dashboard_label_local_work"

SOURCE_TABLES = {
    ("dwd_datasync", "lx_sales_mws_listing"): "dashboard_label_source_listing",
    (
        "dwd_datasync",
        "lx_statistics_product_performance",
    ): "dashboard_label_source_performance",
    ("dwd_datasync", "lx_fba_shipment"): "dashboard_label_source_shipment",
    (
        "dwd_datasync",
        "lx_sales_listing_relation_tag",
    ): "dashboard_label_source_listing_tag",
    ("dwd_datasync", "lx_sales_mws_orders_detail"): "dashboard_label_source_orders",
    (
        "dwd_datasync",
        "lx_storage_fba_warehouse_detail",
    ): "dashboard_label_source_raw_fba",
    (
        "etl_datasync",
        "etl_dispose_lx_storage_fba_warehouse_detail",
    ): "dashboard_label_source_fba",
    (
        "etl_datasync",
        "etl_dispose_lx_replenishment_suggest_restocking",
    ): "dashboard_label_source_restock",
    (
        "etl_datasync",
        "etl_dispose_lx_product_local_product_info",
    ): "dashboard_label_source_product",
    ("dws_datasync", "dws_库存宽表"): "dashboard_label_source_inventory",
    ("temporary_dwd", "在库节点_输出定价表"): "dashboard_label_source_price",
    (
        "temporary_dwd",
        "在库节点_输出定价表_每日快照",
    ): "dashboard_label_source_price_history",
    (
        "temporary_APP",
        "lx_sale_adjust_price_queue",
    ): "dashboard_label_source_price_adjustment",
    ("dws_datasync", "dws_标签详情表"): "dashboard_label_source_dictionary",
}
TABLE_MAP = {
    **SOURCE_TABLES,
    ("dws_datasync", "dws_标签表"): WORK_TABLE,
    ("dws_datasync", "sp_dws_标签表_一体化_v47"): PROCEDURE_NAME,
    ("etl_datasync", "etl_execution_log"): "dashboard_label_local_execution_log",
    ("etl_datasync", "etl_error_log"): "dashboard_label_local_error_log",
    (
        "etl_datasync",
        "etl_execution_select_log_v47",
    ): "dashboard_label_local_select_log",
}

_TOKEN = re.compile(
    r"(?P<space>\s+)|(?P<comment>--(?=\s|$)[^\n]*|\#[^\n]*|/\*.*?\*/)"
    r"|(?P<string>'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\")"
    r"|(?P<quoted>`(?:``|[^`])*`)|(?P<word>[\w$]+)|(?P<symbol>.)",
    re.S,
)
_TABLE_CONTEXT = {
    "from",
    "join",
    "straight_join",
    "into",
    "update",
    "table",
    "procedure",
    "references",
}


def sql_tokens(sql: str) -> list[tuple[str, str]]:
    return [(m.lastgroup, m.group()) for m in _TOKEN.finditer(sql)]


def identifier(value: str) -> str:
    return value[1:-1].replace("``", "`") if value.startswith("`") else value


def checked_schema(schema: str) -> str:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]{0,39}", schema):
        raise ValueError("invalid local schema name")
    if schema.lower() in {
        "dwd_datasync",
        "dws_datasync",
        "etl_datasync",
        "temporary_dwd",
        "temporary_app",
        "mysql",
        "sys",
        "information_schema",
        "performance_schema",
    }:
        raise ValueError(
            "local schema must be a dedicated target, not a source/system schema"
        )
    return schema


def quote(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def qualified_references(sql: str) -> set[tuple[str, str]]:
    tokens = [(k, v) for k, v in sql_tokens(sql) if k not in {"space", "comment"}]
    result = set()
    for position, (kind, value) in enumerate(tokens):
        if kind != "word" or value.lower() not in _TABLE_CONTEXT:
            continue
        i = position + 1
        while (
            i < len(tokens)
            and tokens[i][0] == "word"
            and tokens[i][1].lower()
            in {"if", "not", "exists", "only", "low_priority", "ignore"}
        ):
            i += 1
        if i + 2 >= len(tokens):
            continue
        if (
            tokens[i][0] in {"word", "quoted"}
            and tokens[i + 1][1] == "."
            and tokens[i + 2][0] in {"word", "quoted"}
        ):
            result.add((identifier(tokens[i][1]), identifier(tokens[i + 2][1])))
    return result


def baseline_sql(path: Path = BASELINE_PATH, *, check_hash: bool = True) -> str:
    raw = path.read_bytes()
    if check_hash and hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("V47 archive hash differs from the approved baseline")
    return raw.decode("utf-8-sig")


def compile_procedure(
    schema: str,
    *,
    input_schema: str | None = None,
    path: Path = BASELINE_PATH,
    check_hash: bool = True,
) -> str:
    schema = checked_schema(schema)
    input_schema = checked_schema(input_schema or schema)
    source = baseline_sql(path, check_hash=check_hash)
    start = re.search(r"\bcreate\s+procedure\s+", source, re.I)
    end = re.search(r"\bend\s*//\s*delimiter\s*;", source, re.I)
    if not start or not end:
        raise ValueError("V47 procedure boundaries not found")
    body = source[start.start() : end.start()] + "end"
    unknown = qualified_references(body) - TABLE_MAP.keys()
    if unknown:
        raise ValueError(f"unmapped SQL dependencies: {sorted(unknown)}")
    tokens = sql_tokens(body)
    result = []
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        if kind == "comment":
            result.append("\n")
            i += 1
            continue
        if kind in {"word", "quoted"}:
            j = i + 1
            while j < len(tokens) and tokens[j][0] == "space":
                j += 1
            if j + 1 < len(tokens) and tokens[j][1] == ".":
                k = j + 1
                while tokens[k][0] == "space":
                    k += 1
                ref = (identifier(value), identifier(tokens[k][1]))
                if ref in TABLE_MAP:
                    mapped_schema = input_schema if ref in SOURCE_TABLES else schema
                    result.append(f"{quote(mapped_schema)}.{quote(TABLE_MAP[ref])}")
                    i = k + 1
                    continue
        if kind == "string" and value == "'dws_label_v47_singleton'":
            value = f"'label_local_v47:{schema}'"
        if (
            kind == "string"
            and value == "'etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail'"
        ):
            value = "'dwd_datasync.lx_storage_fba_warehouse_detail'"
        result.append(value.lower() if kind == "word" else value)
        i += 1
    compiled = "".join(result)
    allowed = {
        (input_schema if ref in SOURCE_TABLES else schema, name)
        for ref, name in TABLE_MAP.items()
    }
    if qualified_references(compiled) - allowed:
        raise ValueError("compiled procedure contains nonlocal dependencies")
    words = {v.lower() for k, v in sql_tokens(compiled) if k == "word"}
    if words & {"prepare", "execute", "event", "definer", "call"}:
        raise ValueError("unsupported executable/dynamic SQL in V47 body")
    return compiled
