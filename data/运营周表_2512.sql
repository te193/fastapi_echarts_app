-- 2512 api数据源
-- listing_产品管理-店铺-周维度
drop table if exists etl_datasync.ops_rpt_listing_prod_basic_data;
create table if not exists etl_datasync.ops_rpt_listing_prod_basic_data
with listing_产品基础数据 as (select distinct sml.create_time,                                                                                   -- 数据时间
                                              sml.seller_sku,                                                                                    -- msku
                                              sml.asin,                                                                                          -- asin
                                              sml.fnsku,                                                                                         -- fnsku
                                              sml.local_sku,                                                                                     -- sku
                                              sml.seller_name,                                                                                   -- 店铺
                                              sml.marketplace,                                                                                   -- 国家
                                              sml.local_name,                                                                                    -- 品名
                                              sml.status,                                                                                        -- 状态
                                              sml.seller_brand,                                                                                  -- 亚马逊品牌
                                              sml.global_tags,                                                                                   -- 标签
                                              sml.review_num,                                                                                    -- 评论数
                                              sml.last_star,                                                                                     -- 评分
                                              sml.currency_code,                                                                                 -- 币种
                                              sml.first_order_time,                                                                              -- 首单时间
                                              sml.small_rank,                                                                                    -- 小类排名
                                              sml.spu,                                                                                           -- spu
                                              sml.country_category,                                                                              -- 国家类别
                                              sml.seller_name_ue,                                                                                -- 店铺_ue
                                              sml.seller_name_new,                                                                               -- 店铺_新
                                              sml.country_code,                                                                                  -- 国家代码
                                              sml.org_currency_icon,                                                                             -- 原币种
                                              sml.price,                                                                                         -- 价格
                                              sml.principal,                                                                                     -- 负责人
                                              sml.sales_team_1,                                                                                  -- 运营团队
                                              plpi.tag_name,                                                                                     -- 产品标签
                                              plpi.brand_name,                                                                                   -- 品牌
                                              plpi.category_name,                                                                                -- 分类
                                              plpi.product_developer,                                                                            -- 开发人
                                              plpi.cg_price,                                                                                     -- 采购价格
                                              plpi.cg_box_pcs,                                                                                   -- 单箱数量
                                              plpi.cg_transport_costs,                                                                           -- 默认头程成本_含税
                                              count(case when sml.status = '在售' then 1 end)
                                                    over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku) as onsale_sites, -- 在售站点个数
                                              count(case when sml.status = '停售' then 1 end)
                                                    over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku) as unsale_sites, -- 停售站点个数
                                              max(sml.local_sku)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_sku,
                                              max(sml.fnsku)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_fnsku,
                                              max(sml.asin)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_asin,
                                              max(local_name)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_local_name,
                                              max(spu)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_spu,
                                              max(tag_name)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_tag_name,
                                              max(case
                                                      when plpi.tag_name = '2024 十月开发新品,emag平台产品'
                                                          then '2024 十月开发新品'
                                                      when plpi.tag_name = '2024 十一月开发新品,emag平台产品'
                                                          then '2024 十一月开发新品'
                                                      when plpi.tag_name = '2025 八月开发新品,2025 九月开发新品'
                                                          then '2025 八月开发新品'
                                                      else plpi.tag_name
                                                      end)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_product_dev_time,
                                              max(brand_name)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_brand_name,
                                              max(category_name)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_category_name,
                                              max(product_developer)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_product_developer,
                                              max(cg_box_pcs)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_cg_box_pcs,
                                              max(cg_price)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_cg_price,
                                              max(cg_transport_costs)
                                                  over (partition by sml.country_category,sml.seller_name_new,sml.seller_sku)   as max_cg_transport_costs

                              from etl_datasync.etl_dispose_lx_sales_mws_listing as sml
                                       left join etl_datasync.etl_dispose_lx_product_local_product_info as plpi
                                                 on sml.seller_sku = plpi.seller_sku
                                                     and sml.marketplace = plpi.country
                                                     and sml.seller_name_new = plpi.seller_name_new
                                                     and sml.local_sku = plpi.local_sku
                              where sml.seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'),
     汇率 as (select *
              from dwd_datasync.lx_basic_currency
              where date = date_format(curdate(), '%Y-%m'))
select lpd.*,
       round(lpd.price * hl.rate_org, 2)                                             as price_cny,
       round(avg(lpd.price * hl.rate_org)
                 over (partition by country_category,seller_name_new,seller_sku), 2) as avg_price_cny,
       max(case
               when onsale_sites = 0 then '停售中'
               else '在售中' end)
           over (partition by country_category,seller_name_new,seller_sku)           as sales_status,
       max(case
               when max_product_dev_time regexp '2027|2026|2025|2024 十月|2024 十一月|2024 十二月'
                   then '新品'
               else '老品' end)
           over (partition by country_category,seller_name_new,seller_sku)           as new_old_product -- 新老品区分
from listing_产品基础数据 as lpd
         left join 汇率 as hl
                   on lpd.org_currency_icon = hl.name;


-- FBA库存明细-店铺-周维度
drop table if exists etl_datasync.ops_weekly_rpt_fba_inv_detail_basic_data;
create table if not exists etl_datasync.ops_weekly_rpt_fba_inv_detail_basic_data
with inventory_value as (select distinct *
                         from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
                         where date(create_time) =
                               date_add(date_add(str_to_date(concat(yearweek(create_time, 1), '1'), '%X%V%w'),
                                                 interval -1 week), interval 6 day)
                            or date(create_time) = curdate()),
     month_end_data as (select year(iv.create_time)                                           as dt_year,
                               month(iv.create_time)                                          as dt_month,
                               yearweek(iv.create_time, 1)                                    as dt_week,
                               date(iv.create_time)                                           as create_time,
                               iv.country_category,
                               iv.seller_sku_adj,
                               iv.seller_name_new,
                               sum(iv.total)                                                  as total,
                               sum(iv.total_price)                                            as total_price,
                               sum(iv.available_total)                                        as available_total,
                               sum(iv.available_total_price)                                  as available_total_price,
                               sum(iv.afn_fulfillable_quantity)                               as afn_fulfillable_quantity,
                               sum(iv.afn_fulfillable_quantity_price)                         as afn_fulfillable_quantity_price,
                               sum(iv.reserved_fc_transfers)                                  as reserved_fc_transfers,
                               sum(iv.reserved_fc_transfers_price)                            as reserved_fc_transfers_price,
                               sum(iv.reserved_fc_processing)                                 as reserved_fc_processing,
                               sum(iv.reserved_fc_processing_price)                           as reserved_fc_processing_price,
                               sum(iv.reserved_customerorders)                                as reserved_customerorders,
                               sum(iv.reserved_customerorders_price)                          as reserved_customerorders_price,
                               sum(iv.afn_unsellable_quantity)                                as afn_unsellable_quantity,
                               sum(iv.afn_unsellable_quantity_price)                          as afn_unsellable_quantity_price,
                               sum(iv.afn_inbound_receiving_quantity)                         as afn_inbound_receiving_quantity,
                               sum(iv.afn_inbound_receiving_quantity_price)                   as afn_inbound_receiving_quantity_price,
                               sum(iv.stock_up_num)                                           as stock_up_num,
                               sum(iv.stock_up_num_price)                                     as stock_up_num_price,
                               sum(iv.afn_researching_quantity)                               as afn_researching_quantity,
                               sum(iv.afn_researching_quantity_price)                         as afn_researching_quantity_price,
                               max(iv.cg_price)                                               as cg_price,
                               max(iv.cg_transport_costs)                                     as cg_transport_costs,

                               -- 库龄分段
                               sum(iv.inv_age_0_to_30_days + iv.inv_age_31_to_60_days +
                                   iv.inv_age_61_to_90_days)                                  as inv_age_0_3_days,
                               sum(iv.inv_age_0_to_30_price + iv.inv_age_31_to_60_price +
                                   iv.inv_age_61_to_90_price)                                 as inv_age_0_3_price,
                               sum(iv.inv_age_91_to_180_days)                                 as inv_age_3_6_days,
                               sum(iv.inv_age_91_to_180_price)                                as inv_age_3_6_price,
                               sum(iv.inv_age_181_to_270_days)                                as inv_age_6_9_days,
                               sum(iv.inv_age_181_to_270_price)                               as inv_age_6_9_price,
                               sum(iv.inv_age_271_to_330_days + iv.inv_age_331_to_365_days)   as inv_age_9_12_days,
                               sum(iv.inv_age_271_to_330_price + iv.inv_age_331_to_365_price) as inv_age_9_12_price,
                               sum(iv.inv_age_365_plus_days)                                  as inv_age_over_12_days,
                               sum(iv.inv_age_365_plus_price)                                 as inv_age_over_12_price,

                               -- 低库龄数据（<=180天库龄）
                               sum(iv.inv_age_0_to_30_days + iv.inv_age_31_to_60_days +
                                   iv.inv_age_61_to_90_days + iv.inv_age_91_to_180_days)      as lowerlibrary_ages_days,
                               sum(iv.inv_age_0_to_30_price + iv.inv_age_31_to_60_price +
                                   iv.inv_age_61_to_90_price +
                                   iv.inv_age_91_to_180_price)                                as lowerlibrary_ages_price,

                               -- 超库龄数据（>180天库龄）
                               sum(iv.inv_age_181_to_270_days + iv.inv_age_271_to_330_days +
                                   iv.inv_age_331_to_365_days +
                                   iv.inv_age_365_plus_days)                                  as superlibrary_ages_days,
                               sum(iv.inv_age_181_to_270_price + iv.inv_age_271_to_330_price +
                                   iv.inv_age_331_to_365_price +
                                   iv.inv_age_365_plus_price)                                 as superlibrary_ages_price,

                               -- 超库龄数据（>90天库龄）
                               sum(iv.inv_age_91_to_180_days + iv.inv_age_181_to_270_days +
                                   iv.inv_age_271_to_330_days +
                                   iv.inv_age_331_to_365_days +
                                   iv.inv_age_365_plus_days)                                  as over_inv90_days,
                               sum(iv.inv_age_91_to_180_price + iv.inv_age_181_to_270_price +
                                   iv.inv_age_271_to_330_price +
                                   iv.inv_age_331_to_365_price +
                                   iv.inv_age_365_plus_price)                                 as over_inv90_price
                        from inventory_value iv
                        group by iv.create_time, iv.country_category, iv.seller_sku_adj, iv.seller_name_new)
select *,
       superlibrary_ages_price /
       nullif((lowerlibrary_ages_price + superlibrary_ages_price), 0) as superlibrary_proportion
from month_end_data
order by create_time desc;


-- 补货建议-店铺-周维度
drop table if exists etl_datasync.ops_weekly_rpt_replenish_sug_basic_data;
create table etl_datasync.ops_weekly_rpt_replenish_sug_basic_data as
with replenishment_value as (select distinct *
                             from etl_datasync.etl_dispose_lx_replenishment_suggest_restocking
                             where date(create_time) =
                                   date_add(date_add(str_to_date(concat(dt_week, '1'), '%X%V%w'),
                                                     interval -1 week), interval 6 day)
                                or date(create_time) = curdate()),
     month_end_data as (select dt_year,
                               yearweek(create_time, 1)           as dt_week,
                               create_time,
                               country_category,
                               seller_sku_adj,
                               seller_name_new,

                               -- 月末补货数据快照
                               max(sc_quantity_local_valid)       as sc_quantity_local_valid,
                               max(sc_quantity_purchase_shipping) as sc_quantity_purchase_shipping,
                               max(sc_quantity_purchase_plan)     as sc_quantity_purchase_plan,
                               max(sc_quantity_local_qc)          as sc_quantity_local_qc,

                               -- 库存周转相关
                               (max(sc_quantity_local_valid) +
                                max(sc_quantity_purchase_shipping) +
                                max(sc_quantity_purchase_plan) +
                                max(sc_quantity_local_qc))        as local_quantity

                        from replenishment_value
                        group by dt_year, dt_week, create_time, country_category, seller_sku_adj, seller_name_new
                        order by dt_week desc)
select *
from month_end_data;


-- FBA货件-店铺
drop table if exists etl_datasync.ops_rpt_fba_shipment_basic_data;
create table etl_datasync.ops_rpt_fba_shipment_basic_data as
select *,
       datediff(current_date, min_receiving_time) as days_since_launch,    -- 开售天数
       datediff(current_date, max_receiving_time) as days_latest_delivery, -- 货件最晚收货时间
       case
           when datediff(current_date, min_receiving_time) between 0 and 30 then '<=30天'
           when datediff(current_date, min_receiving_time) between 31 and 90 then '<=90天'
           when datediff(current_date, min_receiving_time) between 91 and 180 then '<=180'
           when datediff(current_date, min_receiving_time) > 180 then '>180天'
           end                                    as since_launch_range,   -- 开售时间段
       case
           when datediff(current_date, max_receiving_time) between 0 and 7 then '0-7天'
           when datediff(current_date, max_receiving_time) between 8 and 14 then '8-14天'
           when datediff(current_date, max_receiving_time) between 15 and 30 then '15-30天'
           when datediff(current_date, max_receiving_time) >= 30 then '>=30天'
           end                                    as delivery_time_range   -- 货件最晚收货时间段
from (select msku,
             seller_name_new,
             country_category,
             min(str_to_date(receiving_time, '%Y-%m-%d %H:%i:%s')) as min_receiving_time,
             max(str_to_date(receiving_time, '%Y-%m-%d %H:%i:%s')) as max_receiving_time,
             max(receiving_cnt)                                    as receiving_cnt
      from (select f.country_category,
                   f.store_name,
                   f.seller_name_new,
                   f.msku,
                   f.country,
                   case
                       when f.receiving_time = '' then null
                       else f.receiving_time
                       end as receiving_time,
                   f.asin,
                   f.parent_asin,
                   f.fnsku,
                   f.sku,
                   f.shipment_id,
                   f.quantity_shipped,
                   f.quantity_received,

                   r.receiving_cnt
            from etl_datasync.etl_dispose_lx_fba_shipment as f
                     left join (select msku,
                                       store_name,
                                       count(*) as receiving_cnt
                                from etl_datasync.etl_dispose_lx_fba_shipment
                                where receiving_time is not null
                                  and quantity_shipped <> 0
                                group by msku, store_name) as r
                               on f.msku = r.msku and f.store_name = r.store_name
            where f.receiving_time is not null
              and f.quantity_received <> 0) as a
      group by msku, seller_name_new, country_category) as b;


