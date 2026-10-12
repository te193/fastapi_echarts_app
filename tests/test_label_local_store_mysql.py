"""Opt-in transactional checks against an isolated local MySQL schema."""

from datetime import date
import json
import os
from uuid import uuid4

import pytest

from etl.label_local_store import (
    FACT_COLUMNS,
    archive_day,
    prepare_tables,
    publish_days,
    restore_work,
    table,
    validate_day,
)
from etl.label_rule_evidence_snapshot_update import detail_table_sql

pytestmark = pytest.mark.skipif(
    os.environ.get("LABEL_LOCAL_MYSQL_TEST") != "1",
    reason="isolated local MySQL integration is opt-in",
)


def seed_lifecycle_completion(conn, schema):
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_source_dictionary')} (label_id,sub_label_id,sub_label_name,create_time) values (2,201,'测款期',now()),(2,203,'成长期',now()),(3,301,'正常在售',now()),(3,304,'断货中',now()),(3,306,'停售',now()),(3,307,'待上架',now())"
        )
        q.execute(
            f"create table {table(schema,'dashboard_label_source_shipment')} (country varchar(64),seller varchar(128),msku varchar(255),receiving_time varchar(64))"
        )
        keys = [
            ("shop", name)
            for name in ("keep", "stop", "live", "oos", "pending", "unknown")
        ] + [("shopA", "shared"), ("shopB", "shared")]
        for store, sku in keys:
            q.execute(
                f"insert into {table(schema,'dashboard_label_local_work')} (data_date,country_category,store,msku,label_id,label_period,evidence_json) values ('2026-10-07','欧洲站',%s,%s,101,'30d',json_object('window',json_object('start','2026-09-08'),'metrics',json_object('period_sales_qty',1,'daily_sales',1,'sales_amount',1,'tag_gross_profit',1,'tag_margin_rate',1)))",
                (store, sku),
            )
        q.execute(
            f"insert into {table(schema,'dashboard_label_local_work')} (data_date,country_category,store,msku,label_id,label_period,evidence_json) values ('2026-10-07','欧洲站','shop','keep',203,'6m',json_object('original',true))"
        )
        for store, sku, status in [
            ("shop", "stop", 306),
            ("shop", "live", 301),
            ("shop", "oos", 304),
            ("shop", "pending", 307),
            ("shopA", "shared", 306),
            ("shopB", "shared", 301),
        ]:
            q.execute(
                f"insert into {table(schema,'dashboard_label_local_work')} (data_date,country_category,store,msku,label_id,label_period,evidence_json) values ('2026-10-07','欧洲站',%s,%s,%s,'current',json_object('operation',true))",
                (store, sku, status),
            )
    conn.commit()


def test_lifecycle_completion_preserves_phases_and_covers_each_role_key(local_store):
    from etl.label_lifecycle_completion import complete_day, validate_coverage

    conn, schema = local_store
    seed_lifecycle_completion(conn, schema)
    day = date(2026, 10, 7)
    complete_day(conn, schema, day)
    assert validate_coverage(conn, schema, day)["lifecycle_units"] == 8
    with conn.cursor() as q:
        q.execute(
            f"select store,msku,label_id,label_period,evidence_json from {table(schema,'dashboard_label_local_work')} where label_id between 201 and 207"
        )
        rows = {(r["store"], r["msku"]): r for r in q.fetchall()}
    assert len(rows) == 8 and rows[("shop", "keep")]["label_id"] == 203
    assert json.loads(rows[("shop", "keep")]["evidence_json"]) == {"original": True}
    assert (
        rows[("shop", "stop")]["label_id"]
        == rows[("shopA", "shared")]["label_id"]
        == 206
    )
    for key in [
        ("shop", "live"),
        ("shop", "oos"),
        ("shop", "pending"),
        ("shop", "unknown"),
        ("shopB", "shared"),
    ]:
        assert rows[key]["label_id"] == 207
        ev = json.loads(rows[key]["evidence_json"])
        assert (
            ev["first_receiving_date"] is None
            and ev["reason"] == "no_matching_shipment"
        )
    complete_day(conn, schema, day)
    assert validate_coverage(conn, schema, day)["lifecycle_units"] == 8
    with conn.cursor() as q:
        q.execute(
            f"update {table(schema,'dashboard_label_local_work')} set label_id=301 where msku='stop' and label_id=306"
        )
    complete_day(conn, schema, day)
    with conn.cursor() as q:
        q.execute(
            f"select label_id from {table(schema,'dashboard_label_local_work')} where msku='stop' and label_id in (206,207)"
        )
        assert q.fetchone()["label_id"] == 207
        # The next V47 run can supply a real phase; fallback then disappears.
        q.execute(
            f"insert into {table(schema,'dashboard_label_local_work')} (data_date,country_category,store,msku,label_id,label_period,evidence_json) values ('2026-10-07','欧洲站','shop','stop',202,'90d',json_object('original',true))"
        )
    complete_day(conn, schema, day)
    with conn.cursor() as q:
        q.execute(
            f"select label_id from {table(schema,'dashboard_label_local_work')} where msku='stop' and label_id between 201 and 207"
        )
        assert [r["label_id"] for r in q.fetchall()] == [202]


