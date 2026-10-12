from datetime import date
from uuid import uuid4
import pytest

from test_label_local_store_mysql import local_store, seed_lifecycle_completion
from etl.label_lifecycle_completion import complete_day, VERSION
from etl.label_local_sql import RULE_VERSION
from etl.label_local_store import (
    table,
    prepare_tables,
    validate_day,
    archive_day,
    publish_days,
)


@pytest.mark.parametrize("reject_publication", [False, True])
def test_staged_coverage_promotes_history_and_live_facts_together(
    local_store, reject_publication
):
    conn, schema = local_store
    stage = schema + "_stage"
    dates = [date(2026, 10, 6), date(2026, 10, 7)]
    original_run, new_run = str(uuid4()), str(uuid4())
    inputs = {"batch_id": str(uuid4()), "input_hash": "a" * 64}
    seed_lifecycle_completion(conn, schema)
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_local_work')} (data_date,country_category,country,store,msku,label_id,label_period,created_time,evidence_json) select '2026-10-06',country_category,country,store,msku,label_id,label_period,created_time,evidence_json from {table(schema,'dashboard_label_local_work')} where data_date='2026-10-07'"
        )
        q.execute(
            f"create database `{stage}` character set utf8mb4 collate utf8mb4_0900_ai_ci"
        )
    prepare_tables(conn, stage)
    try:
        for day in dates:
            archive_day(
                conn,
                schema,
                day,
                original_run,
                inputs,
                dates[0],
                validate_day(conn, schema, day),
            )
        original = publish_days(conn, schema, dates, original_run, inputs, dates[0])
        with conn.cursor() as q:
            q.execute(
                f"insert into {table(stage,'dashboard_label_local_work')} select * from {table(schema,'dashboard_label_local_work')}"
            )
        for day in dates:
            complete_day(conn, stage, day, input_schema=schema)
            archive_day(
                conn,
                stage,
                day,
                new_run,
                inputs,
                dates[0],
                validate_day(
                    conn, stage, day, input_schema=schema, complete_lifecycle=True
                ),
                rule_version=VERSION,
            )
        real_cursor = conn.cursor
        if reject_publication:

            class RejectMarker:
                def __init__(self):
                    self.inner = real_cursor()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.inner.close()

                def __getattr__(self, name):
                    return getattr(self.inner, name)

                def execute(self, sql, args=None):
                    if sql.startswith(
                        f"insert into {table(schema,'dashboard_label_local_publication')}"
                    ):
                        raise RuntimeError("injected failure before publication commit")
                    return self.inner.execute(sql, args)

            conn.cursor = RejectMarker
            with pytest.raises(RuntimeError, match="injected failure"):
                publish_days(
                    conn,
                    schema,
                    dates,
                    new_run,
                    inputs,
                    dates[0],
                    complete_lifecycle=True,
                    work_schema=stage,
                    history_schema=stage,
                )
            conn.cursor = real_cursor
        else:
            publish_days(
                conn,
                schema,
                dates,
                new_run,
                inputs,
                dates[0],
                complete_lifecycle=True,
                work_schema=stage,
                history_schema=stage,
            )
        with real_cursor() as q:
            q.execute(
                f"select rule_version,run_id from {table(schema,'dashboard_label_local_publication')}"
            )
            assert q.fetchone() == {
                "rule_version": RULE_VERSION if reject_publication else VERSION,
                "run_id": original_run if reject_publication else new_run,
            }
            q.execute(
                f"select distinct rule_version from {table(schema,'dashboard_label_local_days')}"
            )
            assert [r["rule_version"] for r in q.fetchall()] == [
                RULE_VERSION if reject_publication else VERSION
            ]
            q.execute(
                f"select count(*) as n from {table(schema,'dashboard_label_fact_snapshot')} where label_id in (206,207)"
            )
            assert q.fetchone()["n"] == (0 if reject_publication else 14)
            q.execute(
                f"select sum(row_count) as n from {table(schema,'dashboard_label_local_history')}"
            )
            archived_count = q.fetchone()["n"]
            q.execute(
                f"select count(*) as n from {table(schema,'dashboard_label_fact_snapshot')}"
            )
            live_count = q.fetchone()["n"]
            assert (
                live_count
                == archived_count
                == original["fact_rows"] + (0 if reject_publication else 14)
            )
    finally:
        conn.cursor = real_cursor if "real_cursor" in locals() else conn.cursor
        with conn.cursor() as q:
            q.execute(f"drop database if exists `{stage}`")
        conn.commit()
