# 低于最小起订量独立分类展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让低于 MOQ 的商品在独立层级中显示计算补货数量、箱数和货值，同时继续从正常补货执行与汇总中排除。

**Architecture:** ETL 同时持久化计算值与可执行值；低于 MOQ 时计算值保留、可执行值归零。服务层将低于 MOQ 映射成独立展示层级，并仅在明细和导出中用计算值覆盖现有补货展示列，汇总仍使用可执行值。

**Tech Stack:** Python 3、FastAPI、PyMySQL、MySQL 8、原生 JavaScript、AG Grid、pytest。

## Global Constraints

- 首选供应商按 `is_primary = '是'` 过滤，阶梯报价取最小正数 MOQ。
- 不覆盖原 `replenish_qty / replenish_box_qty / replenish_cost` 字段。
- 不修改补货追踪数据与追踪逻辑。
- 所有浏览器验证必须后台无界面运行。

---

### Task 1: 持久化计算箱数与计算货值

**Files:**
- Modify: `etl/replenishment_update.py:360-390,2256-2318,2669-2710`
- Modify: `etl/replenishment_test_db.py:94-190`
- Test: `tests/test_replenishment_update_sql.py`
- Test: `tests/test_replenishment_test_db.py`

**Interfaces:**
- Produces: `calculated_replenish_box_qty`、`calculated_replenish_cost` 两个结果字段。
- Consumes: 现有 `calculated_replenish_qty`、历史兜底箱规与采购成本表达式。

- [ ] **Step 1: 写失败测试**

在 `tests/test_replenishment_update_sql.py` 断言 DDL、MOQ 门禁更新和补列逻辑均包含：

```python
self.assertIn("calculated_replenish_box_qty", ddl)
self.assertIn("calculated_replenish_cost", ddl)
self.assertIn("r.calculated_replenish_box_qty = g.calculated_replenish_box_qty", sql)
self.assertIn("r.calculated_replenish_cost = g.calculated_replenish_cost", sql)
```

在 `tests/test_replenishment_test_db.py` 断言生产提升 SQL 只写 MOQ 相关字段，并包含两个新计算字段。

- [ ] **Step 2: 验证测试按预期失败**

Run: `python -m pytest tests/test_replenishment_update_sql.py tests/test_replenishment_test_db.py -q`

Expected: FAIL，缺少两个计算字段或对应更新语句。

- [ ] **Step 3: 最小实现**

在结果表 DDL 与 `ensure_replenishment_columns()` 增加：

```sql
calculated_replenish_box_qty decimal(18,4) null,
calculated_replenish_cost decimal(18,4) null
```

在 `MOQ_GATING_SQL` 更新结果时增加：

```sql
r.calculated_replenish_box_qty = g.calculated_replenish_box_qty,
r.calculated_replenish_cost = g.calculated_replenish_cost,
```

在 `build_result_moq_update_sql()` 用现有生产计算表达式写入这两个字段；低于 MOQ 时仅 `executable_*` 归零。

- [ ] **Step 4: 运行专项测试**

Run: `python -m pytest tests/test_replenishment_update_sql.py tests/test_replenishment_test_db.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add etl/replenishment_update.py etl/replenishment_test_db.py tests/test_replenishment_update_sql.py tests/test_replenishment_test_db.py
git commit -m "保存MOQ预警计算箱数和货值"
```

### Task 2: 建立独立展示层级并分离展示值与执行值

**Files:**
- Modify: `app/services/replenishment_data.py:16-54,620-730,927-990,1462-1670`
- Test: `tests/test_replenishment_data.py`

**Interfaces:**
- Produces: `LEVEL_BELOW_MOQ = "低于最小起订量"`。
- Produces: `_detail_replenish_qty_expr()`、`_detail_replenish_box_qty_expr()`、`_detail_replenish_cost_expr()`。
- Consumes: `_display_replenish_*` 继续作为可执行汇总口径。

- [ ] **Step 1: 写失败测试**

新增测试验证：

```python
self.assertIn("moq_status = 'below_minimum'", service._display_level_expr())
self.assertIn("level_below_moq", service._display_level_expr())
self.assertIn("calculated_replenish_qty", service._detail_replenish_qty_expr())
self.assertIn("calculated_replenish_box_qty", service._detail_replenish_box_qty_expr())
self.assertIn("calculated_replenish_cost", service._detail_replenish_cost_expr())
```

再用记录 SQL 的测试连接验证 `_summary()` 仍引用 `executable_replenish_qty`，而 `_items()` 与 `_export_select_expression()` 使用 detail 表达式。

- [ ] **Step 2: 验证测试按预期失败**

Run: `python -m pytest tests/test_replenishment_data.py -q`

Expected: FAIL，缺少独立层级与 detail 展示表达式。

- [ ] **Step 3: 最小实现**

新增层级常量与排序：

```python
LEVEL_BELOW_MOQ = "低于最小起订量"
FLOW_LEVEL_ORDER[LEVEL_BELOW_MOQ] = 7
```

在 `_display_level_expr()` 最前增加 MOQ 判断，使低于 MOQ 优先显示为独立层级；层级筛选使用同一表达式，因此紧急、建议、计划自动排除该分类。