def test_lifecycle_completion_dictionary_collision_blocks_before_writes(local_store):
    from etl.label_lifecycle_completion import complete_day

    conn, schema = local_store
    seed_lifecycle_completion(conn, schema)
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_source_dictionary')} (label_id,sub_label_id,sub_label_name,create_time) values (9,206,'occupied',now())"
        )
    with pytest.raises(RuntimeError, match="occupied"):
        complete_day(conn, schema, date(2026, 10, 7))


def test_lifecycle_coverage_rejects_missing_and_multiple_classifications(local_store):
    from etl.label_lifecycle_completion import complete_day, validate_coverage

    conn, schema = local_store
    seed_lifecycle_completion(conn, schema)
    day = date(2026, 10, 7)
    with pytest.raises(RuntimeError, match="coverage"):
        validate_coverage(conn, schema, day)
    complete_day(conn, schema, day)
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_local_work')} (data_date,country_category,store,msku,label_id,label_period,evidence_json) values ('2026-10-07','欧洲站','shop','keep',201,'30d',json_object('bad',true))"
        )
    with pytest.raises(RuntimeError, match="coverage"):
        validate_coverage(conn, schema, day)


def test_retained_archive_survives_source_changes_but_rejects_work_changes(local_store):
    from etl.label_lifecycle_completion import complete_day, validate_coverage, VERSION
    from etl.label_local_store import validate_retained_archive

    conn, schema = local_store
    seed_lifecycle_completion(conn, schema)
    day = date(2026, 10, 7)
    complete_day(conn, schema, day)
    summary = validate_day(conn, schema, day, complete_lifecycle=True)
    archive_day(
        conn,
        schema,
        day,
        str(uuid4()),
        {"batch_id": str(uuid4()), "input_hash": "old-input"},
        day,
        summary,
        rule_version=VERSION,
    )
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_source_shipment')} values('德国','shop-DE','stop','2026-10-06')"
        )
    with pytest.raises(RuntimeError, match="same-batch"):
        validate_coverage(conn, schema, day)
    validate_retained_archive(conn, schema, schema, day, VERSION)
    validate_coverage(conn, schema, day, check_source_evidence=False)
    with conn.cursor() as q:
        q.execute(
            f"update {table(schema,'dashboard_label_local_work')} set evidence_json=json_set(evidence_json,'$.classification','wrong') where msku='stop' and label_id=206"
        )
    with pytest.raises(RuntimeError, match="differs"):
        validate_retained_archive(conn, schema, schema, day, VERSION)
    with pytest.raises(RuntimeError, match="same-batch"):
        validate_coverage(conn, schema, day, check_source_evidence=False)


