import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable

from etl.dashboard_daily_update import build_schema_config, connect_source, connect_target, render_sql
from etl.replenishment_update import apply_database_ini_env


DEFAULT_PERIODS = (7, 14, 30, 90)
RULE_VERSION = "label_id_1_20260702_v1_raw_predict_profit"
ROLE_PRIORITY = (101, 102, 103, 104)
LABEL_FACT_TABLE = "dws_datasync.dws_标签表"
LABEL_DETAIL_TABLE = "dws_datasync.dws_标签详情表"
LOCAL_LABEL_FACT_TABLE = "etl_datasync_test.dashboard_label_fact_snapshot"
LOCAL_LABEL_DETAIL_TABLE = "etl_datasync_test.dashboard_label_detail_snapshot"
LOCAL_LABEL_FACT_STATE_TABLE = "etl_datasync_test.dashboard_label_fact_snapshot_state"
SNAPSHOT_BATCH_SIZE = 5000


def fact_table_sql(table_name: str, *, include_indexes: bool) -> str:
    indexes = """
    key idx_label_date (label_id, data_date, label_period, country_category, store(80), msku(120)),
    key idx_date_unit (data_date, country_category, store(80), msku(120), country(40), label_id, label_period),
    key idx_date_label_period (data_date, label_id, label_period),
    key idx_msku_date (msku(120), data_date)
    """ if include_indexes else ""
    index_clause = f",\n{indexes.rstrip()}" if indexes else ""
    return f"""
create table if not exists {table_name} (
    id bigint unsigned not null auto_increment,
    data_date date not null comment '标签事实日期',
    country_category varchar(20) null,
    country varchar(100) null,
    store varchar(100) not null,
    msku varchar(500) not null,
    label_id int not null,
    label_period varchar(20) not null,
    created_time datetime not null,
    evidence_blob mediumblob null,
    primary key (id)
    {index_clause}
) engine=InnoDB default charset=utf8mb4 comment='标签中心本地事实快照，仅保留最近两个标签日期';
"""


def detail_table_sql(table_name: str, *, include_indexes: bool) -> str:
    index_clause = ",\n    key idx_label_detail_parent_child (label_id, sub_label_id)" if include_indexes else ""
    return f"""
create table if not exists {table_name} (
    label_id int not null,
    label_name text null,
    sub_label_id int not null,
    sub_label_name text null,
    tag_rule text null,
    business_definition text null,
    business_owner text null,
    label_category text null,
    update_frequency text null,
    mutual_exclusion text null,
    status text null,
    create_time datetime not null,
    tagging_method varchar(20) null,
    key idx_label_detail_sub_label (sub_label_id)
    {index_clause}
) engine=InnoDB default charset=utf8mb4 comment='标签中心本地标签详情快照';
"""


def fact_state_table_sql(table_name: str) -> str:
    return f"""
create table if not exists {table_name} (
    data_date date not null,
    source_row_count bigint not null,
    source_max_created_time datetime(6) null,
    source_checksum_sum decimal(30,0) not null,
    source_checksum_xor bigint unsigned not null,
    synced_at datetime not null default current_timestamp,
    primary key (data_date)
) engine=InnoDB default charset=utf8mb4 comment='标签事实快照远端同步指纹';
"""


def _source_row_checksum_sql() -> str:
    return """
crc32(concat_ws(
    char(31),
    coalesce(cast(data_date as char), ''),
    coalesce(country_category, ''),
    coalesce(country, ''),
    coalesce(store, ''),
    coalesce(msku, ''),
    coalesce(cast(label_id as char), ''),
    coalesce(label_period, ''),
    coalesce(date_format(created_time, '%%Y-%%m-%%d %%H:%%i:%%s.%%f'), ''),
    coalesce(cast(evidence_json as char), '')
))
""".strip()


def _source_fingerprint_sql() -> str:
    checksum_sql = _source_row_checksum_sql()
    return f"""
select
    data_date,
    count(*) as source_row_count,
    max(created_time) as source_max_created_time,
    coalesce(sum({checksum_sql}), 0) as source_checksum_sum,
    coalesce(bit_xor({checksum_sql}), 0) as source_checksum_xor
from {LABEL_FACT_TABLE} force index (idx_dt)
where data_date = %s
group by data_date
"""


