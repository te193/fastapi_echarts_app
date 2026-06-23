# Replenishment Listing Detail Field Source Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 明确每日补货看板新增“国家明细”的字段来源和计算口径，保证它只作为展示和排名分析，不和现有补货主计算规则混用。

**Architecture:** 补货主结果继续读取 `dashboard_pur_plan_replenish_data`，粒度不变：`cur_date + country_category + seller_name_new + seller_sku_adj`。国家明细新增独立展示表或独立查询，字段全部来自本地 `dashboard_product_performance_daily` 最近 30 天聚合，粒度为 `snapshot_date + country_category + country + seller_name_new + seller_sku_adj`。这套明细数据不写回补货主表，不参与库存支撑天数、补货层级、需求量、补货数量、箱数和补货货值。

**Tech Stack:** Local MySQL `etl_datasync_test`, Python/PyMySQL ETL, FastAPI, AG Grid, pytest.

---

## 1. 口径边界

### 1.1 补货主逻辑不变

现有补货主逻辑仍然按三维聚合：

```text
country_category + seller_name_new + seller_sku_adj
```

也就是：

```text
国家类别/站点 + 店铺 + MSKU
```

继续由 `dashboard_pur_plan_replenish_data` 提供：

- 库存支撑天数
- 补货层级
- 需求量
- 补货数量
- 箱数
- 补货货值
- 是否跟卖
- 30 天销量、30 天毛利率、产品分类等主表展示字段

### 1.2 新增国家明细只做展示

新增明细只用于看：

- 欧洲站下面德国、法国、意大利等国家表现
- 每个国家最近 30 天销量
- 最近 30 天日销
- 最近 30 天销售额、利润、毛利率
- 排名、Sessions、广告等经营指标

不用于：

- 判断是否补货
- 改变补货层级
- 改变库存支撑天数
- 改变补货数量
- 改变补货货值

---

## 2. 数据源确认

### 2.1 本地库

项目配置：

```text
config/database.ini [target]
host = 192.168.112.235
port = 3306
database = etl_datasync_test
```

本次字段来源只使用本地库，不让页面查远端。

### 2.2 明细主来源表

本地日表：

```text
etl_datasync_test.dashboard_product_performance_daily
```

该表由 `etl/dashboard_daily_update.py` 从产品表现源表同步聚合而来。当前代码里的源字段映射为：

| 本地字段 | 源字段/计算 | 用途 |
| --- | --- | --- |
| `dt_date` | 产品表现日期 | 30 天窗口日期 |
| `country` | 源表国家/marketplace | 国家明细维度，例如德国、法国 |
| `country_category` | 源表站点类别 | 主补货维度，例如欧洲站 |
| `seller_name_new` | 源表标准店铺名 | 主补货维度 |
| `seller_sku_adj` | 源表清洗后 MSKU | 主补货维度 |
| `local_sku` | 源表本地 SKU | 不进聚合粒度；如页面需要，可用 `group_concat(distinct local_sku)` 做参考展示 |
| `sales_qty` | `sum(volume)` | 销量 |
| `sales_amount` | `sum(amount)` | 销售额 |
| `order_gross_profit` | `sum(case when volume = 0 then 0 else predict_gross_profit end)` | 订单毛利 |
| `afn_fulfillable_quantity` | `max(afn_fulfillable_quantity)` | 可售库存，用于可售天数 |
| `sessions_total` | `sum(sessions_total)` | Sessions |
| `ranking` | `max(ranking)` | 当天排名 |
| `ad_spend` | `sum(spend)` | 广告花费 |
| `ad_orders` | `sum(ad_order_quantity)` | 广告订单 |
| `ad_sales` | `sum(ad_sales_amount)` | 广告销售额 |
| `ad_clicks` | `sum(clicks)` | 广告点击 |
| `ad_impressions` | `sum(impressions)` | 广告曝光 |

### 2.3 当前字段覆盖情况

本地表已核对，最近 30 天窗口为：

