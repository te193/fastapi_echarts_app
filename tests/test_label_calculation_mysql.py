"""Opt-in result and access-path checks in a disposable MySQL schema."""
from datetime import datetime
import re

import pytest

from test_label_local_store_mysql import local_store
from etl.label_local_sql import compile_procedure


def test_fba_lookup_preserves_latest_snapshot_sums_and_text_matching(local_store):
    conn, schema = local_store
    old = compile_procedure(schema, optimize_calculation=False)
    new = compile_procedure(schema)
    with conn.cursor() as q:
        q.execute("set time_zone='+08:00'")
        q.execute(f"""create table `{schema}`.dashboard_label_source_fba (
            seller_sku_adj varchar(255),create_time datetime,
            country_category varchar(32),seller_name_new varchar(100),
            afn_fulfillable_quantity decimal(18,4),stock_up_num decimal(18,4),total decimal(18,4),
            key id1(seller_sku_adj,create_time,country_category,seller_name_new)
        ) character set utf8mb4 collate utf8mb4_0900_ai_ci""")
        q.execute("""create temporary table tmp_listing_keys (
            country_category varchar(20),store varchar(100),msku varchar(255),
            key lookup_key(country_category,store,msku)
        ) character set utf8mb4 collate utf8mb4_0900_ai_ci""")
        q.execute("insert into tmp_listing_keys values ('欧洲站','SHOP','SKU'),('欧洲站','SHOP','Café'),('欧洲站','SHOP','missing')")
        q.executemany(f"insert into `{schema}`.dashboard_label_source_fba values (%s,%s,%s,%s,%s,%s,%s)", [
            ('SKU','2026-10-14','欧洲站','SHOP-DE',99,98,97),
            ('SKU','2026-10-15 08:00:00','欧洲站','SHOP-DE',1,2,3),
            ('SKU','2026-10-15 09:00:00','欧洲站','SHOP-DE',4,5,6),
            ('sku','2026-10-15 09:00:00','欧洲站','shop-AT',7,8,9),
            ('SKU','2026-10-16','欧洲站','SHOP-DE',90,90,90),
            ('SKU','2026-10-15 10:00:00','北美站','SHOP-US',90,90,90),
            ('SKU','2026-10-15 10:00:00','欧洲站','OTHER-DE',90,90,90),
            ('cafe','2026-10-15 10:00:00','欧洲站','SHOP UK',2,3,4),
            ('SKU ','2026-10-15 11:00:00','欧洲站','SHOP-DE',90,90,90),
            (None,'2026-10-15','欧洲站','SHOP-DE',90,90,90),
        ] + [(f'unrelated-{i}','2026-10-15','欧洲站','OTHER-DE',1,1,1) for i in range(1000)])
        results = []
        for sql in (old, new):
            for name in ('tmp_op_fba_latest_key', 'tmp_op_fba'):
                q.execute(f'drop temporary table if exists {name}')
                statement = re.search(r'create temporary table ' + name + r'\b.*?;', sql, re.S).group()
                statement = statement.replace('v_next_date', "date('2026-10-16')")
                q.execute(statement)
            q.execute('select * from tmp_op_fba order by msku')
            results.append(q.fetchall())
        assert results[0] == results[1]
        assert [(r['msku'],r['fba_available'],r['fba_in_transit'],r['total_stock']) for r in results[1]] == [
            ('Café',2,3,4), ('SKU',11,13,15),
        ]
        q.execute("select max_create_time from tmp_op_fba_latest_key where msku='SKU'")
        assert q.fetchone()['max_create_time'] == datetime(2026,10,15,9)
        select = re.search(r'create temporary table tmp_op_fba_latest_key as\s*(.*?);', new, re.S).group(1)
        q.execute('explain ' + select.replace('v_next_date', "date('2026-10-16')"))
        fba = next(row for row in q.fetchall() if row['table'] == 'f')
        assert fba['type'] == 'ref' and fba['key'] == 'id1'


@pytest.mark.parametrize('fail', [False, True])
def test_calculation_memory_is_limited_to_the_connection_and_restored(local_store, fail):
    from etl.label_calculation_session import calculation_session

    conn, _ = local_store
    with conn.cursor() as q:
        q.execute('set session sort_buffer_size=262144,tmp_table_size=16777216')
    try:
        with calculation_session(conn):
            with conn.cursor() as q:
                q.execute('select @@sort_buffer_size as sort_bytes,@@tmp_table_size as temp_bytes')
                assert q.fetchone() == {'sort_bytes':8388608, 'temp_bytes':268435456}
            if fail:
                raise RuntimeError('calculation failed')
    except RuntimeError as exc:
        assert fail and str(exc) == 'calculation failed'
    with conn.cursor() as q:
        q.execute('select @@sort_buffer_size as sort_bytes,@@tmp_table_size as temp_bytes')
        assert q.fetchone() == {'sort_bytes':262144, 'temp_bytes':16777216}


def test_calculation_memory_keeps_larger_existing_session_limits(local_store):
    from etl.label_calculation_session import calculation_session

    conn, _ = local_store
    with conn.cursor() as q:
        q.execute('set session sort_buffer_size=16777216,tmp_table_size=536870912')
    with calculation_session(conn):
        with conn.cursor() as q:
            q.execute('select @@sort_buffer_size as sort_bytes,@@tmp_table_size as temp_bytes')
            assert q.fetchone() == {'sort_bytes':16777216, 'temp_bytes':536870912}
