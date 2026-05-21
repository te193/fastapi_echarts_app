
set @start_date='2026-01-01';
set @end_date='2026-03-31';

drop table if exists etl_datasync.product_performance_90_days;
create table etl_datasync.product_performance_90_days as
with a as (
    select
        year(start_date) as dt_year,
        yearweek(start_date, 1) as dt_week,
        month(start_date) as dt_month,
        date(start_date) as dt_date,
        country,
        case
            when country = '英国' then '英国站'
            when country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
            else '欧洲站'
        end as country_category,
        local_sku as local_sku,
        max(seller_name) as seller_name,
        left(seller_name, locate('-', seller_name) - 1) as seller_name_new,
        if(
            length(substring_index(seller_sku, ',', 1)) > 16,
            replace(substring_index(substring_index(seller_sku, ',', 1), '-', 1), 'amzn.gr.', ''),
            substring_index(seller_sku, ',', 1)
        ) as seller_sku_adj,
        sum(volume) as 销量,
        sum(amount) as 销售额,
        sum(
            case
                when country = '德国' then amount / 1.19
                when country = '法国' then amount / 1.2
                when country = '瑞典' then amount / 1.25
                when country = '西班牙' then amount / 1.21
                when country = '意大利' then amount / 1.22
                when country = '英国' then amount / 1.2
                when country = '比利时' then amount / 1.21
                when country = '荷兰' then amount / 1.21
                when country = '爱尔兰' then amount / 1.23
                when country = '波兰' then amount / 1.23
                when country = '墨西哥' then amount / 1.16
                when country = '土耳其' then amount / 1.20
                else amount
            end
        ) as 销售额_不含税,
        sum(predict_gross_profit) as 原订单毛利润,
        sum(case when volume =0 then 0 else predict_gross_profit end ) as 订单毛利润,
        sum(case when (volume =0 and predict_gross_profit!=0) or (amount<abs(predict_gross_profit)) then 1
            else 0 end) as 是否异常,
        sum(gross_profit) as 结算毛利润,
        max(afn_fulfillable_quantity) as afn_fulfillable_quantity,
        sum(spend) as 广告花费,
        sum(ad_order_quantity) as 广告订单量,
        sum(ad_sales_amount) as 广告销售额,
        sum(clicks) as 广告点击量,
        sum(impressions) as 广告曝光量
#         max(available_days) as 预估可售天数
    from dwd_datasync.lx_statistics_product_performance
    where start_date >= @start_date
      and start_date < @end_date + interval 1 day
    and seller_sku not like 'Amazon.Found%'
#     and country in ('德国','法国','意大利','西班牙','荷兰','美国')
    group by
        year(start_date),
        yearweek(start_date, 1),
        month(start_date),
        date(start_date),
        country,
        case
            when country = '英国' then '英国站'
            when country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
            else '欧洲站'
        end,
        left(seller_name, locate('-', seller_name) - 1),
        if(
            length(substring_index(seller_sku, ',', 1)) > 16,
            replace(substring_index(substring_index(seller_sku, ',', 1), '-', 1), 'amzn.gr.', ''),
            substring_index(seller_sku, ',', 1)
        ),local_sku)
    select * from a;




drop table if exists etl_datasync.month_end_data_补货建议;
create table etl_datasync.month_end_data_补货建议 as
with
b as (
    select
        date(create_time) as dt_date,
        country_category,
        seller_sku_adj,
        seller_name_new,
        max(sc_quantity_local_valid)
        + max(sc_quantity_purchase_shipping)
        + max(sc_quantity_purchase_plan)
        + max(sc_quantity_local_qc) as local_quantity
    from etl_datasync.etl_dispose_lx_replenishment_suggest_restocking
 where create_time >=curdate()
    group by
        date(create_time),
        country_category,
        seller_sku_adj,
        seller_name_new
)
select * from b;

drop table if exists etl_datasync.month_end_data_库存明细;
create table etl_datasync.month_end_data_库存明细 as
with
    c as (
    select
        date(create_time) as dt_date,
        country_category,
        seller_sku_adj,
        seller_name_new,
        sum(total) as total,-- 总库存
        sum(total_price) as total_price, -- 总库存成本
        sum(available_total) as available_total, -- 可用库存
        sum(available_total_price ) as available_price, -- 可用库存成本
        sum(afn_fulfillable_quantity) as afn_fulfillable_quantity, -- fba可售
        sum(reserved_fc_transfers) as reserved_fc_transfers, -- 待调仓
        sum(reserved_fc_processing) as reserved_fc_processing, -- 调仓中
        sum(reserved_customerorders) as reserved_customerorders, -- 待发货
        sum(afn_unsellable_quantity) as afn_unsellable_quantity, -- 不可售
        sum(afn_inbound_working_quantity) as afn_inbound_working_quantity, -- 计划入库
        sum(stock_up_num) as stock_up_num, -- 实际在途
        sum(afn_researching_quantity) as afn_researching_quantity,-- 调查中
        sum(total_fulfillable_quantity) as total_fulfillable_quantity -- 总可用库存

    from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
    where create_time >= curdate()
    group by
        date(create_time),
        country_category,
        seller_sku_adj,
        seller_name_new
)
select * from c;

