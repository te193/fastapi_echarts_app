# 产品分层看板指标口径与 SQL 占位文档

> 本文档已按 `sqlcode/原始.sql` 中的看板指标 SQL 修正。此前误读为“调价追踪 SQL”的内容不再作为看板迁移依据。

## 1. 文档目标

- 梳理当前看板指标 SQL 的表来源、字段来源、计算逻辑。
- 对齐现有 FastAPI 页面和 API 所需字段。
- 为后续数据库迁移预留 SQL 占位符。
- 暂不改现有代码，等 SQL 口径确认后再替换 `MockDashboardService`。

## 2. 当前 SQL 总体链路

当前 SQL 不是调价追踪链路，而是直接服务看板宽表。主线如下：

1. 从 `dwd_datasync.lx_statistics_product_performance` 聚合周期内每日商品表现，生成 `etl_datasync.product_performance_90_days`。
2. 从 `etl_datasync.etl_dispose_lx_replenishment_suggest_restocking` 汇总本地库存/补货建议，生成 `etl_datasync.month_end_data_补货建议`。
3. 从 `etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail` 汇总 FBA 库存明细，生成 `etl_datasync.month_end_data_库存明细`。
4. 从 `etl_datasync.etl_dispose_lx_sales_mws_listing` 获取当前 listing 现价。
5. 从 `dwd_datasync.lx_basic_currency` 获取当月汇率，计算人民币现价。
6. 从 `temporary_APP.yd_product_pricing_schedule` 获取目标毛利率 35%、运输方式为铁路的限价。
7. 将产品表现、补货建议、库存、现价、限价合并，输出当前看板明细宽表。

## 3. 源表与中间表

| 类型 | 表名 | SQL 中作用 | 后续迁移建议 |
| --- | --- | --- | --- |
| 销售/广告/利润事实表 | `dwd_datasync.lx_statistics_product_performance` | 商品表现核心来源，包含销量、销售额、毛利润、广告、点击曝光、FBA 可售等 | 最核心日事实表 |
| 商品周期聚合中间表 | `etl_datasync.product_performance_90_days` | 按日期、国家、店铺、SKU、local_sku 聚合商品表现 | 建议改为可每日增量的长期日聚合表 |
| 补货建议表 | `etl_datasync.etl_dispose_lx_replenishment_suggest_restocking` | 本地有效库存、采购在途、采购计划、本地 QC 等 | 建议生成每日快照表 |
| 补货建议中间表 | `etl_datasync.month_end_data_补货建议` | 汇总本地库存数量 `local_quantity` | 建议按快照日期保存 |
| FBA 库存明细表 | `etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail` | 总库存、可用库存、FBA 可售、不可售、在途等 | 建议生成每日库存快照 |
| FBA 库存中间表 | `etl_datasync.month_end_data_库存明细` | 汇总库存字段 | 建议按快照日期保存 |
| listing 现价表 | `etl_datasync.etl_dispose_lx_sales_mws_listing` | 获取当前售价与币种 | 建议生成每日价格快照 |
| 汇率表 | `dwd_datasync.lx_basic_currency` | 按月份与币种匹配汇率 | 保留月份维度 |
| 限价表 | `temporary_APP.yd_product_pricing_schedule` | 获取限价、目标毛利率、运输方式 | 建议确认是否应迁到正式 schema |

## 4. 当前宽表粒度

最终看板宽表建议保持以下粒度：

```text
统计周期 + seller_name_new + seller_sku_adj + country_category + country + local_sku
```

当前 SQL 里产品表现聚合的核心分组：

```text
seller_name_new, seller_sku_adj, country_category, country, local_sku
```

建议后续生成稳定主键：

```sql
concat(seller_name_new, '-', seller_sku_adj, '-', country, '-', local_sku) as item_id
```

## 5. 参数口径

当前 SQL 使用：

```sql
set @start_date = '2026-01-01';
set @end_date = '2026-03-31';
```

对应页面：

