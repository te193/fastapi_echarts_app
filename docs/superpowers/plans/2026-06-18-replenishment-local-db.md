# Replenishment Local DB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `data/跟卖补货6.4最终修改.sql` 改造成每天可复跑的本地补货 ETL，先用当天产品表现宽表生成补货基础池，再按当天库存和滚动销售表现计算“哪些 SKU 需要补货”。

**Architecture:** 周表 SQL 只作为指标来源和计算逻辑参考，不生成周报表，不依赖 `ops_weekly_rpt_prod_perf_interim` 或 `ops_weekly_rpt_prod_perf_data_2026` 落表。补货 ETL 在一次本地任务内构造 session 临时表，远端只读拉取源数据，本地读取每日快照表，最终按 `snapshot_date` 删除重算 `{target_schema}.dashboard_pur_plan_replenish_data`。

**Tech Stack:** Python 3, PyMySQL, MySQL 8 CTE/window functions, existing `etl.dashboard_daily_update` connection/config/log helpers, pytest.

---

## 1. Updated Decision

### 1.1 周表不再是补货前置产物

`data/运营周表_2512.sql` 的作用改为参考口径：

- 参考 `ops_weekly_rpt_prod_perf_interim` 如何从产品表现表计算滚动销量、销售额、订单毛利。
- 参考 `ops_weekly_rpt_prod_perf_data_2026` 如何拼 listing、货件、利润分类、库存、补货建议、物流天数。
- 不在本地单独生成周表。
- 补货任务不再用 `year_week = yearweek(date_sub(curdate(), interval 1 week), 1)` 作为主商品池入口。

### 1.2 补货每天独立计算

补货 ETL 每天使用两个日期：

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `biz_date` | 昨天 | 销售表现、可售天数、历史同期窗口的统计截止日 |
| `snapshot_date` | 今天 | FBA 库存、本地库存、采购计划、最终结果日期 |
| `candidate_days` | `1` | 补货基础池回看天数；默认只取 `biz_date` 当天产品表现宽表 |

结果表按 `snapshot_date` 重算：

```sql
delete from `{target_schema}`.`dashboard_pur_plan_replenish_data`
where cur_date = %(snapshot_date)s;
```

基础池默认只取当天：

```sql
where dt_date = %(biz_date)s
```

原因是产品表现表是每日全量大宽表，无论 SKU 当天是否有销售，基本都会出现。默认 `candidate_days = 1` 可以复刻周表“从产品表现表取 SKU，再按三维聚合”的入口，同时避免滚动 7 天把已经不该参与当天补货的旧 SKU 带入。`candidate_days` 保留为参数只是兜底，如果后续发现某天源表同步不完整，可以临时改为 3 或 7。

### 1.3 库存改为当天快照

原 SQL 的周维度库存来源：

```sql
from etl_datasync.ops_weekly_rpt_fba_inv_detail_basic_data
where dt_week = yearweek(date_sub(curdate(), interval 0 week), 1)
```

```sql
from etl_datasync.ops_weekly_rpt_replenish_sug_basic_data
where dt_week = yearweek(date_sub(curdate(), interval 0 week), 1)
```

改为本地每日快照：

```text
{target_schema}.dashboard_inventory_daily_snapshot
where snapshot_date = %(snapshot_date)s
```

```text
{target_schema}.dashboard_restock_daily_snapshot
where snapshot_date = %(snapshot_date)s
```

当天库存快照缺失时，补货 ETL 应失败并写入日志，不自动 fallback 到最近一天。

### 1.4 本地库核对结果

项目里的本地写库配置来自 `config/database.ini` 的 `[target]` 段；当前核对到的本地库是：

```text
host = 192.168.112.235
port = 3306
database = etl_datasync_test
target_schema = etl_datasync_test
```

实现时不要把这套“本地写库”与远端只读源库混用。`etl.dashboard_daily_update.connect_target()` 仍然通过 `DASHBOARD_DB_*` 环境变量连接；如果运行环境没有注入环境变量，需要先接入 `config/database.ini`，或由部署脚本把 `database.ini` 的值写入环境变量。

当前 `config/database.ini` 的 `[source]` 段仍是 `REMOTE_*` 占位配置，不能直接用于远端源表拉取。后续编码时要把这个作为显式前置校验：本地快照链路可以只依赖 `[target]`，但凡是需要 listing、product info、FBA 货件、结算毛利、月表、季表、物流预计到货的 session temp，都必须先确认远端只读源库连接和 schema 已配置完成，否则任务应失败并提示缺少 source 配置。

本地库已经存在并可直接复用：

| 本地表 | 日期覆盖 | 补货用途 |
| --- | --- | --- |
| `etl_datasync_test.dashboard_product_performance_daily` | `dt_date` = `2025-12-11` ~ `2026-06-17`，最新日约 18,559 行 | 候选池、90/30/14/7/3 天销量/销售额/订单毛利滚动指标 |
| `etl_datasync_test.dashboard_inventory_daily_snapshot` | `snapshot_date` = `2026-04-30` ~ `2026-06-18`，最新日约 8,138 行 | 当天 FBA 库存、可用库存、实际在途、不可售 |
| `etl_datasync_test.dashboard_restock_daily_snapshot` | `snapshot_date` = `2026-04-30` ~ `2026-06-18`，最新日约 4,592 行 | 当天本地可用、待交付、采购计划、待检待上架、本地库存 |
| `etl_datasync_test.dashboard_product_period_7d_snapshot` | 最新到 `2026-06-18` | 可参考 7 天聚合，但补货主链路仍建议从日表按基础池重算 |
| `etl_datasync_test.dashboard_product_period_14d_snapshot` | 最新到 `2026-06-18` | 可参考 14 天聚合 |
| `etl_datasync_test.dashboard_product_period_30d_snapshot` | 最新到 `2026-06-18` | 可参考 30 天聚合 |
| `etl_datasync_test.dashboard_product_period_90d_snapshot` | 最新到 `2026-06-18` | 可参考 90 天聚合 |
| `etl_datasync_test.dashboard_product_period_last_month_snapshot` | 最新到 `2026-06-18` | 可辅助上月表现类指标 |
| `etl_datasync_test.dashboard_inventory_weekly_snapshot` | 最新到 `2026-06-18` | 周聚合库存，只作校验参考，不作为每日补货主口径 |

本地库当前不存在、必须远端只读拉取或新增本地快照：

| 缺失表/数据 | 缺失影响 | 处理方式 |
| --- | --- | --- |
| `dashboard_pur_plan_replenish_data` | 最终补货落表不存在 | 新建本地结果表 |
| `pur_plan_prod_perf_salable_days_stat` | 可售天数长期表不存在 | 可用本地 `dashboard_product_performance_daily.afn_fulfillable_quantity` 重算并新建 |
| `etl_dispose_lx_sales_mws_listing` | 缺 `global_tags`、ASIN、listing 商品信息 | 远端拉取到 session temp，或新增本地 listing 快照 |
| `etl_dispose_lx_product_local_product_info` | 缺品牌、采购价、头程、箱规 | 远端拉取到 session temp，或新增本地 product info 快照 |
| `etl_dispose_lx_fba_shipment` | 缺 `receiving_cnt`、`max_receiving_time` | 远端拉取到 session temp，或新增本地 FBA 货件快照 |
| `etl_dispose_lx_statistics_profit_statistics_msku` | 严格结算毛利 `abcd_category/gp_margin_range` 无法直接复刻 | 远端拉取；若接受近似，可用本地订单毛利重算 |
| `ops_monthly_rpt_prod_perf_basic_data` | 缺 `pre_1m_predict_abcd_category` 原口径 | 远端拉取；或用本地 last month period snapshot 重算近似 |
| `ops_quarter_rpt_prod_perf_basic_data` | 缺 `pre_1q_predict_abcd_category` 原口径 | 远端拉取；或用本地日表按季度窗口重算 |
| `ops_rpt_logi_est_days_data` / FBA 发货单源表 | 缺物流预计到货时间 | 远端拉取物流结果表，或远端重算后落 session temp |

## 2. 两个周表中间表的替代方案

### 2.0 每日补货基础池入口

周表过去的基础池本质是：

```text
产品表现表最近一周出现过的明细
+ seller_sku_adj 长度 5-10
+ 排除异常店铺
+ 按 country_category + seller_name_new + seller_sku_adj 聚合
```

每日补货直接复刻这个入口，但时间窗口改成当天产品表现宽表：

```text
tmp_pur_plan_candidate_keys
```

粒度：

```text
country_category + seller_name_new + seller_sku_adj
```

原周表参考 SQL，只用于说明原入口逻辑，不是每日实现 SQL：

```sql
create temporary table tmp_pur_plan_candidate_keys as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    max(local_sku) as max_sku,
    max(local_name) as max_local_name,
    max(asin) as max_asin
from `{etl_source_schema}`.`etl_dispose_lx_statistics_product_performance_2026`
where start_date between date_sub(%(biz_date)s, interval (%(candidate_days)s - 1) day)
                     and %(biz_date)s
  and seller_name not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
  and seller_name_new not in ('gushili', 'Joochees', 'ouhao', 'pingter')
  and seller_sku_adj is not null
  and seller_sku_adj <> ''
  and length(seller_sku_adj) between 5 and 10
group by country_category, seller_name_new, seller_sku_adj;
```

本地库核对后，实际实现使用本地日表，不再默认远端拉产品表现源表：

```sql
create temporary table tmp_pur_plan_candidate_keys as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    max(local_sku) as max_sku
from `{target_schema}`.`dashboard_product_performance_daily`
where dt_date between date_sub(%(biz_date)s, interval (%(candidate_days)s - 1) day)
                  and %(biz_date)s
  and seller_name not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
  and seller_name_new not in ('gushili', 'Joochees', 'ouhao', 'pingter')
  and seller_sku_adj is not null
  and seller_sku_adj <> ''
  and length(seller_sku_adj) between 5 and 10
group by country_category, seller_name_new, seller_sku_adj;
```

