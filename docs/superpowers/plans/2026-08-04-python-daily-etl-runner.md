# Python Daily ETL Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent Python command that runs the complete daily ETL chain with progress output, per-step logs, failure handling, dry-run behavior, and DingTalk notifications.

**Architecture:** Create `etl.daily_update_runner` as a process orchestrator. It starts every existing ETL module with the current Python interpreter, streams stdout/stderr to both the console and dedicated log files, and invokes the existing DingTalk notification script with the same log contract as the PowerShell runner.

**Tech Stack:** Python 3.11+, standard library (`argparse`, `dataclasses`, `pathlib`, `subprocess`, `threading`, `time`), pytest.

---

### Task 1: Define the runner contract with tests

**Files:**
- Create: `tests/test_daily_update_runner.py`
- Create: `etl/daily_update_runner.py`

- [ ] **Step 1: Write failing tests for step definitions and argument handling**

```python
from etl import daily_update_runner as runner


def test_default_steps_match_daily_chain():
    assert [step.module for step in runner.DEFAULT_STEPS] == [
        "etl.dashboard_source_preflight",
        "etl.dashboard_daily_update",
        "etl.product_performance_history_sync",
        "etl.sales_role_snapshot_update",
        "etl.label_rule_evidence_snapshot_update",
        "etl.replenishment_update",
        "etl.replenishment_tracking_summary_update",
        "etl.return_goods_update",
    ]


def test_parse_args_keeps_unknown_args_for_etl_modules():
    options = runner.parse_args(["--dry-run", "--biz-date", "2026-08-03"])
    assert options.dry_run is True
    assert options.etl_args == ("--dry-run", "--biz-date", "2026-08-03")
```

- [ ] **Step 2: Run tests and verify they fail because the module is missing**

Run:

```powershell
python -m pytest tests/test_daily_update_runner.py -q
```

Expected: collection failure because `etl.daily_update_runner` does not exist.

- [ ] **Step 3: Add minimal step metadata and argument parsing**

Define:

```python
@dataclass(frozen=True)
class EtlStep:
    key: str
    label: str
    module: str
    log_prefix: str
    stage: str
    continue_on_failure: bool = False
```

Create `DEFAULT_STEPS` in the approved order. Parse `--dry-run` while preserving all command-line arguments in `etl_args`.

- [ ] **Step 4: Run the focused tests**

Run:

```powershell
python -m pytest tests/test_daily_update_runner.py -q
```

Expected: the initial contract tests pass.

### Task 2: Implement process execution and stop/continue rules

**Files:**
- Modify: `tests/test_daily_update_runner.py`
- Modify: `etl/daily_update_runner.py`

- [ ] **Step 1: Add failing tests for successful execution, blocking failure, and warning failure**

Use an injected `step_executor` that records the command and returns controlled exit codes. Verify:

- commands use `sys.executable -m <module>`
- all required steps run after successful predecessors
- a required step failure stops the chain and returns its exit code
- label evidence failure records a warning and continues
- ETL arguments are appended to every step command

- [ ] **Step 2: Run the focused tests and verify the expected failures**

Run:

```powershell
python -m pytest tests/test_daily_update_runner.py -q
```

Expected: failures identify missing orchestration behavior.

- [ ] **Step 3: Implement the orchestration loop**

Add `run_daily_update(...)` with injectable clock, output writer, step executor, and notifier. Return a `RunResult` containing the process exit code, executed step results, run stamp, and log paths.

Required failures stop immediately. `label_evidence` uses `continue_on_failure=True`.

- [ ] **Step 4: Implement real subprocess streaming**

Use `subprocess.Popen` and two reader threads to copy child stdout/stderr to UTF-8 log files and the parent console without buffering the complete ETL output in memory.

- [ ] **Step 5: Run the focused tests**

Run:

```powershell
python -m pytest tests/test_daily_update_runner.py -q
```

Expected: orchestration tests pass.

### Task 3: Add DingTalk notification integration and operator output

**Files:**
- Modify: `tests/test_daily_update_runner.py`
- Modify: `etl/daily_update_runner.py`

- [ ] **Step 1: Add failing tests for notification behavior**

Verify:

- required failure sends `status=failed` with the failed step stage
- successful required chain sends `status=success`, `stage=all`
- label evidence warning sends a failure notification and the final success notification
- dry-run sends no notification
- notification failure does not replace the ETL exit code
- every notification command contains all log path options expected by `notify_daily_task_dingtalk.py`

- [ ] **Step 2: Add failing tests for progress and final summary output**

Verify the output contains `[1/8]`, step labels, success/warning/failure states, elapsed time, total elapsed time, and failed log location.

- [ ] **Step 3: Run tests and verify they fail for missing behavior**

Run:

```powershell
python -m pytest tests/test_daily_update_runner.py -q
```

- [ ] **Step 4: Implement notifications and progress reporting**

Invoke:

```powershell
<python> scripts/notify_daily_task_dingtalk.py --status ... --stage ...
```

Pass run stamp, project root, all stdout/stderr log paths, exit code, and optional error message. Skip this call in dry-run mode and catch notification errors as warnings.

- [ ] **Step 5: Add `main()`**

Resolve the project root from `__file__`, create `logs`, run the chain, and return the chain exit code:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python -m pytest tests/test_daily_update_runner.py -q
```

Expected: all runner tests pass without database writes or network calls.

### Task 4: Verify compatibility and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/windows_deploy.md`

- [ ] **Step 1: Document the backup Python command**

Add:

```powershell
python -m etl.daily_update_runner
```

and:

```powershell
python -m etl.daily_update_runner --dry-run
```

Explain that the PowerShell and Python runners are independent entry points for the same daily chain.

- [ ] **Step 2: Run syntax and focused verification**

Run:

```powershell
python -m py_compile etl/daily_update_runner.py
python -m pytest tests/test_daily_update_runner.py tests/test_daily_task_script.py tests/test_notify_daily_task_dingtalk.py -q
```

Expected: compilation succeeds and all selected tests pass.

- [ ] **Step 3: Run the full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Inspect the final diff**

Run:

```powershell
git diff --check
git status --short
```

Confirm only the runner, tests, and documentation created for this feature are modified, while pre-existing untracked files remain untouched.
