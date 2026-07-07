$ErrorActionPreference = "Stop"

. "$PSScriptRoot\dashboard_env.ps1"

$ProjectRoot = Get-DashboardProjectRoot
$PythonExe = Get-DashboardPython
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$PreflightStdoutLog = Join-Path $LogDir "etl_source_preflight_run_$RunStamp.log"
$PreflightStderrLog = Join-Path $LogDir "etl_source_preflight_run_$RunStamp.err.log"
$StdoutLog = Join-Path $LogDir "etl_daily_run_$RunStamp.log"
$StderrLog = Join-Path $LogDir "etl_daily_run_$RunStamp.err.log"
$ReplenishmentStdoutLog = Join-Path $LogDir "etl_replenishment_run_$RunStamp.log"
$ReplenishmentStderrLog = Join-Path $LogDir "etl_replenishment_run_$RunStamp.err.log"
$ReplenishmentTrackingStdoutLog = Join-Path $LogDir "etl_replenishment_tracking_run_$RunStamp.log"
$ReplenishmentTrackingStderrLog = Join-Path $LogDir "etl_replenishment_tracking_run_$RunStamp.err.log"
$ReturnGoodsStdoutLog = Join-Path $LogDir "etl_return_goods_run_$RunStamp.log"
$ReturnGoodsStderrLog = Join-Path $LogDir "etl_return_goods_run_$RunStamp.err.log"
$DingTalkNotifyScript = Join-Path $ProjectRoot "scripts\notify_daily_task_dingtalk.py"

Set-Location $ProjectRoot

function Send-DashboardDingTalkNotification {
    param(
        [Parameter(Mandatory=$true)][string]$Status,
        [Parameter(Mandatory=$true)][string]$Stage,
        [int]$ExitCode = 0,
        [string]$ErrorMessage = ""
    )

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
        & $PythonExe @NotifyArgs | Out-Null
        $NotifyExitCode = $LASTEXITCODE
        if ($NotifyExitCode -ne 0) {
            Write-Warning "DingTalk notification failed with exit code $NotifyExitCode."
        }
    } catch {
        Write-Warning "DingTalk notification failed: $($_.Exception.Message)"
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
Write-Host "Replenishment tracking ETL started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Replenishment tracking stdout log : $ReplenishmentTrackingStdoutLog"
Write-Host "Replenishment tracking stderr log : $ReplenishmentTrackingStderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.replenishment_tracking_update --rolling-days 30 @args > $ReplenishmentTrackingStdoutLog 2> $ReplenishmentTrackingStderrLog
$ReplenishmentTrackingExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($ReplenishmentTrackingExitCode -ne 0) {
    Send-DashboardDingTalkNotification -Status "failed" -Stage "replenishment_tracking" -ExitCode $ReplenishmentTrackingExitCode -ErrorMessage "Replenishment tracking ETL failed with exit code $ReplenishmentTrackingExitCode. See $ReplenishmentTrackingStdoutLog and $ReplenishmentTrackingStderrLog."
    Write-Error "Replenishment tracking ETL failed with exit code $ReplenishmentTrackingExitCode. See $ReplenishmentTrackingStdoutLog and $ReplenishmentTrackingStderrLog."
    exit $ReplenishmentTrackingExitCode
}

Write-Host "Replenishment tracking ETL finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
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
Write-Host "Data update strategy includes rolling product refresh, current snapshots, preset period summaries, matrix summaries, replenishment results, replenishment tracking, and return goods."
Send-DashboardDingTalkNotification -Status "success" -Stage "all" -ExitCode 0