-- 物流天数-店铺-周维度
drop table if exists etl_datasync.ops_rpt_logi_est_days_data;
create table etl_datasync.ops_rpt_logi_est_days_data as
with 货件处理 as (select shipment_id,                              -- 货件单号
                         substring_index(seller, ' ', 1) as sname, -- 店铺
                         country,                                  -- 国家
                         msku,                                     -- MSKU
                         shipment_status                           -- 货件状态
                  from dwd_datasync.lx_fba_shipment
                  where shipment_status in ('WORKING', 'READY_TO_SHIP', 'SHIPPED', 'IN_TRANSIT')),
     发货单处理 as (select splb.shipment_id,           -- 货件单号
                           splb.sname,                 -- 店铺
                           splb.shipment_sn,           -- 发货单号
                           splb.msku,                  -- MSKU
                           spd.shipment_time,          -- 发货时间
                           spd.logistics_channel_name, -- 物流渠道
                           splb.remark,                -- 备注
                           splb.shipment_status        -- 货件状态
                    from dwd_datasync.lx_inbound_shipment_detail_ShangPinLieBiao as splb
                             left join dwd_datasync.lx_inbound_shipment_detail as spd
                                       on splb.shipment_sn = spd.shipment_sn
                    where splb.shipment_status in ('WORKING', 'READY_TO_SHIP', 'SHIPPED', 'IN_TRANSIT')),
     联结 as (select a.shipment_id,            -- 货件单号
                     a.sname,                  -- 店铺
                     a.country,                -- 国家
                     b.shipment_sn,            -- 发货单号
                     a.msku,
                     b.shipment_time,          -- 发货时间
                     b.logistics_channel_name, -- 物流渠道
                     b.remark,                 -- 货件备注
                     a.shipment_status,        -- 货件状态,
                     substring_index(a.sname, '-', 1)                         as seller_name_new,
                     case
                         when a.country = '英国' then '英国站'
                         when a.country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
                         else '欧洲站'
                         end                                                  as country_category,
                     min(b.shipment_time) over (partition by a.sname, a.MSKU) as earliest_ship_time,
                     case
                         when logistics_channel_name regexp '空' then '空运'
                         when logistics_channel_name regexp '铁' then '铁路'
                         when logistics_channel_name regexp ('海|航|卡派') then '海运'
                         end                                                     channel_abbrev,
                     case
                         when logistics_channel_name regexp '空' then 15
                         when logistics_channel_name regexp '铁' then 45
                         when logistics_channel_name regexp ('海|航|卡派') then 60
                         end                                                     logistics_est_days
              from 货件处理 as a
                       left join 发货单处理 as b
                                 on a.shipment_id = b.shipment_id and a.msku = b.msku and a.sname = b.sname)
select distinct seller_name_new,    -- 店铺
                country_category,   -- 国家类别
                msku,
                shipment_time,      -- 货件发货时间
                earliest_ship_time, -- 最早发货时间
                channel_abbrev,     -- 渠道简写
                logistics_est_days  -- 物流预计天数
from 联结
where sname not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy|hongyuanEU'
  and earliest_ship_time = shipment_time
  and earliest_ship_time is not null
  and channel_abbrev is not null;


