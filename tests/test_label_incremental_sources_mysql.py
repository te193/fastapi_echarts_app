import json
from uuid import uuid4

import pytest

from test_label_local_store_mysql import local_store
from etl import label_incremental_sources as incremental
from etl import label_local_sources as sources
from etl.dashboard_daily_update import connect_target


@pytest.fixture
def inputs(local_store, monkeypatch):
    conn, schema = local_store
    specs = [
        sources.SourceSpec(schema, "remote_performance", "dashboard_label_source_performance"),
        sources.SourceSpec(schema, "remote_orders", "dashboard_label_source_orders"),
    ]
    monkeypatch.setattr(sources, "source_specs", lambda: tuple(specs))
    monkeypatch.setattr(incremental, "source_specs", lambda: tuple(specs))
    manifests = []
    with conn.cursor() as q:
        for spec in specs:
            q.execute(
                f"create table `{schema}`.`{spec.table}` "
                "(id bigint primary key,start_date varchar(100),"
                "volume decimal(18,4),create_time datetime) engine=innodb"
            )
            q.execute(
                f"insert into `{schema}`.`{spec.table}` values "
                "(1,'2026-01-01',10,'2026-01-02'),"
                "(50001,'2026-10-11',20,'2026-10-12'),"
                "(100001,'2026-10-12',30,'2026-10-13'),"
                "(150001,null,null,null)"
            )
            q.execute(
                f"create table `{schema}`.`{spec.local_name}` "
                f"like `{schema}`.`{spec.table}`"
            )
            q.execute(
                f"insert into `{schema}`.`{spec.local_name}` "
                f"select * from `{schema}`.`{spec.table}`"
            )
            manifests.append({
                "source": spec.reference, "local_name": spec.local_name,
                "rows": 4, "columns": ["id", "start_date", "volume", "create_time"],
                "sha256": "a" * 64, "raw_fba_date": "None",
            })
        marker = {
            "batch_id": str(uuid4()), "sources": manifests,
            "input_hash": incremental.manifest_hash(manifests),
        }
        q.execute(
            f"create table `{schema}`.dashboard_label_local_input "
            "(singleton tinyint primary key,manifest_json json not null) engine=innodb"
        )
        q.execute(
            f"insert into `{schema}`.dashboard_label_local_input values (1,%s)",
            (json.dumps(marker),),
        )
        q.execute(
            f"create table `{schema}`.dashboard_label_local_source_batch "
            "(batch_id varchar(36) not null,source_name varchar(180) not null,"
            "local_name varchar(64) not null,row_count bigint not null,"
            "content_sha256 char(64) not null,contract_json json not null,"
            "primary key(batch_id,local_name)) engine=innodb"
        )
    conn.commit()
    source = connect_target()
    try:
        yield source, conn, schema, specs
    finally:
        source.close()


def refresh(inputs):
    source, target, schema, _ = inputs
    return sources.sync_sources(
        source, target, schema, str(uuid4()), progress=lambda r: None
    )


def read_marker(target, schema):
    with target.cursor() as q:
        q.execute(f"select manifest_json from `{schema}`.dashboard_label_local_input")
        return json.loads(q.fetchone()["manifest_json"])


def test_existing_full_batch_is_adopted_without_copy_then_rerun_reuses_it(inputs):
    _, target, schema, _ = inputs
    before = read_marker(target, schema)
    first = refresh(inputs)
    assert first["sync_mode"] == "incremental"
    assert first["transferred_rows"] == 0
    assert first["reused_input_batch"] == before["batch_id"]
    assert len(first["sources"][0]["partitions"]) == 4
    assert refresh(inputs) == first