```text
2026-05-23 ~ 2026-06-21
```

字段覆盖情况：

| 检查项 | 结果 |
| --- | ---: |
| 最近 30 天行数 | 555,555 |
| 国家 + 店铺 + MSKU key 数 | 后续按新粒度重新核对 |
| 有销量行 | 27,075 |
| 有销售额行 | 27,075 |
| 有利润行 | 27,073 |
| 有可售库存行 | 178,123 |
| 有 Sessions 行 | 86,162 |
| 有排名行 | 481,124 |
| 有广告花费行 | 43,058 |
| 有广告销售额行 | 10,720 |

结论：字段可用，国家明细可以先完全基于 `dashboard_product_performance_daily` 做最近 30 天展示。

---

## 3. 新展示表规划

### 3.1 表名

```text
etl_datasync_test.dashboard_replenishment_listing_30d_metrics
```

### 3.2 粒度

```text
snapshot_date
+ country_category
+ country
+ seller_name_new
+ seller_sku_adj
```

解释：

- `snapshot_date`：对应补货结果日期。
- `country_category`：和补货主表一致，例如欧洲站。
- `country`：细分国家，例如德国、法国。
- `seller_name_new`：店铺。
- `seller_sku_adj`：MSKU。
- 不使用 `local_sku` 作为粒度；同一国家下多个 `local_sku` 聚合到同一条国家明细。

### 3.3 建议字段

| 字段 | 类型 | 来源/公式 | 说明 |
| --- | --- | --- | --- |
| `snapshot_date` | date | ETL 参数 | 补货结果日期 |
| `period_start` | date | `biz_date - interval 29 day` | 30 天窗口开始 |
| `period_end` | date | `biz_date` | 30 天窗口结束 |
| `country_category` | varchar | `dashboard_product_performance_daily.country_category` | 国家类别/站点 |
| `country` | varchar | `dashboard_product_performance_daily.country` | 国家细分 |
| `seller_name_new` | varchar | `dashboard_product_performance_daily.seller_name_new` | 店铺 |
| `seller_sku_adj` | varchar | `dashboard_product_performance_daily.seller_sku_adj` | MSKU |
| `local_sku_list` | text | `group_concat(distinct nullif(local_sku,''))` | 可选展示字段；不参与主键和分组 |
| `sales_30d` | decimal | `sum(sales_qty)` | 最近 30 天销量 |
| `daily_sales_30d` | decimal | `sum(sales_qty) / 30` | 自然 30 天日销 |
| `salable_days_30d` | int | `sum(case when afn_fulfillable_quantity > 0 then 1 else 0 end)` | 30 天可售天数 |
| `salable_daily_sales_30d` | decimal | `sum(sales_qty) / nullif(salable_days_30d,0)` | 可售日销 |
| `sales_amount_30d` | decimal | `sum(sales_amount)` | 最近 30 天销售额 |
| `order_profit_30d` | decimal | `sum(order_gross_profit)` | 最近 30 天订单毛利 |
| `order_profit_rate_30d` | decimal | `sum(order_gross_profit) / nullif(sum(sales_amount),0)` | 最近 30 天毛利率 |
| `avg_ranking_30d` | decimal | `avg(nullif(ranking,0))` | 平均排名 |
| `best_ranking_30d` | decimal | `min(nullif(ranking,0))` | 最好排名，数字越小越好 |
| `worst_ranking_30d` | decimal | `max(nullif(ranking,0))` | 最差排名 |
| `sessions_30d` | decimal | `sum(sessions_total)` | Sessions |
| `conversion_rate_30d` | decimal | `sum(sales_qty) / nullif(sum(sessions_total),0)` | 转化率 |
| `ad_spend_30d` | decimal | `sum(ad_spend)` | 广告花费 |
| `ad_orders_30d` | decimal | `sum(ad_orders)` | 广告订单 |
| `ad_sales_30d` | decimal | `sum(ad_sales)` | 广告销售额 |
| `ad_clicks_30d` | decimal | `sum(ad_clicks)` | 广告点击 |
| `ad_impressions_30d` | decimal | `sum(ad_impressions)` | 广告曝光 |
| `acos_30d` | decimal | `sum(ad_spend) / nullif(sum(ad_sales),0)` | ACOS |
| `ctr_30d` | decimal | `sum(ad_clicks) / nullif(sum(ad_impressions),0)` | CTR |