-- 结算利润-店铺-周维度
drop table if exists etl_datasync.ops_weekly_rpt_settlement_profit_interim;
create table if not exists etl_datasync.ops_weekly_rpt_settlement_profit_interim
with 结算利润指标 as (select data_date,
                             country_category,
                             seller_name_new,
                             seller_sku_adj,
                             total_sales_amount,
                             gross_profit,
                             gross_profit_with_tax
                      from etl_datasync.etl_dispose_lx_statistics_profit_statistics_msku
                      where data_date >= date_sub(current_date, interval 90 day)
                        and store_name not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'),
     分段指标 as (select country_category,
                         seller_name_new,
                         seller_sku_adj,
                         date(curdate())                                                               as cur_date,   -- 当天时间
                         -- 销售额指标
                         sum(case
                                 when data_date >= curdate() - interval 30 day
                                     then total_sales_amount end)                                      as amount_30,  -- 近30天销售额
                         sum(case
                                 when data_date >= curdate() - interval 14 day
                                     then total_sales_amount end)                                      as amount_14,  -- 近14天销售额
                         sum(case
                                 when data_date >= curdate() - interval 7 day
                                     then total_sales_amount end)                                      as amount_7,   -- 近7天销售额
                         sum(case
                                 when data_date >= curdate() - interval 3 day
                                     then total_sales_amount end)                                      as amount_3,   -- 近3天销售额

                         -- 结算毛利润指标
                         sum(case when data_date >= curdate() - interval 30 day then gross_profit end) as gprofit_30, -- 近30天结算毛利润
                         sum(case when data_date >= curdate() - interval 14 day then gross_profit end) as gprofit_14, -- 近14天结算毛利润
                         sum(case when data_date >= curdate() - interval 7 day then gross_profit end)  as gprofit_7,  -- 近7天结算毛利润
                         sum(case when data_date >= curdate() - interval 3 day then gross_profit end)  as gprofit_3   -- 近3天结算毛利润

                  from 结算利润指标
                  group by country_category, seller_name_new, seller_sku_adj)
select a.*,
       b.cur_date,
       b.amount_30,
       b.amount_14,
       b.amount_7,
       b.amount_3,
       b.gprofit_30,
       b.gprofit_14,
       b.gprofit_7,
       b.gprofit_3,
       b.gprofit_30 / nullif(b.amount_30, 0) as gprofit_ratio_30,
       b.gprofit_14 / nullif(b.amount_14, 0) as gprofit_ratio_14,
       b.gprofit_7 / nullif(b.amount_7, 0)   as gprofit_ratio_7,
       b.gprofit_3 / nullif(b.amount_3, 0)   as gprofit_ratio_3
from 结算利润指标 as a
         left join 分段指标 as b
                   on a.country_category = b.country_category
                       and a.seller_name_new = b.seller_name_new
                       and a.seller_sku_adj = b.seller_sku_adj;

-- 店铺
drop table if exists etl_datasync.ops_weekly_rpt_settlement_profit_basic_data;
create table etl_datasync.ops_weekly_rpt_settlement_profit_basic_data as
with 周度数据表现 as (select date_sub(data_date, interval weekday(data_date) day)            as week_start,
                             date_add(date_sub(data_date, interval weekday(data_date) day), interval 6
                                      day)                                                   as week_end,
                             max(yearweek(data_date, 1))                                     as year_week,
                             country_category,
                             seller_name_new,
                             seller_sku_adj,
                             sum(total_sales_amount)                                         as total_sales_amount,
                             sum(gross_profit)                                               as gross_profit,
                             sum(gross_profit_with_tax)                                      as gross_profit_with_tax,
                             sum(gross_profit) / nullif(sum(total_sales_amount), 0)          as profit_margin,
                             sum(gross_profit_with_tax) / nullif(sum(total_sales_amount), 0) as profit_with_tax_margin

                      from etl_datasync.etl_dispose_lx_statistics_profit_statistics_msku
                      where data_date >= date_sub(current_date, interval 90 day)
                        and store_name not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
                      group by week_start, week_end, country_category, seller_name_new, seller_sku_adj
                      order by year_week desc, seller_sku_adj desc),
     完整周数 as (select *,
                         lag(w.year_week, 1)
                             over (partition by w.seller_sku_adj, w.seller_name_new, w.country_category order by w.year_week) as prev_week_date
                  from 周度数据表现 as w),
     上周利润 as (select *,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(gross_profit, 1) over w
                             end as last_week_gross_profit,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(profit_margin, 1) over w
                             end as last_week_profit_margin
                  from 完整周数
                  window w as ( partition by seller_sku_adj, seller_name_new, country_category order by year_week ))
select *,
       gross_profit - last_week_gross_profit as wk_profit_diff,
       case
           when profit_margin >= 0.15 then 'A'
           when profit_margin >= 0.10 and profit_margin < 0.15 then 'B'
           when profit_margin >= 0.05 and profit_margin < 0.10 then 'C'
           when profit_margin >= 0.00 and profit_margin < 0.05 then 'D'
           else 'E'
           end                               as abcd_category,
       case
           when profit_margin >= 0.15 then '>=15%'
           when profit_margin >= 0.10 and profit_margin < 0.15 then '10%-15%'
           when profit_margin >= 0.05 and profit_margin < 0.10 then '5%-10%'
           when profit_margin >= 0.00 and profit_margin < 0.05 then '0%-5%'
           else '<0%'
           end                               as gp_margin_range
from 上周利润;

-- 站点
drop table if exists etl_datasync.ops_weekly_rpt_site_settlement_profit_basic_data;
create table etl_datasync.ops_weekly_rpt_site_settlement_profit_basic_data as
with 周度数据表现 as (select date_sub(data_date, interval weekday(data_date) day)            as week_start,
                             date_add(date_sub(data_date, interval weekday(data_date) day), interval 6
                                      day)                                                   as week_end,
                             max(yearweek(data_date, 1))                                     as year_week,
                             country_category,
                             seller_name_new,
                             store_name,
                             country,
                             seller_sku_adj,
                             sum(total_sales_amount)                                         as total_sales_amount,
                             sum(gross_profit)                                               as gross_profit,
                             sum(gross_profit_with_tax)                                      as gross_profit_with_tax,
                             sum(gross_profit) / nullif(sum(total_sales_amount), 0)          as profit_margin,
                             sum(gross_profit_with_tax) / nullif(sum(total_sales_amount), 0) as profit_with_tax_margin

                      from etl_datasync.etl_dispose_lx_statistics_profit_statistics_msku
                      where data_date >= date_sub(current_date, interval 90 day)
                        and store_name not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
                      group by week_start, week_end, country_category, seller_name_new, store_name, country,
                               seller_sku_adj
                      order by year_week desc, seller_sku_adj desc),
     完整周数 as (select *,
                         lag(w.year_week, 1)
                             over (partition by w.seller_sku_adj, w.seller_name_new, w.store_name, w.country,w.country_category order by w.year_week) as prev_week_date
                  from 周度数据表现 as w),
     上周利润 as (select *,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(gross_profit, 1) over w
                             end as last_week_gross_profit,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(profit_margin, 1) over w
                             end as last_week_profit_margin
                  from 完整周数
                  window w as ( partition by seller_sku_adj, seller_name_new, store_name, country,country_category
                          order by year_week ))
select *,
       gross_profit - last_week_gross_profit as wk_profit_diff,
       case
           when profit_margin >= 0.15 then 'A'
           when profit_margin >= 0.10 and profit_margin < 0.15 then 'B'
           when profit_margin >= 0.05 and profit_margin < 0.10 then 'C'
           when profit_margin >= 0.00 and profit_margin < 0.05 then 'D'
           else 'E'
           end                               as abcd_category,
       case
           when profit_margin >= 0.15 then '>=15%'
           when profit_margin >= 0.10 and profit_margin < 0.15 then '10%-15%'
           when profit_margin >= 0.05 and profit_margin < 0.10 then '5%-10%'
           when profit_margin >= 0.00 and profit_margin < 0.05 then '0%-5%'
           else '<0%'
           end                               as gp_margin_range
from 上周利润;


-- 产品表现-店铺-周维度
drop table if exists etl_datasync.ops_weekly_rpt_prod_perf_interim;
create table if not exists etl_datasync.ops_weekly_rpt_prod_perf_interim
with 产品表现指标 as (select start_date,                            -- 开始时间
                             year(start_date)        as year_date,  -- 年
                             month(start_date)       as month_date, -- 月
                             yearweek(start_date, 1) as week_date,  -- 周
                             local_name,                            -- 品名
                             local_sku,                             -- sku
                             asin,                                  -- asin
                             seller_name,                           -- 店铺
                             seller_sku,                            -- msku
                             country,                               -- 国家
                             brands,                                -- 品牌
                             principal_names,                       -- 负责人
                             developer_names,                       -- 开发人
                             currency_icon,                         -- 币种符号
                             volume,                                -- 销量
                             order_items,                           -- 订单量
                             amount,                                -- 销售额
                             gross_profit,                          -- 结算毛利润
                             predict_gross_profit,                  -- 订单毛利润
                             spend,                                 -- 广告花费
                             ad_order_quantity,                     -- 广告订单量
                             ad_sales_amount,                       -- 广告销售额
                             return_goods_count,                    -- 退货量
                             return_count,                          -- 退款量
                             return_amount,                         -- 退款金额
                             clicks,                                -- 点击
                             impressions,                           -- 展示
                             net_amount,                            -- 净销售额
                             sessions_total,                        -- 会话数
                             afn_fulfillable_quantity,              -- fba可售
                             price,                                 -- 价格
                             source_rate,                           -- 汇率
                             `rank`,                                -- 小类排名
                             reviews_count,                         -- 评价数
                             avg_star,                              -- 评分
                             seller_sku_adj,                        -- msku调整
                             seller_name_new,                       -- 新店铺
                             country_category,                      -- 国家类别
                             org_currency_icon                      -- 原币种符号
                      from etl_datasync.etl_dispose_lx_statistics_product_performance_2026
                      where start_date >= date_sub(current_date, interval 90 day)
                        and seller_name not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'),
     分段销量 as (select country_category,
                         seller_name_new,
                         seller_sku_adj,
                         date(curdate())                                                          as cur_date,   -- 当天时间
                         -- 销量指标
                         sum(case when start_date >= curdate() - interval 90 day then volume end) as sales_90,   -- 近90天销量
                         sum(case when start_date >= curdate() - interval 60 day then volume end) as sales_60,   -- 近60天销量
                         sum(case when start_date >= curdate() - interval 30 day then volume end) as sales_30,   -- 近30天销量
                         sum(case when start_date >= curdate() - interval 14 day then volume end) as sales_14,   -- 近14天销量
                         sum(case when start_date >= curdate() - interval 7 day then volume end)  as sales_7,    -- 近7天销量
                         sum(case when start_date >= curdate() - interval 3 day then volume end)  as sales_3,    -- 近3天销量
                         -- 销售额指标
                         sum(case when start_date >= curdate() - interval 90 day then amount end) as amount_90,  -- 近90天销售额
                         sum(case when start_date >= curdate() - interval 60 day then amount end) as amount_60,  -- 近60天销售额
                         sum(case when start_date >= curdate() - interval 30 day then amount end) as amount_30,  -- 近30天销售额
                         sum(case when start_date >= curdate() - interval 14 day then amount end) as amount_14,  -- 近14天销售额
                         sum(case when start_date >= curdate() - interval 7 day then amount end)  as amount_7,   -- 近7天销售额
                         sum(case when start_date >= curdate() - interval 3 day then amount end)  as amount_3,   -- 近3天销售额
                         -- 订单毛利润指标
                         sum(case
                                 when start_date >= curdate() - interval 90 day
                                     then predict_gross_profit end)                               as pprofit_90, -- 近90天订单毛利润
                         sum(case
                                 when start_date >= curdate() - interval 60 day
                                     then predict_gross_profit end)                               as pprofit_60, -- 近60天订单毛利润
                         sum(case
                                 when start_date >= curdate() - interval 30 day
                                     then predict_gross_profit end)                               as pprofit_30, -- 近30天订单毛利润
                         sum(case
                                 when start_date >= curdate() - interval 14 day
                                     then predict_gross_profit end)                               as pprofit_14, -- 近14天订单毛利润
                         sum(case
                                 when start_date >= curdate() - interval 7 day
                                     then predict_gross_profit end)                               as pprofit_7,  -- 近7天订单毛利润
                         sum(case
                                 when start_date >= curdate() - interval 3 day
                                     then predict_gross_profit end)                               as pprofit_3   -- 近3天订单毛利润
                  from 产品表现指标
                  group by country_category, seller_name_new, seller_sku_adj)
select a.*,
       b.cur_date,
       b.sales_90,
       b.sales_60,
       b.sales_30,
       b.sales_14,
       b.sales_7,
       b.sales_3,
       b.amount_90,
       b.amount_60,
       b.amount_30,
       b.amount_14,
       b.amount_7,
       b.amount_3,
       b.pprofit_90,
       b.pprofit_60,
       b.pprofit_30,
       b.pprofit_14,
       b.pprofit_7,
       b.pprofit_3,
       b.pprofit_30 / nullif(b.amount_30, 0) as pprofit_ratio_30,
       b.pprofit_14 / nullif(b.amount_14, 0) as pprofit_ratio_14,
       b.pprofit_7 / nullif(b.amount_7, 0)   as pprofit_ratio_7,
       b.pprofit_3 / nullif(b.amount_3, 0)   as pprofit_ratio_3
from 产品表现指标 as a
         left join 分段销量 as b
                   on a.country_category = b.country_category
                       and a.seller_name_new = b.seller_name_new
                       and a.seller_sku_adj = b.seller_sku_adj;

-- 店铺
drop table if exists etl_datasync.ops_weekly_rpt_prod_perf_basic_data;
create table if not exists etl_datasync.ops_weekly_rpt_prod_perf_basic_data
with 每周afn天数 as (select date_sub(start_date, interval weekday(start_date) day)        as week_start,
                            date_add(date_sub(start_date, interval weekday(start_date) day), interval 6
                                     day)                                                 as week_end,
                            max(yearweek(start_date, 1))                                  AS year_week,
                            seller_name_new,
                            seller_sku_adj,
                            country_category,
                            count(start_date)                                             as week_days, -- 周天数
                            sum(case when afn_fulfillable_quantity > 0 then 1 else 0 end) as afn_fulfillable_quantity_not_zero_days
                     from (select start_date,
                                  week_date,
                                  seller_name_new,
                                  seller_sku_adj,
                                  country_category,
                                  max(afn_fulfillable_quantity) as afn_fulfillable_quantity
                           from etl_datasync.ops_weekly_rpt_prod_perf_interim
                           group by start_date, week_date, seller_name_new, seller_sku_adj, country_category) as a
                     group by week_start, week_end, seller_name_new, seller_sku_adj, country_category),
     周度数据表现 as (select date_sub(start_date, interval weekday(start_date) day)       as week_start,
                             date_add(date_sub(start_date, interval weekday(start_date) day), interval 6
                                      day)                                                as week_end,
                             max(yearweek(start_date, 1))                                 AS year_week,
                             max(local_name)                                              as local_name,
                             max(local_sku)                                               as local_sku,
                             max(asin)                                                    as asin,
                             seller_sku_adj,
                             seller_name_new,
                             country_category,
                             -- org_currency_icon,
                             -- source_rate,
                             max(brands)                                                  as brands,
                             max(principal_names)                                         as principal_names,
                             max(developer_names)                                         as developer_names,
                             max(currency_icon)                                           as currency_icon,

                             sum(volume)                                                  as volume,                   -- 销量
                             sum(order_items)                                             as order_items,              -- 订单量
                             sum(amount)                                                  as amount,                   -- 销售额
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
                             ) as amount_tax,                                                                          -- 销售额不含税
                             sum(gross_profit)                                            as gross_profit,             -- 结算毛利润
                             sum(predict_gross_profit)                                    as predict_gross_profit,     -- 订单毛利润
                             sum(case when volume =0 then 0 else predict_gross_profit end ) as predict_gross_profit_adj, -- 订单毛利润修正
                             sum(spend)                                                   as spend,                    -- 广告花费
                             sum(ad_order_quantity)                                       as ad_order_quantity,        -- 广告订单量
                             sum(ad_sales_amount)                                         as ad_sales_amount,          -- 广告销售额
                             sum(return_goods_count)                                      as return_goods_count,       -- 退货量
                             sum(return_count)                                            as return_count,             -- 退款量
                             sum(return_amount)                                           as return_amount,            -- 退款金额
                             sum(clicks)                                                  as clicks,                   -- 点击量
                             sum(impressions)                                             as impressions,              -- 展示量
                             sum(net_amount)                                              as net_amount,               -- 净销售额
                             sum(sessions_total)                                          as sessions_total,           -- 会话数
                             round(sum(abs(spend)) / nullif(sum(ad_sales_amount), 0), 4)  as acos,
                             round(sum(abs(clicks)) / nullif(sum(impressions), 0), 4)    as ctr,
                             round(sum(ad_order_quantity) / nullif(sum(clicks), 0), 4)    as ad_cvr,                   -- 广告转化率
                             round((sum(order_items) - sum(ad_order_quantity))
                                       / nullif(sum(sessions_total) - sum(clicks), 0), 4) as nature_cvr,               -- 自然转化率
                             round(sum(ad_order_quantity) / nullif(sum(order_items), 0),
                                   4)                                                     as ad_order_proportion,      -- 广告订单占比
                             round(sum(abs(spend)) / nullif(sum(net_amount), 0), 4)       as acoas,
                             round(sum(predict_gross_profit) / nullif(sum(amount), 0),
                                   4)                                                     as predict_profit_margin,    -- 订单毛利率
                             round(sum(return_goods_count) / nullif(sum(volume), 0),
                                   4)                                                     as return_proportion,        -- 退货率
                             round(sum(return_amount) / nullif(sum(amount), 0),
                                   4)                                                     as refund_proportion,        -- 退款率
                             max(afn_fulfillable_quantity)                                as afn_fulfillable_quantity, -- fba可售
                             group_concat(case
                                              when start_date =
                                                   date_add(date_add(str_to_date(concat(week_date, '1'), '%X%V%w'),
                                                                     interval -1 week), interval 6 day)
                                                  then concat(country, '-', price) end
                                          separator
                                          ',')                                            as concat_price,             -- 价格
                             group_concat(case
                                              when start_date =
                                                   date_add(date_add(str_to_date(concat(week_date, '1'), '%X%V%w'),
                                                                     interval -1 week), interval 6 day)
                                                  then concat(country, '-', `rank`) end
                                          separator
                                          ',')                                            as concat_rank,              -- 排名
                             group_concat(case
                                              when start_date =
                                                   date_add(date_add(str_to_date(concat(week_date, '1'), '%X%V%w'),
                                                                     interval -1 week), interval 6 day)
                                                  then concat(country, '-', reviews_count) end
                                          separator
                                          ',')                                            as concat_reviews_count,     -- 评价数
                             group_concat(case
                                              when start_date =
                                                   date_add(date_add(str_to_date(concat(week_date, '1'), '%X%V%w'),
                                                                     interval -1 week), interval 6 day)
                                                  then concat(country, '-', avg_star) end
                                          separator
                                          ',')                                            as concat_avg_star,          -- 评分
                             max(sales_30)                                                as sales_30,
                             max(sales_60)                                                as sales_60
                      from etl_datasync.ops_weekly_rpt_prod_perf_interim
                      group by week_start, week_end, seller_sku_adj, seller_name_new, country_category),
     完整周数 as (select w.*,
                         a.week_days,
                         a.afn_fulfillable_quantity_not_zero_days,
                         lag(w.year_week, 1)
                             over (partition by w.seller_sku_adj, w.seller_name_new, w.country_category order by w.year_week) as prev_week_date
                  from 周度数据表现 as w
                           left join 每周afn天数 as a
                                     on w.year_week = a.year_week
                                         and w.seller_sku_adj = a.seller_sku_adj
                                         and w.seller_name_new = a.seller_name_new
                                         and w.country_category = a.country_category
                  where w.seller_sku_adj is not null),
     上周销量 as (select wd.*,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(volume, 1) over w
                             end as last_week_volume,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(amount, 1) over w
                             end as last_week_amount,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(week_days, 1) over w
                             end as last_week_sales_days
                  from 完整周数 as wd
                  window w as ( partition by seller_sku_adj, seller_name_new, country_category order by year_week )),
     新增日销分类 as (select *,
                             volume - last_week_volume as volume_diff,
                             amount - last_week_amount as amount_diff,
                             predict_gross_profit_adj/nullif(amount_tax,0) as predict_profit_margin_adj,                -- 订单毛利率-不含税
                             case
                                 when week_days > 0 then round(volume / week_days, 2)
                                 end                   as avg_daily_volume,
                             case
                                 when round(volume / week_days, 2) >= 5 then '日销>=5'
                                 when round(volume / week_days, 2) >= 1 and round(volume / week_days, 2) < 5 then '日销1-5'
                                 when round(volume / week_days, 2) < 1  and round(volume / week_days, 2) > 0 then '日销0-1'
                                 when round(volume / week_days, 2) = 0 then '日销0'
                                 else ''
                                 end                   as avg_daily_volume_category,
                             case
                                 when round(last_week_volume / last_week_sales_days, 2) >= 5 then '日销>=5'
                                 when round(last_week_volume / last_week_sales_days, 2) >= 1 and
                                      round(last_week_volume / last_week_sales_days, 2) < 5
                                     then '日销1-5'
                                 when round(last_week_volume / last_week_sales_days, 2) < 1  and
                                      round(last_week_volume / last_week_sales_days, 2) > 0
                                      then '日销0-1'
                                 when round(last_week_volume / last_week_sales_days, 2) = 0 then '日销0'
                                 else ''
                                 end                   as last_week_avg_daily_volume_category
                      from 上周销量)
select *,
       case
           when predict_profit_margin < 0 or predict_profit_margin is null then 'E'
           when avg_daily_volume < 1 then 'D'
           when avg_daily_volume >= 1 then
               case
                   when predict_profit_margin >= 0.20 then 'A'
                   when predict_profit_margin >= 0.15 and predict_profit_margin < 0.20 then 'B'
                   when predict_profit_margin >= 0.10 and predict_profit_margin < 0.15 then 'C'
                   else 'D'
                   end
           end as predict_abcd_category,
       case
           when predict_profit_margin_adj >= 0.35 then '毛利率>0.35'
           when predict_profit_margin_adj>=0.25 and  predict_profit_margin_adj<0.35 then '毛利率0.25-0.35'
           when predict_profit_margin_adj >=0.15 and predict_profit_margin_adj < 0.25 then '毛利率0.15-0.25'
           when predict_profit_margin_adj >=0.1 and predict_profit_margin_adj <0.15  then '毛利率0.1-0.15'
           when predict_profit_margin_adj >=0 and predict_profit_margin_adj <0.1  then '毛利率0.05-0.1'
           else '毛利率小于0' end as profit_margin_category
from 新增日销分类;

-- 站点
drop table if exists etl_datasync.ops_weekly_rpt_site_prod_perf_basic_data;
create table if not exists etl_datasync.ops_weekly_rpt_site_prod_perf_basic_data
with 每周afn天数 as (select date_sub(start_date, interval weekday(start_date) day)        as week_start,
                            date_add(date_sub(start_date, interval weekday(start_date) day), interval 6
                                     day)                                                 as week_end,
                            max(yearweek(start_date, 1))                                  AS year_week,
                            seller_name_new,
                            seller_sku_adj,
                            country_category,
                            count(start_date)                                             as week_days, -- 周天数
                            sum(case when afn_fulfillable_quantity > 0 then 1 else 0 end) as afn_fulfillable_quantity_not_zero_days
                     from (select start_date,
                                  week_date,
                                  seller_name_new,
                                  seller_sku_adj,
                                  country_category,
                                  max(afn_fulfillable_quantity) as afn_fulfillable_quantity
                           from etl_datasync.ops_weekly_rpt_prod_perf_interim
                           group by start_date, week_date, seller_name_new, seller_sku_adj, country_category) as a
                     group by week_start, week_end, seller_name_new, seller_sku_adj, country_category),
     周度数据表现 as (select date_sub(start_date, interval weekday(start_date) day)       as week_start,
                             date_add(date_sub(start_date, interval weekday(start_date) day), interval 6
                                      day)                                                as week_end,
                             max(yearweek(start_date, 1))                                 AS year_week,
                             max(local_name)                                              as local_name,
                             max(local_sku)                                               as local_sku,
                             max(asin)                                                    as asin,
                             seller_sku_adj,
                             seller_name,
                             seller_name_new,
                             country,
                             country_category,
                             -- org_currency_icon,
                             -- source_rate,
                             max(brands)                                                  as brands,
                             max(principal_names)                                         as principal_names,
                             max(developer_names)                                         as developer_names,
                             max(currency_icon)                                           as currency_icon,

                             sum(volume)                                                  as volume,                   -- 销量
                             sum(order_items)                                             as order_items,              -- 订单量
                             sum(amount)                                                  as amount,                   -- 销售额
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
                             ) as amount_tax,                                                                          -- 销售额不含税
                             sum(gross_profit)                                            as gross_profit,             -- 结算毛利润
                             sum(predict_gross_profit)                                    as predict_gross_profit,     -- 订单毛利润
                             sum(case when volume =0 then 0 else predict_gross_profit end ) as predict_gross_profit_adj, -- 订单毛利润修正
                             sum(spend)                                                   as spend,                    -- 广告花费
                             sum(ad_order_quantity)                                       as ad_order_quantity,        -- 广告订单量
                             sum(ad_sales_amount)                                         as ad_sales_amount,          -- 广告销售额
                             sum(return_goods_count)                                      as return_goods_count,       -- 退货量
                             sum(return_count)                                            as return_count,             -- 退款量
                             sum(return_amount)                                           as return_amount,            -- 退款金额
                             sum(clicks)                                                  as clicks,                   -- 点击量
                             sum(impressions)                                             as impressions,              -- 展示量
                             sum(net_amount)                                              as net_amount,               -- 净销售额
                             sum(sessions_total)                                          as sessions_total,           -- 会话数
                             round(sum(abs(spend)) / nullif(sum(ad_sales_amount), 0), 4)  as acos,
                             round(sum(abs(clicks)) / nullif(sum(impressions), 0), 4)     as ctr,
                             round(sum(ad_order_quantity) / nullif(sum(clicks), 0), 4)    as ad_cvr,                   -- 广告转化率
                             round((sum(order_items) - sum(ad_order_quantity))
                                       / nullif(sum(sessions_total) - sum(clicks), 0), 4) as nature_cvr,               -- 自然转化率
                             round(sum(ad_order_quantity) / nullif(sum(order_items), 0),
                                   4)                                                     as ad_order_proportion,      -- 广告订单占比
                             round(sum(abs(spend)) / nullif(sum(net_amount), 0), 4)       as acoas,
                             round(sum(predict_gross_profit) / nullif(sum(amount), 0),
                                   4)                                                     as predict_profit_margin,    -- 订单毛利率
                             round(sum(return_goods_count) / nullif(sum(volume), 0),
                                   4)                                                     as return_proportion,        -- 退货率
                             round(sum(return_amount) / nullif(sum(amount), 0),
                                   4)                                                     as refund_proportion,        -- 退款率
                             max(afn_fulfillable_quantity)                                as afn_fulfillable_quantity, -- fba可售
                             group_concat(case
                                              when start_date =
                                                   date_add(date_add(str_to_date(concat(week_date, '1'), '%X%V%w'),
                                                                     interval -1 week), interval 6 day)
                                                  then price end
                                          separator
                                          ',')                                            as concat_price,             -- 价格
                             group_concat(case
                                              when start_date =
                                                   date_add(date_add(str_to_date(concat(week_date, '1'), '%X%V%w'),
                                                                     interval -1 week), interval 6 day)
                                                  then `rank` end
                                          separator
                                          ',')                                            as concat_rank,              -- 排名
                             group_concat(case
                                              when start_date =
                                                   date_add(date_add(str_to_date(concat(week_date, '1'), '%X%V%w'),
                                                                     interval -1 week), interval 6 day)
                                                  then reviews_count end
                                          separator
                                          ',')                                            as concat_reviews_count,     -- 评论数
                             group_concat(case
                                              when start_date =
                                                   date_add(date_add(str_to_date(concat(week_date, '1'), '%X%V%w'),
                                                                     interval -1 week), interval 6 day)
                                                  then avg_star end
                                          separator
                                          ',')                                            as concat_avg_star,          -- 评分
                             max(sales_30)                                                as sales_30,
                             max(sales_60)                                                as sales_60
                      from etl_datasync.ops_weekly_rpt_prod_perf_interim
                      group by week_start, week_end, seller_sku_adj, seller_name_new, seller_name, country,
                               country_category),
     完整周数 as (select w.*,
                         a.week_days,
                         a.afn_fulfillable_quantity_not_zero_days,
                         lag(w.year_week, 1)
                             over (partition by w.seller_sku_adj, w.seller_name_new,w.seller_name,w.country, w.country_category order by w.year_week) as prev_week_date
                  from 周度数据表现 as w
                           left join 每周afn天数 as a
                                     on w.year_week = a.year_week
                                         and w.seller_sku_adj = a.seller_sku_adj
                                         and w.seller_name_new = a.seller_name_new
                                         and w.country_category = a.country_category
                  where w.seller_sku_adj is not null),
     上周销量 as (select wd.*,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(volume, 1) over w
                             end as last_week_volume,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(amount, 1) over w
                             end as last_week_amount,
                         case
                             when prev_week_date is null or year_week - prev_week_date != 1 then null
                             else lag(week_days, 1) over w
                             end as last_week_sales_days
                  from 完整周数 as wd
                  window w as ( partition by seller_sku_adj, seller_name_new, seller_name,country, country_category
                          order by year_week )),
     新增日销分类 as (select *,
                             volume - last_week_volume as volume_diff,
                             amount - last_week_amount as amount_diff,
                             predict_gross_profit_adj/nullif(amount_tax,0) as predict_profit_margin_adj,                -- 订单毛利率-不含税
                             case
                                 when week_days > 0 then round(volume / week_days, 2)
                                 end                   as avg_daily_volume,
                             case
                                 when round(volume / week_days, 2) >= 5 then '日销>=5'
                                 when round(volume / week_days, 2) >= 1 and round(volume / week_days, 2) < 5 then '日销1-5'
                                 when round(volume / week_days, 2) < 1  and round(volume / week_days, 2) > 0 then '日销0-1'
                                 when round(volume / week_days, 2) = 0 then '日销0'
                                 else ''
                                 end                   as avg_daily_volume_category,
                             case
                                 when round(last_week_volume / last_week_sales_days, 2) >= 5 then '日销>=5'
                                 when round(last_week_volume / last_week_sales_days, 2) >= 1 and
                                      round(last_week_volume / last_week_sales_days, 2) < 5
                                     then '日销1-5'
                                 when round(last_week_volume / last_week_sales_days, 2) < 1  and
                                      round(last_week_volume / last_week_sales_days, 2) > 0
                                     then '日销0-1'
                                 when round(last_week_volume / last_week_sales_days, 2) = 0 then '日销0'
                                 else ''
                                 end                   as last_week_avg_daily_volume_category
                      from 上周销量)
