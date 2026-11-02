import importlib
import importlib.util
import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.label_analysis_materialized import COMPACT_STORAGE, decode_history, join_row


def module():
    assert importlib.util.find_spec('etl.migrate_analysis_storage'), 'lossless history migration is missing'
    return importlib.import_module('etl.migrate_analysis_storage')


def record(object_id=7, phase='current'):
    return dict(analysis_date=date(2026, 10, 16), cutoff_date=date(2026, 10, 16 if phase == 'current' else 9),
                period_days=7, view_kind='business_unit' if object_id == 7 else 'country', phase=phase,
                object_id=object_id, context_json=json.dumps({'key': '商品', '_object_id': object_id,
                    '_batch_id': 'old', 'labels': [{'id': 201}], 'ratio_pairs': {'margin': [None, 0]}}),
                business='{"sales_qty":null,"profit":-0.125}', traffic='{"sessions_total":0}',
                stockout='{"unknown_days":3}', inventory='{"inventory_cost":12.34}')


def test_conversion_preserves_exact_public_result_and_all_record_dimensions():
    m = module(); source = record()
    packed = m.convert_record('old', source)
    assert packed[:7] == ('old', source['analysis_date'], source['cutoff_date'], 7, 'business_unit', 'current', 7)
    assert decode_history(packed[-2], packed[-1]) == join_row(source['context_json'], {
        key: source[key] for key in ('business', 'traffic', 'stockout', 'inventory')})


def test_missing_domain_is_rejected_instead_of_silently_losing_metrics():
    m = module(); source = record(); source['traffic'] = None
    with pytest.raises(ValueError, match='missing domain'):
        m.convert_record('old', source)


def test_manifest_row_count_must_match_both_phases_and_quality_report():
    m = module()
    batch = {'quality_report': '{"rows":4}', 'source_manifest': '{"counts":{"business_unit:7":1,"country:7":1}}'}
    assert m.expected_rows(batch) == 4
    batch['quality_report'] = '{"rows":3}'
    with pytest.raises(ValueError, match='manifest'):
        m.expected_rows(batch)


@pytest.fixture
def database():
    if os.getenv('LABEL_LOCAL_MYSQL_TEST') != '1':
        pytest.skip('isolated real MySQL test requires LABEL_LOCAL_MYSQL_TEST=1')
    from etl.daily_update_runner import load_dashboard_environment
    from etl.dashboard_daily_update import connect_target, build_schema_config
    load_dashboard_environment(Path.cwd())
    name = 'analysis_migrate_test_' + uuid4().hex
    source = build_schema_config().target_schema
    conn = connect_target()
    tables = ['dashboard_analysis_batch', 'dashboard_analysis_publication', 'dashboard_analysis_compact_period',
              *['dashboard_analysis_' + key + '_period' for key in ('object', 'business', 'traffic', 'stockout', 'inventory_object')]]
    try:
        with conn.cursor() as q:
            q.execute(f'create database `{name}`')
            for table in tables:
                q.execute(f'create table `{name}`.`{table}` like `{source}`.`{table}`')
            manifest = json.dumps({'counts': {'business_unit:7': 1, 'country:7': 1}, 'unchanged': '保留'})
            windows = json.dumps([{'date': '2026-10-16', 'period': 7, 'view': view} for view in ('business_unit', 'country')])
            for batch, storage in [('old', 'analysis-read-model-v2-bounded'), ('current', COMPACT_STORAGE)]:
                q.execute(f'insert into `{name}`.dashboard_analysis_batch '
                          '(batch_id,state,formula_version,schema_version,source_manifest,available_windows,label_dictionary,quality_report) '
                          'values (%s,%s,%s,%s,%s,%s,%s,%s)',
                          (batch, 'ready', 'formula-preserved', storage, manifest, windows, '[]', '{"rows":4}'))
            q.execute(f'insert into `{name}`.dashboard_analysis_publication(singleton,batch_id) values(1,%s)', ('current',))
            for oid in (7, 8):
                for phase in ('current', 'previous'):
                    row = record(oid, phase)
                    q.execute(f'insert into `{name}`.dashboard_analysis_object_period '
                              '(batch_id,analysis_date,cutoff_date,period_days,view_kind,phase,object_id,context_json) '
                              'values(%s,%s,%s,%s,%s,%s,%s,%s)',
                              ('old', row['analysis_date'], row['cutoff_date'], 7, row['view_kind'], phase, oid, row['context_json']))
                    for domain in ('business', 'traffic', 'stockout', 'inventory'):
                        suffix = 'inventory_object' if domain == 'inventory' else domain
                        extra = {'paired_values': '{"margin":[null,0]}', 'coverage_json': '{}'} if domain in ('business', 'traffic') else (
                            {'unknown_days': 3, 'valid_days': 4, 'expected_days': 7} if domain == 'stockout' else {})
                        columns = ['batch_id', 'cutoff_date', 'period_days', 'object_id', 'result_json', *extra]
                        q.execute(f'insert into `{name}`.dashboard_analysis_{suffix}_period '
                                  f'({",".join(columns)}) values({",".join(["%s"] * len(columns))})',
                                  ('old', row['cutoff_date'], 7, oid, row[domain], *extra.values()))
        conn.commit()
        yield name, connect_target
    finally:
        conn.rollback()
        assert name.startswith('analysis_migrate_test_') and name != source
        with conn.cursor() as q:
            q.execute(f'drop database if exists `{name}`')
        conn.close()


