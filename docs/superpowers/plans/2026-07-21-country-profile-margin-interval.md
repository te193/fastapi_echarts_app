# Country Profile Margin Interval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pricing-zone label below each country with the gross-margin interval implied by that country's current listing price and limit-price ladder.

**Architecture:** Add one pure backend classifier that consumes `price.value` and `limit_prices.margin_prices`, then expose its result as `price_margin_interval` on each country row. The frontend country cell renders only this prepared value, keeping display logic separate from pricing math.

**Tech Stack:** Python 3, FastAPI service layer, vanilla JavaScript, pytest, Playwright CLI.

## Global Constraints

- Standard tiers are 0%, 5%, 10%, 15%, 20%, 25%, 30%, and 35%.
- A price equal to a tier belongs to the interval beginning at that tier.
- Values at or above the 35% threshold display `≥35%`; values below the 0% threshold display `<0%`.
- Missing price or ladder data displays `--` and never falls back to the remote pricing-zone label.
- Preserve existing country-cell alignment, row height, and the separate margin-price ladder column.

---

### Task 1: Backend margin interval classifier

**Files:**
- Modify: `app/services/country_label_hub_data.py`
- Test: `tests/test_country_label_hub_data.py`

**Interfaces:**
- Consumes: `price: dict[str, Any] | None`, `limit_prices: dict[str, Any] | None`.
- Produces: `_price_margin_interval(price, limit_prices) -> str` and country payload field `price_margin_interval`.

- [ ] **Step 1: Write the failing tests**

Add parameterized assertions for prices inside `30%–35%`, exactly on 30%, at/above 35%, below 0%, and missing inputs. Extend the profile payload test to assert the new field.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_country_label_hub_data.py -q`

Expected: FAIL because `_price_margin_interval` or `price_margin_interval` does not exist.

- [ ] **Step 3: Write minimal implementation**

Normalize populated ladder entries by numeric margin and value, sort ascending by margin, then classify with inclusive lower bounds. Return `--` for incomplete inputs.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_country_label_hub_data.py -q`

Expected: PASS.

### Task 2: Country-cell presentation

**Files:**
- Modify: `app/static/js/label_hub.js`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: country row property `price_margin_interval: string`.
- Produces: country identity cell whose `<small>` text is the interval or `--`.

- [ ] **Step 1: Write the failing frontend contract test**

Assert `countryProfileCountryCell` reads `item.price_margin_interval` and no longer reads `(item.pricing || {}).label`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_label_hub_frontend.py -q`

Expected: FAIL because the country cell still renders the pricing label.

- [ ] **Step 3: Write minimal implementation**

Replace the pricing-label local variable with `item.price_margin_interval || "--"`; retain the existing markup and CSS classes.

- [ ] **Step 4: Run focused and regression tests**

Run: `python -m pytest tests/test_country_label_hub_data.py tests/test_label_hub_frontend.py tests/test_label_hub_api.py -q`

Expected: PASS.

### Task 3: Runtime verification

**Files:**
- No production files created.

**Interfaces:**
- Consumes: restarted local service on port 8001.
- Produces: verified API payload and headless-browser drawer rendering.

- [ ] **Step 1: Restart the existing Uvicorn process**

Restart `app.main:app` with host `0.0.0.0` and port `8001` in a hidden background process.

- [ ] **Step 2: Verify the API**

Request `/api/label-hub/msku-country-profile` for a populated MSKU and confirm every returned country has `price_margin_interval`, with values matching its price ladder.

- [ ] **Step 3: Verify the rendered drawer headlessly**

Use Playwright CLI to filter the label hub, open the country profile, and confirm country names show interval text while the old `健康利润区/基础利润区` copy is absent from that cell. Confirm no new browser console errors.
