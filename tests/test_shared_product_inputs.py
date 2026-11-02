import json
from unittest.mock import MagicMock
import pytest
from etl import shared_product_inputs as shared


def test_shared_projection_preserves_raw_fields_and_requires_complete_union():
    assert len(shared.PRODUCT_COLUMNS) == 39
    assert {'id','start_date','end_date','create_time','gross_profit','local_sku','sessions_mobile','page_views_mobile'} <= set(shared.PRODUCT_COLUMNS)
    with pytest.raises(RuntimeError,match="missing"):
        shared.require_columns([{'column_name':'id'}])


def test_additive_migration_rejects_contract_loss_or_wrong_source():
    old={'source':shared.SOURCE_REFERENCE,'columns':['id','start_date'],'rows':1}
    shared.validate_upgrade(old,['id','start_date','volume'])
    with pytest.raises(RuntimeError):shared.validate_upgrade(old,['id','volume'])
    with pytest.raises(RuntimeError):shared.validate_upgrade({**old,'source':'other.table'},['id','start_date'])


def test_sql_routing_changes_only_qualified_product_reference():
    sql='select volume from dwd_datasync.lx_statistics_product_performance where end_date=start_date'
    result=shared.local_product_sql(sql,'dwd_datasync','local_test')
    assert 'local_test.dashboard_label_source_performance' in result
    assert 'where end_date=start_date' in result
    assert shared.local_product_sql('select * from dwd_datasync.other','dwd_datasync','local_test')=='select * from dwd_datasync.other'


def test_shared_reuse_requires_same_run_version_and_full_projection(monkeypatch):
    monkeypatch.setenv(shared.RUN_ENV,'run_a')
    item={'columns':list(shared.PRODUCT_COLUMNS),'shared_acquisition':{'run_id':'run_a','version':shared.CONTRACT_VERSION}}
    assert shared.can_reuse(item)
    assert not shared.can_reuse({**item,'columns':['id']})
    assert not shared.can_reuse({**item,'shared_acquisition':{'run_id':'run_b','version':shared.CONTRACT_VERSION}})


def test_reader_fails_closed_when_manifest_generation_changed(monkeypatch):
    monkeypatch.setenv(shared.RUN_ENV,'run_a')
    conn=MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value={'manifest_json':json.dumps({'sources':[]})}
    with pytest.raises(RuntimeError,match='shared product'):
        shared.read_shared_item(conn,'local_test')


def test_frozen_reader_cannot_silently_reconnect():
    raw=MagicMock();wrapped=shared.LocalProductConnection(raw,'remote_dwd','local_test')
    wrapped.ping(reconnect=True)
    raw.ping.assert_called_once_with(reconnect=False)


def test_traffic_delta_requires_exact_base_and_keeps_old_corrections_and_new_days():
    from datetime import date
    state={'first_loaded':date(2025,1,1),'last_loaded':date(2026,10,15),
           'coverage_start':date(2025,1,1),'source_revision':json.dumps(['dwd','product','shared:old'])}
    item={'shared_acquisition':{'previous_sha256':'old','changed_partitions':['2026-09-01','2026-10-16','__NULL__']}}
    args=(state,date(2026,1,1),date(2026,10,16),('dwd','product','shared:new'),'2025-01-01',item)
    assert shared.shared_traffic_ranges(*args)==[(date(2026,9,1),date(2026,9,1)),(date(2026,10,16),date(2026,10,16))]
    state['source_revision']=json.dumps(['dwd','product','shared:older'])
    assert shared.shared_traffic_ranges(*args) is None


def test_traffic_delta_handles_deletions_without_reloading_unchanged_dates():
    from datetime import date
    state={'first_loaded':date(2025,1,1),'last_loaded':date(2026,10,16),
           'coverage_start':date(2025,1,1),'source_revision':json.dumps(['dwd','product','shared:old'])}
    item={'shared_acquisition':{'previous_sha256':'old','changed_partitions':['2026-01-02']}}
    assert shared.shared_traffic_ranges(state,date(2026,1,1),date(2026,10,16),('dwd','product','shared:new'),'2025-01-01',item)==[(date(2026,1,2),date(2026,1,2))]


def test_local_product_reader_streams_rows_like_the_original_source(monkeypatch):
    import pymysql.cursors
    from etl.dashboard_daily_update import build_schema_config
    from unittest.mock import patch
    monkeypatch.setenv(shared.RUN_ENV,'stream_test')
    raw=MagicMock()
    with patch.object(shared,'read_shared_item',return_value={}):
        with shared.product_reader(build_schema_config(),target_factory=lambda:raw) as reader:
            assert reader.raw.cursorclass is pymysql.cursors.SSDictCursor
