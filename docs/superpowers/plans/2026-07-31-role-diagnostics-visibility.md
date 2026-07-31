# Role Diagnostics Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize the role diagnostics `<details>` open state with whether the active parent category is sales role ID 1.

**Architecture:** Centralize the rule in `syncDiagnosticsVisibility()`. Call it after initial state normalization and every parent-category selection, leaving manual summary toggling and all diagnostic data flows unchanged.

**Tech Stack:** Vanilla JavaScript and pytest frontend contract tests.

## Global Constraints

- Sales role ID 1 opens the section; every other parent category closes it.
- Diagnostic child conditions must not override parent-category visibility.
- Do not change APIs, queries, branches, commits, or the user's foreground browser.

---

### Task 1: Synchronize diagnostics visibility

**Files:**
- Modify: `app/static/js/label_hub.js`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: `state.parent_label_id` and `elements.labelHubDiagnosticsSection`.
- Produces: `syncDiagnosticsVisibility()` which assigns the `<details>.open` state.

- [ ] **Step 1: Add a failing frontend regression test**

Assert that the synchronization function uses only `Number(state.parent_label_id) === 1` and is called during initialization and `selectParent()`.

- [ ] **Step 2: Verify the test fails**

Run `python -m pytest tests/test_label_hub_frontend.py -q -k diagnostics_visibility`.

- [ ] **Step 3: Implement the minimal state synchronization**

Replace `shouldOpenDiagnostics()` with:

```javascript
function syncDiagnosticsVisibility() {
  if (!elements.labelHubDiagnosticsSection) return;
  elements.labelHubDiagnosticsSection.open = Number(state.parent_label_id) === 1;
}
```

Call it after initial state setup and immediately after assigning `state.parent_label_id` in `selectParent()`.

- [ ] **Step 4: Verify focused and full behavior**

Run:

```powershell
python -m pytest tests/test_label_hub_frontend.py -q
node --check app/static/js/label_hub.js
python -m pytest -q
git diff --check
```

Expected: all tests pass and no JavaScript or whitespace errors are reported.
