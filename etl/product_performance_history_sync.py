import argparse
from datetime import date, datetime, timedelta
from typing import Iterable

from etl.dashboard_daily_update import (
    PRODUCT_DAILY_COLUMNS,
    STEPS,
    SourceLoadStep,
    build_schema_config,
    connect_source,
    connect_target,
    ensure_tables,
    execute_source_load_step,
    log_task,
    render_sql,
)
from etl.replenishment_update import apply_database_ini_env, parse_day


DEFAULT_HISTORY_DAYS = 381
DEFAULT_ROLLING_DAYS = 50
DEFAULT_WATERMARK_OVERLAP_HOURS = 48
# The remote polling job currently rebuilds roughly half a month per run.
# Keep two overlapping polling runs in one source scan instead of scanning
# the unindexed varchar business-date column once per day.
DEFAULT_HISTORY_BATCH_DAYS = 31
TASK_NAME = "product_performance_history_sync"
BATCH_TASK_NAME = "product_performance_history_sync_batch"


def required_history_start(biz_date: date, history_days: int = DEFAULT_HISTORY_DAYS) -> date:
    return biz_date - timedelta(days=history_days - 1)


def coalesce_dates(days: Iterable[date]) -> list[tuple[date, date]]:
    ordered = sorted(set(days))
    if not ordered:
        return []

    ranges: list[tuple[date, date]] = []
    range_start = ordered[0]
    range_end = ordered[0]
    for day in ordered[1:]:
        if day == range_end + timedelta(days=1):
            range_end = day
            continue
        ranges.append((range_start, range_end))
        range_start = day
        range_end = day
    ranges.append((range_start, range_end))
    return ranges


def split_ranges(
    ranges: Iterable[tuple[date, date]],
    *,
    max_days: int = DEFAULT_HISTORY_BATCH_DAYS,
) -> list[tuple[date, date]]:
    if max_days < 1:
        raise ValueError("max_days must be at least 1")

    chunks: list[tuple[date, date]] = []
    for range_start, range_end in ranges:
        chunk_start = range_start
        while chunk_start <= range_end:
            chunk_end = min(range_end, chunk_start + timedelta(days=max_days - 1))
            chunks.append((chunk_start, chunk_end))
            chunk_start = chunk_end + timedelta(days=1)
    return chunks


def transaction_ranges(
    ranges: list[tuple[date, date]],
    *,
    first_run: bool,
    max_days: int,
) -> list[tuple[date, date]]:
    # The remote business date is a varchar without a useful range index.
    # A first backfill therefore uses one source scan; later corrections are
    # small and can be safely split into bounded transactions.
    if first_run:
        return ranges
    return split_ranges(ranges, max_days=max_days)


def changed_history_ranges(
    *,
    biz_date: date,
    history_days: int,
    rolling_days: int,
    last_success_at: datetime | None,
    changed_dates: Iterable[date],
) -> list[tuple[date, date]]:
    history_start = required_history_start(biz_date, history_days)
    rolling_start = biz_date - timedelta(days=rolling_days - 1)
    history_end = rolling_start - timedelta(days=1)
    if history_start > history_end:
        return []
    if last_success_at is None:
        return [(history_start, history_end)]

    eligible_dates = (
        day
        for day in changed_dates
        if history_start <= day <= history_end
    )
    return coalesce_dates(eligible_dates)


def latest_success_at(target_conn, schemas) -> datetime | None:
    with target_conn.cursor() as cursor:
        cursor.execute(
            render_sql(
                """
                select max(finished_at) as finished_at
                from etl_datasync.dashboard_etl_task_log
                where task_name = %(task_name)s
                  and status = 'success'
                """,
                schemas,
            ),
            {"task_name": TASK_NAME},
        )
        row = cursor.fetchone() or {}
    return row.get("finished_at")


def fetch_changed_dates(
    source_conn,
    schemas,
    *,
    history_start: date,
    history_end: date,
    changed_since: datetime,
) -> list[date]:
    with source_conn.cursor() as cursor:
        cursor.execute(
            render_sql(
                """
                select distinct date(start_date) as dt_date
                from dwd_datasync.lx_statistics_product_performance
                where create_time >= %(changed_since)s
                  and start_date >= %(history_start)s
                  and start_date < %(next_history_end)s
                order by dt_date
                """,
                schemas,
            ),
            {
                "changed_since": changed_since,
                "history_start": history_start,
                "next_history_end": history_end + timedelta(days=1),
            },
        )
        return [row["dt_date"] for row in cursor.fetchall() if row.get("dt_date")]


def range_params(
    *,
    biz_date: date,
    snapshot_date: date,
    range_start: date,
    range_end: date,
) -> dict[str, object]:
    return {
        "biz_date": biz_date,
        "snapshot_date": snapshot_date,
        "period_start": range_start,
        "period_end": range_end,
        "product_start_date": range_start,
        "product_end_date": range_end,
        "next_product_end_date": range_end + timedelta(days=1),
        "product_full_load": 0,
    }


