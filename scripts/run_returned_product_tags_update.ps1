$ErrorActionPreference = "Stop"

. "$PSScriptRoot\dashboard_env.ps1"

$ProjectRoot = Get-DashboardProjectRoot
$PythonExe = Get-DashboardPython
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StdoutLog = Join-Path $LogDir "returned_product_tags_run_$RunStamp.log"
$StderrLog = Join-Path $LogDir "returned_product_tags_run_$RunStamp.err.log"

Set-Location $ProjectRoot

Write-Host "Returned product tags update started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Project root: $ProjectRoot"
Write-Host "Stdout log : $StdoutLog"
Write-Host "Stderr log : $StderrLog"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m etl.returned_product_tags_update @args > $StdoutLog 2> $StderrLog
$ExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($ExitCode -ne 0) {
    Write-Error "Returned product tags update failed with exit code $ExitCode. See $StdoutLog and $StderrLog."
    exit $ExitCode
}

Write-Host "Returned product tags update finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
