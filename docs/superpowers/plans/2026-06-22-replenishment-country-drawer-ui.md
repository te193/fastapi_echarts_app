# Replenishment Country Drawer UI Plan

> This file is the final UI supplement for the replenishment country detail feature. If older planning notes mention row-level child tables, this file takes precedence.

## Goal

Add country-level operating metrics to the replenishment page without making the main replenishment table too wide or mixing country metrics into replenishment calculations.

## Final UI Decision

Use:

```text
Main table country summary column + right-side drawer + 7/14/30/90 day switch
```

Do not use:

```text
Expanded child table under each main table row
```

Do not append all country metrics as main table columns.

## Main Table

The main replenishment table still represents one aggregated replenishment row:

```text
snapshot_date + country_category + seller_name_new + seller_sku_adj
```

The main table can add one lightweight column:

```text
国家表现
```

Suggested display:

```text
DE 80 | FR 42 | IT 31
```

or:

```text
国家 9 个 / Top: 德国 80
```

This column is only an entry point and quick summary. It should not show every metric for every country.

## Right Drawer

Clicking the country summary column or a `国家明细` button opens a right-side drawer.

Drawer title:

```text
MSKU / 店铺 / 国家类别
```

Example:

```text
OYJ078a / ouyaojing / 欧洲站
```

Drawer fixed note:

```text
该明细仅用于查看国家经营表现，不参与库存支撑天数、补货层级或补货数量计算。
```

## Period Switch

The drawer supports:

```text
7天 | 14天 | 30天 | 90天
```

Default:

```text
30天
```

Period meaning:

| Period | Purpose |
| --- | --- |
| 7 days | Short-term movement |
| 14 days | Recent two-week performance |
| 30 days | Default view, closest to current main-table 30-day fields |
| 90 days | Longer-term stable performance |

Switching the period only refreshes drawer data. It must not refresh the main replenishment table or change replenishment quantity, inventory support days, or replenishment level.

## Drawer Summary

At the top of the drawer, show current-period summary cards:

```text
国家数
周期销量
周期销售额
周期毛利率
```

Optional later:

```text
Top 国家
最低毛利国家
排名最好国家
```

First version should keep only the four required cards.

## Country Metrics Table

One row per country:

```text
snapshot_date + period_days + country_category + country + seller_name_new + seller_sku_adj
```

Columns:

| Column | Notes |
| --- | --- |
| 国家 | Country / marketplace |
| Listing SKU 汇总 | Optional `local_sku_list`, not a grouping key |
| 周期销量 | `sum(sales_qty)` |
| 自然日销 | `sales_qty / period_days` |
| 可售日销 | `sales_qty / salable_days` |
| 销售额 | `sum(sales_amount)` |
| 利润 | `sum(order_gross_profit)` |
| 毛利率 | `sum(order_gross_profit) / sum(sales_amount)` |
| 平均排名 | `avg(nullif(ranking, 0))` |
| 最好排名 | `min(nullif(ranking, 0))` |
| 最差排名 | `max(nullif(ranking, 0))` |
| Sessions | `sum(sessions_total)` |
| 转化率 | `sum(sales_qty) / sum(sessions_total)` |
| 广告花费 | `sum(ad_spend)` |
| 广告销售额 | `sum(ad_sales)` |
| ACOS | `sum(ad_spend) / sum(ad_sales)` |

Default sort:

```text
周期销量 desc
```

## API Shape

Endpoint:

```text
GET /api/replenishment/country-metrics
```

Parameters:

```text
snapshot_date
site
store
msku
period_days
sort_field
sort_dir
```

Allowed `period_days`:

```text
7, 14, 30, 90
```

Default:

```text
30
```

Example:

```text
/api/replenishment/country-metrics?snapshot_date=2026-06-22&site=欧洲站&store=ouyaojing&msku=OYJ078a&period_days=30
```

## Data Table Grain

If using a stored local table, use this grain:

```text
snapshot_date + period_days + country_category + country + seller_name_new + seller_sku_adj
```

Do not include `local_sku` in the primary key or `group by`.

`local_sku_list` may be kept as a display-only field:

```sql
group_concat(distinct nullif(local_sku, '') order by nullif(local_sku, '') separator ',') as local_sku_list
```

## Guardrails

This drawer data must not feed:

- inventory support days
- replenish level
- replenish need quantity
- replenish quantity
- box quantity
- replenish cost

It is display-only.
