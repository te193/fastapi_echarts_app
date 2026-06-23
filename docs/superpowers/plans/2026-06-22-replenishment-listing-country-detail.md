# Replenishment Country Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每日补货看板中增加“国家明细”查看能力，把欧洲站下德国、法国、意大利等国家的最近 30 天表现拆出来看排名、销量、日销和经营指标，但不改变补货主计算。

**Architecture:** 保持补货主结果表 `dashboard_pur_plan_replenish_data` 的三维粒度不变：`cur_date + country_category + seller_name_new + seller_sku_adj`。新增一张只读展示用的 30 天国家明细表，粒度为 `snapshot_date + country_category + country + seller_name_new + seller_sku_adj`，通过国家类别、店铺、MSKU 关联到主表。前端在补货 SKU 明细表中打开某个 MSKU 的国家明细，不把国家级指标写回库存支撑天数、补货层级、需求量或补货数量。

**Tech Stack:** Python 3, PyMySQL, MySQL 8, FastAPI, AG Grid, existing `etl.replenishment_update` and `app.services.replenishment_data` patterns, pytest.

---

## 1. 需求理解

### 1.1 当前补货主粒度

当前补货主表：

```text
etl_datasync.dashboard_pur_plan_replenish_data
```

当前主键：

```text
cur_date + country_category + seller_name_new + seller_sku_adj
```

也就是页面里现在看到的一行补货记录，是按：

```text
补货日期 + 国家类别/站点 + 店铺 + MSKU
```

聚合后的结果。

这个粒度继续用于：

- 补货基础池
- 30/14/7/3 天销量聚合
- 30 天毛利率和产品分类
- 库存可支撑天数
- 紧急/建议/计划/库存充足/日销为 0 分层
- 需求量
- 补货数量
- 箱数
- 补货货值

### 1.2 新增国家明细的边界

新增明细只用于“查看表现”，不参与补货判断。

新增维度：

```text
国家类别 country_category
  -> 国家 country / marketplace
     -> 店铺 seller_name_new
        -> MSKU seller_sku_adj
```

例如当前主表一行：

```text
欧洲站 + ouyaojing + OYJ078a
```

国家明细可以拆成：

```text
欧洲站 + 德国 + ouyaojing + OYJ078a
欧洲站 + 法国 + ouyaojing + OYJ078a
欧洲站 + 意大利 + ouyaojing + OYJ078a
...
```

这些国家明细只展示最近 30 天：

- 国家
- 可选展示 local_sku 汇总，但不作为明细粒度
- 30 天销量
- 30 天销售额
- 30 天利润
- 30 天毛利率
- 30 天可售天数
- 30 天可售日销
- 平均排名
- 最好排名
- 最差排名
- Sessions
- 转化率
- 广告花费
- 广告销售额
- ACOS

### 1.3 明确不做的事

以下逻辑不改：

- 不把国家维度加入 `dashboard_pur_plan_replenish_data` 主键。
- 不按国家拆补货数量。
- 不按国家重算库存支撑天数。
- 不按国家重算补货层级。
- 不按国家重算补货需求量。
- 不改变补货导出主表字段顺序。

---

## 2. 推荐数据方案

### 2.1 新增本地展示表

新增表：

```text
etl_datasync.dashboard_replenishment_country_30d_metrics
```

建议字段：

```sql
create table if not exists etl_datasync.dashboard_replenishment_country_30d_metrics (
    snapshot_date date not null,
    period_start date not null,
    period_end date not null,
    country_category varchar(64) not null,
    country varchar(64) not null,
    seller_name_new varchar(128) not null,
    seller_sku_adj varchar(128) not null,
    local_sku_list text null,
    sales_30d decimal(18,4) not null default 0,
    sales_amount_30d decimal(18,4) not null default 0,
    order_profit_30d decimal(18,4) not null default 0,
    order_profit_rate_30d decimal(18,6) null,
    salable_days_30d int not null default 0,
    salable_daily_sales_30d decimal(18,6) not null default 0,
    avg_ranking_30d decimal(18,4) null,
    best_ranking_30d decimal(18,4) null,
    worst_ranking_30d decimal(18,4) null,
    sessions_30d decimal(18,4) not null default 0,
    conversion_rate_30d decimal(18,6) null,
    ad_spend_30d decimal(18,4) not null default 0,
    ad_sales_30d decimal(18,4) not null default 0,
    acos_30d decimal(18,6) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (snapshot_date, country_category, country, seller_name_new, seller_sku_adj),
    key idx_repl_country_parent (snapshot_date, country_category, seller_name_new, seller_sku_adj),
    key idx_repl_country_rank (snapshot_date, country_category, seller_name_new, sales_30d)
) engine=InnoDB default charset=utf8mb4;
```

