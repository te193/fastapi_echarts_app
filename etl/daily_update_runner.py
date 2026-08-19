from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Callable, Iterable, Sequence


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
        "label_evidence",
        "标签规则证据 ETL",
        "etl.label_rule_evidence_snapshot_update",
        "etl_label_rule_evidence_run",
        "label_evidence",
        continue_on_failure=True,
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
        "return_goods",
        "返厂品 ETL",
        "etl.return_goods_update",
        "etl_return_goods_run",
        "return_goods",
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
    known, _unknown = parser.parse_known_args(raw_args)
    return RunnerOptions(dry_run=known.dry_run, etl_args=raw_args)


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


def _stream_pipe(pipe, log_file, emit: Emit) -> None:
    try:
        for line in iter(pipe.readline, ""):
            log_file.write(line)
            log_file.flush()
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

        stdout_thread = threading.Thread(
            target=_stream_pipe,
            args=(process.stdout, stdout_log, emit),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_stream_pipe,
            args=(process.stderr, stderr_log, emit),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        exit_code = process.wait()
        stdout_thread.join()
        stderr_thread.join()
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
    label_evidence = logs.get("label_evidence")
    replenishment = logs.get("replenishment")
    tracking = logs.get("replenishment_tracking")
    return_goods = logs.get("return_goods")
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
        "--label-evidence-stdout",
        str(label_evidence.stdout),
        "--label-evidence-stderr",
        str(label_evidence.stderr),
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
    ]
    if request.error_message:
        command.extend(("--error-message", request.error_message))
    return command


def send_dingtalk_notification(
    request: NotificationRequest,
    *,
    python_executable: str,
    project_root: Path,
    logs: DailyLogPaths,
) -> None:
    command = build_notification_command(
        request,
        python_executable=python_executable,
        project_root=project_root,
        logs=logs,
    )
    result = subprocess.run(
        command,
        cwd=project_root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"DingTalk notification failed with exit code {result.returncode}: {detail}"
        )


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)} 分 {remainder:.1f} 秒"


def _touch_logs(logs: DailyLogPaths) -> None:
    for item in logs.by_step.values():
        item.stdout.touch()
        item.stderr.touch()


def run_daily_update(
    *,
    project_root: Path,
    etl_args: Sequence[str] = (),
    dry_run: bool = False,
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
    run_stamp = now().strftime("%Y%m%d_%H%M%S")
    logs = build_log_paths(project_root, run_stamp)
    _touch_logs(logs)
    selected_steps = tuple(steps)
    step_results: list[StepResult] = []
    total_started = monotonic()

    if step_executor is None:
        step_executor = lambda command, stdout_path, stderr_path, writer: execute_subprocess(
            command,
            stdout_path,
            stderr_path,
            writer,
            cwd=project_root,
        )
    if notifier is None:
        notifier = lambda request: send_dingtalk_notification(
            request,
            python_executable=python_executable,
            project_root=project_root,
            logs=logs,
        )

    def notify(request: NotificationRequest) -> None:
        if dry_run:
            emit("钉钉通知：dry-run 模式已跳过。")
            return
        try:
            notifier(request)
            emit(f"钉钉通知：已发送 {request.status}/{request.stage}。")
        except Exception as exc:
            emit(f"[警告] 钉钉通知发送失败：{exc}")

    emit("=" * 72)
    emit(f"每日 ETL 汇总调度开始：{now():%Y-%m-%d %H:%M:%S}")
    emit(f"运行批次：{run_stamp}")
    emit(f"项目目录：{project_root}")
    emit(f"执行模式：{'流程验证（不写库）' if dry_run else '正式更新'}")
    emit(f"步骤数量：{len(selected_steps)}")
    emit("=" * 72)

    for index, step in enumerate(selected_steps, start=1):
        step_logs = logs.get(step.key)
        command = [python_executable, "-m", step.module, *etl_args]
        step_started = monotonic()
        emit("")
        emit(f"[{index}/{len(selected_steps)}] {step.label}")
        emit(f"模块：{step.module}")
        emit(f"开始：{now():%Y-%m-%d %H:%M:%S}")
        emit(f"标准日志：{step_logs.stdout}")
        emit(f"错误日志：{step_logs.stderr}")

        try:
            exit_code = step_executor(
                command,
                step_logs.stdout,
                step_logs.stderr,
                emit,
            )
        except Exception as exc:
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

        step_results.append(
            StepResult(
                step=step,
                status=status,
                exit_code=exit_code,
                elapsed_seconds=elapsed,
                logs=step_logs,
            )
        )

        if exit_code != 0:
            error_message = (
                f"{step.label} failed with exit code {exit_code}. "
                f"See {step_logs.stdout} and {step_logs.stderr}."
            )
            notify(
                NotificationRequest(
                    status="failed",
                    stage=step.stage,
                    exit_code=exit_code,
                    run_stamp=run_stamp,
                    error_message=error_message,
                )
            )
            if not step.continue_on_failure:
                total_elapsed = monotonic() - total_started
                emit("")
                emit("=" * 72)
                emit(f"每日 ETL 汇总调度失败，总耗时 {_format_elapsed(total_elapsed)}")
                emit(f"失败步骤：{step.label}")
                emit(f"退出码：{exit_code}")
                emit(f"错误日志：{step_logs.stderr}")
                emit("=" * 72)
                return RunResult(
                    exit_code=exit_code,
                    run_stamp=run_stamp,
                    step_results=tuple(step_results),
                    logs=logs,
                )

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
        }[result.status]
        emit(
            f"- {result.step.label}：{status_label}，"
            f"{_format_elapsed(result.elapsed_seconds)}，日志 {result.logs.stdout}"
        )
    emit("=" * 72)
    return RunResult(
        exit_code=0,
        run_stamp=run_stamp,
        step_results=tuple(step_results),
        logs=logs,
    )


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    result = run_daily_update(
        project_root=project_root,
        etl_args=options.etl_args,
        dry_run=options.dry_run,
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
