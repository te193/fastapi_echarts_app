"""One versioned raw product acquisition for daily facts, history, V47 and traffic.

The existing raw input table is the canonical store. Projection upgrades retain
an explicitly named previous table; this module never applies retention cleanup.
"""
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from uuid import uuid4

RUN_ENV = "DASHBOARD_SHARED_PRODUCT_RUN"
CONTRACT_VERSION = "raw_product_union39_v1"
SOURCE_REFERENCE = "dwd_datasync.lx_statistics_product_performance"
LOCAL_TABLE = "dashboard_label_source_performance"
PRODUCT_COLUMNS = (
    "id", "relate_id", "seller_sku", "status", "rank", "country", "seller_name",
    "volume", "amount", "predict_gross_profit", "return_rate",
    "afn_fulfillable_quantity", "stock_up_num", "avg_star", "acoas", "acos",
    "spend", "ad_sales_amount", "local_quantity", "product_create_time",
    "tag_name", "start_date", "end_date", "create_time", "sessions_total",
    "order_items", "sessions", "sessions_mobile", "page_views_total",
    "page_views", "page_views_mobile", "local_sku", "gross_profit",
    "ad_order_quantity", "clicks", "impressions", "return_count", "return_amount", "net_amount",
)


def run_id():
    value = os.getenv(RUN_ENV, "")
    if value and not re.fullmatch(r"[A-Za-z0-9_]{1,64}", value):
        raise RuntimeError("invalid shared product run identifier")
    return value


def require_columns(metadata):
    missing = set(PRODUCT_COLUMNS) - {row['column_name'] for row in metadata}
    if missing:
        raise RuntimeError(f"shared product source columns missing: {sorted(missing)}")


def validate_upgrade(old, names):
    if (old.get('source') != SOURCE_REFERENCE or not old.get('columns')
            or not set(old['columns']).issubset(names) or int(old.get('rows', 0)) < 1):
        raise RuntimeError("shared product projection upgrade would lose the previous contract")


def can_reuse(item):
    marker = item.get('shared_acquisition', {})
    return bool(run_id() and marker.get('run_id') == run_id()
                and marker.get('version') == CONTRACT_VERSION
                and set(item.get('columns', ())) >= set(PRODUCT_COLUMNS))


def read_shared_item(conn, schema):
    from etl.label_local_sql import checked_schema, quote
    schema = checked_schema(schema)
    with conn.cursor() as cursor:
        cursor.execute(f"select manifest_json from {quote(schema)}.dashboard_label_local_input where singleton=1")
        row = cursor.fetchone()
    manifest = json.loads(row['manifest_json']) if row else {}
    items = [item for item in manifest.get('sources', ()) if item.get('local_name') == LOCAL_TABLE]
    if len(items) != 1 or not can_reuse(items[0]):
        raise RuntimeError("shared product input is missing, stale or belongs to another run")
    return items[0]


def local_product_sql(sql, source_schema, target_schema):
    from etl.label_local_sql import checked_schema
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", source_schema):
        raise ValueError("invalid source schema")
    checked_schema(target_schema)
    pattern = rf"(?<![\w`])(?:`{re.escape(source_schema)}`|{re.escape(source_schema)})\.(?:`lx_statistics_product_performance`|lx_statistics_product_performance)(?![\w`])"
    return re.sub(pattern, target_schema + '.' + LOCAL_TABLE, sql, flags=re.IGNORECASE)


class LocalProductCursor:
    def __init__(self, cursor, source_schema, target_schema):
        self.raw = cursor; self.source_schema = source_schema; self.target_schema = target_schema
    def execute(self, sql, args=None):
        return self.raw.execute(local_product_sql(sql, self.source_schema, self.target_schema), args)
    def __getattr__(self, name): return getattr(self.raw, name)
    def __enter__(self): self.raw.__enter__(); return self
    def __exit__(self, *args): return self.raw.__exit__(*args)


