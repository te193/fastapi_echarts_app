"""Execute the production clearance predicates against representative rows."""
import sqlite3
from datetime import date
from unittest.mock import MagicMock

import pytest

from etl import replenishment_update as update


@pytest.fixture
def db():
    conn = sqlite3.connect(':memory:')
    conn.execute("attach database ':memory:' as etl_datasync_test")
    conn.execute('create table etl_datasync_test.dashboard_replenishment_clearance_sync (msku text collate nocase, store text)')
    conn.execute('create table candidates (country_category text, seller_name_new text, seller_sku_adj text, replenish_qty real)')
    conn.executemany('insert into candidates values (?,?,?,?)', [
        ('欧洲站','Shop-A','clearance',100), ('英国站','Shop-A','clearance',0),
        ('欧洲站','Shop-B','clearance',200), ('欧洲站','Shop-A','normal',50)])
    yield conn
    conn.close()


def final_rows(conn, entries):
    conn.executemany('insert into etl_datasync_test.dashboard_replenishment_clearance_sync values (?,?)', entries)
    final_insert = next(s for s in update.split_sql_statements(update.REPLENISHMENT_RESULT_SQL)
                        if s.startswith('insert into etl_datasync_test.dashboard_pur_plan_replenish_data'))
    tail = final_insert.rsplit(') merged',1)[1].strip().rstrip(';')
    assert tail.startswith('where not exists'), 'Clearance exclusion must apply to every generated row.'
    return conn.execute('select * from candidates merged '+tail).fetchall()


def test_global_clearance_produces_no_rows_for_any_store_or_category_including_zero_qty(db):
    assert final_rows(db,[('clearance','全部')]) == [('欧洲站','Shop-A','normal',50)]


def test_specific_store_clearance_preserves_other_stores_and_unlisted_products(db):
    rows = final_rows(db,[('clearance','shop-a')])
    assert rows == [('欧洲站','Shop-B','clearance',200),('欧洲站','Shop-A','normal',50)]


def test_empty_list_preserves_all_business_rows_and_quantities(db):
    assert sum(row[3] for row in final_rows(db,[])) == 350


def test_global_and_specific_entries_do_not_duplicate_or_leave_clearance_rows(db):
    assert final_rows(db,[('clearance','全部'),('clearance','shop-a')]) == [('欧洲站','Shop-A','normal',50)]


def test_every_candidate_can_be_excluded_without_generating_zero_quantity_placeholders(db):
    assert final_rows(db,[('clearance','全部'),('normal','全部')]) == []


def test_clearance_sync_reads_only_and_normalizes_configuration():
    conn=sqlite3.connect(':memory:')
    conn.execute("attach database ':memory:' as dws_datasync")
    conn.execute('create table dws_datasync.dws_product_clearance_list (msku text, store text)')
    conn.executemany('insert into dws_datasync.dws_product_clearance_list values (?,?)',
                     [(' clear ','全部'),('sku',' Shop-A '),('','全部'),('sku','  '),(None,'全部')])
    step=update.STEPS['clearance_list_sync']
    update.assert_source_select_only(step.source_select_statement)
    assert conn.execute(step.source_select_statement).fetchall() == [('clear','全部'),('sku','shop-a')]
    assert step.target_columns == ('msku','store')
    assert 'dashboard_replenishment_clearance_sync' in '\n'.join(update.DDL_STATEMENTS)
    conn.close()


@pytest.mark.parametrize('selection',['replenishment_result','replenishment_result,clearance_list_sync','clearance_list_sync,replenishment_result'])
def test_even_partial_generation_refreshes_clearance_before_deleting_or_generating(selection):
    steps=update.parse_steps(selection)
    assert steps.index('clearance_list_sync') < steps.index('replenishment_result')
    assert steps.count('clearance_list_sync') == 1


def test_default_generation_refreshes_clearance_first():
    steps=update.parse_steps('all')
    assert steps.index('clearance_list_sync') < steps.index('replenishment_result')


def test_source_read_failure_stops_before_existing_result_is_deleted(monkeypatch):
    import sys
    monkeypatch.setattr(sys,'argv',['replenishment_update','--steps','replenishment_result','--skip-ddl',
                                   '--biz-date','2026-10-14','--snapshot-date','2026-10-15'])
    monkeypatch.setattr(update,'apply_database_ini_env',lambda:None)
    monkeypatch.setattr(update,'build_schema_config',schemas)
    monkeypatch.setattr(update,'connect_target',MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(update,'connect_source',MagicMock(return_value=MagicMock()))
    load=MagicMock(side_effect=RuntimeError('clearance source unavailable'))
    generate=MagicMock()
    monkeypatch.setattr(update,'execute_source_load_step',load)
    monkeypatch.setattr(update,'execute_sql_step',generate)
    with pytest.raises(RuntimeError,match='clearance source unavailable'):
        update.main()
    assert load.call_args.args[3].name == 'clearance_list_sync'
    generate.assert_not_called()


def connection(rows):
    conn,cursor=MagicMock(),MagicMock()
    conn.cursor.return_value.__enter__.return_value=cursor
    cursor.fetchone.side_effect=rows
    return conn


def schemas():
    return update.SchemaConfig(target_schema='etl_datasync_test',etl_source_schema='etl_datasync',
                               dwd_source_schema='dwd_datasync',pricing_source_schema='temporary_dwd')


def test_validation_rejects_any_clearance_object_even_when_snapshot_is_nonempty():
    with pytest.raises(RuntimeError,match='清货名单'):
        update.validate_replenishment_result(connection([{'row_count':3,'clearance_count':1}]),schemas(),
            {'snapshot_date':date(2026,10,15),'biz_date':date(2026,10,14)})


def test_all_candidates_cleared_is_a_valid_empty_result_not_an_upstream_failure():
    assert update.validate_replenishment_result(connection([{'row_count':0,'clearance_count':0},
        {'candidate_count':4,'allowed_count':0}]),schemas(),
        {'snapshot_date':date(2026,10,15),'biz_date':date(2026,10,14)}) == 0
