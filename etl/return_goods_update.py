import argparse
import hashlib
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

import pymysql

from etl.dashboard_daily_update import build_schema_config, connect_target, render_sql
from etl.replenishment_update import apply_database_ini_env, parse_day


DEFAULT_LOOKBACK_DAYS = 180
RETURN_STOCK_THRESHOLD = Decimal("5")
MONITOR_DAYS = 21
RETURN_HISTORY_START_DATE = date(2026, 1, 1)


def source_history_start_date(snapshot_date: date, lookback_days: int) -> date:
    # The deployed label procedure identifies complete stockout rounds from
    # the available 2026 history, then applies the 180-day event window.
    return min(RETURN_HISTORY_START_DATE, snapshot_date)

CREATE_RETURN_EVENTS_SQL = """
create table if not exists etl_datasync.dashboard_return_goods_events (
    snapshot_date date not null,
    return_event_id varchar(40) not null,
    item_key varchar(512) not null,
    seller_name_new varchar(128) not null,
    country_category varchar(64) not null,
    seller_sku_adj varchar(128) not null,
    local_sku varchar(128) null,
    return_round int not null,
    stockout_date date not null,
    return_start_date date not null,
    exit_date date null,
    exit_reason varchar(32) null,
    return_days int not null,
    stage varchar(32) not null,
    pre_7d_sales_qty decimal(18,4) null,
    pre_7d_sales_avg decimal(18,4) null,
    pre_7d_gross_margin_rate decimal(18,4) null,
    pre_stockout_sales_role varchar(32) null,
    observe_7d_sales_qty decimal(18,4) null,
    observe_7d_sales_avg decimal(18,4) null,
    post_7d_sales_qty decimal(18,4) null,
    post_7d_sales_avg decimal(18,4) null,
    post_21d_available_sales_qty decimal(18,4) null,
    recovery_window_days int null,
    pre_recovery_sales_qty decimal(18,4) null,
    post_recovery_sales_qty decimal(18,4) null,
    post_return_sales_qty decimal(18,4) null,
    sales_recovery_rate decimal(18,4) null,
    pre_21d_sales_qty decimal(18,4) null,
    post_first_21d_sales_qty decimal(18,4) null,
    d21_recovery_rate decimal(18,6) null,
    recovery_followup_flag tinyint not null default 0,
    post_cumulative_sales_qty decimal(18,4) null,
    cumulative_avg_recovery_rate decimal(18,6) null,
    recovery_followup_status varchar(32) null,
    stable_recovery_start_date date null,
    current_stable_recovery_flag tinyint not null default 0,
    recovery_fallback_flag tinyint not null default 0,
    days_to_standard int null,
    current_fba_sellable decimal(18,4) null,
    current_fba_inbound decimal(18,4) null,
    warning_type varchar(32) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (snapshot_date, return_event_id),
    key idx_return_filter (snapshot_date, country_category, seller_name_new, seller_sku_adj),
    key idx_return_start (return_start_date),
    key idx_return_exit (exit_date),
    key idx_return_warning (snapshot_date, warning_type)
) default charset=utf8mb4;
"""

CREATE_STOCKOUT_POOL_SQL = """
create table if not exists etl_datasync.dashboard_return_goods_stockout_pool (
    snapshot_date date not null,
    item_key varchar(512) not null,
    seller_name_new varchar(128) not null,
    country_category varchar(64) not null,
    seller_sku_adj varchar(128) not null,
    local_sku varchar(128) null,
    first_stockout_date date not null,
    last_stockout_date date not null,
    stockout_days int not null,
    period_sales_qty decimal(18,4) not null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (snapshot_date, item_key),
    key idx_stockout_filter (snapshot_date, country_category, seller_name_new, seller_sku_adj)
) default charset=utf8mb4;
"""

CREATE_STAGE_DAILY_SUMMARY_SQL = """
create table if not exists etl_datasync.dashboard_return_goods_stage_daily_summary (
    snapshot_date date not null,
    stage_key varchar(32) not null,
    segment_key varchar(32) not null,
    segment_name varchar(32) not null,
    stage_day int not null,
    return_day int not null,
    observable_msku int not null,
    ordered_msku int not null,
    cumulative_ordered_msku int not null,
    sales_qty decimal(18,4) not null,
    cumulative_sales_qty decimal(18,4) not null,
    fba_sellable decimal(18,4) not null,
    not_ordered_msku int not null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (snapshot_date, stage_key, segment_key, stage_day),
    key idx_stage_summary_filter (snapshot_date, stage_key, return_day)
) default charset=utf8mb4;
"""

CREATE_COUNTRY_METRICS_SQL = """
create table if not exists etl_datasync.dashboard_return_goods_country_metrics (
    snapshot_date date not null,
    return_event_id varchar(40) not null,
    item_key varchar(512) not null,
    seller_name_new varchar(128) not null,
    country_category varchar(64) not null,
    seller_sku_adj varchar(128) not null,
    country varchar(64) not null,
    local_sku_list varchar(1024) null,
    metric_window_days int not null,
    pre_window_start date not null,
    pre_window_end date not null,
    post_window_start date not null,
    post_window_end date not null,
    pre_sales_qty decimal(18,4) not null default 0,
    pre_sales_amount decimal(18,4) not null default 0,
    pre_order_gross_profit decimal(18,4) not null default 0,
    post_sales_qty decimal(18,4) not null default 0,
    post_sales_amount decimal(18,4) not null default 0,
    post_order_gross_profit decimal(18,4) not null default 0,
    post_order_gross_margin decimal(18,6) null,
    sales_recovery_rate decimal(18,6) null,
    sales_amount_recovery_rate decimal(18,6) null,
    sessions_total decimal(18,4) not null default 0,
    conversion_rate decimal(18,6) null,
    ad_spend decimal(18,4) not null default 0,
    ad_orders decimal(18,4) not null default 0,
    ad_sales decimal(18,4) not null default 0,
    ad_clicks decimal(18,4) not null default 0,
    ad_impressions decimal(18,4) not null default 0,
    acos decimal(18,6) null,
    ctr decimal(18,6) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (snapshot_date, return_event_id, country),
    key idx_return_country_item (snapshot_date, country_category, seller_name_new, seller_sku_adj),
    key idx_return_country_event (return_event_id)
) default charset=utf8mb4;
"""