FACT_INSERT_SQL = """
insert into {table_name} (
    data_date, country_category, country, store, msku,
    label_id, label_period, created_time, evidence_blob
) values (
    %(data_date)s, %(country_category)s, %(country)s, %(store)s, %(msku)s,
    %(label_id)s, %(label_period)s, %(created_time)s, %(evidence_blob)s
)
"""


DETAIL_INSERT_SQL = """
insert into {table_name} (
    label_id, label_name, sub_label_id, sub_label_name, tag_rule,
    business_definition, business_owner, label_category, update_frequency,
    mutual_exclusion, status, create_time, tagging_method
) values (
    %(label_id)s, %(label_name)s, %(sub_label_id)s, %(sub_label_name)s, %(tag_rule)s,
    %(business_definition)s, %(business_owner)s, %(label_category)s, %(update_frequency)s,
    %(mutual_exclusion)s, %(status)s, %(create_time)s, %(tagging_method)s
)
"""


CREATE_TABLE_SQL = """
create table if not exists etl_datasync_test.dashboard_label_rule_evidence_snapshot (
    id bigint unsigned not null auto_increment,
    label_date date not null comment '远端标签事实日期',
    country_category varchar(64) not null,
    store varchar(128) not null,
    msku varchar(128) not null,
    parent_label_id int not null,
    label_period varchar(16) not null,
    period_start date not null,
    period_end date not null,
    sales_qty decimal(18,4) null,
    daily_sales decimal(18,6) null,
    tag_sales_amount decimal(18,4) null,
    tag_gross_profit decimal(18,4) null comment '原始预测毛利润口径',
    tag_gross_margin decimal(18,6) null,
    computed_sub_label_id int null,
    remote_sub_label_id int null,
    rule_version varchar(96) not null,
    evidence_status varchar(16) not null comment 'matched/mismatch/missing',
    generated_at datetime not null default current_timestamp,
    primary key (id),
    unique key uk_label_rule_evidence (label_date, country_category, store, msku, parent_label_id, label_period),
    key idx_label_rule_evidence_msku (msku, label_date),
    key idx_label_rule_evidence_status (label_date, label_period, evidence_status)
) engine=InnoDB default charset=utf8mb4 comment='标签变化原因审计证据，仅保留最近两个标签日期';
"""


LOCAL_AGGREGATE_SQL = """
select
    country_category,
    seller_name_new as store,
    seller_sku_adj as msku,
    sum(coalesce(sales_qty, 0)) as sales_qty,
    sum(coalesce(sales_amount, 0)) as tag_sales_amount,
    sum(coalesce(raw_order_gross_profit, 0)) as tag_gross_profit
from etl_datasync_test.dashboard_product_performance_daily
where dt_date between %(period_start)s and %(period_end)s
  and seller_sku_adj is not null and seller_sku_adj != ''
  and seller_name_new is not null and seller_name_new != ''
  and country_category is not null and country_category != ''
  and seller_sku_adj not like 'Amazon.Found.%%'
group by country_category, seller_name_new, seller_sku_adj;
"""


INSERT_SQL = """
insert into etl_datasync_test.dashboard_label_rule_evidence_snapshot (
    label_date, country_category, store, msku, parent_label_id, label_period,
    period_start, period_end, sales_qty, daily_sales, tag_sales_amount,
    tag_gross_profit, tag_gross_margin, computed_sub_label_id,
    remote_sub_label_id, rule_version, evidence_status
) values (
    %(label_date)s, %(country_category)s, %(store)s, %(msku)s, 1, %(label_period)s,
    %(period_start)s, %(period_end)s, %(sales_qty)s, %(daily_sales)s, %(tag_sales_amount)s,
    %(tag_gross_profit)s, %(tag_gross_margin)s, %(computed_sub_label_id)s,
    %(remote_sub_label_id)s, %(rule_version)s, %(evidence_status)s
);
"""


def parse_periods(value: str) -> tuple[int, ...]:
    result = []
    for token in value.split(","):
        days = int(token.strip().lower().removesuffix("d"))
        if days < 1:
            raise ValueError("period must be at least 1 day")
        if days not in result:
            result.append(days)
    return tuple(result)


