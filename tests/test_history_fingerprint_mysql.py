"""Opt-in, tiny temporary-table tests. Never write a production schema."""
from contextlib import nullcontext
from datetime import date, datetime
from decimal import Decimal
import json
import os
import re
from uuid import uuid4

import pymysql
import pytest

from etl import dashboard_daily_update as daily
from etl.product_performance_history_sync import BATCH_TASK_NAME
from etl.shared_product_inputs import RUN_ENV


def connect_owned_schema(schema):
    assert re.fullmatch(r'test_etl_shared_[a-zA-Z0-9_]+', schema)
    return pymysql.connect(
        host=os.environ['DASHBOARD_DB_HOST'],
        port=int(os.getenv('DASHBOARD_DB_PORT', '3306')),
        user=os.environ['DASHBOARD_DB_USER'],
        password=os.environ['DASHBOARD_DB_PASSWORD'],
        database=schema, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5, read_timeout=15, write_timeout=10,
    )


class TracedCursor:
    def __init__(self, raw, writes):
        self.raw, self.writes = raw, writes

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, *args):
        return self.raw.__exit__(*args)

    def execute(self, sql, args=None):
        if sql.lstrip().lower().startswith(('delete ', 'insert ')):
            self.writes.append((sql, args))
        return self.raw.execute(sql, args)

    def executemany(self, sql, args):
        self.writes.append((sql, args))
        return self.raw.executemany(sql, args)

    def __getattr__(self, name):
        return getattr(self.raw, name)


class TracedConnection:
    def __init__(self, raw):
        self.raw, self.writes = raw, []

    def cursor(self):
        return TracedCursor(self.raw.cursor(), self.writes)

    def __getattr__(self, name):
        return getattr(self.raw, name)


@pytest.fixture
def history_database(monkeypatch, request):
    schema = os.getenv('DASHBOARD_HISTORY_FINGERPRINT_TEST_DB', '')
    if not schema:
        pytest.skip('set an explicitly owned test_etl_shared_ database to run MySQL tests')
    assert re.fullmatch(r'test_etl_shared_[a-zA-Z0-9_]+', schema)
    monkeypatch.delenv(RUN_ENV, raising=False)
    # Task logging is external to the row-reconciliation contract under test.
    monkeypatch.setattr(daily, 'log_task', lambda *args: None)
    conn = connect_owned_schema(schema)
    names = ['hist_fp_source_' + uuid4().hex[:8], 'hist_fp_target_' + uuid4().hex[:8]]
    definitions = []
    for column in daily.PRODUCT_DAILY_COLUMNS:
        kind = ('date' if column == 'dt_date' else
                'datetime' if column in {'created_at', 'updated_at'} else
                'decimal(18,4)' if column in daily.PRODUCT_FINGERPRINT_DECIMAL_COLUMNS else
                'bigint' if column in daily.PRODUCT_FINGERPRINT_INTEGER_COLUMNS else 'varchar(255)')
        definitions.append(f'`{column}` {kind} null')
    with conn.cursor() as q:
        from etl import product_consumer_contract as contract
        q.execute(contract.state_ddl(schema, temporary=True))
        monkeypatch.setattr(contract, 'ensure_state', lambda *args: None)
        for index, name in enumerate(names):
            if index == 1 and getattr(request, 'param', False):
                schemas = daily.SchemaConfig(schema, 'etl_datasync', 'dwd_datasync', 'temporary_dwd')
                ddl = daily.render_sql(daily.CREATE_PRODUCT_DAILY_SQL, schemas)
                ddl = ddl.replace('create table if not exists', 'create temporary table', 1)
                ddl = ddl.replace(f'{schema}.dashboard_product_performance_daily', f'{schema}.{name}')
                q.execute(ddl)
            else:
                q.execute(f'create temporary table `{name}` ({",".join(definitions)}) engine=innodb')
        for day in (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)):
            row = {column: 'value' for column in daily.PRODUCT_DAILY_COLUMNS}
            row.update({column: Decimal('10.0000') for column in daily.PRODUCT_FINGERPRINT_DECIMAL_COLUMNS})
            row.update({column: 1 for column in daily.PRODUCT_FINGERPRINT_INTEGER_COLUMNS})
            row.update(dt_date=day, item_key=f'item-{day.day}', local_sku=None)
            for index, name in enumerate(names):
                row.update(created_at=datetime(2026 if index == 0 else 2010, 1, 1),
                           updated_at=datetime(2026 if index == 0 else 2010, 1, 1))
                columns = ','.join(f'`{column}`' for column in daily.PRODUCT_DAILY_COLUMNS)
                values = ','.join(f'%({column})s' for column in daily.PRODUCT_DAILY_COLUMNS)
                q.execute(f'insert into `{name}` ({columns}) values ({values})', row)
    conn.commit()
    try:
        yield conn, schema, names
    finally:
        conn.close()  # MySQL discards these session-only tables automatically.


