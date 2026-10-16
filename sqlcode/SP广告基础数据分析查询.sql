-- SP 广告基础数据查询示例（MySQL 8）
-- 修改参数后执行。金额按币种分组，避免不同币种直接相加。
set @start_date = '2026-08-08';
set @end_date = '2026-09-06';

-- 1. 店铺、站点、投放方式、匹配方式汇总（关键词口径）
select seller_name, country_code, currency_code, targeting_type, match_type,
       sum(impressions) impressions, sum(clicks) clicks, sum(cost) cost,
       sum(orders_1d) orders_1d, sum(orders_7d) orders_7d,
       sum(orders_14d) orders_14d, sum(orders_30d) orders_30d,
       sum(sales_1d) sales_1d, sum(sales_7d) sales_7d,
       sum(sales_14d) sales_14d, sum(sales_30d) sales_30d,
       sum(clicks) / nullif(sum(impressions), 0) ctr,
       sum(cost) / nullif(sum(clicks), 0) cpc,
       sum(orders_1d) / nullif(sum(clicks), 0) cvr_1d,
       sum(orders_7d) / nullif(sum(clicks), 0) cvr_7d,
       sum(orders_14d) / nullif(sum(clicks), 0) cvr_14d,
       sum(orders_30d) / nullif(sum(clicks), 0) cvr_30d,
       sum(cost) / nullif(sum(sales_1d), 0) acos_1d,
       sum(cost) / nullif(sum(sales_7d), 0) acos_7d,
       sum(cost) / nullif(sum(sales_14d), 0) acos_14d,
       sum(cost) / nullif(sum(sales_30d), 0) acos_30d,
       sum(sales_1d) / nullif(sum(cost), 0) roas_1d,
       sum(sales_7d) / nullif(sum(cost), 0) roas_7d,
       sum(sales_14d) / nullif(sum(cost), 0) roas_14d,
       sum(sales_30d) / nullif(sum(cost), 0) roas_30d
from dashboard_sp_keyword_daily
where report_date between @start_date and @end_date
group by seller_name, country_code, currency_code, targeting_type, match_type;

-- 2. MSKU 广告商品表现。MSKU 指标只使用商品广告报表，不把广告组指标分摊给商品。
select seller_name, country_code, currency_code, msku, asin,
       sum(impressions) impressions, sum(clicks) clicks, sum(cost) cost,
       sum(orders_7d) orders_7d, sum(sales_7d) sales_7d,
       sum(clicks) / nullif(sum(impressions), 0) ctr,
       sum(cost) / nullif(sum(clicks), 0) cpc,
       sum(orders_7d) / nullif(sum(clicks), 0) cvr_7d,
       sum(cost) / nullif(sum(sales_7d), 0) acos_7d,
       sum(sales_7d) / nullif(sum(cost), 0) roas_7d
from dashboard_sp_product_ad_daily
where report_date between @start_date and @end_date
group by seller_name, country_code, currency_code, msku, asin;

-- 3. 关键词详细表现。一个词在不同活动、广告组、匹配方式下分别保留。
select seller_name, country_code, currency_code, campaign_name_current,
       ad_group_name_current, targeting_type, keyword_text, match_type,
       associated_msku_count, sum(impressions) impressions, sum(clicks) clicks,
       sum(cost) cost, sum(orders_7d) orders_7d, sum(sales_7d) sales_7d,
       sum(cost) / nullif(sum(sales_7d), 0) acos_7d
from dashboard_sp_keyword_daily
where report_date between @start_date and @end_date
group by profile_id, campaign_id, ad_group_id, keyword_id, keyword_text, match_type,
         seller_name, country_code, currency_code, campaign_name_current,
         ad_group_name_current, targeting_type, associated_msku_count;

-- 4. 搜索词详细表现及对应投放表达式。
select seller_name, country_code, currency_code, campaign_name_current,
       ad_group_name_current, targeting_type, target_id, target_text,
       target_expressions, match_type, search_term, associated_msku_count,
       sum(impressions) impressions, sum(clicks) clicks, sum(cost) cost,
       sum(orders_7d) orders_7d, sum(sales_7d) sales_7d
from dashboard_sp_search_term_daily
where report_date between @start_date and @end_date
group by profile_id, campaign_id, ad_group_id, target_id, target_text,
         target_expressions, match_type, search_term, seller_name, country_code,
         currency_code, campaign_name_current, ad_group_name_current,
         targeting_type, associated_msku_count;

-- 5. 查询广告组当前关联的 MSKU，不与关键词指标做一对多展开。
select m.profile_id, m.campaign_id, m.ad_group_id,
       count(distinct m.msku) msku_count,
       group_concat(distinct m.msku order by m.msku separator ', ') msku_list
from dashboard_sp_ad_group_msku_current m
group by m.profile_id, m.campaign_id, m.ad_group_id;

-- 6. 数据质量与最近批次。
select batch_id, range_start, range_end, status, source_rows, result_rows,
       quality_json, started_at, finished_at
from dashboard_sp_etl_batch
order by batch_id desc limit 10;
