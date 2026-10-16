"""Prove the one-off publication barrier against real concurrent MySQL writers."""
import os

import pymysql
import pytest

from test_label_local_store_mysql import local_store
from etl.dashboard_daily_update import connect_target

pytestmark = pytest.mark.skipif(
    os.getenv("LABEL_LOCAL_MYSQL_TEST") != "1", reason="isolated MySQL opt-in"
)


def publication_module(monkeypatch):
    from etl import label_local_store
    return label_local_store


def test_core_and_output_writers_stay_blocked_across_atomic_rename(local_store, monkeypatch):
    module = publication_module(monkeypatch)
    conn, live = local_store
    stage, backup = live + "_new", live + "_old"
    writer = connect_target()
    writer.autocommit(True)
    try:
        with conn.cursor() as q:
            for schema in (stage, backup):
                q.execute(f"create database `{schema}`")
            for schema, value in ((live,1),(stage,2)):
                q.execute(f"create table `{schema}`.output (n int) engine=innodb")
                q.execute(f"insert into `{schema}`.output values ({value})")
            q.execute(f"create table `{live}`.core (n int) engine=innodb")
        conn.commit()
        conn.autocommit(True)
        module.lock_publication_tables(conn, live, stage, ("output",), ((live,"core"),))
        with writer.cursor() as other:
            other.execute("set session lock_wait_timeout=1")
            with pytest.raises(pymysql.err.OperationalError) as error:
                other.execute(f"insert into `{live}`.core values (3)")
            assert error.value.args[0] == 1205
        with conn.cursor() as q:
            q.execute(f"rename table `{live}`.output to `{backup}`.output,"
                      f"`{stage}`.output to `{live}`.output")
            q.execute(f"select n from `{live}`.output")
            assert q.fetchone()["n"] == 2
        with writer.cursor() as other:
            for table in ("core", "output"):
                with pytest.raises(pymysql.err.OperationalError) as error:
                    other.execute(f"insert into `{live}`.`{table}` values (3)")
                assert error.value.args[0] == 1205
        with conn.cursor() as q:
            q.execute("unlock tables")
        with writer.cursor() as other:
            other.execute(f"insert into `{live}`.core values (3)")
            other.execute(f"select n from `{live}`.output")
            assert other.fetchone()["n"] == 2
            other.execute(f"select n from `{backup}`.output")
            assert other.fetchone()["n"] == 1
    finally:
        with conn.cursor() as q:
            q.execute("unlock tables")
            for schema in (stage,backup):
                assert schema.startswith("label_validation_")
                q.execute(f"drop database if exists `{schema}`")
        writer.close()


def test_invalid_json_null_and_corrupt_compressed_evidence_are_rejected(local_store, monkeypatch):
    module = publication_module(monkeypatch)
    conn, _ = local_store
    with conn.cursor() as q:
        q.execute(f"select sum({module.INVALID_EVIDENCE_SQL}) as invalid from ("
                  "select compress('{\"valid\":true,\"name\":\"库存\"}') as evidence_blob "
                  "union all select compress('invalid JSON') "
                  "union all select null union all select x'01020304') evidence")
        assert q.fetchone()["invalid"] == 3