@pytest.fixture
def consumer_database(history_database, monkeypatch):
    from etl import product_consumer_contract as contract, shared_product_inputs as shared
    from etl.product_performance_history_sync import range_params
    conn, schema, (_, target) = history_database
    strings = {'country', 'seller_name', 'seller_sku', 'local_sku', 'start_date'}
    definitions = ','.join(f'`{column}` ' + ('varchar(255)' if column in strings else 'decimal(18,4)')
                           for column in contract.RAW_COLUMNS)
    with conn.cursor() as q:
        # Session temporary tables shadow only this owned-schema connection.
        q.execute(f'create temporary table `{shared.LOCAL_TABLE}` ({definitions},status varchar(255),page_views_mobile int) engine=InnoDB')
        for day in ('2026-01-01', '2026-01-02'):
            row = {column: 1 for column in contract.RAW_COLUMNS}
            row.update(start_date=day, country='德国', seller_name='seller-main',
                       seller_sku='SKU-1', local_sku='local', amount=10, predict_gross_profit=2)
            q.execute(f'insert into `{shared.LOCAL_TABLE}` ({",".join(f"`{c}`" for c in row)}) '
                      f'values ({",".join(f"%({c})s" for c in row)})', row)
    conn.commit()
    reader = shared.LocalProductConnection(conn, 'dwd_datasync', schema)
    reader.shared_product_item = dict(columns=list(shared.PRODUCT_COLUMNS), fingerprint_version='test-v1',
        partitions={'2026-01-01': {'hash': 'first'}, '2026-01-02': {'hash': 'second'}},
        shared_acquisition={'run_id': 'owned_consumer_test'})
    semantics = {'epoch': 'v1'}
    monkeypatch.setattr(contract, 'semantic_epoch', lambda *args: dict(semantics))
    original = daily.STEPS['product_performance_daily']
    step = daily.SourceLoadStep(BATCH_TASK_NAME,
        f'delete from {schema}.{target} where dt_date between %(product_start_date)s and %(product_end_date)s',
        original.source_select_statement, f'{schema}.{target}', daily.PRODUCT_DAILY_COLUMNS)
    params = range_params(biz_date=date(2026, 1, 2), snapshot_date=date(2026, 1, 3),
                          range_start=date(2026, 1, 1), range_end=date(2026, 1, 2))
    schemas = daily.SchemaConfig(schema, 'etl_datasync', 'dwd_datasync', 'temporary_dwd')
    traced = TracedConnection(conn)
    assert daily.execute_source_load_step(traced, reader, schemas, step, params, 1) == 2
    traced.writes.clear()
    return conn, schema, target, traced, reader, schemas, step, params, semantics


@pytest.mark.parametrize('scenario', ['unchanged', 'irrelevant', 'schema_only', 'value',
    'delete_day', 'new_day', 'missing_result', 'rule', 'semantic', 'duplicate', 'null_zero'])
