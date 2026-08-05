import argparse
from datetime import date, datetime, timedelta

from etl.dashboard_daily_update import build_schema_config, connect_target, render_sql
from etl.replenishment_update import apply_database_ini_env


DEFAULT_PERIODS = (7, 14, 30, 90)
SALES_ROLE_RULE_VERSION = "label_id_1_20260702_v1"


CREATE_SALES_ROLE_PERIOD_SNAPSHOT_SQL = """
create table if not exists etl_datasync_test.dashboard_sales_role_period_snapshot (
    id bigint unsigned not null auto_increment comment '自增主键',
    snapshot_date date not null comment '快照日期，通常为统计周期结束日的下一天',
    period_code varchar(16) not null comment '统计周期编码：7d/14d/30d/90d',
    period_days int not null comment '统计周期天数',
    period_start date not null comment '统计周期开始日期，含当天',
    period_end date not null comment '统计周期结束日期，含当天',
    seller_sku_adj varchar(128) not null comment 'MSKU，来自产品表现每日统计表seller_sku_adj',
    seller_name_new varchar(128) not null comment '店铺新名称',
    country_category varchar(64) not null comment '国家类别，如欧洲站/北美站/英国站',
    local_sku_sample varchar(128) null comment 'SKU示例，同一聚合粒度下取一个local_sku样例',
    country_count int not null default 0 comment '覆盖国家数，按周期内country去重',
    countries text null comment '覆盖国家列表，按周期内country去重拼接',
    source_row_count int not null default 0 comment '来源每日明细行数',
    period_seen_days int not null default 0 comment '周期内出现天数',
    sales_days int not null default 0 comment '周期内有销量的天数',
    inventory_days int not null default 0 comment '周期内FBA可售库存大于0的天数',
    sales_qty decimal(18,4) not null default 0 comment '周期销量',
    daily_sales decimal(18,6) not null default 0 comment '周期日均销量，sales_qty/period_days',
    sales_amount decimal(18,4) not null default 0 comment '周期销售额',
    sales_amount_ex_tax decimal(18,4) not null default 0 comment '周期不含税销售额',
    order_gross_profit decimal(18,4) not null default 0 comment '周期订单毛利额',
    order_gross_margin decimal(18,6) null comment '周期订单毛利率，order_gross_profit/sales_amount',
    settlement_gross_profit decimal(18,4) not null default 0 comment '周期结算毛利额',
    settlement_gross_margin decimal(18,6) null comment '周期结算毛利率，settlement_gross_profit/sales_amount',
    ending_inventory_qty decimal(18,4) not null default 0 comment '周期末FBA可售库存，取period_end当天各国家共享库存最大值',
    max_inventory_qty decimal(18,4) not null default 0 comment '周期内单日最大FBA可售库存',
    avg_inventory_qty decimal(18,4) not null default 0 comment '周期内日均FBA可售库存',
    ad_spend decimal(18,4) not null default 0 comment '周期广告花费',
    ad_sales decimal(18,4) not null default 0 comment '周期广告销售额',
    ad_orders decimal(18,4) not null default 0 comment '周期广告订单量',
    ad_clicks decimal(18,4) not null default 0 comment '周期广告点击量',
    ad_impressions decimal(18,4) not null default 0 comment '周期广告曝光量',
    acos decimal(18,6) null comment '广告ACOS，ad_spend/ad_sales',
    tacos decimal(18,6) null comment '总ACOS，ad_spend/sales_amount',
    sessions_total decimal(18,4) not null default 0 comment '周期会话数',
    return_count decimal(18,4) not null default 0 comment '周期退货数量',
    return_amount decimal(18,4) not null default 0 comment '周期退货金额',
    net_amount decimal(18,4) not null default 0 comment '周期净销售额',
    sales_role_code varchar(32) not null comment '销售角色编码：star/potential/dog/problem',
    sales_role_label varchar(32) not null comment '销售角色名称：明星产品/潜力产品/瘦狗产品/问题产品',
    sales_role_sub_label_id int not null comment '销售角色子标签ID，对应标签详情表sub_label_id',
    sales_role_rule_version varchar(64) not null comment '销售角色规则版本',
    created_at datetime not null default current_timestamp comment '创建时间',
    updated_at datetime not null default current_timestamp on update current_timestamp comment '更新时间',
    primary key (id),
    unique key uk_sales_role_period_grain (
        snapshot_date, period_code, seller_sku_adj, seller_name_new, country_category
    ),
    key idx_sales_role_period (snapshot_date, period_code, period_start, period_end),
    key idx_sales_role_role (snapshot_date, period_code, sales_role_code),
    key idx_sales_role_store (snapshot_date, period_code, seller_name_new),
    key idx_sales_role_country_category (snapshot_date, period_code, country_category),
    key idx_sales_role_msku (seller_sku_adj)
) engine=InnoDB default charset=utf8mb4 comment='销售角色分析全量周期快照，基于产品表现每日统计表按MSKU+店铺新+国家类别聚合';
"""


