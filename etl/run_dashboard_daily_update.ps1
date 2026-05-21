$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $ProjectRoot "scripts\run_daily_update_task.ps1") @args
exit $LASTEXITCODE
