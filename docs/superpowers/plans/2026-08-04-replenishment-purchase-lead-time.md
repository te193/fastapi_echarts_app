# Replenishment Purchase Lead Time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不写入正式库的前提下，将领星采购交期纳入补货分层和补货数量，并在专用测试库完成数据备份、重算和新旧结果验证。

**Architecture:** 采购交期从 `dwd_datasync.lx_product_local_product_info.cg_delivery` 只读同步到测试目标库的 listing basic 表，再沿现有补货 CTE 链路计算到货剩余天数、到货剩余库存和缺货风险。单链接使用自身采购交期；同 ASIN 合并使用与箱规、采购价、头程成本相同的采购字段来源记录。所有结果只写入 `etl_datasync_replenishment_test`，不调用测试数据推广功能。

**Tech Stack:** Python 3、PyMySQL、MySQL 8 SQL、pytest、Git worktree

## Global Constraints

- 工作分支固定为 `codex/replenishment-lead-time-test`，工作区为 `.worktrees/replenishment-lead-time-test`。
- 数据备份源仅为 `etl_datasync_test`，重算目标仅为 `etl_datasync_replenishment_test`。
- `dwd_datasync` 仅允许 SELECT；不得向 `etl_datasync` 或其他正式输出 schema 写入。
- 禁止执行 `python -m etl.replenishment_test_db --promote`。
- 补货目标保持120天，补货分层阈值保持35/65/90天。
- 预测日销、库存池、季节性、历史恢复、跟卖阻断、同 ASIN 目标链接、箱规和 MOQ 的现有顺序保持不变。
- 采购交期空值、0、负数按0参与计算并标记 `unconfigured`。
- 当 `R < 0` 时，基础需求为 `120 × D`；理论损失销量只作风险指标，不加入采购量。

---

### Task 1: Prepare and Back Up the Isolated Test Snapshot

**Files:**
- Verify: `etl/replenishment_test_db.py`
- Test: `tests/test_replenishment_test_db.py`

**Interfaces:**
- Consumes: `PRODUCTION_SCHEMA = "etl_datasync_test"`、`TEST_SCHEMA = "etl_datasync_replenishment_test"`
- Produces: 测试输入快照及 `baseline_dashboard_pur_plan_replenish_data`、`baseline_dashboard_replenishment_country_metrics`

- [ ] **Step 1: Verify the schema safety guard**

Run:

```powershell
python -c "from etl.replenishment_test_db import PRODUCTION_SCHEMA,TEST_SCHEMA,target_schemas; assert PRODUCTION_SCHEMA == 'etl_datasync_test'; assert TEST_SCHEMA == 'etl_datasync_replenishment_test'; assert target_schemas(PRODUCTION_SCHEMA,TEST_SCHEMA) == (PRODUCTION_SCHEMA,TEST_SCHEMA); print(PRODUCTION_SCHEMA, '->', TEST_SCHEMA)"
```

Expected: prints `etl_datasync_test -> etl_datasync_replenishment_test`.

- [ ] **Step 2: Run the existing test-database unit tests**

Run:

```powershell
python -m pytest tests/test_replenishment_test_db.py -q
```

Expected: PASS.

- [ ] **Step 3: Copy the bounded test snapshot and preserve the baseline**

Run:

```powershell
$snapshotDate = (python -c "from etl.replenishment_update import apply_database_ini_env; from etl.replenishment_test_db import connect_without_database,default_snapshot_date,PRODUCTION_SCHEMA; apply_database_ini_env(); c=connect_without_database(); print(default_snapshot_date(c,PRODUCTION_SCHEMA).isoformat()); c.close()").Trim()
$bizDate = ([datetime]$snapshotDate).AddDays(-1).ToString('yyyy-MM-dd')
python -m etl.replenishment_test_db --snapshot-date $snapshotDate
```

Expected: each bounded source table reports copied rows, both baseline tables report backed-up rows, and the final target is `etl_datasync_replenishment_test`.

