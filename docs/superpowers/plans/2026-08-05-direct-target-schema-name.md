# Direct Target Schema Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local target table references use `etl_datasync_test` directly while preserving configurable target Schema rendering and keeping remote source references unchanged.

**Architecture:** Treat `etl_datasync_test` as the canonical target Schema written in Python SQL templates. Extend the existing renderers to translate that canonical name to `SchemaConfig.target_schema`, then mechanically update target-table references without changing SQL behavior.

**Tech Stack:** Python, MySQL SQL templates, unittest/pytest.

---

### Task 1: Define target Schema rendering behavior

**Files:**
- Modify: `tests/test_dashboard_daily_update_sql.py`
- Modify: `tests/test_replenishment_update_sql.py`

- [ ] **Step 1: Add a failing test for dashboard target tables**

Import `render_sql` and assert:

```python
schemas = SchemaConfig(
    target_schema="etl_datasync_replenishment_test",
    etl_source_schema="etl_datasync",
    dwd_source_schema="dwd_datasync",
    pricing_source_schema="temporary_dwd",
)
rendered = render_sql(
    "select * from etl_datasync_test.dashboard_inventory_daily_snapshot",
    schemas,
)
assert rendered == (
    "select * from "
    "etl_datasync_replenishment_test.dashboard_inventory_daily_snapshot"
)
```

- [ ] **Step 2: Add a failing test for replenishment target tables**

Assert that:

```python
render_replenishment_sql(
    "select * from etl_datasync_test.pur_plan_prod_perf_salable_days_stat",
    schemas,
)
```

renders the table into `etl_datasync_replenishment_test`.

- [ ] **Step 3: Run focused tests and confirm the new assertions fail**

Run:

```powershell
python -m pytest tests/test_dashboard_daily_update_sql.py tests/test_replenishment_update_sql.py -q
```

Expected: the new canonical `etl_datasync_test` references remain unchanged and both new tests fail.

### Task 2: Extend the SQL renderers

**Files:**
- Modify: `etl/dashboard_daily_update.py`
- Modify: `etl/replenishment_update.py`

- [ ] **Step 1: Render canonical dashboard targets**

Update `render_sql()` so both the new canonical target name and legacy target name render to
`schemas.target_schema`:

```python
rendered = rendered.replace(
    "etl_datasync_test.dashboard_",
    f"{schemas.target_schema}.dashboard_",
)
rendered = rendered.replace(
    "etl_datasync.dashboard_",
    f"{schemas.target_schema}.dashboard_",
)
```

Keep the legacy line temporarily so external callers or untracked SQL snippets remain compatible.

- [ ] **Step 2: Render canonical replenishment targets**

Update `render_replenishment_sql()` to translate both:

```python
etl_datasync_test.pur_plan_
etl_datasync.pur_plan_
```

to `schemas.target_schema`.

- [ ] **Step 3: Run focused rendering tests**

Run:

```powershell
python -m pytest tests/test_dashboard_daily_update_sql.py tests/test_replenishment_update_sql.py -q
```

Expected: both new rendering tests pass.

### Task 3: Update Python SQL target references

**Files:**
- Modify: Python files under `app/`, `etl/`, and `tests/` containing `etl_datasync.dashboard_*`
- Modify: `etl/replenishment_update.py` and related tests containing local `etl_datasync.pur_plan_*`

- [ ] **Step 1: Replace local dashboard target references**

Mechanically replace:

```text
etl_datasync.dashboard_
```

with:

```text
etl_datasync_test.dashboard_
```

in Python source and test files only.

- [ ] **Step 2: Replace local replenishment result references**

Replace local target references:

```text
etl_datasync.pur_plan_
```

with:

```text
etl_datasync_test.pur_plan_
```

Do not modify `etl_datasync.etl_dispose_*`.

- [ ] **Step 3: Scan for leftovers and source-table damage**

Run:

```powershell
rg -n "etl_datasync\.dashboard_" app etl tests -g "*.py"
rg -n "etl_datasync_test\.etl_dispose_" app etl tests -g "*.py"
```

Expected: both commands return no matches.

### Task 4: Regression verification

**Files:**
- No production file changes expected.

- [ ] **Step 1: Run focused ETL and service tests**

Run:

```powershell
python -m pytest tests/test_dashboard_daily_update_sql.py tests/test_replenishment_update_sql.py tests/test_return_goods_update.py tests/test_sales_role_snapshot_update.py tests/test_dashboard_fixed_periods.py tests/test_opportunity_precompute.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Review the final diff**

Confirm the diff contains Schema naming and test changes only, with no SQL calculation, field, table structure, or task-order changes.
