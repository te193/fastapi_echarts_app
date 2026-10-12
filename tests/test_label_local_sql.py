from pathlib import Path

import pytest

from etl.label_local_sql import compile_procedure, qualified_references, sql_tokens


def test_compiles_v47_without_any_remote_table_reference():
    sql = compile_procedure("label_local_test")
    refs = qualified_references(sql)
    assert refs
    assert all(schema == "label_local_test" for schema, _ in refs)
    assert "create procedure `label_local_test`.`dashboard_label_local_v47`" in sql
    assert "delimiter" not in {
        value.lower() for kind, value in sql_tokens(sql) if kind == "word"
    }
    assert "'dws_label_v47_singleton'" not in sql
    assert "resignal" in sql
    assert "'RECEIVING'" in sql
    assert "'dwd_datasync.lx_storage_fba_warehouse_detail'" in sql
    assert "'etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail'" not in sql


def test_compiler_fails_closed_on_new_unknown_source_dependency(tmp_path):
    from etl.label_local_sql import BASELINE_PATH

    sql = BASELINE_PATH.read_text(encoding="utf-8-sig")
    sql = sql.replace(
        "dwd_datasync.lx_statistics_product_performance", "other_data.unknown_source"
    )
    path = tmp_path / "changed.sql"
    path.write_text(sql, encoding="utf-8")
    with pytest.raises(ValueError, match="unmapped"):
        compile_procedure("label_local_test", path=path, check_hash=False)


def test_literals_and_comments_are_not_treated_as_table_dependencies():
    sql = "select 'dws_datasync.dws_标签表', 'it''s \\'quoted' from `local`.`source`; -- other.table\n"
    assert qualified_references(sql) == {("local", "source")}


def test_schema_cannot_inject_additional_statements():
    with pytest.raises(ValueError, match="schema"):
        compile_procedure("test; drop database mysql")


def test_archive_hash_is_checked_before_compiling(tmp_path):
    path = tmp_path / "wrong.sql"
    path.write_text("create procedure x() begin end //", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        compile_procedure("label_local_test", path=path)


def test_optional_ddl_words_do_not_hide_unknown_schema_dependencies():
    assert qualified_references(
        "drop table if exists other_data.secret; create temporary table if not exists safe.work(id int)"
    ) == {("other_data", "secret"), ("safe", "work")}


def test_isolated_preview_uses_real_input_indexes_and_separate_work_tables():
    sql = compile_procedure("label_preview", input_schema="label_inputs")
    refs = qualified_references(sql)
    assert ("label_inputs", "dashboard_label_source_performance") in refs
    assert ("label_preview", "dashboard_label_local_work") in refs
    assert all(schema in {"label_preview", "label_inputs"} for schema, _ in refs)
    assert "force index (`idx_osp_performance_date_sync`)" in sql