DELETE_SALES_ROLE_PERIOD_SNAPSHOT_SQL = """
delete from etl_datasync_test.dashboard_sales_role_period_snapshot
where snapshot_date = %(snapshot_date)s
  and period_code = %(period_code)s
  and period_start = %(period_start)s
  and period_end = %(period_end)s;
"""


INSERT_SALES_ROLE_PERIOD_SNAPSHOT_SQL = """
insert into etl_datasync_test.dashboard_sales_role_period_snapshot (
    snapshot_date, period_code, period_days, period_start, period_end,
    seller_sku_adj, seller_name_new, country_category, local_sku_sample,
    country_count, countries, source_row_count, period_seen_days, sales_days, inventory_days,
    sales_qty, daily_sales, sales_amount, sales_amount_ex_tax,
    order_gross_profit, order_gross_margin, settlement_gross_profit, settlement_gross_margin,
    ending_inventory_qty, max_inventory_qty, avg_inventory_qty,
    ad_spend, ad_sales, ad_orders, ad_clicks, ad_impressions, acos, tacos,
    sessions_total, return_count, return_amount, net_amount,
    sales_role_code, sales_role_label, sales_role_sub_label_id, sales_role_rule_version
)
select
    %(snapshot_date)s as snapshot_date,
    %(period_code)s as period_code,
    %(period_days)s as period_days,
    %(period_start)s as period_start,
    %(period_end)s as period_end,
    classified.seller_sku_adj,
    classified.seller_name_new,
    classified.country_category,
    classified.local_sku_sample,
    classified.country_count,
    classified.countries,
    classified.source_row_count,
    classified.period_seen_days,
    classified.sales_days,
    classified.inventory_days,
    classified.sales_qty,
    classified.daily_sales,
    classified.sales_amount,
    classified.sales_amount_ex_tax,
    classified.order_gross_profit,
    classified.order_gross_margin,
    classified.settlement_gross_profit,
    classified.settlement_gross_margin,
    classified.ending_inventory_qty,
    classified.max_inventory_qty,
    classified.avg_inventory_qty,
    classified.ad_spend,
    classified.ad_sales,
    classified.ad_orders,
    classified.ad_clicks,
    classified.ad_impressions,
    classified.acos,
    classified.tacos,
    classified.sessions_total,
    classified.return_count,
    classified.return_amount,
    classified.net_amount,
    classified.sales_role_code,
    classified.sales_role_label,
    classified.sales_role_sub_label_id,
    %(sales_role_rule_version)s as sales_role_rule_version
from (
    select
        agg.*,
        case
            when agg.daily_sales > 5 and agg.order_gross_margin > 0.15 then 'star'
            when agg.daily_sales between 1 and 5 and agg.order_gross_margin > 0.25 then 'star'
            when agg.daily_sales > 5 and agg.order_gross_margin between 0.05 and 0.15 then 'potential'
            when agg.daily_sales between 1 and 5 and agg.order_gross_margin between 0.10 and 0.25 then 'potential'
            when agg.daily_sales between 1 and 5 and agg.order_gross_margin >= 0.05 and agg.order_gross_margin < 0.10 then 'dog'
            when agg.daily_sales < 1 and agg.order_gross_margin > 0.05 then 'dog'
            else 'problem'
        end as sales_role_code,
        case
            when agg.daily_sales > 5 and agg.order_gross_margin > 0.15 then '明星产品'
            when agg.daily_sales between 1 and 5 and agg.order_gross_margin > 0.25 then '明星产品'
            when agg.daily_sales > 5 and agg.order_gross_margin between 0.05 and 0.15 then '潜力产品'
            when agg.daily_sales between 1 and 5 and agg.order_gross_margin between 0.10 and 0.25 then '潜力产品'
            when agg.daily_sales between 1 and 5 and agg.order_gross_margin >= 0.05 and agg.order_gross_margin < 0.10 then '瘦狗产品'
            when agg.daily_sales < 1 and agg.order_gross_margin > 0.05 then '瘦狗产品'
            else '问题产品'
        end as sales_role_label,
        case
            when agg.daily_sales > 5 and agg.order_gross_margin > 0.15 then 101
            when agg.daily_sales between 1 and 5 and agg.order_gross_margin > 0.25 then 101
            when agg.daily_sales > 5 and agg.order_gross_margin between 0.05 and 0.15 then 102
            when agg.daily_sales between 1 and 5 and agg.order_gross_margin between 0.10 and 0.25 then 102
            when agg.daily_sales between 1 and 5 and agg.order_gross_margin >= 0.05 and agg.order_gross_margin < 0.10 then 103
            when agg.daily_sales < 1 and agg.order_gross_margin > 0.05 then 103
            else 104
        end as sales_role_sub_label_id
    from (
        select
            p.seller_sku_adj,
            p.seller_name_new,
            p.country_category,
            substring_index(group_concat(distinct nullif(p.local_sku, '') order by p.local_sku separator ','), ',', 1) as local_sku_sample,
            count(distinct p.country) as country_count,
            group_concat(distinct p.country order by p.country separator ',') as countries,
            count(*) as source_row_count,
            count(distinct p.dt_date) as period_seen_days,
            count(distinct case when p.sales_qty > 0 then p.dt_date end) as sales_days,
            count(distinct case when p.afn_fulfillable_quantity > 0 then p.dt_date end) as inventory_days,
            sum(p.sales_qty) as sales_qty,
            sum(p.sales_qty) / %(period_days)s as daily_sales,
            sum(p.sales_amount) as sales_amount,
            sum(p.sales_amount_ex_tax) as sales_amount_ex_tax,
            sum(p.order_gross_profit) as order_gross_profit,
            case when sum(p.sales_amount) = 0 then null else sum(p.order_gross_profit) / sum(p.sales_amount) end as order_gross_margin,
            sum(p.settlement_gross_profit) as settlement_gross_profit,
            case when sum(p.sales_amount) = 0 then null else sum(p.settlement_gross_profit) / sum(p.sales_amount) end as settlement_gross_margin,
            max(case when p.dt_date = %(period_end)s then p.afn_fulfillable_quantity else 0 end) as ending_inventory_qty,
            max(p.afn_fulfillable_quantity) as max_inventory_qty,
            avg(p.afn_fulfillable_quantity) as avg_inventory_qty,
            sum(p.ad_spend) as ad_spend,
            sum(p.ad_sales) as ad_sales,
            sum(p.ad_orders) as ad_orders,
            sum(p.ad_clicks) as ad_clicks,
            sum(p.ad_impressions) as ad_impressions,
            case when sum(p.ad_sales) = 0 then null else sum(p.ad_spend) / sum(p.ad_sales) end as acos,
            case when sum(p.sales_amount) = 0 then null else sum(p.ad_spend) / sum(p.sales_amount) end as tacos,
            sum(p.sessions_total) as sessions_total,
            sum(p.return_count) as return_count,
            sum(p.return_amount) as return_amount,
            sum(p.net_amount) as net_amount
        from etl_datasync_test.dashboard_product_performance_daily p
        where p.dt_date between %(period_start)s and %(period_end)s
          and p.seller_sku_adj is not null
          and p.seller_sku_adj != ''
          and p.seller_name_new is not null
          and p.seller_name_new != ''
          and p.country_category is not null
          and p.country_category != ''
        group by
            p.seller_sku_adj,
            p.seller_name_new,
            p.country_category
    ) agg
) classified;
"""


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def latest_product_date(conn, schemas) -> date:
    with conn.cursor() as cursor:
        cursor.execute(
            render_sql(
                "select max(dt_date) as max_date from etl_datasync_test.dashboard_product_performance_daily",
                schemas,
            )
        )
        value = (cursor.fetchone() or {}).get("max_date")
    if not value:
        raise RuntimeError("dashboard_product_performance_daily has no data")
    return value


