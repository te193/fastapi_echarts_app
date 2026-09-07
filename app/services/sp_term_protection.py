from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from dateutil.parser import parse as parse_datetime


MARKETPLACE_COUNTRY_CODES = {
    "美国": "US", "加拿大": "CA", "墨西哥": "MX", "巴西": "BR",
    "英国": "UK", "德国": "DE", "法国": "FR", "意大利": "IT",
    "西班牙": "ES", "荷兰": "NL", "瑞典": "SE", "波兰": "PL",
    "比利时": "BE", "爱尔兰": "IE", "土耳其": "TR", "日本": "JP",
    "澳大利亚": "AU", "阿联酋": "AE", "沙特阿拉伯": "SA",
    "印度": "IN", "新加坡": "SG",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_match_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _text(value)).casefold().replace("_", " ")
    return " ".join(re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).split())


def strict_phrase_match(candidate: Any, text: Any) -> str | None:
    candidate_text = _text(candidate)
    phrase = normalize_match_text(candidate_text)
    target = normalize_match_text(text)
    if not phrase or not target:
        return None
    if len(phrase) <= 2:
        return candidate_text if phrase == target else None
    return candidate_text if f" {phrase} " in f" {target} " else None


def clean_category(value: Any) -> str:
    text = re.sub(r"^\s*\d+\s*-\s*", "", _text(value))
    return "" if text in {"", "[]", "{}", "null", "None"} else text


def parse_business_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not _text(value):
        return None
    try:
        return parse_datetime(_text(value)).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _json_values(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
    elif isinstance(value, (list, tuple, set)):
        parsed = value
    else:
        parsed = []
    return [_text(item) for item in parsed if _text(item)]


def _unique(values: Iterable[Any]) -> list[str]:
    result, seen = [], set()
    for value in values:
        text = _text(value)
        key = normalize_match_text(text)
        if text and key and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _base_store(value: Any) -> str:
    text = _text(value)
    return re.sub(r"-(?:eu-)?[a-z]{2}$", "", text, flags=re.IGNORECASE)


def build_protection_context_rows(
    listings: Iterable[Mapping[str, Any]],
    titles: Iterable[Mapping[str, Any]],
    store_brand_rows: Iterable[Mapping[str, Any]],
    *,
    title_run_id: Any = None,
) -> list[dict[str, Any]]:
    title_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in titles:
        title_map[(normalize_match_text(row.get("seller_name")), normalize_match_text(row.get("msku")))] = row

    store_brands: dict[str, list[str]] = defaultdict(list)
    for row in store_brand_rows:
        store_brands[normalize_match_text(row.get("store_name"))].append(_text(row.get("brand_name")))

    latest: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in listings:
        key = (
            _text(row.get("seller_name")).casefold(),
            MARKETPLACE_COUNTRY_CODES.get(_text(row.get("marketplace")), ""),
            _text(row.get("seller_sku")).casefold(),
        )
        if not all(key):
            continue
        previous = latest.get(key)
        rank = (row.get("create_time") or datetime.min, int(row.get("id") or 0))
        previous_rank = (
            (previous or {}).get("create_time") or datetime.min,
            int((previous or {}).get("id") or 0),
        )
        if previous is None or rank > previous_rank:
            latest[key] = row

    result = []
    for key, listing in latest.items():
        title = title_map.get(
            (normalize_match_text(key[0]), normalize_match_text(key[2])),
            {},
        )
        brands = _unique(store_brands.get(normalize_match_text(_base_store(listing.get("seller_name"))), []))
        product_brand = _text(listing.get("seller_brand"))
        brand_source = "listing.seller_brand" if product_brand else ""
        if not product_brand and len(brands) == 1:
            product_brand, brand_source = brands[0], "store_brand_relation"

        categories = _unique(
            clean_category(listing.get(field))
            for field in ("small_1", "small_2", "small_3", "small_4", "small_5")
        )
        categories = _unique([
            *categories,
            clean_category(title.get("leaf_category")),
            clean_category(title.get("category")),
        ])

        launch_date = None
        launch_source = ""
        for field in ("first_order_time", "on_sale_time", "open_date_display"):
            launch_date = parse_business_date(listing.get(field))
            if launch_date:
                launch_source = field
                break

        result.append({
            "seller_name": _text(listing.get("seller_name")),
            "country_code": MARKETPLACE_COUNTRY_CODES.get(_text(listing.get("marketplace")), ""),
            "msku": _text(listing.get("seller_sku")),
            "asin": _text(listing.get("asin")),
            "product_brand": product_brand,
            "brand_source": brand_source,
            "store_brands": brands,
            "leaf_categories": categories,
            "launch_date": launch_date,
            "launch_date_source": launch_source,
            "listing_source_updated_at": listing.get("create_time"),
            "title_run_id": title_run_id if title else None,
        })
    return result


def classify_term_protection(
    search_term: Any,
    context: Mapping[str, Any] | None,
    *,
    cutoff: date,
    new_product_days: int = 90,
) -> dict[str, Any]:
    if context is None:
        return {
            "term_protection_complete": False,
            "protection_missing_codes": ["term_protection_context_missing"],
            "is_brand_term": False,
            "is_core_category_term": False,
            "is_new_product_term": False,
            "protection_brand": None,
            "protection_category": None,
            "product_launch_date": None,
            "product_age_days": None,
        }

    product_brand = _text(context.get("product_brand"))
    store_brands = _json_values(context.get("store_brands_json", context.get("store_brands")))
    brands = _unique([product_brand, *store_brands]) if not product_brand else [product_brand]
    categories = _unique(_json_values(context.get("leaf_categories_json", context.get("leaf_categories"))))
    launch_date = parse_business_date(context.get("launch_date"))

    missing_codes = []
    if not brands:
        missing_codes.append("brand_context_missing")
    if not categories:
        missing_codes.append("category_context_missing")
    if not launch_date:
        missing_codes.append("launch_date_missing")
    elif launch_date > cutoff:
        missing_codes.append("launch_date_invalid")

    matched_brand = next((value for value in brands if strict_phrase_match(value, search_term)), None)
    matched_category = next(
        (
            value for value in categories
            if strict_phrase_match(value, search_term) or strict_phrase_match(search_term, value)
        ),
        None,
    )
    age_days = (cutoff - launch_date).days if launch_date and launch_date <= cutoff else None
    is_new = age_days is not None and age_days <= new_product_days
    return {
        "term_protection_complete": not missing_codes,
        "protection_missing_codes": missing_codes,
        "is_brand_term": matched_brand is not None,
        "is_core_category_term": matched_category is not None,
        "is_new_product_term": is_new,
        "protection_brand": matched_brand,
        "protection_category": matched_category,
        "product_launch_date": launch_date,
        "product_age_days": age_days,
    }