def classify_sales_role(daily_sales: float, gross_margin: float) -> int:
    if daily_sales > 5 and gross_margin > 0.15:
        return 101
    if 1 <= daily_sales <= 5 and gross_margin > 0.25:
        return 101
    if daily_sales > 5 and 0.05 <= gross_margin <= 0.15:
        return 102
    if 1 <= daily_sales <= 5 and 0.10 <= gross_margin <= 0.25:
        return 102
    if 1 <= daily_sales <= 5 and 0.05 <= gross_margin <= 0.10:
        return 103
    if 0 < daily_sales < 1 and gross_margin > 0.05:
        return 103
    return 104


def latest_label_dates(source_conn) -> tuple[date, ...]:
    with source_conn.cursor() as cursor:
        cursor.execute(
            f"select distinct data_date from {LABEL_FACT_TABLE} "
            "order by data_date desc limit 2"
        )
        rows = cursor.fetchall()
    return tuple(row["data_date"] for row in rows if row.get("data_date"))


def _batched(rows: Iterable[dict], batch_size: int = SNAPSHOT_BATCH_SIZE) -> Iterable[list[dict]]:
    batch: list[dict] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def snapshot_date_plan(
    label_dates: tuple[date, ...],
    available_local_dates: set[date],
) -> tuple[tuple[date, ...], tuple[date, ...]]:
    if not label_dates:
        return (), ()
    reusable_dates = tuple(
        item for item in label_dates[1:] if item in available_local_dates
    )
    remote_dates = tuple(
        item
        for item in label_dates
        if item == label_dates[0] or item not in available_local_dates
    )
    return remote_dates, reusable_dates


def _same_source_fingerprint(source: dict | None, local: dict | None) -> bool:
    if not source or not local:
        return False
    return (
        int(local.get("local_row_count") or 0)
        == int(source.get("source_row_count") or 0)
        and all(
            source.get(field) == local.get(field)
            for field in (
                "source_row_count",
                "source_max_created_time",
                "source_checksum_sum",
                "source_checksum_xor",
            )
        )
    )


def _snapshot_sync_plan(
    label_dates: tuple[date, ...],
    local_state: dict[date, dict],
    latest_source_fingerprint: dict | None,
    *,
    supports_blob: bool,
) -> tuple[tuple[date, ...], tuple[date, ...]]:
    if not label_dates or not supports_blob:
        return label_dates, ()
    latest_date = label_dates[0]
    available_local_dates = {
        row_date
        for row_date, state in local_state.items()
        if int(state.get("local_row_count") or 0) > 0
    }
    latest_is_current = _same_source_fingerprint(
        latest_source_fingerprint,
        local_state.get(latest_date),
    )
    reused_dates = tuple(
        item
        for item in label_dates
        if item in available_local_dates
        and (item != latest_date or latest_is_current)
    )
    remote_dates = tuple(item for item in label_dates if item not in reused_dates)
    return remote_dates, reused_dates


def _prepare_snapshot_tables(target_conn, schemas) -> tuple[str, str, str, str, str]:
    fact_table = render_sql(LOCAL_LABEL_FACT_TABLE, schemas)
    detail_table = render_sql(LOCAL_LABEL_DETAIL_TABLE, schemas)
    state_table = render_sql(LOCAL_LABEL_FACT_STATE_TABLE, schemas)
    fact_stage = f"{fact_table}__staging"
    detail_stage = f"{detail_table}__staging"
    with target_conn.cursor() as cursor:
        cursor.execute(fact_table_sql(fact_table, include_indexes=True))
        cursor.execute(detail_table_sql(detail_table, include_indexes=True))
        cursor.execute(fact_state_table_sql(state_table))
        cursor.execute(f"drop table if exists {fact_stage}")
        cursor.execute(f"drop table if exists {detail_stage}")
        cursor.execute(fact_table_sql(fact_stage, include_indexes=False))
        cursor.execute(detail_table_sql(detail_stage, include_indexes=False))
    target_conn.commit()
    return fact_table, detail_table, state_table, fact_stage, detail_stage


