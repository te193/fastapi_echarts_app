# Country Profile Basic Info and Daily Sales Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make country-profile daily sales use in-stock days and add a compact MSKU basic-information strip above the country table.

**Architecture:** Extend the existing per-country metrics query with `inventory_days` and representative `sku`, then keep the current API shape while adding `identity.sku`. Render a new compact strip from the existing profile payload; no new endpoint or dependency is needed.

**Tech Stack:** FastAPI service layer, MySQL aggregation SQL, vanilla JavaScript, CSS, pytest.

## Global Constraints

- In-stock day means a distinct date where `afn_fulfillable_quantity > 0`.
- Daily sales equals period sales divided by in-stock days; zero in-stock days returns `0`.
- Basic information displays one representative SKU using `max(local_sku)`, matching the replenishment-page convention.
- Only the label-hub country-profile drawer changes.
- Browser verification must run headlessly in the background.

---

### Task 1: Country Profile Metric Semantics

**Files:**
- Modify: `tests/test_country_label_hub_data.py`
- Modify: `app/services/country_label_hub_data.py:730-799`

**Interfaces:**
- Consumes: `dashboard_product_performance_daily` rows for one country category, store, and MSKU.
- Produces: `_cached_country_profile_metrics(...)` result with top-level `sku` and per-country `inventory_days` plus `daily_sales`.

- [ ] **Step 1: Write the failing tests**

Add a cursor-backed service test whose aggregate row contains `sales_qty=12`, `inventory_days=3`, and `sku='SKU-01'`, and assert:

```python
self.assertEqual("SKU-01", result["sku"])
self.assertEqual(3, result["metrics"]["美国"]["inventory_days"])
self.assertEqual(4, result["metrics"]["美国"]["daily_sales"])
```

Add a second aggregate row with `inventory_days=0` and assert:

```python
self.assertEqual(0, result["metrics"]["美国"]["daily_sales"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_country_label_hub_data.py -q`

Expected: FAIL because the query result does not yet expose `sku` or `inventory_days`, and `daily_sales` still divides by the fixed period length.

- [ ] **Step 3: Implement the minimal backend change**

Extend the aggregate SQL with:

```sql
max(local_sku) as sku,
count(distinct case when afn_fulfillable_quantity > 0 then dt_date end) as inventory_days,
```

Build each country metric with:

```python
inventory_days = int(_number(row.get("inventory_days")) or 0)
daily_sales = ((_number(row.get("sales_qty")) or 0.0) / inventory_days) if inventory_days else 0.0
```

Return the representative SKU next to `window` and `metrics`, and pass it into `get_label_hub_country_profile()` as `identity.sku`.

- [ ] **Step 4: Run backend tests**

Run: `python -m pytest tests/test_country_label_hub_data.py -q`

Expected: PASS.

### Task 2: Compact MSKU Basic Information Strip

**Files:**
- Modify: `tests/test_label_hub_frontend.py`
- Modify: `app/static/js/label_hub.js:1536-1577`
- Modify: `app/static/css/styles.css`

**Interfaces:**
- Consumes: `profile.identity.sku`, existing identity fields, `profile.summary.country_count`, and the existing operating sales total.
- Produces: `.label-hub-country-profile-basic` above the “逐国标签、价格与经营表现” section.

- [ ] **Step 1: Write the failing frontend contract test**

Add assertions for:

```python
assert 'class="label-hub-country-profile-basic"' in script
assert "identity.sku || '--'" in script
assert "summary.country_count || 0" in script
assert ".label-hub-country-profile-basic" in styles
```

- [ ] **Step 2: Run the frontend test to verify it fails**

Run: `python -m pytest tests/test_label_hub_frontend.py -q`

Expected: FAIL because the basic-information strip does not exist.

- [ ] **Step 3: Implement the strip**

Render six compact items immediately above the country-detail section:

```text
MSKU | SKU | 店铺 | 国家类别 | 覆盖国家 | 30d销量
```

Use CSS grid with six columns on wide screens and responsive wrapping on narrow screens. Match the existing country-profile blue border, background, spacing, and typography.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_country_label_hub_data.py tests/test_label_hub_frontend.py -q`

Expected: PASS.

### Task 3: Final Verification

**Files:**
- Verify only; no new files.

**Interfaces:**
- Consumes: completed backend and frontend changes.
- Produces: test and headless browser evidence.

- [ ] **Step 1: Run relevant regression tests**

Run: `python -m pytest tests/test_country_label_hub_data.py tests/test_label_hub_api.py tests/test_label_hub_frontend.py -q`

Expected: PASS with zero failures.

- [ ] **Step 2: Check the patch**

Run: `git diff --check`

Expected: exit code `0`.

- [ ] **Step 3: Verify in a background browser**

Start Uvicorn with a hidden PowerShell process, open the label-hub page through headless Playwright, open a country profile, and verify the six basic-information labels and sticky country-table header. Close Playwright and stop the hidden server before reporting completion.