def test_publish_retained_day_with_its_original_evidence(local_store):
    from etl.label_lifecycle_completion import complete_day, VERSION

    conn, schema = local_store
    seed_lifecycle_completion(conn, schema)
    day = date(2026, 10, 7)
    prior = date(2026, 10, 6)
    complete_day(conn, schema, day)
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_local_work')} ({','.join(FACT_COLUMNS)}) select '2026-10-06',country_category,country,store,msku,label_id,label_period,created_time,evidence_json from {table(schema,'dashboard_label_local_work')} where data_date='2026-10-07'"
        )
    complete_day(conn, schema, prior)
    old_inputs = {"batch_id": str(uuid4()), "input_hash": "old-source"}
    archive_day(
        conn,
        schema,
        prior,
        str(uuid4()),
        old_inputs,
        prior,
        validate_day(conn, schema, prior, complete_lifecycle=True),
        rule_version=VERSION,
    )
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_source_shipment')} values('德国','shop-DE','stop','2026-10-05')"
        )
    complete_day(conn, schema, day)
    publish_days(
        conn,
        schema,
        [day, prior],
        str(uuid4()),
        {"batch_id": str(uuid4())},
        prior,
        complete_lifecycle=True,
        retained_dates=(prior,),
    )
    with conn.cursor() as q:
        q.execute(
            f"select data_date,cast(uncompress(evidence_blob) as char) as evidence from {table(schema,'dashboard_label_fact_snapshot')} where msku='stop' and label_id=206 order by data_date"
        )
        old, new = q.fetchall()
        assert json.loads(old["evidence"])["candidate_first_receiving_date"] is None
        assert (
            json.loads(new["evidence"])["candidate_first_receiving_date"]
            == "2026-10-05"
        )


def test_lifecycle_extensions_publish_atomically_without_changing_source_dictionary(
    local_store,
):
    from etl.label_lifecycle_completion import complete_day, VERSION

    conn, schema = local_store
    seed_lifecycle_completion(conn, schema)
    day = date(2026, 10, 7)
    complete_day(conn, schema, day)
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_local_work')} (data_date,country_category,country,store,msku,label_id,label_period,created_time,evidence_json) select '2026-10-06',country_category,country,store,msku,label_id,label_period,created_time,evidence_json from {table(schema,'dashboard_label_local_work')} where data_date='2026-10-07'"
        )
    complete_day(conn, schema, date(2026, 10, 6))
    assert (
        validate_day(conn, schema, day, complete_lifecycle=True)[
            "lifecycle_unique_msku"
        ]
        == 7
    )
    dates = [day, date(2026, 10, 6)]
    run_id = str(uuid4())
    inputs = {"batch_id": str(uuid4())}
    publish_days(
        conn, schema, dates, run_id, inputs, dates[-1], complete_lifecycle=True
    )
    with conn.cursor() as q:
        q.execute(
            f"select sub_label_name from {table(schema,'dashboard_label_detail_snapshot')} where sub_label_id in (206,207) order by sub_label_id"
        )
        assert [r["sub_label_name"] for r in q.fetchall()] == [
            "归档产品",
            "生命周期待判定",
        ]
        q.execute(
            f"select count(*) as n from {table(schema,'dashboard_label_source_dictionary')} where sub_label_id in (206,207)"
        )
        assert q.fetchone()["n"] == 0
        q.execute(
            f"select rule_version,run_id from {table(schema,'dashboard_label_local_publication')}"
        )
        assert q.fetchone() == {"rule_version": VERSION, "run_id": run_id}
        q.execute(
            f"insert into {table(schema,'dashboard_label_source_dictionary')} (label_id,sub_label_id,sub_label_name,create_time) values (9,206,'collision',now())"
        )
    conn.commit()
    with pytest.raises(RuntimeError, match="occupied"):
        publish_days(
            conn,
            schema,
            dates,
            str(uuid4()),
            inputs,
            dates[-1],
            complete_lifecycle=True,
        )
    with conn.cursor() as q:
        q.execute(
            f"select run_id from {table(schema,'dashboard_label_local_publication')}"
        )
        assert q.fetchone()["run_id"] == run_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("label_id", 207),
        ("operation_status_id", 301),
        ("first_receiving_date", "2026-10-10"),
        ("candidate_first_receiving_date", "2026-10-10"),
        ("reason", "no_valid_receiving_date"),
        ("matched_rule", "wrong"),
        ("receiving_source", "wrong"),
    ],
)
def test_lifecycle_completion_evidence_must_match_label_and_status(
    local_store, field, value
):
    from etl.label_lifecycle_completion import complete_day, validate_coverage

    conn, schema = local_store
    seed_lifecycle_completion(conn, schema)
    day = date(2026, 10, 7)
    complete_day(conn, schema, day)
    with conn.cursor() as q:
        q.execute(
            f"update {table(schema,'dashboard_label_local_work')} set evidence_json=json_set(evidence_json,%s,%s) where label_id=206",
            ("$." + field, value),
        )
    with pytest.raises(RuntimeError, match="evidence"):
        validate_coverage(conn, schema, day)


