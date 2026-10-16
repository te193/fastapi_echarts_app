"""Executable MySQL 8 contract; only disposable private test schemas are written."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import pytest
import pymysql

SQL = Path(__file__).resolve().parents[1] / 'sqlcode' / '2026-10-10-产品历史销售角色建表与计算.sql'


def test_sql_delivery_exists():
    assert SQL.exists(), 'Missing deployable history SQL'


def execute_script(conn, script):
    script = re.sub(r'/\*.*?\*/', '', script, flags=re.S)
    delimiter = ';'
    buffer = ''
    with conn.cursor() as q:
        for line in script.splitlines():
            if line.strip().startswith('delimiter '):
                assert not buffer.strip()
                delimiter = line.strip().split()[1]
                continue
            if not buffer and (not line.strip() or line.lstrip().startswith('--')):
                continue
            buffer += line + '\n'
            if buffer.rstrip().endswith(delimiter):
                q.execute(buffer.rstrip()[:-len(delimiter)].strip())
                while q.nextset():
                    pass
                buffer = ''
        assert not buffer.strip()


def read_section(key):
    script = SQL.read_text(encoding='utf-8')
    body = script.split(f'-- section:{key}:begin\n', 1)[1].split(f'-- section:{key}:end', 1)[0].strip()
    if body.startswith('/*'):
        body = body[2:].removesuffix('*/').strip()
    return body


@pytest.fixture
def db(request):
    if os.getenv('PRODUCT_ROLE_HISTORY_MYSQL_TEST') != '1':
        pytest.skip('isolated MySQL integration is opt-in')
    # These tests may never load production/project credentials or reach a LAN host.
    host = os.getenv('PRODUCT_ROLE_HISTORY_TEST_HOST', '127.0.0.1')
    assert host in {'127.0.0.1', 'localhost'}
    conn = pymysql.connect(host=host, port=int(os.getenv('PRODUCT_ROLE_HISTORY_TEST_PORT', '33316')),
                           user=os.getenv('PRODUCT_ROLE_HISTORY_TEST_USER', 'root'),
                           password=os.getenv('PRODUCT_ROLE_HISTORY_TEST_PASSWORD', ''), charset='utf8mb4',
                           autocommit=True, cursorclass=pymysql.cursors.DictCursor)
    schema = 'test_role_history_' + uuid4().hex[:12]
    def cleanup():
        try:
            with conn.cursor() as q:
                q.execute(f'drop database if exists `{schema}`')
        finally:
            conn.close()
    request.addfinalizer(cleanup)
    with conn.cursor() as q:
        q.execute(f'create database `{schema}` character set utf8mb4 collate utf8mb4_0900_ai_ci')
        q.execute(f'use `{schema}`')
        for suffix in [''] + [f'_{y}' for y in range(2020, 2026)]:
            q.execute(f'''create table lx_statistics_product_performance{suffix} (
                id bigint primary key, seller_name varchar(100), country varchar(100),
                seller_sku varchar(500), asin varchar(40), start_date varchar(100), end_date varchar(100),
                product_create_time varchar(100), volume decimal(18,4), amount decimal(18,4),
                predict_gross_profit decimal(18,4), afn_fulfillable_quantity int,
                `rank` int, create_time datetime, index idx_date(start_date))''')
        q.execute('''create table lx_sales_mws_listing (seller_name varchar(100), seller_sku varchar(500),
            asin varchar(40), open_date_display varchar(100), on_sale_time varchar(100), marketplace varchar(100) default '德国')''')
        script = SQL.read_text(encoding='utf-8').replace('dws_datasync', schema).replace('dwd_datasync', schema)
        execute_script(conn, script)
    yield conn, schema


def call(db, mode, day, start=None, end=None):
    conn, schema = db
    with conn.cursor() as q:
        try:
            q.execute('call sp_product_role_history(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                      (mode, day, schema, start, end, None if mode != 'rebuild' else 'country',
                       None if mode != 'rebuild' else '欧洲站', None if mode != 'rebuild' else '德国',
                       None if mode != 'rebuild' else 'shop', None if mode != 'rebuild' else 'sku', 0, 7))
        except pymysql.MySQLError as exc:
            q.execute('select stage,error_message from dws_product_sales_role_history_run_log order by started_at desc limit 1')
            exc.add_note(str(q.fetchone()))
            raise
        while q.nextset():
            pass


def seed(db, days=90, anchor='2026-01-01', country='德国', sku='sku', volume=6, stock=5, rank=20, id_offset=0):
    conn, schema = db
    first = date.fromisoformat(anchor)
    rows = []
    for n in range(days):
        d = first + timedelta(days=n)
        suffix = f'_{d.year}' if d.year < 2026 else ''
        rows.append((suffix, (n + 1 + id_offset, 'shop-DE', country, sku, 'ASIN', d.isoformat(), d.isoformat(),
                              anchor, volume, 100, 20, stock, rank, '2026-01-01 00:00:00')))
    with conn.cursor() as q:
        for suffix in {x[0] for x in rows}:
            q.executemany(f'insert into lx_statistics_product_performance{suffix} values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                          [r for s, r in rows if s == suffix])


def result(db, scope='country', sku='sku'):
    with db[0].cursor() as q:
        q.execute('select * from dws_product_sales_role_history where scope_mode=%s and msku=%s', (scope, sku))
        row = q.fetchone()
        return row, json.loads(row['evidence_json'])


def test_rules_match_v47_boundaries(db):
    cases = [('business_unit', 2, .04, 1, 103), ('business_unit', .5, .05, 1, 103),
             ('business_unit', 6, .15, 1, 102), ('business_unit', 6, .15001, 1, 101),
             ('country', 4, .15, 50, 1301), ('country', 4, .15, 51, 1302),
             ('country', 2, .04, 50, 1303), ('country', 2, .2, None, 1303),
             ('country', .5, .2, None, 1304), ('country', 0, 0, None, 1304)]
    with db[0].cursor() as q:
        expr = SQL.read_text(encoding='utf-8').split('-- classifier:begin\n', 1)[1].split('-- classifier:end', 1)[0].strip()
        expr = expr.replace('v_scope', 'scope_mode')
        for scope, daily, margin, rank, expected in cases:
            q.execute('select '+expr+' as role from (select %s scope_mode,%s daily_sales_value,%s margin,%s small_rank) sample',
                      (scope, daily, margin, rank))
            assert q.fetchone()['role'] == expected


def test_dedup_frozen_incremental_gap_and_rebuild(db):
    seed(db)
    with db[0].cursor() as q:
        q.execute("insert into lx_statistics_product_performance select 999,seller_name,country,seller_sku,asin,start_date,end_date,product_create_time,volume,amount,predict_gross_profit,afn_fulfillable_quantity,`rank`,'2026-02-01' from lx_statistics_product_performance where id=1")
    call(db, 'bootstrap', '2026-02-04')
    _, before = result(db)
    assert len(before['history']) == 2
    assert before['history'][0]['sales_qty'] == 180
    assert before['history'][0]['vote_eligible'] == 1
    assert before['dominant_role']['role_id'] == 1301
    assert before['dominant_role']['valid_segment_count'] == 1
    frozen = before['history'][0]
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set volume=0 where start_date <= '2026-01-30'")
    call(db, 'incremental', '2026-03-31')
    _, after = result(db)
    assert len(after['history']) == 3
    assert after['history'][0] == frozen
    assert all(n['complete'] == 1 for n in after['history'])
    call(db, 'incremental', '2026-03-31')
    assert result(db)[1] == after
    call(db, 'rebuild', '2026-03-31', '2026-01-03', '2026-01-04')
    _, repaired = result(db)
    assert repaired['history'][0]['role_id'] == 1304
    assert repaired['history'][1:] == after['history'][1:]
    assert repaired['dominant_role']['role_id'] == 1301


def test_cross_year_oos_missing_and_tie(db):
    seed(db, days=90, anchor='2025-12-20')
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set volume=2,predict_gross_profit=20 where start_date between '2026-01-19' and '2026-02-17'")
        q.execute("update lx_statistics_product_performance set afn_fulfillable_quantity=0,volume=0 where start_date >= '2026-02-18'")
    call(db, 'bootstrap', '2026-03-19')
    _, ev = result(db)
    assert ev['history'][0]['sales_qty'] == 180
    assert ev['history'][0]['observed_days'] == 30
    assert ev['history'][1]['role_id'] == 1302
    assert ev['history'][2]['vote_eligible'] == 0
    assert ev['dominant_role']['role_id'] == 1302  # most recent tied valid segment
    assert ev['dominant_role']['tie'] == 1
    assert set(ev['dominant_role']['max_count_role_ids']) == {1301, 1302}
    assert ev['dominant_role']['selected_latest_valid_period'] == 2
    assert result(db, 'business_unit')[1]['history'][0]['role_id'] == 101


def test_bad_cutoff_and_rule_change_do_not_publish(db):
    seed(db, days=35)
    call(db, 'bootstrap', '2026-02-04')
    before = result(db)[1]
    with pytest.raises(pymysql.MySQLError, match='cutoff'):
        call(db, 'incremental', '2026-02-05')
    assert result(db)[1] == before
    with db[0].cursor() as q:
        q.execute("update dws_product_sales_role_history set evidence_json=json_set(evidence_json,'$.calculation.rule_version','old')")
    with pytest.raises(pymysql.MySQLError, match='rule version'):
        call(db, 'incremental', '2026-02-04')


def test_partial_rebuild_cannot_skip_unfinished_history(db):
    seed(db)
    call(db, 'bootstrap', '2026-02-04')
    before = result(db)[1]
    with pytest.raises(pymysql.MySQLError, match='partial rebuild cutoff'):
        call(db, 'rebuild', '2026-03-31', '2026-01-01', '2026-01-05')
    assert result(db)[1] == before


def test_conflicting_anchor_missing_day_and_frozen_years(db):
    seed(db)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='2026-01-15'")
        q.execute("delete from lx_statistics_product_performance where start_date='2026-01-07'")
    call(db, 'bootstrap', '2026-02-04')
    _, ev = result(db)
    assert ev['identity']['anchor_date'] == '2026-01-01'
    assert ev['identity']['is_proxy'] == 1 and ev['identity']['date_conflict'] == 1
    assert ev['history'][0]['exclusion_reason'] == 'missing_daily_data'
    assert ev['history'][0]['vote_eligible'] == 0
    assert ev['dominant_role']['role_id'] is None
    assert ev['identity']['asins'] == ['ASIN']
    frozen = ev['history'][0]
    with db[0].cursor() as q:
        for year in range(2020, 2026):
            q.execute(f'drop table lx_statistics_product_performance_{year}')
    call(db, 'incremental', '2026-03-31')
    assert result(db)[1]['history'][0] == frozen


def test_pre2020_anchor_and_pending_anchor(db):
    seed(db, days=60, anchor='2020-01-01')
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance_2020 set product_create_time='2019-12-10'")
    call(db, 'bootstrap', '2020-02-29')
    _, ev = result(db)
    assert ev['history'][0]['start'] == '2019-12-10'
    assert ev['history'][0]['exclusion_reason'] == 'before_source_history'
    assert ev['history'][1]['vote_eligible'] == 1
    assert ev['identity']['history_before_2020_missing'] == 1


def test_missing_dates_use_first_performance_record_without_sales_or_stock(db):
    seed(db, days=50, volume=0, stock=0)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time=''")
    call(db, 'bootstrap', '2026-02-04')
    assert result(db)[1]['identity']['anchor_status'] == 'established'
    assert result(db)[1]['identity']['anchor_date'] == '2026-01-01'
    assert result(db)[1]['identity']['anchor_source'] == 'first_performance_record'
    assert result(db)[1]['history'][0]['role_id']==1304
    assert result(db)[1]['history'][0]['vote_eligible']==0
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set volume=6,afn_fulfillable_quantity=5 where start_date>='2026-02-05'")
    call(db, 'incremental', '2026-02-19')
    _, ev = result(db)
    assert ev['identity']['anchor_date'] == '2026-01-01'
    assert ev['identity']['anchor_status'] == 'established'
    assert ev['history'][0]['start'] == '2026-01-01'


def test_business_unit_detects_missing_station_day(db):
    seed(db, days=35)
    seed(db, days=35, country='法国', id_offset=1000)
    with db[0].cursor() as q:
        q.execute("delete from lx_statistics_product_performance where country='法国' and start_date='2026-01-07'")
    call(db, 'bootstrap', '2026-02-04')
    assert result(db, 'country')[1]['history'][0]['vote_eligible'] == 1
    node = result(db, 'business_unit')[1]['history'][0]
    assert node['vote_eligible'] == 0
    assert node['missing_station_days'] == 1


def test_legacy_pending_earlier_listing_anchor_backfills_observed_history(db):
    seed(db, days=90, volume=0, stock=0)
    seed(db, days=90, sku='normal', id_offset=2000)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time=''")
    call(db, 'bootstrap', '2026-02-04')
    # Simulate an imported pending row generated by the previous anchor policy.
    with db[0].cursor() as q:
        q.execute("update dws_product_sales_role_history set evidence_json=json_set(evidence_json,'$.identity.anchor_date',null,'$.identity.anchor_status','pending','$.history',json_array(),'$.calculation.open_segment_start',null) where msku='sku'")
    frozen=result(db,sku='normal')[1]['history'][0]
    before = result(db)[1]
    assert before['identity']['anchor_status'] == 'pending'
    with db[0].cursor() as q:
        q.execute("insert into lx_sales_mws_listing (seller_name,seller_sku,asin,open_date_display,on_sale_time) values ('shop-DE','sku','ASIN','2026-01-01',null)")
        q.execute("update lx_statistics_product_performance set volume=999 where seller_sku='normal' and start_date<='2026-01-30'")
    call(db, 'incremental', '2026-03-31')
    ev = result(db)[1]
    assert ev['identity']['anchor_date'] == '2026-01-01'
    assert len(ev['history']) == 3
    assert ev['history'][0]['start'] == '2026-01-01'
    assert ev['history'][0]['observed_days'] == 30
    assert ev['history'][1]['observed_days'] == 30
    assert result(db,sku='normal')[1]['history'][0]==frozen


def test_imported_pending_record_uses_saved_first_observation_without_listing_or_recent_rows(db):
    seed(db,days=35)
    seed(db,days=30,sku='old',volume=0,stock=0,id_offset=1000)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='' where seller_sku='old'")
    call(db,'bootstrap','2026-02-04')
    with db[0].cursor() as q:
        q.execute("update dws_product_sales_role_history set evidence_json=json_set(evidence_json,'$.identity.anchor_date',null,'$.identity.anchor_status','pending','$.identity.candidate_date',null,'$.history',json_array(),'$.calculation.open_segment_start',null) where msku='old'")
        q.execute("delete from lx_sales_mws_listing where seller_sku='old'")
    seed(db,days=1,anchor='2026-02-05',id_offset=5000)
    call(db,'incremental','2026-02-05')
    doc=result(db,sku='old')[1]
    assert doc['identity']['anchor_date']=='2026-01-01'
    assert doc['identity']['anchor_source']=='first_performance_record'
    assert doc['identity']['asins']==['ASIN']
    assert doc['history'][0]['observed_days']==30
    assert doc['history'][0]['sales_qty']==0
    assert doc['history'][0]['role_id']==1304


def test_scheduled_initializes_legacy_pending_at_same_cutoff_and_only_reads_required_products(db):
    seed(db,days=35)
    seed(db,days=30,sku='old',volume=0,stock=0,id_offset=1000)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='' where seller_sku='old'")
    call(db,'bootstrap','2026-02-04')
    before=result(db)
    with db[0].cursor() as q:
        q.execute("update dws_product_sales_role_history set evidence_json=json_set(evidence_json,'$.identity.anchor_date',null,'$.identity.anchor_status','pending','$.identity.candidate_date',null,'$.history',json_array(),'$.calculation.open_segment_start',null) where msku='old'")
        q.execute("update lx_statistics_product_performance set end_date='2026-03-01' where seller_sku='sku' and start_date='2026-01-01'")
    response=scheduled_call(db)
    assert response[0]['status']=='success'
    assert response[0]['published_products']==2
    doc=result(db,sku='old')[1]
    assert doc['identity']['anchor_date']=='2026-01-01'
    assert doc['history'][0]['observed_days']==30
    assert doc['history'][0]['role_id']==1304
    assert result(db)==before
    assert scheduled_call(db)[0]['reason']=='already_current'


def test_legacy_pending_archive_initializes_once_without_changing_frozen_products(db):
    seed(db,days=61,anchor='2025-12-01')
    seed(db,days=30,anchor='2025-12-15',sku='old',volume=0,stock=0,id_offset=1000)
    with db[0].cursor() as q:
        for suffix in ('_2025',''):
            q.execute(f"update lx_statistics_product_performance{suffix} set product_create_time='' where seller_sku='old'")
    call(db,'bootstrap','2026-01-30')
    normal_before=result(db)
    bu_before=result(db,'business_unit')
    with db[0].cursor() as q:
        q.execute("update dws_product_sales_role_history set evidence_json=json_set(evidence_json,'$.identity.anchor_date',null,'$.identity.anchor_status','pending','$.identity.candidate_date',null,'$.history',json_array(),'$.calculation.open_segment_start',null) where msku='old'")
        q.execute("update lx_statistics_product_performance_2025 set end_date='2025-12-31' where seller_sku='sku' and start_date='2025-12-01'")
    assert scheduled_call(db)[0]['published_products']==2
    doc=result(db,sku='old')[1]
    assert doc['identity']['anchor_date']=='2025-12-15'
    assert doc['identity']['asins']==['ASIN']
    assert doc['history'][0]['observed_days']==30
    assert doc['history'][0]['role_id']==1304
    assert result(db)==normal_before
    assert result(db,'business_unit')==bu_before
    with db[0].cursor() as q:
        for year in range(2020,2026):q.execute(f'drop table lx_statistics_product_performance_{year}')
    seed(db,days=1,anchor='2026-01-31',id_offset=9000)
    assert scheduled_call(db)[0]['status']=='success'
    assert result(db,sku='old')[1]['history'][0]==doc['history'][0]


def test_pending_backfill_keeps_business_unit_costs_before_station_anchor(db):
    seed(db,days=31)
    seed(db,days=31,country='法国',id_offset=1000)
    seed(db,days=30,anchor='2025-12-15',sku='old',volume=0,stock=0,id_offset=2000)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='2026-01-10' where country='法国'")
        q.execute("update lx_statistics_product_performance set volume=0,amount=0,predict_gross_profit=-6,afn_fulfillable_quantity=0 where country='法国' and start_date<'2026-01-10'")
        for suffix in ('_2025',''):
            q.execute(f"update lx_statistics_product_performance{suffix} set product_create_time='' where seller_sku='old'")
    call(db,'bootstrap','2026-01-20')
    with db[0].cursor() as q:
        q.execute("update dws_product_sales_role_history set evidence_json=json_set(evidence_json,'$.identity.anchor_date',null,'$.identity.anchor_status','pending','$.identity.candidate_date',null,'$.history',json_array(),'$.calculation.open_segment_start',null) where msku='old'")
    call(db,'incremental','2026-01-31')
    period=result(db,'business_unit')[1]['history'][0]
    assert period['predict_gross_profit']==966  # DE 30*20 + FR 21*20 - 9*6
    assert period['sales_amount']==5100
    assert period['sales_qty']==306


def test_listing_date_anchors_zero_sales_rows_without_reading_old_years(db):
    seed(db, days=50)
    with db[0].cursor() as q:
        q.execute("insert into lx_sales_mws_listing (seller_name,seller_sku,asin,open_date_display) values ('shop-DE','pending','ASIN','2022-09-24')")
    call(db, 'bootstrap', '2026-02-04')
    assert result(db,sku='pending')[1]['identity']['anchor_status']=='pending'
    seed(db,days=15,anchor='2026-02-05',sku='pending',volume=0,stock=0,id_offset=1000)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='' where seller_sku='pending'")
        for year in range(2020,2026):q.execute(f'drop table lx_statistics_product_performance_{year}')
    call(db, 'incremental', '2026-02-19')
    doc=result(db,sku='pending')[1]
    assert doc['identity']['anchor_status']=='established'
    assert doc['identity']['anchor_date']=='2022-09-24'
    assert doc['identity']['first_observed']=='2026-02-05'
    assert sum(n['observed_days'] for n in doc['history'])==15
    assert doc['history'][-1]['role_id']==1304
    assert all(n['role_id'] is None and n['sales_qty'] is None for n in doc['history'] if n['observed_days']==0)
    assert doc['dominant_role']['role_id'] is None


def test_late_positive_product_fills_missing_segments_without_reading_old_years(db):
    seed(db, days=50)
    with db[0].cursor() as q:
        q.execute("insert into lx_sales_mws_listing (seller_name,seller_sku,asin,open_date_display) values ('shop-DE','late','ASIN','2022-09-24')")
    call(db, 'bootstrap', '2026-02-04')
    frozen=result(db)[1]['history'][0]
    seed(db,days=15,anchor='2026-02-05',sku='late',id_offset=1000)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='' where seller_sku='late'")
        for year in range(2020,2026):q.execute(f'drop table lx_statistics_product_performance_{year}')
    call(db, 'incremental', '2026-02-19')
    doc=result(db,sku='late')[1]
    assert doc['identity']['anchor_date']=='2022-09-24'
    assert doc['history'][0]['sales_qty'] is None
    assert doc['history'][0]['observed_days']==0
    assert sum(node['sales_qty'] or 0 for node in doc['history'])==90
    assert doc['dominant_role']['valid_segment_count']==0
    assert result(db)[1]['history'][0]==frozen


def test_pending_first_observation_survives_shorter_windows_and_later_activation(db):
    seed(db,days=64)
    with db[0].cursor() as q:
        q.execute("insert into lx_sales_mws_listing (seller_name,seller_sku,asin,open_date_display) values ('shop-DE','late','ASIN','2022-09-24')")
    call(db,'bootstrap','2026-02-04')
    seed(db,days=15,anchor='2026-02-05',sku='late',volume=0,stock=0,id_offset=1000)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='' where seller_sku='late'")
    call(db,'incremental','2026-03-01')
    call(db,'incremental','2026-03-02')
    assert result(db,sku='late')[1]['identity']['first_observed']=='2026-02-05'
    frozen=result(db)[1]['history'][:2]
    seed(db,days=2,anchor='2026-03-04',sku='late',id_offset=5000)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='' where seller_sku='late'")
        for year in range(2020,2026):q.execute(f'drop table lx_statistics_product_performance_{year}')
    call(db,'incremental','2026-03-05')
    doc=result(db,sku='late')[1]
    assert doc['identity']['anchor_date']=='2022-09-24'
    assert doc['identity']['first_observed']=='2026-02-05'
    assert sum(n['observed_days'] for n in doc['history'])==17
    assert sum(n['sales_qty'] or 0 for n in doc['history'])==12
    assert result(db)[1]['history'][:2]==frozen


def test_failed_product_publication_is_atomic_and_retryable(db):
    seed(db, days=35)
    with db[0].cursor() as q:
        q.execute("""create trigger fail_history_product before insert on dws_product_sales_role_history
            for each row begin
              if new.scope_mode='country' then
                signal sqlstate '45000' set message_text='injected publication failure';
              end if;
            end""")
    with pytest.raises(pymysql.MySQLError, match='injected publication failure'):
        call(db, 'bootstrap', '2026-02-04')
    with db[0].cursor() as q:
        q.execute("select status,published_products from dws_product_sales_role_history_run_log order by started_at desc limit 1")
        run = q.fetchone()
        assert run['status'] == 'failed'
        q.execute("select count(*) n from dws_product_sales_role_history where scope_mode='country'")
        assert q.fetchone()['n'] == 0
        q.execute('select count(*) n from dws_product_sales_role_history')
        assert q.fetchone()['n'] == run['published_products']
        q.execute('drop trigger fail_history_product')
    call(db, 'bootstrap', '2026-02-04')
    assert len(result(db)[1]['history']) == 2
    assert len(result(db, 'business_unit')[1]['history']) == 2


def test_anchor_is_frozen_until_explicit_full_reset(db):
    seed(db, days=35)
    call(db, 'bootstrap', '2026-02-04')
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='2025-12-22'")
    call(db, 'incremental', '2026-02-04')
    assert result(db)[1]['identity']['anchor_date'] == '2026-01-01'
    with db[0].cursor() as q:
        q.execute('call sp_product_role_history(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  ('rebuild', '2026-02-04', db[1], '2020-01-01', '2026-02-04',
                   'country', '欧洲站', '德国', 'shop', 'sku', 1, 7))
        while q.nextset():
            pass
    ev = result(db)[1]
    assert ev['identity']['anchor_date'] == '2025-12-22'
    assert ev['history'][0]['start'] == '2025-12-22'
    assert ev['history'][0]['observed_days'] == 20
    assert ev['history'][0]['vote_eligible'] == 0


def test_full_msku_multiple_asins_and_latest_rank(db):
    sku = 'X' * 500
    seed(db, days=35, sku=sku)
    with db[0].cursor() as q:
        q.execute("""insert into lx_statistics_product_performance
            select id+1000,seller_name,country,seller_sku,'OTHER_ASIN',start_date,end_date,
              product_create_time,volume,amount,predict_gross_profit,afn_fulfillable_quantity,
              51,'2026-03-01' from lx_statistics_product_performance where id<=35""")
    call(db, 'bootstrap', '2026-02-04')
    row, ev = result(db, sku=sku)
    assert len(row['msku']) == 500
    assert ev['history'][0]['sales_qty'] == 360
    assert ev['history'][0]['observed_days'] == 30
    assert ev['history'][0]['small_rank'] == 51
    assert ev['history'][0]['role_id'] == 1302
    assert set(ev['identity']['asins']) == {'ASIN', 'OTHER_ASIN'}


def test_incremental_date_index_explain(db):
    seed(db, days=90)
    with db[0].cursor() as q:
        q.execute("""explain select id from lx_statistics_product_performance force index(idx_date)
            where start_date between '2026-03-01' and '2026-03-31' and id>0 order by id limit 7""")
        plan = q.fetchone()
        assert plan['key'] == 'idx_date'
        assert plan['type'] == 'range'


def test_delivered_entry_scripts_run_in_isolated_schema(db):
    seed(db)
    for name, cutoff in [('bootstrap', '2026-02-04'), ('incremental', '2026-03-31'),
                         ('rebuild', '2026-03-31')]:
        script = read_section(name)
        script = script.replace('dws_datasync', db[1]).replace('dwd_datasync', db[1])
        script = script.replace('set @role_history_cutoff=null;', f"set @role_history_cutoff='{cutoff}';")
        script = script.replace('set @role_history_store=null;', "set @role_history_store='shop';")
        script = script.replace('set @role_history_msku=null;', "set @role_history_msku='sku';")
        script = script.replace('set @role_history_from=null;', "set @role_history_from='2026-01-03';")
        script = script.replace('set @role_history_to=null;', "set @role_history_to='2026-01-04';")
        execute_script(db[0], script)
        assert result(db)[0]['data_date'].isoformat() == cutoff
    assert len(result(db)[1]['history']) == 3


def test_readonly_acceptance_queries_execute(db):
    seed(db, days=30)
    call(db, 'bootstrap', '2026-01-30')
    with db[0].cursor() as q:
        q.execute("insert into lx_sales_mws_listing (seller_name,seller_sku,asin,open_date_display) values ('shop-DE','sku','ASIN','2026-01-01'),('shop-DE','amzn.gr.placeholder','ASIN','2026-01-01')")
        q.execute('alter table lx_statistics_product_performance add index idx_osp_performance_date_sync(start_date,id)')
        q.execute('''create table dws_标签表 (data_date date,country_category varchar(20),country varchar(100),
            store varchar(100),msku varchar(500),label_id int,label_period varchar(10),evidence_json json)''')
        q.execute('''insert into dws_标签表 values ('2026-01-30','欧洲站','德国','shop','sku',1301,'30d',
            json_object('window',json_object('start','2026-01-01','end','2026-01-30'),
              'metrics',json_object('period_sales_qty',180,'daily_sales',6,'tag_margin_rate',20,'small_rank',20)))''')
    script = read_section('acceptance')
    script = script.replace('dws_datasync', db[1]).replace('dwd_datasync', db[1])
    script = script.replace('set @role_check_store=null;', "set @role_check_store='shop';")
    script = script.replace('set @role_check_msku=null;', "set @role_check_msku='sku';")
    execute_script(db[0], script)


def test_country_and_business_anchors_remain_consistent_on_reset(db):
    seed(db, days=60)
    seed(db, days=60, country='法国', id_offset=1000)
    call(db, 'bootstrap', '2026-02-04')
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set product_create_time='2025-12-01' where country='法国'")
    call(db, 'incremental', '2026-03-01')
    with db[0].cursor() as q:
        q.execute("select evidence_json from dws_product_sales_role_history where scope_mode='country' and country='法国'")
        assert json.loads(q.fetchone()['evidence_json'])['identity']['anchor_date'] == '2026-01-01'
        q.execute('call sp_product_role_history(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  ('rebuild', '2026-03-01', db[1], '2020-01-01', '2026-03-01',
                   'business_unit', '欧洲站', '', 'shop', 'sku', 1, 7))
        while q.nextset():
            pass
    assert result(db, 'business_unit')[1]['identity']['anchor_date'] == '2026-01-01'
    assert result(db, 'business_unit')[1]['history'][0]['vote_eligible'] == 1


def test_missing_entire_period_is_not_a_zero_sales_problem(db):
    seed(db, days=35)
    seed(db, days=90, sku='calendar_product', id_offset=1000)
    call(db, 'bootstrap', '2026-03-31')
    node = result(db)[1]['history'][2]
    assert node['complete'] == 1
    assert node['observed_days'] == 0
    assert node['role_id'] is None
    assert node['sales_qty'] is None
    assert node['daily_sales'] is None
    assert node['vote_eligible'] == 0
    assert node['exclusion_reason'] == 'missing_daily_data'


def test_anomaly_and_latest_invalid_rank_follow_current_rules(db):
    seed(db, days=30)
    with db[0].cursor() as q:
        q.execute('update lx_statistics_product_performance set afn_fulfillable_quantity=null where id=5')
        q.execute('update lx_statistics_product_performance set `rank`=99999 where id=30')
    call(db, 'bootstrap', '2026-01-30')
    node = result(db)[1]['history'][0]
    assert node['small_rank'] == 99999
    assert node['small_rank_date'] == '2026-01-30'
    assert node['role_id'] == 1303
    assert node['anomaly_days'] == 1
    assert node['vote_eligible'] == 0
    assert node['exclusion_reason'] == 'source_anomaly'


def test_cross_year_anchor_candidates_keep_earliest_evidence(db):
    seed(db, days=400, anchor='2020-01-01')
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance_2020 set product_create_time='2019-12-10'")
        q.execute("update lx_statistics_product_performance_2021 set product_create_time='2021-01-01'")
        q.execute("insert into lx_sales_mws_listing (seller_name,seller_sku,asin,open_date_display,on_sale_time) values ('shop-DE','sku','ASIN','2021-01-05',null)")
    call(db, 'bootstrap', '2021-02-03')
    assert result(db)[1]['identity']['anchor_date'] == '2019-12-10'


def test_same_cutoff_incremental_needs_no_source_access(db):
    seed(db, days=35)
    call(db, 'bootstrap', '2026-02-04')
    before = result(db)
    with db[0].cursor() as q:
        q.execute('drop table lx_sales_mws_listing')
        q.execute('drop table lx_statistics_product_performance')
    call(db, 'incremental', '2026-02-04')
    assert result(db) == before


def scheduled_call(db):
    with db[0].cursor() as q:
        q.execute('call sp_product_role_history_incremental()')
        rows=q.fetchall()
        while q.nextset():
            pass
    return rows


def test_scheduled_incremental_uses_latest_source_day(db):
    seed(db, days=35)
    call(db, 'bootstrap', '2026-01-30')
    frozen=result(db)[1]['history'][0]
    rows=scheduled_call(db)
    assert rows[0]['status']=='success'
    row,doc=result(db)
    assert str(row['data_date'])=='2026-02-04'
    assert doc['history'][0]==frozen
    assert len(doc['history'])==2


def test_scheduled_incremental_skips_unchanged_source_day(db):
    seed(db, days=35)
    call(db, 'bootstrap', '2026-02-04')
    before=result(db)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set volume=999 where id=35")
    rows=scheduled_call(db)
    assert rows[0]['reason']=='already_current'
    assert result(db)==before


def test_scheduled_incremental_recovers_partially_processed_pool(db):
    seed(db, days=35)
    call(db, 'bootstrap', '2026-02-04')
    with db[0].cursor() as q:
        q.execute("update dws_product_sales_role_history set data_date='2026-02-03' where scope_mode='country'")
    rows=scheduled_call(db)
    assert rows[0]['status']=='success'
    assert str(result(db)[0]['data_date'])=='2026-02-04'


def test_scheduled_incremental_does_not_move_backwards(db):
    seed(db, days=35)
    call(db, 'bootstrap', '2026-02-04')
    before=result(db)
    with db[0].cursor() as q:
        q.execute("delete from lx_statistics_product_performance where start_date>'2026-02-03'")
    assert scheduled_call(db)[0]['reason']=='source_date_behind_history'
    assert result(db)==before


def test_scheduled_incremental_skips_empty_and_current_day(db):
    assert scheduled_call(db)[0]['reason']=='source_empty'
    today=date.today()
    seed(db, days=1, anchor=today.isoformat())
    assert scheduled_call(db)[0]['reason']=='latest_day_not_closed'


def test_listing_pool_covers_both_grains_without_fabricating_history(db):
    seed(db, days=35)
    with db[0].cursor() as q:
        q.execute("insert into lx_sales_mws_listing (marketplace,seller_name,seller_sku,asin,open_date_display) values ('英国','shop-UK','missing','A','2020-01-01'),('美国','shop-US','undated','B',null),('法国','shop-FR','sku','ASIN',null)")
    call(db, 'bootstrap', '2026-02-04')
    for sku in ('missing', 'undated'):
        for scope in ('country', 'business_unit'):
            row, doc = result(db, scope, sku)
            assert doc['identity']['anchor_status'] == 'pending'
            assert doc['identity']['anchor_date'] is None
            assert doc['history'] == []
            assert doc['dominant_role']['role_id'] is None
            assert doc['dominant_role']['valid_segment_count'] == 0
    with db[0].cursor() as q:
        q.execute("select evidence_json from dws_product_sales_role_history where scope_mode='country' and country='法国' and msku='sku'")
        assert json.loads(q.fetchone()['evidence_json'])['history'] == []
    assert result(db, 'business_unit')[1]['history'][0]['sales_qty'] == 180


def test_same_cutoff_discovers_new_listing_country_and_business_unit(db):
    seed(db, days=35)
    call(db, 'bootstrap', '2026-02-04')
    country_before, bu_before = result(db), result(db, 'business_unit')
    with db[0].cursor() as q:
        q.execute("insert into lx_sales_mws_listing (marketplace,seller_name,seller_sku,asin) values ('法国','shop-FR','sku','ASIN'),('英国','shop-UK','new','A')")
    call(db, 'incremental', '2026-02-04')
    assert result(db) == country_before
    assert result(db, 'business_unit') == bu_before
    assert result(db, 'business_unit', 'new')[1]['history'] == []
    with db[0].cursor() as q:
        q.execute("select evidence_json from dws_product_sales_role_history where scope_mode='country' and country='法国' and msku='sku'")
        assert json.loads(q.fetchone()['evidence_json'])['history'] == []
        q.execute('select count(*) n from dws_product_sales_role_history')
        assert q.fetchone()['n'] == 5
    call(db, 'incremental', '2026-02-04')
    assert result(db) == country_before
    assert result(db, 'business_unit') == bu_before


def test_listing_pool_invalid_identity_stops_before_ignore(db):
    seed(db, days=35)
    with db[0].cursor() as q:
        q.execute("insert into lx_sales_mws_listing (marketplace,seller_name,seller_sku,asin) values (null,'shop-DE','missing','A')")
    with pytest.raises(pymysql.MySQLError, match='invalid Listing identity'):
        call(db, 'bootstrap', '2026-02-04')


def test_listing_candidate_dates_are_isolated_by_country(db):
    seed(db, days=35)
    with db[0].cursor() as q:
        q.execute("insert into lx_sales_mws_listing (marketplace,seller_name,seller_sku,asin,open_date_display) values ('德国','other-DE','missing','A','2020-01-01'),('法国','other-FR','missing','A','2021-02-01')")
    call(db, 'bootstrap', '2026-02-04')
    with db[0].cursor() as q:
        q.execute("select country,evidence_json from dws_product_sales_role_history where scope_mode='country' and msku='missing'")
        dates = {r['country']: json.loads(r['evidence_json'])['identity']['candidate_date'] for r in q.fetchall()}
    assert dates == {'德国': '2020-01-01', '法国': '2021-02-01'}


def test_recent_id_batches_handle_shuffled_ids_and_multicolumn_date_index(db):
    seed(db, days=60)
    call(db, 'bootstrap', '2026-02-04')
    with db[0].cursor() as q:
        q.execute('alter table lx_statistics_product_performance add index idx_osp_performance_date_sync(start_date,end_date,create_time)')
        q.execute('update lx_statistics_product_performance set id=10000-id')
        q.execute('''insert into lx_statistics_product_performance
            select 1,seller_name,country,seller_sku,asin,start_date,end_date,product_create_time,
              9,90,18,afn_fulfillable_quantity,`rank`,'2026-03-02'
            from lx_statistics_product_performance where start_date='2026-02-15' ''')
        # Not in the requested recent range; its invalid grain must not abort the call.
        q.execute("update lx_statistics_product_performance set end_date='2026-01-02' where start_date='2026-01-01'")
    call(db, 'incremental', '2026-03-01')
    nodes = result(db)[1]['history']
    assert nodes[0]['sales_qty'] == 180
    assert nodes[1]['sales_qty'] == 183
    assert nodes[1]['observed_days'] == 30


def test_history_assembly_preserves_frozen_json_hash_and_session_limit(db):
    seed(db, days=90)
    script=SQL.read_text(encoding='utf-8').replace('dws_datasync',db[1])
    start=script.index('        -- 只拼接按周期排序的数字路径')
    end=script.index('        -- history assembly:end',start)
    baseline=script[:start]+"""        set v_history=json_array();
        if v_total>0 then
            select h into v_history from (select json_arrayagg(node_doc) over(order by period_no rows between unbounded preceding and unbounded following) h from tmp_hr_nodes) a limit 1;
        end if;
