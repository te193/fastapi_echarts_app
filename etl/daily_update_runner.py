from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from contextlib import suppress
import time
from typing import Callable, Iterable, Sequence

from etl.daily_pricing_update import EARLY_DASHBOARD_STEPS
from app import label_update_policy
from etl.run_observability import RunObserver, atomic_json_write, environment_number, observe


Emit = Callable[[str], None]
StepExecutor = Callable[[Sequence[str], Path, Path, Emit], int]


@dataclass(frozen=True)
class EtlStep:
    key: str
    label: str
    module: str
    log_prefix: str
    stage: str
    continue_on_failure: bool = False


@dataclass(frozen=True)
class RunnerOptions:
    dry_run: bool
    etl_args: tuple[str, ...]
    parallel_pricing: bool = True
    notifications_enabled: bool = True


@dataclass(frozen=True)
class StepLogPaths:
    stdout: Path
    stderr: Path


@dataclass(frozen=True)
class DailyLogPaths:
    by_step: dict[str, StepLogPaths]

    def get(self, key: str) -> StepLogPaths:
        return self.by_step[key]


@dataclass(frozen=True)
class StepResult:
    step: EtlStep
    status: str
    exit_code: int
    elapsed_seconds: float
    logs: StepLogPaths
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class NotificationRequest:
    status: str
    stage: str
    exit_code: int
    run_stamp: str
    error_message: str = ""


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    run_stamp: str
    step_results: tuple[StepResult, ...]
    logs: DailyLogPaths


# Nine active daily jobs. Retired label jobs stay outside the scheduled plan.
DEFAULT_STEPS = (
    EtlStep(
        "source_preflight",
        "远端数据完整性预检",
        "etl.dashboard_source_preflight",
        "etl_source_preflight_run",
        "source_preflight",
    ),
    EtlStep(
        "dashboard",
        "看板总 ETL",
        "etl.dashboard_daily_update",
        "etl_daily_run",
        "dashboard",
    ),
    EtlStep(
        "replenishment",
        "补货 ETL",
        "etl.replenishment_update",
        "etl_replenishment_run",
        "replenishment",
    ),
    EtlStep(
        "replenishment_tracking",
        "补货追踪汇总 ETL",
        "etl.replenishment_tracking_summary_update",
        "etl_replenishment_tracking_summary_run",
        "replenishment_tracking",
    ),
    EtlStep(
        "product_history",
        "产品表现历史同步",
        "etl.product_performance_history_sync",
        "etl_product_history_run",
        "product_history",
    ),
    EtlStep(
        "sales_role",
        "销售角色 / 生命周期 ETL",
        "etl.sales_role_snapshot_update",
        "etl_sales_role_run",
        "sales_role",
    ),
    EtlStep(
        "return_goods",
        "返厂品 ETL",
        "etl.return_goods_update",
        "etl_return_goods_run",
        "return_goods",
    ),
    EtlStep(
        "pricing",
        "定价及依赖分析 ETL",
        "etl.daily_pricing_update",
        "etl_pricing_run",
        "pricing",
    ),
    EtlStep(
        "return_strategy",
        "返场品运营策略预计算",
        "etl.return_goods_strategy_update",
        "etl_return_strategy_run",
        "return_strategy",
    ),
)


ENV_ASSIGNMENT_RE = re.compile(
    r'^\s*\$env:([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"((?:[^"`]|`.)*)"\s*$'
)


def parse_args(argv: Sequence[str] | None = None) -> RunnerOptions:
    raw_args = tuple(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Run the complete dashboard daily ETL chain without PowerShell."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the ETL flow without writing result tables or sending DingTalk.",
    )
    parser.add_argument("--serial", action="store_true",
                        help="Run pricing after return goods without overlapping branches.")
    parser.add_argument("--no-notify", action="store_true",
                        help="Perform real updates without sending milestone or final messages.")
    known, _unknown = parser.parse_known_args(raw_args)
    return RunnerOptions(dry_run=known.dry_run,
                         etl_args=tuple(arg for arg in raw_args if arg not in ('--serial', '--no-notify')),
                         parallel_pricing=not known.serial,
                         notifications_enabled=not known.no_notify)


