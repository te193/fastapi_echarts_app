from __future__ import annotations

import configparser
import csv
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pymysql
from pymysql.cursors import DictCursor


TABLES = {
    "bid": "dashboard_sp_bid_recommendation",
    "add": "dashboard_sp_add_term_recommendation",
    "negative": "dashboard_sp_negative_term_recommendation",
}
DEFAULT_INDEXES = {"bid": "idx_bid_default_v2", "add": "idx_add_default_v2", "negative": "idx_negative_default_v2"}
SORTS = {
    "bid": {"cost", "clicks", "orders", "sales", "current_bid", "suggested_bid", "change_amount", "change_rate", "priority_rank"},
    "add": {"cost", "clicks", "orders", "sales", "acos", "priority_rank"},
    "negative": {"cost", "clicks", "orders", "sales", "acos", "priority_rank"},
}
PAGE_SIZES = {50, 100, 200}
ID_FIELDS = {"id", "batch_id", "profile_id", "campaign_id", "ad_group_id", "target_id", "object_id"}
FORMULA_PREFIXES = ("=", "+", "-", "@")
CONTEXT_WARNING_LABELS = {
    "msku_missing": "未找到推广MSKU，需人工排查",
    "multiple_msku": "关联多个MSKU，需人工排查",
    "protection_missing": "保护信息缺失，需人工排查",
}
RULE_COPY = {
    "bid": "定价毛利段理论CPC=平均客单价×CVR×毛利段系数；单次提价不超过20%，单次降价不超过30%，并受库存、预算和数据完整性保护。",
    "add": "成熟30天内广告订单≥10且ACOS≤10%为最高优先级；订单≥10且10%<ACOS≤15%为中优先级。文本词建议精准匹配，ASIN建议商品投放；MSKU映射异常单独提示，不覆盖建议结论。",
    "negative": "成熟30天内点击量≥10且广告订单为0进入高优先级。文本词建议精准否定，ASIN建议否定商品投放；MSKU或保护信息缺失单独提示，已识别保护词不直接建议否定。",
}


def table_for_kind(kind: str) -> str:
    try:
        return TABLES[kind]
    except KeyError as exc:
        raise ValueError("unsupported recommendation kind") from exc


