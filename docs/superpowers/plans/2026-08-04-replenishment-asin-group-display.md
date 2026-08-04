# 同 ASIN 产品组补货指标统一展示实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让同一补货合并组内所有链接展示完全一致的产品组库存支撑、交期指标和补货层级，同时保持现有补货数量只落到目标链接。

**Architecture:** 复用 `tmp_asin_merge_assignments` 已计算的产品组指标，在最终结果落表时对所有 `asin_merge_flag = 1` 行应用，而非只应用于 `asin_merge_target_flag = 1` 的目标行；接口层移除“ASIN合并且零补货强制显示库存充足”的覆盖。结果表继续作为页面统计、筛选、排序和明细的统一来源。

**Tech Stack:** Python、MySQL 8 SQL、FastAPI 服务层、pytest/unittest

## Global Constraints

- 只修改并重算 `etl_datasync_replenishment_test`，不得写正式库。
- 不修改产品组日销、库存汇总、补货需求、目标链接选择、箱规、成本、MOQ或历史恢复公式。
- 同 ASIN 合并组内所有链接使用相同产品组指标与产品组层级。
- 补货数量、箱数和货值仍只由目标链接承接。
- 普通单链接结果保持不变。

---

### Task 1: 锁定 ETL 产品组指标落表规则

**Files:**
- Modify: `tests/test_replenishment_update_sql.py`
- Modify: `etl/replenishment_update.py`

**Interfaces:**
- Consumes: `assign.asin_merge_flag`、`assign.group_*`、`purchase.*`
- Produces: `final_inventory_support_days`、`final_support_replenish_level`、`final_support_replenish_level_sort` 及现有 `final_*` 交期指标

- [ ] **Step 1: 写失败的 SQL 合同测试**

增加测试，截取最终 `from tmp_pur_plan_replenish_calc calc` 之前的合并表达式，要求：

```python
self.assertIn(
    "when coalesce(assign.asin_merge_flag, 0) = 1 then assign.group_inventory_support_days",
    merged_sql,
)
self.assertIn("end as final_inventory_support_days", merged_sql)
self.assertIn("end as final_support_replenish_level_sort", merged_sql)
self.assertNotIn(
    "when coalesce(assign.asin_merge_target_flag, 0) = 1 then assign.group_arrival_inventory_support_days",
    merged_sql,
)
```

并要求最终 insert select 使用：

```text
final_inventory_support_days as inventory_support_days
final_support_replenish_level as support_replenish_level
final_support_replenish_level_sort as support_replenish_level_sort
```

- [ ] **Step 2: 运行定向测试并确认 RED**

Run: `python -m pytest tests/test_replenishment_update_sql.py -k "all_asin_links_use_group" -q`

Expected: FAIL，因为当前只有目标链接替换到货指标，当前支撑和层级仍使用单链接字段。

- [ ] **Step 3: 实现所有合并链接使用产品组指标**

在最终合并子查询中：

- `asin_merge_flag = 1` 时使用产品组当前支撑、到货支撑、到货库存、交期需求、补货基础需求和断货风险字段。
- `asin_merge_flag = 1` 时所有行使用同一采购交期来源。
- 根据 `group_support_replenish_level_sort` 映射产品组层级文字：1紧急、2建议、3计划、4库存充足、5日销为0。
- 普通行回退 `calc.*` 原字段。
- 最终 insert select 使用上述 `final_*` 字段。
- 补货数量、箱数、成本相关条件继续使用 `asin_merge_target_flag`，不作改动。

- [ ] **Step 4: 运行定向测试并确认 GREEN**

Run: `python -m pytest tests/test_replenishment_update_sql.py -k "all_asin_links_use_group" -q`

Expected: PASS。

### Task 2: 取消页面零补货层级覆盖

**Files:**
- Modify: `tests/test_replenishment_data.py`
- Modify: `app/services/replenishment_data.py`

**Interfaces:**
- Consumes: 结果表中已统一的 `support_replenish_level`、`support_replenish_level_sort`
- Produces: 页面层级统计、筛选、排序和明细使用同一产品组层级

- [ ] **Step 1: 写失败的接口层级测试**

将原“ASIN合并零补货显示库存充足”测试改为：

```python
level_expr = service._display_level_expr()
sort_expr = service._display_level_sort_expr()
self.assertNotIn("asin_merge_flag", level_expr)
self.assertNotIn("asin_merge_flag", sort_expr)
self.assertIn("else support_replenish_level end", level_expr)
self.assertIn("else support_replenish_level_sort end", sort_expr)
```

- [ ] **Step 2: 运行定向测试并确认 RED**

Run: `python -m pytest tests/test_replenishment_data.py -k "asin_merge_rows_keep_group_layer" -q`

Expected: FAIL，因为当前表达式仍将部分零补货行覆盖成库存充足。

- [ ] **Step 3: 写最小实现**

删除 `_asin_merge_zero_qty_display_condition` 及 `_display_level_expr`、`_display_level_sort_expr` 中对应分支；保留 MOQ 和历史恢复的既有覆盖顺序。

- [ ] **Step 4: 运行定向测试并确认 GREEN**

Run: `python -m pytest tests/test_replenishment_data.py -k "asin_merge_rows_keep_group_layer" -q`

Expected: PASS。

### Task 3: 回归测试、测试库重算和实际核对

**Files:**
- Verify: `etl/replenishment_update.py`
- Verify: `etl/replenishment_test_db.py`
- Verify: `app/services/replenishment_data.py`

**Interfaces:**
- Consumes: 2026-08-03 测试快照
- Produces: 8002 测试页面的统一产品组展示

- [ ] **Step 1: 运行相关测试**

Run: `python -m pytest tests/test_replenishment_update_sql.py tests/test_replenishment_data.py tests/test_replenishment_test_db.py tests/test_replenishment_frontend.py -q`

Expected: 全部 PASS。

- [ ] **Step 2: 验证目标库安全配置**

确认 `DASHBOARD_TARGET_SCHEMA=etl_datasync_replenishment_test`，并通过 dry-run 检查渲染 SQL 中只出现测试目标 schema。

- [ ] **Step 3: 重算测试快照**

以 `snapshot_date=2026-08-03`、`biz_date=2026-08-02` 运行补货结果和 MOQ 步骤，仅写测试库。

- [ ] **Step 4: 数据库验收**

只读核对：

```text
QP122b 欧洲站两条链接：80.19天、到货70.19天、计划补货
QP0102b 同组链接：产品组支撑、到货支撑和层级一致
每个合并组正补货目标数 <= 1
被跟卖原始链接正补货数 = 0
普通单链接与重算前业务公式一致
```

- [ ] **Step 5: 运行完整回归**

Run: `python -m pytest -q`

Expected: 全部 PASS。

- [ ] **Step 6: 重启并验证 8002**

重启测试服务，确认页面与 `/api/replenishment` 返回 HTTP 200，并核对 QP122b 组内所有欧洲站链接的支撑天数、到货支撑和层级一致。

- [ ] **Step 7: 提交实现**

```powershell
git add etl/replenishment_update.py app/services/replenishment_data.py tests/test_replenishment_update_sql.py tests/test_replenishment_data.py
git commit -m "统一同ASIN产品组补货指标和层级"
```