DELETE_RETURN_EVENTS_SQL = """
delete from etl_datasync.dashboard_return_goods_events
where snapshot_date = %(snapshot_date)s;
"""

DELETE_STOCKOUT_POOL_SQL = """
delete from etl_datasync.dashboard_return_goods_stockout_pool
where snapshot_date = %(snapshot_date)s;
"""

DELETE_STAGE_DAILY_SUMMARY_SQL = """
delete from etl_datasync.dashboard_return_goods_stage_daily_summary
where snapshot_date = %(snapshot_date)s;
"""

DELETE_COUNTRY_METRICS_SQL = """
delete from etl_datasync.dashboard_return_goods_country_metrics
where snapshot_date = %(snapshot_date)s;
"""

INSERT_STOCKOUT_POOL_SQL = """
insert into etl_datasync.dashboard_return_goods_stockout_pool (
    snapshot_date, item_key, seller_name_new, country_category, seller_sku_adj,
    local_sku, first_stockout_date, last_stockout_date, stockout_days, period_sales_qty
)
select
    %(snapshot_date)s as snapshot_date,
    concat_ws('|', seller_name_new, country_category, seller_sku_adj) as item_key,
    seller_name_new,
    country_category,
    seller_sku_adj,
    max(local_sku) as local_sku,
    min(case when fba_sellable = 0 then dt_date end) as first_stockout_date,
    max(case when fba_sellable = 0 then dt_date end) as last_stockout_date,
    sum(case when fba_sellable = 0 then 1 else 0 end) as stockout_days,
    sum(sales_qty) as period_sales_qty
from (
    select
        dt_date,
        seller_name_new,
        country_category,
        seller_sku_adj,
        max(local_sku) as local_sku,
        max(coalesce(afn_fulfillable_quantity, 0)) as fba_sellable,
        sum(coalesce(sales_qty, 0)) as sales_qty
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between %(source_start_date)s and %(snapshot_date)s
      and seller_name_new is not null and seller_name_new <> ''
      and country_category is not null and country_category <> ''
      and seller_sku_adj is not null and seller_sku_adj <> ''
      and seller_sku_adj not like 'amzn.gr.%%'
    group by dt_date, seller_name_new, country_category, seller_sku_adj
) daily_msku_stock
group by seller_name_new, country_category, seller_sku_adj
having stockout_days > 0;
"""

INSERT_STAGE_DAILY_SUMMARY_SQL = """
insert into etl_datasync.dashboard_return_goods_stage_daily_summary (
    snapshot_date, stage_key, segment_key, segment_name, stage_day, return_day,
    observable_msku, ordered_msku, cumulative_ordered_msku, sales_qty,
    cumulative_sales_qty, fba_sellable, not_ordered_msku
)
with recursive days as (
    select 1 as return_day
    union all
    select return_day + 1 from days where return_day < 21
),
latest_events as (
    select *
    from (
        select
            e.*,
            row_number() over (
                partition by e.item_key
                order by e.return_start_date desc, e.return_round desc
            ) as latest_rank
        from etl_datasync.dashboard_return_goods_events e
        inner join etl_datasync.dashboard_return_goods_stockout_pool p
                on p.snapshot_date = e.snapshot_date
               and p.item_key = e.item_key
        where e.snapshot_date = %(snapshot_date)s
          and e.return_start_date <= %(snapshot_date)s
    ) ranked
    where latest_rank = 1
      and return_start_date <= %(snapshot_date)s
      and (exit_date is null or exit_date > %(snapshot_date)s)
      and stage in ('观察期', '运营干预期')
),
daily_msku as (
    select
        dt_date,
        seller_name_new,
        country_category,
        seller_sku_adj,
        sum(coalesce(sales_qty, 0)) as sales_qty,
        max(coalesce(afn_fulfillable_quantity, 0)) as fba_sellable
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between %(source_start_date)s and %(snapshot_date)s
      and seller_name_new is not null and seller_name_new <> ''
      and country_category is not null and country_category <> ''
      and seller_sku_adj is not null and seller_sku_adj <> ''
      and seller_sku_adj not like 'amzn.gr.%%'
    group by dt_date, seller_name_new, country_category, seller_sku_adj
),
stage_days as (
    select
        'observe' as stage_key,
        'observe' as segment_key,
        '观察段' as segment_name,
        d.return_day as stage_day,
        d.return_day
    from days d
    where d.return_day between 1 and 7
    union all
    select
        'operating' as stage_key,
        case when d.return_day <= 7 then 'observe' else 'operating' end as segment_key,
        case when d.return_day <= 7 then '观察段' else '干预段' end as segment_name,
        case when d.return_day <= 7 then d.return_day else d.return_day - 7 end as stage_day,
        d.return_day
    from days d
),
event_calendar as (
    select
        sd.stage_key,
        sd.segment_key,
        sd.segment_name,
        sd.stage_day,
        sd.return_day,
        e.return_event_id,
        e.return_days as event_return_days,
        e.return_start_date,
        e.seller_name_new,
        e.country_category,
        e.seller_sku_adj,
        coalesce(p.sales_qty, 0) as sales_qty,
        coalesce(p.fba_sellable, 0) as fba_sellable
    from stage_days sd
    join latest_events e on (
                            (sd.stage_key = 'observe' and e.stage = '观察期')
                            or (sd.stage_key = 'operating' and e.stage = '运营干预期')
                        )
    left join daily_msku p
           on p.dt_date = date_add(e.return_start_date, interval sd.return_day - 1 day)
          and p.seller_name_new = e.seller_name_new
          and p.country_category = e.country_category
          and p.seller_sku_adj = e.seller_sku_adj
),
event_calendar_with_cumulative as (
    select
        ec.stage_key,
        ec.segment_key,
        ec.segment_name,
        ec.stage_day,
        ec.return_day,
        ec.return_event_id,
        ec.event_return_days,
        ec.sales_qty,
        ec.fba_sellable,
        sum(coalesce(p2.sales_qty, 0)) as event_cumulative_sales_qty
    from event_calendar ec
    left join daily_msku p2
           on p2.dt_date between
                date_add(ec.return_start_date, interval case when ec.segment_key = 'observe' then 0 else 7 end day)
                and date_add(ec.return_start_date, interval ec.return_day - 1 day)
          and p2.seller_name_new = ec.seller_name_new
          and p2.country_category = ec.country_category
          and p2.seller_sku_adj = ec.seller_sku_adj
    group by
        ec.stage_key, ec.segment_key, ec.segment_name, ec.stage_day, ec.return_day,
        ec.return_event_id, ec.event_return_days, ec.sales_qty, ec.fba_sellable
),
current_summary as (
    select
        stage_key,
        segment_key,
        segment_name,
        stage_day,
        return_day,
        count(distinct return_event_id) as observable_msku,
        sum(case when sales_qty > 0 then 1 else 0 end) as ordered_msku,
        sum(sales_qty) as sales_qty,
        sum(fba_sellable) as fba_sellable
    from event_calendar_with_cumulative
    where event_return_days = return_day
    group by stage_key, segment_key, segment_name, stage_day, return_day
),
cumulative_summary as (
    select
        stage_key,
        segment_key,
        segment_name,
        stage_day,
        return_day,
        count(distinct return_event_id) as pool_msku,
        sum(case when coalesce(event_cumulative_sales_qty, 0) > 0 then 1 else 0 end) as cumulative_ordered_msku,
        sum(coalesce(event_cumulative_sales_qty, 0)) as cumulative_sales_qty
    from event_calendar_with_cumulative
    group by stage_key, segment_key, segment_name, stage_day, return_day
)
select
    %(snapshot_date)s as snapshot_date,
    sd.stage_key,
    sd.segment_key,
    sd.segment_name,
    sd.stage_day,
    sd.return_day,
    coalesce(cs.observable_msku, 0) as observable_msku,
    coalesce(cs.ordered_msku, 0) as ordered_msku,
    coalesce(cus.cumulative_ordered_msku, 0) as cumulative_ordered_msku,
    coalesce(cs.sales_qty, 0) as sales_qty,
    coalesce(cus.cumulative_sales_qty, 0) as cumulative_sales_qty,
    coalesce(cs.fba_sellable, 0) as fba_sellable,
    coalesce(cus.pool_msku, 0) - coalesce(cus.cumulative_ordered_msku, 0) as not_ordered_msku
from stage_days sd
left join current_summary cs
       on cs.stage_key = sd.stage_key
      and cs.segment_key = sd.segment_key
      and cs.return_day = sd.return_day
left join cumulative_summary cus
       on cus.stage_key = sd.stage_key
      and cus.segment_key = sd.segment_key
      and cus.return_day = sd.return_day
where coalesce(cus.pool_msku, 0) > 0;
"""

