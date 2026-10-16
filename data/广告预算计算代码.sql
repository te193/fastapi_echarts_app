# create table if not exists dws_datasync.dws_ad_budget_pool_daily_history (
#     biz_date date not null comment '执行日期',
#     country_category varchar(32) not null comment '国家类别',
#     seller_name_new varchar(64) not null comment '店铺',
#     seller_sku_adj varchar(100) not null comment 'msku',
#     available_total decimal(20,4) null comment 'fba可用库存',
#     stock_up_num decimal(20,4) null comment '备货库存',
#     local_quantity decimal(20,4) null comment '本地库存',
#     total_budget_inventory decimal(20,4) null comment '当日预算库存',
#     previous_month_max_inventory_qty decimal(20,4) null comment '变动前月最大库存',
#     month_max_inventory_qty decimal(20,4) null comment '变动后月最大库存',
#     inventory_growth_qty decimal(20,4) not null default 0 comment '新增库存',
#     total_weighted_daily_sales decimal(20,6) not null default 0 comment '国家类别加权日销',
#     previous_total_budget_pool_cny decimal(20,2) null comment '变动前总预算',
#     budget_change_cny decimal(20,2) null comment '总预算变动额',
#     budget_increment_cny decimal(20,2) not null default 0 comment '新增总预算',
#     budget_per_inventory_cny decimal(20,6) null comment '单位新增库存预算',
#     total_budget_pool_cny decimal(20,2) null comment '变动后总预算',
#     monthly_budget_cny decimal(20,2) not null default 0 comment '月预算合计',
#     weekly_budget_cny decimal(20,2) not null default 0 comment '周预算合计',
#     change_type varchar(16) not null comment '变动类型',
#     created_at datetime not null default current_timestamp comment '创建时间',
#     updated_at datetime not null default current_timestamp
#         on update current_timestamp comment '更新时间',
#     primary key (
#         biz_date,
#         country_category,
#         seller_name_new,
#         seller_sku_adj
#     ),
#     index idx_ad_budget_pool_history_msku (
#         seller_sku_adj,
#         biz_date
#     ),
#     index idx_ad_budget_pool_history_store (
#         country_category,
#         seller_name_new,
#         biz_date
#     )
# ) engine=innodb
# default charset=utf8mb4
# comment='广告总预算每日快照';

drop procedure if exists dws_datasync.sp_dws_monthly_ad_budget_calculate;
delimiter $$
create procedure dws_datasync.sp_dws_monthly_ad_budget_calculate()
begin
set @run_date = current_date();
set @biz_date = (
    select date(max(start_date))
    from dwd_datasync.lx_statistics_product_performance
);
set @product_start_date = date_sub(@biz_date, interval 29 day);
set @product_end_date = date_add(@biz_date, interval 1 day);
set @listing_date = (
    select date(max(create_time))
    from dwd_datasync.lx_sales_mws_listing
);
set @listing_end_date = date_add(@listing_date, interval 1 day);
set @inventory_date = (
    select date(max(create_time))
    from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
);
set @inventory_end_date = date_add(@inventory_date, interval 1 day);
set @restock_date = (
    select date(max(create_time))
    from etl_datasync.etl_dispose_lx_replenishment_suggest_restocking
);
set @restock_end_date = date_add(@restock_date, interval 1 day);
set @previous_budget_date = (
    select max(biz_date)
    from dws_datasync.dws_monthly_ad_budget_detail
);

/* 第一层：会话临时表只扫描最近 30 天，先按日去重，再落国家周期指标。 */
drop temporary table if exists dws_datasync.tmp_replenishment_weighted_sales_product_30d;
create temporary table dws_datasync.tmp_replenishment_weighted_sales_product_30d
engine=InnoDB
default charset=utf8mb4
as
select
    d.country_category,
    d.country,
    d.seller_name_new,
    d.seller_sku_adj,
    sum(case when d.dt_date >= date_sub(@biz_date, interval 2 day)
             then d.sales_qty else 0 end) as sales_3,
    sum(case when d.dt_date >= date_sub(@biz_date, interval 6 day)
             then d.sales_qty else 0 end) as sales_7,
    sum(case when d.dt_date >= date_sub(@biz_date, interval 13 day)
             then d.sales_qty else 0 end) as sales_14,
    sum(d.sales_qty) as sales_30,
    sum(case when d.dt_date >= date_sub(@biz_date, interval 2 day)
              and d.afn_fulfillable_quantity > 0 then 1 else 0 end)
        as r_3d_salable_days,
    sum(case when d.dt_date >= date_sub(@biz_date, interval 6 day)
              and d.afn_fulfillable_quantity > 0 then 1 else 0 end)
        as r_7d_salable_days,
    sum(case when d.dt_date >= date_sub(@biz_date, interval 13 day)
              and d.afn_fulfillable_quantity > 0 then 1 else 0 end)
        as r_14d_salable_days,
    sum(case when d.afn_fulfillable_quantity > 0 then 1 else 0 end)
        as r_30d_salable_days
from (
    select
        date(p.start_date) as dt_date,
        cast(
            case
                when p.country = '英国' then '英国站'
                when p.country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
                else '欧洲站'
            end as char(16)
        ) as country_category,
        cast(p.country as char(32)) as country,
        cast(
            case
                when locate('-', p.seller_name) > 0
                    then left(p.seller_name, locate('-', p.seller_name) - 1)
                else p.seller_name
            end as char(64)
        ) as seller_name_new,
        cast(
            if(
                length(substring_index(p.seller_sku, ',', 1)) > 16,
                trim(
                    leading 'amzn.gr.' from
                    substring_index(substring_index(p.seller_sku, ',', 1), '-', 1)
                ),
                substring_index(p.seller_sku, ',', 1)
            ) as char(100)
        ) as seller_sku_adj,
        sum(coalesce(p.volume, 0)) as sales_qty,
        max(coalesce(p.afn_fulfillable_quantity, 0)) as afn_fulfillable_quantity
    from dwd_datasync.lx_statistics_product_performance as p
    force index (idx_osp_performance_dashboard_cover)
    where p.start_date >= date_format(@product_start_date, '%Y-%m-%d')
      and p.start_date < date_format(@product_end_date, '%Y-%m-%d')
      and p.seller_sku not like 'Amazon.Found%'
      and p.seller_sku is not null
      and p.seller_sku <> ''
      and p.country in ('德国', '法国', '意大利', '西班牙', '荷兰', '美国', '英国')
    group by
        dt_date,
        country_category,
        country,
        seller_name_new,
        seller_sku_adj
) as d
group by
    d.country_category,
    d.country,
    d.seller_name_new,
    d.seller_sku_adj;

