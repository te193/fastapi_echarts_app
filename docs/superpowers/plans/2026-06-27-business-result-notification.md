# Business Result Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily task report success only when the expected business-date datasets were actually generated, and show concise dashboard, replenishment, and tracking outcomes in DingTalk.

**Architecture:** Validate business outputs inside each ETL before returning exit code zero. Pass all three ETL logs to the notification formatter so its status summary reflects validated output rather than SQL execution alone.

**Tech Stack:** Python, PyMySQL, PowerShell, pytest

---

### Task 1: Validate Daily Product Output

**Files:**
- Modify: `etl/dashboard_daily_update.py`
- Test: `tests/test_dashboard_daily_update_sql.py`

- [ ] Add a failing test proving the product-performance step rejects zero rows for the requested business date.
- [ ] Run the focused test and confirm it fails because the validation is absent.
- [ ] Add a target-table count check before the source-load transaction is committed.
- [ ] Run the focused test and confirm it passes.

### Task 2: Validate Replenishment And Tracking Outputs

**Files:**
- Modify: `etl/replenishment_update.py`
- Modify: `etl/replenishment_tracking_update.py`
- Test: `tests/test_replenishment_update_sql.py`
- Test: `tests/test_replenishment_tracking.py`

- [ ] Add failing tests proving zero result rows raise an error.
- [ ] Add result-count validation before each ETL reports success.
- [ ] Run focused tests and confirm they pass.

### Task 3: Improve DingTalk Business Summary

**Files:**
- Modify: `scripts/run_daily_update_task.ps1`
- Modify: `scripts/notify_daily_task_dingtalk.py`
- Test: `tests/test_daily_task_script.py`
- Test: `tests/test_notify_daily_task_dingtalk.py`

- [ ] Add failing tests for tracking-log arguments and concise three-stage output.
- [ ] Pass tracking stdout/stderr into the notifier.
- [ ] Format the success summary around business dates, validated result counts, durations, and data-health status.
- [ ] Use the correct stage stderr for tracking failures.
- [ ] Run focused notification tests.

### Task 4: Verify

**Files:**
- Verify all files above.

- [ ] Run the complete pytest suite with `.venv\Scripts\python.exe -m pytest -q`.
- [ ] Parse the PowerShell runner with the PowerShell parser.
- [ ] Render a dry-run success and failure notification without sending to DingTalk.