| 页面筛选 | API 参数 | SQL 参数/字段 |
| --- | --- | --- |
| 观察周期 | `start_date`, `end_date` | `@start_date`, `@end_date`, `start_date` |
| 国家站点 | `site` | `country` |
| 店铺 | `store` | `seller_name_new` |
| 站点分组 | 暂未独立筛选 | `country_category` |
| 负责人 | `owner` | 当前 SQL 未产出，需要后续维表 |
| 是否超限价 | `over_limit` | `筛选_现价高于限价` |
| 日销分层 | `daily_sales_band` | `日销销量区间` |
| 毛利率分层 | `margin_band` | `毛利率分类` |
| 关键词 | `keyword` | `seller_sku_adj`, `local_sku`, 后续可加商品名/ASIN |

## 6. 基础清洗逻辑

### 6.1 店铺清洗

```sql
left(seller_name, locate('-', seller_name) - 1) as seller_name_new
```

注意：如果 `seller_name` 不包含 `-`，该表达式可能得到空值，建议后续实现时加保护：

```sql
case
    when locate('-', seller_name) > 0 then left(seller_name, locate('-', seller_name) - 1)
    else seller_name
end as seller_name_new
```

### 6.2 SKU 清洗

```sql
if(
    length(substring_index(seller_sku, ',', 1)) > 16,
    replace(substring_index(substring_index(seller_sku, ',', 1), '-', 1), 'amzn.gr.', ''),
    substring_index(seller_sku, ',', 1)
) as seller_sku_adj
```

### 6.3 站点分组

```sql
case
    when country = '英国' then '英国站'
    when country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
    else '欧洲站'
end as country_category
```

### 6.4 不含税销售额

当前 SQL 按国家税率折算：

```sql
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
```

## 7. 产品表现核心指标

| 指标 | SQL 字段 | 计算逻辑 |
| --- | --- | --- |
| 销量 | `销量` | `sum(volume)` |
| 销售额 | `销售额` | `sum(amount)` |
| 销售额_不含税 | `销售额_不含税` | 按国家税率折算后 `sum(...)` |
| 原订单毛利润 | `原订单毛利润` | `sum(predict_gross_profit)` |
| 订单毛利润 | `订单毛利润` | `sum(case when volume = 0 then 0 else predict_gross_profit end)` |
| 是否异常 | `是否异常` | `volume = 0 且 predict_gross_profit != 0` 或 `amount < abs(predict_gross_profit)` |
| 结算毛利润 | `结算毛利润` | `sum(gross_profit)` |
| 订单毛利率 | `订单毛利率` | `round(sum(订单毛利润) / nullif(sum(销售额_不含税), 0), 2)` |
| 有库存的天数 | `有库存的天数` | `sum(case when afn_fulfillable_quantity <> 0 then 1 else 0 end)` |
| 统计天数 | `统计天数` | `abs(datediff(@start_date, @end_date)) + 1` |
| 日销 | `日销` | `sum(销量) / 统计天数` |
| 日销_有库存天数 | `日销_有库存天数` | `sum(销量) / 有库存的天数` |
| 异常天数 | `异常天数` | `sum(是否异常)` |
| 全部异常 | `统计周期内是否全部异常` | `统计天数 = 异常天数` |

## 8. 广告指标

| 指标 | SQL 字段 | 计算逻辑 |
| --- | --- | --- |
| 广告花费 | `广告花费` | `sum(spend)` |
| 广告订单量 | `广告订单量` | `sum(ad_order_quantity)` |
| 广告销售额 | `广告销售额` | `sum(ad_sales_amount)` |
| 广告点击量 | `广告点击量` | `sum(clicks)` |
| 广告曝光量 | `广告曝光量` | `sum(impressions)` |
| ACOS | `acos` | `round(sum(广告花费) / nullif(sum(广告销售额), 0), 2)` |
| TACOS | `tacos` | `round(sum(广告花费) / nullif(sum(销售额), 0), 2)` |
| CTR | `ctr` | `round(sum(广告点击量) / nullif(sum(广告曝光量), 0), 2)` |

## 9. 价格与限价指标

### 9.1 现价

来源：

```sql
etl_datasync.etl_dispose_lx_sales_mws_listing
```

过滤：

```sql
where date(create_time) = curdate()
```

字段：

| 指标 | SQL 字段 |
| --- | --- |
| 现价 | `price` |
| 现价币种 | `org_currency_icon` |
| 现价人民币 | `round(price * rate_org, 2)` |

### 9.2 汇率

来源：