def test_lifecycle_receiving_evidence_uses_retained_history_without_future_start(
    local_store,
):
    from etl.label_lifecycle_completion import complete_day

    conn, schema = local_store
    seed_lifecycle_completion(conn, schema)
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_source_shipment')} values ('德国','shop-德国','live','2024-01-01'),('德国','shop-德国','live','2026-01-01'),('德国','shop-德国','oos','2026-10-10'),('德国','shop-德国','pending',null)"
        )
    complete_day(conn, schema, date(2026, 10, 7))
    with conn.cursor() as q:
        q.execute(
            f"select msku,evidence_json from {table(schema,'dashboard_label_local_work')} where label_id=207 and msku in ('live','oos','pending')"
        )
        evidence = {r["msku"]: json.loads(r["evidence_json"]) for r in q.fetchall()}
    assert evidence["live"]["first_receiving_date"] == "2024-01-01"
    assert evidence["live"]["reason"] == "original_lifecycle_not_matched"
    assert evidence["oos"]["first_receiving_date"] is None
    assert evidence["oos"]["candidate_first_receiving_date"] == "2026-10-10"
    assert evidence["oos"]["reason"] == "receiving_after_label_date"
    assert evidence["pending"]["reason"] == "no_valid_receiving_date"


@pytest.fixture
def local_store():
    from etl.dashboard_daily_update import connect_target
    from etl.replenishment_update import apply_database_ini_env

    apply_database_ini_env()
    conn = connect_target()
    schema = "label_validation_" + uuid4().hex[:12]
    try:
        with conn.cursor() as q:
            q.execute(
                f"create database `{schema}` character set utf8mb4 collate utf8mb4_0900_ai_ci"
            )
        prepare_tables(conn, schema)
        with conn.cursor() as q:
            q.execute(
                detail_table_sql(
                    table(schema, "dashboard_label_source_dictionary"),
                    include_indexes=True,
                )
            )
            q.execute(
                f"insert into {table(schema,'dashboard_label_source_dictionary')} (label_id,sub_label_id,sub_label_name,create_time) values (1,101,'明星产品',now())"
            )
        conn.commit()
        yield conn, schema
    finally:
        # This exact random schema was created above; no configured application DB is dropped.
        with conn.cursor() as q:
            q.execute(f"drop database if exists `{schema}`")
        conn.close()


def seed(conn, schema):
    evidence = json.dumps(
        {
            "window": {"start": "2026-09-08"},
            "metrics": {
                "period_sales_qty": 60,
                "daily_sales": 2,
                "sales_amount": 600,
                "tag_gross_profit": 180,
                "tag_margin_rate": 30,
            },
        },
        ensure_ascii=False,
    )
    with conn.cursor() as q:
        for d in ("2026-10-06", "2026-10-07"):
            q.execute(
                f"insert into {table(schema,'dashboard_label_local_work')} (data_date,country_category,country,store,msku,label_id,label_period,evidence_json) values (%s,'欧洲站',null,'shop','SKU',101,'30d',%s)",
                (d, evidence),
            )
    conn.commit()


def test_history_restore_survives_partial_work_and_preserves_json(local_store):
    conn, schema = local_store
    seed(conn, schema)
    day = date(2026, 10, 7)
    summary = validate_day(conn, schema, day)
    archive_day(
        conn,
        schema,
        day,
        str(uuid4()),
        {"batch_id": str(uuid4()), "input_hash": "a" * 64},
        day,
        summary,
    )
    with conn.cursor() as q:
        q.execute(f"delete from {table(schema,'dashboard_label_local_work')}")
    conn.commit()
    restore_work(conn, schema, [day])
    with conn.cursor() as q:
        q.execute(
            f"select country,evidence_json from {table(schema,'dashboard_label_local_work')}"
        )
        rows = q.fetchall()
    assert len(rows) == 1
    assert rows[0]["country"] is None
    assert json.loads(rows[0]["evidence_json"])["metrics"]["daily_sales"] == 2


def test_original_v47_lifecycle_periods_are_valid(local_store):
    conn, schema = local_store
    seed(conn, schema)
    with conn.cursor() as q:
        q.execute(
            f"insert into {table(schema,'dashboard_label_source_dictionary')} (label_id,sub_label_id,sub_label_name,create_time) values (2,203,'成熟期',now()),(2,204,'衰退期',now())"
        )
        q.execute(
            f"insert into {table(schema,'dashboard_label_local_work')} (data_date,country_category,store,msku,label_id,label_period,evidence_json) values ('2026-10-07','欧洲站','shop','SKU',203,'6m',json_object('lifecycle','mature')),('2026-10-07','欧洲站','shop','SKU2',204,'long_term',json_object('lifecycle','decline'))"
        )
    conn.commit()
    assert validate_day(conn, schema, date(2026, 10, 7))["fact_rows"] == 3


