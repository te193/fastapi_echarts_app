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
DICTIONARY_FIELDS = (
    "label_id",
    "label_name",
    "sub_label_id",
    "sub_label_name",
    "status",
    "tagging_method",
)


def dictionary_contract() -> list[dict]:
    """Minimal rule identity metadata captured on 2026-10-08, no business facts."""
    return json.loads(DICTIONARY_PATH.read_text(encoding="utf-8"))


def validate_dictionary(rows: list[dict]) -> None:
    # The archived rules emit base labels 1..11 and station labels 13..21,23.
    parents = set(range(1, 12)) | set(range(13, 22)) | {23}
    expected = {
        r["sub_label_id"]: r for r in dictionary_contract() if r["label_id"] in parents
    }
    actual = {r["sub_label_id"]: r for r in rows}
    if len(actual) != len(rows):
        raise RuntimeError("V47 dictionary contract has duplicate child IDs")
    invalid = [
        key
        for key, row in expected.items()
        if key not in actual
        or any(actual[key].get(field) != row.get(field) for field in DICTIONARY_FIELDS)
    ]
    if invalid:
        raise RuntimeError(
            f"V47 dictionary contract missing or changed: {invalid}; review metadata before publication"
        )


def validate_history_coverage(
    start: date, available: set[date], end: date, *, require_baseline: bool = True
) -> None:
    if require_baseline and start != HISTORY_START:
        raise RuntimeError(
            "full local label history must start at 2026-01-01; a short bootstrap is preview-only"
        )
    if start > end:
        raise RuntimeError("local label history starts after the business date")
    required = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    missing = required - available
    if missing:
        raise RuntimeError(
            f"local history lacks business dates since {start}: {sorted(missing)[:10]}"
        )
    if (
        require_baseline
        and end >= CONTINUOUS_COUNT_START
        and CONTINUOUS_COUNT_START not in available
    ):
        raise RuntimeError("label 23 continuous-count history lacks 2026-09-03")


def validate_local_dictionary(conn, schema: str) -> None:
    from etl.label_local_store import table

    with conn.cursor() as cursor:
        cursor.execute(
            f"select {','.join(DICTIONARY_FIELDS)} from {table(schema,'dashboard_label_source_dictionary')}"
        )
        validate_dictionary(cursor.fetchall())


def validate_history_input_versions(
    conn, schema: str, input_schema: str, restored_dates: list[date]
) -> None:
    """Do not carry frozen facts or a comparison day across projection changes."""
    from etl.label_fba_source import NORMALIZATION_VERSION
    from etl.label_local_store import table

    if not restored_dates:
        return
    placeholders = ",".join(["%s"] * len(restored_dates))
    with conn.cursor() as cursor:
        cursor.execute(
            "select d.data_date, json_unquote(json_extract(b.contract_json,"
            "'$.normalization_version')) as normalization_version "
            f"from {table(schema,'dashboard_label_local_days')} d "
            f"left join {table(input_schema,'dashboard_label_local_source_batch')} b "
            "on b.batch_id=d.input_batch and b.local_name='dashboard_label_source_fba' "
            f"where d.data_date in ({placeholders})", restored_dates,
        )
        for row in cursor.fetchall():
            if row["normalization_version"] != NORMALIZATION_VERSION:
                raise RuntimeError(
                    f"archive {row['data_date']} uses incompatible FBA normalization; "
                    "replay affected history in a separate schema before publication"
                )


def validate_inventory_dates(conn, schema: str, dates: list[date]) -> None:
    from etl.label_local_store import table

    fba = table(schema, "dashboard_label_source_fba")
    raw_fba = table(schema, "dashboard_label_source_raw_fba")
    with conn.cursor() as cursor:
        # Check historical fallback rows as well as the requested business days:
        # V47 can use an item's older latest snapshot when today's is absent.
        cursor.execute(
            f"select create_time from {fba} "
            "where create_time<>cast(date(create_time) as datetime) limit 1"
        )
        if cursor.fetchone():
            raise RuntimeError("FBA daily normalization invalid; rebuild label inputs")
        cursor.execute(f"select date(max(create_time)) as d from {raw_fba}")
        clearance_date = cursor.fetchone()["d"]
        if clearance_date is None:
            raise RuntimeError("clearance raw FBA snapshot is empty or has no valid date")
        bounds = (clearance_date, clearance_date + timedelta(days=1))
        counts = []
        for source in (raw_fba, fba):
            cursor.execute(
                f"select count(*) as n from {source} "
                "where create_time>=%s and create_time<%s", bounds,
            )
            counts.append(int(cursor.fetchone()["n"]))
        # The label projection preserves one row per raw warehouse/SKU record.
        # Merely having a business-day snapshot cannot prove that latest-day
        # clearance mappings exist or that their row set is complete.
        if counts[0] != counts[1]:
            raise RuntimeError(
                f"clearance FBA mapping snapshot {clearance_date} row count mismatch: "
                f"raw={counts[0]}, projected={counts[1]}; refresh complete label inputs"
            )
    for name in ("dashboard_label_source_fba", "dashboard_label_source_restock"):
        with conn.cursor() as cursor:
            cursor.execute(
                f"select distinct date(create_time) as d from {table(schema,name)} where create_time>=%s and create_time<%s",
                (min(dates), max(dates) + timedelta(days=1)),
            )
            available = {row["d"] for row in cursor.fetchall()}
        missing = set(dates) - available
        if missing:
            raise RuntimeError(
                f"{name} has no inventory snapshot on {sorted(missing)[:10]}; missing data cannot mean zero inventory"
            )


def preflight_remote_history(
    source, target, schema: str, biz_date: date | None, bootstrap_start: date | None
) -> None:
    """Fail before a large transfer when a full replay is already impossible.

    Local validations still run against the final atomic input batch, so this
    cheap early check is not used as proof that the later snapshot is complete.
    """
    from etl.label_local_store import table

    with source.cursor() as q:
        q.execute(
            "select distinct date(start_date) as d from dwd_datasync.lx_statistics_product_performance"
        )
        available = {row["d"] for row in q.fetchall() if row["d"]}
    if not available:
        raise RuntimeError("product performance source is empty")
    end = biz_date or datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    if biz_date is None and max(available) != end:
        raise RuntimeError(
            f"product performance maximum {max(available)} must equal yesterday {end}"
        )
    # First publication deliberately starts with the latest two business days.
    # Business-source history remains intact for V47 rolling metric windows.
    start = bootstrap_start or end - timedelta(days=1)
    with target.cursor() as q:
        q.execute(
            "select count(*) as n from information_schema.tables where table_schema=%s and table_name='dashboard_label_local_days'",
            (schema,),
        )
        exists = q.fetchone()["n"]
        if exists:
            q.execute(
                f"select data_date,history_start from {table(schema,'dashboard_label_local_days')} order by data_date desc limit 1"
            )
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
    for reference in (
        "dwd_datasync.lx_storage_fba_warehouse_detail",
        "etl_datasync.etl_dispose_lx_replenishment_suggest_restocking",
    ):
        with source.cursor() as q:
            q.execute(
                f"select distinct date(create_time) as d from {reference} where create_time>=%s and create_time<%s",
                (first, end + timedelta(days=1)),
            )
            dates = {row["d"] for row in q.fetchall()}
        missing = required - dates
        if missing:
            raise RuntimeError(
                f"business source {reference} lacks {sorted(missing)[:10]}; repair historical inventory before publication"
            )