新增三组 detail 表达式：

```sql
case when moq_status = 'below_minimum'
     then coalesce(calculated_replenish_qty, 0)
     else <现有可执行展示表达式>
end
```

箱数与货值分别使用 `calculated_replenish_box_qty` 和 `calculated_replenish_cost`。明细、排序和导出映射使用 detail 表达式；顶部和层级汇总继续使用现有可执行表达式。

- [ ] **Step 4: 运行专项测试**

Run: `python -m pytest tests/test_replenishment_data.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add app/services/replenishment_data.py tests/test_replenishment_data.py
git commit -m "新增低于最小起订量独立层级"
```

### Task 3: 前端展示与筛选

**Files:**
- Modify: `app/static/js/replenishment.js:400-470,730-840,1270-1340`
- Modify: `app/static/css/styles.css`
- Modify: `app/templates/replenishment.html:250`
- Test: `tests/test_replenishment_moq_frontend.py`
- Test: `tests/test_replenishment_frontend.py`

**Interfaces:**
- Consumes: API 返回层级“低于最小起订量”及现有 `replenish_qty / box_qty / cost` 字段。
- Produces: 独立层级标签、筛选入口和对应视觉样式。

- [ ] **Step 1: 写失败测试**

在静态前端测试中断言：

```python
assert "低于最小起订量" in source
assert 'below_minimum' in source
assert "calculated_replenish_box_qty" not in source  # 前端继续消费统一展示字段
```

并更新模板缓存版本断言。

- [ ] **Step 2: 验证测试按预期失败**

Run: `python -m pytest tests/test_replenishment_moq_frontend.py tests/test_replenishment_frontend.py -q`

Expected: FAIL，缺少独立层级文案或缓存版本。

- [ ] **Step 3: 最小实现**

为层级映射和图标补充“低于最小起订量”，使用现有橙色 MOQ 预警色；预警卡点击仍设置 `moq_status=below_minimum`。AG Grid 的补货数量、箱数、货值列不新增重复列，直接展示 API 统一返回的参考值。

更新 `replenishment.js` 缓存版本，确保 8001 页面刷新后加载新逻辑。

- [ ] **Step 4: 运行前端测试与语法检查**

Run: `python -m pytest tests/test_replenishment_moq_frontend.py tests/test_replenishment_frontend.py -q`

Run: `node --check app/static/js/replenishment.js`

Expected: 全部 PASS，Node 退出码 0。

- [ ] **Step 5: 提交**

```powershell
git add app/static/js/replenishment.js app/static/css/styles.css app/templates/replenishment.html tests/test_replenishment_moq_frontend.py tests/test_replenishment_frontend.py
git commit -m "展示低于MOQ独立分类参考补货值"
```

### Task 4: 测试库、现有库与后台浏览器验收

**Files:**
- No code changes expected.

**Interfaces:**
- Consumes: Tasks 1-3 的数据库字段、API 口径和前端资源。
- Produces: 测试库与生产库验证记录。

- [ ] **Step 1: 在测试库补列并重跑 MOQ 门禁**

Run: `python -c "import os,sys; from pathlib import Path; from etl.replenishment_update import apply_database_ini_env,main; apply_database_ini_env(Path(r'config/database.ini')); os.environ['DASHBOARD_TARGET_SCHEMA']='etl_datasync_replenishment_test'; sys.argv=['replenishment_update','--biz-date','2026-07-20','--snapshot-date','2026-07-21','--steps','supplier_moq_sync,moq_gating']; main()"`

Expected: 测试库字段存在，MOQ 门禁成功。

- [ ] **Step 2: 验证测试库口径**

检查低于 MOQ 行满足：可执行值为 0，计算数量/箱数/货值大于等于 0，展示层级为“低于最小起订量”；紧急/建议/计划筛选返回 0 条 MOQ 预警。

- [ ] **Step 3: 事务提升现有库**

Run: `python -c "import sys; from pathlib import Path; from etl.replenishment_update import apply_database_ini_env; apply_database_ini_env(Path(r'config/database.ini')); from etl.replenishment_test_db import main; sys.argv=['replenishment_test_db','--snapshot-date','2026-07-21','--promote']; main()"`

Expected: MOQ 快照和 3,669 行 MOQ 字段事务提交成功，原补货字段不变。

- [ ] **Step 4: 完整回归**

Run: `python -m pytest -q`

Expected: 全部测试 PASS。

- [ ] **Step 5: 后台浏览器验收**

使用无界面 Playwright 打开 `http://127.0.0.1:8001/replenishment?snapshot_date=2026-07-21`，验证：

- 预警卡进入独立分类。
- 行内补货数量、箱数、货值为计算参考值。
- 紧急、建议、计划筛选均不出现预警行。
- 导出 CSV 中预警行保留三个参考值。
- 控制台无错误。

- [ ] **Step 6: 重启并核对 8001 服务**

隐藏重启原 uvicorn 进程；请求页面与 `/api/replenishment`，确认新缓存版本、独立层级与汇总口径生效。