class LocalProductConnection:
    shared_product = True
    def __init__(self, raw, source_schema, target_schema):
        self.raw = raw; self.source_schema = source_schema; self.target_schema = target_schema
    def cursor(self, *args, **kwargs):
        return LocalProductCursor(self.raw.cursor(*args, **kwargs), self.source_schema, self.target_schema)
    def ping(self, reconnect=False):
        # Reconnecting would discard the pinned input generation.
        return self.raw.ping(reconnect=False)
    def __getattr__(self, name): return getattr(self.raw, name)
    def __enter__(self): return self
    def __exit__(self, *args): self.raw.close()


@contextmanager
def product_reader(schemas, *, target_factory=None):
    from etl.dashboard_daily_update import connect_source, connect_target
    if not run_id():
        with connect_source() as conn: yield conn
        return
    conn = (target_factory or connect_target)()
    try:
        with conn.cursor() as cursor:
            cursor.execute("set session time_zone='+08:00'")
            cursor.execute('set transaction isolation level repeatable read')
            cursor.execute('start transaction with consistent snapshot, read only')
        item = read_shared_item(conn, schemas.target_schema)
        # Local acquisition is consumed with the same bounded fetchmany batches
        # as the original remote source, rather than buffering an entire range.
        from pymysql.cursors import SSDictCursor
        conn.cursorclass = SSDictCursor
        reader = LocalProductConnection(conn, schemas.dwd_source_schema, schemas.target_schema)
        reader.shared_product_item = item
        yield reader
    finally:
        conn.close()


def retain_known_partitions(item, old):
    """Keep authoritative dates across a deletion and a failed downstream run."""
    known = set(old.get('known_partitions', ())) | set(old.get('partitions', {})) | set(item['partitions'])
    return {**item, 'known_partitions': sorted(known)}


def _shared_marker(item, identifier):
    return {**item, 'shared_acquisition': {
        'version': CONTRACT_VERSION, 'run_id': identifier,
        'acquired_at': datetime.now(timezone.utc).isoformat(),
    }}


def _upgrade(source, target, schema, spec, old, columns, indexes, progress):
    from etl.label_local_sql import quote
    from etl.label_local_sources import source_table_ddl, source_index_clauses, source_select_sql
    from etl.label_incremental_sources import read_fingerprints, validate_delta, validate_local_table, FINGERPRINT_VERSION, partition_expression
    names = [row['column_name'] for row in columns]
    validate_upgrade(old, names)
    by_name = {row['column_name']: row for row in columns}
    validate_local_table(target, schema, spec, [by_name[n] for n in old['columns']], indexes, old)
    suffix = uuid4().hex[:8]
    stage_name = LOCAL_TABLE + '__shared_' + suffix
    previous_name = LOCAL_TABLE + '__previous_' + suffix
    stage = f'{quote(schema)}.{quote(stage_name)}'
    sql, params = source_select_sql(spec, names)
    remote = read_fingerprints(source, spec, names, sql, params)
    total = sum(part['rows'] for part in remote.values())
    if not total: raise RuntimeError('shared product source is empty')
    with target.cursor() as cursor:
        cursor.execute(source_table_ddl(stage, columns))
    target.commit()
    count = 0
    insert = f"insert into {stage} ({','.join(quote(n) for n in names)}) values ({','.join('%s' for _ in names)})"
    with source.cursor() as reader:
        reader.execute(sql, params or None)
        while rows := reader.fetchmany(5000):
            with target.cursor() as writer:
                writer.executemany(insert, [tuple(row[n] for n in names) for row in rows])
            target.commit(); count += len(rows)
            progress({'stage': 'shared_product_upgrade_copy', 'rows': count, 'expected_rows': total})
    if count != total: raise RuntimeError('shared product upgrade count mismatch')
    actual = read_fingerprints(target, spec, names, f'select * from {stage}')
    validate_delta(remote, actual, tuple(remote))
    clauses = source_index_clauses(columns, indexes)
    if clauses:
        with target.cursor() as cursor: cursor.execute(f'alter table {stage} ' + ', '.join(clauses))
        target.commit()
    item = {**old, 'columns': names, 'rows': total, 'partitions': remote,
            'fingerprint_version': FINGERPRINT_VERSION,
            'partition_expression': partition_expression(spec.local_name),
            'sha256': hashlib.sha256(json.dumps(remote, sort_keys=True).encode()).hexdigest()}
    return item, stage_name, previous_name