def period_params(snapshot_date: date, period_end: date, period_days: int) -> dict[str, object]:
    if period_days < 1:
        raise ValueError("period_days must be at least 1")
    return {
        "snapshot_date": snapshot_date,
        "period_code": f"{period_days}d",
        "period_days": period_days,
        "period_start": period_end - timedelta(days=period_days - 1),
        "period_end": period_end,
        "sales_role_rule_version": SALES_ROLE_RULE_VERSION,
    }


def ensure_table(conn, schemas) -> None:
    with conn.cursor() as cursor:
        cursor.execute(render_sql(CREATE_SALES_ROLE_PERIOD_SNAPSHOT_SQL, schemas))
    conn.commit()


def refresh_period(conn, schemas, params: dict[str, object]) -> int:
    with conn.cursor() as cursor:
        cursor.execute(render_sql(DELETE_SALES_ROLE_PERIOD_SNAPSHOT_SQL, schemas), params)
        cursor.execute(render_sql(INSERT_SALES_ROLE_PERIOD_SNAPSHOT_SQL, schemas), params)
        affected = max(cursor.rowcount, 0)
    conn.commit()
    return affected


def parse_periods(value: str) -> tuple[int, ...]:
    periods = []
    for raw in value.split(","):
        token = raw.strip().lower().removesuffix("d")
        if not token:
            continue
        days = int(token)
        if days < 1:
            raise ValueError("period must be at least 1 day")
        periods.append(days)
    if not periods:
        raise ValueError("at least one period is required")
    return tuple(dict.fromkeys(periods))


