"""Readiness contracts for the original V47 migration, before any publication."""

from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo


# V47's lifecycle/base performance explicitly starts on this date. Earlier
# business records are still needed as context for pre-stockout/ad windows.
HISTORY_START = date(2026, 1, 1)
CONTINUOUS_COUNT_START = date(2026, 9, 3)
DICTIONARY_PATH = Path(__file__).with_name("label_local_dictionary.json")
DICTIONARY_FIELDS = ("label_id", "label_name", "sub_label_id", "sub_label_name", "status", "tagging_method")


def dictionary_contract() -> list[dict]:
    """Minimal rule identity metadata captured on 2026-10-08, no business facts."""
    return json.loads(DICTIONARY_PATH.read_text(encoding="utf-8"))


def validate_dictionary(rows: list[dict]) -> None:
    # The archived rules emit base labels 1..11 and station labels 13..21,23.
    parents = set(range(1, 12)) | set(range(13, 22)) | {23}
    expected = {r["sub_label_id"]: r for r in dictionary_contract() if r["label_id"] in parents}
    actual = {r["sub_label_id"]: r for r in rows}
    if len(actual) != len(rows):
        raise RuntimeError("V47 dictionary contract has duplicate child IDs")
    invalid = [key for key, row in expected.items() if key not in actual or any(actual[key].get(field) != row.get(field) for field in DICTIONARY_FIELDS)]
    if invalid:
        raise RuntimeError(f"V47 dictionary contract missing or changed: {invalid}; review metadata before publication")


def validate_history_coverage(start: date, available: set[date], end: date, *, require_baseline: bool = True) -> None:
    if require_baseline and start != HISTORY_START:
        raise RuntimeError("full local label history must start at 2026-01-01; a short bootstrap is preview-only")
    if start > end:
        raise RuntimeError("local label history starts after the business date")
    required = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    missing = required - available
    if missing:
        raise RuntimeError(f"local history lacks business dates since {start}: {sorted(missing)[:10]}")
    if require_baseline and end >= CONTINUOUS_COUNT_START and CONTINUOUS_COUNT_START not in available:
        raise RuntimeError("label 23 continuous-count history lacks 2026-09-03")


def validate_local_dictionary(conn, schema: str) -> None:
    from etl.label_local_store import table
    with conn.cursor() as cursor:
        cursor.execute(f"select {','.join(DICTIONARY_FIELDS)} from {table(schema,'dashboard_label_source_dictionary')}")
        validate_dictionary(cursor.fetchall())


def validate_inventory_dates(conn, schema: str, dates: list[date]) -> None:
    from etl.label_local_store import table
    for name in ("dashboard_label_source_fba", "dashboard_label_source_restock"):
        with conn.cursor() as cursor:
            cursor.execute(f"select distinct date(create_time) as d from {table(schema,name)} where create_time>=%s and create_time<%s", (min(dates), max(dates) + timedelta(days=1)))
            available = {row["d"] for row in cursor.fetchall()}
        missing = set(dates) - available
        if missing:
            raise RuntimeError(f"{name} has no inventory snapshot on {sorted(missing)[:10]}; missing data cannot mean zero inventory")


def preflight_remote_history(source, target, schema: str, biz_date: date | None, bootstrap_start: date | None) -> None:
    """Fail before a large transfer when a full replay is already impossible.

    Local validations still run against the final atomic input batch, so this
    cheap early check is not used as proof that the later snapshot is complete.
    """
    from etl.label_local_store import table
    with source.cursor() as q:
        q.execute("select distinct date(start_date) as d from dwd_datasync.lx_statistics_product_performance")
        available = {row["d"] for row in q.fetchall() if row["d"]}
    if not available:
        raise RuntimeError("product performance source is empty")
    end = biz_date or datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    if biz_date is None and max(available) != end:
        raise RuntimeError(f"product performance maximum {max(available)} must equal yesterday {end}")
    # First publication deliberately starts with the latest two business days.
    # Business-source history remains intact for V47 rolling metric windows.
    start = bootstrap_start or end - timedelta(days=1)
    with target.cursor() as q:
        q.execute("select count(*) as n from information_schema.tables where table_schema=%s and table_name='dashboard_label_local_days'", (schema,))
        exists = q.fetchone()["n"]
        if exists:
            q.execute(f"select data_date,history_start from {table(schema,'dashboard_label_local_days')} order by data_date desc limit 1")
            previous = q.fetchone()
            if previous:
                start = previous["history_start"]
                first = min(end, previous["data_date"] + timedelta(days=1))
            else:
                first = start
        else:
            first = start
    validate_history_coverage(start, available, end, require_baseline=False)
    required = {first + timedelta(days=i) for i in range((end - first).days + 1)}
    for reference in ("dwd_datasync.lx_storage_fba_warehouse_detail", "etl_datasync.etl_dispose_lx_replenishment_suggest_restocking"):
        with source.cursor() as q:
            q.execute(f"select distinct date(create_time) as d from {reference} where create_time>=%s and create_time<%s", (first, end + timedelta(days=1)))
            dates = {row["d"] for row in q.fetchall()}
        missing = required - dates
        if missing:
            raise RuntimeError(f"business source {reference} lacks {sorted(missing)[:10]}; repair historical inventory before publication")
