"""Keep clearance evidence small, separate, dated and explicit about old snapshots."""
from datetime import date
from io import BytesIO
import sqlite3
from unittest.mock import MagicMock

import pymysql
from openpyxl import load_workbook
import pytest

from app import main
from app.services.replenishment_data import ReplenishmentDataService
from etl import replenishment_update as update


def workbook(audit):
    return load_workbook(BytesIO(main.build_replenishment_xlsx({
        'columns': [{'name': 'seller_sku_adj', 'label': 'MSKU'},
                    {'name': 'replenish_qty', 'label': '补货数量'}],
        'rows': [{'seller_sku_adj': 'normal', 'replenish_qty': 100}],
        'clearance_rows': audit, 'snapshot_date': '2026-10-13',
    })))


def test_nonempty_audit_is_only_five_columns_and_never_expands_the_main_sheet():
    wb = workbook([{'country_category': '欧洲站', 'seller_name_new': 'Shop',
                     'seller_sku_adj': 'blocked', 'reference_qty': 50,
                     'block_reason': '清货名单，禁止补货'}])
    assert wb.sheetnames == ['补货计划', '清货拦截明细', '颜色与标注说明']
    assert wb['补货计划'].max_row == 2
    assert wb['补货计划'].max_column == 3
    assert wb['补货计划']['B2'].value == 100
    sheet = wb['清货拦截明细']
    assert sheet.max_column == 5
    assert sheet['C2'].value == 'blocked'
    assert sheet['D2'].value == 50
    assert sheet['E2'].value == '清货名单，禁止补货'
    assert '参考' in sheet['D1'].value


@pytest.mark.parametrize('rows', [[], [{'reference_qty': 0}], [{'reference_qty': -1}]])
def test_no_positive_clearance_does_not_create_an_empty_sheet(rows):
    assert workbook(rows).sheetnames == ['补货计划', '颜色与标注说明']


def mock_conn(rows):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = rows
    return conn, cursor


def test_saved_evidence_is_read_without_requesting_sources_or_recalculating():
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    service.connect_source = MagicMock(side_effect=AssertionError('no remote query for saved evidence'))
    conn, cursor = mock_conn([{'reference_qty': 25}])
    assert service._clearance_export_items(conn, date(2026, 10, 15), '欧洲站', 'Shop', 'ABC') == [{'reference_qty': 25}]
    sql, params = cursor.execute.call_args.args
    assert 'snapshot_date' in sql and 'reference_qty > 0' in sql
    assert params['snapshot_date'] == date(2026, 10, 15)
    assert params['site'] == '欧洲站' and params['store'] == 'Shop'
    assert params['keyword'] == '%ABC%'
    assert 'role_' not in sql


def test_old_snapshot_preview_uses_display_quantity_and_marks_pending_not_blocked():
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    conn, cursor = mock_conn([{'country_category': '欧洲站', 'seller_name_new': 'Shop',
                             'seller_sku_adj': 'ABC', 'reference_qty': 36}])
    cursor.execute.side_effect = [pymysql.err.ProgrammingError(1146, 'audit table absent'), None]
    source, source_cursor = mock_conn([{'msku': 'ABC', 'store': '全部'},
                                       {'msku': 'DEF', 'store': 'shop'}])
    service.connect_source = MagicMock(return_value=source)
    rows = service._clearance_export_items(conn, date(2026, 10, 13), 'all', 'all', '')
    assert rows[0]['reference_qty'] == 36
    assert '待重新生成' in rows[0]['block_reason']
    sql, params = cursor.execute.call_args.args
    assert 'executable_replenish_qty' in sql
    assert 'history_recovery_flag' in sql
    assert params['clearance_msku_0'] == 'ABC'
    assert params['clearance_msku_1'] == 'DEF'
    assert params['clearance_store_1'] == 'shop'
    assert 'r.cur_date=' in sql
    assert 'reference_qty > 0' in sql


def test_errors_other_than_missing_audit_table_are_not_silenced():
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    conn, cursor = mock_conn([])
    cursor.execute.side_effect = pymysql.err.OperationalError(2013, 'connection lost')
    with pytest.raises(pymysql.err.OperationalError):
        service._clearance_export_items(conn, date(2026, 10, 15), 'all', 'all', '')