def _load_detail_snapshot(source_conn, target_conn, detail_stage: str) -> int:
    with source_conn.cursor() as source_cursor:
        source_cursor.execute(
            f"""
            select label_id, label_name, sub_label_id, sub_label_name, tag_rule,
                   business_definition, business_owner, label_category, update_frequency,
                   mutual_exclusion, status, create_time, tagging_method
            from {LABEL_DETAIL_TABLE}
            """
        )
        rows = source_cursor.fetchall()
    with target_conn.cursor() as target_cursor:
        if rows:
            target_cursor.executemany(DETAIL_INSERT_SQL.format(table_name=detail_stage), rows)
    target_conn.commit()
    return len(rows)


def _load_local_snapshot_state(
    target_conn,
    fact_table: str,
    state_table: str,
    label_dates: tuple[date, ...],
) -> dict[date, dict]:
    placeholders = ",".join(["%s"] * len(label_dates))
    with target_conn.cursor() as cursor:
        cursor.execute(
            f"""
            select
                dates.data_date,
                dates.local_row_count,
                state.source_row_count,
                state.source_max_created_time,
                state.source_checksum_sum,
                state.source_checksum_xor
            from (
                select data_date, count(*) as local_row_count
                from {fact_table}
                where data_date in ({placeholders})
                group by data_date
            ) dates
            left join {state_table} state on state.data_date = dates.data_date
            """,
            label_dates,
        )
        return {row["data_date"]: row for row in cursor.fetchall()}


def _load_latest_source_fingerprint(
    source_conn,
    latest_date: date,
    local_state: dict | None,
) -> dict | None:
    if not local_state or local_state.get("source_row_count") is None:
        return None
    with source_conn.cursor() as cursor:
        cursor.execute(_source_fingerprint_sql(), (latest_date,))
        return cursor.fetchone()


def _load_fact_snapshot(
    source_conn,
    target_conn,
    fact_table: str,
    state_table: str,
    fact_stage: str,
    label_dates: tuple[date, ...],
) -> tuple[dict[str, int], tuple[date, ...], dict[date, dict]]:
    local_state = _load_local_snapshot_state(
        target_conn,
        fact_table,
        state_table,
        label_dates,
    )
    with target_conn.cursor() as cursor:
        cursor.execute(f"show columns from {fact_table} like 'evidence_blob'")
        supports_blob = cursor.fetchone() is not None
    latest_date = label_dates[0]
    latest_source_fingerprint = _load_latest_source_fingerprint(
        source_conn,
        latest_date,
        local_state.get(latest_date),
    )
    remote_dates, reusable_dates = _snapshot_sync_plan(
        label_dates,
        local_state,
        latest_source_fingerprint,
        supports_blob=supports_blob,
    )
    reused = sum(
        int(local_state[item].get("local_row_count") or 0)
        for item in reusable_dates
    )
    if reused:
        print(f"  label facts : {reused:,} existing rows retained locally")

    copied = 0
    source_fingerprints: dict[date, dict] = {}
    insert_sql = FACT_INSERT_SQL.format(table_name=fact_stage)
    for label_date in remote_dates:
        fingerprint = {
            "data_date": label_date,
            "source_row_count": 0,
            "source_max_created_time": None,
            "source_checksum_sum": 0,
            "source_checksum_xor": 0,
        }
        with source_conn.cursor() as source_cursor:
            source_cursor.execute(
                f"""
                select data_date, country_category, country, store, msku,
                       label_id, label_period, created_time,
                       compress(cast(evidence_json as char)) as evidence_blob,
                       {_source_row_checksum_sql()} as source_row_checksum
                from {LABEL_FACT_TABLE} force index (idx_dt)
                where data_date = %s
                """,
                (label_date,),
            )
            with target_conn.cursor() as target_cursor:
                date_copied = 0
                for batch in _batched(source_cursor):
                    for row in batch:
                        checksum = int(row.get("source_row_checksum") or 0)
                        created_time = row.get("created_time")
                        fingerprint["source_row_count"] += 1
                        fingerprint["source_checksum_sum"] += checksum
                        fingerprint["source_checksum_xor"] ^= checksum
                        if (
                            created_time is not None
                            and (
                                fingerprint["source_max_created_time"] is None
                                or created_time > fingerprint["source_max_created_time"]
                            )
                        ):
                            fingerprint["source_max_created_time"] = created_time
                    target_cursor.executemany(insert_sql, batch)
                    copied += len(batch)
                    date_copied += len(batch)
                    if date_copied % 50000 == 0:
                        target_conn.commit()
                        print(
                            f"  label facts : {label_date.isoformat()} "
                            f"copied {date_copied:,} rows remotely"
                        )
        target_conn.commit()
        print(f"  label facts : {label_date.isoformat()} copied {date_copied:,} rows remotely")
        if date_copied == 0:
            raise RuntimeError(
                f"remote label fact date {label_date.isoformat()} returned no rows"
            )
        source_fingerprints[label_date] = fingerprint
    with target_conn.cursor() as cursor:
        cursor.execute(f"select count(*) as row_count from {fact_stage}")
        staged = int((cursor.fetchone() or {}).get("row_count") or 0)
    if staged != copied:
        raise RuntimeError(
            f"label fact staging row count mismatch: inserted={copied}, staged={staged}"
        )
    return (
        {
            "fact_rows": reused + copied,
            "remote_fact_rows": copied,
            "reused_fact_rows": reused,
        },
        remote_dates,
        source_fingerprints,
    )


