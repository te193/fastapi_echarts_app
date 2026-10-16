from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import sys

from etl.dashboard_daily_update import (
    DEFAULT_PERIOD_DAYS,
    DEFAULT_PRODUCT_REFRESH_DAYS,
    SchemaConfig,
    build_params as build_dashboard_params,
    build_schema_config,
    connect_source,
    render_sql,
)
from etl.replenishment_update import apply_database_ini_env


@dataclass(frozen=True)
class SourceReadinessCheck:
    name: str
    label: str
    required_date_key: str
    sql: str


@dataclass(frozen=True)
class SourceReadinessResult:
    name: str
    label: str
    required_date: object
    row_count: int


class PreflightFailure(RuntimeError):
    pass


SOURCE_READINESS_CHECKS = (
    SourceReadinessCheck(
        "product_performance_daily_source",
        "product performance",
        "biz_date",
        """
        /* product_performance_daily_source */
        select count(*) as row_count
        from dwd_datasync.lx_statistics_product_performance
        where start_date >= %(biz_date)s
          and start_date < %(next_product_end_date)s
          and seller_sku not like 'Amazon.Found%%'
        """,
    ),
    SourceReadinessCheck(
        "restock_snapshot_source",
        "restock snapshot",
        "snapshot_date",
        """
        /* restock_snapshot_source */
        select count(*) as row_count
        from etl_datasync.etl_dispose_lx_replenishment_suggest_restocking
        where create_time >= %(snapshot_date)s
          and create_time < %(next_snapshot_date)s
        """,
    ),
    SourceReadinessCheck(
        "inventory_snapshot_source",
        "inventory snapshot",
        "snapshot_date",
        """
        /* inventory_snapshot_source */
        select count(*) as row_count
        from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
        where create_time >= %(snapshot_date)s
          and create_time < %(next_snapshot_date)s
        """,
    ),
    SourceReadinessCheck(
        "listing_price_snapshot_source",
        "listing price snapshot",
        "snapshot_date",
        """
        /* listing_price_snapshot_source */
        select count(*) as row_count
        from dwd_datasync.lx_sales_mws_listing
        where create_time >= %(snapshot_date)s
          and create_time < %(next_snapshot_date)s
        """,
    ),
    SourceReadinessCheck(
        "limit_price_source_current",
        "limit price current source",
        "snapshot_date",
        """
        /* limit_price_source_current */
        select count(*) as row_count
        from temporary_dwd.`在库节点_输出定价表`
        where msku is not null
          and msku <> ''
          and 新店铺 is not null
          and 新店铺 <> ''
          and 国家 is not null
          and 国家 <> ''
          and 国家类别 is not null
          and 国家类别 <> ''
        """,
    ),
)


def _int_value(row: dict[str, object], key: str) -> int:
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _execute_count_check(
    source_conn,
    schemas: SchemaConfig,
    check: SourceReadinessCheck,
    params: dict[str, object],
) -> SourceReadinessResult:
    with source_conn.cursor() as cursor:
        cursor.execute(render_sql(check.sql, schemas), params)
        row = cursor.fetchone() or {}
    return SourceReadinessResult(
        name=check.name,
        label=check.label,
        required_date=params.get(check.required_date_key),
        row_count=_int_value(row, "row_count"),
    )


def check_source_readiness(
    source_conn,
    schemas: SchemaConfig,
    params: dict[str, object],
    checks: tuple[SourceReadinessCheck, ...] = SOURCE_READINESS_CHECKS,
) -> list[SourceReadinessResult]:
    results = [_execute_count_check(source_conn, schemas, check, params) for check in checks]
    missing = [result for result in results if result.row_count <= 0]

    for result in results:
        prefix = "[failed]" if result in missing else "[success]"
        print(
            f"{prefix} source_preflight {result.name}: "
            f"required_date={result.required_date} rows={result.row_count}"
        )

    if missing:
        detail = "; ".join(
            f"{result.name} required_date={result.required_date} rows={result.row_count}"
            for result in missing
        )
        raise PreflightFailure(
            "Remote source preflight failed: "
            f"biz_date={params['biz_date']} snapshot_date={params['snapshot_date']}; {detail}"
        )

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check remote source data before the daily dashboard ETL.")
    parser.add_argument("--biz-date", help="Business date to validate, format YYYY-MM-DD. Default: yesterday.")
    parser.add_argument("--snapshot-date", help="Snapshot date to validate, format YYYY-MM-DD. Default: today.")
    parser.add_argument("--period-start", help="Accepted for compatibility with dashboard ETL args.")
    parser.add_argument("--period-end", help="Accepted for compatibility with dashboard ETL args.")
    parser.add_argument("--period-days", type=int, default=DEFAULT_PERIOD_DAYS)
    parser.add_argument("--product-refresh-days", type=int, default=DEFAULT_PRODUCT_REFRESH_DAYS)
    parser.add_argument("--product-full-load", action="store_true")
    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"[info] source_preflight ignored_args={' '.join(unknown)}")
    return args


def print_plan(params: dict[str, object], schemas: SchemaConfig) -> None:
    print("Dashboard source preflight plan")
    print(f"  biz_date      : {params['biz_date']}")
    print(f"  snapshot_date : {params['snapshot_date']}")
    print(f"  product_load  : {params['product_start_date']} to {params['product_end_date']}")
    print(f"  etl_source    : {schemas.etl_source_schema}")
    print(f"  dwd_source    : {schemas.dwd_source_schema}")
    print(f"  pricing_source: {schemas.pricing_source_schema}")
    print(f"  checks        : {', '.join(check.name for check in SOURCE_READINESS_CHECKS)}")


def main() -> int:
    apply_database_ini_env()
    args = parse_args()
    params = build_dashboard_params(args)
    schemas = build_schema_config()
    print_plan(params, schemas)
    try:
        with connect_source() as source_conn:
            check_source_readiness(source_conn, schemas, params)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("[success] source_preflight: remote source data is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
