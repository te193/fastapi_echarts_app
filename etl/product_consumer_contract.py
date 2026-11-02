"""Applied per-day dependencies for the one product-fact producer.

This is bounded metadata, not another raw copy. It is committed with the facts.
Only a pinned, complete local input generation may use this fast path.
"""
from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
import re

RAW_COLUMNS = (
    'start_date', 'country', 'local_sku', 'seller_name', 'seller_sku',
    'volume', 'amount', 'predict_gross_profit', 'gross_profit',
    'afn_fulfillable_quantity', 'spend', 'ad_order_quantity', 'ad_sales_amount',
    'clicks', 'impressions', 'sessions_total', 'rank', 'return_count',
    'return_amount', 'net_amount',
)
RULE_VERSION = 'product-performance-daily-v1'
TABLE = 'dashboard_product_consumer_partition'
CONSUMER = 'product_performance_daily'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), default=str).encode()).hexdigest()


def validate_sql(sql):
    clean = re.sub(r"'(?:''|\\.|[^'])*'", "''", sql.lower())
    clean = re.sub(r'/\*.*?\*/|--[^\n]*', '', clean, flags=re.S)
    sources = re.findall(r'\b(?:from|join)\s+([\w.`]+)', clean)
    if sources != ['dwd_datasync.lx_statistics_product_performance', 'src'] or re.search(r'\bjoin\b', clean):
        raise ValueError('product dependency source/join contract changed')
    if (not re.search(r'\bfrom\s+dwd_datasync\.lx_statistics_product_performance\s+where\b', clean)
            or not re.search(r'\bfrom\s+src\s+group\s+by\b', clean)):
        raise ValueError('product dependency FROM structure changed')
    # Only the raw CTE contains source identifiers; outer aliases are not inputs.
    raw = clean.split(')\nselect', 1)[0]
    raw = raw.replace('dwd_datasync.lx_statistics_product_performance', '')
    raw = re.sub(r'%\([a-z_][a-z_0-9]*\)s', '0', raw)
    tokens = re.findall(r'[a-z_][a-z_0-9]*|\S', raw)
    keywords = {'with', 'src', 'as', 'select', 'case', 'when', 'then', 'else', 'end',
                'in', 'from', 'where', 'or', 'and', 'not', 'like', 'null', 'is'}
    functions = {'year', 'yearweek', 'month', 'date', 'locate', 'left', 'if', 'length',
                 'substring_index', 'replace', 'coalesce'}
    used = set()
    for index, token in enumerate(tokens):
        if not re.fullmatch(r'[a-z_][a-z_0-9]*', token):
            continue
        if index and tokens[index - 1] == 'as':
            continue  # Exempt only this alias occurrence, never its other uses.
        if token in RAW_COLUMNS:
            used.add(token)
        elif token in keywords:
            continue
        elif token in functions and index + 1 < len(tokens) and tokens[index + 1] == '(':
            continue
        else:
            raise ValueError(f'product dependency identifier not declared: {token}')
    if used != set(RAW_COLUMNS):
        raise ValueError(f'product dependency fields changed: {sorted(used ^ set(RAW_COLUMNS))}')


def rule_sha(sql, *, rule_version=RULE_VERSION, semantic_epoch=None):
    from etl.product_history_fingerprints import BUSINESS_COLUMNS
    validate_sql(sql)
    return digest((rule_version, sql, RAW_COLUMNS, BUSINESS_COLUMNS,
                   'json-sha256-multiset-v1', semantic_epoch))


def raw_stamp(item, day):
    return digest((item.get('columns'), item.get('fingerprint_version'),
                   item['partitions'].get(str(day))))


def requires_projection(state, stamp, rule, output_rows):
    return not state or (state['raw_stamp'], state['rule_sha'], state['output_rows']) != (
        stamp, rule, output_rows)


def requires_aggregate(state, dependency_fp, rule, output_rows):
    return not state or (state['dependency_fp'], state['rule_sha'], state['output_rows']) != (
        dependency_fp, rule, output_rows)


