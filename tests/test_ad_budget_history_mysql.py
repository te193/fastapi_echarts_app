"""Prove partial daily source windows cannot erase accepted local budget days."""
from datetime import date
import os
from uuid import uuid4

import pytest

from etl.dashboard_daily_update import (
    CREATE_LOG_TABLE_SQL, DELETE_AD_BUDGET_SNAPSHOT_SQL, SchemaConfig, SourceLoadStep, connect_target,
    execute_source_load_step, render_sql,
)

pytestmark = pytest.mark.skipif(os.getenv('LABEL_LOCAL_MYSQL_TEST') != '1', reason='isolated MySQL opt-in')


@pytest.fixture
def budget_store():
    schema = 'label_validation_budget_' + uuid4().hex[:12]
    target = connect_target()
    source = connect_target()
    schemas = SchemaConfig(schema, schema, schema, schema)
    try:
        with target.cursor() as q:
            q.execute(f'create database `{schema}`')
            for name in ('budget_target', 'budget_source'):
                q.execute(f'create table `{schema}`.`{name}` (biz_date date not null,sku varchar(20) not null,amount decimal(18,4) not null,primary key(biz_date,sku))')
            q.execute(render_sql(CREATE_LOG_TABLE_SQL, schemas))
            q.execute(f"insert into `{schema}`.budget_target values ('2026-10-13','old',13),('2026-10-14','old',14)")
        target.commit()
        step = SourceLoadStep('ad_budget_snapshot',
            DELETE_AD_BUDGET_SNAPSHOT_SQL.replace('etl_datasync.dashboard_ad_budget_snapshot', f'`{schema}`.budget_target'),
            f'select biz_date,sku,amount from `{schema}`.budget_source where biz_date >= %(budget_start_date)s order by biz_date,sku',
            f'`{schema}`.budget_target', ('biz_date','sku','amount'))
        params = {'biz_date':date(2026,10,14),'snapshot_date':date(2026,10,15),
                  'period_start':date(2026,7,17),'period_end':date(2026,10,14),
                  'budget_start_date':date(2026,10,1)}
        yield target,source,schema,schemas,step,params
    finally:
        source.close()
        target.rollback()
        with target.cursor() as q:
            assert schema.startswith('label_validation_budget_')
            q.execute(f'drop database if exists `{schema}`')
        target.close()


def test_partial_budget_source_preserves_absent_days_and_replaces_each_returned_day_once(budget_store):
    target,source,schema,schemas,step,params = budget_store
    with source.cursor() as q:
        q.execute(f"insert into `{schema}`.budget_source values ('2026-10-14','A',21),('2026-10-14','B',22),('2026-10-15','C',23)")
    source.commit()
    execute_source_load_step(target,source,schemas,step,params,batch_size=1)
    with target.cursor() as q:
        q.execute(f'select biz_date,sku,amount from `{schema}`.budget_target order by biz_date,sku')
        result = [(str(r['biz_date']),r['sku'],str(r['amount'])) for r in q.fetchall()]
    assert result == [('2026-10-13','old','13.0000'),('2026-10-14','A','21.0000'),
                      ('2026-10-14','B','22.0000'),('2026-10-15','C','23.0000')]


def test_empty_budget_source_keeps_existing_day_partitions(budget_store):
    target,source,schema,schemas,step,params = budget_store
    with pytest.raises(RuntimeError,match='0 rows'):
        execute_source_load_step(target,source,schemas,step,params,batch_size=1)
    with target.cursor() as q:
        q.execute(f'select biz_date,sku,amount from `{schema}`.budget_target order by biz_date')
        result = [(str(r['biz_date']),r['sku'],str(r['amount'])) for r in q.fetchall()]
    assert result == [('2026-10-13','old','13.0000'),('2026-10-14','old','14.0000')]