/* 第二层：会话临时表只扫描最新同步日，再在当天取每个业务键的最新有效售价。 */
drop temporary table if exists dws_datasync.tmp_replenishment_listing_price_latest;
create temporary table dws_datasync.tmp_replenishment_listing_price_latest
engine=InnoDB
default charset=utf8mb4
as
with listing_source as (
    select
        cast(
            case
                when l.marketplace = '英国' then '英国站'
                when l.marketplace in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
                else '欧洲站'
            end as char(16)
        ) as country_category,
        cast(l.marketplace as char(32)) as country,
        cast(
            case
                when locate('-', l.seller_name) > 0
                    then left(l.seller_name, locate('-', l.seller_name) - 1)
                else l.seller_name
            end as char(64)
        ) as seller_name_new,
        cast(l.seller_sku as char(100)) as seller_sku_adj,
        cast(nullif(l.landed_price, '') as decimal(18,4)) as listing_price,
        cast(nullif(upper(trim(l.currency_code)), '') as char(10)) as currency_code,
        l.create_time,
        cast(
            case nullif(upper(trim(l.currency_code)), '')
                when 'EUR' then '欧元'
                when 'PLN' then '波兰兹罗提'
                when 'SEK' then '瑞典'
                when 'TRY' then '土耳其里拉'
                when 'GBP' then '英镑'
                when 'USD' then '美元'
                when 'CAD' then '加元'
                when 'MXN' then '墨西哥比索'
                when 'BRL' then '巴西雷亚尔'
                else null
            end as char(32)
        ) as currency_name
    from dwd_datasync.lx_sales_mws_listing as l
    where l.create_time >= @listing_date
      and l.create_time < @listing_end_date
      and nullif(trim(l.landed_price), '') is not null
      and cast(l.landed_price as decimal(18,4)) > 0
      and l.seller_sku is not null
      and l.seller_sku <> ''
),
listing_ranked as (
    select
        l.*,
        row_number() over (
            partition by
                l.country_category,
                l.country,
                l.seller_name_new,
                l.seller_sku_adj
            order by l.create_time desc, l.listing_price desc
        ) as price_rank
    from listing_source as l
)
select
    l.country_category,
    l.country,
    l.seller_name_new,
    l.seller_sku_adj,
    l.listing_price,
    l.currency_code,
    l.create_time as listing_create_time,
    cast(nullif(c.rate_org, '') as decimal(18,8)) as exchange_rate_cny,
    round(
        l.listing_price * cast(nullif(c.rate_org, '') as decimal(18,8)),
        2
    ) as listing_price_cny
from listing_ranked as l
left join dwd_datasync.lx_basic_currency as c
       on l.currency_name = c.name
      and date_format(l.create_time, '%Y-%m') = c.date
where l.price_rank = 1;

alter table dws_datasync.tmp_replenishment_listing_price_latest
    add primary key (
        country_category,
        country,
        seller_name_new,
        seller_sku_adj
    );

/* 第三层：汇总补货口径库存池，避免在国家站点结果中重复计算国家类别库存。 */
drop temporary table if exists dws_datasync.tmp_replenishment_budget_fba_latest;
create temporary table dws_datasync.tmp_replenishment_budget_fba_latest
engine=InnoDB
default charset=utf8mb4
as
select
    cast(f.country_category as char(16)) as country_category,
    cast(f.seller_name_new as char(64)) as seller_name_new,
    cast(f.seller_sku_adj as char(100)) as seller_sku_adj,
    sum(coalesce(f.available_total, 0)) as available_total,
    sum(coalesce(f.stock_up_num, 0)) as stock_up_num
from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail as f
where f.create_time >= @inventory_date
  and f.create_time < @inventory_end_date
  and f.seller_sku_adj is not null
  and f.seller_sku_adj <> ''
group by
    f.country_category,
    f.seller_name_new,
    f.seller_sku_adj;

alter table dws_datasync.tmp_replenishment_budget_fba_latest
    add primary key (
        country_category,
        seller_name_new,
        seller_sku_adj
    );

drop temporary table if exists dws_datasync.tmp_replenishment_budget_restock_latest;
create temporary table dws_datasync.tmp_replenishment_budget_restock_latest
engine=InnoDB
default charset=utf8mb4
as
select
    cast(r.country_category as char(16)) as country_category,
    cast(r.seller_name_new as char(64)) as seller_name_new,
    cast(r.seller_sku_adj as char(100)) as seller_sku_adj,
    max(coalesce(r.local_quantity, 0)) as local_quantity
from etl_datasync.etl_dispose_lx_replenishment_suggest_restocking as r
where r.create_time >= @restock_date
  and r.create_time < @restock_end_date
  and r.seller_sku_adj is not null
  and r.seller_sku_adj <> ''
group by
    r.country_category,
    r.seller_name_new,
    r.seller_sku_adj;

alter table dws_datasync.tmp_replenishment_budget_restock_latest
    add primary key (
        country_category,
        seller_name_new,
        seller_sku_adj
    );