- [ ] **Step 4: Verify the test schema contains both working and baseline rows**

Use the project connection loader and execute count-only queries for the selected snapshot:

```sql
select count(*) from etl_datasync_replenishment_test.dashboard_pur_plan_replenish_data where cur_date = :snapshot_date;
select count(*) from etl_datasync_replenishment_test.baseline_dashboard_pur_plan_replenish_data where cur_date = :snapshot_date;
```

Expected: both counts are greater than0; no query targets `etl_datasync.dashboard_pur_plan_replenish_data`.

### Task 2: Add Failing SQL Contract Tests for Lead-Time Behavior

**Files:**
- Modify: `tests/test_replenishment_update_sql.py`
- Test: `tests/test_replenishment_update_sql.py`

**Interfaces:**
- Consumes: `SELECT_LISTING_BASIC_SYNC_SQL`、`LISTING_BASIC_COLUMNS`、`REPLENISHMENT_RESULT_SQL`、`ensure_replenishment_columns`
- Produces: 对采购交期来源、字段传递、分层和数量公式的回归保护

- [ ] **Step 1: Add a failing test for purchase-lead synchronization**

Add assertions equivalent to:

```python
def test_listing_basic_sync_carries_purchase_lead_days_from_local_product_info():
    sql = " ".join(replenishment_update.SELECT_LISTING_BASIC_SYNC_SQL.split())
    assert "lx_product_local_product_info" in sql
    assert "cg_delivery" in sql
    assert "max_cg_delivery" in replenishment_update.LISTING_BASIC_COLUMNS
```

- [ ] **Step 2: Add failing tests for normal and stockout formulas**

Add assertions that require the rendered replenishment SQL to expose these exact output aliases and semantic branches:

```python
required_aliases = {
    "purchase_lead_days_raw",
    "effective_purchase_lead_days",
    "purchase_lead_status",
    "arrival_inventory_support_days",
    "arrival_inventory_qty",
    "lead_time_stockout_flag",
    "lead_time_stockout_days",
    "lead_time_lost_sales_qty",
    "lead_adjusted_replenish_need_qty",
}
```

The test must also verify that the layer thresholds are applied after subtracting effective purchase lead days and that arrival inventory uses `greatest(..., 0)`.

- [ ] **Step 3: Add a failing test for ASIN purchase-field inheritance**

Require `tmp_asin_merge_purchase_fields` to select `effective_purchase_lead_days` from the same ranked record that supplies `effective_max_cg_box_pcs`, `effective_max_cg_price`, and `effective_max_cg_transport_costs`.