```sql
dwd_datasync.lx_basic_currency
where date = date_format(curdate(), '%Y-%m')
```

关联：

```sql
现价_listing.org_currency_icon = lx_basic_currency.name
```

### 9.3 限价

来源：

```sql
temporary_APP.yd_product_pricing_schedule
```

过滤：

```sql
where date(create_time) = curdate()
  and target_margin = 0.35
  and shipping_method = '铁路'
```

字段：

| 指标 | SQL 字段 |
| --- | --- |
| 限价 | `tax_inclusive_price` |
| 限价_不包含广告 | `tax_inclusive_price_noad` |
| 限价修正 | `tax_inclusive_price_adj` |
| 目标毛利率 | `target_margin` |
| 运输方式 | `shipping_method` |

### 9.4 超限价

```sql
case when 现价 > nullif(限价, 0) then 1 else 0 end as 筛选_现价高于限价
```

## 10. 库存指标

### 10.1 本地库存/补货建议

来源：

```sql
etl_datasync.etl_dispose_lx_replenishment_suggest_restocking
```

当前汇总：

```sql
max(sc_quantity_local_valid)
+ max(sc_quantity_purchase_shipping)
+ max(sc_quantity_purchase_plan)
+ max(sc_quantity_local_qc) as local_quantity
```

输出字段：

| 页面字段 | SQL 字段 |
| --- | --- |
| fba可售库存_本地库存 | `local_quantity` |

### 10.2 FBA 库存

来源：

```sql
etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
```

字段映射：

| 页面字段 | SQL 字段 | 含义 |
| --- | --- | --- |
| fba总库存 | `total` | 总库存 |
| fba总库存成本 | `total_price` | 总库存成本 |
| fba可用库存 | `available_total` | 可用库存 |
| fba可用库存成本 | `available_price` | 可用库存成本 |
| fba可售库存 | `afn_fulfillable_quantity` | FBA 可售 |
| 待调仓 | `reserved_fc_transfers` | 待调仓 |
| 调仓中 | `reserved_fc_processing` | 调仓中 |
| 待发货 | `reserved_customerorders` | 待发货 |
| 不可售库存 | `afn_unsellable_quantity` | 不可售 |
| 计划入库 | `afn_inbound_working_quantity` | 计划入库 |
| 实际在途 | `stock_up_num` | 实际在途 |
| 调查中 | `afn_researching_quantity` | 调查中 |
| 总可用库存 | `total_fulfillable_quantity` | 总可用库存 |

### 10.3 库存可售天数

```sql
case
    when (coalesce(可售库存_本地库存, 0) + coalesce(库存, 0)) > 0
         and (销量 = 0 or 有库存的天数 = 0)
        then '99999'
    when (coalesce(可售库存_本地库存, 0) + coalesce(库存, 0)) > 0
         and (销量 > 0 and 有库存的天数 > 0)
        then round((可售库存_本地库存 + 库存) / 日销_有库存天数, 0)
    when (coalesce(可售库存_本地库存, 0) + coalesce(库存, 0)) = 0
        then 0
end as fba库存_本地库存可售天数
```

## 11. 分层规则

### 11.1 毛利率分类

当前 SQL 输出：

```sql
case
    when 订单毛利率 >= 0.35 then '毛利率>0.35'
    when 订单毛利率 >= 0.25 and 订单毛利率 < 0.35 then '毛利率0.25-0.35'
    when 订单毛利率 >= 0.15 and 订单毛利率 < 0.25 then '毛利率0.15-0.25'
    when 订单毛利率 >= 0.1 and 订单毛利率 < 0.15 then '毛利率0.1-0.15'
    when 订单毛利率 >= 0 and 订单毛利率 < 0.1 then '毛利率0.05-0.1'
    else '毛利率小于0'
end as 毛利率分类
```

页面当前展示标签建议映射为：

| SQL 标签 | 页面标签 |
| --- | --- |
| `毛利率>0.35` | `毛利率 >35%` |
| `毛利率0.25-0.35` | `毛利率 25-35%` |
| `毛利率0.15-0.25` | `毛利率 15-25%` |
| `毛利率0.1-0.15` | `毛利率 10-15%` |
| `毛利率0.05-0.1` | `毛利率 0-10%` |
| `毛利率小于0` | `毛利率 <0%` |