drop temporary table if exists dws_datasync.tmp_replenishment_budget_inventory_latest;
create temporary table dws_datasync.tmp_replenishment_budget_inventory_latest
engine=InnoDB
default charset=utf8mb4
as
select
    p.country_category,
    p.seller_name_new,
    p.seller_sku_adj,
    cast(@inventory_date as date) as inventory_snapshot_date,
    cast(@restock_date as date) as restock_snapshot_date,
    coalesce(f.available_total, 0) as available_total,
    coalesce(f.stock_up_num, 0) as stock_up_num,
    coalesce(r.local_quantity, 0) as local_quantity,
    coalesce(f.available_total, 0)
        + coalesce(f.stock_up_num, 0)
        + coalesce(r.local_quantity, 0) as total_budget_inventory
from (
    select distinct
        country_category,
        seller_name_new,
        seller_sku_adj
    from dws_datasync.tmp_replenishment_weighted_sales_product_30d
    union
    select distinct
        country_category,
        seller_name_new,
        seller_sku_adj
    from dws_datasync.dws_monthly_ad_budget_detail
    where biz_date = @previous_budget_date
) as p
left join dws_datasync.tmp_replenishment_budget_fba_latest as f
       on p.country_category = f.country_category
      and p.seller_name_new = f.seller_name_new
      and binary p.seller_sku_adj = f.seller_sku_adj
left join dws_datasync.tmp_replenishment_budget_restock_latest as r
       on p.country_category = r.country_category
      and p.seller_name_new = r.seller_name_new
      and binary p.seller_sku_adj = r.seller_sku_adj;

alter table dws_datasync.tmp_replenishment_budget_inventory_latest
    add primary key (
        country_category,
        seller_name_new,
        seller_sku_adj
    );

drop temporary table dws_datasync.tmp_replenishment_budget_fba_latest;
drop temporary table dws_datasync.tmp_replenishment_budget_restock_latest;

/* 第四层：读取远端上一版预算状态，作为本次预算刷新基准。 */
drop temporary table if exists dws_datasync.tmp_replenishment_previous_budget_state;
set @previous_state_has_month_max = (
    select count(*)
    from information_schema.columns
    where table_schema = 'dws_datasync'
      and table_name = 'dws_monthly_ad_budget_detail'
      and column_name = 'month_max_inventory_qty'
);
set @previous_state_sql = if(
    @previous_state_has_month_max > 0,
    'create temporary table dws_datasync.tmp_replenishment_previous_budget_state engine=innodb default charset=utf8mb4 as select p.biz_date, p.country_category, p.country, p.seller_name_new, p.seller_sku_adj, p.month_max_inventory_qty, p.total_inventory_allocated_qty, p.site_total_budget_cny, p.total_budget_pool_cny, p.monthly_forecast_qty, p.monthly_allocated_qty, p.monthly_ad_budget_original, p.monthly_ad_budget_cny, p.weekly_forecast_qty, p.weekly_allocated_qty, p.weekly_ad_budget_original, p.weekly_ad_budget_cny from dws_datasync.dws_monthly_ad_budget_detail as p where p.biz_date = @previous_budget_date',
    'create temporary table dws_datasync.tmp_replenishment_previous_budget_state engine=innodb default charset=utf8mb4 as select p.biz_date, p.country_category, p.country, p.seller_name_new, p.seller_sku_adj, greatest(p.total_budget_inventory, 0) as month_max_inventory_qty, p.total_inventory_allocated_qty, p.site_total_budget_cny, p.total_budget_pool_cny, p.monthly_forecast_qty, p.monthly_allocated_qty, p.monthly_ad_budget_original, p.monthly_ad_budget_cny, p.weekly_forecast_qty, p.weekly_allocated_qty, p.weekly_ad_budget_original, p.weekly_ad_budget_cny from dws_datasync.dws_monthly_ad_budget_detail as p where p.biz_date = @previous_budget_date'
);
prepare previous_state_statement from @previous_state_sql;
execute previous_state_statement;
deallocate prepare previous_state_statement;

alter table dws_datasync.tmp_replenishment_previous_budget_state
    add index idx_previous_budget_site (
        country_category,
        country,
        seller_name_new,
        seller_sku_adj
    );

drop temporary table if exists dws_datasync.tmp_replenishment_previous_missing_site;
create temporary table dws_datasync.tmp_replenishment_previous_missing_site
engine=innodb
default charset=utf8mb4
as
select
    p.country_category,
    p.country,
    p.seller_name_new,
    p.seller_sku_adj
from dws_datasync.dws_monthly_ad_budget_detail as p
left join dws_datasync.tmp_replenishment_weighted_sales_product_30d as c
       on p.country_category = c.country_category
      and p.country = c.country
      and p.seller_name_new = c.seller_name_new
      and binary p.seller_sku_adj = c.seller_sku_adj
where p.biz_date = @previous_budget_date
  and c.seller_sku_adj is null;

