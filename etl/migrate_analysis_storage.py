"""Copy immutable legacy analysis batches to compact storage, without recalculating.

Defaults to a read-only plan. --apply copies and verifies every result before
changing each historical batch's format. Legacy rows and the live publication
are retained, so the operation remains reversible.
"""
from collections import Counter
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import re

from pymysql.cursors import SSDictCursor

from app.services.label_analysis_materialized import (
    COMPACT_STORAGE, decode_history, dumps, encode_history, join_row, unpack,
)

LEGACY_STORAGE = {'analysis-read-model-v1', 'analysis-read-model-v2-bounded'}
DOMAINS = ('business', 'traffic', 'stockout', 'inventory')
TABLES = ('object', 'business', 'traffic', 'stockout', 'inventory_object')
COLUMNS = ('batch_id', 'analysis_date', 'cutoff_date', 'period_days', 'view_kind',
           'phase', 'object_id', 'payload', 'checksum')
ORDER = 'analysis_date,period_days,view_kind,phase,object_id'


def table(schema, suffix):
    if not re.fullmatch(r'[A-Za-z0-9_]+', schema):
        raise ValueError('invalid target schema')
    return f'`{schema}`.`dashboard_analysis_{suffix}`'


def expected_rows(batch):
    count = int(unpack(batch['quality_report'])['rows'])
    counts = unpack(batch['source_manifest'])['counts']
    if count <= 0 or sum(int(n) for n in counts.values()) * 2 != count:
        raise ValueError('batch manifest and quality row counts disagree')
    return count


def expected_windows(batch):
    return {f'{key}:{phase}': int(n) for key, n in unpack(batch['source_manifest'])['counts'].items()
            for phase in ('current', 'previous') if int(n)}


def convert_record(batch_id, row):
    if any(row[key] is None for key in DOMAINS):
        raise ValueError('missing domain in legacy result')
    prepared = join_row(row['context_json'], {key: row[key] for key in DOMAINS})
    if prepared.get('_batch_id', batch_id) != batch_id or prepared.get('_object_id', row['object_id']) != row['object_id']:
        raise ValueError('legacy result identity mismatch')
    payload, checksum = encode_history(prepared)
    return (batch_id, *(row[key] for key in COLUMNS[1:7]), payload, checksum)


def fingerprint(digest, record):
    digest.update(dumps([*record[:7], record[-1]]).encode('utf-8') + b'\n')


def verify_compact(connect, schema, batch_id):
    digest = hashlib.sha256(); count = 0; windows = Counter()
    conn = connect()
    try:
        with conn.cursor(SSDictCursor) as q:
            q.execute(f'select {",".join(COLUMNS)} from {table(schema, "compact_period")} '
                      f'where batch_id=%s order by {ORDER}', (batch_id,))
            while rows := q.fetchmany(200):
                for row in rows:
                    # This reads and checks the entire stored payload, not just its metadata.
                    decode_history(row['payload'], row['checksum'])
                    fingerprint(digest, tuple(row[key] for key in COLUMNS))
                    count += 1; windows[f'{row["view_kind"]}:{row["period_days"]}:{row["phase"]}'] += 1
    finally:
        conn.close()
    return {'rows': count, 'digest': digest.hexdigest(), 'windows': dict(windows)}


def source_sql(schema):
    joins = ' '.join(f'left join {table(schema, suffix + "_period")} {alias} '
                     'on ' + ' and '.join(f'{alias}.{key}=c.{key}' for key in ('batch_id', 'cutoff_date', 'period_days', 'object_id'))
                     for suffix, alias in (('business', 'b'), ('traffic', 't'), ('stockout', 's'), ('inventory_object', 'i')))
    return (f'select straight_join c.analysis_date,c.cutoff_date,c.period_days,c.view_kind,c.phase,c.object_id,c.context_json,'
            'b.result_json business,t.result_json traffic,s.result_json stockout,i.result_json inventory '
            f'from {table(schema, "object_period")} c {joins} where c.batch_id=%s '
            'order by ' + ','.join('c.' + key for key in ORDER.split(',')))