待确认：`毛利率0.05-0.1` 的 SQL 条件实际是 `0 <= 毛利率 < 0.1`，建议命名为 `毛利率0-0.1` 或直接输出页面标签。

### 11.2 日销分层

当前 SQL 输出：

```sql
case
    when 日销 < 1 and 日销 > 0 then '日销销量<1'
    when 日销 >= 1 and 日销 < 5 then '日销销量1-5'
    when 日销 >= 5 then '日销销量大于5'
    else '日销销量0'
end as 日销销量区间
```

页面当前展示标签建议映射为：

| SQL 标签 | 页面标签 |
| --- | --- |
| `日销销量0` | `日销 0` |
| `日销销量<1` | `日销 <1` |
| `日销销量1-5` | `日销 1-5` |
| `日销销量大于5` | `日销 >5` |

待确认：当前 SQL 用 `日销 >= 5` 归入“大于5”，页面文案是 `>5`。如果严格按页面文案，建议 SQL 改为 `日销 > 5`，并把 `日销 = 5` 放入 `1-5`。

## 12. 页面字段映射

| 页面/API 字段 | 当前 SQL 字段 |
| --- | --- |
| `stat_period` | `统计周期` |
| `store` | `seller_name_new` |
| `raw_store` | `seller_name` |
| `sku` | `seller_sku_adj` |
| `country_category` | `country_category` |
| `site` | `country` |
| `local_sku` | `local_sku` |
| `scoped_sales` | `销量` |
| `scoped_revenue` | `销售额` |
| `revenue_ex_tax` | `销售额_不含税` |
| `order_gross_profit` | `订单毛利润` |
| `raw_order_gross_profit` | `原订单毛利润` |
| `order_gross_margin` | `订单毛利率` |
| `margin_band` | `毛利率分类` |
| `settlement_gross_profit` | `结算毛利润` |
| `filter_flag` | `筛选` |
| `current_price_cny` | `现价_人民币` |
| `price_currency` | `现价_币种` |
| `current_price` | `现价` |
| `limit_price` | `限价` |
| `over_limit` | `筛选_现价高于限价` |
| `shipping_method` | `运输方式` |
| `target_margin` | `目标毛利率` |
| `limit_price_without_ad` | `限价_不包含广告` |
| `in_stock_days` | `有库存的天数` |
| `stat_days` | `统计天数` |
| `abnormal_days` | `异常天数` |
| `all_abnormal` | `统计周期内是否全部异常` |
| `daily_sales` | `日销` |
| `daily_sales_in_stock_days` | `日销_有库存天数` |
| `daily_sales_in_stock_band` | `日销_有库存天数销量区间` |
| `daily_sales_band` | `日销销量区间` |
| `ad_spend` | `广告花费` |
| `ad_orders` | `广告订单量` |
| `ad_sales` | `广告销售额` |
| `ad_clicks` | `广告点击量` |
| `ad_impressions` | `广告曝光量` |
| `acos` | `acos` |
| `tacos` | `tacos` |
| `ctr` | `ctr` |
| `fba_total_inventory` | `fba总库存` |
| `fba_total_inventory_cost` | `fba总库存成本` |
| `fba_available_inventory` | `fba可用库存` |
| `fba_available_inventory_cost` | `fba可用库存成本` |
| `fba_sellable_inventory` | `fba可售库存` |
| `pending_transfer` | `待调仓` |
| `transferring_qty` | `调仓中` |
| `pending_shipment` | `待发货` |
| `unsellable_inventory` | `不可售库存` |
| `planned_inbound` | `计划入库` |
| `actual_in_transit` | `实际在途` |
| `under_investigation` | `调查中` |
| `total_available_inventory` | `总可用库存` |
| `local_sellable_inventory` | `fba可售库存_本地库存` |
| `local_stock_sellable_days` | `fba库存_本地库存可售天数` |

当前 SQL 未直接产出但页面 mock 中存在的字段：

| 字段 | 建议 |
| --- | --- |
| `asin` | 后续接商品维表；迁移初期可置空 |
| `product_name` | 当前可临时用 `seller_sku_adj + country` 或后续商品维表 |
| `brand` | 后续商品维表 |
| `category` | 当前可临时用 `country_category`，后续商品维表 |
| `owner` | 后续店铺/商品负责人维表 |
| `rating` | 后续评论/商品表现源 |
| `review_count` | 后续评论/商品表现源 |