### 2.2 数据来源

优先使用本地日表：

```text
etl_datasync.dashboard_product_performance_daily
```

原因：

- 已经是本地表，不需要页面查询远端。
- 粒度里有 `country` 和 `country_category`。
- 可以按最近 30 天聚合到国家维度。
- 已经服务其他看板，字段口径相对稳定。

聚合窗口：

```text
period_end = biz_date
period_start = biz_date - 29 days
snapshot_date = 补货结果日期
```

基础 SQL 形态：

```sql
delete from etl_datasync.dashboard_replenishment_country_30d_metrics
where snapshot_date = %(snapshot_date)s;

insert into etl_datasync.dashboard_replenishment_country_30d_metrics (
    snapshot_date,
    period_start,
    period_end,
    country_category,
    country,
    seller_name_new,
    seller_sku_adj,
    local_sku_list,
    sales_30d,
    sales_amount_30d,
    order_profit_30d,
    order_profit_rate_30d,
    salable_days_30d,
    salable_daily_sales_30d,
    avg_ranking_30d,
    best_ranking_30d,
    worst_ranking_30d,
    sessions_30d,
    conversion_rate_30d,
    ad_spend_30d,
    ad_sales_30d,
    acos_30d
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
    sum(coalesce(p.sales_amount, 0)) as sales_amount_30d,
    sum(coalesce(p.order_gross_profit, 0)) as order_profit_30d,
    sum(coalesce(p.order_gross_profit, 0)) / nullif(sum(coalesce(p.sales_amount, 0)), 0) as order_profit_rate_30d,
    sum(case when coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end) as salable_days_30d,
    sum(coalesce(p.sales_qty, 0)) / nullif(sum(case when coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end), 0) as salable_daily_sales_30d,
    avg(nullif(p.ranking, 0)) as avg_ranking_30d,
    min(nullif(p.ranking, 0)) as best_ranking_30d,
    max(nullif(p.ranking, 0)) as worst_ranking_30d,
    sum(coalesce(p.sessions_total, 0)) as sessions_30d,
    sum(coalesce(p.sales_qty, 0)) / nullif(sum(coalesce(p.sessions_total, 0)), 0) as conversion_rate_30d,
    sum(coalesce(p.ad_spend, 0)) as ad_spend_30d,
    sum(coalesce(p.ad_sales, 0)) as ad_sales_30d,
    sum(coalesce(p.ad_spend, 0)) / nullif(sum(coalesce(p.ad_sales, 0)), 0) as acos_30d
from etl_datasync.dashboard_product_performance_daily p
inner join etl_datasync.dashboard_pur_plan_replenish_data r
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

注意：上面 SQL 只把已经进入补货主表的 MSKU 做国家明细，避免生成全站全店铺无关明细。

---

## 3. 后端 API 方案

### 3.1 新增服务方法

修改：

```text
app/services/replenishment_data.py
```

新增方法：

```python
def get_country_metrics(
    self,
    snapshot_date: str,
    country_category: str,
    store: str,
    msku: str,
    sort_field: str = "sales_30d",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    ...
```

返回结构：

```json
{
  "snapshot_date": "2026-06-22",
  "period_start": "2026-05-24",
  "period_end": "2026-06-22",
  "parent": {
    "country_category": "欧洲站",
    "store": "ouyaojing",
    "msku": "OYJ078a"
  },
  "summary": {
    "country_count": 9,
    "sales_30d": 198,
    "sales_amount_30d": 22457.55,
    "order_profit_30d": 7908.94,
    "order_profit_rate_30d": 0.352173
  },
  "items": [
    {
      "country": "德国",
      "local_sku_list": "GQ1177a-de,GQ1177a-de-2",
      "sales_30d": 80,
      "salable_daily_sales_30d": 3.2,
      "order_profit_rate_30d": 0.31,
      "avg_ranking_30d": 18.5
    }
  ]
}
```

### 3.2 新增 API

修改：

```text
app/main.py
```

新增路由：

```python
@app.get("/api/replenishment/country-metrics")
def api_replenishment_country_metrics(
    snapshot_date: str = Query(default=""),
    site: str = Query(...),
    store: str = Query(...),
    msku: str = Query(...),
    sort_field: str = Query(default="sales_30d"),
    sort_dir: str = Query(default="desc"),
) -> dict:
    return replenishment_service.get_country_metrics(
        snapshot_date=snapshot_date,
        country_category=site,
        store=store,
        msku=msku,
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
```

### 3.3 排序字段白名单

API 只允许按这些字段排序：

```text
country
sales_30d
sales_amount_30d
order_profit_30d
order_profit_rate_30d
salable_days_30d
salable_daily_sales_30d
avg_ranking_30d
sessions_30d
conversion_rate_30d
ad_spend_30d
ad_sales_30d
acos_30d
```

默认排序：

```text
sales_30d desc, salable_daily_sales_30d desc, country
```

---

## 4. 前端展示方案

### 4.1 展示入口

修改：

```text
app/static/js/replenishment.js
app/templates/replenishment.html
app/static/css/styles.css
```

推荐方式：在补货明细表 `MSKU / SKU` 列增加一个小按钮或链接：

```text
查看国家明细
```

点击后在当前表格下方或右侧抽屉展示：

```text
OYJ078a / ouyaojing / 欧洲站 - 最近30天国家表现
```

不建议把国家明细直接平铺进主表，因为会让补货主表从一行变多行，容易误解为按国家补货。

### 4.2 国家明细表字段

表格列：

```text
国家
Listing SKU 汇总
30天销量
30天可售日销
30天销售额
30天利润
30天毛利率
平均排名
最好排名
最差排名
Sessions
转化率
广告花费
广告销售额
ACOS
```

页面顶部加一个小汇总：

```text
国家数
30天销量
30天销售额
30天利润
30天毛利率
```

### 4.3 UI 文案

必须明确说明这块用途：

```text
该明细仅用于查看国家经营表现，不参与库存支撑天数、补货层级或补货数量计算。
```

不要放在补货主指标卡里，避免用户误会它会影响补货建议。

---

## 5. 实施任务

### Task 1: 新增国家 30 天指标落表

**Files:**

- Modify: `etl/replenishment_update.py`
- Test: `tests/test_replenishment_update_sql.py`

- [ ] **Step 1: 写建表 SQL 测试**

新增测试断言：

```python
def test_country_metrics_table_uses_country_grain():
    sql = replenishment_update.CREATE_COUNTRY_30D_METRICS_SQL
    assert "dashboard_replenishment_country_30d_metrics" in sql
    assert "primary key (snapshot_date, country_category, country, seller_name_new, seller_sku_adj)" in sql
    assert "idx_repl_country_parent" in sql
```

- [ ] **Step 2: 新增建表 SQL**

在 `etl/replenishment_update.py` 中增加 `CREATE_COUNTRY_30D_METRICS_SQL`，字段按本文第 2.1 节。

- [ ] **Step 3: 写聚合 SQL 测试**

新增测试断言：

```python
def test_country_metrics_sql_does_not_feed_replenishment_calculation():
    sql = replenishment_update.BUILD_COUNTRY_30D_METRICS_SQL
    assert "dashboard_product_performance_daily" in sql
    assert "dashboard_pur_plan_replenish_data" in sql
    assert "r.cur_date = %(snapshot_date)s" in sql
    assert "p.country" in sql
    assert "group by" in sql.lower()
```

- [ ] **Step 4: 新增聚合 SQL**

新增 `DELETE_COUNTRY_30D_METRICS_SQL` 和 `BUILD_COUNTRY_30D_METRICS_SQL`，按 `snapshot_date` 先删后插。

- [ ] **Step 5: 接入 ETL 顺序**

在补货结果主表写入完成后执行国家 30 天指标聚合：

```text
build_replenishment_result
-> build_country_30d_metrics
```

这样国家明细只跟随已生成的补货结果，不影响补货结果生成。

### Task 2: 新增后端查询 API

**Files:**

- Modify: `app/services/replenishment_data.py`
- Modify: `app/main.py`
- Test: `tests/test_replenishment_data.py`

- [ ] **Step 1: 写序列化测试**

新增测试：

```python
def test_serialize_country_metric_formats_rates():
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    row = {
        "country": "德国",
        "local_sku_list": "GQ1177a-de,GQ1177a-de-2",
        "sales_30d": 10,
        "sales_amount_30d": 1000,
        "order_profit_30d": 200,
        "order_profit_rate_30d": 0.2,
        "salable_days_30d": 5,
        "salable_daily_sales_30d": 2,
        "avg_ranking_30d": 12.345,
        "best_ranking_30d": 5,
        "worst_ranking_30d": 30,
        "sessions_30d": 100,
        "conversion_rate_30d": 0.1,
        "ad_spend_30d": 50,
        "ad_sales_30d": 500,
        "acos_30d": 0.1,
    }
    item = service._serialize_country_metric(row)
    assert item["country"] == "德国"
    assert item["order_profit_rate_30d"] == 0.2
    assert item["avg_ranking_30d"] == 12.35
```

- [ ] **Step 2: 实现 `_serialize_country_metric`**

输出字段保持前端友好命名，不直接暴露数据库所有字段。

- [ ] **Step 3: 实现 `get_country_metrics`**

查询条件必须包含：

```sql
snapshot_date = %(snapshot_date)s
and country_category = %(country_category)s
and seller_name_new = %(store)s
and seller_sku_adj = %(msku)s
```

- [ ] **Step 4: 新增 FastAPI 路由**

在 `app/main.py` 新增 `/api/replenishment/country-metrics`。

### Task 3: 前端增加国家明细抽屉/面板

**Files:**

- Modify: `app/static/js/replenishment.js`
- Modify: `app/templates/replenishment.html`
- Modify: `app/static/css/styles.css`

- [ ] **Step 1: 主表增加入口**

在 `MSKU / SKU` 单元格里增加一个小按钮：

```text
国家明细
```

按钮携带当前行：

```text
snapshot_date
country
store
msku
```

- [ ] **Step 2: 请求 API**

点击后请求：

```text
/api/replenishment/country-metrics?snapshot_date=2026-06-22&site=欧洲站&store=ouyaojing&msku=OYJ078a
```

- [ ] **Step 3: 渲染明细表**

使用现有 AG Grid 组件渲染国家明细表。

默认排序：

```text
30天销量 desc
```

- [ ] **Step 4: 增加说明文案**

面板内固定显示：

```text
该明细仅用于查看国家经营表现，不参与库存支撑天数、补货层级或补货数量计算。
```

### Task 4: 验证

**Files:**

- Test: `tests/test_replenishment_update_sql.py`
- Test: `tests/test_replenishment_data.py`

- [ ] **Step 1: 跑服务层测试**

```powershell
python -m pytest tests/test_replenishment_update_sql.py tests/test_replenishment_data.py -q
```

Expected:

```text
passed
```

- [ ] **Step 2: 跑全量测试**

```powershell
python -m pytest -q
```

Expected:

```text
passed
```

- [ ] **Step 3: 本地页面验证**

打开：

```text
http://127.0.0.1:8001/replenishment
```

验证：

- 主表行数不因为国家明细增加而变化。
- 补货数量、补货货值、支撑天数不因为打开国家明细而变化。
- 点击某个欧洲站 MSKU 后，可以看到德国、法国、意大利等国家明细。
- 国家明细中 30 天销量合计应接近主表该 MSKU 的 `30天销量`。

---

## 6. 风险和口径

1. 如果 `dashboard_product_performance_daily.country` 不是“德国/法国”中文，而是 marketplace 编码，需要在服务层做国家名称映射。
2. 如果同一个 `seller_sku_adj` 在一个国家下有多个 `local_sku`，会先聚合成一条国家明细，`local_sku_list` 只作为参考展示。
3. 如果主表 30 天销量和国家明细 30 天销量合计有差异，优先排查国家映射是否一致、产品日表是否有汇总行。
4. 这张表只用于展示，不参与补货主链路计算，避免欧洲站拆国家后把库存和补货数量重复计算。

---

## 7. 推荐上线顺序

1. 先落表并用 SQL 校验某几个 MSKU 的国家明细是否正确。
2. 再开放 API。
3. 最后加前端入口。
4. 验证主表补货数量、支撑天数、层级计数和改造前完全一致。