def test_real_migration_preserves_old_rows_metadata_and_current_publication(database):
    name, connect = database; m = module()
    result = m.migrate(connect, name, ['old'], apply=True, chunk_rows=2, lock_name=name)
    assert result['batches'][0]['rows'] == 4
    assert result['batches'][0]['source_digest'] == result['batches'][0]['target_digest']
    with connect() as c, c.cursor() as q:
        q.execute(f'select * from `{name}`.dashboard_analysis_batch where batch_id=%s', ('old',))
        batch = q.fetchone()
        assert batch['schema_version'] == COMPACT_STORAGE
        assert batch['formula_version'] == 'formula-preserved'
        assert json.loads(batch['source_manifest'])['unchanged'] == '保留'
        q.execute(f'select batch_id from `{name}`.dashboard_analysis_publication where singleton=1')
        assert q.fetchone()['batch_id'] == 'current'
        q.execute(f'select count(*) n from `{name}`.dashboard_analysis_object_period')
        assert q.fetchone()['n'] == 4


def test_real_dry_run_has_no_writes(database):
    name, connect = database; m = module()
    result = m.migrate(connect, name, ['old'], apply=False, lock_name=name)
    assert result['applied'] is False
    with connect() as c, c.cursor() as q:
        q.execute(f'select count(*) n from `{name}`.dashboard_analysis_compact_period')
        assert q.fetchone()['n'] == 0


def test_real_missing_source_rows_cannot_switch_batch(database):
    name, connect = database; m = module()
    with connect() as c, c.cursor() as q:
        q.execute(f'delete from `{name}`.dashboard_analysis_traffic_period limit 1'); c.commit()
    with pytest.raises(ValueError, match='source row count'):
        m.migrate(connect, name, ['old'], apply=True, lock_name=name)
    with connect() as c, c.cursor() as q:
        q.execute(f'select schema_version from `{name}`.dashboard_analysis_batch where batch_id=%s', ('old',))
        assert q.fetchone()['schema_version'] != COMPACT_STORAGE


def test_real_bad_target_checksum_blocks_switch(database, monkeypatch):
    name, connect = database; m = module(); original = m.verify_compact
    def corrupt_then_verify(*args, **kwargs):
        with connect() as c, c.cursor() as q:
            q.execute(f'update `{name}`.dashboard_analysis_compact_period set checksum=%s limit 1', ('0' * 64,)); c.commit()
        return original(*args, **kwargs)
    monkeypatch.setattr(m, 'verify_compact', corrupt_then_verify)
    with pytest.raises(ValueError, match='校验失败'):
        m.migrate(connect, name, ['old'], apply=True, lock_name=name)
    with connect() as c, c.cursor() as q:
        q.execute(f'select schema_version from `{name}`.dashboard_analysis_batch where batch_id=%s', ('old',))
        assert q.fetchone()['schema_version'] != COMPACT_STORAGE


def test_real_published_batch_and_busy_lock_are_protected(database):
    name, connect = database; m = module()
    with connect() as blocker, blocker.cursor() as q:
        q.execute('select get_lock(%s,0)', (name,))
        with pytest.raises(RuntimeError, match='lock'):
            m.migrate(connect, name, ['old'], apply=True, lock_name=name)
    with connect() as c, c.cursor() as q:
        q.execute(f'update `{name}`.dashboard_analysis_publication set batch_id=%s where singleton=1', ('old',)); c.commit()
    with pytest.raises(ValueError, match='published'):
        m.migrate(connect, name, ['old'], apply=True, lock_name=name)


def test_real_same_command_resumes_after_first_batch_was_switched(database, monkeypatch):
    name, connect = database; m = module()
    with connect() as c, c.cursor() as q:
        for suffix in ('batch', *[key + '_period' for key in m.TABLES]):
            target = f'`{name}`.`dashboard_analysis_{suffix}`'
            q.execute(f'show columns from {target}')
            columns = [row['Field'] for row in q.fetchall()]
            selection = ','.join('%s' if key == 'batch_id' else f'`{key}`' for key in columns)
            q.execute(f'insert into {target} select {selection} from {target} where batch_id=%s', ('old2', 'old'))
        q.execute(f'update `{name}`.dashboard_analysis_object_period '
                  "set context_json=json_set(context_json,'$._batch_id',%s) where batch_id=%s", ('old2', 'old2'))
        c.commit()
    original = m.verify_compact
    def interrupt_second(*args, **kwargs):
        if args[2] == 'old2':
            raise RuntimeError('interrupted second batch')
        return original(*args, **kwargs)
    monkeypatch.setattr(m, 'verify_compact', interrupt_second)
    with pytest.raises(RuntimeError, match='interrupted second batch'):
        m.migrate(connect, name, ['old', 'old2'], apply=True, lock_name=name)
    monkeypatch.setattr(m, 'verify_compact', original)
    resumed = m.migrate(connect, name, ['old', 'old2'], apply=True, lock_name=name)
    assert len(resumed['batches']) == 2
    assert all(b['rows'] == 4 and b['source_digest'] == b['target_digest'] for b in resumed['batches'])
