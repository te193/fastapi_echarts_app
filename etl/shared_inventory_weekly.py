"""Build weekly inventory from acquired daily inputs, replacing changed weeks only."""
from datetime import timedelta
import hashlib
import json

CONTRACT_VERSION = "daily_inventory_weekly_v1"
EMPTY_SIGNATURE = hashlib.sha256(b"empty weekly daily inputs").hexdigest()
STATE_TABLE = "etl_datasync_test.dashboard_inventory_weekly_input_state"


def changed_weeks(current, saved):
    return sorted(week for week in current.keys() | saved.keys()
                  if saved.get(week) != current.get(week, EMPTY_SIGNATURE))


def signature_sql():
    # Only the latest date of each source affects a historical week. The current
    # week has always been overwritten by the exact requested source day.
    sources = []
    for table, fields in (
        ("dashboard_inventory_daily_snapshot", "available_total,available_price,stock_up_num,stock_up_num_price"),
        ("dashboard_restock_daily_snapshot", "local_quantity,purchase_shipping_quantity,purchase_cost,transport_cost"),
    ):
        sources.append(f"""select d.snapshot_date,d.item_key,d.country_category,d.seller_name_new,d.seller_sku_adj,
            '{table}' as source_type,sha2(cast(json_array(d.snapshot_date,d.item_key,
            d.country_category,d.seller_name_new,d.seller_sku_adj,{','.join('d.'+f for f in fields.split(','))})
            as char character set utf8mb4),256) as row_hash
            from etl_datasync_test.{table} d join (
                select date_sub(snapshot_date,interval weekday(snapshot_date) day) as week_start,
                       max(snapshot_date) as last_day
                from etl_datasync_test.{table}
                where snapshot_date <= %(snapshot_date)s
                group by week_start
            ) latest on latest.last_day=d.snapshot_date
            where latest.week_start < date_sub(%(snapshot_date)s,interval weekday(%(snapshot_date)s) day)
               or d.snapshot_date = %(snapshot_date)s""")
    return """select date_sub(snapshot_date,interval weekday(snapshot_date) day) as week_start,
        source_type,count(*) as rows_count,
        sum(cast(conv(substr(row_hash,1,16),16,10) as decimal(20,0))) as hash_1,
        sum(cast(conv(substr(row_hash,17,16),16,10) as decimal(20,0))) as hash_2
        from (""" + " union all ".join(sources) + ") inputs group by week_start,source_type"


def current_week_insert_sql():
    from etl.dashboard_daily_update import INSERT_INVENTORY_WEEKLY_SNAPSHOT_SQL
    # Restrict both daily input calendars BEFORE latest-date selection. This
    # preserves the legacy remote step's exact day, including missing identities.
    sql = INSERT_INVENTORY_WEEKLY_SNAPSHOT_SQL.replace(
        "select snapshot_date, 'inventory' as source_type from etl_datasync_test.dashboard_inventory_daily_snapshot",
        "select snapshot_date, 'inventory' as source_type from etl_datasync_test.dashboard_inventory_daily_snapshot where snapshot_date = %(snapshot_date)s",
    ).replace(
        "select snapshot_date, 'restock' as source_type from etl_datasync_test.dashboard_restock_daily_snapshot",
        "select snapshot_date, 'restock' as source_type from etl_datasync_test.dashboard_restock_daily_snapshot where snapshot_date = %(snapshot_date)s",
    )
    # The join back to the daily tables already uses the selected exact dates.
    return sql


def load_signatures(conn, schemas, params):
    from etl.dashboard_daily_update import render_sql
    with conn.cursor() as cursor:
        cursor.execute(render_sql(signature_sql(), schemas), params)
        rows = cursor.fetchall()
    grouped = {}
    for row in rows:
        grouped.setdefault(row['week_start'], []).append([
            row['source_type'], int(row['rows_count']),
            str(int(row['hash_1'] or 0)), str(int(row['hash_2'] or 0)),
        ])
    return {week: hashlib.sha256(json.dumps(sorted(parts)).encode()).hexdigest()
            for week, parts in grouped.items()}


def load_saved(conn, schemas):
    from etl.dashboard_daily_update import render_sql
    with conn.cursor() as cursor:
        cursor.execute(render_sql(f"select week_start,signature from {STATE_TABLE} where contract_version=%s", schemas), (CONTRACT_VERSION,))
        return {row['week_start']: row['signature'] for row in cursor.fetchall()}


def refresh(conn, schemas, params, *, current):
    from etl.dashboard_daily_update import render_sql, INSERT_INVENTORY_WEEKLY_SNAPSHOT_SQL
    with conn.cursor() as cursor:
        cursor.execute(render_sql(f"""create table if not exists {STATE_TABLE} (
            week_start date primary key,signature char(64) not null,
            contract_version varchar(64) not null,updated_at datetime(6) not null
            ) engine=innodb""", schemas))
    # Acquire the daily inputs and their signatures in the same target snapshot.
    # Both the business rows and signature are committed by execute_target_step.
    signatures = load_signatures(conn, schemas, params)
    saved = load_saved(conn, schemas)
    this_week = params['snapshot_date'] - timedelta(days=params['snapshot_date'].weekday())
    # A missing exact current day must clear stale week rows, even on bootstrap.
    signatures.setdefault(this_week, EMPTY_SIGNATURE)
    weeks = [w for w in changed_weeks(signatures, saved)
             if w <= this_week and (w == this_week) == current]
    affected = 0
    with conn.cursor() as cursor:
        for week in weeks:
            bound = {**params, 'refresh_week_start': week}
            cursor.execute(render_sql("delete from etl_datasync_test.dashboard_inventory_weekly_snapshot where week_start=%(refresh_week_start)s", schemas), bound)
            sql = current_week_insert_sql() if current else INSERT_INVENTORY_WEEKLY_SNAPSHOT_SQL.replace(
                "where snapshot_date <= %(snapshot_date)s",
                "where snapshot_date <= %(snapshot_date)s and date_sub(snapshot_date,interval weekday(snapshot_date) day) = %(refresh_week_start)s",
            )
            cursor.execute(render_sql(sql, schemas), bound)
            affected += max(cursor.rowcount, 0)
            cursor.execute(render_sql(f"""insert into {STATE_TABLE}
                (week_start,signature,contract_version,updated_at) values (%s,%s,%s,now(6))
                on duplicate key update signature=values(signature),contract_version=values(contract_version),updated_at=values(updated_at)""", schemas),
                (week, signatures.get(week, EMPTY_SIGNATURE), CONTRACT_VERSION))
    print(f"[info] inventory_weekly_local: mode={'current' if current else 'history'} changed_weeks={len(weeks)} affected_rows={affected}", flush=True)
    return affected