def test_consumer_skips_aggregation_before_query_but_replays_true_changes(consumer_database, monkeypatch, scenario):
    from etl import product_consumer_contract as contract
    conn, schema, target, traced, reader, schemas, step, params, semantics = consumer_database
    table = 'dashboard_label_source_performance'
    with conn.cursor() as q:
        if scenario == 'irrelevant':
            q.execute(f"update `{table}` set status='new' where start_date='2026-01-02'")
        elif scenario == 'value':
            q.execute(f"update `{table}` set amount=11 where start_date='2026-01-02'")
        elif scenario == 'delete_day':
            q.execute(f"delete from `{table}` where start_date='2026-01-02'")
            reader.shared_product_item['partitions'].pop('2026-01-02')
        elif scenario == 'new_day':
            q.execute(f"update `{table}` set start_date='2026-01-03' where start_date='2026-01-02'")
            reader.shared_product_item['partitions'].pop('2026-01-02')
            reader.shared_product_item['partitions']['2026-01-03'] = {'hash': 'new-day'}
            params.update(product_end_date=date(2026, 1, 3), next_product_end_date=date(2026, 1, 4))
        elif scenario == 'missing_result':
            q.execute(f"delete from `{target}` where dt_date='2026-01-02'")
        elif scenario == 'duplicate':
            q.execute(f"select * from `{table}` where start_date='2026-01-02'")
            row = q.fetchone()
            q.execute(f'insert into `{table}` ({",".join(f"`{c}`" for c in row)}) '
                      f'values ({",".join(f"%({c})s" for c in row)})', row)
        elif scenario == 'null_zero':
            q.execute(f"update `{table}` set volume=null where start_date='2026-01-02'")
        elif scenario == 'schema_only':
            reader.shared_product_item['columns'].append('unused_new_column')
    conn.commit()
    if scenario in {'irrelevant', 'value', 'duplicate', 'null_zero'}:
        reader.shared_product_item['partitions']['2026-01-02'] = {'hash': 'changed'}
    if scenario == 'rule':
        step = daily.SourceLoadStep(step.name, step.delete_statement,
            step.source_select_statement.replace('/ 1.19', '/ 1.20'), step.target_table, step.target_columns)
    elif scenario == 'semantic':
        semantics['epoch'] = 'v2'
    queries = []
    original_cursor = reader.cursor
    class RecordCursor:
        def __init__(self, cursor): self.cursor = cursor
        def __enter__(self): self.cursor.__enter__(); return self
        def __exit__(self, *args): return self.cursor.__exit__(*args)
        def execute(self, sql, args=None): queries.append(sql); return self.cursor.execute(sql, args)
        def __getattr__(self, name): return getattr(self.cursor, name)
    reader.cursor = lambda *args: RecordCursor(original_cursor(*args))
    result = daily.execute_source_load_step(traced, reader, schemas, step, params, 1)
    aggregates = [sql for sql in queries if 'with src as' in sql.lower()]
    fact_writes = [(sql, args) for sql, args in traced.writes if target in sql]
    if scenario in {'unchanged', 'irrelevant', 'schema_only'}:
        assert not aggregates and not fact_writes and result == 0
    else:
        assert aggregates
        assert result == (0 if scenario in {'delete_day', 'semantic'} else 2 if scenario == 'rule' else 1)
    with conn.cursor() as q:
        q.execute(f'select dt_date,sales_amount,sales_qty from `{target}` order by dt_date')
        rows = q.fetchall()
        q.execute(f'select dt_date from `{contract.TABLE}` order by dt_date')
        assert q.fetchall()  # Applied metadata is stored in the same test session.
    if scenario != 'new_day':
        # Unknown older/later target coverage must not be cleared by the cache.
        assert any(row['dt_date'] == date(2026, 1, 3) for row in rows)
    if scenario == 'value':
        assert next(row for row in rows if row['dt_date'] == date(2026, 1, 2))['sales_amount'] == 11
    if scenario == 'duplicate':
        assert next(row for row in rows if row['dt_date'] == date(2026, 1, 2))['sales_qty'] == 2