---

## 4. 聚合 SQL 口径

### 4.1 只聚合补货主表已有 MSKU

国家明细只跟随补货主表已有记录生成，避免生成全量无关 SKU：

```sql
inner join etl_datasync_test.dashboard_pur_plan_replenish_data r
        on r.cur_date = %(snapshot_date)s
       and r.country_category = p.country_category
       and r.seller_name_new = p.seller_name_new
       and r.seller_sku_adj = p.seller_sku_adj
```

这保证了：

- 主表一行仍是一条补货建议。
- 国家明细只是主表行的下钻展示。
- 同一个国家下多个 `local_sku` 会先聚合为一条国家记录，不会因为 listing 拆分导致页面过细。

### 4.2 时间窗口

```text
period_end = biz_date
period_start = biz_date - 29 days
```

原因：

- 补货结果日期 `snapshot_date` 通常是当天库存快照日期。
- 产品表现最大可用日期通常是昨天或最近业务日。
- 国家明细用最近 30 个业务日期窗口，和补货页面上“30 天销量/30 天毛利率”的展示逻辑保持方向一致，但不覆盖主表字段。

### 4.3 SQL 草案

```sql
delete from etl_datasync_test.dashboard_replenishment_listing_30d_metrics
where snapshot_date = %(snapshot_date)s;

insert into etl_datasync_test.dashboard_replenishment_listing_30d_metrics (
    snapshot_date,
    period_start,
    period_end,
    country_category,
    country,
    seller_name_new,
    seller_sku_adj,
    local_sku_list,
    sales_30d,
    daily_sales_30d,
    salable_days_30d,
    salable_daily_sales_30d,
    sales_amount_30d,
    order_profit_30d,
    order_profit_rate_30d,
    avg_ranking_30d,
    best_ranking_30d,
    worst_ranking_30d,
    sessions_30d,
    conversion_rate_30d,
    ad_spend_30d,
    ad_orders_30d,
    ad_sales_30d,
    ad_clicks_30d,
    ad_impressions_30d,
    acos_30d,
    ctr_30d
)
select
    %(snapshot_date)s as snapshot_date,
    %(period_start)s as period_start,
    %(biz_date)s as period_end,
    p.country_category,
    p.country,
    p.seller_name_new,
    p.seller_sku_adj,
    group_concat(distinct nullif(p.local_sku, '') order by nullif(p.local_sku, '') separator ',') as local_sku_list,
    sum(coalesce(p.sales_qty, 0)) as sales_30d,
    sum(coalesce(p.sales_qty, 0)) / 30 as daily_sales_30d,
    sum(case when coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end) as salable_days_30d,
    sum(coalesce(p.sales_qty, 0)) / nullif(sum(case when coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end), 0) as salable_daily_sales_30d,
    sum(coalesce(p.sales_amount, 0)) as sales_amount_30d,
    sum(coalesce(p.order_gross_profit, 0)) as order_profit_30d,
    sum(coalesce(p.order_gross_profit, 0)) / nullif(sum(coalesce(p.sales_amount, 0)), 0) as order_profit_rate_30d,
    avg(nullif(p.ranking, 0)) as avg_ranking_30d,
    min(nullif(p.ranking, 0)) as best_ranking_30d,
    max(nullif(p.ranking, 0)) as worst_ranking_30d,
    sum(coalesce(p.sessions_total, 0)) as sessions_30d,
    sum(coalesce(p.sales_qty, 0)) / nullif(sum(coalesce(p.sessions_total, 0)), 0) as conversion_rate_30d,
    sum(coalesce(p.ad_spend, 0)) as ad_spend_30d,
    sum(coalesce(p.ad_orders, 0)) as ad_orders_30d,
    sum(coalesce(p.ad_sales, 0)) as ad_sales_30d,
    sum(coalesce(p.ad_clicks, 0)) as ad_clicks_30d,
    sum(coalesce(p.ad_impressions, 0)) as ad_impressions_30d,
    sum(coalesce(p.ad_spend, 0)) / nullif(sum(coalesce(p.ad_sales, 0)), 0) as acos_30d,
    sum(coalesce(p.ad_clicks, 0)) / nullif(sum(coalesce(p.ad_impressions, 0)), 0) as ctr_30d
from etl_datasync_test.dashboard_product_performance_daily p
inner join etl_datasync_test.dashboard_pur_plan_replenish_data r
        on r.cur_date = %(snapshot_date)s
       and r.country_category = p.country_category
       and r.seller_name_new = p.seller_name_new
       and r.seller_sku_adj = p.seller_sku_adj
where p.dt_date between %(period_start)s and %(biz_date)s
group by
    p.country_category,
    p.country,
    p.seller_name_new,
    p.seller_sku_adj;
```

