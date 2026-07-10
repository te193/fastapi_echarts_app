"""Generate the returned product tags dashboard static JSON file."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from etl.dashboard_daily_update import connect_target


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "app" / "static" / "returned-product-tags" / "returned-product-tags-data.json"

SUMMARY_SQL = """
SELECT
  run_id,
  generated_at AS source_generated_at,
  latest_inventory_date,
  window_180_start,
  window_14_start,
  window_21_start,
  total_msku,
  total_asin,
  current_fba_available,
  current_fba_inbound,
  current_stock_up_qty,
  sales_qty_14d,
  sales_qty_21d,
  exited_return_msku,
  return_closure_rate
FROM opt_db.lyt_returned_product_tags_latest_run;
"""

SUMMARY_BY_STATUS_SQL = """
SELECT
  status,
  label,
  msku_count,
  asin_count,
  current_fba_available,
  current_fba_inbound,
  current_stock_up_qty,
  current_fba_available_purchase_cost,
  current_fba_inbound_purchase_cost,
  sales_qty_14d,
  sales_qty_21d,
  avg_longest_stockout_days,
  max_longest_stockout_days
FROM opt_db.lyt_returned_product_tags_latest_status_summary
ORDER BY FIELD(
  status,
  'returned_not_arrived',
  'returned_receiving',
  'returned_observation_period',
  'returned_operation_period',
  'returned_with_sales',
  'exited_return'
);
"""

COHORT_BY_DAY_SQL = """
SELECT
  day_no AS day,
  observable_msku,
  with_sales_msku,
  cumulative_with_sales_msku,
  order_rate,
  cumulative_order_rate,
  sales_qty,
  cumulative_sales_qty,
  avg_sales_qty,
  fba_available,
  day0_fba_available,
  stock_consumption_rate,
  no_sales_yet_msku
FROM opt_db.lyt_returned_product_tags_latest_cohort_day
ORDER BY day_no;
"""

COHORT_ITEMS_SQL = """
SELECT
  status,
  label,
  msku,
  sku,
  asin,
  product_name,
  seller_name_new,
  return_day0,
  observed_days,
  day0_fba_available,
  day14_cumulative_sales,
  day14_stock_consumption_rate,
  day21_cumulative_sales,
  day21_stock_consumption_rate
FROM opt_db.lyt_returned_product_tags_latest_cohort_item
ORDER BY day21_cumulative_sales DESC, day0_fba_available DESC;
"""

DETAIL_SQL = """
SELECT
  status,
  label,
  msku,
  sku,
  asin,
  product_name,
  seller_name_new,
  current_fba_available,
  current_fba_inbound,
  current_stock_up_qty,
  current_fba_available_purchase_cost,
  current_fba_inbound_purchase_cost,
  stockout_days_180d,
  stock_days_180d,
  max_consecutive_stockout_days_180d,
  sales_qty_14d,
  sales_qty_21d
FROM opt_db.lyt_returned_product_tags_latest_detail
ORDER BY
  FIELD(
    status,
    'returned_not_arrived',
    'returned_receiving',
    'returned_observation_period',
    'returned_operation_period',
    'returned_with_sales',
    'exited_return'
  ),
  sales_qty_21d DESC,
  current_fba_available DESC,
  current_fba_inbound DESC;
"""


def json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: json_value(value) for key, value in row.items()}


def normalize_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_row(row) for row in rows]


def build_cohort_summary(cohort_items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cohort_msku": len(cohort_items),
        "complete_21d_msku": sum(1 for row in cohort_items if int(row.get("observed_days") or 0) >= 21),
        "partial_msku": sum(1 for row in cohort_items if int(row.get("observed_days") or 0) < 21),
        "day0_to_day21_window": "observable sample by return day",
    }


def build_payload(
    *,
    summary_row: dict[str, Any],
    summary_by_status: list[dict[str, Any]],
    cohort_by_day: list[dict[str, Any]],
    cohort_items: list[dict[str, Any]],
    detail: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now()
    normalized_summary = normalize_row(summary_row)
    normalized_cohort_items = normalize_rows(cohort_items)

    scope_keys = {
        "run_id",
        "source_generated_at",
        "latest_inventory_date",
        "window_180_start",
        "window_14_start",
        "window_21_start",
    }
    scope = {key: normalized_summary[key] for key in scope_keys if key in normalized_summary}
    scope["definition"] = {
        "long_stockout_days": 14,
        "min_current_total_inventory": 10,
        "min_operable_fba_available": 10,
        "sales_verify_days": 21,
        "return_day0": "连续缺货不少于 14 天后，FBA 可售库存首次恢复到 >=10 的日期",
        "observation_period": "D0-D3",
        "operation_period": "D4-D21",
    }
    summary = {key: value for key, value in normalized_summary.items() if key not in scope_keys}

    return {
        "generated_at": generated_at.isoformat(),
        "scope": scope,
        "summary": summary,
        "summary_by_status": normalize_rows(summary_by_status),
        "cohort_summary": build_cohort_summary(normalized_cohort_items),
        "cohort_by_day": normalize_rows(cohort_by_day),
        "cohort_items": normalized_cohort_items,
        "detail": normalize_rows(detail),
    }


def fetch_all(conn, sql: str) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(sql)
        return list(cursor.fetchall())


def fetch_payload(conn) -> dict[str, Any]:
    summary_rows = fetch_all(conn, SUMMARY_SQL)
    if not summary_rows:
        raise RuntimeError("No rows returned from opt_db.lyt_returned_product_tags_latest_run")

    return build_payload(
        summary_row=summary_rows[0],
        summary_by_status=fetch_all(conn, SUMMARY_BY_STATUS_SQL),
        cohort_by_day=fetch_all(conn, COHORT_BY_DAY_SQL),
        cohort_items=fetch_all(conn, COHORT_ITEMS_SQL),
        detail=fetch_all(conn, DETAIL_SQL),
    )


def write_payload(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(output_path)


def generate(output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    with connect_target() as conn:
        payload = fetch_payload(conn)
    write_payload(output_path, payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output JSON path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = generate(args.output)
    summary = payload.get("summary", {})
    print(
        "[success] returned_product_tags: "
        f"output={args.output} total_msku={summary.get('total_msku', 0)} "
        f"detail_rows={len(payload.get('detail', []))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