`max_local_name`、`max_asin` 不从本地日表取；本地 `dashboard_product_performance_daily` 没有这两个字段，应由后续 `tmp_listing_product_daily` 从远端 listing/product info 补齐。

`candidate_days = 1` 时等价于只取当天。后续所有补货计算都以 `tmp_pur_plan_candidate_keys` 为入口；不要再用销量、库存、在售状态提前筛掉 SKU，避免漏掉真正需要补货但当天销量为 0 的产品。

### 2.1 替代周表产品表现中间表

旧来源：

```sql
from etl_datasync.ops_weekly_rpt_prod_perf_interim
```

新方案：

在补货 ETL 内直接从本地产品表现日表计算滚动指标，但只保留基础池内 SKU：

```sql
from `{target_schema}`.`dashboard_product_performance_daily`
where dt_date >= date_sub(%(biz_date)s, interval 89 day)
  and dt_date <= %(biz_date)s
```

输出临时表：

```text
tmp_prod_perf_sku_metrics
```

粒度：

```text
country_category + seller_name_new + seller_sku_adj
```

保留字段：

| 字段 | 口径 |
| --- | --- |
| `cur_date` | `%(biz_date)s` |
| `sales_90/30/14/7/3` | 对应滚动窗口内 `sum(sales_qty)` |
| `amount_30/14/7/3` | 对应滚动窗口内 `sum(sales_amount)` |
| `pprofit_30/14/7/3` | 对应滚动窗口内 `sum(order_gross_profit)` |
| `pprofit_ratio_30/14/7/3` | `pprofit_x / nullif(amount_x, 0)` |

实现时需要 inner join `tmp_pur_plan_candidate_keys`：

```sql
inner join tmp_pur_plan_candidate_keys c
        on p.country_category = c.country_category
       and p.seller_name_new = c.seller_name_new
       and p.seller_sku_adj = c.seller_sku_adj
```

这样可以避免对全部历史产品跑滚动指标。本地 `dashboard_product_performance_daily` 不含 `asin` 和 `local_name`；跟卖补偿如果必须按 ASIN 找原品牌销量，需要在跟卖补偿链路里额外从远端产品表现源表或 listing 源表拉取 ASIN 映射，不作为基础池入口。

### 2.2 替代 `tmp_pur_plan_wd_current`

旧来源：

```sql
from dws_datasync.ops_weekly_rpt_prod_perf_data_2026
where year_week = yearweek(date_sub(curdate(), interval 1 week), 1)
```

新方案：

在补货 ETL 内生成每日商品基础池：

```text
tmp_pur_plan_daily_base
```

粒度：

```text
country_category + seller_name_new + seller_sku_adj
```

字段来源：

| 字段 | 新来源 | 说明 |
| --- | --- | --- |
| 三维 key | `tmp_pur_plan_candidate_keys` | 基础池入口，只取当天产品表现宽表聚合出的 SKU |
| `new_old_product` | listing/product info 原逻辑 | 参考周表 `ops_rpt_listing_prod_basic_data` 的新品/老品判断 |
| `principal`, `sales_team_1` | listing/product info 原逻辑 | 负责人和运营团队 |
| `max_sku`, `max_local_name`, `global_tags`, `max_brand_name` | listing/product info 原逻辑 | 商品基础信息 |
| `max_cg_transport_costs`, `max_cg_price`, `max_cg_box_pcs` | product info 原逻辑 | 采购成本、头程、箱规 |
| `max_receiving_time`, `receiving_cnt` | FBA 货件源表原逻辑 | 参考周表 `ops_rpt_fba_shipment_basic_data` |
| `abcd_category`, `gp_margin_range` | 结算利润源表滚动/最近周期计算 | 作为补货展示字段，不作为候选池入口 |
| `predict_abcd_category` | 产品表现滚动毛利和日销计算 | 作为补货展示字段，不作为候选池入口 |
| `pre_1m_predict_abcd_category`, `pre_1q_predict_abcd_category` | 月度/季度分类原逻辑或最近可用分类 | 作为补充字段 |
| `stockout_status` | 当天库存 + 当天本地库存 + 日销实时判断 | 不再复用周表值 |
| `max_fnsku`, `max_asin`, `marketplace_status` | listing 源表 | 作为最终展示和后续跟卖补偿辅助字段 |

候选池入口以 `tmp_pur_plan_candidate_keys` 为准，`tmp_pur_plan_daily_base` 只负责补字段，不再依赖任何 `year_week`。

### 2.3 周表字段每日重算映射

截图中原来直接从 `dws_datasync.ops_weekly_rpt_prod_perf_data_2026` 取的字段，不能直接删掉。每日版需要追到周表上游重新算：

| 原周表字段 | 周表上游逻辑 | 每日补货临时表 | 每日口径 |
| --- | --- | --- | --- |
| `global_tags` | `etl_dispose_lx_sales_mws_listing.global_tags` 聚合 | `tmp_listing_product_daily` | 基于 `tmp_pur_plan_candidate_keys` join listing，当天或最新 listing 快照，`group_concat(distinct global_tags)` |
| `max_brand_name` | `etl_dispose_lx_product_local_product_info.brand_name` | `tmp_listing_product_daily` | 按三维 key 取 `max(brand_name)` |
| `max_cg_transport_costs` | `etl_dispose_lx_product_local_product_info.cg_transport_costs` | `tmp_listing_product_daily` | 按三维 key 取 `max(cg_transport_costs)` |
| `max_cg_price` | `etl_dispose_lx_product_local_product_info.cg_price` | `tmp_listing_product_daily` | 按三维 key 取 `max(cg_price)` |
| `max_cg_box_pcs` | `etl_dispose_lx_product_local_product_info.cg_box_pcs` | `tmp_listing_product_daily` | 按三维 key 取 `max(cg_box_pcs)`，为空时后续补货箱规默认 50 |
| `max_receiving_time` | `etl_dispose_lx_fba_shipment.receiving_time` | `tmp_fba_shipment_receiving_daily` | `max(str_to_date(receiving_time, '%Y-%m-%d %H:%i:%s'))` |
| `receiving_cnt` | `etl_dispose_lx_fba_shipment` 收货记录数 | `tmp_fba_shipment_receiving_daily` | `receiving_time is not null and quantity_shipped <> 0` 时按 `msku + store_name` 计数，再回连到三维 key |
| `abcd_category` | `etl_dispose_lx_statistics_profit_statistics_msku` 周度结算毛利率分层 | `tmp_settlement_profit_recent` | 每日版可用 `biz_date` 往前 7 天或最近完整 7 天计算结算毛利率并分 A/B/C/D/E |
| `gp_margin_range` | 同 `abcd_category` | `tmp_settlement_profit_recent` | 按结算毛利率映射 `>=15%`, `10%-15%`, `5%-10%`, `0%-5%`, `<0%` |
| `predict_abcd_category` | 产品表现表订单毛利率 + 日销分层 | `tmp_prod_perf_sku_metrics` / `tmp_predict_category_daily` | 用基础池内 SKU 的近 7 天日销和订单毛利率重算 |
| `pre_1m_predict_abcd_category` | `ops_monthly_rpt_prod_perf_basic_data` 上月分类 | `tmp_monthly_predict_category` | 如果本地已有月表可读最新上月；否则按产品表现表上月窗口重算 |
| `pre_1q_predict_abcd_category` | `ops_quarter_rpt_prod_perf_basic_data` 前 1 季度分类 | `tmp_quarter_predict_category` | 如果本地已有季度表可读最近前 1 季度；否则按产品表现表季度窗口重算 |
| `stockout_status` | 周表最终 `available_salable_days` + 预计到货时间判断 | `tmp_stockout_status_daily` | 用当天库存、当天本地库存/采购计划、日销和物流预计到货时间重算 |

`stockout_status` 虽然是截图里从周表直接取的字段，但它还依赖周表内部字段 `expected_delivery_time`。每日版需要额外生成：

```text
tmp_logistics_expected_delivery_daily
```

这个表复刻周表 `ops_rpt_logi_est_days_data` 的上游逻辑：`dwd_datasync.lx_fba_shipment` 取在途/待发货货件，关联 `dwd_datasync.lx_inbound_shipment_detail_ShangPinLieBiao` 和 `dwd_datasync.lx_inbound_shipment_detail`，按物流渠道映射预计天数，得到 `earliest_ship_time + logistics_est_days = expected_delivery_time`。匹配时先按三维 key 精确匹配国家类别；英国站/欧洲站缺失时 fallback 到欧洲站发货记录。

`receiving_cnt` 是必需字段，不只是展示字段。补货 SQL 后面用它判断新品补货逻辑：

```sql
case
    when (max_brand_name like '%2025%' and (receiving_cnt <= 1 or receiving_cnt is null))
      or (max_brand_name like '%2026%' and (receiving_cnt <= 1 or receiving_cnt is null))
    then adjusted_daily_sales_3d * 0.5 + adjusted_daily_sales_7d * 0.5
    else adjusted_daily_sales_7d * 0.6
       + adjusted_daily_sales_14d * 0.2
       + adjusted_daily_sales_30d * 0.2
end as pre_daily_avg_sales
```

因此每日版必须先重算 `receiving_cnt` 和 `max_receiving_time`，再进入日销权重判断。

### 2.4 每日字段重算 SQL 形态

#### Listing/Product Info