def test_incremental_corrects_old_values_deletes_partitions_and_adds_new_rows(inputs):
    _, target, schema, specs = inputs
    refresh(inputs)
    with target.cursor() as q:
        for spec in specs:
            q.execute(f"update `{schema}`.`{spec.table}` set volume=11 where id=1")
            q.execute(f"delete from `{schema}`.`{spec.table}` where id=50001")
            q.execute(
                f"insert into `{schema}`.`{spec.table}` "
                "values (200001,'2026-10-13',99,'2026-10-14')"
            )
    target.commit()
    result = refresh(inputs)
    assert result["transferred_rows"] == 4
    for spec in specs:
        with target.cursor() as q:
            q.execute(f"select * from `{schema}`.`{spec.table}` order by id")
            expected = q.fetchall()
            q.execute(f"select * from `{schema}`.`{spec.local_name}` order by id")
            assert q.fetchall() == expected
    assert refresh(inputs) == result


def test_partition_key_move_removes_old_copy(inputs):
    _, target, schema, specs = inputs
    refresh(inputs)
    with target.cursor() as q:
        q.execute(
            f"update `{schema}`.`{specs[0].table}` "
            "set start_date='2026-10-13' where id=1"
        )
    target.commit()
    result = refresh(inputs)
    assert result["transferred_rows"] == 1
    assert "2026-01-01" not in result["sources"][0]["partitions"]
    with target.cursor() as q:
        q.execute(
            f"select count(*) as n from `{schema}`.`{specs[0].local_name}` where id=1"
        )
        assert q.fetchone()["n"] == 1


@pytest.mark.parametrize("failure_point", ["source", "ledger", "marker"])
def test_mid_publication_failure_rolls_back_all_inputs_manifest_and_ledger(
    inputs, monkeypatch, failure_point
):
    _, target, schema, specs = inputs
    first = refresh(inputs)
    with target.cursor() as q:
        for spec in specs:
            q.execute(f"update `{schema}`.`{spec.table}` set volume=88 where id=1")
    target.commit()
    real_publish = incremental.publish_incremental

    class FailingCursor:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def execute(self, sql, params=None):
            source_failure = (
                sql.startswith("insert into") and "dashboard_label_source_orders`" in sql
            )
            ledger_failure = (
                sql.startswith("insert into") and "dashboard_label_local_source_batch" in sql
            )
            marker_failure = (
                sql.startswith("update") and "dashboard_label_local_input" in sql
            )
            if {
                "source": source_failure,
                "ledger": ledger_failure,
                "marker": marker_failure,
            }[failure_point]:
                raise RuntimeError("injected publication failure")
            return self.wrapped.execute(sql, params)

    class FailingConnection:
        def cursor(self):
            return FailingCursor(target.cursor())

        def __getattr__(self, name):
            return getattr(target, name)

    def fail(conn, *args):
        return real_publish(FailingConnection(), *args)

    monkeypatch.setattr(incremental, "publish_incremental", fail)
    with pytest.raises(RuntimeError, match="injected publication failure"):
        refresh(inputs)
    assert read_marker(target, schema) == first
    with target.cursor() as q:
        q.execute(f"select count(*) as n from `{schema}`.dashboard_label_local_source_batch")
        assert q.fetchone()["n"] == 2
        for spec in specs:
            q.execute(
                f"select volume from `{schema}`.`{spec.local_name}` where id=1"
            )
            assert q.fetchone()["volume"] == 10
    target.commit()
    monkeypatch.setattr(incremental, "publish_incremental", real_publish)
    assert refresh(inputs)["transferred_rows"] == 2


def test_remote_mutation_after_fingerprinting_is_seen_on_next_sync(inputs):
    source, target, schema, specs = inputs
    refresh(inputs)
    with target.cursor() as q:
        q.execute(f"update `{schema}`.`{specs[0].table}` set volume=20 where id=1")
    target.commit()
    writer = connect_target()
    mutated = False

    def progress(event):
        nonlocal mutated
        if event["stage"] == "source_partition_plan" and not mutated:
            with writer.cursor() as q:
                q.execute(
                    f"update `{schema}`.`{specs[0].table}` set volume=30 where id=1"
                )
            writer.commit()
            mutated = True

    try:
        result = sources.sync_sources(
            source, target, schema, str(uuid4()), progress=progress
        )
    finally:
        writer.close()
    assert mutated
    assert result["transferred_rows"] == 1
    with target.cursor() as q:
        q.execute(f"select volume from `{schema}`.`{specs[0].local_name}` where id=1")
        assert q.fetchone()["volume"] == 20
    target.commit()
    assert refresh(inputs)["transferred_rows"] == 1
    with target.cursor() as q:
        q.execute(f"select volume from `{schema}`.`{specs[0].local_name}` where id=1")
        assert q.fetchone()["volume"] == 30