def _select_arguments(args: Sequence[str], values: Sequence[str], switches: Sequence[str]) -> list[str]:
    selected = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in values:
            if index + 1 >= len(args) or args[index + 1].startswith('--'):
                raise ValueError(f'Missing value for task argument {arg}')
            selected.extend((arg, args[index + 1]))
            index += 2
            continue
        if arg in switches or arg.split('=', 1)[0] in values and '=' in arg:
            selected.append(arg)
        index += 1
    return selected


def build_step_command(step: EtlStep, args: Sequence[str], python_executable: str) -> list[str]:
    # Match the scheduled task's per-consumer argument contract. In particular,
    # --snapshot-date is today's source day, not the strategy's business day.
    profiles = {
        'sales_role': (('--snapshot-date', '--period-end', '--periods'), ('--skip-ddl', '--dry-run')),
        'label_evidence': (('--periods', '--date', '--bootstrap-start'),
                           ('--dry-run', '--reuse-inputs', '--full-sync', '--no-publish')),
        'stockout_historical_operating': (('--biz-date', '--data-date'),
                                         ('--allow-source-max-mismatch', '--dry-run')),
        'replenishment': (('--biz-date', '--snapshot-date', '--candidate-days',
                           '--history-start-date', '--history-end-date', '--batch-size'),
                          ('--skip-ddl', '--dry-run')),
        'replenishment_tracking': (('--cutoff-date',), ('--dry-run',)),
        'return_goods': (('--snapshot-date', '--lookback-days', '--batch-size'), ('--dry-run',)),
        'return_strategy': (('--biz-date',), ('--dry-run',)),
        'label_analysis': ((), ('--dry-run',)),
    }
    selected = _select_arguments(args, *profiles[step.key]) if step.key in profiles else list(args)
    if step.key == 'return_strategy':
        selected = [arg.replace('--biz-date', '--snapshot-date', 1) for arg in selected]
    if step.key == 'dashboard':
        selected.extend(('--steps', EARLY_DASHBOARD_STEPS))
    return [python_executable, '-m', step.module, *selected]


def _read_powershell_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = ENV_ASSIGNMENT_RE.match(line)
        if not match:
            continue
        name, value = match.groups()
        values[name] = re.sub(r"`(.)", r"\1", value)
    return values


def load_dashboard_environment(project_root: Path) -> None:
    scripts_dir = project_root / "scripts"
    protected_names = set(os.environ)
    merged: dict[str, str] = {}
    for path in (
        scripts_dir / "dashboard_env.ps1",
        scripts_dir / "dashboard_env.local.ps1",
    ):
        merged.update(_read_powershell_env_file(path))

    for name, value in merged.items():
        if name not in protected_names:
            os.environ[name] = value

    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    try:
        from etl.replenishment_update import apply_database_ini_env

        apply_database_ini_env(project_root / "config" / "database.ini")
    except ImportError:
        pass


def build_log_paths(project_root: Path, run_stamp: str) -> DailyLogPaths:
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    by_step: dict[str, StepLogPaths] = {}
    for step in DEFAULT_STEPS:
        by_step[step.key] = StepLogPaths(
            stdout=log_dir / f"{step.log_prefix}_{run_stamp}.log",
            stderr=log_dir / f"{step.log_prefix}_{run_stamp}.err.log",
        )
    return DailyLogPaths(by_step=by_step)


def _stream_pipe(pipe, log_file, emit: Emit, on_output=None) -> None:
    try:
        for line in iter(pipe.readline, ""):
            log_file.write(line)
            log_file.flush()
            if on_output is not None:
                on_output(line.rstrip("\r\n"))
            emit(line.rstrip("\r\n"))
    finally:
        pipe.close()