set @start_date='2026-01-01';
set @end_date='2026-03-31';

with
    产品表现数据 as (
      select
          seller_name_new,
          max(seller_name) as seller_name,
          seller_sku_adj,
          country_category,
          country,
          local_sku,
          sum(销量) as 销量,
          sum(销售额) as 销售额,
          sum(销售额_不含税) as 销售额_不含税,
          sum(订单毛利润) as 订单毛利润,
          sum(原订单毛利润) as 原订单毛利润,
          sum(结算毛利润) as 结算毛利润,
          round(sum(订单毛利润) / nullif(sum(销售额_不含税), 0), 2) as 订单毛利率,
          max(afn_fulfillable_quantity) as afn_fulfillable_quantity,
          sum(case when afn_fulfillable_quantity <>0 then 1 else 0  end) as '有库存的天数',
        abs(datediff(@start_date, @end_date))+1 as '统计天数',
        sum(销量)/(abs(datediff(@start_date, @end_date))+1) as '日销',
        sum(是否异常) as 异常天数 ,
        nullif(sum(销量)/sum(case when afn_fulfillable_quantity <>0 then 1 else 0  end), 0) as '日销_有库存天数',
        sum(广告花费) as 广告花费,
        sum(广告订单量) as 广告订单量,
        sum(广告销售额) as 广告销售额,
        sum(广告点击量) as 广告点击量,
        sum(广告曝光量) as 广告曝光量,
        round(sum(广告花费)/nullif(sum(广告销售额),0), 2) as 'acos',
        round(sum(广告花费)/nullif(sum(销售额),0),2) as 'tacos',
        round(sum(广告点击量)/nullif(sum(广告曝光量),0), 2) as 'ctr'
      from etl_datasync.product_performance_90_days
      where seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
       and length(seller_sku_adj) between 5 and 10
      group by seller_name_new,
    seller_sku_adj,
    country_category,
    country,
    local_sku
    ),
     现价_listing as(
    select
        year(create_time) as dt_year,
        month(create_time) as dt_month,
        yearweek(create_time, 1) as dt_week,
        date(create_time) as dt_date,
        seller_name_new,
        seller_name,
        seller_sku,
        country_category,
        marketplace as country,
        price,
        org_currency_icon
    from etl_datasync.etl_dispose_lx_sales_mws_listing
    where date(create_time) = curdate()
),
 汇率 as (select *
              from dwd_datasync.lx_basic_currency
              where date = date_format(curdate(), '%Y-%m')),