/* 第五层：分模块刷新预算，新记录插入，已有记录按业务主键更新。 */
insert into dws_datasync.dws_monthly_ad_budget_detail (
    biz_date,
    country_category,
    country,
    seller_name_new,
    seller_sku_adj,
    max_brand_name,
    receiving_cnt,
    product_type,
    sales_3,
    r_3d_salable_days,
    sales_7,
    r_7d_salable_days,
    sales_14,
    r_14d_salable_days,
    sales_30,
    r_30d_salable_days,
    daily_avg_sales,
    listing_price,
    currency_code,
    exchange_rate_cny,
    listing_price_cny,
    available_total,
    stock_up_num,
    local_quantity,
    total_budget_inventory,
    month_max_inventory_qty,
    total_weighted_daily_sales,
    sales_share,
    total_inventory_allocated_qty,
    site_total_budget_cny,
    monthly_forecast_qty,
    monthly_allocated_qty,
    monthly_ad_budget_original,
    monthly_ad_budget_cny,
    weekly_forecast_qty,
    weekly_allocated_qty,
    weekly_ad_budget_original,
    weekly_ad_budget_cny,
    total_budget_pool_cny,
    inventory_sufficient_flag,
    weekly_inventory_sufficient_flag
)
with
period_metrics as (
    select
        p.country_category,
        p.country,
        p.seller_name_new,
        p.seller_sku_adj,
        p.sales_3,
        p.sales_7,
        p.sales_14,
        p.sales_30,
        p.r_3d_salable_days,
        p.r_7d_salable_days,
        p.r_14d_salable_days,
        p.r_30d_salable_days
    from dws_datasync.tmp_replenishment_weighted_sales_product_30d as p
    union all
    select
        p.country_category,
        p.country,
        p.seller_name_new,
        p.seller_sku_adj,
        0 as sales_3,
        0 as sales_7,
        0 as sales_14,
        0 as sales_30,
        0 as r_3d_salable_days,
        0 as r_7d_salable_days,
        0 as r_14d_salable_days,
        0 as r_30d_salable_days
    from dws_datasync.tmp_replenishment_previous_missing_site as p
),
product_brand as (
    select
        country_category,
        seller_name_new,
        seller_sku,
        max(brand_name) as max_brand_name
    from etl_datasync.etl_dispose_lx_product_local_product_info
    group by country_category, seller_name_new, seller_sku
),
shipment_receiving_count as (
    select
        msku,
        store_name,
        count(*) as receiving_cnt
    from etl_datasync.etl_dispose_lx_fba_shipment
    where receiving_time is not null
      and receiving_time <> ''
      and quantity_shipped <> 0
    group by msku, store_name
),
receiving_metrics as (
    select
        f.country_category,
        f.seller_name_new,
        f.msku,
        max(rc.receiving_cnt) as receiving_cnt
    from etl_datasync.etl_dispose_lx_fba_shipment as f
    left join shipment_receiving_count as rc
           on f.msku = rc.msku
          and f.store_name = rc.store_name
    where f.receiving_time is not null
      and f.receiving_time <> ''
      and f.quantity_received <> 0
    group by f.country_category, f.seller_name_new, f.msku
),
metric_base as (
    select
        m.*,
        b.max_brand_name,
        r.receiving_cnt,
        case
            when (
                b.max_brand_name like '%2025%'
                or b.max_brand_name like '%2026%'
            )
            and (r.receiving_cnt <= 1 or r.receiving_cnt is null)
                then 1
            else 0
        end as is_new_product
    from period_metrics as m
    left join product_brand as b
           on m.country_category = b.country_category
          and m.seller_name_new = b.seller_name_new
          and m.seller_sku_adj = b.seller_sku
    left join receiving_metrics as r
           on m.country_category = r.country_category
          and m.seller_name_new = r.seller_name_new
          and m.seller_sku_adj = r.msku
),
adjusted_daily_sales as (
    select
        m.*,
        case
            when m.r_30d_salable_days >= 7 then
                case when m.r_3d_salable_days > 0
                     then m.sales_3 / m.r_3d_salable_days else 0 end
            else m.sales_3 / greatest(m.r_3d_salable_days, 2)
        end as daily_sales_3d,
        case
            when m.r_30d_salable_days >= 7 then
                case
                    when m.r_7d_salable_days >= 7
                        then m.sales_7 / m.r_7d_salable_days
                    else least(
                        case when m.r_7d_salable_days > 0
                             then m.sales_7 / m.r_7d_salable_days else 0 end,
                        (case when m.r_7d_salable_days > 0
                              then m.sales_7 / m.r_7d_salable_days else 0 end)
                            * (m.r_7d_salable_days / (m.r_7d_salable_days + 3))
                        + (m.sales_30 / m.r_30d_salable_days)
                            * (1 - m.r_7d_salable_days / (m.r_7d_salable_days + 3))
                    )
                end
            else m.sales_7 / greatest(m.r_7d_salable_days, 3)
        end as daily_sales_7d,
        case
            when m.r_30d_salable_days >= 7 then
                case
                    when m.r_14d_salable_days >= 14
                        then m.sales_14 / m.r_14d_salable_days
                    else least(
                        case when m.r_14d_salable_days > 0
                             then m.sales_14 / m.r_14d_salable_days else 0 end,
                        (case when m.r_14d_salable_days > 0
                              then m.sales_14 / m.r_14d_salable_days else 0 end)
                            * (m.r_14d_salable_days / (m.r_14d_salable_days + 7))
                        + (m.sales_30 / m.r_30d_salable_days)
                            * (1 - m.r_14d_salable_days / (m.r_14d_salable_days + 7))
                    )
                end
            else m.sales_14 / greatest(m.r_14d_salable_days, 7)
        end as daily_sales_14d,
        case
            when m.r_30d_salable_days >= 7
                then m.sales_30 / m.r_30d_salable_days
            else m.sales_30 / greatest(m.r_30d_salable_days, 15)
        end as daily_sales_30d
    from metric_base as m
),
weighted_metrics as (
    select
        a.*,
        case
            when a.is_new_product = 1 then
                a.daily_sales_3d * 0.5
                + a.daily_sales_7d * 0.5
            else
                a.daily_sales_7d * 0.6
                + a.daily_sales_14d * 0.2
                + a.daily_sales_30d * 0.2
        end as daily_avg_sales
    from adjusted_daily_sales as a
),
eligible_site_metrics as (
    select
        w.*,
        lp.listing_price,
        lp.currency_code,
        lp.exchange_rate_cny,
        lp.listing_price_cny,
        i.inventory_snapshot_date,
        i.restock_snapshot_date,
        i.available_total,
        i.stock_up_num,
        i.local_quantity,
        i.total_budget_inventory,
        sum(
            case when w.daily_avg_sales > 0 then w.daily_avg_sales else 0 end
        ) over (
            partition by
                w.country_category,
                w.seller_name_new,
                w.seller_sku_adj
        ) as total_weighted_daily_sales,
        sum(
            case
                when w.daily_avg_sales > 0
                 and (lp.listing_price is null or lp.exchange_rate_cny is null)
                    then 1
                else 0
            end
        ) over (
            partition by
                w.country_category,
                w.seller_name_new,
                w.seller_sku_adj
        ) as missing_price_site_count
    from weighted_metrics as w
    left join dws_datasync.tmp_replenishment_listing_price_latest as lp
           on w.country_category = lp.country_category
          and w.country = lp.country
          and w.seller_name_new = lp.seller_name_new
          and binary w.seller_sku_adj = lp.seller_sku_adj
    left join dws_datasync.tmp_replenishment_budget_inventory_latest as i
           on w.country_category = i.country_category
          and w.seller_name_new = i.seller_name_new
          and binary w.seller_sku_adj = i.seller_sku_adj
    where w.country in ('德国', '法国', '意大利', '西班牙', '荷兰', '美国', '英国')
),
allocation_metrics as (
    select
        e.*,
        case
            when e.daily_avg_sales > 0
             and e.total_weighted_daily_sales > 0
                then e.daily_avg_sales / e.total_weighted_daily_sales
            else 0
        end as sales_share,
        greatest(e.daily_avg_sales, 0) * 30 as monthly_forecast_qty,
        case
            when e.daily_avg_sales > 0
             and e.total_weighted_daily_sales > 0
             and e.inventory_snapshot_date is not null
             and e.restock_snapshot_date is not null
                then e.daily_avg_sales * least(
                    30,
                    greatest(e.total_budget_inventory, 0)
                        / e.total_weighted_daily_sales
                )
            else 0
        end as monthly_allocated_qty,
        greatest(e.daily_avg_sales, 0) * 7 as weekly_forecast_qty,
        case
            when e.daily_avg_sales > 0
             and e.total_weighted_daily_sales > 0
             and e.inventory_snapshot_date is not null
             and e.restock_snapshot_date is not null
                then e.daily_avg_sales * least(
                    7,
                    greatest(e.total_budget_inventory, 0)
                        / e.total_weighted_daily_sales
                )
            else 0
        end as weekly_allocated_qty
    from eligible_site_metrics as e
),
previous_state_metrics as (
    select
        a.*,
        p.biz_date as previous_biz_date,
        p.monthly_forecast_qty as previous_monthly_forecast_qty,
        p.monthly_allocated_qty as previous_monthly_allocated_qty,
        p.monthly_ad_budget_original as previous_monthly_ad_budget_original,
        p.monthly_ad_budget_cny as previous_monthly_ad_budget_cny,
        p.weekly_forecast_qty as previous_weekly_forecast_qty,
        p.weekly_allocated_qty as previous_weekly_allocated_qty,
        p.weekly_ad_budget_original as previous_weekly_ad_budget_original,
        p.weekly_ad_budget_cny as previous_weekly_ad_budget_cny,
        coalesce(p.total_inventory_allocated_qty, 0)
            as previous_total_inventory_allocated_qty,
        p.site_total_budget_cny as previous_site_total_budget_cny,
        max(p.biz_date) over (
            partition by
                a.country_category,
                a.seller_name_new,
                a.seller_sku_adj
        ) as previous_group_biz_date,
        max(coalesce(p.month_max_inventory_qty, 0)) over (
            partition by
                a.country_category,
                a.seller_name_new,
                a.seller_sku_adj
        ) as previous_month_max_inventory_qty,
        max(p.total_budget_pool_cny) over (
            partition by
                a.country_category,
                a.seller_name_new,
                a.seller_sku_adj
        ) as previous_total_budget_pool_cny
    from allocation_metrics as a
    left join dws_datasync.tmp_replenishment_previous_budget_state as p
           on a.country_category = p.country_category
          and a.country = p.country
          and a.seller_name_new = p.seller_name_new
          and binary a.seller_sku_adj = p.seller_sku_adj
),
monthly_budget_module as (
    select
        p.*,
        case
            when p.previous_biz_date is null
              or date_format(p.previous_biz_date, '%Y-%m')
                 <> date_format(@run_date, '%Y-%m')
                then p.monthly_forecast_qty
            else p.previous_monthly_forecast_qty
        end as current_monthly_forecast_qty,
        case
            when p.previous_biz_date is null
              or date_format(p.previous_biz_date, '%Y-%m')
                 <> date_format(@run_date, '%Y-%m')
                then p.monthly_allocated_qty
            else p.previous_monthly_allocated_qty
        end as current_monthly_allocated_qty,
        case
            when p.previous_biz_date is null
              or date_format(p.previous_biz_date, '%Y-%m')
                 <> date_format(@run_date, '%Y-%m') then
                case
                    when p.daily_avg_sales <= 0 then 0
                    when p.listing_price is null then null
                    else p.monthly_allocated_qty * p.listing_price * 0.05
                end
            else p.previous_monthly_ad_budget_original
        end as current_monthly_ad_budget_original,
        case
            when p.previous_biz_date is null
              or date_format(p.previous_biz_date, '%Y-%m')
                 <> date_format(@run_date, '%Y-%m') then
                case
                    when p.daily_avg_sales <= 0 then 0
                    when p.listing_price_cny is null then null
                    else p.monthly_allocated_qty * p.listing_price_cny * 0.05
                end
            else p.previous_monthly_ad_budget_cny
        end as current_monthly_ad_budget_cny
    from previous_state_metrics as p
),
weekly_budget_module as (
    select
        m.*,
        case
            when m.previous_biz_date is null
              or weekday(@run_date) = 0
                then m.weekly_forecast_qty
            else m.previous_weekly_forecast_qty
        end as current_weekly_forecast_qty,
        case
            when m.previous_biz_date is null
              or weekday(@run_date) = 0
                then m.weekly_allocated_qty
            else m.previous_weekly_allocated_qty
        end as current_weekly_allocated_qty,
        case
            when m.previous_biz_date is null
              or weekday(@run_date) = 0 then
                case
                    when m.daily_avg_sales <= 0 then 0
                    when m.listing_price is null then null
                    else m.weekly_allocated_qty * m.listing_price * 0.05
                end
            else m.previous_weekly_ad_budget_original
        end as current_weekly_ad_budget_original,
        case
            when m.previous_biz_date is null
              or weekday(@run_date) = 0 then
                case
                    when m.daily_avg_sales <= 0 then 0
                    when m.listing_price_cny is null then null
                    else m.weekly_allocated_qty * m.listing_price_cny * 0.05
                end
            else m.previous_weekly_ad_budget_cny
        end as current_weekly_ad_budget_cny
    from monthly_budget_module as m
),
inventory_growth_base as (
    select
        i.*,
        case
            when i.previous_group_biz_date is null
              or date_format(i.previous_group_biz_date, '%Y-%m')
                 <> date_format(@run_date, '%Y-%m') then
                case
                    when i.inventory_snapshot_date is null
                      or i.restock_snapshot_date is null then 0
                    else greatest(i.total_budget_inventory, 0)
                end
            when i.inventory_snapshot_date is null
              or i.restock_snapshot_date is null then 0
            else greatest(
                i.total_budget_inventory - i.previous_month_max_inventory_qty,
                0
            )
        end as inventory_growth_qty
    from weekly_budget_module as i
),
inventory_budget_module as (
    select
        i.*,
        case
            when i.previous_group_biz_date is null
              or date_format(i.previous_group_biz_date, '%Y-%m')
                 <> date_format(@run_date, '%Y-%m') then i.inventory_growth_qty
            when i.inventory_growth_qty > 0
                then i.previous_month_max_inventory_qty + i.inventory_growth_qty
            else i.previous_month_max_inventory_qty
        end as month_max_inventory_qty,
        case
            when i.previous_group_biz_date is null
              or date_format(i.previous_group_biz_date, '%Y-%m')
                 <> date_format(@run_date, '%Y-%m') then
                case
                    when i.total_weighted_daily_sales <= 0
                      or i.missing_price_site_count > 0 then 0
                    else i.inventory_growth_qty * i.sales_share
                end
            when i.inventory_growth_qty > 0
             and i.total_weighted_daily_sales > 0
             and i.missing_price_site_count = 0
                then i.previous_total_inventory_allocated_qty
                   + i.inventory_growth_qty * i.sales_share
            else i.previous_total_inventory_allocated_qty
        end as total_inventory_allocated_qty,
        case
            when i.previous_group_biz_date is null
              or date_format(i.previous_group_biz_date, '%Y-%m')
                 <> date_format(@run_date, '%Y-%m') then
                case
                    when i.daily_avg_sales <= 0 then 0
                    when i.missing_price_site_count > 0 then null
                    else i.inventory_growth_qty * i.sales_share
                       * i.listing_price_cny * 0.05
                end
            when i.previous_biz_date is null then
                case
                    when i.daily_avg_sales <= 0 then 0
                    when i.missing_price_site_count > 0 then null
                    else i.inventory_growth_qty * i.sales_share
                       * i.listing_price_cny * 0.05
                end
            when i.inventory_growth_qty > 0
             and i.total_weighted_daily_sales > 0
             and i.missing_price_site_count = 0
             and i.sales_share <= 0
                then i.previous_site_total_budget_cny
            when i.inventory_growth_qty > 0
             and i.total_weighted_daily_sales > 0
             and i.missing_price_site_count = 0
                then i.previous_site_total_budget_cny
                   + i.inventory_growth_qty * i.sales_share
                   * i.listing_price_cny * 0.05
            else i.previous_site_total_budget_cny
        end as site_total_budget_cny_raw
    from inventory_growth_base as i
),
site_budget_storage_metrics as (
    select
        i.*,
        round(i.site_total_budget_cny_raw, 2) as site_total_budget_cny,
        case
            when i.previous_group_biz_date is null
              or date_format(i.previous_group_biz_date, '%Y-%m')
                 <> date_format(@run_date, '%Y-%m')
                then round(i.site_total_budget_cny_raw, 2)
            when i.previous_biz_date is null
                then round(i.site_total_budget_cny_raw, 2)
            when i.previous_site_total_budget_cny is null
              or i.site_total_budget_cny_raw is null then null
            else round(i.site_total_budget_cny_raw, 2)
               - i.previous_site_total_budget_cny
        end as site_budget_increment_cny
    from inventory_budget_module as i
),
budget_pool_metrics as (
    select
        i.*,
        sum(i.site_budget_increment_cny) over (
            partition by
                i.country_category,
                i.seller_name_new,
                i.seller_sku_adj
        ) as total_budget_increment_cny_sum
    from site_budget_storage_metrics as i
),
final_result as (
select
    cast(@run_date as date) as biz_date,
    a.country_category,
    a.country,
    a.seller_name_new,
    a.seller_sku_adj,
    a.max_brand_name,
    a.receiving_cnt,
    case when a.is_new_product = 1 then '新品' else '老品' end as product_type,
    a.sales_3,
    a.r_3d_salable_days,
    a.sales_7,
    a.r_7d_salable_days,
    a.sales_14,
    a.r_14d_salable_days,
    a.sales_30,
    a.r_30d_salable_days,
    round(a.daily_avg_sales, 6) as daily_avg_sales,
    round(a.listing_price, 4) as listing_price,
    a.currency_code,
    round(a.exchange_rate_cny, 4) as exchange_rate_cny,
    round(a.listing_price_cny, 2) as listing_price_cny,
    round(a.available_total, 4) as available_total,
    round(a.stock_up_num, 4) as stock_up_num,
    round(a.local_quantity, 4) as local_quantity,
    round(a.total_budget_inventory, 4) as total_budget_inventory,
    round(a.month_max_inventory_qty, 4) as month_max_inventory_qty,
    round(a.total_weighted_daily_sales, 6) as total_weighted_daily_sales,
    round(a.sales_share, 8) as sales_share,
    round(a.total_inventory_allocated_qty, 4) as total_inventory_allocated_qty,
    round(a.site_total_budget_cny, 2) as site_total_budget_cny,
    round(a.current_monthly_forecast_qty, 4) as monthly_forecast_qty,
    round(a.current_monthly_allocated_qty, 4) as monthly_allocated_qty,
    round(a.current_monthly_ad_budget_original, 2) as monthly_ad_budget_original,
    round(a.current_monthly_ad_budget_cny, 2) as monthly_ad_budget_cny,
    round(a.current_weekly_forecast_qty, 4) as weekly_forecast_qty,
    round(a.current_weekly_allocated_qty, 4) as weekly_allocated_qty,
    round(a.current_weekly_ad_budget_original, 2) as weekly_ad_budget_original,
    round(a.current_weekly_ad_budget_cny, 2) as weekly_ad_budget_cny,
    case
        when (
            a.previous_group_biz_date is null
            or date_format(a.previous_group_biz_date, '%Y-%m')
               <> date_format(@run_date, '%Y-%m')
        ) then
            case
                when a.total_weighted_daily_sales > 0
                 and (
                    a.missing_price_site_count > 0
                    or a.inventory_snapshot_date is null
                    or a.restock_snapshot_date is null
                 ) then null
                else round(a.total_budget_increment_cny_sum, 2)
            end
        when a.previous_total_budget_pool_cny is null then null
        when a.inventory_growth_qty > 0
         and a.total_weighted_daily_sales > 0
         and a.missing_price_site_count = 0
            then round(
                a.previous_total_budget_pool_cny
                + coalesce(a.total_budget_increment_cny_sum, 0),
                2
            )
        else a.previous_total_budget_pool_cny
    end as total_budget_pool_cny,
    case
        when a.inventory_snapshot_date is null
          or a.restock_snapshot_date is null then 0
        when a.total_weighted_daily_sales <= 0 then 1
        when a.total_budget_inventory >= a.total_weighted_daily_sales * 30 then 1
        else 0
    end as inventory_sufficient_flag,
    case
        when a.inventory_snapshot_date is null
          or a.restock_snapshot_date is null then 0
        when a.total_weighted_daily_sales <= 0 then 1
        when a.total_budget_inventory >= a.total_weighted_daily_sales * 7 then 1
        else 0
    end as weekly_inventory_sufficient_flag
from budget_pool_metrics as a
)
select
    new.biz_date,
    new.country_category,
    new.country,
    new.seller_name_new,
    new.seller_sku_adj,
    new.max_brand_name,
    new.receiving_cnt,
    new.product_type,
    new.sales_3,
    new.r_3d_salable_days,
    new.sales_7,
    new.r_7d_salable_days,
    new.sales_14,
    new.r_14d_salable_days,
    new.sales_30,
    new.r_30d_salable_days,
    new.daily_avg_sales,
    new.listing_price,
    new.currency_code,
    new.exchange_rate_cny,
    new.listing_price_cny,
    new.available_total,
    new.stock_up_num,
    new.local_quantity,
    new.total_budget_inventory,
    new.month_max_inventory_qty,
    new.total_weighted_daily_sales,
    new.sales_share,
    new.total_inventory_allocated_qty,
    new.site_total_budget_cny,
    new.monthly_forecast_qty,
    new.monthly_allocated_qty,
    new.monthly_ad_budget_original,
    new.monthly_ad_budget_cny,
    new.weekly_forecast_qty,
    new.weekly_allocated_qty,
    new.weekly_ad_budget_original,
    new.weekly_ad_budget_cny,
    new.total_budget_pool_cny,
    new.inventory_sufficient_flag,
    new.weekly_inventory_sufficient_flag