def _replace_snapshot_dates(
    target_conn,
    fact_table: str,
    detail_table: str,
    state_table: str,
    fact_stage: str,
    detail_stage: str,
    label_dates: tuple[date, ...],
    refresh_dates: tuple[date, ...],
    source_fingerprints: dict[date, dict],
) -> None:
    try:
        with target_conn.cursor() as cursor:
            if refresh_dates:
                placeholders = ",".join(["%s"] * len(refresh_dates))
                cursor.execute(
                    f"delete from {fact_table} where data_date in ({placeholders})",
                    refresh_dates,
                )
                cursor.execute(
                    f"""
                    insert into {fact_table} (
                        data_date, country_category, country, store, msku,
                        label_id, label_period, created_time, evidence_blob
                    )
                    select data_date, country_category, country, store, msku,
                           label_id, label_period, created_time, evidence_blob
                    from {fact_stage}
                    """
                )
            placeholders = ",".join(["%s"] * len(label_dates))
            cursor.execute(
                f"delete from {fact_table} where data_date not in ({placeholders})",
                label_dates,
            )
            cursor.execute(f"delete from {detail_table}")
            cursor.execute(
                f"""
                insert into {detail_table} (
                    label_id, label_name, sub_label_id, sub_label_name, tag_rule,
                    business_definition, business_owner, label_category, update_frequency,
                    mutual_exclusion, status, create_time, tagging_method
                )
                select label_id, label_name, sub_label_id, sub_label_name, tag_rule,
                       business_definition, business_owner, label_category, update_frequency,
                       mutual_exclusion, status, create_time, tagging_method
                from {detail_stage}
                """
            )
            cursor.execute(
                f"delete from {state_table} where data_date not in ({placeholders})",
                label_dates,
            )
            if refresh_dates:
                cursor.executemany(
                    f"""
                    insert into {state_table} (
                        data_date, source_row_count, source_max_created_time,
                        source_checksum_sum, source_checksum_xor
                    ) values (
                        %(data_date)s, %(source_row_count)s, %(source_max_created_time)s,
                        %(source_checksum_sum)s, %(source_checksum_xor)s
                    ) on duplicate key update
                        source_row_count=values(source_row_count),
                        source_max_created_time=values(source_max_created_time),
                        source_checksum_sum=values(source_checksum_sum),
                        source_checksum_xor=values(source_checksum_xor),
                        synced_at=current_timestamp
                    """,
                    [source_fingerprints[item] for item in refresh_dates],
                )
        target_conn.commit()
    except Exception:
        target_conn.rollback()
        raise


def sync_label_snapshots(source_conn, target_conn, schemas, label_dates: tuple[date, ...]) -> dict[str, int]:
    if not label_dates:
        raise RuntimeError("remote label fact table has no label dates")
    fact_table, detail_table, state_table, fact_stage, detail_stage = _prepare_snapshot_tables(
        target_conn,
        schemas,
    )
    try:
        detail_rows = _load_detail_snapshot(source_conn, target_conn, detail_stage)
        fact_counts, refresh_dates, source_fingerprints = _load_fact_snapshot(
            source_conn,
            target_conn,
            fact_table,
            state_table,
            fact_stage,
            label_dates,
        )
        _replace_snapshot_dates(
            target_conn,
            fact_table,
            detail_table,
            state_table,
            fact_stage,
            detail_stage,
            label_dates,
            refresh_dates,
            source_fingerprints,
        )
    except Exception:
        target_conn.rollback()
        raise
    finally:
        with target_conn.cursor() as cursor:
            cursor.execute(f"drop table if exists {fact_stage}")
            cursor.execute(f"drop table if exists {detail_stage}")
        target_conn.commit()
    return {**fact_counts, "detail_rows": detail_rows}


