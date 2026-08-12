/*
用途：按补货库存池和白名单国家站点的加权日销占比，计算月度、周度广告预算并直接返回查询结果。

会话临时表：
1. dws_datasync.tmp_replenishment_weighted_sales_product_30d
   - 产品表现最近 30 天的国家周期汇总
2. dws_datasync.tmp_replenishment_listing_price_latest
   - Listing 最新同步日的国家售价和人民币汇率
3. dws_datasync.tmp_replenishment_budget_inventory_latest
   - 补货口径最新库存池，粒度为国家类别、店铺、MSKU

三张临时表只在当前数据库连接内存在；本 SQL 不建结果表，也不写入结果表。

远端源表：
1. dwd_datasync.lx_statistics_product_performance
2. dwd_datasync.lx_sales_mws_listing
3. dwd_datasync.lx_basic_currency
4. etl_datasync.etl_dispose_lx_product_local_product_info
5. etl_datasync.etl_dispose_lx_fba_shipment
6. etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
7. etl_datasync.etl_dispose_lx_replenishment_suggest_restocking

白名单国家站点：德国、法国、意大利、西班牙、荷兰、美国、英国。
*/

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

/* 第四层：只处理白名单国家站点，按加权日销占比分配库存和预算并直接返回结果。 */
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
                 and lp.listing_price_cny is not null
                    then w.daily_avg_sales * lp.listing_price_cny
                else 0
            end
        ) over (
            partition by
                w.country_category,
                w.seller_name_new,
                w.seller_sku_adj
        ) as weighted_price_cny_numerator,
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
)
select
    cast(@biz_date as date) as biz_date,
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
    round(a.total_weighted_daily_sales, 6) as total_weighted_daily_sales,
    round(a.sales_share, 8) as sales_share,
    round(a.monthly_forecast_qty, 4) as monthly_forecast_qty,
    round(a.monthly_allocated_qty, 4) as monthly_allocated_qty,
    case
        when a.daily_avg_sales <= 0 then 0
        when a.listing_price is null then null
        else round(a.monthly_allocated_qty * a.listing_price * 0.05, 2)
    end as monthly_ad_budget_original,
    case
        when a.daily_avg_sales <= 0 then 0
        when a.listing_price_cny is null then null
        else round(a.monthly_allocated_qty * a.listing_price_cny * 0.05, 2)
    end as monthly_ad_budget_cny,
    round(a.weekly_forecast_qty, 4) as weekly_forecast_qty,
    round(a.weekly_allocated_qty, 4) as weekly_allocated_qty,
    case
        when a.daily_avg_sales <= 0 then 0
        when a.listing_price is null then null
        else round(a.weekly_allocated_qty * a.listing_price * 0.05, 2)
    end as weekly_ad_budget_original,
    case
        when a.daily_avg_sales <= 0 then 0
        when a.listing_price_cny is null then null
        else round(a.weekly_allocated_qty * a.listing_price_cny * 0.05, 2)
    end as weekly_ad_budget_cny,
    case
        when a.total_weighted_daily_sales <= 0 then 0
        when a.missing_price_site_count > 0
          or a.inventory_snapshot_date is null
          or a.restock_snapshot_date is null then null
        else round(
            greatest(
                a.total_budget_inventory,
                0
            )
            * a.weighted_price_cny_numerator
            / a.total_weighted_daily_sales
            * 0.05,
            2
        )
    end as total_budget_pool_cny,
    case
        when a.inventory_snapshot_date is null
          or a.restock_snapshot_date is null then 0
        when a.total_weighted_daily_sales <= 0 then 1
        when a.total_budget_inventory >= a.total_weighted_daily_sales * 30 then 1
        else 0
    end as inventory_sufficient_flag
from allocation_metrics as a
order by
    a.country_category,
    a.country,
    a.seller_name_new,
    a.seller_sku_adj;
