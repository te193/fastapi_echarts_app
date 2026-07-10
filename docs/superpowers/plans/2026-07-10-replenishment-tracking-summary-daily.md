# Replenishment Tracking Summary Daily ETL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the replenishment tracking summary ETL to the daily task and prove the full chain can execute without database writes.

**Architecture:** The summary remains an independent ETL command invoked by the PowerShell orchestrator. A command-level `--dry-run` exits before database setup, while the orchestrator reuses the existing tracking notification channel and suppresses notifications during dry runs.

**Tech Stack:** Python 3.11, argparse, pytest, PowerShell, FastAPI project ETL utilities.

## Global Constraints

- Do not invoke `etl.replenishment_tracking_update`.
- Daily order is preflight, dashboard, replenishment, tracking summary, return goods.
- Dry-run performs zero target database writes and sends no DingTalk message.
- Preserve existing unrelated replenishment worktree changes.

---

### Task 1: Summary ETL Dry-Run

**Files:**
- Modify: `etl/replenishment_tracking_summary_update.py`
- Test: `tests/test_replenishment_tracking_summary.py`

**Interfaces:**
- Consumes: CLI `--cutoff-date` and `--dry-run`.
- Produces: `[success] replenishment_tracking_summary dry_run=true writes=0` without calling database setup.

- [ ] Add a failing test that patches `apply_database_ini_env`, `connect_target`, and `connect_source` to fail if called.
- [ ] Run the focused test and confirm it fails because `--dry-run` is not accepted.
- [ ] Add `--dry-run`; print the cutoff strategy, source sync groups, target tables, and success marker before any database setup.
- [ ] Run the focused test and confirm it passes.

### Task 2: Daily Orchestration

**Files:**
- Modify: `scripts/run_daily_update_task.ps1`
- Test: `tests/test_daily_task_script.py`

**Interfaces:**
- Consumes: raw `--dry-run` in PowerShell `$args`.
- Produces: separate tracking-summary logs and failure stage `replenishment_tracking`; skips notification transmission in dry-run mode.

- [ ] Update script tests to require the summary command between replenishment and return goods, while rejecting the old tracking command.
- [ ] Add assertions for summary stdout/stderr logs, notification arguments, and dry-run notification suppression.
- [ ] Run the focused tests and confirm they fail against the skipped implementation.
- [ ] Implement the summary stage, error handling, logs, notification wiring, and dry-run notification guard.
- [ ] Run the focused tests and confirm they pass.

### Task 3: DingTalk Summary Result

**Files:**
- Modify: `scripts/notify_daily_task_dingtalk.py`
- Test: `tests/test_notify_daily_task_dingtalk.py`

**Interfaces:**
- Consumes: `[success] replenishment_tracking_summary cutoff_date=YYYY-MM-DD summary_rows=N level_history_rows=N ...`.
- Produces: a concise replenishment tracking summary result while retaining old tracking-window log compatibility.

- [ ] Add a failing notification test using the new summary log format.
- [ ] Run the focused test and confirm the current parser cannot report the summary rows.
- [ ] Parse summary cutoff date, summary rows, and level-history rows; prefer them when present and otherwise retain the old window output.
- [ ] Run all notification tests.

### Task 4: Read-Only End-to-End Verification

**Files:**
- Verify only; no data files or database tables are modified.

**Interfaces:**
- Consumes: `scripts/run_daily_update_task.ps1 --dry-run`.
- Produces: exit code 0, per-stage dry-run logs, `writes=0`, and no DingTalk transmission.

- [ ] Run the complete pytest suite.
- [ ] Run the summary module directly with `--dry-run` and verify its success marker.
- [ ] Run the complete daily PowerShell task with `--dry-run`.
- [ ] Inspect all generated logs for failures and verify no write-mode command executed.
- [ ] Commit only the daily-summary files and documentation; leave unrelated replenishment changes unstaged.