def covered_dates(item, states, start, end, *, target_days=()):
    known = set()
    explicit = item.get('shared_acquisition', {}).get('changed_partitions', ())
    for key in set(item['partitions']) | set(explicit) | set(item.get('known_partitions', ())):
        try:
            day = date.fromisoformat(key)
        except (ValueError, TypeError):
            continue  # NULL/invalid raw rows remain retained; they have no fact date.
        if str(day) == key:
            known.add(day)
    if known:
        # A complete raw generation proves absent interior days are empty. The
        # exterior remains unknown until a producer manifest has observed it.
        first, last = min(known), max(known)
        known.update(day for day in target_days if first <= day <= last)
    return tuple(sorted(day for day in known | set(states) if start <= day <= end))


def state_table(schema):
    from etl.label_local_sql import checked_schema, quote
    return f'{quote(checked_schema(schema))}.{TABLE}'


def state_ddl(schema, *, temporary=False):
    create = 'create temporary table' if temporary else 'create table if not exists'
    return f'''{create} {state_table(schema)} (
            consumer_key varchar(64) not null,dt_date date not null,
            rule_sha char(64) not null,raw_stamp char(64) not null,
            dependency_fp json null,output_rows bigint unsigned not null,
            input_run_id varchar(64) not null,updated_at datetime not null,
            primary key(consumer_key,dt_date)
        ) engine=InnoDB'''


def ensure_state(conn, schema):
    with conn.cursor() as cursor:
        cursor.execute(state_ddl(schema))
    conn.commit()  # Called before the fact transaction starts.


def load_states(conn, schema, params):
    with conn.cursor() as cursor:
        cursor.execute(f'''select dt_date,rule_sha,raw_stamp,dependency_fp,output_rows
            from {state_table(schema)} where consumer_key=%(consumer)s
            and dt_date between %(product_start_date)s and %(product_end_date)s''',
                       {**params, 'consumer': CONSUMER})
        rows = cursor.fetchall()
    result = {}
    for row in rows:
        value = json.loads(row['dependency_fp']) if row['dependency_fp'] is not None else None
        result[row['dt_date']] = {**row, 'dependency_fp': tuple(int(part) for part in value) if value is not None else None}
    return result


def output_counts(conn, target_table, params):
    with conn.cursor() as cursor:
        cursor.execute(f'''select dt_date,count(*) as n from {target_table}
            where dt_date between %(product_start_date)s and %(product_end_date)s
            group by dt_date''', params)
        return {row['dt_date']: int(row['n']) for row in cursor.fetchall()}


def semantic_epoch(source, target, schemas, target_table):
    """Raw types/collations and session semantics can change GROUP BY/LIKE/MAX."""
    from etl.shared_product_inputs import LOCAL_TABLE
    with source.cursor() as cursor:
        cursor.execute('''select column_name as column_name,column_type as column_type,
            character_set_name as character_set_name,collation_name as collation_name
            from information_schema.columns where table_schema=%s and table_name=%s
            order by ordinal_position''', (schemas.target_schema, LOCAL_TABLE))
        columns = [row for row in cursor.fetchall() if row['column_name'] in RAW_COLUMNS]
        cursor.execute('select @@session.sql_mode as sql_mode,@@session.time_zone as time_zone,'
                       '@@session.collation_connection as collation_connection')
        session = cursor.fetchone()
    if {row['column_name'] for row in columns} != set(RAW_COLUMNS):
        raise ValueError('product dependency metadata incomplete')
    with target.cursor() as cursor:
        cursor.execute('''select column_name as column_name,column_type as column_type,
            is_nullable as is_nullable,column_default as column_default,
            character_set_name as character_set_name,collation_name as collation_name,
            extra as extra from information_schema.columns
            where table_schema=%s and table_name=%s order by ordinal_position''',
                       (schemas.target_schema, target_table.split('.')[-1].strip('`')))
        output = cursor.fetchall()
    from etl.dashboard_daily_update import CREATE_PRODUCT_DAILY_SQL
    return {'columns': columns, 'session': session, 'output': output,
            'output_contract': CREATE_PRODUCT_DAILY_SQL}