SELECT_PRODUCT_DAILY_SQL = """
with product_daily as (
    select
        dt_date,
        concat_ws('|', seller_name_new, country_category, seller_sku_adj) as item_key,
        country_category,
        seller_name_new,
        seller_sku_adj,
        max(local_sku) as local_sku,
        sum(coalesce(sales_qty, 0)) as sales_qty,
        sum(coalesce(sales_amount, 0)) as sales_amount,
        sum(coalesce(order_gross_profit, 0)) as order_gross_profit,
        max(coalesce(afn_fulfillable_quantity, 0)) as product_fba_sellable
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between %(source_start_date)s and %(snapshot_date)s
      and seller_name_new is not null and seller_name_new <> ''
      and country_category is not null and country_category <> ''
      and seller_sku_adj is not null and seller_sku_adj <> ''
      and seller_sku_adj not like 'amzn.gr.%%'
    group by dt_date, seller_name_new, country_category, seller_sku_adj
),
latest_inventory as (
    select max(snapshot_date) as snapshot_date
    from etl_datasync.dashboard_inventory_daily_snapshot
    where snapshot_date <= %(snapshot_date)s
)
select
    p.dt_date,
    p.item_key,
    p.country_category,
    p.seller_name_new,
    p.seller_sku_adj,
    p.local_sku,
    p.sales_qty,
    p.sales_amount,
    p.order_gross_profit,
    coalesce(p.product_fba_sellable, 0) as afn_fulfillable_quantity,
    coalesce(i.stock_up_num, 0) as fba_inbound_quantity
from product_daily p
cross join latest_inventory li
left join etl_datasync.dashboard_inventory_daily_snapshot i
       on i.snapshot_date = li.snapshot_date
      and i.seller_name_new = p.seller_name_new
      and i.country_category = p.country_category
      and i.seller_sku_adj = p.seller_sku_adj
order by p.item_key, p.dt_date;
"""

