# Replenishment Sales Role Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sales-role selector to the replenishment page that reuses the existing dynamic `category` filter and remains selected when the classification period changes.

**Architecture:** Keep the backend and database unchanged. Add a fixed selector to the replenishment template, bind it to the existing `state.category` value in `replenishment.js`, and rely on the existing request, level-flow, export, and SQL filter paths that already consume `category` together with `category_period_days`.

**Tech Stack:** FastAPI, Jinja2, vanilla JavaScript, pytest.

---

### Task 1: Lock the sales-role selector contract with failing tests

**Files:**
- Modify: `tests/test_replenishment_frontend.py`
- Test: `tests/test_replenishment_frontend.py`

- [ ] **Step 1: Write the failing template test**

Add a test that reads `app/templates/replenishment.html` and verifies the new selector and its fixed options:

```python
def test_replenishment_has_sales_role_filter_with_existing_role_values():
    template = (ROOT / "app" / "templates" / "replenishment.html").read_text(encoding="utf-8")

    assert '<select id="salesRoleSelect">' in template
    assert '<option value="all">全部销售角色</option>' in template
    assert '<option value="明星产品">明星产品</option>' in template
    assert '<option value="潜力产品">潜力产品</option>' in template
    assert '<option value="瘦狗产品">瘦狗产品</option>' in template
    assert '<option value="问题产品">问题产品</option>' in template
```

- [ ] **Step 2: Write the failing JavaScript linkage test**

Add a test that verifies the selector reuses `category`, is synchronized, and is not cleared by a period change:

```python
def test_replenishment_sales_role_filter_reuses_category_state_and_period_linkage():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")

    assert '"salesRoleSelect"' in script
    assert '["salesRoleSelect", "category"]' in script
    assert 'elements.salesRoleSelect.value = state.category || "all";' in script
    assert 'state.category = "all";' in script
    assert 'if (pair[1] === "category_period_days") state.category = "all";' not in script
    assert 'category: state.category' in script
    assert '"snapshot_date", "level", "category", "category_period_days"' in script
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
pytest tests/test_replenishment_frontend.py -q
```

Expected: the two new tests fail because `salesRoleSelect` does not exist and is not bound in `replenishment.js`.

### Task 2: Add and bind the sales-role selector

**Files:**
- Modify: `app/templates/replenishment.html`
- Modify: `app/static/js/replenishment.js`
- Test: `tests/test_replenishment_frontend.py`

- [ ] **Step 1: Add the selector to the filter grid**

After the order-number filter in `app/templates/replenishment.html`, add:

```html
<label class="filter-control">
  <span>销售角色</span>
  <select id="salesRoleSelect">
    <option value="all">全部销售角色</option>
    <option value="明星产品">明星产品</option>
    <option value="潜力产品">潜力产品</option>
    <option value="瘦狗产品">瘦狗产品</option>
    <option value="问题产品">问题产品</option>
  </select>
</label>
```

- [ ] **Step 2: Cache and bind the selector to `state.category`**

Update the element ID list in `init()`:

```javascript
"datePickerBtn", "datePickerValue", "datePickerPanel", "levelSelect", "categoryPeriodSelect", "siteSelect", "storeSelect", "keywordInput", "orderKeywordInput", "salesRoleSelect", "clearFiltersBtn",
```

Add the selector to the existing change bindings:

```javascript
["salesRoleSelect", "category"],
```

Keep the existing category-period handler unchanged so switching periods preserves `state.category`.

- [ ] **Step 3: Synchronize all existing role-selection paths**

In `syncControls()`, add:

```javascript
elements.salesRoleSelect.value = state.category || "all";
```

This makes URL restoration, role-tag clicks, table category filters, and one-click clear all update the selector through the existing `state.category` path.

- [ ] **Step 4: Update the script cache-busting version**

Change the replenishment script reference in `app/templates/replenishment.html` to:

```html
<script src="{{ url_for('static', path='js/replenishment.js') }}?v=20260727salesrole1"></script>
```

Update the existing cache-busting assertion in `tests/test_replenishment_frontend.py` to expect `20260727salesrole1`.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
pytest tests/test_replenishment_frontend.py -q
```

Expected: all tests in the file pass.

### Task 3: Verify the existing backend linkage and regressions

**Files:**
- Verify: `app/main.py`
- Verify: `app/services/replenishment_data.py`
- Test: `tests/test_replenishment_data.py`
- Test: `tests/test_replenishment_frontend.py`

- [ ] **Step 1: Run the replenishment service tests**

Run:

```powershell
pytest tests/test_replenishment_data.py -q
```

Expected: all tests pass, including period normalization and dynamic role-expression coverage for 7, 14, 30, 90, and 180 days.

- [ ] **Step 2: Run the combined focused suite**

Run:

```powershell
pytest tests/test_replenishment_frontend.py tests/test_replenishment_data.py -q
```

Expected: all tests pass with no failures.

- [ ] **Step 3: Run the complete test suite**

Run:

```powershell
pytest -q
```

Expected: the full suite passes.

- [ ] **Step 4: Review the final diff**

Run:

```powershell
git diff --check
git diff -- app/templates/replenishment.html app/static/js/replenishment.js tests/test_replenishment_frontend.py
```

Expected: no whitespace errors; the production change is limited to the selector, state binding, and cache-busting update.