def remote_role_facts(
    source_conn,
    label_dates: tuple[date, ...],
    *,
    fact_table: str = LOCAL_LABEL_FACT_TABLE,
    detail_table: str = LOCAL_LABEL_DETAIL_TABLE,
) -> dict[tuple[date, str, str, str, str], set[int]]:
    if not label_dates:
        return {}
    placeholders = ",".join(["%s"] * len(label_dates))
    sql = f"""
        select data_date, country_category, store, msku, label_period, label_id
        from {fact_table}
        where data_date in ({placeholders})
          and msku not like %s
          and label_id in (
              select sub_label_id from {detail_table}
              where label_id = 1 and sub_label_id is not null
          )
    """
    result: dict[tuple[date, str, str, str, str], set[int]] = defaultdict(set)
    with source_conn.cursor() as cursor:
        cursor.execute(sql, (*label_dates, "Amazon.Found.%"))
        for row in cursor.fetchall():
            key = (
                row["data_date"], str(row.get("country_category") or ""),
                str(row.get("store") or ""), str(row.get("msku") or ""),
                str(row.get("label_period") or ""),
            )
            result[key].add(int(row["label_id"]))
    return result


def local_rule_inputs(target_conn, schemas, label_date: date, days: int) -> dict[tuple[str, str, str], dict]:
    period_start = label_date - timedelta(days=days - 1)
    params = {"period_start": period_start, "period_end": label_date}
    with target_conn.cursor() as cursor:
        cursor.execute(render_sql(LOCAL_AGGREGATE_SQL, schemas), params)
        rows = cursor.fetchall()
    result = {}
    for row in rows:
        sales_qty = float(row.get("sales_qty") or 0)
        sales_amount = float(row.get("tag_sales_amount") or 0)
        gross_profit = float(row.get("tag_gross_profit") or 0)
        daily_sales = sales_qty / days
        gross_margin = gross_profit / sales_amount if sales_amount else 0
        result[(str(row["country_category"]), str(row["store"]), str(row["msku"]))] = {
            "sales_qty": sales_qty,
            "daily_sales": daily_sales,
            "tag_sales_amount": sales_amount,
            "tag_gross_profit": gross_profit,
            "tag_gross_margin": gross_margin,
            "computed_sub_label_id": classify_sales_role(daily_sales, gross_margin),
        }
    return result


def build_rows(target_conn, schemas, label_dates: tuple[date, ...], periods: tuple[int, ...], remote_facts) -> list[dict]:
    rows = []
    for label_date in label_dates:
        for days in periods:
            period = f"{days}d"
            local = local_rule_inputs(target_conn, schemas, label_date, days)
            remote_for_period = {
                (country, store, msku): child_ids
                for (fact_date, country, store, msku, fact_period), child_ids in remote_facts.items()
                if fact_date == label_date and fact_period == period
            }
            for grain in sorted(set(local) | set(remote_for_period)):
                local_row = local.get(grain)
                remote_ids = remote_for_period.get(grain, set())
                remote_primary = next((child_id for child_id in ROLE_PRIORITY if child_id in remote_ids), None)
                computed = local_row.get("computed_sub_label_id") if local_row else None
                status = "matched" if computed is not None and computed in remote_ids else ("mismatch" if computed is not None and remote_ids else "missing")
                rows.append({
                    "label_date": label_date,
                    "country_category": grain[0], "store": grain[1], "msku": grain[2],
                    "label_period": period,
                    "period_start": label_date - timedelta(days=days - 1), "period_end": label_date,
                    "sales_qty": local_row.get("sales_qty") if local_row else None,
                    "daily_sales": local_row.get("daily_sales") if local_row else None,
                    "tag_sales_amount": local_row.get("tag_sales_amount") if local_row else None,
                    "tag_gross_profit": local_row.get("tag_gross_profit") if local_row else None,
                    "tag_gross_margin": local_row.get("tag_gross_margin") if local_row else None,
                    "computed_sub_label_id": computed,
                    "remote_sub_label_id": remote_primary,
                    "rule_version": RULE_VERSION,
                    "evidence_status": status,
                })
    return rows


