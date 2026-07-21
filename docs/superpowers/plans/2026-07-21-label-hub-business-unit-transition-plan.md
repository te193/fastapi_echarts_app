# Label Hub Business Unit Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make label summaries and two-snapshot transitions count `(country_category, store, msku)` business units without collapsing opposite country/store changes into one MSKU-level primary label.

**Architecture:** Introduce one shared business-unit key helper and use it in the label-hub aggregation and change-comparison services. Keep remote label snapshots as the source of truth, expose country/store/MSKU on every change row, and update the existing drawer copy and columns to describe business-unit counts.

**Tech Stack:** Python 3, FastAPI service layer, pytest, vanilla JavaScript, Playwright headless browser verification.

## Global Constraints

- Remote labels continue to come from `dws_datasync.dws_标签表`; do not locally recalculate lifecycle labels.
- The business-unit key is exactly `(country_category, store, msku)`.
- Unique MSKU counts are auxiliary only and must not drive transition totals.
- Browser verification must run headlessly so it does not interrupt the user's desktop.

---

### Task 1: Lock the business-unit aggregation contract with tests

**Files:**
- Modify: `tests/test_label_hub_data.py`
- Modify: `tests/test_label_hub_changes.py`

**Interfaces:**
- Consumes: `LabelHubDataService.build_payload(...)`, `LabelHubChangeDataService.get_changes(...)`.
- Produces: regression tests proving two country/store rows sharing one MSKU remain two independent units.

- [ ] **Step 1: Add a label-hub aggregation regression test**

Create two baseline rows with the same MSKU in different countries and different lifecycle children. Assert the remote breakdown denominator is `2`, each child bucket count is `1`, and the payload still reports one auxiliary unique MSKU.

- [ ] **Step 2: Add an opposite-transition regression test**

Model `QL0052b` as Europe `203 -> 204` and UK `204 -> 203`. Assert there are two changed rows, the transition matrix contains both directions, each output row includes country/store/MSKU, and `business_unit_count == 1`.

- [ ] **Step 3: Run the focused tests and confirm the old MSKU grouping fails**

Run: `python -m pytest tests/test_label_hub_data.py tests/test_label_hub_changes.py -q`

Expected: the new assertions fail because the current services merge rows by MSKU.

### Task 2: Convert label-hub summaries and breakdowns to business-unit keys

**Files:**
- Modify: `app/services/label_hub_data.py`
- Test: `tests/test_label_hub_data.py`

**Interfaces:**
- Produces: `_business_unit_key(row) -> tuple[str, str, str]` and business-unit keyed remote/local bucket maps.
- Preserves: `population_summary.unique_msku_count` as an auxiliary metric and one public table row per business unit.

- [ ] **Step 1: Add the shared key helper**

Implement `_business_unit_key(row)` from the normalized country category, store, and MSKU strings.

- [ ] **Step 2: Replace MSKU-priority maps in breakdowns**

Change remote child selection and local metric selection to key their results by `_business_unit_key(row)`. Calculate bucket denominators and matched counts from business-unit rows, while retaining separate unique-MSKU fields.

- [ ] **Step 3: Convert issue filtering and matrix matching**

Use business-unit key sets for conflict, missing metric, zero sales, negative profit, problem-role filters, and label matrix cells so one country's state cannot select or mask another country's row.

- [ ] **Step 4: Run the label-hub data tests**

Run: `python -m pytest tests/test_label_hub_data.py -q`

Expected: all tests pass and the new cross-country regression reports two business units.

### Task 3: Convert snapshot changes and layer flows to business-unit keys

**Files:**
- Modify: `app/services/label_hub_change_data.py`
- Test: `tests/test_label_hub_changes.py`

**Interfaces:**
- Consumes: `_business_unit_key(row)` from `label_hub_data.py`.
- Produces: change rows with `business_unit_key`, `country_category`, `store`, `msku`, and unit-level previous/current labels.

- [ ] **Step 1: Group comparison rows by business unit**

Replace `_rows_by_msku` in the change path with a business-unit grouping helper. Convert selected sets, canonical layer bucket sets, primary-label maps, label signatures, added/removed/changed detection, and transition matrices to use the tuple key.

- [ ] **Step 2: Scope evidence and metric profiles to one unit**

Resolve rule evidence using the row's exact country/store/MSKU key. Build metric and condition snapshots from only that business unit instead of all rows sharing the MSKU.

- [ ] **Step 3: Expose unit identity and auxiliary MSKU counts**

Return the three identity fields and a stable `business_unit_key` string on every row. Keep `summary.current`, `previous`, `added`, `removed`, and `changed` as business-unit counts, and add auxiliary unique-MSKU counts without changing the reconciliation equation.

- [ ] **Step 4: Run change-service tests**

Run: `python -m pytest tests/test_label_hub_changes.py -q`

Expected: all tests pass; the opposite country transitions are both present.

### Task 4: Update drawer wording, columns, and regression checks

**Files:**
- Modify: `app/static/js/label_hub.js`
- Modify: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: unit identity fields from `/api/label-hub/changes`.
- Produces: user-visible business-unit wording and country/store/MSKU detail columns.

- [ ] **Step 1: Add failing frontend contract assertions**

Assert that the layer summary says `经营单元`, the change list contains `国家类别` and `店铺` columns, and stale phrases such as `共 N 个 MSKU` are removed from transition totals.

- [ ] **Step 2: Update renderers**

Change transition cards, pagination, headings, empty states, Sankey tooltips, and drawer tables to say `经营单元`. Render country category, store, and MSKU as separate columns and keep the MSKU trace action.

- [ ] **Step 3: Run frontend contract tests**

Run: `python -m pytest tests/test_label_hub_frontend.py -q`

Expected: all frontend source-contract tests pass.

### Task 5: Verify live data and the headless browser flow

**Files:**
- No production file changes expected.

**Interfaces:**
- Verifies: API reconciliation, live lifecycle transition counts, and visible drawer identity columns.

- [ ] **Step 1: Run the complete focused suite**

Run: `python -m pytest tests/test_label_hub_data.py tests/test_label_hub_changes.py tests/test_label_hub_frontend.py tests/test_label_hub_api.py -q`

Expected: all tests pass.

- [ ] **Step 2: Verify the live API**

Request the growth-layer change payload and assert lifecycle flows report `14` mature-to-growth units and `28` growth-to-mature units for the current two snapshots. Confirm `QL0052b` appears in both country-specific directions.

- [ ] **Step 3: Run Playwright headlessly**

Open the label-hub page in a headless browser, open the lifecycle growth change drawer, and confirm the drawer shows business-unit wording plus country category, store, and MSKU columns. Capture console errors and fail verification if any uncaught error appears.

- [ ] **Step 4: Review and commit**

Run `git diff --check`, review only the files in this plan, then commit with a concise Chinese summary.