- [ ] **Step 4: Run the focused tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_replenishment_update_sql.py -q
```

Expected: FAIL because `max_cg_delivery` and lead-time output fields do not exist yet.

### Task 3: Implement Lead-Time Synchronization and Calculations

**Files:**
- Modify: `etl/replenishment_update.py`
- Test: `tests/test_replenishment_update_sql.py`

**Interfaces:**
- Consumes: local SKU, `cg_delivery`, `support_inventory_qty`, `daily_avg_sales`, existing ASIN merge ranking
- Produces: `L`、`S`、`R`、`IA`、`G`、`M`、`Q1` and persisted explanation fields

- [ ] **Step 1: Synchronize the purchase lead field**

Add `max_cg_delivery` to `CREATE_LISTING_BASIC_SYNC_SQL`, `LISTING_BASIC_COLUMNS`, and `SELECT_LISTING_BASIC_SYNC_SQL`. Join `dwd_datasync.lx_product_local_product_info` by local SKU and calculate the listing-level raw value from `cg_delivery`.

- [ ] **Step 2: Add idempotent result columns**

Add the following columns to both the result table DDL and `ensure_replenishment_columns`:

```text
purchase_lead_days_raw
effective_purchase_lead_days
purchase_lead_status
arrival_inventory_support_days
arrival_inventory_qty
lead_time_demand_qty
base_replenish_need_qty
lead_adjusted_replenish_need_qty
lead_time_stockout_flag
lead_time_stockout_days
lead_time_lost_sales_qty
```

- [ ] **Step 3: Calculate detail-level lead-time metrics**

Use these formulas after `daily_avg_sales` is available:

```text
L  = case when max_cg_delivery > 0 then max_cg_delivery else 0 end
S  = support_inventory_qty / D
R  = S - L
IA = greatest(support_inventory_qty - L × D, 0)
G  = greatest(L - S, 0)
M  = G × D
Q0 = greatest(120 × D - support_inventory_qty, 0)
Q1 = greatest(120 × D - IA, 0)
```

Classify with `R` using the unchanged thresholds `35/65/90`, and feed `Q1` into the existing sales adjustment, box rounding, history recovery and MOQ chain.

- [ ] **Step 4: Keep ASIN purchase attributes aligned**

Extend the existing purchase-field ranking so the selected record carries box quantity, price, transport cost, and purchase lead together. Calculate group arrival inventory and group replenishment need with that inherited lead; keep non-target detail replenishment quantities blocked exactly as before.

- [ ] **Step 5: Persist explanation fields**

Extend the final insert column list and select list with the new lead-time fields. Preserve `inventory_support_days` as the current support value `S`; store the lead-adjusted value separately in `arrival_inventory_support_days`.

- [ ] **Step 6: Run the focused tests and confirm GREEN**

Run:

```powershell
python -m pytest tests/test_replenishment_update_sql.py tests/test_replenishment_test_db.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the implementation unit**

```powershell
git add etl/replenishment_update.py tests/test_replenishment_update_sql.py
git commit -m "将采购交期纳入补货分层和数量计算"
```

### Task 4: Recalculate and Validate Only in the Test Schema

**Files:**
- Verify: `etl/replenishment_update.py`
- Verify: `etl/replenishment_test_db.py`
- Modify if required by verified behavior: `tests/test_replenishment_update_sql.py`

**Interfaces:**
- Consumes: copied test snapshot and updated ETL SQL
- Produces: test-only replenishment result plus old/new reconciliation evidence

- [ ] **Step 1: Force the target schema for the process**

Set only the current PowerShell process environment:

```powershell
$env:DASHBOARD_TARGET_SCHEMA='etl_datasync_replenishment_test'
```

Before execution, run `python -m etl.replenishment_update --dry-run` and verify the printed target schema exactly matches `etl_datasync_replenishment_test`.

- [ ] **Step 2: Run the ETL for the copied snapshot**

Reuse the `$snapshotDate` and `$bizDate` values established in Task 1:

```powershell
python -m etl.replenishment_update --snapshot-date $snapshotDate --biz-date $bizDate --steps listing_basic_sync,replenishment_result,moq_gating
```

Expected: all three steps succeed and only the dedicated test schema receives writes.

- [ ] **Step 3: Run database verification**

Run:

```powershell
python -m etl.replenishment_test_db --verify-only --snapshot-date $snapshotDate
```

Expected: followed-link and MOQ checks report zero invalid rows.

- [ ] **Step 4: Reconcile the new formulas against the baseline**

For the copied snapshot, verify:

```text
L = 0                           -> old/new base quantity and layer unchanged
R >= 0 and Q1 > 0               -> IA + Q1 = 120 × D
R < 0                           -> Q1 = 120 × D
R < 0                           -> M is not included in Q1
followed/ASIN non-target blocked -> executable quantity remains 0
```

Also output counts by old/new layer, `R < 0` count, total lost-sales risk, calculated quantity delta, and executable quantity delta.

- [ ] **Step 5: Run the complete local test suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS with no new failures.

- [ ] **Step 6: Commit any verification-only test refinements**

```powershell
git add tests/test_replenishment_update_sql.py
git commit -m "补充采购交期补货计算的边界验证"
```