def execute_subprocess(
    command: Sequence[str],
    stdout_path: Path,
    stderr_path: Path,
    emit: Emit,
    *,
    cwd: Path,
    observer=None,
    step_key=None,
) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        stdout_path.open("w", encoding="utf-8", newline="") as stdout_log,
        stderr_path.open("w", encoding="utf-8", newline="") as stderr_log,
    ):
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("Failed to capture ETL process output.")
        if observer is not None:
            observe(observer,'child_started',step_key,process.pid)

        stdout_thread = threading.Thread(
            target=_stream_pipe,
            args=(process.stdout, stdout_log, emit,
                  (lambda line:observe(observer,'record_output',step_key,line)) if observer is not None else None),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_stream_pipe,
            args=(process.stderr, stderr_log, emit,
                  (lambda line:observe(observer,'record_output',step_key,line,'stderr')) if observer is not None else None),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        # Monitor only ETL children; failure notifications must remain available
        # after a lost guard session. Terminate only the process tree we started.
        watch_guard = "-m" in command
        try:
            while True:
                if observer is not None:
                    observe(observer,'tick')
                if watch_guard:
                    from etl.daily_update_guard import assert_guard_healthy
                    assert_guard_healthy()
                try:
                    exit_code = process.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except Exception:
            if process.poll() is None:
                if os.name == 'nt':
                    with suppress(OSError, subprocess.TimeoutExpired):
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                                       capture_output=True,timeout=15,check=False)
                else:
                    process.terminate()
                if process.poll() is None:
                    with suppress(OSError):process.kill()
                with suppress(subprocess.TimeoutExpired):process.wait(timeout=10)
            raise
        finally:
            # A failed tree stop can leave a grandchild holding a pipe. Never
            # block the runner's failure notification on an unbounded join.
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            raise RuntimeError('ETL output pipes remained open after child exit; child-tree shutdown is unconfirmed')
        return exit_code


def build_notification_command(
    request: NotificationRequest,
    *,
    python_executable: str,
    project_root: Path,
    logs: DailyLogPaths,
) -> list[str]:
    preflight = logs.get("source_preflight")
    dashboard = logs.get("dashboard")
    sales_role = logs.get("sales_role")
    replenishment = logs.get("replenishment")
    tracking = logs.get("replenishment_tracking")
    return_goods = logs.get("return_goods")
    pricing = logs.get("pricing")
    return_strategy = logs.get("return_strategy")
    command = [
        python_executable,
        str(project_root / "scripts" / "notify_daily_task_dingtalk.py"),
        "--status",
        request.status,
        "--stage",
        request.stage,
        "--exit-code",
        str(request.exit_code),
        "--run-stamp",
        request.run_stamp,
        "--project-root",
        str(project_root),
        "--preflight-stdout",
        str(preflight.stdout),
        "--preflight-stderr",
        str(preflight.stderr),
        "--dashboard-stdout",
        str(dashboard.stdout),
        "--dashboard-stderr",
        str(dashboard.stderr),
        "--sales-role-stdout",
        str(sales_role.stdout),
        "--sales-role-stderr",
        str(sales_role.stderr),
        "--replenishment-stdout",
        str(replenishment.stdout),
        "--replenishment-stderr",
        str(replenishment.stderr),
        "--tracking-stdout",
        str(tracking.stdout),
        "--tracking-stderr",
        str(tracking.stderr),
        "--return-goods-stdout",
        str(return_goods.stdout),
        "--return-goods-stderr",
        str(return_goods.stderr),
        "--pricing-stdout",
        str(pricing.stdout),
        "--pricing-stderr",
        str(pricing.stderr),
        "--return-strategy-stdout",
        str(return_strategy.stdout),
        "--return-strategy-stderr",
        str(return_strategy.stderr),
    ]
    # Older in-flight runs and archived runs may still supply these logs.
    for key, option in (
        ('label_evidence', 'label-evidence'),
        ('stockout_historical_operating', 'stockout'),
        ('label_analysis', 'label-analysis'),
    ):
        legacy = logs.by_step.get(key)
        if legacy is not None:
            command.extend((f'--{option}-stdout', str(legacy.stdout),
                            f'--{option}-stderr', str(legacy.stderr)))
    if request.error_message:
        command.extend(("--error-message", request.error_message))
    return command