```sql
create temporary table tmp_listing_product_daily as
select
    c.country_category,
    c.seller_name_new,
    c.seller_sku_adj,
    max(sml.local_sku) as max_sku,
    max(sml.fnsku) as max_fnsku,
    max(sml.asin) as max_asin,
    max(sml.marketplace_status) as marketplace_status,
    max(sml.local_name) as max_local_name,
    group_concat(distinct sml.global_tags separator ',') as global_tags,
    max(plpi.brand_name) as max_brand_name,
    max(plpi.cg_box_pcs) as max_cg_box_pcs,
    max(plpi.cg_price) as max_cg_price,
    max(plpi.cg_transport_costs) as max_cg_transport_costs,
    max(sml.principal) as principal,
    max(sml.sales_team_1) as sales_team_1,
    max(case
            when plpi.tag_name regexp '2027|2026|2025|2024 十月|2024 十一月|2024 十二月'
                then '新品'
            else '老品'
        end) as new_old_product
from tmp_pur_plan_candidate_keys c
left join `{etl_source_schema}`.`etl_dispose_lx_sales_mws_listing` sml
       on c.country_category = sml.country_category
      and c.seller_name_new = sml.seller_name_new
      and c.seller_sku_adj = sml.seller_sku
left join `{etl_source_schema}`.`etl_dispose_lx_product_local_product_info` plpi
       on sml.seller_sku = plpi.seller_sku
      and sml.marketplace = plpi.country
      and sml.seller_name_new = plpi.seller_name_new
      and sml.local_sku = plpi.local_sku
group by c.country_category, c.seller_name_new, c.seller_sku_adj;
```

#### FBA Receiving

```sql
create temporary table tmp_fba_shipment_receiving_daily as
select
    f.country_category,
    f.seller_name_new,
    f.msku as seller_sku_adj,
    min(str_to_date(nullif(f.receiving_time, ''), '%Y-%m-%d %H:%i:%s')) as min_receiving_time,
    max(str_to_date(nullif(f.receiving_time, ''), '%Y-%m-%d %H:%i:%s')) as max_receiving_time,
    max(rc.receiving_cnt) as receiving_cnt,
    datediff(%(snapshot_date)s, min(str_to_date(nullif(f.receiving_time, ''), '%Y-%m-%d %H:%i:%s'))) as days_since_launch,
    datediff(%(snapshot_date)s, max(str_to_date(nullif(f.receiving_time, ''), '%Y-%m-%d %H:%i:%s'))) as days_latest_delivery
from `{etl_source_schema}`.`etl_dispose_lx_fba_shipment` f
inner join tmp_pur_plan_candidate_keys c
        on f.country_category = c.country_category
       and f.seller_name_new = c.seller_name_new
       and f.msku = c.seller_sku_adj
left join (
    select
        msku,
        store_name,
        count(*) as receiving_cnt
    from `{etl_source_schema}`.`etl_dispose_lx_fba_shipment`
    where receiving_time is not null
      and receiving_time <> ''
      and quantity_shipped <> 0
    group by msku, store_name
) rc
       on f.msku = rc.msku
      and f.store_name = rc.store_name
where f.receiving_time is not null
  and f.receiving_time <> ''
  and f.quantity_received <> 0
group by f.country_category, f.seller_name_new, f.msku;
```

#### Recent Settlement Category

```sql
create temporary table tmp_settlement_profit_recent as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    sum(total_sales_amount) as total_sales_amount,
    sum(gross_profit) as gross_profit,
    sum(gross_profit) / nullif(sum(total_sales_amount), 0) as profit_margin,
    case
        when sum(gross_profit) / nullif(sum(total_sales_amount), 0) >= 0.15 then 'A'
        when sum(gross_profit) / nullif(sum(total_sales_amount), 0) >= 0.10 then 'B'
        when sum(gross_profit) / nullif(sum(total_sales_amount), 0) >= 0.05 then 'C'
        when sum(gross_profit) / nullif(sum(total_sales_amount), 0) >= 0.00 then 'D'
        else 'E'
    end as abcd_category,
    case
        when sum(gross_profit) / nullif(sum(total_sales_amount), 0) >= 0.15 then '>=15%'
        when sum(gross_profit) / nullif(sum(total_sales_amount), 0) >= 0.10 then '10%-15%'
        when sum(gross_profit) / nullif(sum(total_sales_amount), 0) >= 0.05 then '5%-10%'
        when sum(gross_profit) / nullif(sum(total_sales_amount), 0) >= 0.00 then '0%-5%'
        else '<0%'
    end as gp_margin_range
from `{etl_source_schema}`.`etl_dispose_lx_statistics_profit_statistics_msku`
where data_date between date_sub(%(biz_date)s, interval 6 day) and %(biz_date)s
  and store_name not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
group by country_category, seller_name_new, seller_sku_adj;
```

#### Daily Stockout Status

每日版不再用周表 `week_end`，改用 `snapshot_date`：

```sql
case
    when available_salable_days > 60
      or datediff(expected_delivery_time, %(snapshot_date)s) < available_salable_days
        then '不会缺货'
    when coalesce(stock_up_num, 0) = 0 and coalesce(local_quantity, 0) = 0
        then '缺货未补货'
    when coalesce(stock_up_num, 0) > 0 or coalesce(local_quantity, 0) > 0
        then '缺货已补货'
end as stockout_status
```

#### Logistics Expected Delivery

```sql
create temporary table tmp_logistics_expected_delivery_daily as
with shipment_base as (
    select
        shipment_id,
        substring_index(seller, ' ', 1) as seller_name_new,
        country,
        msku,
        shipment_status
    from `{dwd_source_schema}`.`lx_fba_shipment`
    where shipment_status in ('WORKING', 'READY_TO_SHIP', 'SHIPPED', 'IN_TRANSIT')
),
shipment_detail as (
    select
        splb.shipment_id,
        splb.sname,
        splb.shipment_sn,
        splb.msku,
        spd.shipment_time,
        spd.logistics_channel_name,
        splb.shipment_status
    from `{dwd_source_schema}`.`lx_inbound_shipment_detail_ShangPinLieBiao` splb
    left join `{dwd_source_schema}`.`lx_inbound_shipment_detail` spd
           on splb.shipment_sn = spd.shipment_sn
    where splb.shipment_status in ('WORKING', 'READY_TO_SHIP', 'SHIPPED', 'IN_TRANSIT')
),
joined_shipping as (
    select
        b.seller_name_new,
        case
            when b.country = '英国' then '英国站'
            when b.country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
            else '欧洲站'
        end as country_category,
        b.msku as seller_sku_adj,
        d.shipment_time,
        min(d.shipment_time) over (partition by d.sname, d.msku) as earliest_ship_time,
        case
            when d.logistics_channel_name regexp '空' then '空运'
            when d.logistics_channel_name regexp '铁' then '铁路'
            when d.logistics_channel_name regexp '海|航|卡派' then '海运'
        end as channel_abbrev,
        case
            when d.logistics_channel_name regexp '空' then 15
            when d.logistics_channel_name regexp '铁' then 45
            when d.logistics_channel_name regexp '海|航|卡派' then 60
        end as logistics_est_days
    from shipment_base b
    left join shipment_detail d
           on b.shipment_id = d.shipment_id
          and b.msku = d.msku
          and b.seller_name_new = d.sname
)
select distinct
    seller_name_new,
    country_category,
    seller_sku_adj,
    earliest_ship_time,
    channel_abbrev,
    logistics_est_days,
    date_add(earliest_ship_time, interval logistics_est_days day) as expected_delivery_time
from joined_shipping
where seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy|hongyuanEU'
  and earliest_ship_time = shipment_time
  and earliest_ship_time is not null
  and channel_abbrev is not null;
```

## 3. Daily Replenishment Flow

### 3.1 前置本地快照

补货运行前需要当天快照已经在本地存在：

| 表 | 日期字段 | 用途 |
| --- | --- | --- |
| `{target_schema}.dashboard_inventory_daily_snapshot` | `snapshot_date` | 当天 FBA 总库存、可用库存、实际在途、不可售 |
| `{target_schema}.dashboard_restock_daily_snapshot` | `snapshot_date` | 当天本地可用、待交付、采购计划、待检待上架、本地库存 |

补货任务启动时先检查：

```sql
select count(*) as inventory_rows
from `{target_schema}`.`dashboard_inventory_daily_snapshot`
where snapshot_date = %(snapshot_date)s;
```

```sql
select count(*) as restock_rows
from `{target_schema}`.`dashboard_restock_daily_snapshot`
where snapshot_date = %(snapshot_date)s;
```

任一为 0 则停止。

### 3.2 临时表顺序