def refresh(target_conn, schemas, rows: list[dict], label_dates: tuple[date, ...]) -> int:
    table = render_sql("etl_datasync_test.dashboard_label_rule_evidence_snapshot", schemas)
    status_rank = {"matched": 0, "mismatch": 1, "missing": 2}
    deduplicated: dict[tuple, dict] = {}
    for row in rows:
        key = (
            row["label_date"], str(row["country_category"]).casefold(),
            str(row["store"]).casefold(), str(row["msku"]).casefold(),
            row["label_period"],
        )
        current = deduplicated.get(key)
        if current is None or status_rank.get(row["evidence_status"], 9) < status_rank.get(current["evidence_status"], 9):
            deduplicated[key] = row
    rows = list(deduplicated.values())
    try:
        with target_conn.cursor() as cursor:
            cursor.execute(render_sql(CREATE_TABLE_SQL, schemas))
            if label_dates:
                placeholders = ",".join(["%s"] * len(label_dates))
                cursor.execute(f"delete from {table} where label_date in ({placeholders})", label_dates)
            if rows:
                cursor.executemany(render_sql(INSERT_SQL, schemas), rows)
            if label_dates:
                placeholders = ",".join(["%s"] * len(label_dates))
                cursor.execute(f"delete from {table} where label_date not in ({placeholders})", label_dates)
        target_conn.commit()
    except Exception:
        target_conn.rollback()
        raise
    return len(rows)


def run_update(periods: tuple[int, ...] = DEFAULT_PERIODS) -> dict:
    apply_database_ini_env()
    schemas = build_schema_config()
    target_conn = None
    source_conn = None
    try:
        target_conn = connect_target()
        source_conn = connect_source()
        label_dates = latest_label_dates(source_conn)
        if not label_dates:
            raise RuntimeError("remote label fact table has no label dates")
        snapshot_counts = sync_label_snapshots(source_conn, target_conn, schemas, label_dates)
        remote_facts = remote_role_facts(
            target_conn,
            label_dates,
            fact_table=render_sql(LOCAL_LABEL_FACT_TABLE, schemas),
            detail_table=render_sql(LOCAL_LABEL_DETAIL_TABLE, schemas),
        )
        rows = build_rows(target_conn, schemas, label_dates, periods, remote_facts)
        affected = refresh(target_conn, schemas, rows, label_dates)
        return {
            "status": "refreshed",
            "label_dates": [item.isoformat() for item in label_dates],
            "latest_date": label_dates[0].isoformat(),
            "fact_rows": snapshot_counts["fact_rows"],
            "remote_fact_rows": snapshot_counts["remote_fact_rows"],
            "reused_fact_rows": snapshot_counts["reused_fact_rows"],
            "detail_rows": snapshot_counts["detail_rows"],
            "evidence_rows": affected,
            "periods": [f"{days}d" for days in periods],
        }
    finally:
        if source_conn is not None:
            source_conn.close()
        if target_conn is not None:
            target_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sales-role label change evidence for the latest two remote label dates.")
    parser.add_argument("--periods", default=",".join(f"{days}d" for days in DEFAULT_PERIODS))
    parser.add_argument("--dry-run", action="store_true")
    args, _ = parser.parse_known_args()
    periods = parse_periods(args.periods)
    if args.dry_run:
        print(f"Label rule evidence plan: periods={','.join(f'{days}d' for days in periods)}, retain_dates=2")
        return

    result = run_update(periods)
    print("Local label snapshots and rule evidence updated")
    print(f"  label_dates : {', '.join(result['label_dates'])}")
    print(f"  label_facts : {result['fact_rows']:,}")
    print(f"  remote_rows : {result['remote_fact_rows']:,}")
    print(f"  reused_rows : {result['reused_fact_rows']:,}")
    print(f"  label_meta  : {result['detail_rows']:,}")
    print(f"  periods     : {', '.join(result['periods'])}")
    print(f"  evidence    : {result['evidence_rows']:,}")


if __name__ == "__main__":
    main()
