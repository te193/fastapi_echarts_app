from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Callable, Mapping
from threading import RLock
from time import monotonic
from typing import Any


ISSUE_CODES = {
    "conflict", "missing_metrics", "zero_sales", "negative_profit", "problem_role",
    "problem_product", "low_margin", "site_status_abnormal", "pricing_risk",
    "cross_country_inconsistent",
}
PAGE_SIZES = {20, 50, 100}
BUSINESS_SORT_FIELDS = {
    "problem_priority", "country_category", "store", "msku", "current_label",
    "sales_role_code", "sales_trend_code", "daily_sales", "sales_qty", "sales_amount",
    "order_gross_profit", "order_gross_margin", "ending_inventory_qty", "ad_spend", "return_count",
    "label_summary", "sales_role", "sales_trend", "lifecycle_label", "daily_sales_band",
    "margin_band", "conflict", "data_status", "acos", "tacos", "net_amount",
    "sales_amount_ex_tax", "avg_inventory_qty", "ad_sales", "return_amount", "settlement_gross_profit",
}
COUNTRY_SORT_FIELDS = BUSINESS_SORT_FIELDS | {
    "country", "sku", "country_sales_role_label", "site_status_label", "price_label", "site_lifecycle_label",
    "ranking",
}
METRIC_FILTER_FIELDS = {"sales_roles", "sales_trends", "daily_sales_bands", "margin_bands", "ranking_bands"}
METRIC_PROBLEMS = {"missing_metrics", "zero_sales", "negative_profit", "low_margin"}
RANKING_BANDS = {"top10", "11_20", "21_50", "51_100", "gt100", "missing"}
ROLE_REASON_PARENT_BY_VIEW = {"business_unit": 15, "country": 16}
ROLE_REASON_IDS_BY_VIEW = {
    "business_unit": set(range(1501, 1509)),
    "country": set(range(1601, 1619)),
}
DETAIL_CACHE_SECONDS = 300
CURRENT_STOCKOUT_PARENT_ID = 3
CURRENT_STOCKOUT_CHILD_ID = 304
STOCKOUT_BEFORE_ROLE_IDS = {2101, 2102, 2103, 2104}
STOCKOUT_BEFORE_ROLE_PERIODS = {"7d", "14d", "30d", "90d"}


def _normalize_identifiers(values: list[str] | None) -> tuple[list[str], list[str]]:
    displays: list[str] = []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        display = str(value or "").strip()
        key = display.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        displays.append(display)
        normalized.append(key)
    if len(normalized) > 100:
        raise ValueError("标识符最多支持 100 个不同值")
    return displays, normalized


def _issues(row: dict[str, Any], metric_status: str) -> set[str]:
    result: set[str] = set()
    if row.get("conflict"):
        result.add("conflict")
    if metric_status == "available" and not row.get("_metric_present", row.get("metric_present", True)):
        result.add("missing_metrics")
    metric_present = row.get("_metric_present", row.get("metric_present", True))
    if metric_present and (row.get("daily_sales") == 0 or row.get("daily_sales_band_code") == "zero"):
        result.add("zero_sales")
    if metric_present and row.get("order_gross_profit") is not None and row["order_gross_profit"] < 0:
        result.add("negative_profit")
    if row.get("sales_role_code") == "eliminate":
        result.add("problem_role")
        result.add("problem_product")
    if metric_present and row.get("order_gross_margin") is not None and row["order_gross_margin"] < 0.05:
        result.add("low_margin")
    if any(word in str(row.get("site_status_label") or "") for word in ("部分", "异常", "停售", "断货")):
        result.add("site_status_abnormal")
    if any(word in str(row.get("price_label") or "") for word in ("亏损", "低毛利", "清仓", "异常")):
        result.add("pricing_risk")
    if row.get("cross_country_inconsistent"):
        result.add("cross_country_inconsistent")
    return result


def _ranking_band(value: Any) -> str:
    try:
        ranking = int(value)
    except (TypeError, ValueError):
        return "missing"
    if ranking <= 0:
        return "missing"
    if ranking <= 10:
        return "top10"
    if ranking <= 20:
        return "11_20"
    if ranking <= 50:
        return "21_50"
    if ranking <= 100:
        return "51_100"
    return "gt100"