def test_consumer_metadata_and_fact_changes_roll_back_together(consumer_database, monkeypatch):
    from etl import product_consumer_contract as contract
    conn, schema, target, traced, reader, schemas, step, params, _ = consumer_database
    with conn.cursor() as q:
        q.execute(f'select * from `{target}` order by dt_date')
        old_facts = q.fetchall()
        q.execute(f'select * from `{contract.TABLE}` order by dt_date')
        old_cache = q.fetchall()
        q.execute("update dashboard_label_source_performance set amount=11 where start_date='2026-01-02'")
    conn.commit()
    reader.shared_product_item['partitions']['2026-01-02'] = {'hash': 'changed'}
    monkeypatch.setattr(daily, 'source_load_retry_attempts', lambda: 1)
    def reject_commit():
        raise RuntimeError('injected failure after metadata upsert before commit')
    monkeypatch.setattr(traced, 'commit', reject_commit)
    with pytest.raises(RuntimeError, match='injected failure'):
        daily.execute_source_load_step(traced, reader, schemas, step, params, 1)
    assert any(contract.TABLE in sql for sql, _ in traced.writes)
    assert any(target in sql for sql, _ in traced.writes)
    with conn.cursor() as q:
        q.execute(f'select * from `{target}` order by dt_date')
        assert q.fetchall() == old_facts
        q.execute(f'select * from `{contract.TABLE}` order by dt_date')
        assert q.fetchall() == old_cache


def test_dependency_hash_sums_larger_than_uint64_round_trip_exactly(consumer_database):
    from etl import product_consumer_contract as contract
    conn, schema, target, _, reader, schemas, _, params, _ = consumer_database
    fp = (100, 36893488147419103231, 18446744073709551615, 999999999999999999999999)
    current = contract.Plan((), {date(2026, 1, 2): dict(rule_sha='a' * 64,
        raw_stamp='b' * 64, dependency_fp=fp, output_rows=1)}, 'a' * 64, reader.shared_product_item)
    contract.persist(conn, schema, current, f'{schema}.{target}', params)
    conn.commit()
    assert contract.load_states(conn, schema, params)[date(2026, 1, 2)]['dependency_fp'] == fp


def test_large_partition_hash_ignores_irrelevant_change_without_aggregating(consumer_database, monkeypatch):
    from etl import product_history_fingerprints as fingerprints
    conn, _, target, traced, reader, schemas, step, params, _ = consumer_database
    table = 'dashboard_label_source_performance'
    with conn.cursor() as q:
        q.execute(f"select * from `{table}` where start_date='2026-01-02'")
        row = q.fetchone()
        q.executemany(f'insert into `{table}` ({",".join(f"`{c}`" for c in row)}) '
                      f'values ({",".join(f"%({c})s" for c in row)})', [row] * 20)
    conn.commit()
    reader.shared_product_item['partitions']['2026-01-02'] = {'hash': 'many-rows'}
    assert daily.execute_source_load_step(traced, reader, schemas, step, params, 1) == 1
    with conn.cursor() as q:
        q.execute(f"update `{table}` set status='irrelevant' where start_date='2026-01-02'")
    conn.commit()
    reader.shared_product_item['partitions']['2026-01-02'] = {'hash': 'only-status-changed'}
    calls = []
    original = fingerprints.load_fingerprints
    def record(conn, sql, args, **options):
        calls.append(sql)
        return original(conn, sql, args, **options)
    monkeypatch.setattr(fingerprints, 'load_fingerprints', record)
    traced.writes.clear()
    assert daily.execute_source_load_step(traced, reader, schemas, step, params, 1) == 0
    assert calls and not any('with src as' in sql.lower() for sql in calls)
    assert not any(target in sql for sql, _ in traced.writes)


def test_first_consumer_cache_clears_known_deleted_boundary_after_an_unchanged_input(consumer_database):
    from etl import product_consumer_contract as contract, shared_product_inputs as shared
    conn, schema, target, traced, reader, schemas, step, params, _ = consumer_database
    old = dict(reader.shared_product_item)
    with conn.cursor() as q:
        q.execute("delete from dashboard_label_source_performance where start_date='2026-01-01'")
        q.execute(f'delete from `{contract.TABLE}`')  # Simulate a consumer not seeded before failure.
    conn.commit()
    current = {**old, 'partitions': {'2026-01-02': {'hash': 'second'}}}
    deleted = shared.retain_known_partitions(current, old)
    reader.shared_product_item = shared.retain_known_partitions(current, deleted)
    assert daily.execute_source_load_step(traced, reader, schemas, step, params, 1) == 0
    with conn.cursor() as q:
        q.execute(f'select dt_date from `{target}` order by dt_date')
        assert [row['dt_date'] for row in q.fetchall()] == [date(2026, 1, 2), date(2026, 1, 3)]


