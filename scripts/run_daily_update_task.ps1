$ErrorActionPreference = "Stop"

function Disable-CurrentConsoleQuickEdit {
    if (-not ([System.Management.Automation.PSTypeName]"DashboardConsoleMode").Type) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class DashboardConsoleMode
{
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
}
"@
    }

    $StdInputHandle = -10
    $EnableQuickEditMode = [uint32]0x0040
    $EnableExtendedFlags = [uint32]0x0080
    $ConsoleHandle = [DashboardConsoleMode]::GetStdHandle($StdInputHandle)
    $ConsoleMode = [uint32]0

    if (
        $ConsoleHandle -eq [IntPtr]::Zero -or
        -not [DashboardConsoleMode]::GetConsoleMode($ConsoleHandle, [ref]$ConsoleMode)
    ) {
        Write-Warning "Unable to read the current console mode; QuickEdit protection was not applied."
        return
    }

    $UpdatedConsoleMode = [uint32](($ConsoleMode -band (-bnot $EnableQuickEditMode)) -bor $EnableExtendedFlags)
    if (-not [DashboardConsoleMode]::SetConsoleMode($ConsoleHandle, $UpdatedConsoleMode)) {
        Write-Warning "Unable to disable QuickEdit for the current console."
        return
    }

    Write-Host "QuickEdit disabled for this ETL console."
}

Disable-CurrentConsoleQuickEdit

. "$PSScriptRoot\dashboard_env.ps1"

$ProjectRoot = Get-DashboardProjectRoot
$PythonExe = Get-DashboardPython
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$IsDryRun = $args -contains "--dry-run"
$PreflightStdoutLog = Join-Path $LogDir "etl_source_preflight_run_$RunStamp.log"
$PreflightStderrLog = Join-Path $LogDir "etl_source_preflight_run_$RunStamp.err.log"
$StdoutLog = Join-Path $LogDir "etl_daily_run_$RunStamp.log"
$StderrLog = Join-Path $LogDir "etl_daily_run_$RunStamp.err.log"
$ProductHistoryStdoutLog = Join-Path $LogDir "etl_product_history_run_$RunStamp.log"
$ProductHistoryStderrLog = Join-Path $LogDir "etl_product_history_run_$RunStamp.err.log"
$SalesRoleStdoutLog = Join-Path $LogDir "etl_sales_role_run_$RunStamp.log"
$SalesRoleStderrLog = Join-Path $LogDir "etl_sales_role_run_$RunStamp.err.log"
$LabelEvidenceStdoutLog = Join-Path $LogDir "etl_label_rule_evidence_run_$RunStamp.log"
$LabelEvidenceStderrLog = Join-Path $LogDir "etl_label_rule_evidence_run_$RunStamp.err.log"
$ReplenishmentStdoutLog = Join-Path $LogDir "etl_replenishment_run_$RunStamp.log"
$ReplenishmentStderrLog = Join-Path $LogDir "etl_replenishment_run_$RunStamp.err.log"
$ReplenishmentTrackingStdoutLog = Join-Path $LogDir "etl_replenishment_tracking_summary_run_$RunStamp.log"
$ReplenishmentTrackingStderrLog = Join-Path $LogDir "etl_replenishment_tracking_summary_run_$RunStamp.err.log"
$ReturnGoodsStdoutLog = Join-Path $LogDir "etl_return_goods_run_$RunStamp.log"
$ReturnGoodsStderrLog = Join-Path $LogDir "etl_return_goods_run_$RunStamp.err.log"
$DingTalkNotifyScript = Join-Path $ProjectRoot "scripts\notify_daily_task_dingtalk.py"
$DingTalkStdoutLog = Join-Path $LogDir "dingtalk_notify_run_$RunStamp.log"
$DingTalkStderrLog = Join-Path $LogDir "dingtalk_notify_run_$RunStamp.err.log"

Set-Location $ProjectRoot