def migrate(connect, schema, batch_ids, *, apply=False, chunk_rows=200,
            progress=lambda event: None, lock_name='label_analysis_refresh'):
    if not 1 <= chunk_rows <= 1000:
        raise ValueError('chunk size must be between 1 and 1000')
    table(schema, 'batch')  # Validate identifiers before opening any transaction.
    conn = connect(); acquired = False
    result = {'applied': apply, 'batches': []}
    try:
        with conn.cursor() as q:
            q.execute('select get_lock(%s,0) acquired', (lock_name,))
            acquired = q.fetchone()['acquired'] == 1
            if not acquired:
                raise RuntimeError('analysis migration lock is occupied')
            q.execute(f'select * from {table(schema, "publication")} where singleton=1')
            publication = q.fetchone()
            if not publication:
                raise ValueError('published analysis is missing')
            result['publication_before'] = publication
            for batch_id in batch_ids:
                q.execute(f'select * from {table(schema, "batch")} where batch_id=%s', (batch_id,))
                batch = q.fetchone()
                if not batch or batch['state'] not in ('ready', 'published') or batch['schema_version'] not in LEGACY_STORAGE | {COMPACT_STORAGE}:
                    raise ValueError(f'unsupported historical batch: {batch_id}')
                if publication['batch_id'] == batch_id:
                    raise ValueError('current published batch cannot be migrated by this historical tool')
                expected = expected_rows(batch)
                report = {'batch_id': batch_id, 'original_format': batch['schema_version'], 'expected_rows': expected}
                if not apply:
                    result['batches'].append(report)
                    continue
                progress({'stage': 'source_check', 'batch': batch_id, 'expected': expected})
                for suffix in TABLES:
                    q.execute(f'select count(*) n from {table(schema, suffix + "_period")} where batch_id=%s', (batch_id,))
                    n = q.fetchone()['n']
                    if n != expected:
                        raise ValueError(f'source row count mismatch: {batch_id}/{suffix}: {n} != {expected}')
                conn.commit()
                digest = hashlib.sha256(); count = 0; windows = Counter(); reader = connect()
                insert = (f'insert into {table(schema, "compact_period")} ({",".join(COLUMNS)}) '
                          f'values ({",".join(["%s"] * len(COLUMNS))}) on duplicate key update '
                          'cutoff_date=values(cutoff_date),payload=values(payload),checksum=values(checksum)')
                try:
                    with reader.cursor(SSDictCursor) as stream:
                        stream.execute(source_sql(schema), (batch_id,))
                        while rows := stream.fetchmany(chunk_rows):
                            records = [convert_record(batch_id, row) for row in rows]
                            q.executemany(insert, records); conn.commit()
                            for record in records:
                                fingerprint(digest, record); count += 1
                                windows[f'{record[4]}:{record[3]}:{record[5]}'] += 1
                            if count % 10000 == 0:
                                progress({'stage': 'copied', 'batch': batch_id, 'rows': count, 'expected': expected})
                finally:
                    reader.close()
                if count != expected or dict(windows) != expected_windows(batch):
                    raise ValueError('legacy source windows are incomplete')
                progress({'stage': 'verify', 'batch': batch_id, 'rows': count})
                verified = verify_compact(connect, schema, batch_id)
                if verified != {'rows': count, 'digest': digest.hexdigest(), 'windows': dict(windows)}:
                    raise ValueError('compact copy differs from full legacy source')
                # Refresh the control transaction, then CAS only the historical format marker.
                conn.commit()
                if batch['schema_version'] == COMPACT_STORAGE:
                    # A prior invocation can have committed earlier batches before
                    # interruption. Recheck them against the retained source, then
                    # continue the same command to the remaining batches.
                    q.execute(f'select schema_version,state from {table(schema, "batch")} '
                              'where batch_id=%s for update', (batch_id,))
                    latest = q.fetchone()
                    if latest != {'schema_version': COMPACT_STORAGE, 'state': batch['state']}:
                        conn.rollback(); raise ValueError('historical batch changed before switch')
                else:
                    q.execute(f'update {table(schema, "batch")} set schema_version=%s '
                              'where batch_id=%s and schema_version=%s and state=%s',
                              (COMPACT_STORAGE, batch_id, batch['schema_version'], batch['state']))
                    if q.rowcount != 1:
                        conn.rollback(); raise ValueError('historical batch changed before switch')
                conn.commit()
                report.update(rows=count, source_digest=digest.hexdigest(), target_digest=verified['digest'],
                              windows=verified['windows'], format=COMPACT_STORAGE, legacy_rows_retained=True)
                result['batches'].append(report)
                progress({'stage': 'batch_switched', **report})
            conn.commit()
            q.execute(f'select * from {table(schema, "publication")} where singleton=1')
            result['publication_after'] = q.fetchone()
            if result['publication_after'] != publication:
                raise RuntimeError('current analysis publication changed during migration')
        return result
    finally:
        conn.rollback()
        if acquired:
            with conn.cursor() as q:
                q.execute('select release_lock(%s)', (lock_name,))
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', action='append', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    from etl.daily_update_runner import load_dashboard_environment
    from etl.dashboard_daily_update import connect_target, build_schema_config
    load_dashboard_environment(Path.cwd())
    output = args.output or Path('logs') / f'analysis_storage_migration_{datetime.now():%Y%m%d_%H%M%S}.json'
    events = []
    def progress(event):
        event = {'at': datetime.now().isoformat(), **event}
        events.append(event); print(dumps(event), flush=True)
    try:
        result = migrate(connect_target, build_schema_config().target_schema, args.batch,
                         apply=args.apply, progress=progress)
        result['passed'] = True
    except Exception as exc:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dumps({'passed': False, 'error': str(exc), 'events': events}), encoding='utf-8')
        raise
    result['events'] = events
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    print(dumps({'stage': 'complete', 'applied': args.apply, 'batches': len(result['batches']), 'report': str(output)}), flush=True)


if __name__ == '__main__':
    main()