def test_evidence_uses_original_quantity_with_history_recovery_moq_and_store_scope():
    db = sqlite3.connect(':memory:')
    db.create_function('greatest', 2, max)
    db.execute("attach database ':memory:' as etl_datasync_test")
    db.execute('create table clearance_reference_original (country_category text, seller_name_new text, seller_sku_adj text, max_sku text, history_recovery_flag int, support_replenish_level_sort int, replenish_qty real, max_cg_box_pcs real, cur_date text default "2026-10-15", replenish_block_reason text default "", asin_merge_flag int default 0)')
    db.execute('create table etl_datasync_test.dashboard_replenishment_clearance_sync (msku text, store text)')
    db.execute('create table etl_datasync_test.dashboard_replenishment_supplier_moq_sync (snapshot_date text, sku text, supplier_moq real)')
    db.execute('create table etl_datasync_test.dashboard_replenishment_clearance_audit (snapshot_date text, country_category text, seller_name_new text, seller_sku_adj text, reference_qty real)')
    db.executemany('insert into clearance_reference_original (country_category,seller_name_new,seller_sku_adj,max_sku,history_recovery_flag,support_replenish_level_sort,replenish_qty,max_cg_box_pcs) values (?,?,?,?,?,?,?,?)', [
        ('欧洲站', 'Shop', 'normal', 'A', 0, 1, 80, 10),
        ('欧洲站', 'Shop', 'clear', 'A', 0, 1, 80, 10),
        ('英国站', 'Shop', 'clear', 'B', 0, 1, 20, 10),
        ('欧洲站', 'Shop', 'recover', 'C', 1, 4, 0, 36),
        ('欧洲站', 'Shop', 'zero', 'D', 0, 4, 0, 10),
        ('欧洲站', 'Shop', 'followed', 'D', 0, 1, 0, 10),
        ('欧洲站', 'Other', 'specific', 'D', 0, 1, 80, 10),
        ('欧洲站', 'Shop', 'specific', 'D', 0, 1, 80, 10),
    ])
    db.executemany('insert into etl_datasync_test.dashboard_replenishment_clearance_sync values (?,?)',
                   [('clear', '全部'), ('recover', '全部'), ('zero', '全部'),
                    ('followed', '全部'), ('specific', 'shop')])
    db.execute("insert into etl_datasync_test.dashboard_replenishment_supplier_moq_sync values ('2026-10-15','B',50)")
    # Execute the real production quantity/filter projection over original-result
    # fixtures. ASIN target restoration is executed in the follow-store tests.
    projection = update.build_clearance_audit_sql().split('clearance_reference_quantities as (', 1)[1]
    sql = ('insert into etl_datasync_test.dashboard_replenishment_clearance_audit '
           'with clearance_reference_quantities as (' + projection)
    sql = sql.replace('%(snapshot_date)s', ':snapshot_date').replace('binary ', '')
    db.execute(sql, {'snapshot_date': '2026-10-15'})
    rows = db.execute('select seller_sku_adj, reference_qty from etl_datasync_test.dashboard_replenishment_clearance_audit order by seller_sku_adj').fetchall()
    assert rows == [('clear', 80), ('recover', 36), ('specific', 80)]
    db.close()


def test_audit_reuses_existing_candidates_and_replaces_only_one_snapshot_atomically():
    schemas = update.SchemaConfig(
        target_schema='etl_datasync_test', etl_source_schema='etl_datasync',
        dwd_source_schema='dwd_datasync', pricing_source_schema='temporary_dwd')
    conn, cursor = mock_conn([])
    update.refresh_clearance_audit(conn, schemas, {'snapshot_date': date(2026, 10, 15)})
    delete, insert = [call.args[0] for call in cursor.execute.call_args_list]
    assert 'where snapshot_date = %(snapshot_date)s' in delete
    assert 'dashboard_replenishment_work_replenish_calc_v3' in insert
    assert 'tmp_pur_plan_replenish_calc' not in insert
    conn.commit.assert_called_once()
    assert 'dashboard_replenishment_clearance_audit' in '\n'.join(update.DDL_STATEMENTS)


def test_result_must_validate_before_exclusion_evidence_is_written(monkeypatch):
    conn, cursor = mock_conn([])
    cursor.rowcount = 0
    events = []
    monkeypatch.setattr(update, 'build_replenishment_result_statements', lambda _: [])
    monkeypatch.setattr(update, 'refresh_replenishment_sales_spike_flags', lambda *a, **kw: 0)
    monkeypatch.setattr(update, 'validate_replenishment_result', lambda *a: events.append('validated'))
    monkeypatch.setattr(update, 'refresh_clearance_audit', lambda *a: events.append('audit'))
    monkeypatch.setattr(update, 'log_task', lambda *a: None)
    schemas = update.SchemaConfig(target_schema='etl_datasync_test', etl_source_schema='etl_datasync',
                                  dwd_source_schema='dwd_datasync', pricing_source_schema='temporary_dwd')
    update.execute_sql_step(conn, schemas, update.STEPS['replenishment_result'],
                            {'snapshot_date': date(2026, 10, 15), 'biz_date': date(2026, 10, 14)})
    assert events == ['validated', 'audit']
