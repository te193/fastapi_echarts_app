# Country Profile Compact Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the label-hub country-profile drawer fully visible and easier to scan.

**Architecture:** Keep the existing country-profile data API and drawer structure. Adjust only its rendering copy and CSS layout, with static frontend assertions protecting the requested presentation contract.

**Tech Stack:** FastAPI templates, vanilla JavaScript, CSS, pytest.

## Global Constraints

- Do not change country-profile API payloads or backend aggregation.
- Preserve the existing drawer and table semantics.
- Let the page, rather than an inner table container, handle vertical scrolling.

---

### Task 1: Lock the compact display contract with frontend tests

**Files:**
- Modify: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: the country-profile rendering functions and CSS selectors.
- Produces: regression assertions for centered country display, rank-only content, separate TACOS, and natural table height.

- [ ] **Step 1: Write the failing test**

```python
def test_label_hub_country_profile_uses_compact_full_height_table():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "<small>取经营窗口最后一天</small>" not in script
    assert "countryProfileMetricRow('TACOS', tacos)" in script
    assert ".label-hub-country-name { display: grid; justify-items: center;" in styles
    assert ".label-hub-country-profile-table-wrap { overflow: visible;" in styles
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_label_hub_frontend.py::test_label_hub_country_profile_uses_compact_full_height_table -q`

Expected: FAIL because the current rank explanatory text, combined TACOS row, left-aligned country name, and inner scrolling CSS are still present.

- [ ] **Step 3: Implement the minimal rendering and CSS changes**

```javascript
return '<div class="label-hub-country-metrics is-rank">' +
  countryProfileMetricRow('小类排名', ranking) + '</div>';

countryProfileMetricRow('广告销售', countryProfileMoney(metrics.ad_sales)) +
countryProfileMetricRow('TACOS', tacos) +
countryProfileMetricRow('退货', countryProfileValue(metrics.return_count, "0"))
```

```css
.label-hub-country-profile-table-wrap { overflow: visible; }
.label-hub-country-name { justify-items: center; text-align: center; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_label_hub_frontend.py::test_label_hub_country_profile_uses_compact_full_height_table -q`

Expected: PASS.

### Task 2: Verify the complete label-hub frontend contract

**Files:**
- Modify: `app/static/js/label_hub.js`
- Modify: `app/static/css/styles.css`
- Modify: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: Task 1 regression assertions.
- Produces: an unchanged country-profile API contract with the compact presentation.

- [ ] **Step 1: Run the label-hub frontend tests**

Run: `python -m pytest tests/test_label_hub_frontend.py -q`

Expected: PASS with all label-hub static frontend assertions satisfied.

- [ ] **Step 2: Inspect the diff for scope**

Run: `git diff --check; git diff -- app/static/js/label_hub.js app/static/css/styles.css tests/test_label_hub_frontend.py`

Expected: no whitespace errors and changes limited to country-profile presentation plus its regression test.