def test_filter_rule_migration_then_newly_included_row_change_is_not_skipped(consumer_database):
    conn, schema, target, traced, reader, schemas, step, params, _ = consumer_database
    table = 'dashboard_label_source_performance'
    with conn.cursor() as q:
        q.execute(f"select * from `{table}` where start_date='2026-01-02'")
        row = {**q.fetchone(), 'seller_sku': 'Amazon.FoundIncluded', 'amount': 20}
        q.execute(f'insert into `{table}` ({",".join(f"`{c}`" for c in row)}) '
                  f'values ({",".join(f"%({c})s" for c in row)})', row)
    conn.commit()
    reader.shared_product_item['partitions']['2026-01-02'] = {'hash': 'excluded-new-row'}
    assert daily.execute_source_load_step(traced, reader, schemas, step, params, 1) == 0
    changed = daily.SourceLoadStep(step.name, step.delete_statement,
        step.source_select_statement.replace("'Amazon.Found%%'", "'Nothing.Excluded%%'"),
        step.target_table, step.target_columns)
    assert daily.execute_source_load_step(traced, reader, schemas, changed, params, 1) == 2
    with conn.cursor() as q:
        q.execute(f"update `{table}` set amount=99 where seller_sku='Amazon.FoundIncluded'")
    conn.commit()
    reader.shared_product_item['partitions']['2026-01-02'] = {'hash': 'included-value-changed'}
    assert daily.execute_source_load_step(traced, reader, schemas, changed, params, 1) == 2
    with conn.cursor() as q:
        q.execute(f"select sales_amount from `{target}` where seller_sku_adj='Amazon.FoundIncluded'")
        assert q.fetchone()['sales_amount'] == 99


@pytest.mark.parametrize('full_load', [False, True])
def test_alternate_fact_writer_invalidates_cache_in_its_fact_transaction(consumer_database, monkeypatch, full_load):
    from etl import product_consumer_contract as contract
    conn, schema, target, traced, reader, schemas, step, params, _ = consumer_database
    monkeypatch.setattr(contract, 'state_exists', lambda *args: True)  # TEMP tables are absent in I_S.tables.
    select = f'select * from {schema}.{target} where dt_date between %(product_start_date)s and %(product_end_date)s'
    alternate = daily.SourceLoadStep(step.name, step.delete_statement, select, step.target_table, step.target_columns)
    # A no-change alternate writer still invalidates trust, including the full-load path.
    if full_load:
        # Avoid self-select after delete; this fixture explicitly tests the writer lifecycle.
        alternate = daily.SourceLoadStep(step.name, 'delete from ' + step.target_table + ' where 1=0',
            select + ' and 1=0', step.target_table, step.target_columns)
    daily.execute_source_load_step(traced, conn, schemas, alternate,
                                  {**params, 'product_full_load': int(full_load)}, 1)
    with conn.cursor() as q:
        q.execute(f'select * from `{contract.TABLE}`')
        assert not q.fetchall()


