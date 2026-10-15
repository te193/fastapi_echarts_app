"""Generate labels AND evidence in local MySQL using the archived V47 rules.

Remote connections only supply business inputs. No remote label result, JSON,
or historical label seed is read by this entry point.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
from time import monotonic
from uuid import uuid4
from zoneinfo import ZoneInfo

from etl.dashboard_daily_update import build_schema_config, connect_source, connect_target
from etl.replenishment_update import apply_database_ini_env
from etl.label_local_sql import BASELINE_SHA256, PROCEDURE_NAME, RULE_VERSION, checked_schema, compile_procedure
from etl.label_operation_completion import complete_operations
from etl.label_receiving_status import apply_receiving_status
from etl.label_local_sources import source_specs, sync_sources
from etl.label_local_contracts import HISTORY_START, preflight_remote_history, validate_history_coverage, validate_inventory_dates, validate_local_dictionary
from etl.label_lifecycle_completion import VERSION as LIFECYCLE_VERSION,complete_day,validate_extension_ids
from etl.label_local_store import (
    archive_day, decode_history_chunk, encode_history_chunk, prepare_tables,
    publish_days, restore_work, table, validate_day,
)


class LabelGenerationBusyError(RuntimeError):
    """Another daily/manual generator owns the local publication lock."""


def calculation_dates(end: date, start: date, last_success: date | None) -> list[date]:
    if start > end:
        raise ValueError("history start is later than business date")
    if last_success and end < last_success:
        raise ValueError("requested date is earlier than local history; rebuild in a separate schema")
    first = max(start, last_success + timedelta(days=1)) if last_success else start
    if last_success == end:
        first = end
    return [first + timedelta(days=i) for i in range((end - first).days + 1)]


def emit(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=False, default=str), flush=True)


def load_inputs(conn, schema: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(f"select manifest_json from {table(schema,'dashboard_label_local_input')} where singleton=1")
        row = cursor.fetchone()
    if not row:
        raise RuntimeError("no complete local input batch; sync business sources first")
    inputs = json.loads(row["manifest_json"])
    expected = {(s.reference, s.local_name) for s in source_specs()}
    actual = {(s["source"], s["local_name"]) for s in inputs["sources"]}
    if actual != expected or len(inputs["sources"]) != len(expected):
        raise RuntimeError("local input manifest has an incomplete source contract")
    digest = hashlib.sha256(json.dumps(inputs["sources"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if digest != inputs["input_hash"]:
        raise RuntimeError("local input manifest checksum mismatch")
    return inputs


def assert_separate_servers(source, target) -> None:
    ids = []
    for connection in (source, target):
        with connection.cursor() as cursor:
            cursor.execute("select @@server_uuid as server_uuid")
            ids.append(cursor.fetchone()["server_uuid"])
    if not all(ids) or ids[0] == ids[1]:
        raise RuntimeError("local label target must be a different server from remote business sources")


def lifecycle_policy(explicit: bool | None, published_version: str | None) -> bool:
    """Daily and manual refreshes retain the locally published coverage policy."""
    return published_version == LIFECYCLE_VERSION if explicit is None else explicit


def run_generation(biz_date: date | None = None, bootstrap_start: date | None = None,
                   *, publish: bool = True, sync: bool = True, schema: str | None = None,
                   input_schema: str | None = None, complete_lifecycle: bool | None = None,
                   expected_input_hash: str | None = None, progress=emit) -> dict:
    apply_database_ini_env()
    schema = checked_schema(schema or build_schema_config().target_schema)
    input_schema = checked_schema(input_schema or schema)
    conn = connect_target()
    source = None
    locks = sorted({f"label_local_generation:{schema}", f"label_local_generation:{input_schema}"})
    acquired_locks = []
    run_id = str(uuid4())
    started = monotonic()
    prepared = False
    rule_version = RULE_VERSION
    try:
        with conn.cursor() as cursor:
            for lock in locks:
                cursor.execute("select get_lock(%s,0) as acquired", (lock,))
                if cursor.fetchone()["acquired"] != 1:
                    raise LabelGenerationBusyError("local label generation is already running")
                acquired_locks.append(lock)
            cursor.execute("set time_zone='+08:00'")
        if sync:
            source = connect_source()
            assert_separate_servers(source, conn)
            if publish:
                preflight_remote_history(source, conn, schema, biz_date, bootstrap_start)
            inputs = sync_sources(source, conn, input_schema, str(uuid4()), progress=progress)
            source.close()
            source = None
        else:
            inputs = load_inputs(conn, input_schema)
        if expected_input_hash is not None and inputs['input_hash'] != expected_input_hash:
            raise RuntimeError('input batch changed after baseline acceptance; publication blocked')
        prepare_tables(conn, schema)
        prepared = True
        with conn.cursor() as cursor:
            cursor.execute(f"select rule_version from {table(schema,'dashboard_label_local_publication')} where singleton=1")
            publication = cursor.fetchone()
            complete_lifecycle = lifecycle_policy(complete_lifecycle, publication['rule_version'] if publication else None)
            rule_version = LIFECYCLE_VERSION if complete_lifecycle else RULE_VERSION
            cursor.execute(f"select distinct date(start_date) as d from {table(input_schema,'dashboard_label_source_performance')} order by d")
            available = {row["d"] for row in cursor.fetchall() if row["d"]}
            if not available:
                raise RuntimeError("local product performance has no business dates")
            if biz_date is None:
                yesterday = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
                if max(available) != yesterday:
                    raise RuntimeError(f"product performance maximum {max(available)} must equal yesterday {yesterday}")
                biz_date = yesterday
            cursor.execute(f"select * from {table(schema,'dashboard_label_local_days')} order by data_date desc limit 1")
            previous = cursor.fetchone()
            if previous and (previous["baseline_sha256"] != BASELINE_SHA256 or previous["rule_version"] != rule_version):
                raise RuntimeError("local history uses a different rule version; use a separate schema to rebuild")
            history_start = previous["history_start"] if previous else (bootstrap_start or biz_date - timedelta(days=1))
            if previous and bootstrap_start and bootstrap_start != history_start:
                raise ValueError("bootstrap start differs from existing local history")
            dates = calculation_dates(biz_date, history_start, previous["data_date"] if previous else None)
            missing = set(dates) - available
            if missing:
                raise RuntimeError(f"missing product performance dates in replay: {sorted(missing)[:10]}")
            # The user chose a two-day initial publication. Retain its real
            # start date; never describe it as a full historical replay.
            if publish:
                validate_history_coverage(history_start, available, biz_date, require_baseline=False)
            cursor.execute(f"insert into {table(schema,'dashboard_label_local_runs')} (run_id,business_date,input_batch,status) values (%s,%s,%s,'running')", (run_id, biz_date, inputs["batch_id"]))
        conn.commit()
        validate_local_dictionary(conn, input_schema)
        if complete_lifecycle:
            validate_extension_ids(conn,input_schema)
        validate_inventory_dates(conn, input_schema, dates)
        with conn.cursor() as cursor:
            cursor.execute(f"drop procedure if exists {table(schema,PROCEDURE_NAME)}")
            cursor.execute(compile_procedure(schema, input_schema=input_schema))
        conn.commit()
        progress({"stage": "replay_start", "run_id": run_id, "history_start": history_start, "days": len(dates), "business_date": biz_date})
        restore_work(conn, schema, [dates[0] - timedelta(days=1), dates[0]])
        last_summary = {}
        for day in dates:
            day_start = monotonic()
            progress({"stage": "calculate_start", "date": day})
            with conn.cursor() as cursor:
                cursor.execute(f"call {table(schema,PROCEDURE_NAME)}(%s)", (day,))
                while cursor.nextset():
                    pass
            complete_operations(conn,schema,day,input_schema=input_schema)
            apply_receiving_status(conn,schema,day,input_schema=input_schema)
            if complete_lifecycle:
                complete_day(conn,schema,day,input_schema=input_schema)
            last_summary = validate_day(conn, schema, day, input_schema=input_schema,complete_lifecycle=complete_lifecycle)
            archive_day(conn, schema, day, run_id, inputs, history_start, last_summary,rule_version=rule_version)
            progress({"stage": "calculate_complete", "date": day, "seconds": round(monotonic() - day_start, 1), **last_summary})
        with conn.cursor() as cursor:
            cursor.execute(f"select data_date from {table(schema,'dashboard_label_local_days')} where data_date<=%s order by data_date desc limit 2", (biz_date,))
            published_dates = [row["data_date"] for row in cursor.fetchall()]
        summary = {
            "status": "generated", "source_mode": "local_generated", "run_id": run_id,
            "business_date": biz_date.isoformat(), "latest_date": biz_date.isoformat(),
            "label_dates": [d.isoformat() for d in published_dates],
            "rule_version": rule_version, "baseline_sha256": BASELINE_SHA256,
            "input_batch": inputs["batch_id"], "input_hash": inputs["input_hash"],
            "history_start": history_start.isoformat(), "history_semantics": "recomputed_with_current_business_sources",
            "input_history_start": min(available).isoformat(),
            "history_coverage": "baseline_replayed" if history_start == HISTORY_START else "recent_periods_only",
            "historical_carry_complete": history_start == HISTORY_START,
            "historical_point_in_time": False,
            "periods": ["7d", "14d", "30d", "90d"],
            **last_summary,
        }
        if publish:
            if len(published_dates) != 2 or published_dates[0] - published_dates[1] != timedelta(days=1):
                raise RuntimeError("publication requires two consecutive locally generated dates")
            restore_work(conn, schema, published_dates)
            summary.update(publish_days(conn, schema, published_dates, run_id, inputs, history_start, input_schema=input_schema,complete_lifecycle=complete_lifecycle,
                                       retained_dates=tuple(d for d in published_dates if d not in dates)))
            summary["status"] = "refreshed"
        summary["seconds"] = round(monotonic() - started, 1)
        with conn.cursor() as cursor:
            cursor.execute(f"update {table(schema,'dashboard_label_local_runs')} set status=%s,finished_at=current_timestamp(6),summary_json=%s where run_id=%s", (summary["status"], json.dumps(summary, ensure_ascii=False, default=str), run_id))
        conn.commit()
        return summary
    except Exception as exc:
        conn.rollback()
        if prepared:
            with conn.cursor() as cursor:
                cursor.execute(f"update {table(schema,'dashboard_label_local_runs')} set status='failed',finished_at=current_timestamp(6),error_message=%s where run_id=%s", (str(exc)[:8000], run_id))
            conn.commit()
        raise
    finally:
        if source is not None:
            source.close()
        for lock in reversed(acquired_locks):
            with conn.cursor() as cursor:
                cursor.execute("select release_lock(%s)", (lock,))
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--bootstrap-start", type=date.fromisoformat)
    parser.add_argument("--reuse-inputs", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--baseline-only", action="store_true",help="preview original V47 without lifecycle completion")
    parser.add_argument("--complete-lifecycle", action="store_true",help="explicitly enable the deferred lifecycle extension")
    parser.add_argument("--schema", help="dedicated local schema for an isolated replay")
    parser.add_argument("--input-schema", help="local business inputs to reuse, guarded by the same writer lock")
    args = parser.parse_args()
    if args.baseline_only and not args.no_publish:
        parser.error('--baseline-only requires --no-publish')
    if args.baseline_only and args.complete_lifecycle:
        parser.error('--baseline-only cannot be combined with --complete-lifecycle')
    policy = False if args.baseline_only else (True if args.complete_lifecycle else None)
    emit(run_generation(args.date, args.bootstrap_start, publish=not args.no_publish, sync=not args.reuse_inputs, schema=args.schema, input_schema=args.input_schema,complete_lifecycle=policy))


if __name__ == "__main__":
    main()