function Send-DashboardDingTalkNotification {
    param(
        [Parameter(Mandatory=$true)][string]$Status,
        [Parameter(Mandatory=$true)][string]$Stage,
        [int]$ExitCode = 0,
        [string]$ErrorMessage = ""
    )

    if ($IsDryRun) {
        Write-Host "DingTalk notification skipped in dry-run mode."
        return
    }

    if (-not (Test-Path -LiteralPath $DingTalkNotifyScript)) {
        Write-Warning "DingTalk notification script was not found: $DingTalkNotifyScript"
        return
    }

    $NotifyArgs = @(
        $DingTalkNotifyScript,
        "--status", $Status,
        "--stage", $Stage,
        "--exit-code", $ExitCode,
        "--run-stamp", $RunStamp,
        "--project-root", $ProjectRoot,
        "--preflight-stdout", $PreflightStdoutLog,
        "--preflight-stderr", $PreflightStderrLog,
        "--dashboard-stdout", $StdoutLog,
        "--dashboard-stderr", $StderrLog,
        "--sales-role-stdout", $SalesRoleStdoutLog,
        "--sales-role-stderr", $SalesRoleStderrLog,
        "--label-evidence-stdout", $LabelEvidenceStdoutLog,
        "--label-evidence-stderr", $LabelEvidenceStderrLog,
        "--replenishment-stdout", $ReplenishmentStdoutLog,
        "--replenishment-stderr", $ReplenishmentStderrLog,
        "--tracking-stdout", $ReplenishmentTrackingStdoutLog,
        "--tracking-stderr", $ReplenishmentTrackingStderrLog,
        "--return-goods-stdout", $ReturnGoodsStdoutLog,
        "--return-goods-stderr", $ReturnGoodsStderrLog
    )

    if ($ErrorMessage) {
        $NotifyArgs += @("--error-message", $ErrorMessage)
    }

    $PreviousNativeExitCode = $global:LASTEXITCODE
    try {
        & $PythonExe @NotifyArgs > $DingTalkStdoutLog 2> $DingTalkStderrLog
        $NotifyExitCode = $LASTEXITCODE
        if ($NotifyExitCode -ne 0) {
            Write-Warning "DingTalk notification failed with exit code $NotifyExitCode. See $DingTalkStdoutLog and $DingTalkStderrLog."
        }
    } catch {
        Write-Warning "DingTalk notification failed: $($_.Exception.Message). See $DingTalkStdoutLog and $DingTalkStderrLog."
    } finally {
        $global:LASTEXITCODE = $PreviousNativeExitCode
    }
}

Write-Host "Source preflight started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Project root: $ProjectRoot"
Write-Host "Preflight stdout log : $PreflightStdoutLog"
Write-Host "Preflight stderr log : $PreflightStderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.dashboard_source_preflight @args > $PreflightStdoutLog 2> $PreflightStderrLog
$PreflightExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($PreflightExitCode -ne 0) {
    Send-DashboardDingTalkNotification -Status "failed" -Stage "source_preflight" -ExitCode $PreflightExitCode -ErrorMessage "Source preflight failed with exit code $PreflightExitCode."
    Write-Error "Source preflight failed with exit code $PreflightExitCode. See $PreflightStdoutLog and $PreflightStderrLog."
    exit $PreflightExitCode
}

Write-Host "Source preflight finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Dashboard ETL started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Project root: $ProjectRoot"
Write-Host "Stdout log : $StdoutLog"
Write-Host "Stderr log : $StderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.dashboard_daily_update @args > $StdoutLog 2> $StderrLog
$ExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($ExitCode -ne 0) {
    Send-DashboardDingTalkNotification -Status "failed" -Stage "dashboard" -ExitCode $ExitCode -ErrorMessage "Dashboard ETL failed with exit code $ExitCode."
    Write-Error "Dashboard ETL failed with exit code $ExitCode. See $StdoutLog and $StderrLog."
    exit $ExitCode
}

Write-Host "Dashboard ETL finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Product performance history sync started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Product history stdout log : $ProductHistoryStdoutLog"
Write-Host "Product history stderr log : $ProductHistoryStderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.product_performance_history_sync @args > $ProductHistoryStdoutLog 2> $ProductHistoryStderrLog
$ProductHistoryExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($ProductHistoryExitCode -ne 0) {
    Send-DashboardDingTalkNotification -Status "failed" -Stage "product_history" -ExitCode $ProductHistoryExitCode -ErrorMessage "Product performance history sync failed with exit code $ProductHistoryExitCode. See $ProductHistoryStdoutLog and $ProductHistoryStderrLog."
    Write-Error "Product performance history sync failed with exit code $ProductHistoryExitCode. See $ProductHistoryStdoutLog and $ProductHistoryStderrLog."
    exit $ProductHistoryExitCode
}