"""+script[end:]
    execute_script(db[0],baseline)
    with db[0].cursor() as q:
        q.execute('update lx_statistics_product_performance set amount=123.4567,predict_gross_profit=23.1234')
        q.execute('set session group_concat_max_len=128')
    call(db, 'bootstrap', '2026-02-04')
    with db[0].cursor() as q:
        q.execute("select sha2(cast(json_extract(evidence_json,'$.history[0]') as char),256) h from dws_product_sales_role_history where scope_mode='country'")
        before=q.fetchone()['h']
    execute_script(db[0],script)
    call(db, 'incremental', '2026-03-31')
    with db[0].cursor() as q:
        q.execute("select sha2(cast(json_extract(evidence_json,'$.history[0]') as char),256) h from dws_product_sales_role_history where scope_mode='country'")
        assert q.fetchone()['h']==before
        q.execute('select @@session.group_concat_max_len n')
        assert q.fetchone()['n']==128
    assert [n['period_no'] for n in result(db)[1]['history']]==[1,2,3]


def test_missing_station_counts_start_at_each_station_anchor(db):
    seed(db, days=60)
    seed(db, days=45, country='法国', anchor='2026-01-16', id_offset=1000)
    with db[0].cursor() as q:
        q.execute("delete from lx_statistics_product_performance where country='法国' and start_date in ('2026-01-20','2026-02-15')")
    call(db, 'bootstrap', '2026-03-01')
    nodes=result(db,'business_unit')[1]['history']
    assert [n['missing_station_days'] for n in nodes]==[1,1]
    assert all(n['observed_days']==30 for n in nodes)
    assert all(n['vote_eligible']==0 for n in nodes)


def test_missing_station_counts_cover_fourteenth_window_in_leap_year(db):
    seed(db, days=425, anchor='2023-12-03')
    seed(db, days=425, country='法国', anchor='2023-12-03', id_offset=1000)
    with db[0].cursor() as q:
        q.execute("delete from lx_statistics_product_performance_2024 where country='法国' and start_date='2024-12-31'")
    call(db, 'bootstrap', '2025-01-30')
    node=result(db,'business_unit')[1]['history'][13]
    assert node['period_no']==14
    assert node['missing_station_days']==1
    assert node['exclusion_reason']=='missing_station_daily_data'


def test_calendar_prefix_preserves_global_gaps_across_year_and_leap_day(db):
    seed(db, days=400, anchor='2023-12-03')
    seed(db, days=400, country='法国', anchor='2023-12-03', id_offset=1000)
    with db[0].cursor() as q:
        q.execute("delete from lx_statistics_product_performance_2023 where start_date='2023-12-31'")
        q.execute("delete from lx_statistics_product_performance_2024 where start_date in ('2024-01-01','2024-02-29')")
        q.execute("delete from lx_statistics_product_performance_2024 where country='法国' and start_date in ('2024-01-02','2024-03-01')")
    call(db, 'bootstrap', '2025-01-05')
    nodes=result(db,'business_unit')[1]['history']
    # 全局没有该日时，旧日历口径也不计入应有站点日；仍因观测不足排除。
    assert nodes[0]['observed_days']==28
    assert nodes[0]['missing_station_days']==0
    assert nodes[0]['vote_eligible']==0
    assert nodes[1]['missing_station_days']==1
    assert nodes[2]['observed_days']==29
    assert nodes[2]['missing_station_days']==1
    assert nodes[2]['vote_eligible']==0


def test_partial_first_bootstrap_must_finish_before_incremental(db):
    seed(db, days=60)
    with db[0].cursor() as q:
        q.execute("""create trigger stop_partial_bootstrap before insert on dws_product_sales_role_history
          for each row begin
            if exists(select 1 from dws_product_sales_role_history) then
              signal sqlstate '45000' set message_text='stop after first committed product';
            end if;
          end""")
    with pytest.raises(pymysql.MySQLError,match='stop after first'):
        call(db,'bootstrap','2026-02-04')
    with db[0].cursor() as q:
        q.execute('select count(*) n from dws_product_sales_role_history')
        assert q.fetchone()['n']==1
        q.execute('drop trigger stop_partial_bootstrap')
    with pytest.raises(pymysql.MySQLError,match='complete bootstrap must succeed'):
        call(db,'incremental','2026-02-05')
    call(db,'bootstrap','2026-02-04')
    call(db,'incremental','2026-02-05')
    assert result(db)[0]['data_date']==date(2026,2,5)


def test_current_label_placeholder_sku_exclusions_in_full_and_incremental(db):
    seed(db,days=60)
    for i,sku in enumerate(['amzn.gr.refund','AMZN.GR.Mixed','Amazon-placeholder',' amazon.Mixed']):
        seed(db,days=60,sku=sku,id_offset=(i+1)*1000)
    with db[0].cursor() as q:
        q.execute("update lx_statistics_product_performance set end_date=null where seller_sku<>'sku'")
    call(db,'bootstrap','2026-01-30')
    call(db,'incremental','2026-01-31')
    with db[0].cursor() as q:
        q.execute('select scope_mode,msku from dws_product_sales_role_history order by scope_mode')
        assert q.fetchall()==[{'scope_mode':'business_unit','msku':'sku'},{'scope_mode':'country','msku':'sku'}]
    assert result(db,'business_unit')[1]['history'][0]['sales_qty']==180
