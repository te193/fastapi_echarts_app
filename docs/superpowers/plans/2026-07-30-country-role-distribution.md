# Country Role Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hidden same-role country filter with a two-level country-site role distribution and expandable diagnostic reasons.

**Architecture:** Extend the pure diagnostics aggregator with an exact `country_role_distribution` derived from retained parent-16 facts. Render that distribution as a full-width hierarchy in the existing diagnostics module while preserving child-label filtering.

**Tech Stack:** Python, FastAPI service payloads, vanilla JavaScript, CSS, pytest.

## Global Constraints

- Preserve all existing public filters and URL behavior.
- Keep full-site diagnostics behavior unchanged except for removing the duplicate attention rail.
- Do not commit or push.

---

### Task 1: Country role aggregation

**Files:**
- Modify: `app/services/label_hub_diagnostics.py`
- Test: `tests/test_label_hub_diagnostics.py`

**Interfaces:**
- Consumes: retained parent-16 facts and filtered business rows.
- Produces: `country_role_distribution`, with `role_id`, `label`, `country_record_count`, `business_unit_count`, `ratio`, `delta`, business metrics, evidence coverage, and child buckets.

- [ ] Write a failing test with one product across multiple countries and multiple site roles.
- [ ] Run the focused test and confirm it fails because `country_role_distribution` is absent.
- [ ] Implement exact role grouping and country-record deltas.
- [ ] Run the focused diagnostics tests and confirm they pass.

### Task 2: Expandable hierarchy UI

**Files:**
- Modify: `app/static/js/label_hub.js`
- Modify: `app/static/css/styles.css`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: `payload.country_role_distribution`.
- Produces: full-width rows with `data-diagnostic-country-role` and nested child rows with `data-diagnostic-country-detail`.

- [ ] Write a failing frontend contract test for hierarchy hooks and removal of the attention rail.
- [ ] Run the focused test and confirm the hierarchy is missing.
- [ ] Render role rows and hidden child rows; toggle children locally without a new request.
- [ ] Update responsive styles and remove attention-rail layout.
- [ ] Run frontend tests and JavaScript syntax validation.

### Task 3: Runtime verification

**Files:**
- No production files.

- [ ] Run the full pytest suite, JavaScript syntax check, and diff check.
- [ ] Restart the existing port 8001 service.
- [ ] Verify live API totals and visually inspect desktop and narrow states.
