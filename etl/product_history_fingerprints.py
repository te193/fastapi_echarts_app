"""Compare derived history rows at their stored precision, preserving NULLs."""
from etl.dashboard_daily_update import (
    PRODUCT_DAILY_COLUMNS,
    PRODUCT_FINGERPRINT_DECIMAL_COLUMNS,
    PRODUCT_FINGERPRINT_INTEGER_COLUMNS,
)


BUSINESS_COLUMNS = tuple(column for column in PRODUCT_DAILY_COLUMNS
                         if column not in {'created_at', 'updated_at'})


def fingerprint_sql(rows_sql, *, columns=BUSINESS_COLUMNS,
                    decimal_columns=PRODUCT_FINGERPRINT_DECIMAL_COLUMNS,
                    integer_columns=PRODUCT_FINGERPRINT_INTEGER_COLUMNS):
    values = []
    for column in columns:
        value = f'`{column}`'
        if column in decimal_columns:
            value = f'cast({value} as decimal(18,4))'
        elif column in integer_columns:
            value = f'cast({value} as signed)'
        # JSON preserves NULL vs empty/zero and escapes field separators.
        values.append(f'cast({value} as char)')
    parts = []
    for index in range(4):
        part = f'conv(substring(row_sha,{index * 16 + 1},16),16,10)'
        parts.append(f'sum(cast({part} as decimal(65,0))) as hash_sum_{index}')
        parts.append(f'bit_xor(cast({part} as unsigned)) as hash_xor_{index}')
    return f'''select dt_date,count(*) as row_count,{','.join(parts)}
        from (
            select dt_date,sha2(cast(json_array({','.join(values)}) as char character set utf8mb4),256) as row_sha
            from ({rows_sql.strip().rstrip(';')}) product_rows
        ) fingerprint_rows group by dt_date order by dt_date'''


def load_fingerprints(conn, rows_sql, params, **options):
    with conn.cursor() as cursor:
        cursor.execute(fingerprint_sql(rows_sql, **options), params)
        rows = cursor.fetchall()
    fields = ['row_count'] + [f'hash_{kind}_{index}' for index in range(4) for kind in ('sum', 'xor')]
    return {row['dt_date']: tuple(int(row[field]) for field in fields) for row in rows}


def local_rows_sql(table):
    columns = ','.join(f'`{column}`' for column in BUSINESS_COLUMNS)
    return f'''select {columns} from {table}
        where dt_date between %(product_start_date)s and %(product_end_date)s'''