现价 as (
select
    a.dt_year,
    a.dt_month,
    a.dt_week,
    a.dt_date,
    a.seller_name_new,
    a.seller_name,
    a.seller_sku,
    a.country_category,
    a.country,
    a.price,
    a.org_currency_icon,
    round(a.price * b.rate_org, 2)  as price_cny
from 现价_listing a
left join 汇率 b
on a.org_currency_icon = b.name),
限价 as(
select
    sku as local_sku,
    msku as seller_sku,
    store as seller_name_new,
    country,
    shipping_method,
    target_margin,
    case
            when country = '英国' then '英国站'
            when country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
            else '欧洲站'
        end as country_category,
    currency,
    tax_inclusive_price,
    tax_inclusive_price_noad,
    tax_inclusive_price_adj
from temporary_APP.yd_product_pricing_schedule
where date(create_time)=curdate()
and target_margin=0.35
and shipping_method='铁路'),
d as (
    select
        a.*,
        f.price as '现价',
        price_cny as '现价_人民币',
        f.org_currency_icon as '现价_币种',
        tax_inclusive_price as '限价',
        shipping_method as '运输方式',
        target_margin as '目标毛利率',
        tax_inclusive_price_noad as '限价_不包含广告',
        tax_inclusive_price_adj as '限价修正',
        c.total as '库存',
        c.total_price as '库存成本',
        c.available_total as '可售库存',
        c.available_price as '可售库存成本',
        c.afn_fulfillable_quantity as 'fba可售库存',
        c.reserved_fc_transfers as '待调仓库存',
        c.reserved_fc_processing as '调仓中库存',
        c.reserved_customerorders as '待发货库存',
        c.afn_unsellable_quantity as '不可售库存',
        c.afn_inbound_working_quantity as '计划入库库存',
        c.stock_up_num as '在途库存',
        c.afn_researching_quantity as '调查中库存',
        c.total_fulfillable_quantity as '总可用库存',
        b.local_quantity as '可售库存_本地库存',
        case
            when a.销量 > 0 or (coalesce(b.local_quantity, 0) + coalesce(c.total, 0)) > 0
                then '1'
            else '0'
        end as 筛选
    from 产品表现数据 a
    left join etl_datasync.month_end_data_补货建议 b
       on a.country_category = b.country_category
       and a.seller_sku_adj = b.seller_sku_adj
       and a.seller_name_new = b.seller_name_new
    left join etl_datasync.month_end_data_库存明细 c
       on a.country_category = c.country_category
       and a.seller_sku_adj = c.seller_sku_adj
       and a.seller_name_new = c.seller_name_new
    left join 现价 f
    on a.country_category = f.country_category
       and binary a.seller_sku_adj = binary f.seller_sku
       and a.seller_name_new = f.seller_name_new
        and a.country = f.country
    left join 限价 g
    on a.country_category = g.country_category
       and a.seller_sku_adj = g.seller_sku
       and a.seller_name_new = g.seller_name_new
       and a.country = g.country
       and a.local_sku = g.local_sku
)
select
    distinct
    concat(@start_date, '-', @end_date) as '统计周期',
    seller_name_new,
    seller_name,
    seller_sku_adj,
    country_category,
    country,
    local_sku,
    销量,
    销售额,
    销售额_不含税,
    订单毛利润,
    原订单毛利润,
    订单毛利率,
    case
        when 订单毛利率 >= 0.35 then '毛利率>0.35'
        when 订单毛利率>=0.25 and  订单毛利率<0.35 then '毛利率0.25-0.35'
        when 订单毛利率 >=0.15 and 订单毛利率 < 0.25 then '毛利率0.15-0.25'
        when 订单毛利率 >=0.1 and 订单毛利率 <0.15  then '毛利率0.1-0.15'
        when 订单毛利率 >=0 and 订单毛利率 <0.1  then '毛利率0.05-0.1'
        else '毛利率小于0' end as 毛利率分类,
    结算毛利润,
    筛选,
    现价_人民币,
    现价_币种,
    现价,
    限价,
    case when 现价>nullif(限价,0) then 1 else 0 end as 筛选_现价高于限价,
    运输方式,
    目标毛利率,
    限价_不包含广告,
    有库存的天数,
    abs(datediff(@start_date, @end_date))+1 as '统计天数',
    异常天数,
    case when abs(datediff(@start_date, @end_date))+1= 异常天数 then 1 else 0 end as 统计周期内是否全部异常,
    日销,
    日销_有库存天数,
    case when 日销_有库存天数<1  and 日销_有库存天数>0 then '日销销量<1'
    when 日销_有库存天数>=1 and 日销_有库存天数<5 then '日销销量1-5'
    when 日销_有库存天数>=5 then '日销销量大于5' else '日销销量0'
    end as 日销_有库存天数销量区间,
    case when 日销<1  and 日销>0 then '日销销量<1'
    when 日销>=1 and 日销<5 then '日销销量1-5'
    when 日销>=5 then '日销销量大于5' else '日销销量0'
    end as 日销销量区间,
    广告花费,
    广告订单量,
    广告销售额,
    广告销售额,
    广告点击量,
    广告曝光量,
    acos,
    tacos,
    ctr,
    库存 as fba总库存,
    库存成本 as fba总库存成本,
    可售库存 as fba可用库存,
    可售库存成本 as fba可用库存成本,
    fba可售库存 as fba可售库存,
    待调仓库存 as 待调仓,
    调仓中库存 as 调仓中,
    待发货库存 as 待发货,
    不可售库存 as 不可售库存,
    计划入库库存 as 计划入库,
    在途库存 as 实际在途,
    调查中库存 as 调查中,
    总可用库存 as 总可用库存,
    可售库存_本地库存 as fba可售库存_本地库存,
    case
     when (coalesce(可售库存_本地库存, 0) + coalesce(库存, 0)) > 0 and
          (销量= 0 or 有库存的天数 = 0) then '99999'
     when (coalesce(可售库存_本地库存, 0) + coalesce(库存, 0))> 0 and
          (销量> 0 and 有库存的天数 > 0)
         then round((可售库存_本地库存+ 库存) /
              日销_有库存天数,0)
     when (coalesce(可售库存_本地库存, 0) + coalesce(库存, 0)) = 0 then 0
     end as fba库存_本地库存可售天数    -- fba库存+本地库存可售天数
from d;