```text
1. tmp_pur_plan_candidate_keys           -- 当天产品表现宽表聚合出的三维 key
2. tmp_prod_perf_sku_metrics             -- 本地日表重算基础池内 SKU 滚动产品表现
3. tmp_candidate_asin_mapping            -- 可选；跟卖补偿需要 ASIN 时从远端限量拉取
4. tmp_自有店铺品牌asin                  -- 自有品牌 ASIN
5. tmp_asin_to_self_store                -- ASIN -> 自有品牌店铺
6. tmp_origin_sales_all                  -- 原品牌店铺销量
7. tmp_prod_perf_follow_origin           -- 跟卖标记和原品牌销量补偿
8. tmp_listing_product_daily             -- listing/product info 重算商品基础字段
9. tmp_fba_shipment_receiving_daily      -- FBA 货件重算 receiving_cnt/max_receiving_time
10. tmp_settlement_profit_recent         -- 最近结算毛利重算 abcd_category/gp_margin_range
11. tmp_predict_category_daily           -- 产品表现重算 predict_abcd_category
12. tmp_monthly_predict_category         -- 上月或上月窗口重算 pre_1m_predict_abcd_category
13. tmp_quarter_predict_category         -- 前 1 季度或季度窗口重算 pre_1q_predict_abcd_category
14. tmp_logistics_expected_delivery_daily -- 在途货件物流预计到货时间
15. tmp_pur_plan_daily_base              -- 基于三维 key 汇总 listing/货件/分类字段
16. tmp_pur_plan_fba_current             -- 当天 FBA 库存快照
17. tmp_pur_plan_replenish_sug_current   -- 当天本地库存/采购计划快照
18. tmp_pur_plan_salable_days_current    -- 截至 biz_date 的可售天数
19. tmp_pur_plan_pre_daily_sales         -- 预估日销，依赖 receiving_cnt 新老品判断
20. tmp_stockout_status_daily            -- 当天库存口径重算 stockout_status
21. tmp_pur_plan_support_layer_all       -- 按库存支撑天数分层
22. tmp_pur_plan_support_layer_summary   -- 分层汇总，供看板展示
23. tmp_pur_plan_replenish_candidates    -- 只保留紧急/建议/计划补货进入后续重计算
24. tmp_pur_plan_hist_daily_*            -- 历史同期环比修正
25. tmp_lx_orders_profit_rate_*          -- 最近订单毛利率
26. final insert dashboard_pur_plan_replenish_data
```

### 3.3 库存输入口径

`tmp_pur_plan_fba_current`：

```sql
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    total,
    available_total,
    afn_fulfillable_quantity,
    stock_up_num,
    afn_unsellable_quantity
from `{target_schema}`.`dashboard_inventory_daily_snapshot`
where snapshot_date = %(snapshot_date)s;
```

`tmp_pur_plan_replenish_sug_current`：

```sql
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    local_quantity,
    purchase_shipping_quantity as sc_quantity_purchase_shipping,
    purchase_plan_quantity as sc_quantity_purchase_plan,
    local_valid_quantity as sc_quantity_local_valid,
    local_qc_quantity as sc_quantity_local_qc
from `{target_schema}`.`dashboard_restock_daily_snapshot`
where snapshot_date = %(snapshot_date)s;
```

## 4. Core Metrics

### 4.1 可售天数

产物：

```text
tmp_pur_plan_salable_days_current
```

口径：

| 指标 | 计算 |
| --- | --- |
| `r_90d_salable_days` | 近 90 天 `afn_fulfillable_quantity > 0` 的去重日期数 |
| `r_30d_salable_days` | 近 30 天 `afn_fulfillable_quantity > 0` 的去重日期数 |
| `r_14d_salable_days` | 近 14 天 `afn_fulfillable_quantity > 0` 的去重日期数 |
| `r_7d_salable_days` | 近 7 天 `afn_fulfillable_quantity > 0` 的去重日期数 |
| `r_3d_salable_days` | 近 3 天 `afn_fulfillable_quantity > 0` 的去重日期数 |
| `available_daily_sales_base` | `sales_30 / nullif(r_30d_salable_days, 0)`，用于估算当前库存还能卖几天 |
| `available_salable_days` | 当天 `available_total / nullif(available_daily_sales_base, 0)`；当 `available_total = 0` 时为 0 |

建议仍可落长期表：

```text
{target_schema}.pur_plan_prod_perf_salable_days_stat
```

但补货运行时以 `biz_date` 删除重算，避免重复。

`available_salable_days` 不能再从周表最终结果里取，必须在 `tmp_pur_plan_salable_days_current` 中每日重算并暴露给 `tmp_stockout_status_daily`。推荐 SQL 形态：

```sql
create temporary table tmp_pur_plan_salable_days_current as
select
    c.country_category,
    c.seller_name_new,
    c.seller_sku_adj,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 89 day)
              and coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end) as r_90d_salable_days,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 29 day)
              and coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end) as r_30d_salable_days,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 13 day)
              and coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end) as r_14d_salable_days,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 6 day)
              and coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end) as r_7d_salable_days,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 2 day)
              and coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end) as r_3d_salable_days,
    m.sales_30 / nullif(sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 29 day)
                                  and coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end), 0) as available_daily_sales_base,
    case
        when coalesce(f.available_total, 0) = 0 then 0
        else coalesce(f.available_total, 0)
             / nullif(m.sales_30 / nullif(sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 29 day)
                                                    and coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end), 0), 0)
    end as available_salable_days
from tmp_pur_plan_candidate_keys c
left join `{target_schema}`.`dashboard_product_performance_daily` p
       on c.country_category = p.country_category
      and c.seller_name_new = p.seller_name_new
      and c.seller_sku_adj = p.seller_sku_adj
      and p.dt_date between date_sub(%(biz_date)s, interval 89 day) and %(biz_date)s
left join tmp_prod_perf_sku_metrics m
       on c.country_category = m.country_category
      and c.seller_name_new = m.seller_name_new
      and c.seller_sku_adj = m.seller_sku_adj
left join tmp_pur_plan_fba_current f
       on c.country_category = f.country_category
      and c.seller_name_new = f.seller_name_new
      and c.seller_sku_adj = f.seller_sku_adj
group by
    c.country_category,
    c.seller_name_new,
    c.seller_sku_adj,
    m.sales_30,
    f.available_total;
```

### 4.2 跟卖销量补偿

规则保持原 SQL：

| 场景 | 最终销量 |
| --- | --- |
| 自有品牌 ASIN | 使用当前 SKU 自身销量 |
| 非自有品牌 ASIN 跟卖 | 当前 SKU 销量 + 原品牌店铺同 ASIN 销量 |

字段：

```text
fllow_flag
origin_sales_30d / 14d / 7d / 3d
final_sales_30d / 14d / 7d / 3d
```

### 4.3 预估日销

字段：

```text
adjusted_daily_sales_3d
adjusted_daily_sales_7d
adjusted_daily_sales_14d
adjusted_daily_sales_30d
daily_avg_sales
```

新品：

```text
daily_avg_sales = adjusted_daily_sales_3d * 0.5 + adjusted_daily_sales_7d * 0.5
```

老品：

```text
daily_avg_sales = adjusted_daily_sales_7d * 0.6
                + adjusted_daily_sales_14d * 0.2
                + adjusted_daily_sales_30d * 0.2
```

`tmp_pur_plan_pre_daily_sales` 输出的日销先命名为 `pre_daily_avg_sales`，用于库存支撑天数分层；最终 SQL 在跟卖补偿、历史环比和利润字段都补齐后，再输出 `daily_avg_sales`。

### 4.4 库存支撑天数分层

新增 SQL `data/跟卖补货6.4最终修改_库存支撑天数筛选.sql` 里的周表依赖不复用，只复用分层口径。每日版分层发生在 `tmp_pur_plan_pre_daily_sales` 之后、历史同期和最终补货数量重计算之前。

产物：

```text
tmp_pur_plan_support_layer_all
tmp_pur_plan_support_layer_summary
tmp_pur_plan_replenish_candidates
```

库存支撑数量：

```text
support_inventory_qty =
  pre_available_total
  + pre_stock_up_num
  + pre_local_quantity
```

库存支撑天数：

```text
inventory_support_days =
  support_inventory_qty / pre_daily_avg_sales
```

分层规则：

| 条件 | `support_replenish_level_sort` | `support_replenish_level` |
| --- | ---: | --- |
| `pre_daily_avg_sales <= 0` 或为空 | 5 | `日销为0` |
| `inventory_support_days <= 35` | 1 | `紧急补货` |
| `35 < inventory_support_days <= 65` | 2 | `建议补货` |
| `65 < inventory_support_days <= 90` | 3 | `计划补货` |
| `inventory_support_days > 90` | 4 | `库存充足` |
| 其他兜底 | 2 | `建议补货` |

只有以下三层继续进入后续补货数量、利润和历史同期计算：

```sql
where support_replenish_level_sort in (1, 2, 3)
```

分层只做基础池二次粗筛和看板展示，不改变最终补货数量公式，也不替换 4.7 里的最终落表过滤。

### 4.5 补货需求

公式保持原 SQL：

```text
replenish_need_qty =
  replenish_comp_months * 30 * daily_avg_sales
  - available_total
  - local_quantity
  - stock_up_num
  - sc_quantity_purchase_plan
```

其中库存字段全部来自 `snapshot_date` 当天快照。

### 4.6 历史恢复和环比修正

历史恢复候选保持原 SQL：

```text
pre_normal_replenish_need_qty < pre_replenish_trigger_qty
and pre_r_30d_salable_days < 15
and hist_90d_instock_days >= 15
and hist_90d_instock_daily_sales > 1.5
and history_recovery_need_qty >= pre_replenish_trigger_qty
```

历史同期修正保持原 SQL：

```text
sales_change_rate_adj =
  ((future_instock_sales_adj - prev_matched_sales_adj) / greatest(prev_matched_sales_adj, 30))
  * least(prev_matched_sales_adj / 50, 1)
```

边界：

```text
sales_change_rate_adj between -0.5 and 1.5
sales_adj_factor = 1 when sales_change_rate_adj is null
sales_adj_factor = 1 + sales_change_rate_adj otherwise
```

### 4.7 最终补货数量

箱规：

```text
replenish_trigger_qty = max_cg_box_pcs when max_cg_box_pcs > 0 else 50
```

补货数量：

| 场景 | 口径 |
| --- | --- |
| `history_recovery_flag = 1` 且有箱规 | 补 1 箱 |
| 正常需要补货且有箱规 | 按箱规四舍五入 |
| 正常需要补货且无箱规 | 按数量四舍五入 |

最终过滤：

```sql
where (replenish_need_qty >= replenish_trigger_qty and replenish_qty >= 90)
   or coalesce(history_recovery_flag, 0) = 1
```

## 5. Local Table Design