class LabelHubDetailDataService:
    def __init__(
        self,
        business_row_provider: Callable[..., list[dict[str, Any]] | dict[str, Any]],
        identifier_alias_provider: Mapping[str, Any] | Callable[[list[str]], Mapping[str, Any]] | None = None,
        condition_parser: Callable[[str], dict[int, set[int]]] | None = None,
        country_row_provider: Callable[..., list[dict[str, Any]] | dict[str, Any]] | None = None,
        country_summary_provider: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self._business_row_provider = business_row_provider
        self._identifier_alias_provider = identifier_alias_provider or {}
        self._country_row_provider = country_row_provider
        self._country_summary_provider = country_summary_provider
        self._business_rows_cache: OrderedDict[tuple[Any, ...], tuple[float, Any]] = OrderedDict()
        self._country_rows_cache: OrderedDict[tuple[Any, ...], tuple[float, Any]] = OrderedDict()
        self._business_rows_cache_lock = RLock()
        if condition_parser is None:
            from .label_hub_data import label_hub_service
            condition_parser = label_hub_service.parse_conditions
        self._condition_parser = condition_parser

    def _business_rows(self, provider_kwargs: dict[str, Any]) -> Any:
        cache_key = tuple(
            (key, tuple(value) if isinstance(value, list) else value)
            for key, value in provider_kwargs.items()
        )
        now = monotonic()
        with self._business_rows_cache_lock:
            cached = self._business_rows_cache.get(cache_key)
            if cached and now - cached[0] < DETAIL_CACHE_SECONDS:
                self._business_rows_cache.move_to_end(cache_key)
                return cached[1]
        result = self._business_row_provider(**provider_kwargs)
        with self._business_rows_cache_lock:
            self._business_rows_cache[cache_key] = (now, result)
            self._business_rows_cache.move_to_end(cache_key)
            while len(self._business_rows_cache) > 8:
                self._business_rows_cache.popitem(last=False)
        return result

    def _country_rows(self, provider_kwargs: dict[str, Any]) -> Any:
        cache_key = tuple(
            (key, tuple(value) if isinstance(value, list) else value)
            for key, value in provider_kwargs.items()
        )
        now = monotonic()
        with self._business_rows_cache_lock:
            cached = self._country_rows_cache.get(cache_key)
            if cached and now - cached[0] < DETAIL_CACHE_SECONDS:
                self._country_rows_cache.move_to_end(cache_key)
                return cached[1]
        result = self._country_row_provider(**provider_kwargs)
        with self._business_rows_cache_lock:
            self._country_rows_cache[cache_key] = (monotonic(), result)
            self._country_rows_cache.move_to_end(cache_key)
            while len(self._country_rows_cache) > 2:
                self._country_rows_cache.popitem(last=False)
        return result

    def _alias_payload(self, identifiers: list[str]) -> tuple[dict[str, Any], int]:
        provider = self._identifier_alias_provider
        payload = provider(identifiers) if callable(provider) else provider
        country_count = 0
        if "aliases" in payload:
            country_count = int(payload.get("country_unit_count") or 0)
            payload = payload.get("aliases") or {}
        return {str(key).strip().casefold(): value for key, value in payload.items()}, country_count

    @staticmethod
    def _alias_value(value: Any) -> tuple[set[str], int]:
        country_count = 0
        if isinstance(value, Mapping):
            country_count = int(value.get("country_unit_count") or 0)
            value = value.get("mskus") or []
        if isinstance(value, str):
            value = [value]
        return {str(item).strip().casefold() for item in value or [] if str(item).strip()}, country_count

    def get_details(self, **filters: Any) -> dict[str, Any]:
        return self._get_details(paginate=True, **filters)

    def get_export_rows(self, **filters: Any) -> dict[str, Any]:
        return self._get_details(paginate=False, **filters)

    def _get_details(self, *, paginate: bool, **filters: Any) -> dict[str, Any]:
        detail_view = str(filters.get("detail_view") or "business_unit")
        if detail_view not in {"business_unit", "country"}:
            raise ValueError("明细视图不受支持")
        if detail_view == "country" and self._country_row_provider is None:
            raise ValueError("国家明细数据源暂不可用")
        mode = str(filters.get("problem_mode") or "any")
        if mode not in {"any", "all"}:
            raise ValueError("问题匹配模式只支持 any 或 all")
        page_size = int(filters.get("page_size") or 20)
        if page_size not in PAGE_SIZES:
            raise ValueError("每页条数只支持 20、50、100")
        sort_field = str(filters.get("sort_field") or "sales_amount")
        sort_fields = COUNTRY_SORT_FIELDS if detail_view == "country" else BUSINESS_SORT_FIELDS
        if sort_field not in sort_fields:
            raise ValueError("排序字段不受支持")
        ranking_bands = {
            str(item or "").strip()
            for item in filters.get("ranking_bands") or []
            if str(item or "").strip()
        }
        if not ranking_bands.issubset(RANKING_BANDS):
            raise ValueError("排名筛选包含无效档位")

        try:
            role_reason_ids = list(dict.fromkeys(
                int(item) for item in filters.get("role_reason_ids") or []
            ))
        except (TypeError, ValueError) as exc:
            raise ValueError("角色原因筛选包含无效标签") from exc
        if not set(role_reason_ids).issubset(ROLE_REASON_IDS_BY_VIEW[detail_view]):
            raise ValueError("角色原因筛选与当前明细维度不匹配")
        role_reason_parent = ROLE_REASON_PARENT_BY_VIEW[detail_view]

        stockout_before_role_period = str(filters.get("stockout_before_role_period") or "")
        if stockout_before_role_period and stockout_before_role_period not in STOCKOUT_BEFORE_ROLE_PERIODS:
            raise ValueError("断货前角色周期不存在")
        try:
            stockout_before_role_ids = {
                int(item) for item in filters.get("stockout_before_role_ids") or []
            }
        except (TypeError, ValueError) as exc:
            raise ValueError("断货前角色筛选包含无效标签") from exc
        if not stockout_before_role_ids.issubset(STOCKOUT_BEFORE_ROLE_IDS):
            raise ValueError("断货前角色筛选包含无效标签")
        if stockout_before_role_ids and not stockout_before_role_period:
            raise ValueError("断货前角色筛选必须指定周期")
        current_stockout_only = bool(filters.get("current_stockout_only"))

        requested, normalized = _normalize_identifiers(filters.get("identifiers"))
        aliases, provider_country_count = self._alias_payload(normalized)
        alias_targets: dict[str, set[str]] = {}
        alias_country_counts: dict[str, int] = {}
        for key, value in aliases.items():
            alias_targets[key], alias_country_counts[key] = self._alias_value(value)

        analysis_parent_ids = filters.get("analysis_parent_ids") or []
        analysis_periods = filters.get("analysis_periods") or []
        provider_kwargs = dict(
            data_date=filters.get("data_date", ""), metric_period=filters.get("metric_period", "30d"),
            country_category=filters.get("country_category", "all"), store=filters.get("store", "all"),
            keyword=filters.get("keyword", ""), parent_label_id=filters.get("parent_label_id", 0),
            compare_parent_id=filters.get("compare_parent_id", 0), conditions=filters.get("conditions", ""),
            label_period=filters.get("label_period", "all"),
            analysis_parent_ids="|".join(map(str, analysis_parent_ids)),
            analysis_periods="|".join(map(str, analysis_periods)),
        )
        provider_result = self._business_rows(provider_kwargs)
        if isinstance(provider_result, Mapping):
            rows = [dict(row) for row in provider_result.get("rows") or []]
            metric_status = str(provider_result.get("metric_status") or "unknown")
            warnings = list(provider_result.get("warnings") or [])
            provider_country_count = int(provider_result.get("country_unit_count") or provider_country_count)
        else:
            rows = [dict(row) for row in provider_result]
            metric_status, warnings = "unknown", []

        country_rows: list[dict[str, Any]] = []
        country_metric_status = "unknown"
        country_warnings: list[str] = []
        detail_filters_active = bool(
            normalized
            or filters.get("country_categories") or filters.get("stores")
            or filters.get("detail_conditions") or filters.get("sales_roles")
            or role_reason_ids
            or filters.get("sales_trends") or filters.get("daily_sales_bands")
            or filters.get("margin_bands") or filters.get("problems")
            or current_stockout_only or stockout_before_role_period or stockout_before_role_ids
            or (detail_view == "country" and ranking_bands)
        )
        use_country_summary = (
            detail_view == "business_unit"
            and not detail_filters_active
            and not filters.get("conditions")
            and self._country_summary_provider is not None
        )
        if use_country_summary:
            summary = self._country_summary_provider(**provider_kwargs)
            provider_country_count = int(summary.get("country_unit_count") or 0)
        elif self._country_row_provider is not None:
            country_result = self._country_rows({
                **provider_kwargs,
                "identifiers": requested,
                "detail_view": detail_view,
            })
            if isinstance(country_result, Mapping):
                country_rows = [dict(row) for row in country_result.get("rows") or []]
                country_metric_status = str(country_result.get("metric_status") or "unknown")
                country_warnings = list(country_result.get("warnings") or [])
            else:
                country_rows = [dict(row) for row in country_result]
            business_by_key = {
                (
                    str(row.get("country_category") or ""),
                    str(row.get("store") or ""),
                    str(row.get("msku") or "").casefold(),
                ): row
                for row in rows
            }
            merged_country_rows: list[dict[str, Any]] = []
            for country_row in country_rows:
                key = (
                    str(country_row.get("country_category") or ""),
                    str(country_row.get("store") or ""),
                    str(country_row.get("msku") or "").casefold(),
                )
                business_row = business_by_key.get(key)
                if business_row is None:
                    continue
                merged = dict(business_row)
                merged.update(country_row)
                by_parent = {
                    int(parent): set(children)
                    for parent, children in (business_row.get("_by_parent") or {}).items()
                }
                for parent, children in (country_row.get("_by_parent") or {}).items():
                    by_parent.setdefault(int(parent), set()).update(children)
                merged["_by_parent"] = by_parent
                label_keys: set[tuple[int, int]] = set()
                labels = []
                for label in [*(business_row.get("labels") or []), *(country_row.get("labels") or [])]:
                    label_key = (int(label.get("parent_id") or 0), int(label.get("id") or 0))
                    if label_key in label_keys:
                        continue
                    label_keys.add(label_key)
                    labels.append(label)
                merged["labels"] = labels
                merged_country_rows.append(merged)
            country_rows = merged_country_rows
            if detail_view == "country":
                rows = country_rows
                metric_status = country_metric_status
                warnings = country_warnings

        all_resolution_rows = [*rows, *country_rows]
        existing_mskus = {str(row.get("msku") or "").casefold() for row in all_resolution_rows}
        matched: list[str] = []
        unmatched: list[str] = []
        selected_mskus: set[str] = set()
        selected_skus: set[str] = set()
        country_count = provider_country_count if not normalized else 0
        for display, identifier in zip(requested, normalized):
            targets = set(alias_targets.get(identifier, set()))
            if identifier in existing_mskus:
                targets.add(identifier)
            sku_targets = {
                str(row.get("msku") or "").casefold()
                for row in country_rows
                if str(row.get("sku") or "").strip().casefold() == identifier
            }
            targets.update(sku_targets)
            targets.intersection_update(existing_mskus)
            if targets:
                matched.append(display)
                selected_mskus.update(targets)
                if sku_targets:
                    selected_skus.add(identifier)
                country_count += alias_country_counts.get(identifier, 0)
            else:
                unmatched.append(display)

        problems = {str(item) for item in filters.get("problems") or []}
        if not problems.issubset(ISSUE_CODES):
            raise ValueError("问题筛选包含不支持的问题代码")
        if detail_view == "country" and metric_status == "unavailable":
            has_metric_filters = any(filters.get(field) for field in METRIC_FILTER_FIELDS)
            if has_metric_filters or problems.intersection(METRIC_PROBLEMS):
                raise ValueError("国家经营指标暂不可用，当前不能使用指标型筛选")
        conditions = self._condition_parser(str(filters.get("detail_conditions") or ""))
        selections = (
            ("country_category", set(filters.get("country_categories") or [])),
            ("store", set(filters.get("stores") or [])),
            ("sales_role_code", set(filters.get("sales_roles") or [])),
            ("sales_trend_code", set(filters.get("sales_trends") or [])),
            ("daily_sales_band_code", set(filters.get("daily_sales_bands") or [])),
            ("margin_band_code", set(filters.get("margin_bands") or [])),
        )
        global_country_category = str(filters.get("country_category") or "all")
        global_store = str(filters.get("store") or "all")
        selected_countries = set(filters.get("countries") or [])

        def row_matches(row: dict[str, Any]) -> bool:
            if global_country_category != "all" and row.get("country_category") != global_country_category:
                return False
            if global_store != "all" and row.get("store") != global_store:
                return False
            if detail_view == "country" and selected_countries and row.get("country") not in selected_countries:
                return False
            if detail_view == "country" and ranking_bands and _ranking_band(row.get("ranking")) not in ranking_bands:
                return False
            if normalized and str(row.get("msku") or "").casefold() not in selected_mskus:
                return False
            if any(selected and row.get(field) not in selected for field, selected in selections):
                return False
            if conditions or role_reason_ids or current_stockout_only:
                labels_by_parent = {
                    int(parent): {int(child) for child in children}
                    for parent, children in (row.get("_by_parent") or {}).items()
                }
                for label in row.get("labels") or []:
                    labels_by_parent.setdefault(int(label["parent_id"]), set()).add(int(label["id"]))
                for diagnostic in row.get("role_diagnostics") or []:
                    labels_by_parent.setdefault(int(diagnostic["parent_id"]), set()).add(int(diagnostic["id"]))
                if any(not labels_by_parent.get(parent, set()).intersection(children) for parent, children in conditions.items()):
                    return False
                if role_reason_ids and not labels_by_parent.get(role_reason_parent, set()).intersection(role_reason_ids):
                    return False
                if current_stockout_only and CURRENT_STOCKOUT_CHILD_ID not in labels_by_parent.get(CURRENT_STOCKOUT_PARENT_ID, set()):
                    return False
            if stockout_before_role_period:
                matched_roles = [
                    role
                    for role in row.get("stockout_before_roles") or []
                    if str(role.get("period") or "") == stockout_before_role_period
                ]
                if stockout_before_role_ids and (
                    len(matched_roles) != 1
                    or int(matched_roles[0].get("id") or 0) not in stockout_before_role_ids
                ):
                    return False
            row_issues = _issues(row, metric_status)
            if problems and mode == "any" and not row_issues.intersection(problems):
                return False
            if problems and mode == "all" and not problems.issubset(row_issues):
                return False
            return True

        option_rows = list(rows)
        rows = [row for row in rows if row_matches(row)]
        business_keys = {
            (str(row.get("country_category") or ""), str(row.get("store") or ""), str(row.get("msku") or "").casefold())
            for row in rows
        }
        if detail_view == "country":
            business_count = len(business_keys)
            country_count = len(rows)
        else:
            business_count = len(rows)
            if country_rows:
                country_count = sum(
                    (
                        str(row.get("country_category") or ""), str(row.get("store") or ""),
                        str(row.get("msku") or "").casefold(),
                    ) in business_keys
                    for row in country_rows
                )
        counts = {
            "business_unit_count": business_count,
            "country_unit_count": country_count,
            "unique_msku_count": len({str(row.get("msku") or "").casefold() for row in rows}),
        }
        reverse = str(filters.get("sort_dir") or "desc").lower() != "asc"
        def sort_value(row: dict[str, Any]) -> Any:
            if sort_field == "problem_priority":
                issues = _issues(row, metric_status)
                return sum(code in issues for code in ISSUE_CODES)
            return row.get(sort_field)

        measured = [row for row in rows if sort_value(row) is not None]
        missing = [row for row in rows if sort_value(row) is None]
        measured.sort(key=lambda row: (sort_value(row), str(row.get("msku") or "")), reverse=reverse)
        missing.sort(key=lambda row: str(row.get("msku") or ""))
        rows = measured + missing
        total = len(rows)
        total_pages = max(1, math.ceil(total / page_size))
        page = min(max(1, int(filters.get("page") or 1)), total_pages)
        start = (page - 1) * page_size
        issue_labels = {
            "conflict": "标签冲突", "missing_metrics": "指标缺失", "zero_sales": "零销量",
            "negative_profit": "负毛利", "problem_role": "问题产品", "problem_product": "问题产品",
            "low_margin": "低毛利", "site_status_abnormal": "站点状态异常", "pricing_risk": "定价风险",
            "cross_country_inconsistent": "跨国标签不一致",
        }
        public_rows = []
        selected_rows = rows[start:start + page_size] if paginate else rows
        for row in selected_rows:
            codes = sorted(_issues(row, metric_status))
            row = dict(row)
            row["issue_codes"] = codes
            row["issue_labels"] = [issue_labels[code] for code in codes]
            if stockout_before_role_period:
                matched_roles = [
                    role
                    for role in row.get("stockout_before_roles") or []
                    if str(role.get("period") or "") == stockout_before_role_period
                ]
                if len(matched_roles) == 1:
                    row["stockout_before_role"] = matched_roles[0].get("label") or ""
                    row["stockout_before_role_id"] = int(matched_roles[0].get("id") or 0)
                    row["stockout_before_role_period"] = stockout_before_role_period
            public_rows.append({key: value for key, value in row.items() if not key.startswith("_")})
        rows = public_rows
        applied = {key: filters.get(key, default) for key, default in (
            ("country_categories", []), ("stores", []), ("countries", []), ("sales_roles", []),
            ("sales_trends", []), ("daily_sales_bands", []), ("margin_bands", []), ("ranking_bands", []), ("problems", []),
            ("role_reason_ids", []),
            ("current_stockout_only", False),
            ("stockout_before_role_period", ""),
            ("stockout_before_role_ids", []),
            ("detail_conditions", ""), ("problem_mode", "any"),
        )}
        applied.update({
            "detail_view": detail_view,
            "role_reason_ids": role_reason_ids,
            "identifiers": requested,
            "data_date": filters.get("data_date", ""),
            "metric_period": filters.get("metric_period", "30d"),
            "country_category": filters.get("country_category", "all"),
            "store": filters.get("store", "all"),
            "keyword": filters.get("keyword", ""),
            "conditions": filters.get("conditions", ""),
            "label_period": filters.get("label_period", "all"),
            "current_stockout_only": current_stockout_only,
            "stockout_before_role_period": stockout_before_role_period,
            "stockout_before_role_ids": sorted(stockout_before_role_ids),
        })
        return {
            "rows": rows, "counts": counts,
            "identifier_resolution": {
                "input_count": len(requested), "requested": requested,
                "matched_codes": matched, "matched": matched,
                "unmatched_codes": unmatched, "unmatched": unmatched,
            },
            "metric_status": metric_status, "warnings": warnings, "applied_filters": applied,
            "filter_options": {
                "countries": sorted({str(row.get("country") or "") for row in option_rows if row.get("country")}),
                "country_categories": sorted({str(row.get("country_category") or "") for row in option_rows if row.get("country_category")}),
                "stores": sorted({str(row.get("store") or "") for row in option_rows if row.get("store")}),
            },
            "page": page, "page_size": page_size, "total_pages": total_pages, "total": total,
        }


from .country_label_hub_data import country_label_hub_service
from .label_hub_data import label_hub_service

label_hub_detail_service = LabelHubDetailDataService(
    label_hub_service.get_business_detail_base_rows,
    country_row_provider=country_label_hub_service.get_country_detail_base_rows,
    country_summary_provider=country_label_hub_service.get_country_detail_count,
)