def projection_sql(producer_sql):
    validate_sql(producer_sql)
    raw = re.split(r'\)\s*\nselect\b', producer_sql, maxsplit=1, flags=re.I)[0]
    predicate = re.split(r'\bfrom\s+dwd_datasync\.lx_statistics_product_performance\s+',
                         raw, maxsplit=1, flags=re.I)[1].strip()
    columns = ','.join(f'`{column}`' for column in RAW_COLUMNS)
    return f'''select date(start_date) as dt_date,{columns}
        from dwd_datasync.lx_statistics_product_performance
        {predicate}'''


@dataclass
class Plan:
    candidates: tuple
    states: dict
    rule: str
    item: dict

    def subset(self, start, end):
        return Plan(tuple(day for day in self.candidates if start <= day <= end),
                    {day: value for day, value in self.states.items() if start <= day <= end},
                    self.rule, self.item)


def plan(target, source, schemas, sql, target_table, params, item):
    from etl.dashboard_daily_update import _contiguous_date_ranges
    from etl.product_history_fingerprints import load_fingerprints
    ensure_state(target, schemas.target_schema)
    rule = rule_sha(sql, semantic_epoch=semantic_epoch(source, target, schemas, target_table))
    previous = load_states(target, schemas.target_schema, params)
    counts = output_counts(target, target_table, params)
    days = covered_dates(item, previous, params['product_start_date'], params['product_end_date'],
                         target_days=counts)
    checked = [day for day in days if requires_projection(
        previous.get(day), raw_stamp(item, day), rule, counts.get(day, 0))]
    fingerprints = {}
    for start, end in _contiguous_date_ranges(checked):
        fingerprints.update(load_fingerprints(source, projection_sql(sql), {
            **params, 'product_start_date': start, 'product_end_date': end,
            'next_product_end_date': end + timedelta(days=1)},
            columns=RAW_COLUMNS, decimal_columns=(), integer_columns=()))
    candidates, states = [], {}
    for day in days:
        old = previous.get(day)
        fp = fingerprints.get(day) if day in checked else old['dependency_fp']
        if requires_aggregate(old, fp, rule, counts.get(day, 0)):
            candidates.append(day)
        if day in checked:
            states[day] = dict(rule_sha=rule, raw_stamp=raw_stamp(item, day),
                               dependency_fp=fp, output_rows=counts.get(day, 0))
    print(f'[info] product consumer dependencies: days={len(days)} '
          f'projection_dates={len(checked)} aggregate_dates={len(candidates)}')
    return Plan(tuple(candidates), states, rule, item)


def persist(target, schema, current, target_table, params):
    """No commit here: state and fact writes must succeed or roll back together."""
    if not current.states:
        return
    counts = output_counts(target, target_table, params)
    rows = [(CONSUMER, day, state['rule_sha'], state['raw_stamp'],
             json.dumps([str(part) for part in state['dependency_fp']]
                        if state['dependency_fp'] is not None else None), counts.get(day, 0),
             current.item['shared_acquisition']['run_id']) for day, state in current.states.items()]
    if rows:
        with target.cursor() as cursor:
            cursor.executemany(f'''insert into {state_table(schema)}
                (consumer_key,dt_date,rule_sha,raw_stamp,dependency_fp,output_rows,input_run_id,updated_at)
                values (%s,%s,%s,%s,%s,%s,%s,now()) as new
                on duplicate key update rule_sha=new.rule_sha,raw_stamp=new.raw_stamp,
                dependency_fp=new.dependency_fp,output_rows=new.output_rows,
                input_run_id=new.input_run_id,updated_at=new.updated_at''', rows)


def state_exists(target, schema):
    with target.cursor() as cursor:
        cursor.execute('''select count(*) as n from information_schema.tables
            where table_schema=%s and table_name=%s''', (schema, TABLE))
        return bool(int((cursor.fetchone() or {}).get('n', 0)))


def invalidate(target, schema, params):
    """Alternate/standalone writers may not leave a trusted same-count cache."""
    if not state_exists(target, schema):
        return
    with target.cursor() as cursor:
        clause = '' if params.get('product_full_load') else (
            ' and dt_date between %(product_start_date)s and %(product_end_date)s')
        cursor.execute(f'delete from {state_table(schema)} where consumer_key=%(consumer)s' + clause,
                       {**params, 'consumer': CONSUMER})