def test_source_type_change_blocks_without_automatic_full_download(inputs):
    _, target, schema, specs = inputs
    first = refresh(inputs)
    with target.cursor() as q:
        q.execute(
            f"alter table `{schema}`.`{specs[0].table}` modify volume decimal(20,6)"
        )
    target.commit()
    with pytest.raises(RuntimeError, match="types/collations"):
        refresh(inputs)
    assert read_marker(target, schema) == first


def test_other_writer_is_rejected_before_any_staging(inputs):
    source, target, schema, _ = inputs
    other = connect_target()
    try:
        with target.cursor() as q:
            q.execute("select get_lock(%s,0)", (f"label_local_generation:{schema}",))
        try:
            with pytest.raises(RuntimeError, match="already running"):
                sources.sync_sources(source, other, schema, str(uuid4()))
        finally:
            with target.cursor() as q:
                q.execute("select release_lock(%s)", (f"label_local_generation:{schema}",))
    finally:
        other.close()


def test_same_count_local_corruption_is_repaired_from_unchanged_remote(inputs):
    _, target, schema, specs = inputs
    refresh(inputs)
    with target.cursor() as q:
        q.execute(
            f"update `{schema}`.`{specs[0].local_name}` set volume=999 where id=1"
        )
    target.commit()
    result = refresh(inputs)
    assert result["transferred_rows"] == 1
    with target.cursor() as q:
        q.execute(f"select volume from `{schema}`.`{specs[0].local_name}` where id=1")
        assert q.fetchone()["volume"] == 10


@pytest.mark.parametrize("table", [
    "dashboard_label_local_input", "dashboard_label_local_source_batch",
])
def test_nontransactional_control_tables_are_rejected_before_staging(inputs, table):
    _, target, schema, _ = inputs
    with target.cursor() as q:
        q.execute(f"alter table `{schema}`.`{table}` engine=MyISAM")
    target.commit()
    with pytest.raises(RuntimeError, match="InnoDB"):
        refresh(inputs)


def test_cleanup_failure_does_not_undo_or_misreport_published_inputs(inputs):
    source, target, schema, specs = inputs
    refresh(inputs)
    with target.cursor() as q:
        q.execute(f"update `{schema}`.`{specs[0].table}` set volume=88 where id=1")
    target.commit()

    class Cursor:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def execute(self, sql, params=None):
            if sql.startswith("drop table `") and "__delta" in sql:
                raise RuntimeError("injected cleanup failure")
            return self.wrapped.execute(sql, params)

    class Connection:
        def cursor(self):
            return Cursor(target.cursor())

        def __getattr__(self, name):
            return getattr(target, name)

    progress = []
    result = sources.sync_sources(
        source, Connection(), schema, str(uuid4()), progress=progress.append
    )
    assert result["transferred_rows"] == 1
    assert result == read_marker(target, schema)
    assert any(r["stage"] == "source_cleanup_warning" for r in progress)


def test_nested_sync_keeps_generators_original_lock(inputs):
    _, target, schema, _ = inputs
    lock = f"label_local_generation:{schema}"
    with target.cursor() as q:
        q.execute("select get_lock(%s,0) as acquired", (lock,))
        assert q.fetchone()["acquired"] == 1
    try:
        refresh(inputs)
        with target.cursor() as q:
            q.execute("select is_used_lock(%s)=connection_id() as owned", (lock,))
            assert q.fetchone()["owned"] == 1
    finally:
        with target.cursor() as q:
            q.execute("select release_lock(%s)", (lock,))


