"""Complete the two published local days without rerunning the V47 baseline."""

from datetime import timedelta
import json
from uuid import uuid4

from etl.dashboard_daily_update import build_schema_config, connect_target
from etl.replenishment_update import apply_database_ini_env
from etl.label_local_generation import load_inputs, emit, LabelGenerationBusyError
from etl.label_lifecycle_completion import VERSION, complete_day, validate_extension_ids
from etl.label_operation_completion import complete_operations
from etl.label_receiving_status import apply_receiving_status, validate_extension_id
from etl.label_local_sql import RULE_VERSION, BASELINE_SHA256, checked_schema
from etl.label_local_store import (
    table,
    prepare_tables,
    restore_work,
    validate_day,
    archive_day,
    publish_days,
)


def publish_existing_coverage(*, schema=None, progress=emit):
    apply_database_ini_env()
    schema = checked_schema(schema or build_schema_config().target_schema)
    run_id = str(uuid4())
    stage = checked_schema("label_coverage_" + run_id.replace("-", "")[:16])
    conn = connect_target()
    locks = []
    registered = False
    try:
        with conn.cursor() as q:
            for target in sorted((schema, stage)):
                lock = f"label_local_generation:{target}"
                q.execute("select get_lock(%s,0) as acquired", (lock,))
                if q.fetchone()["acquired"] != 1:
                    raise LabelGenerationBusyError("another label writer is active")
                locks.append(lock)
            q.execute("set time_zone='+08:00'")
            q.execute(
                f"select * from {table(schema,'dashboard_label_local_publication')} where singleton=1"
            )
            publication = q.fetchone()
        if not publication or publication["source_mode"] != "local_generated":
            raise RuntimeError("coverage requires a committed local baseline")
        if publication["rule_version"] not in (RULE_VERSION, VERSION):
            raise RuntimeError("unsupported published rule version")
        inputs = load_inputs(conn, schema)
        if inputs["batch_id"] != publication["input_batch"]:
            raise RuntimeError("input batch changed since baseline publication")
        validate_extension_ids(conn, schema)
        validate_extension_id(conn, schema)
        dates = [
            publication["business_date"] - timedelta(days=1),
            publication["business_date"],
        ]
        with conn.cursor() as q:
            q.execute(
                f"select * from {table(schema,'dashboard_label_local_days')} where data_date in (%s,%s) order by data_date",
                dates,
            )
            original = q.fetchall()
        if len(original) != 2 or any(
            r["baseline_sha256"] != BASELINE_SHA256
            or r["input_hash"] != inputs["input_hash"]
            or r["rule_version"] != publication["rule_version"]
            for r in original
        ):
            raise RuntimeError(
                "published two-day archives disagree with accepted baseline"
            )
        with conn.cursor() as q:
            q.execute(
                f"create database `{stage}` character set utf8mb4 collate utf8mb4_0900_ai_ci"
            )
        prepare_tables(conn, stage)
        with conn.cursor() as q:
            q.execute(
                f"insert into {table(stage,'dashboard_label_local_history')} select * from {table(schema,'dashboard_label_local_history')} where data_date in (%s,%s)",
                dates,
            )
            q.execute(
                f"insert into {table(schema,'dashboard_label_local_runs')} (run_id,business_date,input_batch,status) values (%s,%s,%s,'running')",
                (run_id, dates[-1], inputs["batch_id"]),
            )
        conn.commit()
        registered = True
        progress(
            {
                "stage": "coverage_restore_start",
                "run_id": run_id,
                "work_schema": stage,
                "dates": dates,
            }
        )
        restore_work(conn, stage, dates)
        summaries = []
        for day in dates:
            progress({"stage": "coverage_day_start", "date": day})
            summary = complete_operations(conn, stage, day, input_schema=schema)
            summary.update(
                apply_receiving_status(conn, stage, day, input_schema=schema)
            )
            summary.update(complete_day(conn, stage, day, input_schema=schema))
            summary.update(
                validate_day(
                    conn, stage, day, input_schema=schema, complete_lifecycle=True
                )
            )
            archive_day(
                conn,
                stage,
                day,
                run_id,
                inputs,
                publication["history_start"],
                summary,
                rule_version=VERSION,
            )
            summaries.append({"date": day, **summary})
            progress(
                {
                    "stage": "coverage_day_validated",
                    "date": day,
                    **{k: v for k, v in summary.items() if k != "labels"},
                }
            )
        progress({"stage": "coverage_publish_start", "run_id": run_id})
        counts = publish_days(
            conn,
            schema,
            dates,
            run_id,
            inputs,
            publication["history_start"],
            input_schema=schema,
            complete_lifecycle=True,
            work_schema=stage,
            history_schema=stage,
        )
        result = {
            "status": "refreshed",
            "source_mode": "local_generated",
            "run_id": run_id,
            "rule_version": VERSION,
            "history_start": publication["history_start"],
            "work_schema": stage,
            "input_batch": inputs["batch_id"],
            "label_dates": dates,
            "days": summaries,
            **counts,
        }
        with conn.cursor() as q:
            q.execute(
                f"update {table(schema,'dashboard_label_local_runs')} set status='refreshed',finished_at=current_timestamp(6),summary_json=%s where run_id=%s",
                (json.dumps(result, ensure_ascii=False, default=str), run_id),
            )
        conn.commit()
        progress({"stage": "coverage_published", "run_id": run_id, **counts})
        return result
    except Exception as exc:
        conn.rollback()
        if registered:
            with conn.cursor() as q:
                q.execute(
                    f"update {table(schema,'dashboard_label_local_runs')} set status='failed',finished_at=current_timestamp(6),error_message=%s where run_id=%s",
                    (str(exc)[:8000], run_id),
                )
            conn.commit()
        raise
    finally:
        for lock in reversed(locks):
            with conn.cursor() as q:
                q.execute("select release_lock(%s)", (lock,))
        conn.close()


if __name__ == "__main__":
    emit(publish_existing_coverage())