def test_history_rule_change_replays_known_dates_without_watermark_candidates(consumer_database, monkeypatch):
    from etl import product_performance_history_sync as history, shared_product_inputs as shared
    conn, schema, target, traced, reader, schemas, step, params, _ = consumer_database
    changed = daily.SourceLoadStep('product_performance_daily', step.delete_statement,
        step.source_select_statement.replace('/ 1.19', '/ 1.20'), step.target_table, step.target_columns)
    monkeypatch.setitem(daily.STEPS, 'product_performance_daily', changed)
    monkeypatch.setattr(history, 'build_schema_config', lambda: schemas)
    monkeypatch.setattr(history, 'connect_target', lambda: nullcontext(traced))
    monkeypatch.setattr(shared, 'product_reader', lambda *args: nullcontext(reader))
    monkeypatch.setattr(history, 'ensure_tables', lambda *args: None)
    monkeypatch.setattr(history, 'latest_success_at', lambda *args: datetime(2026, 3, 30))
    monkeypatch.setattr(history, 'fetch_changed_dates', lambda *args, **kwargs: pytest.fail('must bypass watermark'))
    monkeypatch.setattr(history, 'log_task', lambda *args: None)
    written, ranges = history.sync_history(biz_date=date(2026, 3, 31), snapshot_date=date(2026, 4, 1))
    assert written == 2
    assert ranges == [(date(2026, 1, 1), date(2026, 1, 2))]


@pytest.mark.parametrize('scenario', [
    'unchanged', 'real_value', 'null_to_empty', 'null_to_zero', 'missing_target',
    'deleted_source', 'same_count_replacement', 'duplicate_count',
    'formula_change', 'equal_after_storage_rounding',
])
def test_history_reconciles_business_rows_without_rewriting_unchanged_days(history_database, scenario):
    """Catches unconditional range writes, NULL conflation and stale formula results."""
    conn, schema, (source, target) = history_database
    expression = None
    with conn.cursor() as q:
        if scenario == 'real_value':
            q.execute(f"update `{source}` set order_gross_profit=11 where dt_date='2026-01-02'")
        elif scenario == 'null_to_empty':
            q.execute(f"update `{source}` set local_sku='' where dt_date='2026-01-02'")
        elif scenario == 'null_to_zero':
            q.execute(f"update `{target}` set sales_qty=null where dt_date='2026-01-02'")
            q.execute(f"update `{source}` set sales_qty=0 where dt_date='2026-01-02'")
        elif scenario == 'missing_target':
            q.execute(f"delete from `{target}` where dt_date='2026-01-02'")
        elif scenario == 'deleted_source':
            q.execute(f"delete from `{source}` where dt_date='2026-01-02'")
        elif scenario == 'same_count_replacement':
            q.execute(f"update `{source}` set item_key='replacement' where dt_date='2026-01-02'")
        elif scenario == 'duplicate_count':
            q.execute(f"select * from `{source}` where dt_date='2026-01-02'")
            duplicate = q.fetchone()
            columns = ','.join(f'`{column}`' for column in daily.PRODUCT_DAILY_COLUMNS)
            values = ','.join(f'%({column})s' for column in daily.PRODUCT_DAILY_COLUMNS)
            q.execute(f'insert into `{source}` ({columns}) values ({values})', duplicate)
        elif scenario == 'formula_change':
            expression = 'order_gross_profit * 2'
        elif scenario == 'equal_after_storage_rounding':
            expression = 'cast(10.000041 as decimal(18,6))'
    conn.commit()
    selected = ','.join(
        f'{expression} as `{column}`' if column == 'order_gross_profit' and expression else f'`{column}`'
        for column in daily.PRODUCT_DAILY_COLUMNS
    )
    select = f'''select {selected} from {schema}.{source}
        where dt_date between %(product_start_date)s and %(product_end_date)s'''
    step = daily.SourceLoadStep(
        BATCH_TASK_NAME,
        f'''delete from {schema}.{target}
            where dt_date between %(product_start_date)s and %(product_end_date)s''',
        select, f'{schema}.{target}', daily.PRODUCT_DAILY_COLUMNS,
    )
    traced = TracedConnection(conn)
    result = daily.execute_source_load_step(
        traced, conn, daily.SchemaConfig(schema, 'etl_datasync', 'dwd_datasync', 'temporary_dwd'),
        step, {'product_full_load': 0, 'product_start_date': date(2026, 1, 1),
               'product_end_date': date(2026, 1, 3), 'next_product_end_date': date(2026, 1, 4),
               'biz_date': date(2026, 1, 3), 'snapshot_date': date(2026, 1, 4)}, 100,
    )
    if scenario in {'unchanged', 'equal_after_storage_rounding'}:
        assert traced.writes == []
        assert result == 0
    else:
        assert result == (0 if scenario == 'deleted_source' else
                          2 if scenario == 'duplicate_count' else 3 if scenario == 'formula_change' else 1)
    with conn.cursor() as q:
        q.execute(f'select dt_date,item_key,local_sku,sales_qty,order_gross_profit,updated_at from `{target}` order by dt_date,item_key')
        rows = q.fetchall()
    middle = [row for row in rows if row['dt_date'] == date(2026, 1, 2)]
    if scenario != 'formula_change':
        assert [row['updated_at'] for row in rows if row['dt_date'] != date(2026, 1, 2)] == [datetime(2010, 1, 1)] * 2
    if scenario == 'deleted_source':
        assert middle == []
    elif scenario == 'duplicate_count':
        assert len(middle) == 2
    else:
        assert len(middle) == 1
        assert middle[0]['item_key'] == ('replacement' if scenario == 'same_count_replacement' else 'item-2')
        assert middle[0]['local_sku'] == ('' if scenario == 'null_to_empty' else None)
        assert middle[0]['sales_qty'] == (Decimal(0) if scenario == 'null_to_zero' else Decimal(10))
        assert middle[0]['order_gross_profit'] == Decimal(11 if scenario == 'real_value' else 20 if scenario == 'formula_change' else 10)