### 5.1 最终结果表

```text
{target_schema}.dashboard_pur_plan_replenish_data
```

主键：

```text
cur_date + country_category + seller_name_new + seller_sku_adj
```

核心字段：

```text
cur_date
new_old_product
seller_sku_adj
max_fnsku
max_asin
max_sku
marketplace_status
seller_name_new
country_category
max_local_name
max_brand_name
principal
sales_team_1
max_receiving_time
receiving_cnt
max_cg_box_pcs
max_cg_price
max_cg_transport_costs
stockout_status
pre_daily_avg_sales
pre_normal_replenish_need_qty
pre_replenish_trigger_qty
support_inventory_qty
inventory_support_days
support_replenish_level
support_replenish_level_sort
daily_avg_sales
replenish_comp_months
replenish_need_qty
replenish_trigger_qty
sales_adj_factor
replenish_qty
replenish_box_qty
replenish_cost
amz_instock_sales_ratio
instock_intrans_pur_sales_ratio
fllow_flag
history_recovery_flag
```

### 5.2 不落表的中间结果

以下中间结果只用 session temporary table，不长期落本地：

```text
tmp_pur_plan_candidate_keys
tmp_prod_perf_sku_metrics
tmp_candidate_asin_mapping
tmp_listing_product_daily
tmp_fba_shipment_receiving_daily
tmp_settlement_profit_recent
tmp_predict_category_daily
tmp_monthly_predict_category
tmp_quarter_predict_category
tmp_logistics_expected_delivery_daily
tmp_pur_plan_daily_base
tmp_pur_plan_fba_current
tmp_pur_plan_replenish_sug_current
tmp_stockout_status_daily
tmp_pur_plan_pre_daily_sales
tmp_pur_plan_support_layer_all
tmp_pur_plan_support_layer_summary
tmp_pur_plan_replenish_candidates
tmp_lx_orders_profit_rate_result
```

### 5.3 可长期落表的辅助结果

```text
{target_schema}.pur_plan_prod_perf_salable_days_stat
```

原因：

- 可售天数是补货核心口径。
- 后续可用于排查“为什么某个 SKU 没进补货候选”。
- 按 `sta_dt` 删除重算即可幂等。

## 6. Implementation Tasks

### Task 1: Add Replenishment Plan Guard Tests

**Files:**
- Create: `tests/test_replenishment_update_sql.py`

- [ ] **Step 1: Write tests for no weekly table dependency**

```python
import unittest

from etl import replenishment_update


class ReplenishmentUpdateSqlTests(unittest.TestCase):
    def test_replenishment_does_not_depend_on_weekly_output_tables(self):
        sql = "\n".join(replenishment_update.REPLENISHMENT_TEMPORARY_SQL)
        self.assertNotIn("ops_weekly_rpt_prod_perf_interim", sql)
        self.assertNotIn("ops_weekly_rpt_prod_perf_data_2026", sql)
        self.assertNotIn("yearweek(date_sub(curdate(), interval 1 week)", sql.lower())

    def test_candidate_pool_uses_daily_product_performance_table(self):
        sql = "\n".join(replenishment_update.REPLENISHMENT_TEMPORARY_SQL)
        self.assertIn("tmp_pur_plan_candidate_keys", sql)
        self.assertIn("dashboard_product_performance_daily", sql)
        self.assertIn("candidate_days", sql)
        self.assertIn("length(seller_sku_adj) between 5 and 10", sql.lower())

    def test_inventory_uses_daily_snapshots(self):
        sql = "\n".join(replenishment_update.REPLENISHMENT_TEMPORARY_SQL)
        self.assertIn("dashboard_inventory_daily_snapshot", sql)
        self.assertIn("dashboard_restock_daily_snapshot", sql)
        self.assertIn("snapshot_date = %(snapshot_date)s", sql)
        self.assertNotIn("dt_week = yearweek", sql.lower())

    def test_support_layer_rules_are_present(self):
        sql = "\n".join(replenishment_update.REPLENISHMENT_TEMPORARY_SQL)
        self.assertIn("tmp_pur_plan_support_layer_all", sql)
        self.assertIn("tmp_pur_plan_support_layer_summary", sql)
        self.assertIn("support_inventory_qty", sql)
        self.assertIn("inventory_support_days", sql)
        self.assertIn("support_replenish_level_sort in (1, 2, 3)", sql.lower())
        self.assertIn("紧急补货", sql)
        self.assertIn("建议补货", sql)
        self.assertIn("计划补货", sql)
        self.assertIn("库存充足", sql)
        self.assertIn("日销为0", sql)

    def test_final_filter_is_preserved(self):
        sql = replenishment_update.INSERT_REPLENISHMENT_RESULT_SQL
        self.assertIn("replenish_need_qty >= replenish_trigger_qty", sql)
        self.assertIn("replenish_qty >= 90", sql)
        self.assertIn("history_recovery_flag", sql)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
python -m pytest tests/test_replenishment_update_sql.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'etl.replenishment_update'
```

### Task 2: Create Replenishment ETL Module

**Files:**
- Create: `etl/replenishment_update.py`

- [ ] **Step 1: Add module skeleton**

```python
from __future__ import annotations

import argparse
import configparser
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from etl.dashboard_daily_update import (
    SchemaConfig,
    build_schema_config,
    connect_source,
    connect_target,
    log_task,
    parse_day,
)


DEFAULT_REPLENISHMENT_STEP_ORDER = [
    "check_daily_snapshots",
    "candidate_keys",
    "salable_days_stat",
    "replenishment_result",
]


@dataclass(frozen=True)
class ReplenishmentStep:
    name: str
    statements: tuple[str, ...]


REPLENISHMENT_TEMPORARY_SQL: tuple[str, ...] = ()
INSERT_REPLENISHMENT_RESULT_SQL = ""
```

- [ ] **Step 2: Run tests again**

Run:

```powershell
python -m pytest tests/test_replenishment_update_sql.py -q
```

Expected:

```text
tests fail because SQL constants are empty
```

### Task 3: Add Parameters and Snapshot Checks

**Files:**
- Modify: `etl/replenishment_update.py`

- [ ] **Step 1: Add database.ini config fallback**

Keep the existing environment variable path as the primary runtime path. If variables are absent, load `config/database.ini` and set the same environment variable names that `connect_target()`, `connect_source()`, and `build_schema_config()` already read. Do not log the password.

```python
CONFIG_ENV_MAP = {
    "target": {
        "host": "DASHBOARD_DB_HOST",
        "port": "DASHBOARD_DB_PORT",
        "user": "DASHBOARD_DB_USER",
        "password": "DASHBOARD_DB_PASSWORD",
        "database": "DASHBOARD_DB_NAME",
    },
    "source": {
        "host": "DASHBOARD_SOURCE_DB_HOST",
        "port": "DASHBOARD_SOURCE_DB_PORT",
        "user": "DASHBOARD_SOURCE_DB_USER",
        "password": "DASHBOARD_SOURCE_DB_PASSWORD",
        "database": "DASHBOARD_SOURCE_DB_NAME",
    },
}

SCHEMA_ENV_MAP = {
    "target_schema": "DASHBOARD_TARGET_SCHEMA",
    "etl_source_schema": "DASHBOARD_ETL_SOURCE_SCHEMA",
    "dwd_source_schema": "DASHBOARD_DWD_SOURCE_SCHEMA",
    "pricing_source_schema": "DASHBOARD_PRICING_SOURCE_SCHEMA",
}


def is_real_config_value(value: str | None) -> bool:
    if not value:
        return False
    upper_value = value.strip().upper()
    return not (
        upper_value.startswith("REMOTE_")
        or upper_value in {"YOUR_USER", "YOUR_PASSWORD", "CHANGE_ME"}
    )


def apply_database_ini_env(config_path: Path = Path("config/database.ini")) -> None:
    parser = configparser.ConfigParser()
    if not config_path.exists():
        return
    parser.read(config_path, encoding="utf-8")

    for section, option_map in CONFIG_ENV_MAP.items():
        if not parser.has_section(section):
            continue
        for option, env_name in option_map.items():
            value = parser[section].get(option)
            if is_real_config_value(value):
                os.environ.setdefault(env_name, value.strip())

    if parser.has_section("target"):
        target = parser["target"]
        target_schema = target.get("target_schema", "").strip() or target.get("database", "").strip()
        if is_real_config_value(target_schema):
            os.environ.setdefault("DASHBOARD_TARGET_SCHEMA", target_schema)

    if parser.has_section("schemas"):
        for option, env_name in SCHEMA_ENV_MAP.items():
            value = parser["schemas"].get(option)
            if is_real_config_value(value):
                os.environ.setdefault(env_name, value.strip())
```

Expected local config values from this workspace:

```text
host = 192.168.112.235
port = 3306
database = etl_datasync_test
target_schema = etl_datasync_test
```

当前 workspace 的 `[source]` 是占位值，所以远端依赖的临时表不能静默跳过。实现时在创建远端 temp table 前调用 source 连接校验；如果 source host/user/database 仍是占位值，直接失败并说明缺少远端只读库配置。

- [ ] **Step 2: Add parameter builder**

```python
def build_params(args: argparse.Namespace) -> dict[str, object]:
    biz_date = parse_day(args.biz_date) if args.biz_date else date.today() - timedelta(days=1)
    snapshot_date = parse_day(args.snapshot_date) if args.snapshot_date else date.today()
    candidate_days = int(args.candidate_days or 1)
    if candidate_days < 1:
        raise SystemExit("candidate_days must be at least 1")
    return {
        "biz_date": biz_date,
        "snapshot_date": snapshot_date,
        "next_snapshot_date": snapshot_date + timedelta(days=1),
        "product_start_date": biz_date - timedelta(days=89),
        "candidate_days": candidate_days,
    }
```