def prepare_shared_product(source, target, schemas, *, progress=print):
    """Publish one complete raw input version before any product consumer starts."""
    from etl.label_local_sql import quote
    from etl.label_local_sources import source_specs, read_metadata, project_columns, configure_source_keepalive
    from etl.label_incremental_sources import validate_manifest, validate_control_tables, stage_source, publish_incremental, manifest_hash
    identifier = run_id()
    if not identifier: return None
    schema = schemas.target_schema
    lock = 'label_local_generation:' + schema
    with target.cursor() as cursor:
        cursor.execute('select get_lock(%s,0) as acquired', (lock,))
        if cursor.fetchone()['acquired'] != 1: raise RuntimeError('label input generation is already running')
    try:
        with target.cursor() as cursor:
            cursor.execute(f'select manifest_json from {quote(schema)}.dashboard_label_local_input where singleton=1')
            row = cursor.fetchone()
        if not row: raise RuntimeError('shared product requires an existing complete local input batch')
        previous = json.loads(row['manifest_json']); validate_manifest(previous)
        validate_control_tables(target, schema)
        old = next(item for item in previous['sources'] if item['local_name'] == LOCAL_TABLE)
        if can_reuse(old): return old
        spec = next(spec for spec in source_specs() if spec.local_name == LOCAL_TABLE)
        with target.cursor() as cursor:
            cursor.execute("set session time_zone='+08:00'")
        metadata, indexes = read_metadata(source, spec); require_columns(metadata)
        columns = project_columns(spec.reference, metadata, indexes)
        source.autocommit(True)
        with source.cursor() as cursor:
            cursor.execute("set session time_zone='+08:00'")
            cursor.execute('set session transaction isolation level repeatable read')
        configure_source_keepalive(source); source.autocommit(False)
        source.rollback()
        upgrading = old.get('columns') != [c['column_name'] for c in columns]
        replacements = []
        if upgrading:
            item, stage_name, previous_name = _upgrade(source, target, schema, spec, old, columns, indexes, progress)
            transferred = item['rows']; changed = tuple(item['partitions'])
        else:
            item, replacement, transferred, _, complete = stage_source(
                source, target, schema, spec, old, old.get('raw_fba_date'), progress, allow_shared=False)
            if replacement: replacements.append(replacement)
            changed = tuple(key for key in old.get('partitions', {}).keys() | item['partitions'].keys()
                            if old.get('partitions', {}).get(key) != item['partitions'].get(key))
            progress(complete)
        source.commit()
        item = _shared_marker(retain_known_partitions(item, old), identifier)
        item['shared_acquisition']['changed_partitions'] = list(changed)
        item['shared_acquisition']['previous_sha256'] = old['sha256']
        if upgrading: item['shared_acquisition']['previous_table'] = previous_name
        manifests = [item if part['local_name'] == LOCAL_TABLE else part for part in previous['sources']]
        result = {**previous, 'batch_id': str(uuid4()), 'sources': manifests,
                  'input_hash': manifest_hash(manifests), 'transferred_rows': transferred,
                  'sync_mode': 'shared_product', 'input_consistency': 'product_source_snapshot_with_retained_other_inputs'}
        from etl.daily_update_guard import assert_daily_lock
        assert_daily_lock(target)
        if upgrading:
            marker_stage = 'dashboard_label_local_input__shared_' + uuid4().hex[:8]
            marker_previous = marker_stage.replace('__shared_', '__previous_')
            with target.cursor() as cursor:
                cursor.execute(f'create table {quote(schema)}.{quote(marker_stage)} (singleton tinyint primary key,manifest_json json not null) engine=innodb')
                cursor.execute(f'insert into {quote(schema)}.{quote(marker_stage)} values (1,%s)', (json.dumps(result, ensure_ascii=False),))
                for part in manifests:
                    cursor.execute(f'insert into {quote(schema)}.dashboard_label_local_source_batch (batch_id,source_name,local_name,row_count,content_sha256,contract_json) values (%s,%s,%s,%s,%s,%s)',
                        (result['batch_id'],part['source'],part['local_name'],part['rows'],part['sha256'],json.dumps(part,ensure_ascii=False)))
            target.commit()
            assert_daily_lock(target)
            with target.cursor() as cursor:
                cursor.execute(f'rename table {quote(schema)}.{quote(LOCAL_TABLE)} to {quote(schema)}.{quote(previous_name)}, {quote(schema)}.{quote(stage_name)} to {quote(schema)}.{quote(LOCAL_TABLE)}, {quote(schema)}.dashboard_label_local_input to {quote(schema)}.{quote(marker_previous)}, {quote(schema)}.{quote(marker_stage)} to {quote(schema)}.dashboard_label_local_input')
            target.commit()
        else:
            publish_incremental(target, schema, previous, result, replacements)
        progress({'stage':'shared_product_ready','run_id':identifier,'rows':item['rows'],
                  'transferred_rows':transferred,'changed_partitions':len(changed), 'upgraded':upgrading})
        return item
    except Exception:
        with suppress(Exception): source.rollback()
        with suppress(Exception): target.rollback()
        raise
    finally:
        with suppress(Exception): source.autocommit(True)
        with suppress(Exception):
            with target.cursor() as cursor: cursor.execute('select release_lock(%s)',(lock,))


