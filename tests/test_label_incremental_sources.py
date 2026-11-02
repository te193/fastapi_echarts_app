import inspect
from datetime import date

import pytest

from etl import label_local_sources as sources


def incremental_api():
    from importlib import import_module, util

    assert util.find_spec("etl.label_incremental_sources") is not None, (
        "incremental source loader is missing"
    )
    return import_module("etl.label_incremental_sources")


def test_full_rebuild_is_explicit_not_the_daily_default():
    parameters = inspect.signature(sources.sync_sources).parameters
    assert "force_full" in parameters
    assert parameters["force_full"].default is False


def test_large_sources_use_business_dates_and_order_id_buckets():
    api = incremental_api()
    for name, column in [
        ("performance", "start_date"),
        ("fba", "create_time"),
        ("restock", "create_time"),
        ("inventory", "\u6570\u636e\u65e5\u671f"),
        ("price_history", "\u6570\u636e\u65e5\u671f"),
    ]:
        assert api.partition_expression(
            f"dashboard_label_source_{name}"
        ) == f"coalesce(cast(date(`{column}`) as char), '__NULL__')"
    assert "floor(`id` / 50000)" in api.partition_expression(
        "dashboard_label_source_orders"
    )


def test_changed_partition_detection_includes_old_corrections_and_deletions():
    api = incremental_api()
    old = {
        "2026-01-01": {"rows": 2, "hash_1": "100", "hash_2": "200"},
        "2026-01-02": {"rows": 1, "hash_1": "300", "hash_2": "400"},
    }
    new = {
        "2026-01-01": {"rows": 2, "hash_1": "101", "hash_2": "200"},
        "2026-10-13": {"rows": 1, "hash_1": "500", "hash_2": "600"},
    }
    assert api.changed_partitions(old, new) == (
        "2026-01-01", "2026-01-02", "2026-10-13"
    )
    assert api.changed_partitions(new, new) == ()


def test_partition_hash_preserves_nulls_and_avoids_ambiguous_concatenation():
    api = incremental_api()
    spec = next(s for s in sources.source_specs() if s.local_name.endswith("_orders"))
    sql = api.fingerprint_sql(spec, ["id", "create_time", "msku"], "select 1")
    assert "json_array(`id`, `create_time`, `msku`)" in sql
    assert "sha2(" in sql and "256" in sql
    assert "group by partition_key" in sql
    assert "count(*)" in sql and "hash_1" in sql and "hash_2" in sql


def test_partition_filter_is_parameterized_and_handles_null_dates():
    api = incremental_api()
    spec = next(s for s in sources.source_specs()
                if s.local_name == "dashboard_label_source_fba")
    sql, params = api.delta_select_sql(
        spec,
        ["create_time", "seller_sku"],
        ("2026-10-13", "__NULL__"),
        raw_fba_date=date(2026, 10, 13),
    )
    assert "2026-10-13" not in sql and "__NULL__" in sql
    assert params == ("2026-10-13", "__NULL__")
    assert "partition_key" not in sql
    assert " in (%s,%s)" in sql


def test_missing_partition_rows_block_before_live_changes():
    api = incremental_api()
    expected = {"2026-10-13": {"rows": 10, "hash_1": "123", "hash_2": "456"}}
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        api.validate_delta(expected, {}, ("2026-10-13",))
    api.validate_delta(expected, expected, ("2026-10-13",))
    api.validate_delta({}, {}, ("removed",))


def test_manifest_contract_rejects_corrupt_batches_and_changed_columns():
    api = incremental_api()
    with pytest.raises(RuntimeError, match="checksum"):
        api.validate_manifest({"sources": [], "input_hash": "invalid"})
    spec = sources.source_specs()[0]
    with pytest.raises(RuntimeError, match="columns"):
        api.validate_source_contract(
            spec, {"source": spec.reference, "columns": ["old"]}, ["new"]
        )


def test_fba_projection_change_requires_explicit_rebuild():
    api = incremental_api()
    spec = next(s for s in sources.source_specs()
                if s.local_name == "dashboard_label_source_fba")
    with pytest.raises(RuntimeError, match="full"):
        api.validate_source_contract(
            spec,
            {
                "source": spec.reference,
                "columns": ["create_time"],
                "normalization_version": "obsolete",
            },
            ["create_time"],
        )


@pytest.mark.parametrize("version", ["dwd_fba_label_projection_20261009", None])
def test_outdated_fba_contract_stops_before_any_database_access(version):
    api = incremental_api()
    items = [
        {
            "source": spec.reference,
            "local_name": spec.local_name,
            "columns": ["id"],
            "rows": 1,
            "sha256": "a" * 64,
        }
        for spec in sources.source_specs()
    ]
    fba = next(x for x in items if x["local_name"] == "dashboard_label_source_fba")
    if version is not None:
        fba["normalization_version"] = version
    previous = {"batch_id": "old", "sources": items, "input_hash": api.manifest_hash(items)}

    class UnusedConnection:
        def __getattr__(self, name):
            raise AssertionError("database accessed before validating FBA version")

    progress = []
    with pytest.raises(RuntimeError, match="FBA normalization changed"):
        api.sync_incremental_sources(
            UnusedConnection(), UnusedConnection(), "label_test", "new", previous,
            progress=progress.append,
        )
    assert progress == []
    fba["normalization_version"] = api.NORMALIZATION_VERSION
    previous["input_hash"] = api.manifest_hash(items)
    api.validate_manifest(previous)