def test_dwd_fba_label_projection_handles_shared_warehouse_and_special_msku(
    local_store,
):
    from etl.label_fba_source import RAW_COLUMNS, DERIVED_COLUMNS, fba_select_sql

    conn, schema = local_store
    raw = table(schema, "dashboard_label_test_raw_fba")
    cases = [
        ("HUAWTONG欧洲仓", "HW002a", "HUAWTONG", "HUAWTONG", "欧洲站", "HW002a"),
        (
            "QINGLEE-EU-UK英国仓",
            "QG001a",
            "QINGLEE-EU-UK",
            "QINGLEE",
            "英国站",
            "QG001a",
        ),
        ("paepee北美仓", "PP001a", "paepee", "paepee", "北美站", "PP001a"),
        ("shop-CA加拿大仓", "JKM-008a-2", "shop-CA", "shop", "北美站", "JKM-008a-2"),
        ("shop欧洲仓", "amzn.gr.HW002a-abcdefgh", "shop", "shop", "欧洲站", "HW002a"),
        ("shop欧洲仓", "KQ-UFY7-HWK2", "shop", "shop", "欧洲站", "KQ-UFY7-HWK2"),
    ]
    with conn.cursor() as q:
        q.execute(
            f"create table {raw} (create_time datetime,name varchar(255),seller_sku varchar(255),total int,afn_fulfillable_quantity int,stock_up_num int,inv_age_271_to_330_days int,inv_age_331_to_365_days int,inv_age_365_plus_days int)"
        )
        for warehouse, sku, *_ in cases:
            q.execute(
                f"insert into {raw} values ('2026-10-01 05:05:06',%s,%s,9,0,9,1,2,3)",
                (warehouse, sku),
            )
        sql = fba_select_sql(list(RAW_COLUMNS + DERIVED_COLUMNS)).replace(
            "`dwd_datasync`.`lx_storage_fba_warehouse_detail`", raw
        )
        q.execute(sql)
        rows = {r["seller_sku"]: r for r in q.fetchall()}
    for _, sku, store, prefix, region, normalized_sku in cases:
        row = rows[sku]
        assert (
            row["seller_name"],
            row["seller_name_new"],
            row["country_category"],
            row["seller_sku_adj"],
        ) == (store, prefix, region, normalized_sku)
        assert row["create_time"].hour == 0 and row["create_time"].date() == date(
            2026, 10, 1
        )
        assert (row["total"], row["afn_fulfillable_quantity"], row["stock_up_num"]) == (
            9,
            0,
            9,
        )