---

## 5. 页面展示方式

### 5.1 主表只放国家摘要

补货 SKU 主表仍然保持一行汇总，不把每个国家的毛利、排名、日销等指标直接铺成很多列。

主表只新增一个轻量字段：

```text
国家表现
```

展示方式可以是：

```text
DE 80 | FR 42 | IT 31
```

或：

```text
国家 9 个 / Top: 德国 80
```

该列只承担“快速识别国家表现概况”和“打开明细”的作用，不承载完整经营指标。

不建议在主表后面追加类似下面的列：

```text
德国销量、德国毛利率、德国排名、法国销量、法国毛利率、法国排名...
```

原因是欧洲站国家较多，指标再增加后列数会爆炸，主表补货决策字段会被挤压，阅读和横向滚动成本都会变高。

### 5.2 右侧抽屉展示国家明细

点击主表的“国家表现”列或“国家明细”按钮后，打开右侧抽屉。

抽屉顶部显示当前主表对象：

```text
MSKU / 店铺 / 国家类别
```

示例：

```text
OYJ078a / ouyaojing / 欧洲站
```

抽屉内固定提示：

```text
该明细仅用于查看国家经营表现，不参与库存支撑天数、补货层级或补货数量计算。
```

### 5.3 抽屉支持周期切换

抽屉内增加周期切换：

```text
7天 | 14天 | 30天 | 90天
```

默认打开：

```text
30天
```

原因是当前补货主表已有 30 天销量、30 天毛利率等字段，默认 30 天最容易和主表口径对齐。

周期用途：

| 周期 | 用途 |
| --- | --- |
| 7 天 | 看短期波动和最近趋势 |
| 14 天 | 看近两周变化，降低单周偶然性 |
| 30 天 | 默认经营表现口径，和主表展示最接近 |
| 90 天 | 看长期稳定表现 |

切换周期时，只刷新抽屉内国家明细，不刷新补货主表，不改变补货主表任何计算结果。

### 5.4 抽屉汇总指标

抽屉表格上方展示当前周期汇总：

```text
国家数
周期销量
周期销售额
周期毛利率
```

可选再加：

```text
Top 国家
最低毛利国家
排名最好国家
```

但第一版建议只做前四个，避免信息过载。

### 5.5 抽屉国家明细表字段

国家明细表建议展示：