- [ ] **Step 3: Add required snapshot validation SQL**

```python
CHECK_DAILY_SNAPSHOTS_SQL = """
select
    (select count(*)
     from `{target_schema}`.`dashboard_inventory_daily_snapshot`
     where snapshot_date = %(snapshot_date)s) as inventory_rows,
    (select count(*)
     from `{target_schema}`.`dashboard_restock_daily_snapshot`
     where snapshot_date = %(snapshot_date)s) as restock_rows;
"""
```

Expected behavior:

```text
inventory_rows = 0 or restock_rows = 0 -> raise RuntimeError and write failed log
```

### Task 4: Port Daily Product Metrics

**Files:**
- Modify: `etl/replenishment_update.py`

- [ ] **Step 1: Implement `tmp_pur_plan_candidate_keys`**

Use the local daily product performance table as the candidate entrance:

```sql
create temporary table tmp_pur_plan_candidate_keys as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    max(local_sku) as max_sku
from `{target_schema}`.`dashboard_product_performance_daily`
where dt_date between date_sub(%(biz_date)s, interval (%(candidate_days)s - 1) day)
                  and %(biz_date)s
  and seller_name not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
  and seller_name_new not in ('gushili', 'Joochees', 'ouhao', 'pingter')
  and seller_sku_adj is not null
  and seller_sku_adj <> ''
  and length(seller_sku_adj) between 5 and 10
group by country_category, seller_name_new, seller_sku_adj;
```

Expected default behavior:

```text
candidate_days = 1, so the base pool comes from biz_date only.
```

- [ ] **Step 2: Implement `tmp_prod_perf_sku_metrics`**

Use local `dashboard_product_performance_daily` directly. It is already in the local write DB and contains `dt_date`, `sales_qty`, `sales_amount`, `order_gross_profit`, and `afn_fulfillable_quantity`.

```sql
create temporary table tmp_prod_perf_sku_metrics as
with product_perf as (
    select
        dt_date,
        country_category,
        seller_name_new,
        seller_sku_adj,
        coalesce(sales_qty, 0) as sales_qty,
        coalesce(sales_amount, 0) as sales_amount,
        coalesce(order_gross_profit, 0) as order_gross_profit
    from `{target_schema}`.`dashboard_product_performance_daily` p
    inner join tmp_pur_plan_candidate_keys c
            on p.country_category = c.country_category
           and p.seller_name_new = c.seller_name_new
           and p.seller_sku_adj = c.seller_sku_adj
    where p.dt_date >= %(product_start_date)s
      and p.dt_date <= %(biz_date)s
      and p.seller_name not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
)
select
    %(biz_date)s as cur_date,
    country_category,
    seller_name_new,
    seller_sku_adj,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 89 day) then sales_qty else 0 end) as sales_90,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 29 day) then sales_qty else 0 end) as sales_30,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 13 day) then sales_qty else 0 end) as sales_14,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 6 day) then sales_qty else 0 end) as sales_7,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 2 day) then sales_qty else 0 end) as sales_3,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 29 day) then sales_amount else 0 end) as amount_30,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 13 day) then sales_amount else 0 end) as amount_14,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 6 day) then sales_amount else 0 end) as amount_7,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 2 day) then sales_amount else 0 end) as amount_3,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 29 day) then order_gross_profit else 0 end) as pprofit_30,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 13 day) then order_gross_profit else 0 end) as pprofit_14,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 6 day) then order_gross_profit else 0 end) as pprofit_7,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 2 day) then order_gross_profit else 0 end) as pprofit_3,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 29 day) then order_gross_profit else 0 end)
        / nullif(sum(case when dt_date >= date_sub(%(biz_date)s, interval 29 day) then sales_amount else 0 end), 0) as pprofit_ratio_30,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 13 day) then order_gross_profit else 0 end)
        / nullif(sum(case when dt_date >= date_sub(%(biz_date)s, interval 13 day) then sales_amount else 0 end), 0) as pprofit_ratio_14,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 6 day) then order_gross_profit else 0 end)
        / nullif(sum(case when dt_date >= date_sub(%(biz_date)s, interval 6 day) then sales_amount else 0 end), 0) as pprofit_ratio_7,
    sum(case when dt_date >= date_sub(%(biz_date)s, interval 2 day) then order_gross_profit else 0 end)
        / nullif(sum(case when dt_date >= date_sub(%(biz_date)s, interval 2 day) then sales_amount else 0 end), 0) as pprofit_ratio_3
from product_perf
group by country_category, seller_name_new, seller_sku_adj;
```

- [ ] **Step 3: Add ASIN mapping only for follow-seller compensation if needed**

The local product performance table does not contain `asin`. If the follow-seller compensation path needs ASIN-level origin-store sales, create a separate remote-backed temp table limited to the candidate pool:

```sql
create temporary table tmp_candidate_asin_mapping as
select
    p.country_category,
    p.seller_name_new,
    p.seller_sku_adj,
    max(p.asin) as max_asin
from `{etl_source_schema}`.`etl_dispose_lx_statistics_product_performance_2026` p
inner join tmp_pur_plan_candidate_keys c
        on p.country_category = c.country_category
       and p.seller_name_new = c.seller_name_new
       and p.seller_sku_adj = c.seller_sku_adj
where p.start_date = %(biz_date)s
group by p.country_category, p.seller_name_new, p.seller_sku_adj;
```

### Task 5: Port Daily Base and Inventory Inputs

**Files:**
- Modify: `etl/replenishment_update.py`

- [ ] **Step 1: Build the daily upstream temp tables before `tmp_pur_plan_daily_base`**

Create these temp tables in order:

```text
tmp_listing_product_daily
tmp_fba_shipment_receiving_daily
tmp_settlement_profit_recent
tmp_predict_category_daily
tmp_monthly_predict_category
tmp_quarter_predict_category
tmp_logistics_expected_delivery_daily
```

Use the SQL shapes in section 2.4 for `tmp_listing_product_daily`, `tmp_fba_shipment_receiving_daily`, `tmp_settlement_profit_recent`, and `tmp_logistics_expected_delivery_daily`. `tmp_predict_category_daily` should be derived from `tmp_prod_perf_sku_metrics` with the same product-performance category thresholds as the weekly SQL.

The local DB audit shows `ops_monthly_rpt_prod_perf_basic_data` and `ops_quarter_rpt_prod_perf_basic_data` do not exist locally, so do not write the implementation as "use local if available". Use this priority instead:

```text
tmp_monthly_predict_category:
1. preferred: remote `ops_monthly_rpt_prod_perf_basic_data` if source config is available
2. fallback: local `dashboard_product_period_last_month_snapshot` if its metric fields are sufficient
3. final fallback: recompute from `dashboard_product_performance_daily` for the previous complete calendar month

tmp_quarter_predict_category:
1. preferred: remote `ops_quarter_rpt_prod_perf_basic_data` if source config is available
2. fallback: recompute from `dashboard_product_performance_daily` for the previous complete quarter
```

Both temp tables must keep the output grain as `country_category + seller_name_new + seller_sku_adj`.

- [ ] **Step 2: Join daily upstream fields into `tmp_pur_plan_daily_base`**

`tmp_pur_plan_daily_base` must left join the daily-derived tables below by `country_category + seller_name_new + seller_sku_adj`:

```text
tmp_listing_product_daily
tmp_fba_shipment_receiving_daily
tmp_settlement_profit_recent
tmp_predict_category_daily
tmp_monthly_predict_category
tmp_quarter_predict_category
```

The resulting table must expose these fields for downstream replenishment formulas:

```text
global_tags
max_brand_name
abcd_category
gp_margin_range
predict_abcd_category
pre_1m_predict_abcd_category
pre_1q_predict_abcd_category
max_cg_transport_costs
max_cg_price
max_cg_box_pcs
max_receiving_time
receiving_cnt
new_old_product
principal
sales_team_1
max_sku
max_fnsku
max_local_name
max_asin
marketplace_status
```

- [ ] **Step 3: Implement daily FBA inventory temp table**

```sql
create temporary table tmp_pur_plan_fba_current as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    total,
    available_total,
    afn_fulfillable_quantity,
    stock_up_num,
    afn_unsellable_quantity
from `{target_schema}`.`dashboard_inventory_daily_snapshot`
where snapshot_date = %(snapshot_date)s;
```

- [ ] **Step 4: Implement daily restock temp table**

```sql
create temporary table tmp_pur_plan_replenish_sug_current as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    local_quantity,
    purchase_shipping_quantity as sc_quantity_purchase_shipping,
    purchase_plan_quantity as sc_quantity_purchase_plan,
    local_valid_quantity as sc_quantity_local_valid,
    local_qc_quantity as sc_quantity_local_qc
from `{target_schema}`.`dashboard_restock_daily_snapshot`
where snapshot_date = %(snapshot_date)s;
```

- [ ] **Step 5: Implement daily salable days temp table**

Create `tmp_pur_plan_salable_days_current` after `tmp_prod_perf_sku_metrics` and `tmp_pur_plan_fba_current` exist. Use the SQL shape from section 4.1. This temp table must expose both the historical salable-day counts and the current-stock estimate used by stockout logic:

```text
r_90d_salable_days
r_30d_salable_days
r_14d_salable_days
r_7d_salable_days
r_3d_salable_days
available_daily_sales_base
available_salable_days
```

Also insert or replace the same daily result into `{target_schema}.pur_plan_prod_perf_salable_days_stat` by `sta_dt = %(biz_date)s` if the long-term debug table is enabled.

- [ ] **Step 6: Implement pre-adjusted daily sales temp table**

