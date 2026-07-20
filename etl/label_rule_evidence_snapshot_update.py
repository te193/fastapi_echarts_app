import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta

from etl.dashboard_daily_update import build_schema_config, connect_source, connect_target, render_sql
from etl.replenishment_update import apply_database_ini_env


DEFAULT_PERIODS = (7, 14, 30, 90)
RULE_VERSION = "label_id_1_20260702_v1_raw_predict_profit"
ROLE_PRIORITY = (101, 102, 103, 104)
LABEL_FACT_TABLE = "dws_datasync.dws_标签表"
LABEL_DETAIL_TABLE = "dws_datasync.dws_标签详情表"


CREATE_TABLE_SQL = """
create table if not exists etl_datasync.dashboard_label_rule_evidence_snapshot (
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
from etl_datasync.dashboard_product_performance_daily
where dt_date between %(period_start)s and %(period_end)s
  and seller_sku_adj is not null and seller_sku_adj != ''
  and seller_name_new is not null and seller_name_new != ''
  and country_category is not null and country_category != ''
  and seller_sku_adj not like 'Amazon.Found.%%'
group by country_category, seller_name_new, seller_sku_adj;
"""


INSERT_SQL = """
insert into etl_datasync.dashboard_label_rule_evidence_snapshot (
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
            "where msku not like %s order by data_date desc limit 2",
            ("Amazon.Found.%",),
        )
        rows = cursor.fetchall()
    return tuple(row["data_date"] for row in rows if row.get("data_date"))


def remote_role_facts(source_conn, label_dates: tuple[date, ...]) -> dict[tuple[date, str, str, str, str], set[int]]:
    if not label_dates:
        return {}
    placeholders = ",".join(["%s"] * len(label_dates))
    sql = f"""
        select data_date, country_category, store, msku, label_period, label_id
        from {LABEL_FACT_TABLE}
        where data_date in ({placeholders})
          and msku not like %s
          and label_id in (
              select sub_label_id from {LABEL_DETAIL_TABLE}
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
    table = render_sql("etl_datasync.dashboard_label_rule_evidence_snapshot", schemas)
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


def main() -> None:
    apply_database_ini_env()
    parser = argparse.ArgumentParser(description="Build sales-role label change evidence for the latest two remote label dates.")
    parser.add_argument("--periods", default=",".join(f"{days}d" for days in DEFAULT_PERIODS))
    parser.add_argument("--dry-run", action="store_true")
    args, _ = parser.parse_known_args()
    periods = parse_periods(args.periods)
    schemas = build_schema_config()
    if args.dry_run:
        print(f"Label rule evidence plan: periods={','.join(f'{days}d' for days in periods)}, retain_dates=2")
        return

    target_conn = connect_target()
    source_conn = connect_source()
    try:
        label_dates = latest_label_dates(source_conn)
        if not label_dates:
            raise RuntimeError("remote label fact table has no label dates")
        remote_facts = remote_role_facts(source_conn, label_dates)
        rows = build_rows(target_conn, schemas, label_dates, periods, remote_facts)
        affected = refresh(target_conn, schemas, rows, label_dates)
        print("Label rule evidence snapshot updated")
        print(f"  label_dates : {', '.join(item.isoformat() for item in label_dates)}")
        print(f"  periods     : {', '.join(f'{days}d' for days in periods)}")
        print(f"  rows        : {affected}")
    finally:
        source_conn.close()
        target_conn.close()


if __name__ == "__main__":
    main()