def send_dingtalk_notification(
    request: NotificationRequest,
    *,
    python_executable: str,
    project_root: Path,
    logs: DailyLogPaths,
) -> str:
    command = build_notification_command(
        request,
        python_executable=python_executable,
        project_root=project_root,
        logs=logs,
    )
    notification_path = project_root / 'logs' / (
        f'dingtalk_notify_run_{request.run_stamp}_{request.stage}_{request.status}')
    notification_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            command,
            cwd=project_root,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=environment_number('DASHBOARD_NOTIFICATION_TIMEOUT_SECONDS',120),
        )
    except subprocess.TimeoutExpired as exc:
        # A transport deadline cannot prove that the remote service did not send.
        def decoded(value):
            return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else value or ''
        with suppress(OSError):
            Path(str(notification_path) + '.log').write_text(decoded(exc.stdout),encoding='utf-8')
            Path(str(notification_path) + '.err.log').write_text(decoded(exc.stderr),encoding='utf-8')
        raise
    with suppress(OSError):
        Path(str(notification_path) + '.log').write_text(result.stdout or '', encoding='utf-8')
        Path(str(notification_path) + '.err.log').write_text(result.stderr or '', encoding='utf-8')
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"DingTalk notification failed with exit code {result.returncode}: {detail}"
        )
    return ('skipped' if 'DingTalk webhook is not configured; notification skipped.' in (result.stdout or '')
            else 'sent')


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)} 分 {remainder:.1f} 秒"


def _touch_logs(logs: DailyLogPaths) -> None:
    for item in logs.by_step.values():
        item.stdout.touch()
        item.stderr.touch()


def _run_pricing_branches(indexed_steps, execute_step) -> list[StepResult]:
    """Two workers: roles -> return goods, alongside pricing; drain on failure.

    Called only after the standard chain has completed product history writes.
    Neither branch writes the other's business inputs. No labels may start until
    every running child has exited successfully.
    """
    roles, returns, pricing = indexed_steps
    completed = {}
    failed = False
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='daily-etl') as pool:
        running = {pool.submit(execute_step, *item): item for item in (roles, pricing)}
        while running:
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            batch = []
            for future in done:
                index, step = running.pop(future)
                result = future.result()
                completed[index] = result
                batch.append(result)
                if result.status == 'failed':
                    failed = True
            if not failed and any(result.step.key == 'sales_role' for result in batch):
                running[pool.submit(execute_step, *returns)] = returns
    return [completed[index] for index in sorted(completed)]