def main() -> None:
    apply_database_ini_env()
    parser = argparse.ArgumentParser(description="Build full-pool sales role period snapshots.")
    parser.add_argument("--snapshot-date", help="Snapshot date, format YYYY-MM-DD. Default: period_end + 1 day.")
    parser.add_argument("--period-end", help="Period end date, format YYYY-MM-DD. Default: latest product daily date.")
    parser.add_argument("--periods", default=",".join(f"{days}d" for days in DEFAULT_PERIODS), help="Comma separated periods, e.g. 7d,14d,30d,90d.")
    parser.add_argument("--skip-ddl", action="store_true", help="Skip create table statement.")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only; do not write data.")
    args = parser.parse_args()

    schemas = build_schema_config()
    periods = parse_periods(args.periods)

    conn = connect_target()
    try:
        period_end = parse_day(args.period_end) if args.period_end else latest_product_date(conn, schemas)
        snapshot_date = parse_day(args.snapshot_date) if args.snapshot_date else period_end + timedelta(days=1)
        print("Sales role snapshot ETL plan")
        print(f"  target_schema : {schemas.target_schema}")
        print(f"  source_table  : {schemas.target_schema}.dashboard_product_performance_daily")
        print(f"  target_table  : {schemas.target_schema}.dashboard_sales_role_period_snapshot")
        print(f"  snapshot_date : {snapshot_date}")
        print(f"  period_end    : {period_end}")
        print(f"  periods       : {', '.join(f'{days}d' for days in periods)}")

        if args.dry_run:
            return

        if not args.skip_ddl:
            ensure_table(conn, schemas)
            print("[success] ensured dashboard_sales_role_period_snapshot")

        for days in periods:
            params = period_params(snapshot_date, period_end, days)
            affected = refresh_period(conn, schemas, params)
            print(f"[success] {params['period_code']}: {params['period_start']} ~ {params['period_end']}, rows={affected}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
