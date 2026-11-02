"""Refresh late pricing sources after the early replenishment publication."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time as daytime
from pathlib import Path
import subprocess
import sys
import time

from etl.dashboard_daily_update import DEFAULT_STEP_ORDER, build_schema_config, clean_identifier, connect_source


_REPLENISHMENT_INPUTS = {
    "product_performance_daily", "restock_snapshot", "inventory_snapshot", "listing_price_snapshot",
}
EARLY_DASHBOARD_STEPS = ",".join(step for step in DEFAULT_STEP_ORDER if step in _REPLENISHMENT_INPUTS)
# Keep every step in its original dependency order. Independent summaries can
# run while upstream pricing is pending; all price consumers retain the same
# complete source barrier (including snapshot and queue) as the serial chain.
PRICING_STEPS = ",".join(step for step in DEFAULT_STEP_ORDER if step not in _REPLENISHMENT_INPUTS)
PRICING_PROCEDURES = (
    "proc_在库节点_输出定价表",
    "proc_在库节点_输出定价表_每日快照",
    "proc_lx_sale_adjust_price_queue",
)
_LATE_STEPS = PRICING_STEPS.split(',')
_LIMIT_INDEX = _LATE_STEPS.index('limit_price_snapshot')
PRICING_PHASES = (
    (','.join(_LATE_STEPS[:_LIMIT_INDEX]), ()),
    (','.join(_LATE_STEPS[_LIMIT_INDEX:]), PRICING_PROCEDURES),
)


def _snapshot_readiness_error(conn, schemas, snapshot_date: date):
    """Check the current snapshot producer's log and physical day counts."""
    schema = clean_identifier(schemas.pricing_source_schema, "temporary_dwd")
    with conn.cursor() as q:
        # Do not select only successful rows: a newer unfinished run must block.
        q.execute(
            f"SELECT `执行状态` AS status, `结束时间` AS end_time, "
            f"`源数据日期` AS source_date, `源表行数` AS source_rows, "
            f"`写入快照行数` AS written_rows, `快照校验行数` AS verified_rows "
            f"FROM `{schema}`.`在库节点_输出定价表_每日快照_执行日志` "
            f"ORDER BY `日志ID` DESC LIMIT 1", (),
        )
        row = q.fetchone()
        if (not row or row['status'] != 'success' or row['end_time'] is None
                or row['end_time'].date() != snapshot_date
                or row['source_date'] != snapshot_date
                or not row['source_rows'] or row['source_rows'] <= 0
                or row['source_rows'] != row['written_rows']
                or row['source_rows'] != row['verified_rows']):
            return 'latest dedicated snapshot log is missing, incomplete, or not for today'
    # Close/drain the source's streaming cursor before issuing another query.
    with conn.cursor() as q:
        q.execute(
            f"SELECT COUNT(*) AS source_rows, "
            f"COALESCE(SUM(`数据日期`=%s), 0) AS source_day_rows, "
            f"(SELECT COUNT(*) FROM `{schema}`.`在库节点_输出定价表_每日快照` "
            f"WHERE `数据日期`=%s) AS snapshot_rows "
            f"FROM `{schema}`.`在库节点_输出定价表`",
            (snapshot_date, snapshot_date),
        )
        counts = q.fetchone()
        if not counts or any(counts[key] != row['source_rows'] for key in (
                'source_rows', 'source_day_rows', 'snapshot_rows')):
            return f"snapshot physical counts do not match log rows={row['source_rows']}: {counts}"
    return None


def wait_for_pricing_sources(conn, schemas, snapshot_date: date, *,
                             procedures=PRICING_PROCEDURES,
                             now=datetime.now, sleep=time.sleep, emit=print) -> None:
    """Require current upstream logs and a verified snapshot for the target day."""
    if not procedures:
        raise ValueError('At least one pricing source procedure is required')
    schema = clean_identifier(schemas.etl_source_schema, "etl_datasync")
    snapshot_procedure = 'proc_在库节点_输出定价表_每日快照'
    legacy_procedures = tuple(name for name in procedures if name != snapshot_procedure)
    placeholders = ','.join('%s' for _ in legacy_procedures)
    deadline = datetime.combine(snapshot_date, daytime(9, 30))
    while True:
        rows = {}
        if legacy_procedures:
            with conn.cursor() as q:
                q.execute(
                    f"select l.proc_name,l.status,l.end_time from `{schema}`.etl_execution_log l "
                    f"join (select max(id) as id from `{schema}`.etl_execution_log "
                    f"where proc_name in ({placeholders}) group by proc_name) latest on latest.id=l.id",
                    legacy_procedures,
                )
                rows = {row['proc_name']: row for row in q.fetchall()}
        missing = [name for name in legacy_procedures if (
            name not in rows or rows[name]['status'] != 'success'
            or rows[name]['end_time'] is None
            or rows[name]['end_time'].date() != snapshot_date
        )]
        if snapshot_procedure in procedures:
            snapshot_error = _snapshot_readiness_error(conn, schemas, snapshot_date)
            if snapshot_error:
                missing.append(f'{snapshot_procedure} ({snapshot_error})')
        if not missing:
            emit(f"[success] pricing_sources_ready: snapshot_date={snapshot_date}")
            return
        current = now()
        if current >= deadline:
            raise RuntimeError(f"pricing sources not ready by {deadline}: {', '.join(missing)}")
        message = f"[info] waiting for today's pricing source tasks: {', '.join(missing)}; deadline={deadline}"
        emit(message)
        sleep(min(60, (deadline - current).total_seconds()))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-date')
    parser.add_argument('--dry-run', action='store_true')
    args, _ = parser.parse_known_args(argv)
    snapshot_date = date.fromisoformat(args.snapshot_date) if args.snapshot_date else date.today()
    # Lazy import avoids a cycle with the runner's step-profile import.
    from etl.daily_update_runner import load_dashboard_environment
    load_dashboard_environment(Path(__file__).resolve().parents[1])
    for steps, procedures in PRICING_PHASES:
        if procedures and not args.dry_run:
            conn = connect_source()
            try:
                wait_for_pricing_sources(conn, build_schema_config(), snapshot_date,
                                         procedures=procedures,
                                         emit=lambda message: print(message, flush=True))
            finally:
                conn.close()
        elif procedures:
            print(f"Late pricing plan: steps={steps}; wait for successful source tasks "
                  f"on {snapshot_date}: {', '.join(procedures)}; deadline09:30; "
                  "dry-run does not wait or write", flush=True)
        started = time.monotonic()
        exit_code = subprocess.call([
            sys.executable, '-u', '-m', 'etl.dashboard_daily_update', *argv, '--steps', steps,
        ])
        print(f"[info] pricing_phase: steps={steps}; seconds={time.monotonic() - started:.2f}; "
              f"exit_code={exit_code}", flush=True)
        if exit_code:
            return exit_code
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
