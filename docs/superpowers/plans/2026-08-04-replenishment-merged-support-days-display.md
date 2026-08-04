# 补货页面合并库存支撑天数显示实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让补货明细“库存 / 交期”列的当前支撑天数及排序，与到货时支撑统一使用同一库存范围。

**Architecture:** 在 `ReplenishmentDataService` 中增加页面专用 SQL 表达式：组成字段完整时使用 `arrival_inventory_support_days + effective_purchase_lead_days`，否则回退 `inventory_support_days`。明细查询和 `support_days` 排序共用该表达式，API 与前端字段保持不变。

**Tech Stack:** Python、FastAPI 服务层、MySQL SQL、pytest/unittest

## Global Constraints

- 不修改 ETL 和数据库原始字段。
- 不修改补货数量、补货层级、导出及前端列结构。
- 普通商品显示值不变。
- 同 ASIN 合并主链接显示合并后的当前支撑天数。

---

### Task 1: 统一补货明细当前支撑天数显示和排序

**Files:**
- Modify: `app/services/replenishment_data.py`
- Test: `tests/test_replenishment_data.py`

**Interfaces:**
- Consumes: `arrival_inventory_support_days`、`effective_purchase_lead_days`、`inventory_support_days`
- Produces: `ReplenishmentDataService._display_support_days_expr(alias: str = "") -> str`

- [ ] **Step 1: 写失败测试**

在 `tests/test_replenishment_data.py` 增加测试，验证：

```python
expr = service._display_support_days_expr("r")
self.assertIn("r.arrival_inventory_support_days + r.effective_purchase_lead_days", expr)
self.assertIn("else r.inventory_support_days", expr)
```

同时调用 `_fetch_items(..., sort_field="support_days")`，断言生成的明细查询和 `order by` 都使用该表达式，而不是直接使用 `inventory_support_days` 排序。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `python -m pytest tests/test_replenishment_data.py -k "display_support_days" -q`

Expected: FAIL，因为 `_display_support_days_expr` 尚不存在，查询仍直接读取和排序 `inventory_support_days`。

- [ ] **Step 3: 写最小实现**

在 `ReplenishmentDataService` 增加：

```python
def _display_support_days_expr(self, alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return (
        f"case when {prefix}arrival_inventory_support_days is not null "
        f"and {prefix}effective_purchase_lead_days is not null "
        f"then {prefix}arrival_inventory_support_days + {prefix}effective_purchase_lead_days "
        f"else {prefix}inventory_support_days end"
    )
```

在 `_fetch_items` 中：

- 将该表达式用于 `select ... as inventory_support_days`。
- 将 `sort_map["support_days"]` 指向相同表达式。

- [ ] **Step 4: 运行定向测试**

Run: `python -m pytest tests/test_replenishment_data.py -k "display_support_days" -q`

Expected: PASS。

- [ ] **Step 5: 运行相关和完整回归测试**

Run: `python -m pytest tests/test_replenishment_data.py tests/test_replenishment_frontend.py -q`

Run: `python -m pytest -q`

Expected: 全部 PASS。

- [ ] **Step 6: 重启并检查 8002 测试服务**

停止当前 8002 测试进程，继续使用测试数据库 `etl_datasync_replenishment_test` 启动服务。请求补货页面和明细接口，确认 HTTP 200；检查同 ASIN 主链接满足“当前支撑天数 - 采购交期 = 到货时支撑天数”。

- [ ] **Step 7: 提交实现**

```bash
git add app/services/replenishment_data.py tests/test_replenishment_data.py
git commit -m "统一合并库存支撑天数显示口径"
```