@pytest.mark.parametrize('history_database', [True], indirect=True)
@pytest.mark.parametrize('failure', ['second_insert_duplicate', 'not_null'])
def test_history_rolls_back_changed_day_when_production_constraints_reject_rows(history_database, monkeypatch, failure):
    conn, schema, (source, target) = history_database
    monkeypatch.setattr(daily, 'source_load_retry_attempts', lambda: 1)
    with conn.cursor() as q:
        if failure == 'not_null':
            q.execute(f"update `{source}` set sales_qty=null where dt_date='2026-01-02'")
        else:
            q.execute(f"select * from `{source}` where dt_date='2026-01-02'")
            duplicate = q.fetchone()
            columns = ','.join(f'`{column}`' for column in daily.PRODUCT_DAILY_COLUMNS)
            values = ','.join(f'%({column})s' for column in daily.PRODUCT_DAILY_COLUMNS)
            q.execute(f'insert into `{source}` ({columns}) values ({values})', duplicate)
    conn.commit()
    step = daily.SourceLoadStep(
        BATCH_TASK_NAME,
        f'delete from {schema}.{target} where dt_date between %(product_start_date)s and %(product_end_date)s',
        f'select * from {schema}.{source} where dt_date between %(product_start_date)s and %(product_end_date)s',
        f'{schema}.{target}', daily.PRODUCT_DAILY_COLUMNS,
    )
    with pytest.raises(pymysql.IntegrityError):
        daily.execute_source_load_step(TracedConnection(conn), conn,
            daily.SchemaConfig(schema, 'etl_datasync', 'dwd_datasync', 'temporary_dwd'), step,
            {'product_full_load': 0, 'product_start_date': date(2026, 1, 1),
             'product_end_date': date(2026, 1, 3), 'next_product_end_date': date(2026, 1, 4)}, 1)
    with conn.cursor() as q:
        q.execute(f'select item_key,sales_qty,updated_at from `{target}` order by dt_date')
        rows = q.fetchall()
    assert [row['item_key'] for row in rows] == ['item-1', 'item-2', 'item-3']
    assert [row['sales_qty'] for row in rows] == [Decimal(10)] * 3
    assert [row['updated_at'] for row in rows] == [datetime(2010, 1, 1)] * 3