## 13. Dashboard 指标 SQL 占位

### 13.1 公共宽表占位

```sql
-- SQL_DASHBOARD_WIDE
-- 这里放当前原始 SQL 最后 select from d 的结果。
-- 建议未来落为一张中间表，例如 etl_datasync.dashboard_product_period_wide。
select *
from dashboard_product_period_wide
where period_start = :start_date
  and period_end = :end_date;
```

### 13.2 公共筛选

```sql
-- SQL_FILTER_BASE
where (:site = 'all' or t.country = :site)
  and (:store = 'all' or t.seller_name_new = :store)
  and (:owner = 'all' or t.owner = :owner)
  and (:over_limit = 'all'
       or (:over_limit = 'yes' and t.筛选_现价高于限价 = 1)
       or (:over_limit = 'no' and t.筛选_现价高于限价 = 0))
  and (:daily_sales_band = 'all' or t.日销销量区间 = :daily_sales_band)
  and (:margin_band = 'all' or t.毛利率分类 = :margin_band)
  and (
       :keyword = ''
       or t.seller_sku_adj like concat('%', :keyword, '%')
       or t.local_sku like concat('%', :keyword, '%')
       or t.seller_name_new like concat('%', :keyword, '%')
       or t.country like concat('%', :keyword, '%')
  )
```

### 13.3 KPI

```sql
-- SQL_DASHBOARD_KPIS
select
    count(*) as active_sku,
    sum(t.销售额) as revenue,
    sum(t.销量) / nullif(count(*) * max(t.统计天数), 0) as avg_daily_sales,
    sum(t.订单毛利润) / nullif(sum(t.销售额_不含税), 0) as avg_margin,
    sum(t.fba可售库存) as fba_sellable,
    sum(t.实际在途) as actual_in_transit,
    sum(t.不可售库存) as unsellable,
    sum(t.广告花费) as ad_spend,
    sum(t.广告花费) / nullif(sum(t.广告销售额), 0) as acos,
    sum(t.广告花费) / nullif(sum(t.销售额), 0) as tacos
from ({SQL_DASHBOARD_WIDE}) t
-- paste SQL_FILTER_BASE here
;
```

### 13.4 日销分层图

```sql
-- SQL_DAILY_SALES_CHART
select
    t.日销销量区间 as name,
    count(*) as value,
    sum(case when t.筛选_现价高于限价 = 1 then 1 else 0 end) as over_limit
from ({SQL_DASHBOARD_WIDE}) t
-- paste SQL_FILTER_BASE here
group by t.日销销量区间;
```

### 13.5 毛利率分层图

```sql
-- SQL_MARGIN_CHART
select
    t.毛利率分类 as name,
    count(*) as value,
    sum(case when t.筛选_现价高于限价 = 1 then 1 else 0 end) as over_limit
from ({SQL_DASHBOARD_WIDE}) t
-- paste SQL_FILTER_BASE here
group by t.毛利率分类;
```

### 13.6 日销 × 毛利率矩阵

```sql
-- SQL_DASHBOARD_MATRIX
select
    t.毛利率分类 as margin_band,
    t.日销销量区间 as daily_sales_band,
    count(*) as count,
    count(*) / nullif(total.total_count, 0) as ratio
from ({SQL_DASHBOARD_WIDE}) t
cross join (
    select count(*) as total_count
    from ({SQL_DASHBOARD_WIDE}) x
    -- paste SQL_FILTER_BASE here, alias should be x
) total
-- paste SQL_FILTER_BASE here
group by t.毛利率分类, t.日销销量区间, total.total_count;
```

## 14. 明细页 SQL 占位