from final_result as new
on duplicate key update
    biz_date = new.biz_date,
    max_brand_name = new.max_brand_name,
    receiving_cnt = new.receiving_cnt,
    product_type = new.product_type,
    sales_3 = new.sales_3,
    r_3d_salable_days = new.r_3d_salable_days,
    sales_7 = new.sales_7,
    r_7d_salable_days = new.r_7d_salable_days,
    sales_14 = new.sales_14,
    r_14d_salable_days = new.r_14d_salable_days,
    sales_30 = new.sales_30,
    r_30d_salable_days = new.r_30d_salable_days,
    daily_avg_sales = new.daily_avg_sales,
    listing_price = new.listing_price,
    currency_code = new.currency_code,
    exchange_rate_cny = new.exchange_rate_cny,
    listing_price_cny = new.listing_price_cny,
    available_total = new.available_total,
    stock_up_num = new.stock_up_num,
    local_quantity = new.local_quantity,
    total_budget_inventory = new.total_budget_inventory,
    month_max_inventory_qty = new.month_max_inventory_qty,
    total_weighted_daily_sales = new.total_weighted_daily_sales,
    sales_share = new.sales_share,
    total_inventory_allocated_qty = new.total_inventory_allocated_qty,
    site_total_budget_cny = new.site_total_budget_cny,
    monthly_forecast_qty = new.monthly_forecast_qty,
    monthly_allocated_qty = new.monthly_allocated_qty,
    monthly_ad_budget_original = new.monthly_ad_budget_original,
    monthly_ad_budget_cny = new.monthly_ad_budget_cny,
    weekly_forecast_qty = new.weekly_forecast_qty,
    weekly_allocated_qty = new.weekly_allocated_qty,
    weekly_ad_budget_original = new.weekly_ad_budget_original,
    weekly_ad_budget_cny = new.weekly_ad_budget_cny,
    total_budget_pool_cny = new.total_budget_pool_cny,
    inventory_sufficient_flag = new.inventory_sufficient_flag,
    weekly_inventory_sufficient_flag = new.weekly_inventory_sufficient_flag;