Create `tmp_pur_plan_pre_daily_sales` after `tmp_prod_perf_sku_metrics` and `tmp_pur_plan_salable_days_current` exist. This temp table is used by the inventory-support layer and keeps the same可售天数修正口径 as the new SQL file.

```sql
create temporary table tmp_pur_plan_pre_daily_sales as
select
    spb.country_category,
    spb.seller_name_new,
    spb.seller_sku_adj,
    spb.sales_90 as sales_90d,
    case
        when ks.r_30d_salable_days >= 7
            then case
                when ks.r_3d_salable_days > 0
                    then coalesce(spb.sales_3, 0) / ks.r_3d_salable_days
                else 0
            end
        else coalesce(spb.sales_3, 0) / greatest(coalesce(ks.r_3d_salable_days, 0), 2)
    end as adjusted_daily_sales_3d,
    case
        when ks.r_30d_salable_days >= 7
            then case
                when ks.r_7d_salable_days >= 7
                    then coalesce(spb.sales_7, 0) / ks.r_7d_salable_days
                else least(
                    case
                        when ks.r_7d_salable_days > 0
                            then coalesce(spb.sales_7, 0) / ks.r_7d_salable_days
                        else 0
                    end,
                    (case
                        when ks.r_7d_salable_days > 0
                            then coalesce(spb.sales_7, 0) / ks.r_7d_salable_days
                        else 0
                    end) * (ks.r_7d_salable_days / (ks.r_7d_salable_days + 3))
                    + (coalesce(spb.sales_30, 0) / ks.r_30d_salable_days)
                      * (1 - ks.r_7d_salable_days / (ks.r_7d_salable_days + 3))
                )
            end
        else coalesce(spb.sales_7, 0) / greatest(coalesce(ks.r_7d_salable_days, 0), 3)
    end as adjusted_daily_sales_7d,
    case
        when ks.r_30d_salable_days >= 7
            then case
                when ks.r_14d_salable_days >= 14
                    then coalesce(spb.sales_14, 0) / ks.r_14d_salable_days
                else least(
                    case
                        when ks.r_14d_salable_days > 0
                            then coalesce(spb.sales_14, 0) / ks.r_14d_salable_days
                        else 0
                    end,
                    (case
                        when ks.r_14d_salable_days > 0
                            then coalesce(spb.sales_14, 0) / ks.r_14d_salable_days
                        else 0
                    end) * (ks.r_14d_salable_days / (ks.r_14d_salable_days + 7))
                    + (coalesce(spb.sales_30, 0) / ks.r_30d_salable_days)
                      * (1 - ks.r_14d_salable_days / (ks.r_14d_salable_days + 7))
                )
            end
        else coalesce(spb.sales_14, 0) / greatest(coalesce(ks.r_14d_salable_days, 0), 7)
    end as adjusted_daily_sales_14d,
    case
        when ks.r_30d_salable_days >= 7
            then coalesce(spb.sales_30, 0) / ks.r_30d_salable_days
        else coalesce(spb.sales_30, 0) / greatest(coalesce(ks.r_30d_salable_days, 0), 15)
    end as adjusted_daily_sales_30d
from tmp_prod_perf_sku_metrics spb
left join tmp_pur_plan_salable_days_current ks
       on spb.country_category = ks.country_category
      and spb.seller_name_new = ks.seller_name_new
      and spb.seller_sku_adj = ks.seller_sku_adj;
```

- [ ] **Step 7: Implement daily stockout status temp table**

Create `tmp_stockout_status_daily` after `tmp_pur_plan_fba_current`, `tmp_pur_plan_replenish_sug_current`, and `tmp_pur_plan_salable_days_current` exist. Use `snapshot_date` instead of weekly `week_end`:

```sql
create temporary table tmp_stockout_status_daily as
select
    b.country_category,
    b.seller_name_new,
    b.seller_sku_adj,
    le.expected_delivery_time,
    case
        when s.available_salable_days > 60
          or datediff(le.expected_delivery_time, %(snapshot_date)s) < s.available_salable_days
            then '不会缺货'
        when coalesce(f.stock_up_num, 0) = 0 and coalesce(r.local_quantity, 0) = 0
            then '缺货未补货'
        when coalesce(f.stock_up_num, 0) > 0 or coalesce(r.local_quantity, 0) > 0
            then '缺货已补货'
    end as stockout_status
from tmp_pur_plan_daily_base b
left join tmp_logistics_expected_delivery_daily le
       on b.country_category = le.country_category
      and b.seller_name_new = le.seller_name_new
      and b.seller_sku_adj = le.seller_sku_adj
left join tmp_pur_plan_fba_current f
       on b.country_category = f.country_category
      and b.seller_name_new = f.seller_name_new
      and b.seller_sku_adj = f.seller_sku_adj
left join tmp_pur_plan_replenish_sug_current r
       on b.country_category = r.country_category
      and b.seller_name_new = r.seller_name_new
      and b.seller_sku_adj = r.seller_sku_adj
left join tmp_pur_plan_salable_days_current s
       on b.country_category = s.country_category
      and b.seller_name_new = s.seller_name_new
      and b.seller_sku_adj = s.seller_sku_adj;
```

### Task 6: Port Final Replenishment Logic

**Files:**
- Modify: `etl/replenishment_update.py`

- [ ] **Step 1: Implement inventory-support layer**

Create `tmp_pur_plan_support_layer_all` after `tmp_pur_plan_daily_base`, `tmp_pur_plan_fba_current`, `tmp_pur_plan_replenish_sug_current`, `tmp_pur_plan_salable_days_current`, `tmp_pur_plan_pre_daily_sales`, and `tmp_stockout_status_daily` exist.

```sql
create temporary table tmp_pur_plan_support_layer_all as
select
    pre.*,
    case
        when coalesce(pre.pre_daily_avg_sales, 0) <= 0 then null
        else pre.support_inventory_qty / pre.pre_daily_avg_sales
    end as inventory_support_days,
    case
        when coalesce(pre.pre_daily_avg_sales, 0) <= 0 then 5
        when pre.support_inventory_qty / pre.pre_daily_avg_sales <= 35 then 1
        when pre.support_inventory_qty / pre.pre_daily_avg_sales > 35
          and pre.support_inventory_qty / pre.pre_daily_avg_sales <= 65 then 2
        when pre.support_inventory_qty / pre.pre_daily_avg_sales > 65
          and pre.support_inventory_qty / pre.pre_daily_avg_sales <= 90 then 3
        when pre.support_inventory_qty / pre.pre_daily_avg_sales > 90 then 4
        else 2
    end as support_replenish_level_sort,
    case
        when coalesce(pre.pre_daily_avg_sales, 0) <= 0 then '日销为0'
        when pre.support_inventory_qty / pre.pre_daily_avg_sales <= 35 then '紧急补货'
        when pre.support_inventory_qty / pre.pre_daily_avg_sales > 35
          and pre.support_inventory_qty / pre.pre_daily_avg_sales <= 65 then '建议补货'
        when pre.support_inventory_qty / pre.pre_daily_avg_sales > 65
          and pre.support_inventory_qty / pre.pre_daily_avg_sales <= 90 then '计划补货'
        when pre.support_inventory_qty / pre.pre_daily_avg_sales > 90 then '库存充足'
        else '建议补货'
    end as support_replenish_level
from (
    select
        pre_calc.*,
        pre_calc.pre_available_total + pre_calc.pre_stock_up_num + pre_calc.pre_local_quantity as support_inventory_qty,
        case
            when pre_calc.pre_normal_replenish_need_qty < pre_calc.pre_replenish_trigger_qty
             and pre_calc.pre_r_30d_salable_days < 15
             and pre_calc.hist_90d_instock_days >= 15
             and pre_calc.hist_90d_instock_daily_sales > 1.5
             and pre_calc.history_recovery_need_qty >= pre_calc.pre_replenish_trigger_qty
                then 1
            else 0
        end as history_recovery_flag
    from (
        select
            pre_base.*,
            pre_replenish_comp_months * 30 * coalesce(pre_daily_avg_sales, 0)
                - pre_available_total
                - pre_stock_up_num
                - pre_local_quantity
                - pre_sc_quantity_purchase_plan as pre_normal_replenish_need_qty,
            hist_90d_instock_daily_sales * 120
                - pre_available_total
                - pre_stock_up_num
                - pre_local_quantity
                - pre_sc_quantity_purchase_plan as history_recovery_need_qty
        from (
            select
                b.*,
                ss.stockout_status,
                case
                    when b.country_category in ('英国站', '欧洲站') then 4
                    when b.country_category = '北美站' then 4
                end as pre_replenish_comp_months,
                case
                    when (b.max_brand_name like '%2025%' and (b.receiving_cnt <= 1 or b.receiving_cnt is null))
                      or (b.max_brand_name like '%2026%' and (b.receiving_cnt <= 1 or b.receiving_cnt is null))
                        then coalesce(pds.adjusted_daily_sales_3d, 0) * 0.5
                           + coalesce(pds.adjusted_daily_sales_7d, 0) * 0.5
                    else coalesce(pds.adjusted_daily_sales_7d, 0) * 0.6
                       + coalesce(pds.adjusted_daily_sales_14d, 0) * 0.2
                       + coalesce(pds.adjusted_daily_sales_30d, 0) * 0.2
                end as pre_daily_avg_sales,
                coalesce(f.available_total, 0) as pre_available_total,
                coalesce(f.stock_up_num, 0) as pre_stock_up_num,
                coalesce(r.local_quantity, 0) as pre_local_quantity,
                coalesce(r.sc_quantity_purchase_plan, 0) as pre_sc_quantity_purchase_plan,
                coalesce(ks.r_30d_salable_days, 0) as pre_r_30d_salable_days,
                coalesce(ks.r_90d_salable_days, 0) as hist_90d_instock_days,
                coalesce(pds.sales_90d, 0) as hist_90d_instock_sales,
                case
                    when coalesce(ks.r_90d_salable_days, 0) > 0
                        then coalesce(pds.sales_90d, 0) / ks.r_90d_salable_days
                    else 0
                end as hist_90d_instock_daily_sales,
                case
                    when coalesce(b.max_cg_box_pcs, 0) > 0 then b.max_cg_box_pcs
                    else 50
                end as pre_replenish_trigger_qty
            from tmp_pur_plan_daily_base b
            left join tmp_stockout_status_daily ss
                   on b.country_category = ss.country_category
                  and b.seller_name_new = ss.seller_name_new
                  and b.seller_sku_adj = ss.seller_sku_adj
            left join tmp_pur_plan_fba_current f
                   on b.country_category = f.country_category
                  and b.seller_name_new = f.seller_name_new
                  and b.seller_sku_adj = f.seller_sku_adj
            left join tmp_pur_plan_replenish_sug_current r
                   on b.country_category = r.country_category
                  and b.seller_name_new = r.seller_name_new
                  and b.seller_sku_adj = r.seller_sku_adj
            left join tmp_pur_plan_salable_days_current ks
                   on b.country_category = ks.country_category
                  and b.seller_name_new = ks.seller_name_new
                  and b.seller_sku_adj = ks.seller_sku_adj
            left join tmp_pur_plan_pre_daily_sales pds
                   on b.country_category = pds.country_category
                  and b.seller_name_new = pds.seller_name_new
                  and b.seller_sku_adj = pds.seller_sku_adj
        ) pre_base
    ) pre_calc
) pre;
```