def test_dwd_inventory_refresh_keeps_other_inputs_and_two_projections_in_ledger(
    local_store, monkeypatch
):
    import hashlib
    from datetime import datetime
    from etl import label_local_sources as sources
    from etl.label_fba_source import RAW_COLUMNS, DERIVED_COLUMNS
    from etl.label_local_generation import load_inputs

    conn, schema = local_store
    metadata = [
        {
            "column_name": n,
            "column_type": (
                "datetime"
                if n == "create_time"
                else "varchar(255)" if n in ("name", "seller_sku") else "int"
            ),
            "is_nullable": "YES",
            "character_set_name": "utf8mb4" if n in ("name", "seller_sku") else None,
            "collation_name": (
                "utf8mb4_0900_ai_ci" if n in ("name", "seller_sku") else None
            ),
        }
        for n in RAW_COLUMNS
    ]
    previous_sources = [
        {
            "source": s.reference,
            "local_name": s.local_name,
            "rows": 1,
            "sha256": "a" * 64,
            "columns": [],
        }
        for s in sources.source_specs()
    ]
    for item in previous_sources:
        if item["local_name"] == "dashboard_label_source_fba":
            item["source"] = "etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail"
    previous = {
        "batch_id": str(uuid4()),
        "sources": previous_sources,
        "input_hash": hashlib.sha256(
            json.dumps(previous_sources, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    }
    marker = table(schema, "dashboard_label_local_input")
    with conn.cursor() as q:
        q.execute(
            f"create table {marker} (singleton tinyint primary key,manifest_json json)"
        )
        q.execute(f"insert into {marker} values (1,%s)", (json.dumps(previous),))
        q.execute(
            f"create table {table(schema,'dashboard_label_local_source_batch')} (batch_id varchar(36),source_name varchar(180),local_name varchar(64),row_count bigint,content_sha256 char(64),contract_json json,primary key(batch_id,source_name))"
        )
    conn.commit()
    values = dict(
        zip(
            RAW_COLUMNS + DERIVED_COLUMNS,
            (
                datetime(2026, 10, 1),
                "shop欧洲仓",
                "SKU",
                9,
                0,
                9,
                1,
                2,
                3,
                "SKU",
                "shop",
                "shop",
                "欧洲站",
            ),
        )
    )

    class Reader:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=None):
            if sql == "set session net_write_timeout=600":
                return
            assert "dwd_datasync" in sql and "etl_dispose" not in sql
            self.pending = [values]

        def fetchone(self):
            return {"snapshot_date": date(2026, 10, 1)}

        def fetchmany(self, n):
            result, self.pending = self.pending, []
            return result

    class Remote:
        def cursor(self):
            return Reader()

        def autocommit(self, *args):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(sources, "read_metadata", lambda c, spec: (metadata, []))
    result = sources.sync_sources(
        Remote(),
        conn,
        schema,
        str(uuid4()),
        refresh_inventory_only=True,
        progress=lambda r: None,
    )
    assert (
        result["reused_input_batch"] == previous["batch_id"]
        and load_inputs(conn, schema) == result
    )
    assert [
        r for r in result["sources"] if r["local_name"] != "dashboard_label_source_fba"
    ] == [
        r for r in previous_sources if r["local_name"] != "dashboard_label_source_fba"
    ]
    with conn.cursor() as q:
        q.execute(
            f"select count(*) as n from {table(schema,'dashboard_label_source_dictionary')}"
        )
        assert q.fetchone()["n"] == 1
        q.execute(
            f"select count(*) as n from {table(schema,'dashboard_label_local_source_batch')} where batch_id=%s",
            (result["batch_id"],),
        )
        assert q.fetchone()["n"] == 14


def test_publication_failure_rolls_back_facts_dictionary_audit_and_marker(local_store):
    conn, schema = local_store
    seed(conn, schema)
    dates = [date(2026, 10, 7), date(2026, 10, 6)]
    inputs = {"batch_id": str(uuid4())}
    first_run = str(uuid4())
    assert (
        publish_days(conn, schema, dates, first_run, inputs, dates[-1])["fact_rows"]
        == 2
    )
    with conn.cursor() as q:
        q.execute(
            f"select tag_gross_margin,computed_sub_label_id,remote_sub_label_id,evidence_status from {table(schema,'dashboard_label_rule_evidence_snapshot')}"
        )
        audit = q.fetchone()
        assert float(audit["tag_gross_margin"]) == 0.3
        assert (
            audit["computed_sub_label_id"] == 101
            and audit["remote_sub_label_id"] is None
        )
        assert audit["evidence_status"] == "generated"
        q.execute(
            f"update {table(schema,'dashboard_label_local_work')} set evidence_json=json_object('broken',true)"
        )
        q.execute(
            f"update {table(schema,'dashboard_label_source_dictionary')} set sub_label_name='BROKEN'"
        )
    conn.commit()
    with pytest.raises(Exception):
        publish_days(conn, schema, dates, str(uuid4()), inputs, dates[-1])
    with conn.cursor() as q:
        q.execute(
            f"select cast(uncompress(evidence_blob) as char) as evidence from {table(schema,'dashboard_label_fact_snapshot')}"
        )
        assert all("metrics" in json.loads(row["evidence"]) for row in q.fetchall())
        q.execute(
            f"select run_id from {table(schema,'dashboard_label_local_publication')}"
        )
        assert q.fetchone()["run_id"] == first_run
        q.execute(
            f"select sub_label_name from {table(schema,'dashboard_label_detail_snapshot')}"
        )
        assert q.fetchone()["sub_label_name"] == "明星产品"
        q.execute(
            f"select count(*) as n from {table(schema,'dashboard_label_rule_evidence_snapshot')}"
        )
        assert q.fetchone()["n"] == 2