/* 第六层：从本次最终结果汇总国家类别预算池，保存每日可追溯快照。 */
drop temporary table if exists dws_datasync.tmp_ad_budget_previous_pool_history;
create temporary table dws_datasync.tmp_ad_budget_previous_pool_history
engine=innodb
default charset=utf8mb4
as
select
    h.biz_date,
    h.country_category,
    h.seller_name_new,
    h.seller_sku_adj,
    h.month_max_inventory_qty,
    h.total_budget_pool_cny
from (
    select
        p.biz_date,
        p.country_category,
        p.seller_name_new,
        p.seller_sku_adj,
        p.month_max_inventory_qty,
        p.total_budget_pool_cny,
        row_number() over (
            partition by
                p.country_category,
                p.seller_name_new,
                p.seller_sku_adj
            order by p.biz_date desc
        ) as history_rank
    from dws_datasync.dws_ad_budget_pool_daily_history as p
    where p.biz_date < @run_date
) as h
where h.history_rank = 1;

alter table dws_datasync.tmp_ad_budget_previous_pool_history
    add primary key (
        country_category,
        seller_name_new,
        seller_sku_adj
    );

insert into dws_datasync.dws_ad_budget_pool_daily_history (
    biz_date,
    country_category,
    seller_name_new,
    seller_sku_adj,
    available_total,
    stock_up_num,
    local_quantity,
    total_budget_inventory,
    previous_month_max_inventory_qty,
    month_max_inventory_qty,
    inventory_growth_qty,
    total_weighted_daily_sales,
    previous_total_budget_pool_cny,
    budget_change_cny,
    budget_increment_cny,
    budget_per_inventory_cny,
    total_budget_pool_cny,
    monthly_budget_cny,
    weekly_budget_cny,
    change_type
)
with
current_pool as (
    select
        d.biz_date,
        d.country_category,
        d.seller_name_new,
        d.seller_sku_adj,
        max(d.available_total) as available_total,
        max(d.stock_up_num) as stock_up_num,
        max(d.local_quantity) as local_quantity,
        max(d.total_budget_inventory) as total_budget_inventory,
        max(d.month_max_inventory_qty) as month_max_inventory_qty,
        max(d.total_weighted_daily_sales) as total_weighted_daily_sales,
        max(d.total_budget_pool_cny) as total_budget_pool_cny,
        round(sum(coalesce(d.monthly_ad_budget_cny, 0)), 2)
            as monthly_budget_cny,
        round(sum(coalesce(d.weekly_ad_budget_cny, 0)), 2)
            as weekly_budget_cny
    from dws_datasync.dws_monthly_ad_budget_detail as d
    where d.biz_date = @run_date
    group by
        d.biz_date,
        d.country_category,
        d.seller_name_new,
        d.seller_sku_adj
),
history_base as (
    select
        c.*,
        p.biz_date as previous_biz_date,
        p.month_max_inventory_qty as previous_month_max_inventory_qty,
        p.total_budget_pool_cny as previous_total_budget_pool_cny,
        case
            when p.biz_date is null then 0
            when date_format(p.biz_date, '%Y-%m')
               <> date_format(c.biz_date, '%Y-%m') then 0
            else greatest(
                coalesce(c.month_max_inventory_qty, 0)
                    - coalesce(p.month_max_inventory_qty, 0),
                0
            )
        end as inventory_growth_qty,
        case
            when p.biz_date is null then 0
            when date_format(p.biz_date, '%Y-%m')
               <> date_format(c.biz_date, '%Y-%m') then 0
            when c.total_budget_pool_cny is null
              or p.total_budget_pool_cny is null then null
            else round(
                c.total_budget_pool_cny - p.total_budget_pool_cny,
                2
            )
        end as budget_change_cny
    from current_pool as c
    left join dws_datasync.tmp_ad_budget_previous_pool_history as p
           on c.country_category = p.country_category
          and c.seller_name_new = p.seller_name_new
          and binary c.seller_sku_adj = p.seller_sku_adj
),
history_metrics as (
    select
        h.*,
        case
            when h.budget_change_cny > 0
                then h.budget_change_cny
            else 0
        end as budget_increment_cny,
        case
            when h.inventory_growth_qty > 0
             and h.budget_change_cny > 0
                then h.budget_change_cny / h.inventory_growth_qty
            else null
        end as budget_per_inventory_cny,
        case
            when h.previous_biz_date is null then '初始化'
            when date_format(h.previous_biz_date, '%Y-%m')
               <> date_format(h.biz_date, '%Y-%m') then '月初重置'
            when h.budget_change_cny > 0.01 then '库存增加'
            when h.budget_change_cny < -0.01 then '预算减少异常'
            else '无变化'
        end as change_type
    from history_base as h
)
select
    new.biz_date,
    new.country_category,
    new.seller_name_new,
    new.seller_sku_adj,
    new.available_total,
    new.stock_up_num,
    new.local_quantity,
    new.total_budget_inventory,
    new.previous_month_max_inventory_qty,
    new.month_max_inventory_qty,
    round(new.inventory_growth_qty, 4),
    new.total_weighted_daily_sales,
    new.previous_total_budget_pool_cny,
    new.budget_change_cny,
    new.budget_increment_cny,
    round(new.budget_per_inventory_cny, 6),
    new.total_budget_pool_cny,
    new.monthly_budget_cny,
    new.weekly_budget_cny,
    new.change_type
from history_metrics as new
on duplicate key update
    available_total = new.available_total,
    stock_up_num = new.stock_up_num,
    local_quantity = new.local_quantity,
    total_budget_inventory = new.total_budget_inventory,
    previous_month_max_inventory_qty = new.previous_month_max_inventory_qty,
    month_max_inventory_qty = new.month_max_inventory_qty,
    inventory_growth_qty = new.inventory_growth_qty,
    total_weighted_daily_sales = new.total_weighted_daily_sales,
    previous_total_budget_pool_cny = new.previous_total_budget_pool_cny,
    budget_change_cny = new.budget_change_cny,
    budget_increment_cny = new.budget_increment_cny,
    budget_per_inventory_cny = new.budget_per_inventory_cny,
    total_budget_pool_cny = new.total_budget_pool_cny,
    monthly_budget_cny = new.monthly_budget_cny,
    weekly_budget_cny = new.weekly_budget_cny,
    change_type = new.change_type,
    updated_at = current_timestamp;

/* 仅保留今天及之前 29 天，共 30 个自然日的预算池快照。 */
delete from dws_datasync.dws_ad_budget_pool_daily_history
where biz_date < date_sub(@run_date, interval 29 day);


end$$

delimiter ;