select *,
       case
           when predict_profit_margin < 0 or predict_profit_margin is null then 'E'
           when avg_daily_volume < 1 then 'D'
           when avg_daily_volume >= 1 then
               case
                   when predict_profit_margin >= 0.20 then 'A'
                   when predict_profit_margin >= 0.15 and predict_profit_margin < 0.20 then 'B'
                   when predict_profit_margin >= 0.10 and predict_profit_margin < 0.15 then 'C'
                   else 'D'
                   end
           end as predict_abcd_category,
       case
           when predict_profit_margin_adj >= 0.35 then '毛利率>0.35'
           when predict_profit_margin_adj>=0.25 and  predict_profit_margin_adj<0.35 then '毛利率0.25-0.35'
           when predict_profit_margin_adj >=0.15 and predict_profit_margin_adj < 0.25 then '毛利率0.15-0.25'
           when predict_profit_margin_adj >=0.1 and predict_profit_margin_adj <0.15  then '毛利率0.1-0.15'
           when predict_profit_margin_adj >=0 and predict_profit_margin_adj <0.1  then '毛利率0.05-0.1'
           else '毛利率小于0' end as profit_margin_category
from 新增日销分类;


-- --------------------------------- 店铺组合 ------------------------------------
select yearweek(date_sub(date_sub(curdate(), interval weekday(curdate()) day), interval 7 day), 1);
select yearweek(date_sub(curdate(), interval 1 week), 1);
set @s_week = yearweek(date_sub(curdate(), interval 1 week), 1);
# drop table if exists dws_datasync.ops_weekly_rpt_prod_perf_data_2026;
# create table if not exists dws_datasync.ops_weekly_rpt_prod_perf_data_2026 as
# insert into dws_datasync.ops_weekly_rpt_prod_perf_data_2026
with 产品表现_店铺_周维度 as (select *
                              from etl_datasync.ops_weekly_rpt_prod_perf_basic_data
                              where length(seller_sku_adj) between 5 and 10),
     listing_产品管理_店铺 as (select distinct create_time,
                                               seller_sku,
                                               country_category,
                                               seller_name_ue,
                                               seller_name_new,
                                               principal,
                                               sales_team_1,
                                               onsale_sites,
                                               unsale_sites,
                                               sales_status,
                                               avg_price_cny,
                                               group_concat(distinct global_tags separator ',') as global_tags,
                                               group_concat(distinct
                                                            case
                                                                when global_tags regexp '清货-正常' then '清货-正常'
                                                                when global_tags regexp '清货-紧急'
                                                                    then '清货-紧急' end
                                                            separator ',')                      as clearance_tags,
                                               group_concat(distinct
                                                            case
                                                                when global_tags regexp '不合规-'
                                                                    then regexp_substr(global_tags, '不合规-[^,|，]+') end
                                                            separator
                                                            ',')                                as non_compliant_tags,
                                               max_sku,
                                               max_local_name,
                                               max_spu,
                                               max_tag_name,
                                               max_product_dev_time,
                                               max_brand_name,
                                               max_category_name,
                                               max_product_developer,
                                               max_cg_box_pcs,
                                               max_cg_price,
                                               max_cg_transport_costs,
                                               new_old_product
                               from etl_datasync.ops_rpt_listing_prod_basic_data
                               where length(seller_sku) between 5 and 10
                               group by create_time,
                                        seller_sku,
                                        country_category,
                                        seller_name_ue,
                                        seller_name_new,
                                        principal,
                                        sales_team_1,
                                        onsale_sites,
                                        unsale_sites,
                                        sales_status,
                                        avg_price_cny,
                                        max_sku,
                                        max_local_name,
                                        max_spu,
                                        max_tag_name,
                                        max_product_dev_time,
                                        max_brand_name,
                                        max_category_name,
                                        max_product_developer,
                                        max_cg_box_pcs,
                                        max_cg_price,
                                        max_cg_transport_costs,
                                        new_old_product),
     FBA货件_店铺 as (select *
                      from etl_datasync.ops_rpt_fba_shipment_basic_data),
     结算利润_店铺_周维度 as (select *
                              from etl_datasync.ops_weekly_rpt_settlement_profit_basic_data),
     季度分类_店铺 as (select *
                       from etl_datasync.ops_quarter_rpt_prod_perf_basic_data),
     FBA库存明细_店铺_周维度 as (select *
                                 from etl_datasync.ops_weekly_rpt_fba_inv_detail_basic_data),
     补货建议_店铺_周维度 as (select *
                              from etl_datasync.ops_weekly_rpt_replenish_sug_basic_data),
     物流天数_店铺 as (select *
                       from etl_datasync.ops_rpt_logi_est_days_data),
     上月订单利润分类_店铺 as (select y_month,
                                      country_category,
                                      seller_name_new,
                                      seller_sku_adj,
                                      asin,
                                      local_sku,
                                      predict_profit_margin as pre_1m_predict_profit_margin,
                                      predict_abcd_category as pre_1m_predict_abcd_category
                               from etl_datasync.ops_monthly_rpt_prod_perf_basic_data
                               where y_month = date_format(date_sub(curdate()
                                                               , interval 1 month)
                                   , '%Y-%m')),
     上周筛选数据 as (select year_week,
                             country_category,
                             seller_name_new,
                             seller_sku_adj,
                             max_sku,
                             filtrate as last_week_filtrate
                      from dws_datasync.ops_weekly_rpt_prod_perf_data_2026
                      where year_week = yearweek(date_sub(curdate(), interval 2 week), 1)),
     周度数据表现 as (select ppbd.year_week,                                                                                         --  周
                             ppbd.week_start,                                                                                        -- 周最小日期
                             ppbd.week_end,                                                                                          -- 周最大日期
                             case
                                 when volume > 0 or (coalesce(rbd.local_quantity, 0) + coalesce(fbd.total, 0)) > 0
                                     then '1'
                                 else '0'
                                 end                                                                as filtrate,
                             coalesce(last_week_filtrate, 0)                                        as last_week_filtrate,
                             ppbd.country_category,                                                                                  -- 国家类别
                             ppbd.seller_name_new,                                                                                   -- 新店铺
                             ppbd.seller_sku_adj,                                                                                    -- msku
                             lpbd.sales_team_1,                                                                                      -- 运营团队
                             lpbd.principal,                                                                                         -- 负责人
                             lpbd.global_tags,                                                                                       -- listing标签
                             lpbd.clearance_tags,                                                                                    -- 清货标签
                             lpbd.non_compliant_tags,                                                                                -- 不合规标签
                             lpbd.max_spu,                                                                                           -- spu
                             lpbd.max_sku,                                                                                           -- sku
                             lpbd.max_local_name,                                                                                    -- 品名
                             lpbd.max_category_name,                                                                                 -- 分类
                             lpbd.max_brand_name,                                                                                    -- 品牌
                             lpbd.new_old_product,                                                                                   -- 新老品
                             lpbd.max_product_dev_time,                                                                              -- 产品开发时间
                             lpbd.avg_price_cny,                                                                                     -- 平均售价cny
                             lpbd.onsale_sites,                                                                                      -- 在数站点个数
                             lpbd.unsale_sites,                                                                                      -- 停售站点个数
                             lpbd.sales_status,                                                                                      -- 销售状态
                             ppbd.avg_daily_volume_category,                                                                         -- 本周日均销量分类
                             ppbd.last_week_avg_daily_volume_category,                                                               -- 上周日均销量分类
                             coalesce(spbd.abcd_category, 'E')                                      as abcd_category,                -- 本周结算abcd分类
                             spbd.gp_margin_range,                                                                                   -- 本周结算毛利率区间
                             qbd.pre_2q_predict_abcd_category,                                                                       -- 前2个季度订单利润分类
                             qbd.pre_1q_predict_abcd_category,                                                                       -- 前1个季度订单利润分类
                             qbd.category_changes,                                                                                   -- 季度分类变化
                             coalesce(ppbd.predict_abcd_category, 'E')                              as predict_abcd_category,        -- 本周订单利润分类
                             coalesce(ubd.pre_1m_predict_abcd_category, 'E')                        as pre_1m_predict_abcd_category, -- 前1个月订单利润分类
                             case
                                 when avg_daily_volume >= 1 and predict_profit_margin >= 0.10 then 0
                                 else 1
                                 end                                                                as is_predict_abc,               -- 本周订单分类异常判断

                             lpbd.max_tag_name,                                                                                      -- 标签
                             lpbd.max_cg_box_pcs,                                                                                    -- 单箱数量
                             lpbd.max_cg_price,                                                                                      -- 采购单价
                             lpbd.max_cg_transport_costs,                                                                            -- 头程运费
                             fsbd.receiving_cnt,                                                                                     -- 货件接收次数
                             fsbd.min_receiving_time,                                                                                -- 最小货件接收时间
                             fsbd.days_since_launch,                                                                                 -- 开售天数
                             fsbd.since_launch_range,                                                                                -- 开售天数区间
                             fsbd.max_receiving_time,                                                                                -- 最大货件接收时间
                             fsbd.days_latest_delivery,                                                                              -- 货件最晚发货天数
                             fsbd.delivery_time_range,                                                                               -- 货件最晚发货时间区间
                             case
                                 when new_old_product = '新品' and days_latest_delivery >= 90
                                     and receiving_cnt <= 1 then '新品未补货'
                                 else '已补货'
                                 end                                                                as new_is_replenishment,         -- 新品是否补货
                             ppbd.concat_price,                                                                                      -- 国家_价格
                             ppbd.concat_rank,                                                                                       -- 国家_排名
                             ppbd.concat_reviews_count,                                                                              -- 国家_评论数
                             ppbd.concat_avg_star,                                                                                   -- 国家_评分
                             ppbd.week_days,                                                                                         -- 周实际天数
                             ppbd.afn_fulfillable_quantity_not_zero_days,                                                            -- 可售库存非零天数
                             ppbd.avg_daily_volume,                                                                                  -- 日均销量
                             ppbd.volume,                                                                                            -- 销量
                             ppbd.last_week_volume,                                                                                  -- 上周销量
                             ppbd.volume_diff,                                                                                       -- 销量差值
                             row_number() over (partition by ppbd.year_week, lpbd.sales_team_1
                                 order by ppbd.volume_diff)                                         as rk_volume_diff,               -- 销量差值排序
                             ppbd.amount,                                                                                            -- 销售额
                             ppbd.amount_tax,                                                                                        -- 销售额不含税
                             ppbd.last_week_amount,                                                                                  -- 上周销售额
                             ppbd.amount_diff,                                                                                       -- 销售额差值
                             ppbd.net_amount,                                                                                        -- 净销售额
                             ppbd.order_items,                                                                                       -- 订单量
                             spbd.total_sales_amount,                                                                                -- 结算销售额
                             spbd.gross_profit,                                                                                      -- 结算毛利润
                             spbd.last_week_gross_profit,                                                                            -- 上周结算毛利润
                             spbd.wk_profit_diff,                                                                                    -- 周利润差值
                             spbd.profit_margin,                                                                                     -- 结算毛利率
                             ppbd.predict_gross_profit,                                                                              -- 订单毛利润
                             ppbd.predict_gross_profit_adj,                                                                          -- 订单毛利润（修正）
                             ppbd.predict_profit_margin,                                                                             -- 订单毛利率

#        spbd.gross_profit_with_tax,                  -- 含税结算毛利润
#        spbd.profit_with_tax_margin,                 -- 含税结算毛利率
#        spbd.last_week_profit_margin,                -- 上周结算毛利率
#        ppbd.gross_profit,                           -- 结算毛利润
                             ppbd.return_goods_count,                                                                                -- 退货量
                             ppbd.return_amount,                                                                                     -- 退款金额
                             ppbd.return_proportion,                                                                                 -- 退货率
                             ppbd.refund_proportion,                                                                                 -- 退款率
                             ppbd.spend,                                                                                             -- 广告花费
                             ppbd.acos,
                             ppbd.acoas,
                             ppbd.ctr,
                             ppbd.ad_sales_amount,                                                                                   -- 广告销售额,
                             ppbd.ad_order_quantity,                                                                                 -- 广告订单量
                             ppbd.ad_order_proportion,                                                                               -- 广告订单占比
                             ppbd.ad_cvr,                                                                                            -- 广告cvr
                             ppbd.impressions,                                                                                       -- 展示
                             ppbd.clicks,                                                                                            -- 点击
                             ppbd.sessions_total,                                                                                    -- 会话数
                             ppbd.nature_cvr,                                                                                        -- 自然cvr
                             fbd.total,                                                                                              -- 总库存
                             fbd.total_price,                             -- 总库存_成本
                             fbd.available_total,                                                                                    -- 可用库存
#        fbd.available_total_price,                   -- 可用库存_成本
                             fbd.afn_fulfillable_quantity,                                                                           -- FBA可售
#        fbd.afn_fulfillable_quantity_price,          -- FBA可售_成本
                             fbd.reserved_fc_transfers,                                                                              -- 待调仓
#        fbd.reserved_fc_transfers_price,             -- 待调仓_成本
                             fbd.reserved_fc_processing,                                                                             -- 调仓中
#        fbd.reserved_fc_processing_price,            -- 调仓中_成本
                             fbd.reserved_customerorders,                                                                            -- 待发货
#        fbd.reserved_customerorders_price,           -- 待发货_成本
                             fbd.afn_unsellable_quantity,                                                                            -- 不可售
#        fbd.afn_unsellable_quantity_price,           -- 不可售_成本
                             fbd.afn_inbound_receiving_quantity,                                                                     -- 待入库
#        fbd.afn_inbound_receiving_quantity_price,    -- 待入库_成本
                             fbd.stock_up_num,                                                                                       -- 实际在途
#        fbd.stock_up_num_price,                      -- 实际在途_成本
                             fbd.afn_researching_quantity,                                                                           -- 调查中
#        fbd.afn_researching_quantity_price,          -- 调查中_成本
                             rbd.sc_quantity_local_valid,                                                                            -- 本地可用
                             rbd.sc_quantity_purchase_shipping,                                                                      -- 待交付
                             rbd.sc_quantity_purchase_plan,                                                                          -- 采购计划
                             rbd.sc_quantity_local_qc,                                                                               -- 待检待上架量
                             rbd.local_quantity,                                                                                     -- 本地仓库存
                             (lpbd.max_cg_price + lpbd.max_cg_transport_costs) * rbd.local_quantity as local_cost,                   -- 本地仓成本
                             fbd.available_total_price,                                                                              -- 可用库存_成本
                             coalesce(rbd.local_quantity + fbd.total, 0)                            as fba_local_quantity,           -- fba库存+本地库存
                             (lpbd.max_cg_price + lpbd.max_cg_transport_costs)
                                 * rbd.local_quantity +
                             fbd.total_price                                                        as fba_local_cost,               -- fba库存成本+本地库存成本
                             coalesce(ppbd.sales_30, 0)                                             as sales_30,                     -- 30天销量,
                             coalesce(ppbd.sales_60, 0)                                             as sales_60,                     -- 60天销量
                             fbd.available_total / nullif(ppbd.sales_30, 0)                         as amz_inv_sales_ratio,          -- 在亚马逊库销比
                             (rbd.local_quantity + fbd.total) / nullif(ppbd.sales_30, 0)            as fba_local_inv_sales_ratio,    -- fba_本地库销比
                             case
                                 when (coalesce(rbd.local_quantity, 0) + coalesce(fbd.total, 0)) > 0 and
                                      (ppbd.volume = 0 or ppbd.afn_fulfillable_quantity_not_zero_days = 0) then '99999'
                                 when (coalesce(rbd.local_quantity, 0) + coalesce(fbd.total, 0)) > 0 and
                                      (ppbd.volume > 0 and ppbd.afn_fulfillable_quantity_not_zero_days > 0)
                                     then (rbd.local_quantity + fbd.total) /
                                          (ppbd.volume / ppbd.afn_fulfillable_quantity_not_zero_days)
                                 when (coalesce(rbd.local_quantity, 0) + coalesce(fbd.total, 0)) = 0 then 0
                                 end                                                                as fba_local_salable_days,       -- fba库存+本地库存可售天数
#                              (rbd.local_quantity + fbd.total) /
#                              nullif(ppbd.volume / nullif(ppbd.afn_fulfillable_quantity_not_zero_days, 0),
#                                     0)                                                              as fba_local_salable_days,       -- fba库存+本地库存可售天数
                             case
                                 when fbd.available_total > 0 and
                                      (ppbd.volume = 0 or ppbd.afn_fulfillable_quantity_not_zero_days = 0)
                                     then '99999'
                                 when fbd.available_total > 0 and
                                      (ppbd.volume > 0 and ppbd.afn_fulfillable_quantity_not_zero_days > 0)
                                     then fbd.available_total /
                                          (ppbd.volume / ppbd.afn_fulfillable_quantity_not_zero_days)
                                 when fbd.available_total = 0 then 0
                                 end                                                                as available_salable_days,       -- 可用库存可售天数
#                              fbd.available_total /
#                              nullif(ppbd.volume / nullif(ppbd.afn_fulfillable_quantity_not_zero_days, 0),
#                                     0)                                                              as available_salable_days,       -- 可用库存可售天数
                             coalesce(fbd.inv_age_0_3_days, 0)                                      as inv_age_0_3_days,             -- 库龄0-3月
                             coalesce(fbd.inv_age_0_3_price, 0)                                     as inv_age_0_3_price,            -- 库龄0-3月_成本,
                             coalesce(fbd.inv_age_3_6_days, 0)                                      as inv_age_3_6_days,             -- 库龄3-6月
                             coalesce(fbd.inv_age_3_6_price, 0)                                     as inv_age_3_6_price,            -- 库龄3-6月_成本,
                             coalesce(fbd.inv_age_6_9_days, 0)                                      as inv_age_6_9_days,             -- 库龄6-9月
                             coalesce(fbd.inv_age_6_9_price, 0)                                     as inv_age_6_9_price,            -- 库龄6-9月_成本,
                             coalesce(fbd.inv_age_9_12_days, 0)                                     as inv_age_9_12_days,            -- 库龄9-12月
                             coalesce(fbd.inv_age_9_12_price, 0)                                    as inv_age_9_12_price,           -- 库龄9-12月_成本,
                             coalesce(fbd.inv_age_over_12_days, 0)                                  as inv_age_over_12_days,         -- 库龄12月以上
                             coalesce(fbd.inv_age_over_12_price, 0)                                 as inv_age_over_12_price,        -- 库龄12月以上_成本,
                             coalesce(fbd.lowerlibrary_ages_days, 0)                                as lowerlibrary_ages_days,       -- 低库龄段库存数量
                             coalesce(fbd.lowerlibrary_ages_price, 0)                               as lowerlibrary_ages_price,      -- 低库龄段库存_成本,
                             coalesce(fbd.superlibrary_ages_days, 0)                                as superlibrary_ages_days,       -- 高库龄段库存数量
                             coalesce(fbd.superlibrary_ages_price, 0)                               as superlibrary_ages_price,      -- 高库龄段库存_成本,
                             coalesce(fbd.over_inv90_days, 0)                                       as over_inv90_days,              -- 超90天库存数量
                             coalesce(fbd.over_inv90_price, 0)                                      as over_inv90_price,             -- 超90天库存_成本,
                             fbd.superlibrary_proportion,                                                                            -- 高库龄段成本占比
                             fbd.superlibrary_ages_days /
                             nullif(ppbd.avg_daily_volume, 0)                                       as overdue_prod_sal_days,        -- 超库龄产品可售天数
                             fbd.inv_age_6_9_days /
                             nullif(ppbd.avg_daily_volume, 0)                                       as 6_9m_prod_sal_days,           -- '6-9个月产品可售天数'
                             fbd.inv_age_9_12_days /
                             nullif(ppbd.avg_daily_volume, 0)                                       as 9_12m_prod_sal_days,          -- '9-12个月产品可售天数'
                             fbd.inv_age_over_12_days /
                             nullif(ppbd.avg_daily_volume, 0)                                       as 12m_plus_prod_sal_days,       -- '12个月以上产品可售天数'
                             case
                                 when lowerlibrary_ages_days > 0 and superlibrary_ages_days = 0
                                     then '0-6个月(不含超库龄)'
                                 when lowerlibrary_ages_days > 0 and superlibrary_ages_days > 0
                                     then '0-6个月(含超库龄)'
                                 when lowerlibrary_ages_days = 0 and superlibrary_ages_days > 0 then '6个月以上'
                                 else '无库龄段数据' end                                            as aging_range,
                             coalesce(ist_country.earliest_ship_time, ist_eu.earliest_ship_time)    as earliest_ship_time,
                             coalesce(ist_country.channel_abbrev, ist_eu.channel_abbrev)            as channel_abbrev,
                             coalesce(ist_country.logistics_est_days, ist_eu.logistics_est_days)    as logistics_est_days,
                             date_add(coalesce(ist_country.earliest_ship_time, ist_eu.earliest_ship_time),
                                      interval
                                      coalesce(ist_country.logistics_est_days, ist_eu.logistics_est_days)
                                      day)                                                          as expected_delivery_time,
                    ppbd.predict_profit_margin_adj,
                    ppbd.profit_margin_category

                      from 产品表现_店铺_周维度 as ppbd
                               left join listing_产品管理_店铺 as lpbd
                                         on ppbd.seller_sku_adj = lpbd.seller_sku
                                             and ppbd.seller_name_new = lpbd.seller_name_new
                                             and ppbd.country_category = lpbd.country_category
                                             and ppbd.local_sku = lpbd.max_sku
                               left join FBA货件_店铺 as fsbd
                                         on ppbd.seller_sku_adj = fsbd.msku
                                             and ppbd.seller_name_new = fsbd.seller_name_new
                                             and ppbd.country_category = fsbd.country_category
                               left join 结算利润_店铺_周维度 as spbd
                                         on ppbd.seller_sku_adj = spbd.seller_sku_adj
                                             and ppbd.seller_name_new = spbd.seller_name_new
                                             and ppbd.country_category = spbd.country_category
                                             and spbd.year_week = ppbd.year_week
                               left join 季度分类_店铺 as qbd
                                         on ppbd.seller_sku_adj = qbd.seller_sku_adj
                                             and ppbd.seller_name_new = qbd.seller_name_new
                                             and ppbd.country_category = qbd.country_category
                               left join 上月订单利润分类_店铺 as ubd
                                         on ppbd.seller_sku_adj = ubd.seller_sku_adj
                                             and ppbd.seller_name_new = ubd.seller_name_new
                                             and ppbd.country_category = ubd.country_category
                               left join FBA库存明细_店铺_周维度 as fbd
                                         on ppbd.seller_sku_adj = fbd.seller_sku_adj
                                             and ppbd.seller_name_new = fbd.seller_name_new
                                             and ppbd.country_category = fbd.country_category
                                             and ppbd.year_week = fbd.dt_week
                               left join 补货建议_店铺_周维度 as rbd
                                         on ppbd.seller_sku_adj = rbd.seller_sku_adj
                                             and ppbd.seller_name_new = rbd.seller_name_new
                                             and ppbd.country_category = rbd.country_category
                                             and ppbd.year_week+1 = rbd.dt_week
                               left join 上周筛选数据 as lfd
                                         on ppbd.seller_sku_adj = lfd.seller_sku_adj
                                             and ppbd.seller_name_new = lfd.seller_name_new
                                             and ppbd.country_category = lfd.country_category
                          -- 第一步：精确匹配国家类别
                               left join 物流天数_店铺 as ist_country
                                         on ppbd.seller_name_new = ist_country.seller_name_new
                                             and ppbd.seller_sku_adj = ist_country.msku
                                             and ppbd.country_category = ist_country.country_category
                          -- 第二步：对于英国站和欧洲站，如果没有精确匹配，则尝试匹配欧洲站的发货记录
                               left join 物流天数_店铺 as ist_eu
                                         on ppbd.seller_name_new = ist_eu.seller_name_new
                                             and ppbd.seller_sku_adj = ist_eu.MSKU
                                             and ist_eu.country_category = '欧洲站'
                                             and ppbd.country_category in ('英国站', '欧洲站')
                                             and ist_country.seller_name_new is null),
     周度数据表现汇总 as (select year_week,
                                 week_start,
                                 week_end,
                                 filtrate,
                                 last_week_filtrate,
                                 country_category,
                                 seller_name_new,
                                 seller_sku_adj,
                                 sales_team_1,
                                 principal,
                                 global_tags,
                                 clearance_tags,
                                 non_compliant_tags,
                                 max_spu,
                                 max_sku,
                                 max_local_name,
                                 max_category_name,
                                 max_brand_name,
                                 new_old_product,
                                 max_product_dev_time,
                                 avg_price_cny,
                                 onsale_sites,
                                 unsale_sites,
                                 sales_status,
                                 avg_daily_volume_category,
                                 last_week_avg_daily_volume_category,
                                 abcd_category,
                                 gp_margin_range,
                                 pre_2q_predict_abcd_category,
                                 pre_1q_predict_abcd_category,
                                 category_changes,
                                 predict_abcd_category,
                                 predict_profit_margin_adj, -- 新增
                                 profit_margin_category, -- 新增
                                 pre_1m_predict_abcd_category,
                                 is_predict_abc,
                                 max_tag_name,
                                 max_cg_box_pcs,
                                 max_cg_price,
                                 max_cg_transport_costs,
                                 receiving_cnt,
                                 min_receiving_time,
                                 days_since_launch,
                                 since_launch_range,
                                 max_receiving_time,
                                 days_latest_delivery,
                                 delivery_time_range,
                                 new_is_replenishment,
                                 concat_price,
                                 concat_rank,
                                 concat_reviews_count,
                                 concat_avg_star,
                                 week_days,
                                 afn_fulfillable_quantity_not_zero_days,
                                 avg_daily_volume,
                                 volume,
                                 last_week_volume,
                                 volume_diff,
                                 rk_volume_diff,
                                 amount,
                                 amount_tax, -- 新增
                                 last_week_amount,
                                 amount_diff,
                                 net_amount,
                                 order_items,
                                 total_sales_amount,
                                 gross_profit,
                                 last_week_gross_profit,
                                 wk_profit_diff,
                                 profit_margin,
                                 predict_gross_profit,
                                 predict_gross_profit_adj, -- 新增
                                 predict_profit_margin,
                                 return_goods_count,
                                 return_amount,
                                 return_proportion,
                                 refund_proportion,
                                 spend,
                                 acos,
                                 acoas,
                                 ctr,
                                 ad_sales_amount,
                                 ad_order_quantity,
                                 ad_order_proportion,
                                 ad_cvr,
                                 impressions,
                                 clicks,
                                 sessions_total,
                                 nature_cvr,
                                 total,
                                 total_price,
                                 available_total,
                                 afn_fulfillable_quantity,
                                 reserved_fc_transfers,
                                 reserved_fc_processing,
                                 reserved_customerorders,
                                 afn_unsellable_quantity,
                                 afn_inbound_receiving_quantity,
                                 stock_up_num,
                                 afn_researching_quantity,
                                 sc_quantity_local_valid,
                                 sc_quantity_purchase_shipping,
                                 sc_quantity_purchase_plan,
                                 sc_quantity_local_qc,
                                 local_quantity,
                                 local_cost,
                                 available_total_price,
                                 fba_local_quantity,
                                 fba_local_cost,
                                 sales_30,
                                 sales_60,
                                 amz_inv_sales_ratio,
                                 fba_local_inv_sales_ratio,
                                 fba_local_salable_days,
                                 case
                                     when fba_local_salable_days = 0 and fba_local_salable_days is not null
                                         then '可售天数0天'
                                     when (fba_local_salable_days > 0 and fba_local_salable_days < 30)
                                         then '可售天数30天内'
                                     when (fba_local_salable_days >= 30 and fba_local_salable_days < 60)
                                         then '可售天数60天内'
                                     when (fba_local_salable_days >= 60 and fba_local_salable_days < 90)
                                         then '可售天数90天内'
                                     when (fba_local_salable_days >= 90 and fba_local_salable_days < 180)
                                         then '可售天数180天内'
                                     when (fba_local_salable_days >= 180 and fba_local_salable_days < 270)
                                         then '可售天数270天内'
                                     when (fba_local_salable_days >= 270 and fba_local_salable_days < 360)
                                         then '可售天数360天内'
                                     when (fba_local_salable_days >= 360)
                                         then '可售天数360天以上'
                                     else ''
                                     end as fba_local_salable_days_range, -- fba库存+本地库存可售区间
                                 available_salable_days,
                                 case
                                     when available_salable_days = 0 and available_salable_days is not null
                                         then '可售天数0天'
                                     when (available_salable_days > 0 and available_salable_days < 30)
                                         then '可售天数30天内'
                                     when (available_salable_days >= 30 and available_salable_days < 60)
                                         then '可售天数60天内'
                                     when (available_salable_days >= 60 and available_salable_days < 90)
                                         then '可售天数90天内'
                                     when (available_salable_days >= 90 and available_salable_days < 180)
                                         then '可售天数180天内'
                                     when (available_salable_days >= 180 and available_salable_days < 270)
                                         then '可售天数270天内'
                                     when (available_salable_days >= 270 and available_salable_days < 360)
                                         then '可售天数360天内'
                                     when (available_salable_days >= 360)
                                         then '可售天数360天以上'
                                     else ''
                                     end as available_salable_days_range, -- 可用库存可售天数区间
                                 inv_age_0_3_days,
                                 inv_age_0_3_price,
                                 inv_age_3_6_days,
                                 inv_age_3_6_price,
                                 inv_age_6_9_days,
                                 inv_age_6_9_price,
                                 inv_age_9_12_days,
                                 inv_age_9_12_price,
                                 inv_age_over_12_days,
                                 inv_age_over_12_price,
                                 lowerlibrary_ages_days,
                                 lowerlibrary_ages_price,
                                 superlibrary_ages_days,
                                 superlibrary_ages_price,
                                 over_inv90_days,
                                 over_inv90_price,
                                 superlibrary_proportion,
                                 overdue_prod_sal_days,
                                 `6_9m_prod_sal_days`,
                                 `9_12m_prod_sal_days`,
                                 `12m_plus_prod_sal_days`,
                                 aging_range,
                                 earliest_ship_time,
                                 channel_abbrev,
                                 logistics_est_days,
                                 expected_delivery_time
                          from 周度数据表现),
     产品生命周期 as (select country_category, seller_name_new, seller_sku, product_lifecycle_stage
                      from dws_datasync.dws_product_lifecycle_market_v2
                      where create_time = (select max(create_time) from dws_datasync.dws_product_lifecycle_market_v2))
