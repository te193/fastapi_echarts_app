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
# Keep all other analyses in their original dependency order, after replenishment.
# Presets read limit prices; alerts and opportunities read presets.
PRICING_STEPS = ",".join(step for step in DEFAULT_STEP_ORDER if step not in _REPLENISHMENT_INPUTS)
PRICING_PROCEDURES = (
    "proc_在库节点_输出定价表",
    "proc_在库节点_输出定价表_每日快照",
    "proc_lx_sale_adjust_price_queue",
)


def wait_for_pricing_sources(conn, schemas, snapshot_date: date, *,
                             now=datetime.now, sleep=time.sleep, emit=print) -> None:
    """Require each latest upstream execution to succeed on the snapshot day."""
    schema = clean_identifier(schemas.etl_source_schema, "etl_datasync")
    deadline = datetime.combine(snapshot_date, daytime(9, 30))
    while True:
        with conn.cursor() as q:
            q.execute(
                f"select l.proc_name,l.status,l.end_time from `{schema}`.etl_execution_log l "
                f"join (select max(id) as id from `{schema}`.etl_execution_log "
                "where proc_name in (%s,%s,%s) group by proc_name) latest on latest.id=l.id",
                PRICING_PROCEDURES,
            )
            rows = {row['proc_name']: row for row in q.fetchall()}
        missing = [name for name in PRICING_PROCEDURES if (
            name not in rows or rows[name]['status'] != 'success'
            or rows[name]['end_time'] is None
            or rows[name]['end_time'].date() != snapshot_date
        )]
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
    if not args.dry_run:
        conn = connect_source()
        try:
            wait_for_pricing_sources(conn, build_schema_config(), snapshot_date,
                                     emit=lambda message: print(message, flush=True))
        finally:
            conn.close()
    else:
        print(f"Late pricing plan: wait for successful source tasks on {snapshot_date}; deadline09:30; dry-run does not wait or write", flush=True)
    return subprocess.call([sys.executable, '-m', 'etl.dashboard_daily_update', *argv, '--steps', PRICING_STEPS])


if __name__ == '__main__':
    raise SystemExit(main())