- [ ] **Step 2: Implement support-layer summary**

```sql
create temporary table tmp_pur_plan_support_layer_summary as
select
    support_replenish_level_sort,
    support_replenish_level,
    count(distinct concat_ws('|', country_category, seller_name_new, seller_sku_adj)) as msku_count,
    count(*) as row_count
from tmp_pur_plan_support_layer_all
group by support_replenish_level_sort, support_replenish_level;
```

- [ ] **Step 3: Implement replenishment candidates from support layers**

Only urgent, suggested, and planned replenishment rows continue into the final calculation. `日销为0` and `库存充足` rows remain in `tmp_pur_plan_support_layer_summary` for dashboard visibility but do not enter final quantity calculation.

```sql
create temporary table tmp_pur_plan_replenish_candidates as
select *
from tmp_pur_plan_support_layer_all
where support_replenish_level_sort in (1, 2, 3);
```

- [ ] **Step 4: Replace old references**

In the ported final SQL:

```text
opt_db.tmp_ -> tmp_
tmp_pur_plan_wd_current -> tmp_pur_plan_daily_base
tmp_pur_plan_wd_current used by final CTE -> tmp_pur_plan_replenish_candidates
wd.stockout_status -> tmp_pur_plan_replenish_candidates.stockout_status
ops_weekly_rpt_prod_perf_interim -> removed
ops_weekly_rpt_prod_perf_data_2026 -> removed
ops_weekly_rpt_fba_inv_detail_basic_data -> dashboard_inventory_daily_snapshot temp table
ops_weekly_rpt_replenish_sug_basic_data -> dashboard_restock_daily_snapshot temp table
```

- [ ] **Step 5: Preserve final business formulas**

Keep:

```text
pre_daily_avg_sales
pre_normal_replenish_need_qty
pre_replenish_trigger_qty
support_inventory_qty
inventory_support_days
support_replenish_level
support_replenish_level_sort
daily_avg_sales
replenish_comp_months
replenish_need_qty
history_recovery_flag
sales_adj_factor
replenish_qty
replenish_box_qty
replenish_cost
```

- [ ] **Step 6: Insert into final local table**

The final statement must insert into:

```text
`{target_schema}`.`dashboard_pur_plan_replenish_data`
```

and set:

```text
cur_date = %(snapshot_date)s
```

### Task 7: Verification

**Files:**
- No code changes.

- [ ] **Step 1: Dry run**

Run:

```powershell
python -m etl.replenishment_update --dry-run
```

Expected:

```text
Replenishment ETL plan
biz_date
snapshot_date
steps
```

- [ ] **Step 2: SQL guard tests**

Run:

```powershell
python -m pytest tests/test_replenishment_update_sql.py tests/test_dashboard_daily_update_sql.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 3: Local DB execution**

Run after local/source DB env is configured:

```powershell
python -m etl.replenishment_update --steps all
```

Expected:

```text
[success] check_daily_snapshots
[success] salable_days_stat
[success] replenishment_result
```

- [ ] **Step 4: Final row validation**

Run:

```sql
select cur_date, count(*) as rows_count
from etl_datasync_test.dashboard_pur_plan_replenish_data
group by cur_date
order by cur_date desc
limit 7;
```

Expected:

```text
latest cur_date has rows_count > 0
```

## 7. Local Execution Status

At analysis time on 2026-06-18:

```text
config/database.ini [target] connects successfully.
target host = 192.168.112.235
target database = etl_datasync_test
MySQL version = 8.0.46

Existing local tables:
- dashboard_product_performance_daily: dt_date 2025-12-11 ~ 2026-06-17
- dashboard_inventory_daily_snapshot: snapshot_date 2026-04-30 ~ 2026-06-18
- dashboard_restock_daily_snapshot: snapshot_date 2026-04-30 ~ 2026-06-18
- dashboard_product_period_7d_snapshot: snapshot_date 2026-06-17 ~ 2026-06-18
- dashboard_product_period_14d_snapshot: snapshot_date 2026-06-17 ~ 2026-06-18
- dashboard_product_period_30d_snapshot: snapshot_date 2026-06-17 ~ 2026-06-18
- dashboard_product_period_90d_snapshot: snapshot_date 2026-06-17 ~ 2026-06-18
- dashboard_product_period_last_month_snapshot: snapshot_date 2026-06-17 ~ 2026-06-18

Missing local tables:
- dashboard_pur_plan_replenish_data
- pur_plan_prod_perf_salable_days_stat
- etl_dispose_lx_sales_mws_listing
- etl_dispose_lx_product_local_product_info
- etl_dispose_lx_fba_shipment
- etl_dispose_lx_statistics_profit_statistics_msku
- ops_monthly_rpt_prod_perf_basic_data
- ops_quarter_rpt_prod_perf_basic_data
- ops_rpt_logi_est_days_data
```

The implementation can reuse local dashboard snapshots for product performance, FBA inventory, and restock quantities. Missing商品信息、货件、结算利润、月季分类、物流预计到货字段 must come from the remote read-only source or be materialized as new local snapshots before the replenishment job runs.

## 8. Requirement Closure Before Coding

### 8.1 数据输入

每日补货 ETL 使用两个业务日期：

```text
biz_date = 昨天，默认用于产品表现、可售天数、历史销售窗口
snapshot_date = 今天，默认用于库存快照、本地库存/采购快照、最终落表日期
```

可直接复用本地表：

```text
dashboard_product_performance_daily
dashboard_inventory_daily_snapshot
dashboard_restock_daily_snapshot
dashboard_product_period_last_month_snapshot
```

必须从远端只读源或后续本地快照补齐：

```text
listing/product info
FBA receiving shipment
settlement profit
monthly category
quarter category
logistics expected delivery
ASIN mapping for follow-seller compensation
```

### 8.2 基础池

基础池不再取上一周周表结果，默认从 `biz_date` 当天本地产品表现宽表聚合：

```text
country_category + seller_name_new + seller_sku_adj
```

只保留 SKU 长度、异常店铺排除等原始入口规则，不用销售、库存、在售状态提前筛掉 SKU。

### 8.3 核心计算链路

计算顺序：

```text
candidate keys
-> rolling product metrics
-> follow-seller sales compensation
-> listing/product/receiving/profit/category/logistics fields
-> daily inventory and restock snapshots
-> salable days
-> pre daily sales
-> stockout status
-> support inventory layer
-> replenishment candidates
-> history recovery and YoY adjustment
-> final replenishment quantity
-> dashboard_pur_plan_replenish_data
```

### 8.4 库存支撑分层

分层只复用新增 SQL 文件里的分类口径，不复用该文件里的周表依赖。

```text
support_inventory_qty = pre_available_total + pre_stock_up_num + pre_local_quantity
inventory_support_days = support_inventory_qty / pre_daily_avg_sales
```

分层输出：

```text
1 紧急补货: inventory_support_days <= 35
2 建议补货: 35 < inventory_support_days <= 65
3 计划补货: 65 < inventory_support_days <= 90
4 库存充足: inventory_support_days > 90
5 日销为0: pre_daily_avg_sales <= 0 or null
```

后续最终补货数量只计算 1/2/3 层；4/5 层只保留在分层汇总或排查链路，不进入最终补货候选。

### 8.5 输出

最终落本地表：

```text
{target_schema}.dashboard_pur_plan_replenish_data
```

结果表必须包含看板分层字段：

```text
support_inventory_qty
inventory_support_days
support_replenish_level
support_replenish_level_sort
pre_daily_avg_sales
pre_normal_replenish_need_qty
pre_replenish_trigger_qty
```

最终落表仍保持原补货过滤：

```text
(replenish_need_qty >= replenish_trigger_qty and replenish_qty >= 90)
or history_recovery_flag = 1
```

### 8.6 实现前提

本地 `[target]` 配置已核对可连。`[source]` 仍需真实远端只读配置；如果远端配置不可用，只能完成本地快照相关部分，无法严格复刻 listing、收货次数、结算利润、月季分类、物流预计到货和跟卖 ASIN 补偿。