INSERT_COUNTRY_METRICS_SQL = """
insert into etl_datasync.dashboard_return_goods_country_metrics (
    snapshot_date, return_event_id, item_key, seller_name_new, country_category, seller_sku_adj,
    country, local_sku_list, metric_window_days, pre_window_start, pre_window_end,
    post_window_start, post_window_end, pre_sales_qty, pre_sales_amount, pre_order_gross_profit,
    post_sales_qty, post_sales_amount, post_order_gross_profit, post_order_gross_margin,
    sales_recovery_rate, sales_amount_recovery_rate, sessions_total, conversion_rate,
    ad_spend, ad_orders, ad_sales, ad_clicks, ad_impressions, acos, ctr
)
with event_windows as (
    select
        e.*,
        greatest(1, coalesce(e.recovery_window_days, least(e.return_days, 21))) as metric_window_days,
        date_sub(e.stockout_date, interval greatest(1, coalesce(e.recovery_window_days, least(e.return_days, 21))) day) as pre_window_start,
        date_sub(e.stockout_date, interval 1 day) as pre_window_end,
        e.return_start_date as post_window_start,
        date_add(e.return_start_date, interval greatest(1, coalesce(e.recovery_window_days, least(e.return_days, 21))) - 1 day) as post_window_end
    from etl_datasync.dashboard_return_goods_events e
    where e.snapshot_date = %(snapshot_date)s
),
daily_by_country as (
    select
        dt_date,
        country_category,
        seller_name_new,
        seller_sku_adj,
        country,
        group_concat(distinct local_sku order by local_sku separator ', ') as local_sku_list,
        sum(coalesce(sales_qty, 0)) as sales_qty,
        sum(coalesce(sales_amount, 0)) as sales_amount,
        sum(coalesce(order_gross_profit, 0)) as order_gross_profit,
        sum(coalesce(sessions_total, 0)) as sessions_total,
        sum(coalesce(ad_spend, 0)) as ad_spend,
        sum(coalesce(ad_orders, 0)) as ad_orders,
        sum(coalesce(ad_sales, 0)) as ad_sales,
        sum(coalesce(ad_clicks, 0)) as ad_clicks,
        sum(coalesce(ad_impressions, 0)) as ad_impressions
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between %(source_start_date)s and %(snapshot_date)s
      and seller_name_new is not null and seller_name_new <> ''
      and country_category is not null and country_category <> ''
      and seller_sku_adj is not null and seller_sku_adj <> ''
      and country is not null and country <> ''
      and seller_sku_adj not like 'amzn.gr.%%'
    group by dt_date, country_category, seller_name_new, seller_sku_adj, country
),
country_windows as (
    select distinct
        e.snapshot_date,
        e.return_event_id,
        e.item_key,
        e.seller_name_new,
        e.country_category,
        e.seller_sku_adj,
        d.country,
        e.metric_window_days,
        e.pre_window_start,
        e.pre_window_end,
        e.post_window_start,
        e.post_window_end
    from event_windows e
    inner join daily_by_country d
            on d.country_category = e.country_category
           and d.seller_name_new = e.seller_name_new
           and d.seller_sku_adj = e.seller_sku_adj
           and d.dt_date between e.pre_window_start and e.post_window_end
),
aggregated as (
    select
        cw.snapshot_date,
        cw.return_event_id,
        cw.item_key,
        cw.seller_name_new,
        cw.country_category,
        cw.seller_sku_adj,
        cw.country,
        cw.metric_window_days,
        cw.pre_window_start,
        cw.pre_window_end,
        cw.post_window_start,
        cw.post_window_end,
        group_concat(distinct d.local_sku_list order by d.local_sku_list separator ', ') as local_sku_list,
        sum(case when d.dt_date between cw.pre_window_start and cw.pre_window_end then d.sales_qty else 0 end) as pre_sales_qty,
        sum(case when d.dt_date between cw.pre_window_start and cw.pre_window_end then d.sales_amount else 0 end) as pre_sales_amount,
        sum(case when d.dt_date between cw.pre_window_start and cw.pre_window_end then d.order_gross_profit else 0 end) as pre_order_gross_profit,
        sum(case when d.dt_date between cw.post_window_start and cw.post_window_end then d.sales_qty else 0 end) as post_sales_qty,
        sum(case when d.dt_date between cw.post_window_start and cw.post_window_end then d.sales_amount else 0 end) as post_sales_amount,
        sum(case when d.dt_date between cw.post_window_start and cw.post_window_end then d.order_gross_profit else 0 end) as post_order_gross_profit,
        sum(case when d.dt_date between cw.post_window_start and cw.post_window_end then d.sessions_total else 0 end) as sessions_total,
        sum(case when d.dt_date between cw.post_window_start and cw.post_window_end then d.ad_spend else 0 end) as ad_spend,
        sum(case when d.dt_date between cw.post_window_start and cw.post_window_end then d.ad_orders else 0 end) as ad_orders,
        sum(case when d.dt_date between cw.post_window_start and cw.post_window_end then d.ad_sales else 0 end) as ad_sales,
        sum(case when d.dt_date between cw.post_window_start and cw.post_window_end then d.ad_clicks else 0 end) as ad_clicks,
        sum(case when d.dt_date between cw.post_window_start and cw.post_window_end then d.ad_impressions else 0 end) as ad_impressions
    from country_windows cw
    left join daily_by_country d
           on d.country_category = cw.country_category
          and d.seller_name_new = cw.seller_name_new
          and d.seller_sku_adj = cw.seller_sku_adj
          and d.country = cw.country
          and d.dt_date between cw.pre_window_start and cw.post_window_end
    group by
        cw.snapshot_date, cw.return_event_id, cw.item_key, cw.seller_name_new,
        cw.country_category, cw.seller_sku_adj, cw.country, cw.metric_window_days,
        cw.pre_window_start, cw.pre_window_end, cw.post_window_start, cw.post_window_end
)
select
    snapshot_date,
    return_event_id,
    item_key,
    seller_name_new,
    country_category,
    seller_sku_adj,
    country,
    local_sku_list,
    metric_window_days,
    pre_window_start,
    pre_window_end,
    post_window_start,
    post_window_end,
    coalesce(pre_sales_qty, 0) as pre_sales_qty,
    coalesce(pre_sales_amount, 0) as pre_sales_amount,
    coalesce(pre_order_gross_profit, 0) as pre_order_gross_profit,
    coalesce(post_sales_qty, 0) as post_sales_qty,
    coalesce(post_sales_amount, 0) as post_sales_amount,
    coalesce(post_order_gross_profit, 0) as post_order_gross_profit,
    case when post_sales_amount > 0 then post_order_gross_profit / post_sales_amount else null end as post_order_gross_margin,
    case when pre_sales_qty > 0 then post_sales_qty / pre_sales_qty else null end as sales_recovery_rate,
    case when pre_sales_amount > 0 then post_sales_amount / pre_sales_amount else null end as sales_amount_recovery_rate,
    coalesce(sessions_total, 0) as sessions_total,
    case when sessions_total > 0 then post_sales_qty / sessions_total else null end as conversion_rate,
    coalesce(ad_spend, 0) as ad_spend,
    coalesce(ad_orders, 0) as ad_orders,
    coalesce(ad_sales, 0) as ad_sales,
    coalesce(ad_clicks, 0) as ad_clicks,
    coalesce(ad_impressions, 0) as ad_impressions,
    case when ad_sales > 0 then ad_spend / ad_sales else null end as acos,
    case when ad_impressions > 0 then ad_clicks / ad_impressions else null end as ctr
from aggregated;
"""

