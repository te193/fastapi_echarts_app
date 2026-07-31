# Role Diagnostic Table Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the diagnostic summary link-like cell with a compact “查看诊断” button while preserving the existing drawer behavior and tooltip.

**Architecture:** Keep the existing `roleDiagnosticColumn()` and grid-level click handler. Change only the cell renderer markup and the dedicated CSS class so the current event routing continues to open `openRoleDiagnosticDrawer(event.data)`.

**Tech Stack:** Vanilla JavaScript, AG Grid wrapper, CSS, pytest source-contract tests.

## Global Constraints

- Keep the column header “角色诊断” and use “查看诊断” for the row action.
- Preserve `tooltipField: "role_diagnostic_summary"` and the existing drawer click behavior.
- Do not change APIs, data structures, business logic, dependencies, branches, or commits.

---

### Task 1: Render and style the action button

**Files:**
- Modify: `app/static/js/label_hub.js`
- Modify: `app/static/css/styles.css`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: `roleDiagnosticColumn()` values from `role_diagnostic_summary`.
- Produces: `.label-hub-role-diagnostic-cell` button text “查看诊断”; existing grid click handler remains the interaction boundary.

- [ ] **Step 1: Write the failing test**

Add a frontend source-contract assertion that the renderer emits the literal action text and keeps the diagnostic tooltip field.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests/test_label_hub_frontend.py -q
```

Expected: failure because the renderer still emits the role summary as button text.

- [ ] **Step 3: Implement the minimal renderer and CSS change**

Render:

```javascript
'<button type="button" class="label-hub-role-diagnostic-cell"><span>查看诊断</span><i aria-hidden="true">›</i></button>'
```

Style it as a compact light-blue outlined control with hover and `:focus-visible` states. Keep “暂无诊断” unchanged.

- [ ] **Step 4: Verify focused behavior**

Run:

```powershell
python -m pytest tests/test_label_hub_frontend.py -q
node --check app/static/js/label_hub.js
```

Expected: all commands pass.

- [ ] **Step 5: Verify the full application**

Run:

```powershell
python -m pytest -q
git diff --check
```

Expected: all tests pass and no whitespace errors are reported.

- [ ] **Step 6: Visually verify**

Open the label dashboard, confirm each populated “角色诊断” cell displays “查看诊断”, verify hover/focus styling, and confirm clicking it opens the unchanged diagnostic drawer.