def test_fingerprints_preserve_duplicate_multiplicity_and_nulls(inputs):
    _, target, schema, specs = inputs
    with target.cursor() as q:
        q.execute(
            f"create table `{schema}`.duplicate_rows "
            "(start_date date,volume int) engine=innodb"
        )
        q.execute(
            f"insert into `{schema}`.duplicate_rows values "
            "('2026-10-12',1),('2026-10-12',1),(null,null)"
        )
    target.commit()
    sql = f"select * from `{schema}`.duplicate_rows"
    before = incremental.read_fingerprints(
        target, specs[0], ["start_date", "volume"], sql
    )
    assert before["2026-10-12"]["rows"] == 2
    assert before["__NULL__"]["rows"] == 1
    with target.cursor() as q:
        q.execute(
            f"delete from `{schema}`.duplicate_rows where start_date is not null limit 1"
        )
    target.commit()
    after = incremental.read_fingerprints(target, specs[0], ["start_date", "volume"], sql)
    assert int(before["2026-10-12"]["hash_1"]) == 2 * int(after["2026-10-12"]["hash_1"])
    assert incremental.changed_partitions(before, after) == ("2026-10-12",)


def test_fba_projection_duplicates_intraday_deletion_and_raw_day_rollover(
    inputs, monkeypatch
):
    from etl.label_fba_source import (
        NORMALIZATION_VERSION, fba_columns, fba_indexes,
    )
    source, target, schema, specs = inputs
    raw = sources.SourceSpec(schema, "remote_fba", "dashboard_label_source_raw_fba")
    historical = sources.SourceSpec(schema, "remote_fba", "dashboard_label_source_fba")
    specs.extend([raw, historical])
    real_projection = sources.fba_select_sql

    def projection(names):
        return real_projection(names).replace(
            "`dwd_datasync`.`lx_storage_fba_warehouse_detail`",
            f"`{schema}`.remote_fba",
        )

    monkeypatch.setattr(sources, "fba_select_sql", projection)
    with target.cursor() as q:
        q.execute(
            f"create table `{schema}`.remote_fba (id bigint primary key,"
            "create_time datetime,name varchar(255),seller_sku varchar(255),"
            "total int,afn_fulfillable_quantity int,stock_up_num int,"
            "inv_age_271_to_330_days int,inv_age_331_to_365_days int,"
            "inv_age_365_plus_days int) engine=innodb"
        )
        for key, stamp in [
            (1, "2026-10-12 10:00:00"), (2, "2026-10-12 10:00:00"),
            (3, "2026-10-13 10:00:00"), (4, "2026-10-13 12:00:00"),
            (5, None),
        ]:
            q.execute(
                f"insert into `{schema}`.remote_fba values "
                "(%s,%s,%s,'SKU',20,10,0,0,0,0)",
                (key, stamp, "SHOP-\u5fb7\u56fd"),
            )
    target.commit()
    marker = read_marker(target, schema)
    for spec in [raw, historical]:
        metadata, indexes = sources.read_metadata(source, spec)
        if spec is historical:
            columns, indexes = fba_columns(metadata), fba_indexes()
        else:
            columns = sources.project_columns(spec.reference, metadata, indexes)
        names = [c["column_name"] for c in columns]
        select, params = sources.source_select_sql(
            spec, names, raw_fba_date="2026-10-13"
        )
        with source.cursor() as q:
            q.execute(select, params or None)
            rows = q.fetchall()
        qualified = f"`{schema}`.`{spec.local_name}`"
        with target.cursor() as q:
            q.execute(sources.source_table_ddl(qualified, columns))
            q.executemany(
                f"insert into {qualified} values ({','.join('%s' for _ in names)})",
                [tuple(r[n] for n in names) for r in rows],
            )
            clauses = sources.source_index_clauses(columns, indexes)
            q.execute(f"alter table {qualified} {','.join(clauses)}")
        target.commit()
        marker["sources"].append({
            "source": spec.reference, "local_name": spec.local_name,
            "rows": len(rows), "columns": names, "sha256": "a" * 64,
            "normalization_version": NORMALIZATION_VERSION if spec is historical else None,
            "raw_fba_date": "2026-10-13",
        })
    marker["input_hash"] = incremental.manifest_hash(marker["sources"])
    with target.cursor() as q:
        q.execute(
            f"update `{schema}`.dashboard_label_local_input set manifest_json=%s",
            (json.dumps(marker),),
        )
    target.commit()
    assert refresh(inputs)["transferred_rows"] == 0
    with target.cursor() as q:
        q.execute(f"delete from `{schema}`.remote_fba where id in (2,4)")
        q.execute(
            f"insert into `{schema}`.remote_fba values "
            "(6,'2026-10-14 09:00:00',%s,'SKU',20,10,0,0,0,0)",
            ("SHOP-\u5fb7\u56fd",),
        )
    target.commit()
    result = refresh(inputs)
    assert result["transferred_rows"] == 4
    with target.cursor() as q:
        q.execute(f"select create_time from `{schema}`.`{raw.local_name}`")
        assert str(q.fetchone()["create_time"]) == "2026-10-14 09:00:00"
        q.execute(
            f"select create_time from `{schema}`.`{historical.local_name}` "
            "order by create_time"
        )
        assert [str(r["create_time"]) for r in q.fetchall()] == [
            "None", "2026-10-12 00:00:00",
            "2026-10-13 00:00:00", "2026-10-14 00:00:00",
        ]
    target.commit()
    with target.cursor() as q:
        q.execute(f"update `{schema}`.remote_fba set total=50 where id=6")
    target.commit()
    writer = connect_target()
    mutated = False

    def progress(event):
        nonlocal mutated
        if event["stage"] == "source_delta_copy" and event["source"] == raw.reference and not mutated:
            with writer.cursor() as q:
                q.execute(f"update `{schema}`.remote_fba set total=99 where id=6")
            writer.commit()
            mutated = True

    try:
        sources.sync_sources(
            source, target, schema, str(uuid4()), progress=progress
        )
    finally:
        writer.close()
    assert mutated
    for spec in [raw, historical]:
        with target.cursor() as q:
            q.execute(
                f"select total from `{schema}`.`{spec.local_name}` "
                "where create_time >= '2026-10-14'"
            )
            assert q.fetchall() == [{"total": 50}]
    target.commit()
    assert refresh(inputs)["transferred_rows"] == 2
    for spec in [raw, historical]:
        with target.cursor() as q:
            q.execute(
                f"select total from `{schema}`.`{spec.local_name}` "
                "where create_time >= '2026-10-14'"
            )
            assert q.fetchall() == [{"total": 99}]