def _escape_like(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


@dataclass
class RecommendationFilters:
    kind: str = "bid"
    object_type: str = ""
    currency: str = ""
    store: str = ""
    country: str = ""
    targeting: str = ""
    status: str = ""
    priority: str = ""
    keyword: str = ""
    msku: str = ""
    page: int = 1
    page_size: int = 50
    sort: str = "cost"
    direction: str = "desc"
    key: str = ""

    def __init__(self, values: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        source = dict(values or {}) | kwargs
        self.kind = str(source.get("kind") or "bid")
        table_for_kind(self.kind)
        self.object_type = str(source.get("object_type") or "")
        if self.object_type not in {"", "ad_group", "keyword"}:
            raise ValueError("unsupported bid object type")
        if self.object_type and self.kind != "bid":
            raise ValueError("object type only applies to bid recommendations")
        self.currency = str(source.get("currency") or "")
        self.store = str(source.get("store") or "")
        self.country = str(source.get("country") or "")
        self.targeting = str(source.get("targeting") or "")
        self.status = str(source.get("status") or "")
        self.priority = str(source.get("priority") or "")
        self.keyword = str(source.get("keyword") or "").strip()
        self.msku = str(source.get("msku") or "").strip()
        self.page = max(1, int(source.get("page") or 1))
        self.page_size = int(source.get("page_size") or 50)
        self.sort = str(source.get("sort") or "cost")
        self.direction = str(source.get("direction") or "desc").lower()
        self.key = str(source.get("key") or "")
        if self.page_size not in PAGE_SIZES:
            raise ValueError("unsupported page size")
        if self.sort not in SORTS[self.kind] or self.direction not in {"asc", "desc"}:
            raise ValueError("unsupported recommendation sort")
        if self.key and (len(self.key) != 64 or any(c not in "0123456789abcdef" for c in self.key.lower())):
            raise ValueError("invalid recommendation key")


def serialize(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in ID_FIELDS and item is not None:
                result[key] = str(item)
            elif key == "reason_codes" and isinstance(item, str):
                try:
                    result[key] = json.loads(item)
                except json.JSONDecodeError:
                    result[key] = [item]
            else:
                result[key] = serialize(item)
        reason_codes = result.get("reason_codes")
        if isinstance(reason_codes, list):
            result["data_warning"] = "；".join(
                CONTEXT_WARNING_LABELS[code]
                for code in reason_codes
                if code in CONTEXT_WARNING_LABELS
            )
        return result
    if isinstance(value, (list, tuple)):
        return [serialize(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return value


def csv_cell(field: str, value: Any) -> Any:
    if value is None:
        return ""
    text = str(value)
    if field in ID_FIELDS or text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return value


def _where(filters: RecommendationFilters, batch_id: int) -> tuple[str, list[Any]]:
    clauses = ["batch_id=%s"]
    params: list[Any] = [batch_id]
    if filters.object_type:
        clauses.append("object_type=%s")
        params.append(filters.object_type)
    for column, value in (
        ("currency_code", filters.currency),
        ("seller_name", filters.store),
        ("country_code", filters.country),
        ("targeting_type", filters.targeting),
        ("status", filters.status),
        ("priority", filters.priority if filters.kind != "bid" else ""),
    ):
        if value:
            clauses.append(f"coalesce({column},'')=%s")
            params.append("" if value == "__unknown__" else value)
    if filters.msku:
        clauses.append("coalesce(msku,'') like %s escape '!'")
        params.append(f"%{_escape_like(filters.msku)}%")
    if filters.keyword:
        fields = ["object_text"] if filters.kind == "bid" else ["search_term", "target_text", "suggestion_value"]
        clauses.append("(" + " or ".join(f"coalesce({field},'') like %s escape '!'" for field in fields) + ")")
        params.extend([f"%{_escape_like(filters.keyword)}%"] * len(fields))
    return " and ".join(clauses), params


def order_by(filters: RecommendationFilters) -> str:
    if filters.sort == "cost" and filters.direction == "desc":
        return "priority_rank asc,cost desc,id asc"
    return f"{filters.sort} {filters.direction},id asc"


class SpRecommendationService:
    def __init__(self) -> None:
        config = configparser.ConfigParser()
        config.read(Path(__file__).resolve().parents[2] / "config" / "database.ini", encoding="utf-8")
        target = config["target"]
        self.settings = dict(host=target["host"], port=int(target.get("port", 3306)), user=target["user"],
                             password=target["password"], database=target.get("database", "etl_datasync_test"),
                             charset="utf8mb4", cursorclass=DictCursor, autocommit=True)

    def connect(self):
        return pymysql.connect(**self.settings)

    def _batch(self, conn) -> dict[str, Any] | None:
        with conn.cursor() as cur:
            cur.execute("select * from dashboard_sp_recommendation_batch where status='success' order by cutoff_date desc,batch_id desc limit 1")
            return cur.fetchone()

    def options(self) -> dict[str, Any]:
        with self.connect() as conn:
            batch = self._batch(conn)
            if not batch:
                return {"status": "no_data", "rules": RULE_COPY, "currencies": [], "stores": [], "countries": []}
            with conn.cursor() as cur:
                cur.execute("""select currency_code value,count(*) n from dashboard_sp_bid_recommendation
                    where batch_id=%s group by currency_code order by n desc""", (batch["batch_id"],))
                currencies = [{"value": r["value"] or "__unknown__", "label": r["value"] or "币种未知", "count": r["n"]} for r in cur.fetchall()]
                cur.execute("select distinct seller_name value from dashboard_sp_bid_recommendation where batch_id=%s and seller_name is not null order by seller_name", (batch["batch_id"],))
                stores = [r["value"] for r in cur.fetchall()]
                cur.execute("select distinct country_code value from dashboard_sp_bid_recommendation where batch_id=%s and country_code is not null order by country_code", (batch["batch_id"],))
                countries = [r["value"] for r in cur.fetchall()]
        return serialize({"status": "success", "batch": batch, "rules": RULE_COPY, "currencies": currencies,
                          "stores": stores, "countries": countries, "default_currency": currencies[0]["value"] if currencies else ""})

    def _filters_and_batch(self, values: Mapping[str, Any]) -> tuple[RecommendationFilters, dict[str, Any]]:
        filters = RecommendationFilters(values)
        with self.connect() as conn:
            batch = self._batch(conn)
        if not batch:
            raise LookupError("暂无已发布的广告建议数据")
        return filters, batch

    def summary(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters, batch = self._filters_and_batch(values)
        clause, params = _where(filters, batch["batch_id"])
        table = table_for_kind(filters.kind)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"""select count(*) total,
                sum(status in ('increase','decrease','recommended')) recommended,
                sum(status='manual_review') manual_review,
                coalesce(sum(cost),0) cost,coalesce(sum(sales),0) sales
                from {table} where {clause}""", params)
            row = cur.fetchone()
        return serialize({"batch_id": batch["batch_id"], "summary": row})

    def rows(self, values: Mapping[str, Any], export: bool = False) -> dict[str, Any]:
        filters, batch = self._filters_and_batch(values)
        clause, params = _where(filters, batch["batch_id"])
        table = table_for_kind(filters.kind)
        limit = "" if export else " limit %s offset %s"
        query_params = params if export else [*params, filters.page_size, (filters.page - 1) * filters.page_size]
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"select count(*) total from {table} where {clause}", params)
            total = int(cur.fetchone()["total"])
            index_hint = f" force index ({DEFAULT_INDEXES[filters.kind]})" if filters.sort == "cost" and filters.direction == "desc" else ""
            cur.execute(f"select * from {table}{index_hint} where {clause} order by {order_by(filters)}{limit}", query_params)
            rows = cur.fetchall()
        return serialize({"batch_id": batch["batch_id"], "kind": filters.kind, "rows": rows, "total": total,
                          "page": filters.page, "page_size": filters.page_size})

    def detail(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters, batch = self._filters_and_batch(values)
        if not filters.key:
            raise ValueError("recommendation key is required")
        table = table_for_kind(filters.kind)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"select * from {table} where batch_id=%s and recommendation_key=%s", (batch["batch_id"], filters.key))
            row = cur.fetchone()
        if not row:
            raise LookupError("建议记录不存在")
        return serialize({"batch_id": batch["batch_id"], "item": row})

    def export_csv(self, values: Mapping[str, Any]) -> bytes:
        rows = self.rows(values, export=True)["rows"]
        output = io.StringIO()
        fields = list(rows[0]) if rows else ["message"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_cell(key, value) for key, value in row.items()})
        return ("\ufeff" + output.getvalue()).encode("utf-8")


sp_recommendation_service = SpRecommendationService()