INSERT_RETURN_EVENT_SQL = """
insert into etl_datasync.dashboard_return_goods_events (
    snapshot_date, return_event_id, item_key, seller_name_new, country_category,
    seller_sku_adj, local_sku, return_round, stockout_date, return_start_date,
    exit_date, exit_reason, return_days, stage, pre_7d_sales_qty, pre_7d_sales_avg, pre_7d_gross_margin_rate,
    pre_stockout_sales_role, observe_7d_sales_qty, observe_7d_sales_avg, post_7d_sales_qty, post_7d_sales_avg, post_21d_available_sales_qty,
    recovery_window_days, pre_recovery_sales_qty, post_recovery_sales_qty, post_return_sales_qty,
    sales_recovery_rate, pre_21d_sales_qty, post_first_21d_sales_qty, d21_recovery_rate,
    recovery_followup_flag, post_cumulative_sales_qty, cumulative_avg_recovery_rate,
    recovery_followup_status, stable_recovery_start_date, current_stable_recovery_flag,
    recovery_fallback_flag, days_to_standard,
    current_fba_sellable, current_fba_inbound, warning_type
) values (
    %(snapshot_date)s, %(return_event_id)s, %(item_key)s, %(seller_name_new)s, %(country_category)s,
    %(seller_sku_adj)s, %(local_sku)s, %(return_round)s, %(stockout_date)s, %(return_start_date)s,
    %(exit_date)s, %(exit_reason)s, %(return_days)s, %(stage)s, %(pre_7d_sales_qty)s, %(pre_7d_sales_avg)s, %(pre_7d_gross_margin_rate)s,
    %(pre_stockout_sales_role)s, %(observe_7d_sales_qty)s, %(observe_7d_sales_avg)s, %(post_7d_sales_qty)s, %(post_7d_sales_avg)s, %(post_21d_available_sales_qty)s,
    %(recovery_window_days)s, %(pre_recovery_sales_qty)s, %(post_recovery_sales_qty)s, %(post_return_sales_qty)s,
    %(sales_recovery_rate)s, %(pre_21d_sales_qty)s, %(post_first_21d_sales_qty)s, %(d21_recovery_rate)s,
    %(recovery_followup_flag)s, %(post_cumulative_sales_qty)s, %(cumulative_avg_recovery_rate)s,
    %(recovery_followup_status)s, %(stable_recovery_start_date)s, %(current_stable_recovery_flag)s,
    %(recovery_fallback_flag)s, %(days_to_standard)s,
    %(current_fba_sellable)s, %(current_fba_inbound)s, %(warning_type)s
);
"""


def to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def avg_sales(rows: list[dict[str, Any]], start_day: date, end_day: date) -> Decimal | None:
    period_rows = [row for row in rows if start_day <= row["dt_date"] <= end_day]
    salable_days = sum(1 for row in period_rows if to_decimal(row.get("afn_fulfillable_quantity")) > 0)
    if salable_days == 0:
        return None
    return sum((to_decimal(row.get("sales_qty")) for row in period_rows), Decimal("0")) / Decimal(salable_days)


def salable_sales_qty(rows: list[dict[str, Any]], start_day: date, end_day: date) -> Decimal:
    return sum(
        (
            to_decimal(row.get("sales_qty"))
            for row in rows
            if start_day <= row["dt_date"] <= end_day and to_decimal(row.get("afn_fulfillable_quantity")) > 0
        ),
        Decimal("0"),
    )


def sales_qty(rows: list[dict[str, Any]], start_day: date, end_day: date) -> Decimal:
    return sum(
        (to_decimal(row.get("sales_qty")) for row in rows if start_day <= row["dt_date"] <= end_day),
        Decimal("0"),
    )


def recovery_rate(pre_qty: Decimal | None, post_qty: Decimal | None) -> Decimal | None:
    if pre_qty is None or post_qty is None or pre_qty == 0:
        return None
    return post_qty / pre_qty


def cumulative_average_recovery_rate(
    pre_21d_sales_qty: Decimal | None,
    post_cumulative_sales_qty: Decimal | None,
    elapsed_days: int,
) -> Decimal | None:
    if pre_21d_sales_qty is None or pre_21d_sales_qty == 0 or elapsed_days <= 0:
        return None
    baseline_daily_sales = pre_21d_sales_qty / Decimal(MONITOR_DAYS)
    return (to_decimal(post_cumulative_sales_qty) / Decimal(elapsed_days)) / baseline_daily_sales


def sales_by_day(rows: list[dict[str, Any]], start_day: date, end_day: date) -> dict[date, Decimal]:
    result: dict[date, Decimal] = {}
    for row in rows:
        row_day = row["dt_date"]
        if start_day <= row_day <= end_day:
            result[row_day] = result.get(row_day, Decimal("0")) + to_decimal(row.get("sales_qty"))
    return result


def stable_recovery_state(
    rows: list[dict[str, Any]],
    return_start_date: date,
    effective_date: date,
    pre_21d_sales_qty: Decimal | None,
) -> tuple[date | None, bool, bool]:
    followup_start = return_start_date + timedelta(days=MONITOR_DAYS)
    if pre_21d_sales_qty is None or pre_21d_sales_qty == 0 or effective_date < followup_start + timedelta(days=2):
        return None, False, False
    threshold = (pre_21d_sales_qty / Decimal(MONITOR_DAYS)) * Decimal("0.5")
    daily_sales = sales_by_day(rows, followup_start, effective_date)
    stable_start = None
    streak = 0
    cursor_day = followup_start
    while cursor_day <= effective_date:
        if daily_sales.get(cursor_day, Decimal("0")) >= threshold:
            streak += 1
            if streak == 3 and stable_start is None:
                stable_start = cursor_day - timedelta(days=2)
        else:
            streak = 0
        cursor_day += timedelta(days=1)
    current_stable = all(
        daily_sales.get(effective_date - timedelta(days=offset), Decimal("0")) >= threshold
        for offset in range(3)
    )
    return stable_start, current_stable, stable_start is not None and not current_stable


def gross_margin_rate(rows: list[dict[str, Any]], start_day: date, end_day: date) -> Decimal | None:
    period_rows = [row for row in rows if start_day <= row["dt_date"] <= end_day]
    sales_amount = sum((to_decimal(row.get("sales_amount")) for row in period_rows), Decimal("0"))
    if sales_amount == 0:
        return None
    gross_profit = sum((to_decimal(row.get("order_gross_profit")) for row in period_rows), Decimal("0"))
    return gross_profit / sales_amount


