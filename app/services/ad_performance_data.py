from __future__ import annotations

import configparser
import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pymysql
from pymysql.cursors import DictCursor


VIEWS = {
    "product": {
        "table": "dashboard_sp_product_ad_daily",
        "group": ["profile_id", "seller_name", "country_code", "currency_code", "msku"],
        "objects": ["group_concat(distinct asin order by asin separator ', ') as asin"],
        "labels": ["seller_name", "country_code", "msku", "asin"],
    },
    "campaign": {
        "table": "dashboard_sp_campaign_daily",
        "group": ["profile_id", "seller_name", "country_code", "currency_code", "campaign_id"],
        "objects": ["max(campaign_name_current) campaign_name_current", "max(portfolio_name_current) portfolio_name_current",
                    "max(targeting_type) targeting_type", "max(campaign_state_current) object_state_current"],
        "labels": ["seller_name", "country_code", "campaign_name_current", "portfolio_name_current", "targeting_type"],
    },
    "ad_group": {
        "table": "dashboard_sp_ad_group_daily",
        "group": ["profile_id", "seller_name", "country_code", "currency_code", "campaign_id", "ad_group_id"],
        "objects": ["max(campaign_name_current) campaign_name_current", "max(ad_group_name_current) ad_group_name_current",
                    "max(targeting_type) targeting_type", "max(ad_group_state_current) object_state_current",
                    "max(associated_msku_count) associated_msku_count"],
        "labels": ["seller_name", "country_code", "campaign_name_current", "ad_group_name_current", "targeting_type"],
    },
    "keyword": {
        "table": "dashboard_sp_keyword_daily",
        "group": ["profile_id", "seller_name", "country_code", "currency_code", "campaign_id", "ad_group_id", "keyword_id",
                  "cast(keyword_text as binary)", "cast(match_type as binary)"],
        "objects": ["max(campaign_name_current) campaign_name_current", "max(ad_group_name_current) ad_group_name_current",
                    "max(keyword_text) keyword_text", "max(match_type) match_type", "max(targeting_type) targeting_type",
                    "max(object_state_current) object_state_current", "max(associated_msku_count) associated_msku_count"],
        "labels": ["seller_name", "country_code", "campaign_name_current", "ad_group_name_current", "keyword_text", "match_type"],
    },
    "search_term": {
        "table": "dashboard_sp_search_term_daily",
        "group": ["profile_id", "seller_name", "country_code", "currency_code", "campaign_id", "ad_group_id", "target_id",
                  "cast(search_term as binary)", "cast(match_type as binary)"],
        "objects": ["max(campaign_name_current) campaign_name_current", "max(ad_group_name_current) ad_group_name_current",
                    "max(target_text) target_text", "max(target_expressions) target_expressions", "max(search_term) search_term",
                    "max(match_type) match_type", "max(targeting_type) targeting_type",
                    "max(object_state_current) object_state_current", "max(associated_msku_count) associated_msku_count"],
        "labels": ["seller_name", "country_code", "campaign_name_current", "ad_group_name_current", "target_text", "search_term", "match_type"],
    },
}
WINDOWS = {1, 7, 14, 30}
SORTS = {"cost", "sales", "orders", "impressions", "clicks", "ctr", "cpc", "cvr", "acos", "roas"}
ID_FIELDS = {"profile_id", "campaign_id", "ad_group_id", "keyword_id", "target_id", "ad_id", "portfolio_id"}
FORMULA_PREFIXES = ("=", "+", "-", "@")


def _iso(value: Any) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value))