def test_next_source_rebuilt_after_previous_source_does_not_use_old_snapshot(inputs):
    source, target, schema, specs = inputs
    writer = connect_target()
    rebuilt = False

    def progress(event):
        nonlocal rebuilt
        if event["stage"] == "source_incremental_complete" and not rebuilt:
            spec = specs[1]
            with writer.cursor() as q:
                q.execute(f"create table `{schema}`.replacement like `{schema}`.`{spec.table}`")
                q.execute(
                    f"insert into `{schema}`.replacement select * from `{schema}`.`{spec.table}`"
                )
                q.execute(f"update `{schema}`.replacement set volume=88 where id=1")
                q.execute(
                    f"rename table `{schema}`.`{spec.table}` to `{schema}`.retired, "
                    f"`{schema}`.replacement to `{schema}`.`{spec.table}`"
                )
            writer.commit()
            rebuilt = True

    try:
        result = sources.sync_sources(
            source, target, schema, str(uuid4()), progress=progress
        )
    finally:
        writer.close()
    assert rebuilt
    assert result["transferred_rows"] == 1
    assert read_marker(target, schema) == result
    with target.cursor() as q:
        q.execute(f"select volume from `{schema}`.`{specs[1].local_name}` where id=1")
        assert q.fetchone()["volume"] == 88