def sales_role(daily_sales: Decimal | None, margin_rate: Decimal | None) -> str:
    if daily_sales is None or daily_sales == 0 or margin_rate is None:
        return "问题产品"
    if daily_sales > Decimal("5"):
        if margin_rate > Decimal("0.15"):
            return "明星产品"
        if margin_rate >= Decimal("0.05"):
            return "潜力产品"
        return "问题产品"
    if daily_sales >= Decimal("1"):
        if margin_rate > Decimal("0.25"):
            return "明星产品"
        if margin_rate >= Decimal("0.10"):
            return "潜力产品"
        if margin_rate >= Decimal("0.05"):
            return "瘦狗产品"
        return "问题产品"
    if margin_rate >= Decimal("0.05"):
        return "瘦狗产品"
    return "问题产品"


def make_event_id(item_key: str, return_start_date: date, stockout_date: date, return_round: int) -> str:
    raw = f"{item_key}|{return_start_date.isoformat()}|{stockout_date.isoformat()}|{return_round}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def stage_for(return_days: int, exit_reason: str | None) -> str:
    if exit_reason:
        return "已退出"
    if return_days <= 7:
        return "观察期"
    if return_days <= MONITOR_DAYS:
        return "运营干预期"
    return "持续干预期"


def warning_for(stage: str, exit_reason: str | None, rate: Decimal | None) -> str | None:
    if exit_reason == "二次断货":
        return "二次断货"
    if stage == "持续干预期":
        if rate is None:
            return "持续干预数据不足"
        if rate < Decimal("0.5"):
            return "持续干预严重低恢复"
        return "持续干预恢复不足"
    if stage != "运营干预期" or rate is None:
        return None
    if rate < Decimal("0.5"):
        return "干预期严重低恢复"
    if rate < Decimal("0.7"):
        return "干预期未恢复"
    return None