| 页面字段 | 数据字段 | 展示说明 |
| --- | --- | --- |
| 国家 | `country` | 例如德国、法国 |
| Listing SKU 汇总 | `local_sku_list` | 可选展示；同一国家下多个 local_sku 合并显示 |
| 30 天销量 | `sales_30d` | 按销量降序默认排序 |
| 30 天自然日销 | `daily_sales_30d` | 销量 / 30 |
| 30 天可售日销 | `salable_daily_sales_30d` | 销量 / 可售天数 |
| 30 天销售额 | `sales_amount_30d` | 金额 |
| 30 天利润 | `order_profit_30d` | 订单毛利 |
| 30 天毛利率 | `order_profit_rate_30d` | 利润 / 销售额 |
| 平均排名 | `avg_ranking_30d` | 排名数字越小越好 |
| 最好排名 | `best_ranking_30d` | 30 天内最小排名 |
| 最差排名 | `worst_ranking_30d` | 30 天内最大排名 |
| Sessions | `sessions_30d` | 流量 |
| 转化率 | `conversion_rate_30d` | 销量 / Sessions |
| 广告花费 | `ad_spend_30d` | 广告投入 |
| 广告销售额 | `ad_sales_30d` | 广告产出 |
| ACOS | `acos_30d` | 广告花费 / 广告销售额 |
| CTR | `ctr_30d` | 点击 / 曝光 |

页面说明必须固定展示：

```text
该明细仅用于查看国家经营表现，不参与库存支撑天数、补货层级或补货数量计算。
```

### 5.6 不采用行下子表

不在主表行下面展开子表。

原因：

- 主表已经有横向滚动，行下子表会让纵向阅读变重。
- 国家明细字段较多，行内空间不足。
- 右侧抽屉更适合承载周期切换、汇总卡片和完整国家表格。
- 抽屉可以保持主表当前位置不变，用户关掉抽屉后继续看主表。

---

## 6. 和现有补货规则的隔离方式

### 6.1 不改主表

不向 `dashboard_pur_plan_replenish_data` 增加国家粒度字段。

### 6.2 不改主 ETL 中间计算

不改这些临时表的粒度：

```text
tmp_pur_plan_candidate_keys
tmp_prod_perf_sku_metrics
tmp_pur_plan_support_metric_base
tmp_pur_plan_support_calc_base
tmp_pur_plan_support_layer_all
tmp_pur_plan_replenish_calc
```

它们继续按：

```text
country_category + seller_name_new + seller_sku_adj
```

### 6.3 只在主结果之后生成展示表

执行顺序：

```text
1. 生成 dashboard_pur_plan_replenish_data
2. 根据 dashboard_pur_plan_replenish_data 的主键范围生成 dashboard_replenishment_listing_30d_metrics
3. 页面按主表行下钻查询国家明细
```

这样国家明细无法反向影响补货结果。

---

## 7. 后端 API 规划

新增 API：

```text
GET /api/replenishment/country-metrics
```

参数：

```text
snapshot_date
site              对应 country_category
store             对应 seller_name_new
msku              对应 seller_sku_adj
sort_field
sort_dir
```

查询条件：

```sql
where snapshot_date = %(snapshot_date)s
  and country_category = %(site)s
  and seller_name_new = %(store)s
  and seller_sku_adj = %(msku)s
```

默认排序：

```text
sales_30d desc, salable_daily_sales_30d desc, country
```

---

## 8. 校验口径

实现后需要核对：

1. 主补货表行数不变。
2. 主补货表各分层 MSKU 数不变。
3. 主补货表补货数量、箱数、货值不变。
4. 某个主表 MSKU 的国家明细销量合计，应该接近主表 `final_sales_30d`。
5. 如果国家明细合计和主表不一致，优先检查：
   - `country` 是否存在空值
   - 同一国家下多个 `local_sku` 是否已经被正确聚合
   - 产品日表是否有汇总行和国家行同时存在

---

## 9. 后续实现顺序

1. 新增建表 SQL。
2. 新增最近 30 天聚合 SQL。
3. 在补货 ETL 主结果生成后追加执行展示表生成。
4. 新增只读 API。
5. 前端在补货明细表增加“国家明细”入口。
6. 用页面和 SQL 校验主补货结果未变化。