```sql
-- SQL_DETAIL_LIST
select
    concat(t.seller_name_new, '-', t.seller_sku_adj, '-', t.country, '-', t.local_sku) as id,
    t.country as site,
    t.seller_name_new as store,
    t.seller_sku_adj as sku,
    '' as asin,
    t.seller_sku_adj as product_name,
    '' as brand,
    t.country_category as category,
    t.日销 as daily_sales,
    t.日销销量区间 as daily_sales_band,
    t.订单毛利率 as order_gross_margin,
    t.毛利率分类 as margin_band,
    null as sales_7d,
    t.销量 as sales_30d,
    t.销售额 as revenue_30d,
    t.现价 as current_price,
    t.限价 as limit_price,
    t.现价 - t.限价 as price_gap,
    t.筛选_现价高于限价 as over_limit,
    t.fba可售库存 as fba_sellable_inventory,
    t.fba库存_本地库存可售天数 as stock_days,
    null as rating,
    null as review_count,
    null as owner
from ({SQL_DASHBOARD_WIDE}) t
-- paste SQL_FILTER_BASE here
order by t.销售额 desc, t.日销 desc, t.seller_sku_adj
limit :page_size offset :offset;
```

```sql
-- SQL_DETAIL_COUNT
select count(*) as total
from ({SQL_DASHBOARD_WIDE}) t
-- paste SQL_FILTER_BASE here
;
```

## 15. 详情抽屉与趋势 SQL 占位

当前最终宽表可以直接支持抽屉基础信息。销售额趋势需要从日聚合表 `etl_datasync.product_performance_90_days` 或未来的每日事实中间表读取。

```sql
-- SQL_DETAIL_RECORD
select
    concat(t.seller_name_new, '-', t.seller_sku_adj, '-', t.country, '-', t.local_sku) as id,
    concat(t.seller_sku_adj, ' · ', t.seller_name_new, ' / ', t.country) as title,
    t.country as site,
    t.seller_name_new as store,
    t.seller_sku_adj as sku,
    '' as asin,
    null as owner,
    '' as brand,
    t.country_category as category,
    t.统计周期 as stat_period,
    t.销售额 as current_revenue,
    t.日销 as current_daily_sales,
    t.订单毛利率 as current_margin,
    t.现价 as current_price,
    t.fba可售库存 as fba_sellable_inventory,
    t.fba库存_本地库存可售天数 as stock_days
from ({SQL_DASHBOARD_WIDE}) t
where concat(t.seller_name_new, '-', t.seller_sku_adj, '-', t.country, '-', t.local_sku) = :item_id;
```

```sql
-- SQL_DETAIL_REVENUE_TREND
select
    p.dt_date as label,
    sum(p.销售额) as value
from etl_datasync.product_performance_90_days p
where concat(p.seller_name_new, '-', p.seller_sku_adj, '-', p.country, '-', p.local_sku) = :item_id
  and p.dt_date between date_sub(:end_date, interval (:trend_days - 1) day) and :end_date
group by p.dt_date
order by p.dt_date;
```

## 16. 待确认事项

| 项目 | 当前情况 | 建议 |
| --- | --- | --- |
| 默认周期 | SQL 写死 `2026-01-01` 至 `2026-03-31` | 迁移前改为 API 参数或默认滚动 90 天 |
| 商品名/ASIN/品牌/类目 | 当前 SQL 未产出完整商品维度 | 如页面需要真实展示，补商品维表 |
| 负责人 | 当前 SQL 未产出 | 补店铺负责人或 SKU 负责人维表 |
| 评分/评论数 | 当前 SQL 未产出 | 可先置空，后续补评论源 |
| 日销 5 的归属 | SQL 把 `日销 >= 5` 归到“大于5” | 建议确认是否改为 `> 5` |
| 毛利率 0-10 标签 | SQL 标签写 `毛利率0.05-0.1`，条件是 `0-0.1` | 建议改标签避免误解 |
| 价格/库存快照日期 | SQL 使用 `curdate()` | 每日任务需要明确用 `biz_date` 还是 `snapshot_date` |
| `month_end_data_*` 命名 | 实际 SQL 用的是当天快照 | 建议改成 daily snapshot 命名 |

## 17. 后续迁移建议

1. 先把当前最终 `select from d` 落成一张稳定的看板宽表或视图。
2. 保持 API 返回结构不变，只替换后端 service 的数据来源。
3. SQL 标签最好直接输出页面展示标签，减少 Python 再映射。
4. 对默认首页可用预聚合宽表，对自定义日期筛选可从日聚合表实时聚合。
5. 迁移前先用一组固定日期对比 SQL 导出结果、静态原型结果、FastAPI 页面结果。