Write-Host "Product performance history sync finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Sales role ETL started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Sales role stdout log : $SalesRoleStdoutLog"
Write-Host "Sales role stderr log : $SalesRoleStderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.sales_role_snapshot_update @args > $SalesRoleStdoutLog 2> $SalesRoleStderrLog
$SalesRoleExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($SalesRoleExitCode -ne 0) {
    Send-DashboardDingTalkNotification -Status "failed" -Stage "sales_role" -ExitCode $SalesRoleExitCode -ErrorMessage "Sales role ETL failed with exit code $SalesRoleExitCode."
    Write-Error "Sales role ETL failed with exit code $SalesRoleExitCode. See $SalesRoleStdoutLog and $SalesRoleStderrLog."
    exit $SalesRoleExitCode
}

Write-Host "Sales role ETL finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Label change evidence ETL started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Label evidence stdout log : $LabelEvidenceStdoutLog"
Write-Host "Label evidence stderr log : $LabelEvidenceStderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.label_rule_evidence_snapshot_update @args > $LabelEvidenceStdoutLog 2> $LabelEvidenceStderrLog
$LabelEvidenceExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($LabelEvidenceExitCode -ne 0) {
    Send-DashboardDingTalkNotification -Status "failed" -Stage "label_evidence" -ExitCode $LabelEvidenceExitCode -ErrorMessage "Label change evidence update failed with exit code $LabelEvidenceExitCode; current label dashboard remains available."
    Write-Warning "Label change evidence update failed with exit code $LabelEvidenceExitCode. Current dashboard data remains available. See $LabelEvidenceStdoutLog and $LabelEvidenceStderrLog."
} else {
    Write-Host "Label change evidence ETL finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
}

Write-Host "Replenishment ETL started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Replenishment stdout log : $ReplenishmentStdoutLog"
Write-Host "Replenishment stderr log : $ReplenishmentStderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.replenishment_update @args > $ReplenishmentStdoutLog 2> $ReplenishmentStderrLog
$ReplenishmentExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($ReplenishmentExitCode -ne 0) {
    Send-DashboardDingTalkNotification -Status "failed" -Stage "replenishment" -ExitCode $ReplenishmentExitCode -ErrorMessage "Replenishment ETL failed with exit code $ReplenishmentExitCode."
    Write-Error "Replenishment ETL failed with exit code $ReplenishmentExitCode. See $ReplenishmentStdoutLog and $ReplenishmentStderrLog."
    exit $ReplenishmentExitCode
}

Write-Host "Replenishment ETL finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Replenishment tracking summary ETL started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Replenishment tracking summary stdout log : $ReplenishmentTrackingStdoutLog"
Write-Host "Replenishment tracking summary stderr log : $ReplenishmentTrackingStderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.replenishment_tracking_summary_update @args > $ReplenishmentTrackingStdoutLog 2> $ReplenishmentTrackingStderrLog
$ReplenishmentTrackingExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($ReplenishmentTrackingExitCode -ne 0) {
    Send-DashboardDingTalkNotification -Status "failed" -Stage "replenishment_tracking" -ExitCode $ReplenishmentTrackingExitCode -ErrorMessage "Replenishment tracking summary ETL failed with exit code $ReplenishmentTrackingExitCode."
    Write-Error "Replenishment tracking summary ETL failed with exit code $ReplenishmentTrackingExitCode. See $ReplenishmentTrackingStdoutLog and $ReplenishmentTrackingStderrLog."
    exit $ReplenishmentTrackingExitCode
}

Write-Host "Replenishment tracking summary ETL finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Return goods ETL started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Return goods stdout log : $ReturnGoodsStdoutLog"
Write-Host "Return goods stderr log : $ReturnGoodsStderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.return_goods_update @args > $ReturnGoodsStdoutLog 2> $ReturnGoodsStderrLog
$ReturnGoodsExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($ReturnGoodsExitCode -ne 0) {
    Send-DashboardDingTalkNotification -Status "failed" -Stage "return_goods" -ExitCode $ReturnGoodsExitCode -ErrorMessage "Return goods ETL failed with exit code $ReturnGoodsExitCode. See $ReturnGoodsStdoutLog and $ReturnGoodsStderrLog."
    Write-Error "Return goods ETL failed with exit code $ReturnGoodsExitCode. See $ReturnGoodsStdoutLog and $ReturnGoodsStderrLog."
    exit $ReturnGoodsExitCode
}

Write-Host "Return goods ETL finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Data update strategy includes rolling product refresh, current snapshots, preset period summaries, sales role snapshots, label change evidence, matrix summaries, replenishment results, replenishment tracking summary, and return goods."
Send-DashboardDingTalkNotification -Status "success" -Stage "all" -ExitCode 0