@pytest.mark.parametrize("failure_point", ["fingerprint", "partial_copy"])
def test_definition_change_retries_current_source_with_fresh_snapshot_and_staging(
    inputs, monkeypatch, failure_point
):
    import pymysql

    source, target, schema, specs = inputs
    refresh(inputs)
    with target.cursor() as q:
        q.execute(f"update `{schema}`.`{specs[1].table}` set volume=20 where id=1")
    target.commit()
    writer = connect_target()
    real_read = incremental.read_fingerprints
    real_stage = incremental.stage_delta
    failed = False

    def fail_once():
        nonlocal failed
        with writer.cursor() as q:
            q.execute(f"update `{schema}`.`{specs[1].table}` set volume=88 where id=1")
        writer.commit()
        failed = True
        raise pymysql.err.OperationalError(
            1412, "Table definition has changed, please retry transaction"
        )

    def read(conn, spec, *args, **kwargs):
        if (
            failure_point == "fingerprint" and conn is source
            and spec is specs[1] and not failed
        ):
            real_read(conn, spec, *args, **kwargs)
            fail_once()
        return real_read(conn, spec, *args, **kwargs)

    def stage(conn, dest, db, spec, *args, **kwargs):
        if failure_point == "partial_copy" and spec is specs[1] and not failed:
            real_stage(conn, dest, db, spec, *args, **kwargs)
            fail_once()
        return real_stage(conn, dest, db, spec, *args, **kwargs)

    monkeypatch.setattr(incremental, "read_fingerprints", read)
    monkeypatch.setattr(incremental, "stage_delta", stage)
    progress = []
    try:
        result = sources.sync_sources(
            source, target, schema, str(uuid4()), progress=progress.append
        )
    finally:
        writer.close()
    assert failed
    assert result["transferred_rows"] == 1
    assert read_marker(target, schema) == result
    with target.cursor() as q:
        q.execute(f"select volume from `{schema}`.`{specs[1].local_name}` where id=1")
        assert q.fetchall() == [{"volume": 88}]
    completed = [e["local_name"] for e in progress if e["stage"] == "source_incremental_complete"]
    assert completed.count(specs[0].local_name) == 1
    retries = [e for e in progress if e["stage"] == "source_transaction_retry"]
    assert len(retries) == 1
    assert retries[0]["source"] == specs[1].reference


@pytest.mark.parametrize("error_code,expected_attempts", [(1412, 3), (1142, 1)])
def test_source_failure_preserves_published_inputs_and_stops_at_retry_limit(
    inputs, monkeypatch, error_code, expected_attempts
):
    import pymysql

    source, target, schema, specs = inputs
    first = refresh(inputs)
    with target.cursor() as q:
        q.execute(f"update `{schema}`.`{specs[0].table}` set volume=88 where id=1")
    target.commit()
    real_read = incremental.read_fingerprints
    attempts = 0

    def read(conn, spec, *args, **kwargs):
        nonlocal attempts
        if conn is source and spec is specs[1]:
            attempts += 1
            raise pymysql.err.OperationalError(error_code, "injected source failure")
        return real_read(conn, spec, *args, **kwargs)

    monkeypatch.setattr(incremental, "read_fingerprints", read)
    with pytest.raises(pymysql.err.OperationalError) as error:
        refresh(inputs)
    assert error.value.args[0] == error_code
    assert attempts == expected_attempts
    assert read_marker(target, schema) == first
    with target.cursor() as q:
        q.execute(f"select volume from `{schema}`.`{specs[0].local_name}` where id=1")
        assert q.fetchone()["volume"] == 10