select wd.*,
       case
           when available_salable_days > 60 or datediff(expected_delivery_time, week_end) < available_salable_days
               then '不会缺货'
           else case
                    when stock_up_num = 0 and local_quantity = 0 then '缺货未补货'
                    when stock_up_num > 0 or local_quantity > 0 then '缺货已补货'
               end
           end as stockout_status, -- 缺货状态
       pl.product_lifecycle_stage, -- 产品生命周期标签
       case
           when over_inv90_days > 0 and sales_60 = 0 then '是：库龄90天+且近60天不出单'
           else '否'
           end as clearance_status, -- 是否清货状态
           now() as 'create_time'
from 周度数据表现汇总 as wd
         left join 产品生命周期 as pl
                   on wd.country_category = pl.country_category
                       and wd.seller_name_new = pl.seller_name_new
                       and wd.seller_sku_adj = pl.seller_sku
where year_week = @s_week
order by wd.sales_team_1 desc, cast(wd.rk_volume_diff as signed);


-- --------------------------------- 站点组合 ------------------------------------
select yearweek(date_sub(date_sub(curdate(), interval weekday(curdate()) day), interval 7 day), 1);
select yearweek(date_sub(curdate(), interval 1 week), 1);
set @s_week = yearweek(date_sub(curdate(), interval 1 week), 1);
# drop table if exists dws_datasync.ops_weekly_rpt_prod_perf_sites_data;
# create table if not exists dws_datasync.ops_weekly_rpt_prod_perf_sites_data as
# insert into dws_datasync.ops_weekly_rpt_prod_perf_sites_data
with 产品表现_站点_周维度 as (select *
                              from etl_datasync.ops_weekly_rpt_site_prod_perf_basic_data
                              where length(seller_sku_adj) between 5 and 10),
     listing_产品管理_站点 as (select distinct create_time,
                                               seller_sku,
                                               country_category,
                                               seller_name_ue,
                                               seller_name_new,
                                               seller_name,
                                               marketplace,
                                               principal,
                                               sales_team_1,
                                               onsale_sites,
                                               unsale_sites,
                                               sales_status,
                                               avg_price_cny,
                                               global_tags,
                                               case
                                                   when global_tags regexp '清货-正常' then '清货-正常'
                                                   when global_tags regexp '清货-紧急'
                                                       then '清货-紧急' end                                  as clearance_tags,
                                               case
                                                   when global_tags regexp '不合规-'
                                                       then regexp_substr(global_tags, '不合规-[^,|，]+') end as non_compliant_tags,
                                               max_sku,
                                               max_local_name,
                                               max_spu,
                                               max_tag_name,
                                               max_product_dev_time,
                                               max_brand_name,
                                               max_category_name,
                                               max_product_developer,
                                               max_cg_box_pcs,
                                               max_cg_price,
                                               max_cg_transport_costs,
                                               new_old_product
                               from etl_datasync.ops_rpt_listing_prod_basic_data
                               where length(seller_sku) between 5 and 10),
     FBA货件_店铺 as (select * from etl_datasync.ops_rpt_fba_shipment_basic_data),
     结算利润_站点_周维度 as (select * from etl_datasync.ops_weekly_rpt_site_settlement_profit_basic_data),
     季度分类_店铺 as (select *
                       from etl_datasync.ops_quarter_rpt_prod_perf_basic_data_site),
     FBA库存明细_店铺_周维度 as (select * from etl_datasync.ops_weekly_rpt_fba_inv_detail_basic_data),
     补货建议_店铺_周维度 as (select * from etl_datasync.ops_weekly_rpt_replenish_sug_basic_data),
     物流天数_店铺 as (select * from etl_datasync.ops_rpt_logi_est_days_data),
     上月订单利润分类_店铺 as (select y_month,
                                      country_category,
                                      seller_name_new,
                                      seller_name,
                                      country,
                                      seller_sku_adj,
                                      asin,
                                      local_sku,
                                      predict_profit_margin as pre_1m_predict_profit_margin,
                                      predict_abcd_category as pre_1m_predict_abcd_category
                               from etl_datasync.ops_monthly_rpt_site_prod_perf_basic_data
                               where y_month = date_format(date_sub(curdate()
                                                               , interval 1 month)
                                   , '%Y-%m')),
     上周筛选数据 as (select year_week,
                             country_category,
                             seller_name_new,
                             seller_name,
                             country,
                             seller_sku_adj,
                             max_sku,
                             filtrate as last_week_filtrate
                      from dws_datasync.ops_weekly_rpt_prod_perf_sites_data
                      where year_week = yearweek(date_sub(curdate(), interval 2 week), 1)),
     周度数据表现 as (select ppbd.year_week,                                                                                         --  周
                             ppbd.week_start,                                                                                        -- 周最小日期
                             ppbd.week_end,                                                                                          -- 周最大日期
                             case
                                 when volume > 0 or (coalesce(rbd.local_quantity, 0) + coalesce(fbd.total, 0)) > 0
                                     then '1'
                                 else '0'
                                 end                                                                as filtrate,
                             coalesce(last_week_filtrate, 0)                                        as last_week_filtrate,
                             ppbd.country_category,                                                                                  -- 国家类别
                             ppbd.seller_name_new,                                                                                   -- 新店铺
                             ppbd.seller_name,                                                                                       -- 店铺
                             ppbd.country,                                                                                           -- 国家
                             ppbd.seller_sku_adj,                                                                                    -- msku
                             lpbd.sales_team_1,                                                                                      -- 运营团队
                             lpbd.principal,                                                                                         -- 负责人
                             lpbd.global_tags,                                                                                       -- listing标签
                             lpbd.clearance_tags,                                                                                    -- 清货标签
                             lpbd.non_compliant_tags,                                                                                -- 不合规标签
                             lpbd.max_spu,                                                                                           -- spu
                             lpbd.max_sku,                                                                                           -- sku
                             lpbd.max_local_name,                                                                                    -- 品名
                             lpbd.max_category_name,                                                                                 -- 分类
                             lpbd.max_brand_name,                                                                                    -- 品牌
                             lpbd.new_old_product,                                                                                   -- 新老品
                             lpbd.max_product_dev_time,                                                                              -- 产品开发时间
                             lpbd.avg_price_cny,                                                                                     -- 平均售价cny
                             lpbd.onsale_sites,                                                                                      -- 在数站点个数
                             lpbd.unsale_sites,                                                                                      -- 停售站点个数
                             lpbd.sales_status,                                                                                      -- 销售状态

                             ppbd.avg_daily_volume_category,                                                                         -- 本周日均销量分类
                             ppbd.last_week_avg_daily_volume_category,                                                               -- 上周日均销量分类
                             coalesce(spbd.abcd_category, 'E')                                      as abcd_category,                -- 本周结算abcd分类
                             spbd.gp_margin_range,                                                                                   -- 本周结算毛利率区间
                             qbd.pre_2q_predict_abcd_category,                                                                       -- 前2个季度订单利润分类
                             qbd.pre_1q_predict_abcd_category,                                                                       -- 前1个季度订单利润分类
                             qbd.category_changes,                                                                                   -- 季度分类变化
                             coalesce(ppbd.predict_abcd_category, 'E')                              as predict_abcd_category,        -- 本周订单利润分类
                             coalesce(ubd.pre_1m_predict_abcd_category, 'E')                        as pre_1m_predict_abcd_category, -- 前1个月订单利润分类
                             case
                                 when avg_daily_volume >= 1 and predict_profit_margin >= 0.10 then 0
                                 else 1
                                 end                                                                as is_predict_abc,               -- 本周订单分类异常判断

                             lpbd.max_tag_name,                                                                                      -- 标签
                             lpbd.max_cg_box_pcs,                                                                                    -- 单箱数量
                             lpbd.max_cg_price,                                                                                      -- 采购单价
                             lpbd.max_cg_transport_costs,                                                                            -- 头程运费

                             fsbd.receiving_cnt,                                                                                     -- 货件接收次数
                             fsbd.min_receiving_time,                                                                                -- 最小货件接收时间
                             fsbd.days_since_launch,                                                                                 -- 开售天数
                             fsbd.since_launch_range,                                                                                -- 开售天数区间
                             fsbd.max_receiving_time,                                                                                -- 最大货件接收时间
                             fsbd.days_latest_delivery,                                                                              -- 货件最晚发货天数
                             fsbd.delivery_time_range,                                                                               -- 货件最晚发货时间区间
                             case
                                 when new_old_product = '新品' and days_latest_delivery >= 90
                                     and receiving_cnt <= 1 then '新品未补货'
                                 else '已补货'
                                 end                                                                as new_is_replenishment,         -- 新品是否补货
                             ppbd.concat_price,                                                                                      -- 国家_价格
                             ppbd.concat_rank,                                                                                       -- 国家_排名
                             ppbd.concat_reviews_count,                                                                              -- 国家_评论数
                             ppbd.concat_avg_star,                                                                                   -- 国家_评分
                             ppbd.week_days,                                                                                         -- 周实际天数
                             ppbd.afn_fulfillable_quantity_not_zero_days,                                                            -- 可售库存非零天数
                             ppbd.avg_daily_volume,                                                                                  -- 日均销量
                             ppbd.volume,                                                                                            -- 销量
                             ppbd.last_week_volume,                                                                                  -- 上周销量
                             ppbd.volume_diff,                                                                                       -- 销量差值
                             row_number() over (partition by ppbd.year_week, lpbd.sales_team_1
                                 order by ppbd.volume_diff)                                         as rk_volume_diff,               -- 销量差值排序
                             ppbd.amount,                                                                                            -- 销售额
                             ppbd.amount_tax,                                                                                        -- 销售额不含税
                             ppbd.last_week_amount,                                                                                  -- 上周销售额
                             ppbd.amount_diff,                                                                                       -- 销售额差值
                             ppbd.net_amount,                                                                                        -- 净销售额
                             ppbd.order_items,                                                                                       -- 订单量
                             spbd.total_sales_amount,                                                                                -- 结算销售额
                             spbd.gross_profit,                                                                                      -- 结算毛利润
                             spbd.last_week_gross_profit,                                                                            -- 上周结算毛利润
                             spbd.wk_profit_diff,                                                                                    -- 周利润差值
                             spbd.profit_margin,                                                                                     -- 结算毛利率
                             ppbd.predict_gross_profit,                                                                              -- 订单毛利润
                             ppbd.predict_profit_margin,                                                                             -- 订单毛利率
                             ppbd.predict_gross_profit_adj,                                                                          -- 订单毛利润（修正）
#        spbd.gross_profit_with_tax,                  -- 含税结算毛利润
#        spbd.profit_with_tax_margin,                 -- 含税结算毛利率
#        spbd.last_week_profit_margin,                -- 上周结算毛利率
#        ppbd.gross_profit,                           -- 结算毛利润
                             ppbd.return_goods_count,                                                                                -- 退货量
                             ppbd.return_amount,                                                                                     -- 退款金额
                             ppbd.return_proportion,                                                                                 -- 退货率
                             ppbd.refund_proportion,                                                                                 -- 退款率
                             ppbd.spend,                                                                                             -- 广告花费
                             ppbd.acos,
                             ppbd.acoas,
                             ppbd.ctr,
                             ppbd.ad_sales_amount,                                                                                   -- 广告销售额,
                             ppbd.ad_order_quantity,                                                                                 -- 广告订单量
                             ppbd.ad_order_proportion,                                                                               -- 广告订单占比
                             ppbd.ad_cvr,                                                                                            -- 广告cvr
                             ppbd.impressions,                                                                                       -- 展示
                             ppbd.clicks,                                                                                            -- 点击
                             ppbd.sessions_total,                                                                                    -- 会话数
                             ppbd.nature_cvr,                                                                                        -- 自然cvr
                             fbd.total,                                                                                              -- 总库存
                             fbd.total_price,                             -- 总库存_成本
                             fbd.available_total,                                                                                    -- 可用库存
#        fbd.available_total_price,                   -- 可用库存_成本
                             fbd.afn_fulfillable_quantity,                                                                           -- FBA可售
#        fbd.afn_fulfillable_quantity_price,          -- FBA可售_成本
                             fbd.reserved_fc_transfers,                                                                              -- 待调仓
#        fbd.reserved_fc_transfers_price,             -- 待调仓_成本
                             fbd.reserved_fc_processing,                                                                             -- 调仓中
#        fbd.reserved_fc_processing_price,            -- 调仓中_成本
                             fbd.reserved_customerorders,                                                                            -- 待发货
#        fbd.reserved_customerorders_price,           -- 待发货_成本
                             fbd.afn_unsellable_quantity,                                                                            -- 不可售
#        fbd.afn_unsellable_quantity_price,           -- 不可售_成本
                             fbd.afn_inbound_receiving_quantity,                                                                     -- 待入库
#        fbd.afn_inbound_receiving_quantity_price,    -- 待入库_成本
                             fbd.stock_up_num,                                                                                       -- 实际在途
#        fbd.stock_up_num_price,                      -- 实际在途_成本
                             fbd.afn_researching_quantity,                                                                           -- 调查中
#        fbd.afn_researching_quantity_price,          -- 调查中_成本
                             rbd.sc_quantity_local_valid,                                                                            -- 本地可用
                             rbd.sc_quantity_purchase_shipping,                                                                      -- 待交付
                             rbd.sc_quantity_purchase_plan,                                                                          -- 采购计划
                             rbd.sc_quantity_local_qc,                                                                               -- 待检待上架量
                             rbd.local_quantity,                                                                                     -- 本地仓库存
                             (lpbd.max_cg_price + lpbd.max_cg_transport_costs) * rbd.local_quantity as local_cost,                   -- 本地仓成本
                             fbd.available_total_price,                                                                              -- 可用库存_成本
                             coalesce(rbd.local_quantity + fbd.total, 0)                            as fba_local_quantity,           -- fba库存+本地库存
                             (lpbd.max_cg_price + lpbd.max_cg_transport_costs)
                                 * rbd.local_quantity +
                             fbd.total_price                                                        as fba_local_cost,               -- fba库存成本+本地库存成本
                             coalesce(ppbd.sales_30, 0)                                             as sales_30,                     -- 30天销量,
                             coalesce(ppbd.sales_60, 0)                                             as sales_60,                     -- 60天销量
                             fbd.available_total / nullif(ppbd.sales_30, 0)                         as amz_inv_sales_ratio,          -- 在亚马逊库销比
                             (rbd.local_quantity + fbd.total) / nullif(ppbd.sales_30, 0)            as fba_local_inv_sales_ratio,    -- fba_本地库销比
                             case
                                 when (coalesce(rbd.local_quantity, 0) + coalesce(fbd.total, 0)) > 0 and
                                      (ppbd.volume = 0 or ppbd.afn_fulfillable_quantity_not_zero_days = 0) then '99999'
                                 when (coalesce(rbd.local_quantity, 0) + coalesce(fbd.total, 0)) > 0 and
                                      (ppbd.volume > 0 and ppbd.afn_fulfillable_quantity_not_zero_days > 0)
                                     then (rbd.local_quantity + fbd.total) /
                                          (ppbd.volume / ppbd.afn_fulfillable_quantity_not_zero_days)
                                 when (coalesce(rbd.local_quantity, 0) + coalesce(fbd.total, 0)) = 0 then 0
                                 end                                                                as fba_local_salable_days,       -- fba库存+本地库存可售天数
#                              (rbd.local_quantity + fbd.total) /
#                              nullif(ppbd.volume / nullif(ppbd.afn_fulfillable_quantity_not_zero_days, 0),
#                                     0)                                                              as fba_local_salable_days,       -- fba库存+本地库存可售天数
                             case
                                 when fbd.available_total > 0 and
                                      (ppbd.volume = 0 or ppbd.afn_fulfillable_quantity_not_zero_days = 0)
                                     then '99999'
                                 when fbd.available_total > 0 and
                                      (ppbd.volume > 0 and ppbd.afn_fulfillable_quantity_not_zero_days > 0)
                                     then fbd.available_total /
                                          (ppbd.volume / ppbd.afn_fulfillable_quantity_not_zero_days)
                                 when fbd.available_total = 0 then 0
                                 end                                                                as available_salable_days,       -- 可用库存可售天数
#                              fbd.available_total /
#                              nullif(ppbd.volume / nullif(ppbd.afn_fulfillable_quantity_not_zero_days, 0),
#                                     0)                                                              as available_salable_days,       -- 可用库存可售天数
                             coalesce(fbd.inv_age_0_3_days, 0)                                      as inv_age_0_3_days,             -- 库龄0-3月
                             coalesce(fbd.inv_age_0_3_price, 0)                                     as inv_age_0_3_price,            -- 库龄0-3月_成本,
                             coalesce(fbd.inv_age_3_6_days, 0)                                      as inv_age_3_6_days,             -- 库龄3-6月
                             coalesce(fbd.inv_age_3_6_price, 0)                                     as inv_age_3_6_price,            -- 库龄3-6月_成本,
                             coalesce(fbd.inv_age_6_9_days, 0)                                      as inv_age_6_9_days,             -- 库龄6-9月
                             coalesce(fbd.inv_age_6_9_price, 0)                                     as inv_age_6_9_price,            -- 库龄6-9月_成本,
                             coalesce(fbd.inv_age_9_12_days, 0)                                     as inv_age_9_12_days,            -- 库龄9-12月
                             coalesce(fbd.inv_age_9_12_price, 0)                                    as inv_age_9_12_price,           -- 库龄9-12月_成本,
                             coalesce(fbd.inv_age_over_12_days, 0)                                  as inv_age_over_12_days,         -- 库龄12月以上
                             coalesce(fbd.inv_age_over_12_price, 0)                                 as inv_age_over_12_price,        -- 库龄12月以上_成本,
                             coalesce(fbd.lowerlibrary_ages_days, 0)                                as lowerlibrary_ages_days,       -- 低库龄段库存数量
                             coalesce(fbd.lowerlibrary_ages_price, 0)                               as lowerlibrary_ages_price,      -- 低库龄段库存_成本,
                             coalesce(fbd.superlibrary_ages_days, 0)                                as superlibrary_ages_days,       -- 高库龄段库存数量
                             coalesce(fbd.superlibrary_ages_price, 0)                               as superlibrary_ages_price,      -- 高库龄段库存_成本,
                             coalesce(fbd.over_inv90_days, 0)                                       as over_inv90_days,              -- 超90天库存数量
                             coalesce(fbd.over_inv90_price, 0)                                      as over_inv90_price,             -- 超90天库存_成本,
                             fbd.superlibrary_proportion,                                                                            -- 高库龄段成本占比
                             fbd.superlibrary_ages_days /
                             nullif(ppbd.avg_daily_volume, 0)                                       as overdue_prod_sal_days,        -- 超库龄产品可售天数
                             fbd.inv_age_6_9_days /
                             nullif(ppbd.avg_daily_volume, 0)                                       as 6_9m_prod_sal_days,           -- '6-9个月产品可售天数'
                             fbd.inv_age_9_12_days /
                             nullif(ppbd.avg_daily_volume, 0)                                       as 9_12m_prod_sal_days,          -- '9-12个月产品可售天数'
                             fbd.inv_age_over_12_days /
                             nullif(ppbd.avg_daily_volume, 0)                                       as 12m_plus_prod_sal_days,       -- '12个月以上产品可售天数'


                             case
                                 when lowerlibrary_ages_days > 0 and superlibrary_ages_days = 0
                                     then '0-6个月(不含超库龄)'
                                 when lowerlibrary_ages_days > 0 and superlibrary_ages_days > 0
                                     then '0-6个月(含超库龄)'
                                 when lowerlibrary_ages_days = 0 and superlibrary_ages_days > 0 then '6个月以上'
                                 else '无库龄段数据' end                                            as aging_range,
                             coalesce(ist_country.earliest_ship_time, ist_eu.earliest_ship_time)    as earliest_ship_time,
                             coalesce(ist_country.channel_abbrev, ist_eu.channel_abbrev)            as channel_abbrev,
                             coalesce(ist_country.logistics_est_days, ist_eu.logistics_est_days)    as logistics_est_days,
                             date_add(coalesce(ist_country.earliest_ship_time, ist_eu.earliest_ship_time),
                                      interval
                                      coalesce(ist_country.logistics_est_days, ist_eu.logistics_est_days)
                                      day)                                                          as expected_delivery_time,
                             ppbd.predict_profit_margin_adj,
                             ppbd.profit_margin_category

                      from 产品表现_站点_周维度 as ppbd
                               left join listing_产品管理_站点 as lpbd
                                         on ppbd.seller_sku_adj = lpbd.seller_sku
                                             and ppbd.seller_name_new = lpbd.seller_name_new
                                             and ppbd.country_category = lpbd.country_category
                                             and ppbd.local_sku = lpbd.max_sku
                                             and ppbd.country = lpbd.marketplace
                               left join FBA货件_店铺 as fsbd
                                         on ppbd.seller_sku_adj = fsbd.msku
                                             and ppbd.seller_name_new = fsbd.seller_name_new
                                             and ppbd.country_category = fsbd.country_category
                               left join 结算利润_站点_周维度 as spbd
                                         on ppbd.seller_sku_adj = spbd.seller_sku_adj
                                             and ppbd.seller_name_new = spbd.seller_name_new
                                             and ppbd.country_category = spbd.country_category
                                             and spbd.year_week = ppbd.year_week
                                             and spbd.country = ppbd.country
                               left join 季度分类_店铺 as qbd
                                         on ppbd.seller_sku_adj = qbd.seller_sku_adj
                                             and ppbd.seller_name_new = qbd.seller_name_new
                                             and ppbd.country_category = qbd.country_category
                                             and ppbd.country = qbd.country
                               left join 上月订单利润分类_店铺 as ubd
                                         on ppbd.seller_sku_adj = ubd.seller_sku_adj
                                             and ppbd.seller_name_new = ubd.seller_name_new
                                             and ppbd.country_category = ubd.country_category
                                             and ppbd.country = ubd.country
                               left join FBA库存明细_店铺_周维度 as fbd
                                         on ppbd.seller_sku_adj = fbd.seller_sku_adj
                                             and ppbd.seller_name_new = fbd.seller_name_new
                                             and ppbd.country_category = fbd.country_category
                                             and ppbd.year_week = fbd.dt_week
                               left join 补货建议_店铺_周维度 as rbd
                                         on ppbd.seller_sku_adj = rbd.seller_sku_adj
                                             and ppbd.seller_name_new = rbd.seller_name_new
                                             and ppbd.country_category = rbd.country_category
                                             and ppbd.year_week = rbd.dt_week
                               left join 上周筛选数据 as lfd
                                         on ppbd.seller_sku_adj = lfd.seller_sku_adj
                                             and ppbd.seller_name_new = lfd.seller_name_new
                                             and ppbd.country_category = lfd.country_category
                                             and ppbd.country = lfd.country
                          -- 第一步：精确匹配国家类别
                               left join 物流天数_店铺 as ist_country
                                         on ppbd.seller_name_new = ist_country.seller_name_new
                                             and ppbd.seller_sku_adj = ist_country.msku
                                             and ppbd.country_category = ist_country.country_category
                          -- 第二步：对于英国站和欧洲站，如果没有精确匹配，则尝试匹配欧洲站的发货记录
                               left join 物流天数_店铺 as ist_eu
                                         on ppbd.seller_name_new = ist_eu.seller_name_new
                                             and ppbd.seller_sku_adj = ist_eu.MSKU
                                             and ist_eu.country_category = '欧洲站'
                                             and ppbd.country_category in ('英国站', '欧洲站')
                                             and ist_country.seller_name_new is null),
     周度数据表现汇总 as (select year_week,
                                 week_start,
                                 week_end,
                                 filtrate,
                                 last_week_filtrate,
                                 country_category,
                                 seller_name_new,
                                 seller_name,
                                 country,
                                 seller_sku_adj,
                                 sales_team_1,
                                 principal,
                                 global_tags,
                                 clearance_tags,
                                 non_compliant_tags,
                                 max_spu,
                                 max_sku,
                                 max_local_name,
                                 max_category_name,
                                 new_old_product,
                                 max_product_dev_time,
                                 avg_price_cny,
                                 onsale_sites,
                                 unsale_sites,
                                 sales_status,
                                 avg_daily_volume_category,
                                 last_week_avg_daily_volume_category,
                                 abcd_category,
                                 gp_margin_range,
                                 pre_2q_predict_abcd_category,
                                 pre_1q_predict_abcd_category,
                                 category_changes,
                                 predict_abcd_category,
                                 predict_profit_margin_adj, -- 新增
                                 profit_margin_category, -- 新增
                                 pre_1m_predict_abcd_category,
                                 is_predict_abc,
                                 max_tag_name,
                                 max_brand_name,
                                 max_cg_box_pcs,
                                 max_cg_price,
                                 max_cg_transport_costs,
                                 receiving_cnt,
                                 min_receiving_time,
                                 days_since_launch,
                                 since_launch_range,
                                 max_receiving_time,
                                 days_latest_delivery,
                                 delivery_time_range,
                                 new_is_replenishment,
                                 concat_price,
                                 concat_rank,
                                 concat_reviews_count,
                                 concat_avg_star,
                                 week_days,
                                 afn_fulfillable_quantity_not_zero_days,
                                 avg_daily_volume,
                                 volume,
                                 last_week_volume,
                                 volume_diff,
                                 rk_volume_diff,
                                 amount,
                                 amount_tax,-- 新增销售额不含税
                                 last_week_amount,
                                 amount_diff,
                                 net_amount,
                                 order_items,
                                 total_sales_amount,
                                 gross_profit,
                                 last_week_gross_profit,
                                 wk_profit_diff,
                                 profit_margin,
                                 predict_gross_profit,
                                 predict_gross_profit_adj, -- 新增
                                 predict_profit_margin,
                                 return_goods_count,
                                 return_amount,
                                 return_proportion,
                                 refund_proportion,
                                 spend,
                                 acos,
                                 acoas,
                                 ctr,
                                 ad_sales_amount,
                                 ad_order_quantity,
                                 ad_order_proportion,
                                 ad_cvr,
                                 impressions,
                                 clicks,
                                 sessions_total,
                                 nature_cvr,
                                 total,
                                 total_price,
                                 available_total,
                                 afn_fulfillable_quantity,
                                 reserved_fc_transfers,
                                 reserved_fc_processing,
                                 reserved_customerorders,
                                 afn_unsellable_quantity,
                                 afn_inbound_receiving_quantity,
                                 stock_up_num,
                                 afn_researching_quantity,
                                 sc_quantity_local_valid,
                                 sc_quantity_purchase_shipping,
                                 sc_quantity_purchase_plan,
                                 sc_quantity_local_qc,
                                 local_quantity,
                                 local_cost,
                                 available_total_price,
                                 fba_local_quantity,
                                 fba_local_cost,
                                 sales_30,
                                 sales_60,
                                 amz_inv_sales_ratio,
                                 fba_local_inv_sales_ratio,
                                 fba_local_salable_days,
                                 case
                                     when fba_local_salable_days = 0 and fba_local_salable_days is not null
                                         then '可售天数0天'
                                     when (fba_local_salable_days > 0 and fba_local_salable_days < 30)
                                         then '可售天数30天内'
                                     when (fba_local_salable_days >= 30 and fba_local_salable_days < 60)
                                         then '可售天数60天内'
                                     when (fba_local_salable_days >= 60 and fba_local_salable_days < 90)
                                         then '可售天数90天内'
                                     when (fba_local_salable_days >= 90 and fba_local_salable_days < 180)
                                         then '可售天数180天内'
                                     when (fba_local_salable_days >= 180 and fba_local_salable_days < 270)
                                         then '可售天数270天内'
                                     when (fba_local_salable_days >= 270 and fba_local_salable_days < 360)
                                         then '可售天数360天内'
                                     when (fba_local_salable_days >= 360)
                                         then '可售天数360天以上'
                                     else ''
                                     end as fba_local_salable_days_range, -- fba库存+本地库存可售区间
                                 available_salable_days,
                                 case
                                     when available_salable_days = 0 and available_salable_days is not null
                                         then '可售天数0天'
                                     when (available_salable_days > 0 and available_salable_days < 30)
                                         then '可售天数30天内'
                                     when (available_salable_days >= 30 and available_salable_days < 60)
                                         then '可售天数60天内'
                                     when (available_salable_days >= 60 and available_salable_days < 90)
                                         then '可售天数90天内'
                                     when (available_salable_days >= 90 and available_salable_days < 180)
                                         then '可售天数180天内'
                                     when (available_salable_days >= 180 and available_salable_days < 270)
                                         then '可售天数270天内'
                                     when (available_salable_days >= 270 and available_salable_days < 360)
                                         then '可售天数360天内'
                                     when (available_salable_days >= 360)
                                         then '可售天数360天以上'
                                     else ''
                                     end as available_salable_days_range, -- 可用库存可售天数区间
                                 inv_age_0_3_days,
                                 inv_age_0_3_price,
                                 inv_age_3_6_days,
                                 inv_age_3_6_price,
                                 inv_age_6_9_days,
                                 inv_age_6_9_price,
                                 inv_age_9_12_days,
                                 inv_age_9_12_price,
                                 inv_age_over_12_days,
                                 inv_age_over_12_price,
                                 lowerlibrary_ages_days,
                                 lowerlibrary_ages_price,
                                 superlibrary_ages_days,
                                 superlibrary_ages_price,
                                 over_inv90_days,
                                 over_inv90_price,
                                 superlibrary_proportion,
                                 overdue_prod_sal_days,
                                 `6_9m_prod_sal_days`,
                                 `9_12m_prod_sal_days`,
                                 `12m_plus_prod_sal_days`,
                                 aging_range,
                                 earliest_ship_time,
                                 channel_abbrev,
                                 logistics_est_days,
                                 expected_delivery_time
                          from 周度数据表现),
     产品生命周期 as (select country_category, seller_name_new, seller_sku, product_lifecycle_stage
                      from dws_datasync.dws_product_lifecycle_market_v2
                      where create_time = (select max(create_time) from dws_datasync.dws_product_lifecycle_market_v2))

select wd.*,
       case
           when available_salable_days > 60 or datediff(expected_delivery_time, week_end) < available_salable_days
               then '不会缺货'
           else case
                    when stock_up_num = 0 and local_quantity = 0 then '缺货未补货'
                    when stock_up_num > 0 or local_quantity > 0 then '缺货已补货'
               end
           end as stockout_status, -- 缺货状态
       pl.product_lifecycle_stage, -- 产品生命周期标签  -- 新增
       case
           when over_inv90_days > 0 and sales_60 = 0 then '是：库龄90天+且近60天不出单'
           else '否'
           end as clearance_status, -- 是否清货状态
     now() as 'create_time'
from 周度数据表现汇总 as wd
         left join 产品生命周期 as pl
                   on wd.country_category = pl.country_category
                       and wd.seller_name_new = pl.seller_name_new
                       and wd.seller_sku_adj = pl.seller_sku
where year_week = @s_week
order by wd.sales_team_1 desc, cast(wd.rk_volume_diff as signed);

