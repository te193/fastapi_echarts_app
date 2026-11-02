"""Exercise real primary-key semantics for fresh and existing budget stores."""
from datetime import date
import os
from uuid import uuid4

import pytest

from etl.dashboard_daily_update import (
    CREATE_AD_BUDGET_SNAPSHOT_SQL, SchemaConfig, connect_target, ensure_tables,
    render_sql, with_mysql_comments,
)

pytestmark = pytest.mark.skipif(
    os.getenv('LABEL_LOCAL_MYSQL_TEST') != '1', reason='isolated MySQL opt-in',
)


@pytest.fixture
def budget_schema():
    schema = 'label_validation_budget_case_' + uuid4().hex[:12]
    conn = connect_target()
    schemas = SchemaConfig(schema, schema, schema, schema)
    try:
        with conn.cursor() as q:
            q.execute(f'create database `{schema}` character set utf8mb4 collate utf8mb4_0900_ai_ci')
        yield conn, schemas
    finally:
        conn.rollback()
        assert schema.startswith('label_validation_budget_case_')
        with conn.cursor() as q:
            q.execute(f'drop database if exists `{schema}`')
        conn.close()


def insert_budget(conn, schemas, day, sku, amount):
    with conn.cursor() as q:
        q.execute(render_sql('''insert into etl_datasync.dashboard_ad_budget_snapshot
            (biz_date,country_category,country,seller_name_new,seller_sku_adj,
             product_type,monthly_ad_budget_cny)
            values (%s,%s,%s,%s,%s,%s,%s)''', schemas),
            (day, 'Europe', 'Germany', 'CHOOJEE', sku, 'old', amount))
    conn.commit()


def test_new_budget_table_preserves_case_distinct_mskus(budget_schema):
    conn, schemas = budget_schema
    with conn.cursor() as q:
        q.execute(with_mysql_comments(render_sql(CREATE_AD_BUDGET_SNAPSHOT_SQL, schemas)))
    for sku, amount in [('CJ016A', 12), ('CJ016a', 34)]:
        insert_budget(conn, schemas, date(2026, 10, 29), sku, amount)
    with conn.cursor() as q:
        q.execute(render_sql('''select seller_sku_adj, monthly_ad_budget_cny
            from etl_datasync.dashboard_ad_budget_snapshot order by binary seller_sku_adj''', schemas))
        assert [(r['seller_sku_adj'], float(r['monthly_ad_budget_cny'])) for r in q.fetchall()] == [
            ('CJ016A', 12), ('CJ016a', 34),
        ]


def test_existing_budget_initialization_preserves_history_and_is_idempotent(budget_schema):
    conn, schemas = budget_schema
    legacy = CREATE_AD_BUDGET_SNAPSHOT_SQL.replace(
        'collate utf8mb4_bin', 'collate utf8mb4_0900_ai_ci',
    )
    with conn.cursor() as q:
        q.execute(with_mysql_comments(render_sql(legacy, schemas)))
        q.execute('''select column_comment from information_schema.columns where
            table_schema=%s and table_name='dashboard_ad_budget_snapshot'
            and column_name='seller_sku_adj' ''', (schemas.target_schema,))
        original_comment = q.fetchone()['COLUMN_COMMENT']
    insert_budget(conn, schemas, date(2026, 10, 28), 'CJ016A', 56)
    ensure_tables(conn, schemas)
    for sku, amount in [('CJ016A', 12), ('CJ016a', 34)]:
        insert_budget(conn, schemas, date(2026, 10, 29), sku, amount)
    ensure_tables(conn, schemas)
    with conn.cursor() as q:
        q.execute('''select collation_name, column_comment from information_schema.columns
            where table_schema=%s and table_name='dashboard_ad_budget_snapshot'
            and column_name='seller_sku_adj' ''', (schemas.target_schema,))
        column = q.fetchone()
        assert column['COLLATION_NAME'] == 'utf8mb4_bin'
        assert column['COLUMN_COMMENT'] == original_comment
        q.execute(render_sql('''select biz_date,seller_sku_adj,monthly_ad_budget_cny
            from etl_datasync.dashboard_ad_budget_snapshot
            order by biz_date,binary seller_sku_adj''', schemas))
        assert [(str(r['biz_date']), r['seller_sku_adj'], float(r['monthly_ad_budget_cny']))
                for r in q.fetchall()] == [
            ('2026-10-28', 'CJ016A', 56), ('2026-10-29', 'CJ016A', 12),
            ('2026-10-29', 'CJ016a', 34),
        ]