def build_events(
    rows: list[dict[str, Any]],
    snapshot_date: date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    pending_stockout_index: int | None = None
    return_round = 0

    for index, row in enumerate(rows):
        fba = to_decimal(row.get("afn_fulfillable_quantity"))
        if fba == 0 and pending_stockout_index is None:
            pending_stockout_index = index
            continue
        if pending_stockout_index is not None and fba > RETURN_STOCK_THRESHOLD:
            return_round += 1
            stockout_row = rows[pending_stockout_index]
            events.append(
                {
                    "return_round": return_round,
                    "stockout_date": stockout_row["dt_date"],
                    "return_start_date": row["dt_date"],
                }
            )
            pending_stockout_index = None

    if not rows:
        return []
    latest_row = rows[-1]
    result = []
    # The inclusive 180-day window starts 179 days before the snapshot date.
    min_return_start = snapshot_date - timedelta(days=lookback_days - 1)
    for event in events:
        start_day = event["return_start_date"]
        if start_day < min_return_start:
            continue
        actual_return_days = max(1, (snapshot_date - start_day).days + 1)
        recovery_window_days = min(actual_return_days, MONITOR_DAYS)
        pre_window_start = event["stockout_date"] - timedelta(days=7)
        pre_window_end = event["stockout_date"] - timedelta(days=1)
        pre_recovery_window_start = event["stockout_date"] - timedelta(days=recovery_window_days)
        pre_recovery_window_end = event["stockout_date"] - timedelta(days=1)
        post_recovery_window_end = min(start_day + timedelta(days=recovery_window_days - 1), snapshot_date)
        pre_21d_qty = sales_qty(
            rows,
            event["stockout_date"] - timedelta(days=MONITOR_DAYS),
            event["stockout_date"] - timedelta(days=1),
        )
        post_first_21d_qty = sales_qty(
            rows,
            start_day,
            min(start_day + timedelta(days=MONITOR_DAYS - 1), snapshot_date),
        )
        d21_rate = recovery_rate(pre_21d_qty, post_first_21d_qty) if actual_return_days >= MONITOR_DAYS else None
        followup_flag = actual_return_days > MONITOR_DAYS and (d21_rate is None or d21_rate < Decimal("0.7"))
        exit_day = None
        if actual_return_days > MONITOR_DAYS and d21_rate is not None and d21_rate >= Decimal("0.7"):
            exit_day = start_day + timedelta(days=MONITOR_DAYS)
        elif followup_flag and pre_21d_qty > 0:
            candidate_day = start_day + timedelta(days=MONITOR_DAYS)
            while candidate_day <= snapshot_date:
                elapsed_days = (candidate_day - start_day).days + 1
                candidate_qty = sales_qty(rows, start_day, candidate_day)
                candidate_rate = cumulative_average_recovery_rate(pre_21d_qty, candidate_qty, elapsed_days)
                if candidate_rate is not None and candidate_rate >= Decimal("0.7"):
                    exit_day = candidate_day
                    break
                candidate_day += timedelta(days=1)

        exit_reason = "达标退出" if exit_day else None
        effective_day = min(exit_day or snapshot_date, snapshot_date)
        return_days = max(1, (effective_day - start_day).days + 1)
        metric_end_day = effective_day
        observe_window_end = min(start_day + timedelta(days=6), metric_end_day)
        post_window_start = max(start_day, metric_end_day - timedelta(days=6))
        pre_avg = avg_sales(rows, pre_window_start, pre_window_end)
        pre_qty = sales_qty(rows, pre_window_start, pre_window_end)
        pre_margin = gross_margin_rate(rows, pre_window_start, pre_window_end)
        pre_recovery_qty = pre_21d_qty if actual_return_days > MONITOR_DAYS else sales_qty(
            rows, pre_recovery_window_start, pre_recovery_window_end
        )
        observe_avg = avg_sales(rows, start_day, observe_window_end)
        observe_qty = sales_qty(rows, start_day, observe_window_end)
        post_avg = avg_sales(rows, post_window_start, metric_end_day)
        post_qty = sales_qty(rows, post_window_start, metric_end_day)
        post_cumulative_qty = sales_qty(rows, start_day, metric_end_day) if followup_flag else None
        cumulative_rate = cumulative_average_recovery_rate(pre_21d_qty, post_cumulative_qty, return_days) if followup_flag else None
        post_recovery_qty = sales_qty(rows, start_day, post_recovery_window_end)
        post_return_sales_qty = sales_qty(rows, start_day, snapshot_date)
        post_21d_sales_qty = salable_sales_qty(rows, start_day, min(start_day + timedelta(days=20), snapshot_date))
        rate = cumulative_rate if followup_flag else recovery_rate(pre_recovery_qty, post_recovery_qty)
        stable_start, current_stable, recovery_fallback = (
            stable_recovery_state(rows, start_day, metric_end_day, pre_21d_qty)
            if followup_flag
            else (None, False, False)
        )
        followup_status = None
        if followup_flag:
            if exit_day:
                followup_status = "21天后恢复达标"
            elif cumulative_rate is None:
                followup_status = "数据不足持续关注"
            elif cumulative_rate < Decimal("0.5"):
                followup_status = "截至目前严重恢复不足"
            else:
                followup_status = "恢复提升中"
        stage = stage_for(return_days, exit_reason)

        result.append(
            {
                "return_event_id": make_event_id(
                    latest_row["item_key"], start_day, event["stockout_date"], event["return_round"]
                ),
                "item_key": latest_row["item_key"],
                "seller_name_new": latest_row["seller_name_new"],
                "country_category": latest_row["country_category"],
                "seller_sku_adj": latest_row["seller_sku_adj"],
                "local_sku": latest_row.get("local_sku"),
                "return_round": event["return_round"],
                "stockout_date": event["stockout_date"],
                "return_start_date": start_day,
                "exit_date": exit_day,
                "exit_reason": exit_reason,
                "return_days": return_days,
                "stage": stage,
                "pre_7d_sales_qty": pre_qty,
                "pre_7d_sales_avg": pre_avg,
                "pre_7d_gross_margin_rate": pre_margin,
                "pre_stockout_sales_role": sales_role(pre_avg, pre_margin),
                "observe_7d_sales_qty": observe_qty,
                "observe_7d_sales_avg": observe_avg,
                "post_7d_sales_qty": post_qty,
                "post_7d_sales_avg": post_avg,
                "post_21d_available_sales_qty": post_21d_sales_qty,
                "recovery_window_days": recovery_window_days,
                "pre_recovery_sales_qty": pre_recovery_qty,
                "post_recovery_sales_qty": post_recovery_qty,
                "post_return_sales_qty": post_return_sales_qty,
                "sales_recovery_rate": rate,
                "pre_21d_sales_qty": pre_21d_qty if actual_return_days >= MONITOR_DAYS else None,
                "post_first_21d_sales_qty": post_first_21d_qty if actual_return_days >= MONITOR_DAYS else None,
                "d21_recovery_rate": d21_rate,
                "recovery_followup_flag": followup_flag,
                "post_cumulative_sales_qty": post_cumulative_qty,
                "cumulative_avg_recovery_rate": cumulative_rate,
                "recovery_followup_status": followup_status,
                "stable_recovery_start_date": stable_start,
                "current_stable_recovery_flag": current_stable,
                "recovery_fallback_flag": recovery_fallback,
                "days_to_standard": return_days if exit_day else None,
                "current_fba_sellable": to_decimal(latest_row.get("afn_fulfillable_quantity")),
                "current_fba_inbound": to_decimal(latest_row.get("fba_inbound_quantity")),
                "warning_type": warning_for(stage, exit_reason, rate),
            }
        )
    return result


def connect_stream_target():
    return pymysql.connect(
        host=os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", "127.0.0.1")),
        port=int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", "3306"))),
        user=os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", "")),
        password=os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
        database=os.getenv("DASHBOARD_DB_NAME", os.getenv("MYSQL_DATABASE", "etl_datasync_test")) or None,
        charset=os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4"),
        cursorclass=pymysql.cursors.SSDictCursor,
        autocommit=True,
        read_timeout=3600,
        write_timeout=3600,
    )


def iter_grouped_rows(conn, schemas, snapshot_date: date, lookback_days: int) -> Iterable[list[dict[str, Any]]]:
    source_start_date = source_history_start_date(snapshot_date, lookback_days)
    with conn.cursor() as cursor:
        cursor.execute(
            render_sql(SELECT_PRODUCT_DAILY_SQL, schemas),
            {"source_start_date": source_start_date, "snapshot_date": snapshot_date},
        )
        current_key = None
        group: list[dict[str, Any]] = []
        for row in cursor:
            key = row["item_key"]
            if current_key is not None and key != current_key:
                yield group
                group = []
            current_key = key
            group.append(row)
        if group:
            yield group


def flush_events(cursor, schemas, snapshot_date: date, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    cursor.executemany(render_sql(INSERT_RETURN_EVENT_SQL, schemas), [{**row, "snapshot_date": snapshot_date} for row in rows])
    return len(rows)


def ensure_return_events_schema(cursor, schemas) -> None:
    cursor.execute(render_sql(CREATE_RETURN_EVENTS_SQL, schemas))
    cursor.execute(render_sql(CREATE_STOCKOUT_POOL_SQL, schemas))
    cursor.execute(render_sql(CREATE_STAGE_DAILY_SUMMARY_SQL, schemas))
    cursor.execute(render_sql(CREATE_COUNTRY_METRICS_SQL, schemas))
    migrations = [
        ("current_fba_inbound", "add column current_fba_inbound decimal(18,4) null after current_fba_sellable"),
        ("pre_7d_sales_qty", "add column pre_7d_sales_qty decimal(18,4) null after stage"),
        ("pre_7d_gross_margin_rate", "add column pre_7d_gross_margin_rate decimal(18,4) null after pre_7d_sales_avg"),
        ("pre_stockout_sales_role", "add column pre_stockout_sales_role varchar(32) null after pre_7d_gross_margin_rate"),
        ("observe_7d_sales_qty", "add column observe_7d_sales_qty decimal(18,4) null after pre_stockout_sales_role"),
        ("observe_7d_sales_avg", "add column observe_7d_sales_avg decimal(18,4) null after pre_stockout_sales_role"),
        ("post_7d_sales_qty", "add column post_7d_sales_qty decimal(18,4) null after observe_7d_sales_avg"),
        ("post_21d_available_sales_qty", "add column post_21d_available_sales_qty decimal(18,4) null after post_7d_sales_avg"),
        ("recovery_window_days", "add column recovery_window_days int null after post_21d_available_sales_qty"),
        ("pre_recovery_sales_qty", "add column pre_recovery_sales_qty decimal(18,4) null after recovery_window_days"),
        ("post_recovery_sales_qty", "add column post_recovery_sales_qty decimal(18,4) null after pre_recovery_sales_qty"),
        ("post_return_sales_qty", "add column post_return_sales_qty decimal(18,4) null after post_recovery_sales_qty"),
        ("pre_21d_sales_qty", "add column pre_21d_sales_qty decimal(18,4) null after sales_recovery_rate"),
        ("post_first_21d_sales_qty", "add column post_first_21d_sales_qty decimal(18,4) null after pre_21d_sales_qty"),
        ("d21_recovery_rate", "add column d21_recovery_rate decimal(18,6) null after post_first_21d_sales_qty"),
        ("recovery_followup_flag", "add column recovery_followup_flag tinyint not null default 0 after d21_recovery_rate"),
        ("post_cumulative_sales_qty", "add column post_cumulative_sales_qty decimal(18,4) null after recovery_followup_flag"),
        ("cumulative_avg_recovery_rate", "add column cumulative_avg_recovery_rate decimal(18,6) null after post_cumulative_sales_qty"),
        ("recovery_followup_status", "add column recovery_followup_status varchar(32) null after cumulative_avg_recovery_rate"),
        ("stable_recovery_start_date", "add column stable_recovery_start_date date null after recovery_followup_status"),
        ("current_stable_recovery_flag", "add column current_stable_recovery_flag tinyint not null default 0 after stable_recovery_start_date"),
        ("recovery_fallback_flag", "add column recovery_fallback_flag tinyint not null default 0 after current_stable_recovery_flag"),
        ("days_to_standard", "add column days_to_standard int null after recovery_fallback_flag"),
    ]
    for column_name, alter_sql in migrations:
        cursor.execute(
            render_sql(f"show columns from etl_datasync.dashboard_return_goods_events like '{column_name}'", schemas)
        )
        if not cursor.fetchone():
            cursor.execute(render_sql(f"alter table etl_datasync.dashboard_return_goods_events {alter_sql}", schemas))


def rebuild_stockout_pool(cursor, schemas, snapshot_date: date, lookback_days: int) -> int:
    source_start_date = snapshot_date - timedelta(days=lookback_days - 1)
    cursor.execute(render_sql(DELETE_STOCKOUT_POOL_SQL, schemas), {"snapshot_date": snapshot_date})
    cursor.execute(
        render_sql(INSERT_STOCKOUT_POOL_SQL, schemas),
        {"snapshot_date": snapshot_date, "source_start_date": source_start_date},
    )
    return cursor.rowcount


def rebuild_stage_daily_summary(cursor, schemas, snapshot_date: date, lookback_days: int) -> int:
    source_start_date = snapshot_date - timedelta(days=lookback_days - 1)
    cursor.execute(render_sql(DELETE_STAGE_DAILY_SUMMARY_SQL, schemas), {"snapshot_date": snapshot_date})
    cursor.execute(
        render_sql(INSERT_STAGE_DAILY_SUMMARY_SQL, schemas),
        {"snapshot_date": snapshot_date, "source_start_date": source_start_date},
    )
    return cursor.rowcount


def rebuild_country_metrics(cursor, schemas, snapshot_date: date, lookback_days: int) -> int:
    source_start_date = snapshot_date - timedelta(days=lookback_days + MONITOR_DAYS - 1)
    cursor.execute(render_sql(DELETE_COUNTRY_METRICS_SQL, schemas), {"snapshot_date": snapshot_date})
    cursor.execute(
        render_sql(INSERT_COUNTRY_METRICS_SQL, schemas),
        {"snapshot_date": snapshot_date, "source_start_date": source_start_date},
    )
    return cursor.rowcount


def rebuild_return_events(snapshot_date: date, lookback_days: int = DEFAULT_LOOKBACK_DAYS, batch_size: int = 1000) -> int:
    schemas = build_schema_config()
    with connect_target() as target_conn:
        with target_conn.cursor() as cursor:
            ensure_return_events_schema(cursor, schemas)
            cursor.execute(render_sql(DELETE_RETURN_EVENTS_SQL, schemas), {"snapshot_date": snapshot_date})
            rebuild_stockout_pool(cursor, schemas, snapshot_date, lookback_days)
        target_conn.commit()

    affected = 0
    batch: list[dict[str, Any]] = []
    with connect_stream_target() as source_conn, connect_target() as target_conn:
        with target_conn.cursor() as cursor:
            for group in iter_grouped_rows(source_conn, schemas, snapshot_date, lookback_days):
                batch.extend(build_events(group, snapshot_date, lookback_days))
                if len(batch) >= batch_size:
                    affected += flush_events(cursor, schemas, snapshot_date, batch)
                    target_conn.commit()
                    batch.clear()
            affected += flush_events(cursor, schemas, snapshot_date, batch)
            rebuild_country_metrics(cursor, schemas, snapshot_date, lookback_days)
            rebuild_stage_daily_summary(cursor, schemas, snapshot_date, lookback_days)
            target_conn.commit()
    return affected


def latest_product_date() -> date:
    schemas = build_schema_config()
    with connect_target() as conn:
        with conn.cursor() as cursor:
            cursor.execute(render_sql("select max(dt_date) as dt_date from etl_datasync.dashboard_product_performance_daily", schemas))
            row = cursor.fetchone() or {}
    if not row.get("dt_date"):
        raise SystemExit("dashboard_product_performance_daily has no data")
    return row["dt_date"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build return-goods event table.")
    parser.add_argument("--snapshot-date", help="Snapshot date, format YYYY-MM-DD. Default: latest product date.")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.lookback_days < MONITOR_DAYS:
        raise SystemExit("lookback-days must be at least 21")
    apply_database_ini_env()
    snapshot_date = parse_day(args.snapshot_date) if args.snapshot_date else latest_product_date()
    if not snapshot_date:
        raise SystemExit("invalid snapshot-date")

    print(f"Return goods ETL: snapshot_date={snapshot_date}, lookback_days={args.lookback_days}")
    if args.dry_run:
        return
    affected = rebuild_return_events(snapshot_date, args.lookback_days, args.batch_size)
    print(f"[success] dashboard_return_goods_events rows={affected}")


if __name__ == "__main__":
    main()
