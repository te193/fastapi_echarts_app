$ErrorActionPreference = "Stop"

. "$PSScriptRoot\dashboard_env.ps1"

$ProjectRoot = Get-DashboardProjectRoot
$PythonExe = Get-DashboardPython
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StdoutLog = Join-Path $LogDir "etl_daily_run_$RunStamp.log"
$StderrLog = Join-Path $LogDir "etl_daily_run_$RunStamp.err.log"

Set-Location $ProjectRoot

Write-Host "Dashboard ETL started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Project root: $ProjectRoot"
Write-Host "Stdout log : $StdoutLog"
Write-Host "Stderr log : $StderrLog"

& $PythonExe -m etl.dashboard_daily_update @args > $StdoutLog 2> $StderrLog
$ExitCode = $LASTEXITCODE

if ($ExitCode -ne 0) {
    Write-Error "Dashboard ETL failed with exit code $ExitCode. See $StdoutLog and $StderrLog."
    exit $ExitCode
}

Write-Host "Dashboard ETL finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Data update strategy is unchanged: rolling product refresh, current snapshots, preset period summaries, and matrix summaries."
