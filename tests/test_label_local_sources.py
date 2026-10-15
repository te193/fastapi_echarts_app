from etl.label_local_sources import project_columns, source_specs, source_select_sql


def test_source_contract_never_contains_completed_label_facts():
    refs = [spec.reference for spec in source_specs()]
    assert "dws_datasync.dws_标签表" not in refs
    assert "dws_datasync.dws_标签详情表" in refs
    assert "temporary_APP.lx_sale_adjust_price_queue" in refs


def test_projection_retains_rule_inputs_and_forced_index_columns_only():
    columns = [{"column_name": name} for name in ("id", "seller_sku", "start_date", "create_time", "unused_large_json")]
    indexes = [{"index_name": "idx_osp_performance_date_sync", "column_name": "start_date"}]
    result = project_columns("dwd_datasync.lx_statistics_product_performance", columns, indexes)
    assert {r["column_name"] for r in result} == {"id", "seller_sku", "start_date", "create_time"}


def test_dictionary_keeps_metadata_for_the_page_not_just_rule_input_columns():
    columns = [{"column_name": name} for name in ("label_id", "tag_rule", "business_owner")]
    assert project_columns("dws_datasync.dws_标签详情表", columns, []) == columns


def test_only_current_raw_fba_is_loaded_for_v47_clearance_source():
    spec = next(s for s in source_specs() if s.reference == "dwd_datasync.lx_storage_fba_warehouse_detail")
    sql = source_select_sql(spec, ["id", "create_time"], raw_fba_date="2026-10-08")
    assert sql[1] == ("2026-10-08",)
    assert "select `id`, `create_time`" in sql[0]
    assert "create_time" in sql[0]


def test_source_select_rejects_arbitrary_non_allowlisted_tables():
    import pytest
    from etl.label_local_sources import SourceSpec

    with pytest.raises(ValueError, match="allowlist"):
        source_select_sql(SourceSpec("dws_datasync", "dws_标签表", "bad"), ["evidence_json"])


def test_product_performance_keeps_pre_2026_history_for_pre_stockout_and_ad_windows():
    spec = next(s for s in source_specs() if s.local_name == "dashboard_label_source_performance")
    sql, params = source_select_sql(spec, ["id", "start_date"])
    assert "where" not in sql
    assert params == ()


def test_operational_inventory_reads_remote_dwd_without_using_shared_etl_table():
    spec = next(s for s in source_specs() if s.local_name == "dashboard_label_source_fba")
    assert spec.reference == "dwd_datasync.lx_storage_fba_warehouse_detail"
    sql, params = source_select_sql(spec, ["create_time", "seller_sku_adj", "seller_name_new", "country_category"])
    assert "from `dwd_datasync`.`lx_storage_fba_warehouse_detail`" in sql
    assert "etl_dispose" not in sql and "where" not in sql and params == ()
    assert "regexp_replace" in sql and "cast(date(" in sql


def test_fba_contract_preserves_required_index_and_rejects_missing_raw_fields():
    import pytest
    from etl.label_fba_source import RAW_COLUMNS, DERIVED_COLUMNS, fba_columns, fba_indexes
    metadata = [{"column_name": name} for name in RAW_COLUMNS]
    assert [c["column_name"] for c in fba_columns(metadata)] == list(RAW_COLUMNS + DERIVED_COLUMNS)
    assert {i["index_name"] for i in fba_indexes()} == {"id1","idx_label_fba_date"}
    with pytest.raises(RuntimeError, match="missing"):
        fba_columns(metadata[:-1])


def test_resume_accepts_only_completed_listing_and_performance_stages():
    import pytest
    from etl.label_local_sources import staged_resume_manifest
    valid = {'local_name': 'dashboard_label_source_performance', 'source': 'dwd_datasync.lx_statistics_product_performance',
             'rows': 12, 'sha256': 'a'*64, 'columns': ['id']}
    assert staged_resume_manifest([valid]) == {valid['local_name']: valid}
    for items in ([valid, valid], [{**valid, 'source':'dws_datasync.dws_标签表'}],
                  [{**valid, 'local_name':'dashboard_label_source_dictionary'}], [{**valid, 'rows':0}]):
        with pytest.raises(RuntimeError):
            staged_resume_manifest(items)


def test_resume_rejects_missing_indexes_or_incomplete_rows_before_swap():
    import pytest
    from etl.label_local_sources import validate_staged_resume
    class Cursor:
        def __init__(self, count=12, indexes=('PRIMARY',)):
            self.count, self.indexes = count, indexes
        def cursor(self):return self
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def execute(self, sql, params=None):
            assert sql.startswith('select ')
            if 'information_schema.columns' in sql:self.rows=[{'column_name':'id'}]
            elif 'information_schema.statistics' in sql:self.rows=[{'index_name':i} for i in self.indexes]
            else:self.rows=[{'n':self.count}]
        def fetchall(self):return self.rows
        def fetchone(self):return self.rows[0]
    manifest={'columns':['id'],'rows':12}
    indexes=[{'index_name':'PRIMARY','column_name':'id'},
             {'index_name':'unprojected','column_name':'id'}, {'index_name':'unprojected','column_name':'unused'}]
    validate_staged_resume(Cursor(),'label_test','dashboard_label_source_performance__load',manifest,['id'],indexes)
    with pytest.raises(RuntimeError, match='row count mismatch'):
        validate_staged_resume(Cursor(count=11),'label_test','dashboard_label_source_performance__load',manifest,['id'],indexes)
    with pytest.raises(RuntimeError, match='indexes missing'):
        validate_staged_resume(Cursor(indexes=()),'label_test','dashboard_label_source_performance__load',manifest,['id'],indexes)


def test_disconnect_cleanup_does_not_mask_original_sync_failure(monkeypatch):
    import pytest
    from etl import label_local_sources as sources
    class Conn:
        def cursor(self):return self
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def execute(self,*a):pass
        def fetchall(self):return [{'column_name':'batch_id'},{'column_name':'local_name'}]
        def commit(self):pass
        def rollback(self):raise RuntimeError('cleanup rollback failure')
        def autocommit(self,value):
            if value:raise RuntimeError('cleanup autocommit failure')
    def failure(*a):raise RuntimeError('original remote disconnect')
    monkeypatch.setattr(sources,'configure_source_keepalive',failure)
    with pytest.raises(RuntimeError, match='original remote disconnect'):
        sources.sync_sources(Conn(),Conn(),'label_test','batch')
