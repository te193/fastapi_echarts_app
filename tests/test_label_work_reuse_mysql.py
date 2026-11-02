"""Work reuse must verify every archived fact, not just counts or metadata."""
from datetime import date
from decimal import Decimal
import json
from uuid import uuid4

import pytest

from test_label_local_store_mysql import local_store, seed
from etl.label_local_store import archive_day, restore_work, validate_day, table


@pytest.fixture
def accepted_work(local_store):
    conn, schema = local_store
    seed(conn, schema)
    day = date(2026, 10, 7)
    archive_day(conn, schema, day, str(uuid4()),
                {'batch_id':str(uuid4()),'input_hash':'a'*64}, day, validate_day(conn,schema,day))
    restore_work(conn, schema, [day])
    return conn, schema, day


def test_exactly_verified_work_is_reused_without_changing_row_ids(accepted_work):
    conn, schema, day = accepted_work
    work = table(schema,'dashboard_label_local_work')
    with conn.cursor() as q:
        q.execute(f'select id from {work}')
        before = q.fetchall()
    restore_work(conn, schema, [day])
    with conn.cursor() as q:
        q.execute(f'select id from {work}')
        assert q.fetchall() == before


@pytest.mark.parametrize('change', ['evidence','header','created_time','missing','extra_date'])
def test_any_work_difference_forces_archive_restore(accepted_work, change):
    conn, schema, day = accepted_work
    work = table(schema,'dashboard_label_local_work')
    with conn.cursor() as q:
        q.execute(f'select created_time from {work}')
        original_created = q.fetchone()['created_time']
        if change == 'evidence':
            q.execute(f"update {work} set evidence_json=json_set(evidence_json,'$.metrics.daily_sales',2.0000000000000001)")
        elif change == 'header':
            q.execute(f"update {work} set country='德国'")
        elif change == 'created_time':
            q.execute(f"update {work} set created_time='2000-01-01'")
        elif change == 'missing':
            q.execute(f'delete from {work}')
        else:
            q.execute(f"insert into {work}(data_date,country_category,store,msku,label_id,label_period,evidence_json) values ('2026-10-08','欧洲站','other','extra',101,'30d',json_object())")
    conn.commit()
    restore_work(conn, schema, [day])
    with conn.cursor() as q:
        q.execute(f'select data_date,country,evidence_json,created_time from {work}')
        rows = q.fetchall()
        assert len(rows)==1 and rows[0]['data_date']==day and rows[0]['country'] is None
        assert json.loads(rows[0]['evidence_json'],parse_float=Decimal)['metrics']['daily_sales']==Decimal(2)
        assert rows[0]['created_time']==original_created


def test_difference_in_second_archive_chunk_is_not_hidden_by_first_chunk(accepted_work):
    conn, schema, day = accepted_work
    work = table(schema,'dashboard_label_local_work')
    with conn.cursor() as q:
        q.executemany(f"insert into {work}(data_date,country_category,store,msku,label_id,label_period,evidence_json) values (%s,'欧洲站','shop',%s,101,'30d',json_object('n',1))",[(day,f'SKU-{i:04d}') for i in range(1000)])
    archive_day(conn,schema,day,str(uuid4()),{'batch_id':str(uuid4()),'input_hash':'a'*64},day,validate_day(conn,schema,day))
    with conn.cursor() as q:
        q.execute(f"update {work} set evidence_json=json_object('n',2) where msku='SKU-0999'")
    conn.commit()
    restore_work(conn,schema,[day])
    with conn.cursor() as q:
        q.execute(f"select evidence_json from {work} where msku='SKU-0999'")
        assert json.loads(q.fetchone()['evidence_json'])=={'n':1}


def test_corrupt_archive_is_rejected_even_when_work_looks_complete(accepted_work):
    conn, schema, day = accepted_work
    with conn.cursor() as q:
        q.execute(f"update {table(schema,'dashboard_label_local_history')} set checksum=%s", ('0'*64,))
    conn.commit()
    with pytest.raises(ValueError, match='checksum'):
        restore_work(conn,schema,[day])