def sync_history(
    *,
    biz_date: date,
    snapshot_date: date,
    history_days: int = DEFAULT_HISTORY_DAYS,
    rolling_days: int = DEFAULT_ROLLING_DAYS,
    watermark_overlap_hours: int = DEFAULT_WATERMARK_OVERLAP_HOURS,
    history_batch_days: int = DEFAULT_HISTORY_BATCH_DAYS,
    batch_size: int = 1000,
) -> tuple[int, list[tuple[date, date]]]:
    started_at = datetime.now()
    schemas = build_schema_config()
    product_step = STEPS["product_performance_daily"]
    history_step = SourceLoadStep(
        BATCH_TASK_NAME,
        product_step.delete_statement,
        product_step.source_select_statement,
        product_step.target_table,
        PRODUCT_DAILY_COLUMNS,
    )

    with connect_target() as target_conn, connect_source() as source_conn:
        ensure_tables(target_conn, schemas)
        last_success = latest_success_at(target_conn, schemas)
        history_start = required_history_start(biz_date, history_days)
        rolling_start = biz_date - timedelta(days=rolling_days - 1)
        history_end = rolling_start - timedelta(days=1)

        changed_dates: list[date] = []
        if last_success is not None and history_start <= history_end:
            changed_dates = fetch_changed_dates(
                source_conn,
                schemas,
                history_start=history_start,
                history_end=history_end,
                changed_since=last_success - timedelta(hours=watermark_overlap_hours),
            )

        ranges = transaction_ranges(
            changed_history_ranges(
                biz_date=biz_date,
                history_days=history_days,
                rolling_days=rolling_days,
                last_success_at=last_success,
                changed_dates=changed_dates,
            ),
            first_run=last_success is None,
            max_days=history_batch_days,
        )
        if not ranges:
            params = range_params(
                biz_date=biz_date,
                snapshot_date=snapshot_date,
                range_start=history_start,
                range_end=history_end,
            )
            log_task(
                target_conn,
                schemas,
                TASK_NAME,
                params,
                "success",
                0,
                datetime.now(),
            )
            return 0, []

        affected_rows = 0
        for range_start, range_end in ranges:
            params = range_params(
                biz_date=biz_date,
                snapshot_date=snapshot_date,
                range_start=range_start,
                range_end=range_end,
            )
            print(f"[info] {TASK_NAME}: refreshing {range_start} to {range_end}")
            execute_source_load_step(
                target_conn,
                source_conn,
                schemas,
                history_step,
                params,
                batch_size,
            )
            with target_conn.cursor() as cursor:
                cursor.execute(
                    render_sql(
                        """
                        select count(*) as row_count
                        from etl_datasync.dashboard_product_performance_daily
                        where dt_date between %(product_start_date)s and %(product_end_date)s
                        """,
                        schemas,
                    ),
                    params,
                )
                affected_rows += int((cursor.fetchone() or {}).get("row_count") or 0)
        completed_params = range_params(
            biz_date=biz_date,
            snapshot_date=snapshot_date,
            range_start=ranges[0][0],
            range_end=ranges[-1][1],
        )
        log_task(
            target_conn,
            schemas,
            TASK_NAME,
            completed_params,
            "success",
            affected_rows,
            started_at,
        )
        return affected_rows, ranges


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh historical product-performance dates corrected by the remote polling job."
    )
    parser.add_argument("--biz-date", help="Latest product business date. Default: yesterday.")
    parser.add_argument("--snapshot-date", help="ETL snapshot date. Default: today.")
    parser.add_argument("--product-history-days", type=int, default=DEFAULT_HISTORY_DAYS)
    parser.add_argument("--product-refresh-days", type=int, default=DEFAULT_ROLLING_DAYS)
    parser.add_argument(
        "--history-watermark-overlap-hours",
        type=int,
        default=DEFAULT_WATERMARK_OVERLAP_HOURS,
    )
    parser.add_argument("--history-batch-days", type=int, default=DEFAULT_HISTORY_BATCH_DAYS)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"[info] {TASK_NAME}: ignored_args={' '.join(unknown)}")

    if args.product_history_days < 1:
        raise SystemExit("product-history-days must be at least 1")
    if args.product_refresh_days < 1:
        raise SystemExit("product-refresh-days must be at least 1")
    if args.history_watermark_overlap_hours < 0:
        raise SystemExit("history-watermark-overlap-hours cannot be negative")
    if args.history_batch_days < 1:
        raise SystemExit("history-batch-days must be at least 1")
    if args.batch_size < 1:
        raise SystemExit("batch-size must be at least 1")

    apply_database_ini_env()
    biz_date = parse_day(args.biz_date) if args.biz_date else date.today() - timedelta(days=1)
    snapshot_date = parse_day(args.snapshot_date) if args.snapshot_date else date.today()
    print(
        f"Product history sync: biz_date={biz_date}, history_days={args.product_history_days}, "
        f"rolling_days={args.product_refresh_days}"
    )
    if args.dry_run:
        return

    affected_rows, ranges = sync_history(
        biz_date=biz_date,
        snapshot_date=snapshot_date,
        history_days=args.product_history_days,
        rolling_days=args.product_refresh_days,
        watermark_overlap_hours=args.history_watermark_overlap_hours,
        history_batch_days=args.history_batch_days,
        batch_size=args.batch_size,
    )
    print(f"[success] {TASK_NAME}: ranges={len(ranges)} rows={affected_rows}")


if __name__ == "__main__":
    main()