def run_daily_update(
    *,
    project_root: Path,
    etl_args: Sequence[str] = (),
    dry_run: bool = False,
    parallel_pricing: bool = False,
    notifications_enabled: bool = True,
    steps: Iterable[EtlStep] = DEFAULT_STEPS,
    python_executable: str = sys.executable,
    step_executor: StepExecutor | None = None,
    notifier: Callable[[NotificationRequest], None] | None = None,
    now: Callable[[], datetime] = datetime.now,
    monotonic: Callable[[], float] = time.monotonic,
    emit: Emit = print,
) -> RunResult:
    project_root = project_root.resolve()
    load_dashboard_environment(project_root)
    if dry_run and '--dry-run' not in etl_args:
        etl_args = (*etl_args, '--dry-run')
    dry_run = dry_run or '--dry-run' in etl_args
    started_at = now()
    run_stamp = started_at.strftime("%Y%m%d_%H%M%S")
    logs = build_log_paths(project_root, run_stamp)
    selected_steps = tuple(steps)
    # Explicit administrative steps still receive logs and the freeze guard;
    # they are never restored to the default nine-step plan.
    for step in selected_steps:
        logs.by_step.setdefault(step.key, StepLogPaths(
            stdout=project_root / 'logs' / f'{step.log_prefix}_{run_stamp}.log',
            stderr=project_root / 'logs' / f'{step.log_prefix}_{run_stamp}.err.log',
        ))
    _touch_logs(logs)
    step_results: list[StepResult] = []
    total_started = monotonic()
    console_path = project_root / 'logs' / f'etl_orchestrator_run_{run_stamp}.log'
    summary_path = project_root / 'logs' / f'etl_run_summary_{run_stamp}.json'
    original_emit = emit
    output_lock = threading.Lock()
    notification_records = []
    def emit(message: str) -> None:
        with output_lock:
            with console_path.open('a', encoding='utf-8') as console:
                console.write(message + '\n')
            original_emit(message)

    from etl.daily_update_guard import pinned_data_directory
    progress_directory = Path(os.getenv('DASHBOARD_PROGRESS_DIR',str(project_root / 'logs')))
    observer = RunObserver(progress_directory / f'etl_run_progress_{run_stamp}.json',run_stamp,
        database_directory=pinned_data_directory(),warning_sink=emit)

    def save_summary(exit_code, elapsed, *, terminal):
        report = {
            'run_stamp': run_stamp, 'started_at': started_at.isoformat(),
            'finished_at': now().isoformat() if terminal else None, 'elapsed_seconds': elapsed,
            'status': ('success' if exit_code == 0 else 'failed') if terminal else 'running',
            'exit_code': exit_code, 'dry_run': dry_run,
            'parallel_pricing': use_parallel, 'notifications_enabled': notifications_enabled,
            'notifications': [dict(record) for record in notification_records],
            'steps': [dict(key=r.step.key, module=r.step.module, status=r.status,
                           exit_code=r.exit_code, elapsed_seconds=r.elapsed_seconds,
                           started_at=r.started_at.isoformat() if r.started_at else None,
                           finished_at=r.finished_at.isoformat() if r.finished_at else None,
                           stdout=str(r.logs.stdout), stderr=str(r.logs.stderr))
                      for r in step_results],
        }
        try:
            atomic_json_write(summary_path,report)
        except OSError as exc:
            # A full logging volume must not prevent a file-only failure notice.
            with suppress(Exception):original_emit(f'[warn] run summary write failed: {type(exc).__name__}')

    def finish(exit_code: int, elapsed: float) -> RunResult:
        save_summary(exit_code,elapsed,terminal=True)
        observe(observer,'complete','success' if exit_code == 0 else 'failed',exit_code)
        observe(observer,'close')
        return RunResult(exit_code=exit_code, run_stamp=run_stamp,
                         step_results=tuple(step_results), logs=logs)

    if step_executor is None:
        step_executor = lambda command, stdout_path, stderr_path, writer: execute_subprocess(
            command,
            stdout_path,
            stderr_path,
            writer,
            cwd=project_root,
            observer=observer,
            step_key=next(step.key for step in selected_steps if logs.get(step.key).stdout == stdout_path),
        )
    if notifier is None:
        notifier = lambda request: send_dingtalk_notification(
            request,
            python_executable=python_executable,
            project_root=project_root,
            logs=logs,
        )

    def notify(request: NotificationRequest) -> None:
        def notification_log(message):
            with suppress(Exception):emit(message)
        terminal = request.stage == 'all' or (request.status == 'failed' and any(
            result.step.stage == request.stage and not result.step.continue_on_failure
            and result.exit_code != 0 for result in step_results))
        code = request.exit_code if terminal else None
        record = {'stage':request.stage,'status':request.status,
                  'state':'skipped' if dry_run or not notifications_enabled else 'sending'}
        notification_records.append(record)
        if terminal:
            observe(observer,'complete','success' if code==0 else 'failed',code)
        observe(observer,'notifications',notification_records)
        # Store the ETL outcome before any possibly slow external transport.
        save_summary(code,monotonic()-total_started,terminal=terminal)
        if dry_run:
            notification_log("钉钉通知：dry-run 模式已跳过。")
            return
        if not notifications_enabled:
            notification_log(f"钉钉通知：本次实测已跳过 {request.status}/{request.stage}。")
            return
        try:
            outcome=notifier(request)
        except Exception as exc:
            record.update(state='failed',error_type=type(exc).__name__)
            if isinstance(exc,subprocess.TimeoutExpired):record['delivery']='unknown'
            notification_log(f"[警告] 钉钉通知发送失败：{exc}")
        else:
            record['state']='skipped' if outcome=='skipped' else 'sent'
            action='已跳过（未配置）' if record['state']=='skipped' else '已发送'
            notification_log(f"钉钉通知：{action} {request.status}/{request.stage}。")
        finally:
            observe(observer,'notifications',notification_records)
            save_summary(code,monotonic()-total_started,terminal=terminal)

    emit("=" * 72)
    observe(observer,'start')
    emit(f"每日 ETL 汇总调度开始：{now():%Y-%m-%d %H:%M:%S}")
    emit(f"运行批次：{run_stamp}")
    emit(f"项目目录：{project_root}")
    emit(f"执行模式：{'流程验证（不写库）' if dry_run else '正式更新'}")
    emit(f"步骤数量：{len(selected_steps)}")
    use_parallel = parallel_pricing and selected_steps == DEFAULT_STEPS
    emit(f"定价分支：{'并行，最多 2 个任务' if use_parallel else '串行'}")
    emit("=" * 72)

    def execute_step(index: int, step: EtlStep) -> StepResult:
        step_logs = logs.get(step.key)
        step_started = monotonic()
        step_started_at = now()
        observe(observer,'begin_step',step.key,step_logs.stdout,step_logs.stderr)
        emit("")
        emit(f"[{index}/{len(selected_steps)}] {step.label}")
        emit(f"模块：{step.module}")
        emit(f"开始：{step_started_at:%Y-%m-%d %H:%M:%S}")
        emit(f"标准日志：{step_logs.stdout}")
        emit(f"错误日志：{step_logs.stderr}")

        if label_update_policy.LABEL_UPDATES_FROZEN and step.key in label_update_policy.FROZEN_STEP_KEYS:
            message = f"[跳过] {step.label}：{label_update_policy.FROZEN_MESSAGE}"
            emit(message)
            step_logs.stdout.write_text(message + '\n', encoding='utf-8')
            observe(observer, 'finish_step', step.key, 'skipped', 0)
            return StepResult(
                step=step, status='skipped', exit_code=0,
                elapsed_seconds=monotonic() - step_started, logs=step_logs,
                started_at=step_started_at, finished_at=now(),
            )

        child_exit_confirmed=True
        try:
            if not dry_run:
                from etl.daily_update_guard import check_stage_disk
                free_bytes=check_stage_disk()
                if free_bytes is not None:
                    emit(f"[guard] database_disk_free_gib={free_bytes/1024**3:.2f}")
            from etl.daily_update_guard import assert_guard_healthy
            assert_guard_healthy()
            command = build_step_command(step, etl_args, python_executable)
            def child_emit(message):
                observe(observer,'record_output',step.key,message)
                emit(message)
            exit_code = step_executor(
                command,
                step_logs.stdout,
                step_logs.stderr,
                child_emit,
            )
        except Exception as exc:
            child_exit_confirmed=False
            exit_code = 1
            with step_logs.stderr.open("a", encoding="utf-8") as error_log:
                error_log.write(f"{type(exc).__name__}: {exc}\n")
            emit(f"[失败] 无法执行 {step.label}：{exc}")

        elapsed = monotonic() - step_started
        if exit_code == 0:
            status = "success"
            emit(f"[成功] {step.label}，耗时 {_format_elapsed(elapsed)}")
        elif step.continue_on_failure:
            status = "warning"
            emit(
                f"[警告] {step.label} 返回退出码 {exit_code}，"
                f"耗时 {_format_elapsed(elapsed)}，后续流程继续。"
            )
        else:
            status = "failed"
            emit(
                f"[失败] {step.label} 返回退出码 {exit_code}，"
                f"耗时 {_format_elapsed(elapsed)}。"
            )

        observe(observer,'finish_step',step.key,status,exit_code,
                child_exit_confirmed=child_exit_confirmed)
        return StepResult(
            step=step, status=status, exit_code=exit_code,
            elapsed_seconds=elapsed, logs=step_logs,
            started_at=step_started_at, finished_at=now(),
        )

    indexed_steps = list(enumerate(selected_steps, start=1))
    groups = [[item] for item in indexed_steps]
    if use_parallel:
        # The prefix (including history corrections) and every label consumer
        # retain their publication barriers and original serial order.
        branch_start = next(i for i, (_, step) in enumerate(indexed_steps) if step.key == 'sales_role')
        branch_end = next(i for i, (_, step) in enumerate(indexed_steps) if step.key == 'pricing') + 1
        groups = groups[:branch_start] + [indexed_steps[branch_start:branch_end]] + groups[branch_end:]
    for group in groups:
        results = (_run_pricing_branches(group, execute_step) if len(group) > 1
                   else [execute_step(*group[0])])
        failure = None
        for result in results:
            step_results.append(result)
            step, exit_code, step_logs = result.step, result.exit_code, result.logs
            if exit_code == 0 and step.key == "replenishment":
                notify(NotificationRequest(
                    status="success", stage="replenishment", exit_code=0,
                    run_stamp=run_stamp,
                ))

            if exit_code != 0:
                error_message = (
                    f"{step.label} failed with exit code {exit_code}. "
                    f"See {step_logs.stdout} and {step_logs.stderr}."
                )
                notify(NotificationRequest(
                    status="failed", stage=step.stage, exit_code=exit_code,
                    run_stamp=run_stamp, error_message=error_message,
                ))
                if not step.continue_on_failure and failure is None:
                    failure = result
        if failure is not None:
            total_elapsed = monotonic() - total_started
            emit("")
            emit("=" * 72)
            emit(f"每日 ETL 汇总调度失败，总耗时 {_format_elapsed(total_elapsed)}")
            emit(f"失败步骤：{failure.step.label}")
            emit(f"退出码：{failure.exit_code}")
            emit(f"错误日志：{failure.logs.stderr}")
            emit("=" * 72)
            return finish(failure.exit_code, total_elapsed)

    notify(
        NotificationRequest(
            status="success",
            stage="all",
            exit_code=0,
            run_stamp=run_stamp,
        )
    )
    total_elapsed = monotonic() - total_started
    emit("")
    emit("=" * 72)
    emit(f"每日 ETL 汇总调度完成，总耗时 {_format_elapsed(total_elapsed)}")
    emit("步骤汇总：")
    for result in step_results:
        status_label = {
            "success": "成功",
            "warning": "警告",
            "failed": "失败",
            "skipped": "已冻结，跳过",
        }[result.status]
        emit(
            f"- {result.step.label}：{status_label}，"
            f"{_format_elapsed(result.elapsed_seconds)}，日志 {result.logs.stdout}"
        )
    emit("=" * 72)
    return finish(0, total_elapsed)


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    from etl.shared_product_inputs import RUN_ENV
    from uuid import uuid4
    previous_run = os.environ.get(RUN_ENV)
    load_dashboard_environment(project_root)
    from etl.daily_update_guard import daily_guard
    from contextlib import nullcontext
    try:
        if not options.dry_run:
            os.environ[RUN_ENV] = uuid4().hex
        with (nullcontext() if options.dry_run else daily_guard()):
            result = run_daily_update(
                project_root=project_root,
                etl_args=options.etl_args,
                dry_run=options.dry_run,
                parallel_pricing=options.parallel_pricing,
                notifications_enabled=options.notifications_enabled,
            )
            return result.exit_code
    finally:
        if previous_run is None:
            os.environ.pop(RUN_ENV, None)
        else:
            os.environ[RUN_ENV] = previous_run


if __name__ == "__main__":
    raise SystemExit(main())