@dataclass
class Filters:
    view: str = "product"
    start: date | None = None
    end: date | None = None
    currency: str = ""
    store: str = ""
    country: str = ""
    targeting: str = ""
    keyword: str = ""
    campaign: str = ""
    ad_group: str = ""
    keyword_text: str = ""
    search_term: str = ""
    msku: str = ""
    window: int = 7
    page: int = 1
    page_size: int = 50
    sort: str = "cost"
    direction: str = "desc"
    key: str = ""
    profile_id: str = ""
    campaign_id: str = ""
    ad_group_id: str = ""

    def __init__(self, values: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        source = dict(values or {}) | kwargs
        self.view = str(source.get("view") or "product")
        self.window = int(source.get("window") or 7)
        self.start, self.end = _iso(source.get("start")), _iso(source.get("end"))
        self.currency = str(source.get("currency") or "")
        self.store = str(source.get("store") or "")
        self.country = str(source.get("country") or "")
        self.targeting = str(source.get("targeting") or "")
        self.keyword = str(source.get("keyword") or "").strip()
        self.campaign = str(source.get("campaign") or "").strip()
        self.ad_group = str(source.get("ad_group") or "").strip()
        self.keyword_text = str(source.get("keyword_text") or "").strip()
        self.search_term = str(source.get("search_term") or "").strip()
        self.msku = str(source.get("msku") or "").strip()
        self.page = max(1, int(source.get("page") or 1))
        self.page_size = min(200, max(1, int(source.get("page_size") or 50)))
        self.sort = str(source.get("sort") or "cost")
        self.direction = str(source.get("direction") or "desc").lower()
        self.key = str(source.get("key") or "")
        self.profile_id = str(source.get("profile_id") or "")
        self.campaign_id = str(source.get("campaign_id") or "")
        self.ad_group_id = str(source.get("ad_group_id") or "")
        if self.view not in VIEWS or self.window not in WINDOWS or self.sort not in SORTS or self.direction not in {"asc", "desc"}:
            raise ValueError("unsupported view, window or sort")
        if self.start and self.end and self.start > self.end:
            raise ValueError("start date must not be after end date")
        if self.key and (len(self.key) != 64 or any(c not in "0123456789abcdef" for c in self.key.lower())):
            raise ValueError("invalid detail key")
        if any(value and not value.isdigit() for value in (self.profile_id, self.campaign_id, self.ad_group_id)):
            raise ValueError("invalid advertising identifier")


def _escape_like(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def where(filters: Filters) -> tuple[str, list[Any]]:
    clauses, params = ["report_date between %s and %s"], [filters.start, filters.end]
    for column, value in (("currency_code", filters.currency), ("targeting_type", filters.targeting)):
        if value:
            clauses.append(f"coalesce({column}, '')=%s")
            params.append("" if value == "__unknown__" else value)
    for column, value in (("seller_name", filters.store), ("country_code", filters.country),
                          ("campaign_name_current", filters.campaign),
                          ("ad_group_name_current", filters.ad_group)):
        if value:
            clauses.append(f"coalesce({column}, '') like %s escape '!'")
            params.append(f"%{_escape_like(value)}%")
    if filters.keyword_text:
        clauses.append("coalesce(keyword_text, target_text, '') like %s escape '!'")
        params.append(f"%{_escape_like(filters.keyword_text)}%")
    if filters.search_term:
        clauses.append("coalesce(search_term, '') like %s escape '!'")
        params.append(f"%{_escape_like(filters.search_term)}%")
    for column, value in (("profile_id", filters.profile_id), ("campaign_id", filters.campaign_id),
                          ("ad_group_id", filters.ad_group_id)):
        if value:
            clauses.append(f"t.{column}=%s")
            params.append(int(value))
    if filters.keyword:
        columns = VIEWS[filters.view]["labels"]
        clauses.append("(" + " or ".join(f"coalesce({c}, '') like %s escape '!'" for c in columns) + ")")
        params.extend([f"%{_escape_like(filters.keyword)}%"] * len(columns))
    if filters.msku:
        needle = f"%{_escape_like(filters.msku)}%"
        if filters.view == "product":
            clauses.append("coalesce(msku, '') like %s escape '!'")
        else:
            clauses.append("exists (select 1 from dashboard_sp_ad_group_msku_current am where am.profile_id=t.profile_id and am.campaign_id=t.campaign_id and am.ad_group_id=t.ad_group_id and coalesce(am.msku,'') like %s escape '!')")
        params.append(needle)
    return " and ".join(clauses), params


def trend_index_hint(filters: Filters) -> str:
    """Avoid MySQL's costly date-index scan for broad daily aggregations."""
    if filters.start and filters.end and (filters.end - filters.start).days >= 6:
        return " ignore index (idx_date_profile,idx_date_store)"
    return ""


def _ratio(a: Any, b: Any) -> Decimal | None:
    if a is None or b is None or Decimal(str(b)) == 0:
        return None
    return Decimal(str(a)) / Decimal(str(b))


def with_rates(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row.update(ctr=_ratio(row.get("clicks"), row.get("impressions")), cpc=_ratio(row.get("cost"), row.get("clicks")),
               cvr=_ratio(row.get("orders"), row.get("clicks")), acos=_ratio(row.get("cost"), row.get("sales")),
               roas=_ratio(row.get("sales"), row.get("cost")))
    return row


def serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (str(v) if k in ID_FIELDS and v is not None else serialize(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    return value


def csv_cell(field: str, value: Any) -> Any:
    if value is None:
        return ""
    text = str(value)
    if field in ID_FIELDS:
        return "'" + text
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return value


class AdPerformanceService:
    def __init__(self) -> None:
        config = configparser.ConfigParser()
        config.read(Path(__file__).resolve().parents[2] / "config" / "database.ini", encoding="utf-8")
        target = config["target"]
        self.settings = dict(host=target["host"], port=int(target.get("port", 3306)), user=target["user"],
                             password=target["password"], database=target.get("database", "etl_datasync_test"),
                             charset="utf8mb4", cursorclass=DictCursor, autocommit=True)

    def connect(self):
        return pymysql.connect(**self.settings)

    def _range(self, conn, filters: Filters) -> Filters:
        if filters.start and filters.end:
            return filters
        with conn.cursor() as cur:
            cur.execute("select min(report_date) min_date,max(report_date) max_date from dashboard_sp_product_ad_daily")
            row = cur.fetchone()
        latest = row["max_date"] or date.today() - timedelta(days=1)
        filters.end = filters.end or latest
        filters.start = filters.start or max(row["min_date"] or latest, filters.end - timedelta(days=29))
        return filters

    def filters(self, values: Mapping[str, Any]) -> Filters:
        with self.connect() as conn:
            return self._range(conn, Filters(values))

    def options(self) -> dict[str, Any]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("select min(report_date) min_date,max(report_date) max_date from dashboard_sp_product_ad_daily")
            dates = cur.fetchone()
            cur.execute("select coalesce(currency_code,'') value,count(*) n from dashboard_sp_product_ad_daily group by currency_code order by n desc")
            currencies = [{"value": r["value"] or "__unknown__", "label": r["value"] or "币种未知", "count": r["n"]} for r in cur.fetchall()]
            cur.execute("select distinct seller_name value from dashboard_sp_product_ad_daily where seller_name is not null order by seller_name")
            stores = [r["value"] for r in cur.fetchall()]
            cur.execute("select distinct country_code value from dashboard_sp_product_ad_daily where country_code is not null order by country_code")
            countries = [r["value"] for r in cur.fetchall()]
            cur.execute("select batch_id,finished_at from dashboard_sp_etl_batch where status='success' order by batch_id desc limit 1")
            batch = cur.fetchone() or {}
        return serialize({"min_date": dates["min_date"], "max_date": dates["max_date"], "currencies": currencies,
                          "stores": stores, "countries": countries, "default_currency": currencies[0]["value"] if currencies else "",
                          "batch_id": batch.get("batch_id"), "updated_at": batch.get("finished_at")})

    def _metric_select(self, window: int) -> str:
        return (f"sum(impressions) impressions,sum(clicks) clicks,sum(cost) cost,"
                f"sum(orders_{window}d) orders,sum(units_{window}d) units,sum(sales_{window}d) sales,"
                f"sum(same_orders_{window}d) same_orders,sum(same_units_{window}d) same_units,"
                f"sum(same_sales_{window}d) same_sales,sum(clicks)/nullif(sum(impressions),0) ctr,"
                f"sum(cost)/nullif(sum(clicks),0) cpc,sum(orders_{window}d)/nullif(sum(clicks),0) cvr,"
                f"sum(cost)/nullif(sum(sales_{window}d),0) acos,"
                f"sum(sales_{window}d)/nullif(sum(cost),0) roas")

    def _base(self, filters: Filters, index_hint: str = "") -> tuple[dict[str, Any], str, list[Any]]:
        config = VIEWS[filters.view]
        clause, params = where(filters)
        return config, f"from {config['table']} t{index_hint} where {clause}", params

    def summary(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters = self.filters(values)
        _, base, params = self._base(filters)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"select {self._metric_select(filters.window)} {base}", params)
            row = with_rates(cur.fetchone())
        return serialize({"filters": filters.__dict__, "summary": row})

    def trend(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters = self.filters(values)
        _, base, params = self._base(filters, trend_index_hint(filters))
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"select report_date,{self._metric_select(filters.window)} {base} group by report_date order by report_date", params)
            rows = [with_rates(r) for r in cur.fetchall()]
        return serialize({"rows": rows})

    def _group_sql(self, config: dict[str, Any]) -> tuple[str, str]:
        group = ",".join(config["group"])
        identity = ",".join(f"max({field})" for field in config["group"])
        key = f"sha2(concat_ws(char(31),{identity}),256) item_key"
        visible_group = [field for field in config["group"] if not field.startswith("cast(")]
        select = ",".join(visible_group + config["objects"] + [key])
        return select, group

    def rows(self, values: Mapping[str, Any], export: bool = False) -> dict[str, Any]:
        filters = self.filters(values)
        config, base, params = self._base(filters)
        select, group = self._group_sql(config)
        metric = self._metric_select(filters.window)
        inner = f"select {select},{metric} {base} group by {group}"
        with self.connect() as conn, conn.cursor() as cur:
            if export:
                cur.execute(f"select * from ({inner}) x order by {filters.sort} {filters.direction}", params)
                rows = [with_rates(r) for r in cur.fetchall()]
                return {"rows": serialize(rows), "filters": filters}
            offset = (filters.page - 1) * filters.page_size
            cur.execute(f"select x.*,count(*) over() __total from ({inner}) x "
                        f"order by {filters.sort} {filters.direction} limit %s offset %s",
                        [*params, filters.page_size, offset])
            raw_rows = cur.fetchall()
            total = raw_rows[0].pop("__total") if raw_rows else 0
            rows = [with_rates(r) for r in raw_rows]
        return serialize({"rows": rows, "total": total, "page": filters.page, "page_size": filters.page_size,
                          "view": filters.view, "window": filters.window})

    def detail(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters = self.filters(values)
        if not filters.key:
            raise ValueError("detail key is required")
        config, base, params = self._base(filters)
        select, group = self._group_sql(config)
        windows: dict[str, Any] = {}
        item = None
        trend: list[dict[str, Any]] = []
        with self.connect() as conn, conn.cursor() as cur:
            for window in sorted(WINDOWS):
                inner = f"select {select},{self._metric_select(window)} {base} group by {group}"
                cur.execute(f"select * from ({inner}) x where item_key=%s", [*params, filters.key])
                row = cur.fetchone()
                if row:
                    item = item or row
                    windows[str(window)] = row
            daily = (f"select report_date,{select},{self._metric_select(filters.window)} {base} "
                     f"group by report_date,{group}")
            cur.execute(f"select report_date,cost,sales,clicks,orders from ({daily}) x "
                        "where item_key=%s order by report_date", [*params, filters.key])
            trend = cur.fetchall()
        if not item:
            raise LookupError("detail item not found")
        return serialize({"item": item, "windows": windows, "trend": trend})

    def export_csv(self, values: Mapping[str, Any]) -> bytes:
        result = self.rows(values, export=True)
        rows = result["rows"]
        output = io.StringIO()
        fields = list(rows[0]) if rows else ["message"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: csv_cell(k, v) for k, v in row.items()})
        return ("\ufeff" + output.getvalue()).encode("utf-8")


ad_performance_service = AdPerformanceService()