def test_fba_delta_percent_literals_are_safe_with_bound_parameters():
    api = incremental_api()
    spec = next(s for s in sources.source_specs()
                if s.local_name == "dashboard_label_source_fba")
    sql, params = api.delta_select_sql(
        spec, ["create_time", "country_category"], ("2026-10-13",),
        raw_fba_date=date(2026, 10, 13),
    )
    bound = sql % tuple(repr(p) for p in params)
    assert "2026-10-13" in bound
    assert "%\u82f1\u56fd%" in bound


@pytest.mark.parametrize("existing,force_full,mode", [
    (None, False, "full"), ({"batch_id": "old"}, False, "incremental"),
    ({"batch_id": "old"}, True, "full"),
])
def test_sync_dispatches_bootstrap_incremental_and_explicit_full(
    monkeypatch, existing, force_full, mode
):
    api = incremental_api()

    class Conn:
        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            import json
            if "get_lock" in self.sql:
                return {"acquired": 1}
            if "information_schema" in self.sql:
                return {"n": bool(existing)}
            return {"manifest_json": json.dumps(existing)}

    monkeypatch.setattr(sources, "_sync_full_sources", lambda *a, **k: "full")
    monkeypatch.setattr(api, "sync_incremental_sources", lambda *a, **k: "incremental")
    assert sources.sync_sources(
        Conn(), Conn(), "label_test", "new", force_full=force_full,
        progress=lambda r: None,
    ) == mode


@pytest.mark.parametrize("module_name", [
    "etl.label_local_generation", "etl.label_rule_evidence_snapshot_update",
])
def test_both_cli_entrypoints_forward_explicit_full_sync(monkeypatch, module_name):
    from importlib import import_module
    import sys
    from app import label_update_policy

    # Test CLI argument contracts with updates enabled; production freeze is
    # independently checked against both real entrypoints.
    monkeypatch.setattr(label_update_policy, 'LABEL_UPDATES_FROZEN', False)

    module = import_module(module_name)
    called = []
    result = {
        "label_dates": [], "fact_rows": 0, "source_mode": "local_generated",
        "history_start": "2026-10-07", "periods": [], "evidence_rows": 0,
    }

    def run(*args, **kwargs):
        called.append(kwargs)
        return result

    name = "run_generation" if module_name.endswith("generation") else "run_update"
    monkeypatch.setattr(module, name, run)
    monkeypatch.setattr(sys, "argv", ["label", "--full-sync"])
    module.main()
    assert called[0]["force_full_sync"] is True
    assert called[0]["sync"] is True
    monkeypatch.setattr(sys, "argv", ["label", "--full-sync", "--reuse-inputs"])
    with pytest.raises(SystemExit):
        module.main()


def test_remote_and_local_fingerprints_overlap_without_sharing_connections(monkeypatch):
    from threading import Barrier

    api = incremental_api()
    source, target = object(), object()
    spec = sources.SourceSpec("remote", "orders", "dashboard_label_source_orders")
    both_reading = Barrier(2)

    def read(conn, current_spec, names, sql, params=()):
        assert current_spec is spec and names == ["id"]
        if conn is source:
            assert sql == "select id from remote.orders where id > %s" and params == (5,)
            result = {"1": {"rows": 2}}
        else:
            assert conn is target and sql == "select * from `local`.`orders`"
            result = {"1": {"rows": 1}}
        # A sequential implementation times out here. Each connection must have
        # its own reader, and both must finish before staging starts.
        both_reading.wait(timeout=2)
        return result

    monkeypatch.setattr(api, "read_fingerprints", read)
    remote, local, remote_seconds, local_seconds = api.read_fingerprint_pair(
        source, target, spec, ["id"],
        "select id from remote.orders where id > %s", (5,), "`local`.`orders`",
    )
    assert remote == {"1": {"rows": 2}}
    assert local == {"1": {"rows": 1}}
    assert remote_seconds >= 0 and local_seconds >= 0


def test_local_fingerprint_failure_waits_for_remote_reader_before_rollback(monkeypatch):
    from threading import Event

    api = incremental_api()
    source, target = object(), object()
    remote_started, local_failed, remote_finished = Event(), Event(), Event()

    def read(conn, *args):
        if conn is source:
            remote_started.set()
            assert local_failed.wait(timeout=2)
            remote_finished.set()
            return {}
        assert remote_started.wait(timeout=2)
        local_failed.set()
        raise RuntimeError("local fingerprint failed")

    monkeypatch.setattr(api, "read_fingerprints", read)
    with pytest.raises(RuntimeError, match="local fingerprint failed"):
        api.read_fingerprint_pair(source, target, sources.source_specs()[0], [], "select 1", (), "live")
    assert remote_finished.is_set()
