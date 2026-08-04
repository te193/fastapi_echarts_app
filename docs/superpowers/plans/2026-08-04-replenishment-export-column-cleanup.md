# Replenishment Export Column Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the 12 approved redundant columns from the replenishment detail Excel export while retaining the two approved stockout-risk columns.

**Architecture:** Reuse the existing export-column discovery and filtering path. Add the approved database field names to `REPLENISHMENT_EXPORT_EXCLUDED_COLUMNS`; do not change the database query formulas, workbook writer, page table, or ETL.

**Tech Stack:** Python 3, FastAPI service layer, unittest/pytest, existing XLSX export pipeline.

## Global Constraints

- Only the “导出当前明细” Excel column set changes.
- Do not modify database schema, ETL formulas, replenishment levels, quantities, or the page grid.
- Remove exactly the 12 fields listed in the approved design.
- Keep `lead_time_stockout_flag` and `lead_time_stockout_days` in the export.
- Verify against the test service on port 8002; do not write to the production database.

---

### Task 1: Filter the approved export columns

**Files:**
- Modify: `tests/test_replenishment_data.py`
- Modify: `app/services/replenishment_data.py:215-232`

**Interfaces:**
- Consumes: `ReplenishmentDataService._export_columns(conn) -> list[dict[str, str]]`
- Produces: the same return type, with the 12 approved field names filtered and the two stockout-risk fields retained.

- [ ] **Step 1: Write the failing test**

Add a focused test that supplies all 14 relevant columns to `_export_columns` and checks the exact exclusion/retention contract:

```python
def test_export_columns_removes_redundant_calculation_fields_but_keeps_stockout_risk(self):
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    service.database = "etl_datasync_test"
    removed = [
        "calculated_replenish_qty",
        "calculated_replenish_box_qty",
        "calculated_replenish_cost",
        "executable_replenish_qty",
        "executable_replenish_box_qty",
        "executable_replenish_cost",
        "replenish_dur_calc_stocko_qty",
        "replenish_need_qty",
        "replenish_trigger_qty",
        "base_replenish_need_qty",
        "lead_adjusted_replenish_need_qty",
        "lead_time_lost_sales_qty",
    ]
    retained = ["lead_time_stockout_flag", "lead_time_stockout_days"]
    conn = FakeConnection([
        {"column_name": name, "column_comment": ""}
        for name in removed + retained
    ])

    names = [column["name"] for column in service._export_columns(conn)]

    for name in removed:
        self.assertNotIn(name, names)
    self.assertEqual(retained, names)
```

- [ ] **Step 2: Run the targeted test to verify RED**

Run:

```powershell
& 'E:\Code\Python_code\日常测试使用\fastapi_echarts_app\.venv\Scripts\python.exe' -m pytest tests/test_replenishment_data.py::ReplenishmentDataServiceTests::test_export_columns_removes_redundant_calculation_fields_but_keeps_stockout_risk -q
```

Expected: FAIL because the 12 fields are still returned by `_export_columns`.

- [ ] **Step 3: Implement the minimal filter change**

Add these field names to `REPLENISHMENT_EXPORT_EXCLUDED_COLUMNS`:

```python
"calculated_replenish_qty",
"calculated_replenish_box_qty",
"calculated_replenish_cost",
"executable_replenish_qty",
"executable_replenish_box_qty",
"executable_replenish_cost",
"replenish_dur_calc_stocko_qty",
"replenish_need_qty",
"replenish_trigger_qty",
"base_replenish_need_qty",
"lead_adjusted_replenish_need_qty",
"lead_time_lost_sales_qty",
```

Do not add `lead_time_stockout_flag` or `lead_time_stockout_days`.

- [ ] **Step 4: Run targeted and full automated tests**

Run:

```powershell
& 'E:\Code\Python_code\日常测试使用\fastapi_echarts_app\.venv\Scripts\python.exe' -m pytest tests/test_replenishment_data.py -q
& 'E:\Code\Python_code\日常测试使用\fastapi_echarts_app\.venv\Scripts\python.exe' -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 5: Verify an actual workbook from port 8002**

Restart the 8002 test service if needed so it loads the new code, download `/api/replenishment/export` for the current test snapshot, and inspect the first worksheet header row using the bundled spreadsheet runtime. Confirm all 12 removed labels are absent and both retained labels are present.

- [ ] **Step 6: Commit**

```powershell
git add app/services/replenishment_data.py tests/test_replenishment_data.py
git commit -m "精简补货明细导出冗余字段"
```
