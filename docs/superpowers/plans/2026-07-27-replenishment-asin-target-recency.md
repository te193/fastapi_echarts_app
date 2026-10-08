# 同 ASIN 补货承接 MSKU 时效性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让同 ASIN 合并补货优先承接到产品表现日期最新的可承接 MSKU，同时保持原有补货数量和货值计算口径。

**Architecture:** 在补货结果 SQL 中新增候选 MSKU 最新产品表现日期临时聚合，并将日期放到承接目标窗口排序的首位。日期相同时继续使用现有排序，结果仍由原补货 ETL 统一写入，不增加表字段或接口。

**Tech Stack:** Python 3、MySQL 8 窗口函数、`unittest`/`pytest`

---

### Task 1: 增加承接目标时效性回归测试

**Files:**
- Modify: `tests/test_replenishment_update_sql.py`

- [ ] **Step 1: 写入失败测试**

在 `ReplenishmentUpdateSqlTests` 中增加：

```python
def test_asin_merge_target_prefers_latest_product_performance_date(self):
    sql = " ".join(replenishment_update.REPLENISHMENT_RESULT_SQL.split())
    target_sql = sql.split(
        "create temporary table tmp_asin_merge_targets as", 1
    )[1].split(
        "drop temporary table if exists tmp_asin_merge_assignments", 1
    )[0]

    latest_date_expr = "coalesce(perf.max_perf_date, date('1900-01-01')) desc"
    followed_rank = "case when coalesce(calc.followed_flag, 0) = 0 then 0 else 1 end"

    self.assertIn("tmp_asin_merge_latest_performance", sql)
    self.assertIn(
        "max(dt_date) as max_perf_date",
        sql,
    )
    self.assertIn(latest_date_expr, target_sql)
    self.assertLess(target_sql.index(latest_date_expr), target_sql.index(followed_rank))
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_replenishment_update_sql.py::ReplenishmentUpdateSqlTests::test_asin_merge_target_prefers_latest_product_performance_date -q
```

Expected: `FAIL`，原因是 SQL 尚未包含 `tmp_asin_merge_latest_performance`。

### Task 2: 修改承接目标排序

**Files:**
- Modify: `etl/replenishment_update.py`

- [ ] **Step 1: 增加候选最新产品表现临时表**

在 `tmp_asin_merge_targets` 前加入：

```sql
drop temporary table if exists tmp_asin_merge_latest_performance;
create temporary table tmp_asin_merge_latest_performance as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    max(dt_date) as max_perf_date
from etl_datasync.dashboard_product_performance_daily
where dt_date <= %(biz_date)s
group by country_category, seller_name_new, seller_sku_adj;
```

- [ ] **Step 2: 在承接目标候选中关联最新日期**

在候选查询中加入：

```sql
left join tmp_asin_merge_latest_performance perf
       on calc.country_category = perf.country_category
      and calc.seller_name_new = perf.seller_name_new
      and calc.seller_sku_adj = perf.seller_sku_adj
```

- [ ] **Step 3: 将日期放在窗口排序首位**

窗口排序首项加入：

```sql
coalesce(perf.max_perf_date, date('1900-01-01')) desc,
```

其后保留原有被跟卖、停售、成本、库存、销量、店铺和 MSKU 排序。

- [ ] **Step 4: 运行定向测试并确认通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_replenishment_update_sql.py::ReplenishmentUpdateSqlTests::test_asin_merge_target_prefers_latest_product_performance_date -q
```

Expected: `1 passed`。

### Task 3: 验证回归与重算结果

**Files:**
- Verify: `etl/replenishment_update.py`
- Verify: `tests/test_replenishment_update_sql.py`

- [ ] **Step 1: 运行补货 SQL 测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_replenishment_update_sql.py -q
```

Expected: 全部通过。

- [ ] **Step 2: 运行完整测试集**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 全部通过。

- [ ] **Step 3: 重跑 2026-07-27 补货结果**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_replenishment_update.ps1 -BizDate 2026-07-26 -SnapshotDate 2026-07-27
```

执行完整补货流程，确保同步表和结果表使用同一批数据。

- [ ] **Step 4: 核对指定 ASIN**

查询 `2026-07-27` 结果，确认：

```text
B0DP3ZL1RL -> YuanJinRong/5L-KMVA-BDDG，补货数量 200
B0DP9CD47N -> YuanJinRong/Q8-XW1Y-P3G6，补货数量 140
```

同时确认旧承接行的补货数量、箱数和货值均为 0。

- [ ] **Step 5: 复查全部时效落后组**

重新运行只读差异查询，预期当前承接目标的最新产品表现日期不再落后于同组候选的最新日期。

- [ ] **Step 6: 检查工作区差异**

Run:

```powershell
git diff --check
git status --short
```

只应包含本次 SQL、测试和实施计划改动，以及用户原有的未跟踪文件。