@pytest.mark.parametrize('history_database', [True], indirect=True)
def test_shared_streaming_snapshot_skips_a_second_real_aggregate_load(history_database, monkeypatch):
    from etl import shared_product_inputs as shared
    from etl.product_performance_history_sync import range_params
    conn, schema, (_, target) = history_database
    with conn.cursor() as q:
        q.execute('select manifest_json from dashboard_label_local_input where singleton=1')
        manifest = json.loads(q.fetchone()['manifest_json'])
        item = next(x for x in manifest['sources'] if x['local_name'] == shared.LOCAL_TABLE)
        q.execute('select min(start_date) first_day,max(start_date) last_day from dashboard_label_source_performance')
        bounds = q.fetchone()
    monkeypatch.setenv(RUN_ENV, item['shared_acquisition']['run_id'])
    start, end = (date.fromisoformat(str(bounds[key])[:10]) for key in ('first_day', 'last_day'))
    params = range_params(biz_date=end, snapshot_date=end, range_start=start, range_end=end)
    original = daily.STEPS['product_performance_daily']
    step = daily.SourceLoadStep(BATCH_TASK_NAME,
        f'delete from {schema}.{target} where dt_date between %(product_start_date)s and %(product_end_date)s',
        original.source_select_statement, f'{schema}.{target}', daily.PRODUCT_DAILY_COLUMNS)
    schemas = daily.SchemaConfig(schema, 'etl_datasync', 'dwd_datasync', 'temporary_dwd')
    traced = TracedConnection(conn)
    with shared.product_reader(schemas, target_factory=lambda: connect_owned_schema(schema)) as reader:
        assert reader.raw.cursorclass is pymysql.cursors.SSDictCursor
        assert daily.execute_source_load_step(traced, reader, schemas, step, params, 7) > 0
        with conn.cursor() as q:
            q.execute(f'select * from `{target}` order by dt_date,item_key')
            before = q.fetchall()
        traced.writes.clear()
        assert daily.execute_source_load_step(traced, reader, schemas, step, params, 7) == 0
        assert traced.writes == []
    with conn.cursor() as q:
        q.execute(f'select * from `{target}` order by dt_date,item_key')
        assert q.fetchall() == before


@pytest.mark.parametrize('changed', [False, True])
def test_next_shared_incremental_history_reports_written_rows_not_selected_row_count(history_database, monkeypatch, changed):
    from etl import product_performance_history_sync as history, shared_product_inputs as shared
    conn, schema, (source, target) = history_database
    if changed:
        with conn.cursor() as q:
            q.execute(f"update `{source}` set order_gross_profit=11 where dt_date='2026-01-02'")
        conn.commit()
    step = daily.SourceLoadStep('product_performance_daily',
        f'delete from {schema}.{target} where dt_date between %(product_start_date)s and %(product_end_date)s',
        f'select * from {schema}.{source} where dt_date between %(product_start_date)s and %(product_end_date)s',
        f'{schema}.{target}', daily.PRODUCT_DAILY_COLUMNS)
    traced = TracedConnection(conn)
    conn.shared_product = True
    monkeypatch.setenv(RUN_ENV, 'owned_history_test')
    monkeypatch.setitem(daily.STEPS, 'product_performance_daily', step)
    monkeypatch.setattr(history, 'build_schema_config', lambda: daily.SchemaConfig(schema, 'etl_datasync', 'dwd_datasync', 'temporary_dwd'))
    monkeypatch.setattr(history, 'connect_target', lambda: nullcontext(traced))
    monkeypatch.setattr(shared, 'product_reader', lambda *args, **kwargs: nullcontext(conn))
    monkeypatch.setattr(shared, 'read_shared_item', lambda *args: {'shared_acquisition': {'changed_partitions': ['2026-01-02']}})
    monkeypatch.setattr(history, 'ensure_tables', lambda *args: None)
    monkeypatch.setattr(history, 'latest_success_at', lambda *args: datetime(2026, 1, 1))
    monkeypatch.setattr(history, 'fetch_changed_dates', lambda *args, **kwargs: [])
    monkeypatch.setattr(history, 'log_task', lambda *args: None)
    written, ranges = history.sync_history(biz_date=date(2026, 3, 31), snapshot_date=date(2026, 4, 1))
    assert ranges == [(date(2026, 1, 2), date(2026, 1, 2))]
    assert written == (1 if changed else 0)
    if not changed:
        assert traced.writes == []
