# Sales Role Default Period Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current-label period default to `30d` only when the active analysis category is sales role.

**Architecture:** Keep the behavior in the label-hub frontend state initialization and parent-switch path. Preserve explicit URL state and leave every non-sales-role category at `all`.

**Tech Stack:** Vanilla JavaScript, pytest structural frontend tests.

## Global Constraints

- Do not change backend aggregation.
- Do not change defaults for categories other than parent label `1`.
- Do not commit or push.

---

### Task 1: Sales-role-only default period

**Files:**
- Modify: `app/static/js/label_hub.js`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: `state.parent_label_id`, URL query parameter `label_period`
- Produces: `defaultLabelPeriod(parentId)` returning `30d` for parent `1`, otherwise `all`

- [ ] **Step 1: Write the failing test**

Assert that the frontend defines a sales-role-only default helper, uses it for initial state when the URL has no explicit period, and uses it when switching categories.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_label_hub_frontend.py::test_sales_role_defaults_to_30d_label_period`

Expected: FAIL because the helper and sales-role default do not exist.

- [ ] **Step 3: Write minimal implementation**

Add `defaultLabelPeriod(parentId)` and use it in state initialization and `selectParent`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_label_hub_frontend.py::test_sales_role_defaults_to_30d_label_period`

Expected: PASS.

- [ ] **Step 5: Run regression verification**

Run: `python -m pytest -q tests/test_label_hub_frontend.py`

Expected: all tests pass.