class SharedTrafficRepository:
    """Offline adapter; web repositories keep their existing source contract."""
    table = "lx_statistics_product_performance"
    def __init__(self, db):
        self.db = db
        self.schema = os.getenv('DASHBOARD_DWD_SOURCE_SCHEMA', 'dwd_datasync')
        with db.connect() as conn:
            self.item = read_shared_item(conn, db.database)
    def revision(self):
        with self.db.connect() as conn:
            item = read_shared_item(conn, self.db.database)
        if item['sha256'] != self.item['sha256']:
            raise RuntimeError('shared product input changed during traffic preparation')
        return (self.schema, self.table, 'shared:' + item['sha256'])
    def source_connect(self, autocommit=False):
        from etl.dashboard_daily_update import build_schema_config
        from dataclasses import replace
        schemas = replace(build_schema_config(), target_schema=self.db.database, dwd_source_schema=self.schema)
        return product_reader(schemas, target_factory=self.db.connect)


def shared_traffic_ranges(state, start, end, revision, coverage_start, item):
    """Return None unless the prior prepared state matches the exact delta base."""
    from datetime import timedelta, date
    from app.services.label_analysis_materialized import unpack
    if (not state or state['first_loaded'] > start
            or str(state['coverage_start'])[:10] != coverage_start):
        return None
    previous = tuple(unpack(state['source_revision']))
    base = 'shared:' + str(item.get('shared_acquisition', {}).get('previous_sha256', ''))
    if previous != (*revision[:2], base): return None
    days = set()
    for key in item.get('shared_acquisition', {}).get('changed_partitions', ()):
        try: day = date.fromisoformat(key)
        except (TypeError, ValueError): continue
        if start <= day <= end: days.add(day)
    day = max(start, state['last_loaded'] + timedelta(days=1))
    while day <= end: days.add(day); day += timedelta(days=1)
    from etl.product_performance_history_sync import coalesce_dates
    return coalesce_dates(days)
