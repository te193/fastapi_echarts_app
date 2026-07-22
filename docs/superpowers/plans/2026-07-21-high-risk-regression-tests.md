# High-Risk Business Regression Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add focused regression coverage for country profiles, replenishment cost inheritance, and the daily ETL chain without reading or writing business databases.

**Architecture:** Extend the existing unittest/pytest files and reuse their fake services, fake cursors, SQL-text assertions, and PowerShell-text assertions. Production code remains unchanged unless a new test exposes a verified defect.

**Tech Stack:** Python 3, pytest, unittest, FastAPI TestClient, SQL string contracts, PowerShell script contracts.

## Global Constraints

- Tests must not connect to the remote database.
- Tests must not write local business tables.
- Tests must not send DingTalk notifications.
- Prefer behavioral assertions over broad snapshots.
- Preserve the existing dirty worktree files outside the test scope.

---

### Task 1: Country Profile Service Regression Coverage

**Files:**
- Modify: `tests/test_country_label_hub_data.py`

**Interfaces:**
- Consumes: `CountryLabelHubDataService.get_label_hub_country_profile()` and `_cached_country_profile_metrics()`.
- Produces: regression tests for scope isolation, period handling, deduplication, source degradation, and summary consistency.

- [ ] Add tests that assert duplicate label facts produce one country row and one raw label per parent/period/child.
- [ ] Add a partial-label fixture and assert `data_status`, complete-label count, and missing-price count reconcile with country rows.
- [ ] Add a test that invalid `metric_period` falls back to `30d` before metrics are loaded.
- [ ] Add a test that listing-price, limit-price, and metric failures independently return unavailable statuses without hiding labels.
- [ ] Add a parameterized period-window test for `7d`, `14d`, and `90d`, asserting exact start/end dates and SQL parameters.
- [ ] Add a no-period-end test returning an empty metric result and `sku=None`.
- [ ] Add a cache test proving identical country-profile metric keys execute the fake database query only once.
- [ ] Add a store/MSKU scope test proving all lazy loaders receive the selected row identity unchanged.
- [ ] Run: `.venv\Scripts\python.exe -m pytest -q tests/test_country_label_hub_data.py`.
- [ ] Expected: all country-profile tests pass without opening a database connection outside the fakes.

### Task 2: Country Profile API Error Contracts

**Files:**
- Modify: `tests/test_label_hub_api.py`

**Interfaces:**
- Consumes: `app.main.api_label_hub_msku_country_profile()`.
- Produces: stable HTTP mapping for missing profiles and service failures.

- [ ] Add a fake service that raises `ValueError` and assert the route raises `HTTPException(status_code=404)`.
- [ ] Add a fake service that raises `RuntimeError` and assert the route raises `HTTPException(status_code=503)`.
- [ ] Run: `.venv\Scripts\python.exe -m pytest -q tests/test_label_hub_api.py`.
- [ ] Expected: API parameter forwarding and both error mappings pass.

### Task 3: Replenishment Cost and Follow-Link Regression Coverage

**Files:**
- Modify: `tests/test_replenishment_update_sql.py`
- Modify: `tests/test_replenishment_data.py`

**Interfaces:**
- Consumes: `etl.replenishment_update.REPLENISHMENT_RESULT_SQL` and `ReplenishmentDataService` display expressions.
- Produces: regression guards for purchase-field selection and displayed cost consistency.

- [ ] Assert purchase-field inheritance ranks the followed origin first, then own links, without requiring box size.
- [ ] Assert zero box size is converted to null for inheritance while price and transport remain required.
- [ ] Assert every positive no-box replenishment branch multiplies quantity by effective price plus transport.
- [ ] Assert ASIN non-target/followed rows set both quantity and cost to zero before normal cost branches.
- [ ] Assert historical recovery display cost uses restored quantity multiplied by price plus transport.
- [ ] Assert normal rows preserve stored replenish cost rather than silently recomputing it at read time.
- [ ] Run: `.venv\Scripts\python.exe -m pytest -q tests/test_replenishment_update_sql.py tests/test_replenishment_data.py`.
- [ ] Expected: all replenishment tests pass without executing ETL SQL.

### Task 4: Daily Task Chain Regression Coverage

**Files:**
- Modify: `tests/test_daily_task_script.py`

**Interfaces:**
- Consumes: `scripts/run_daily_update_task.ps1` as text.
- Produces: stable ordering and failure-policy tests for the daily chain.

- [ ] Assert label evidence runs after sales-role snapshots and before replenishment.
- [ ] Assert label evidence has dedicated stdout/stderr logs and notification stage.
- [ ] Assert label evidence failure warns and continues instead of exiting the full daily task.
- [ ] Assert source preflight failure sends failure notification and exits before dashboard ETL execution.
- [ ] Run: `.venv\Scripts\python.exe -m pytest -q tests/test_daily_task_script.py`.
- [ ] Expected: all script-contract tests pass without invoking PowerShell ETLs.

### Task 5: Full Verification

**Files:**
- Verify: all changed test files and existing suite.

**Interfaces:**
- Consumes: the complete pytest collection.
- Produces: final test count and regression status.

- [ ] Run focused tests for all five changed files.
- [ ] Run `.venv\Scripts\python.exe -m pytest --collect-only -q` and record the new total.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q`.
- [ ] Run `git diff --check` and inspect `git status --short`.
- [ ] Expected: focused and full suites pass, test count increases from 419, and unrelated dirty files remain untouched.
