/*
用途：使用两张会话临时表计算补货口径的国家站点加权日销和双币种广告预算，最终直接返回查询结果。

会话临时表：
1. dws_datasync.tmp_replenishment_weighted_sales_product_30d
   - 产品表现最近 30 天的国家周期汇总
2. dws_datasync.tmp_replenishment_listing_price_latest
   - Listing 最新同步日的国家售价和人民币汇率

以上两张表只在当前数据库连接内存在，连接关闭后由 MySQL 自动释放；本 SQL 不持久化过程表或最终结果表。

远端源表：
1. dwd_datasync.lx_statistics_product_performance
2. dwd_datasync.lx_sales_mws_listing
3. dwd_datasync.lx_basic_currency
4. etl_datasync.etl_dispose_lx_product_local_product_info
5. etl_datasync.etl_dispose_lx_fba_shipment

参数：
- @biz_date：产品表现的最新业务日期。
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

/* 第三层：直接读取两张会话临时表并返回最终结果。 */
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
)
select
    cast(@biz_date as date) as biz_date,
    w.country_category,
    w.country,
    w.seller_name_new,
    w.seller_sku_adj,
    w.max_brand_name,
    w.receiving_cnt,
    case when w.is_new_product = 1 then '新品' else '老品' end as product_type,
    w.sales_3,
    w.r_3d_salable_days,
    w.sales_7,
    w.r_7d_salable_days,
    w.sales_14,
    w.r_14d_salable_days,
    w.sales_30,
    w.r_30d_salable_days,
    round(w.daily_avg_sales, 6) as daily_avg_sales,
    round(lp.listing_price, 4) as listing_price,
    lp.currency_code,
    round(lp.exchange_rate_cny, 4) as exchange_rate_cny,
    round(lp.listing_price_cny, 2) as listing_price_cny,
    round(lp.listing_price * 0.05 * w.daily_avg_sales * 30, 2) as ad_budget_original,
    round(
        lp.listing_price * lp.exchange_rate_cny
        * 0.05 * w.daily_avg_sales * 30,
        2
    ) as ad_budget_cny
from weighted_metrics as w
left join dws_datasync.tmp_replenishment_listing_price_latest as lp
       on w.country_category = lp.country_category
      and w.country = lp.country
      and w.seller_name_new = lp.seller_name_new
      and binary w.seller_sku_adj = lp.seller_sku_adj
order by
    w.country_category,
    w.country,
    w.seller_name_new,
    w.seller_sku_adj;
