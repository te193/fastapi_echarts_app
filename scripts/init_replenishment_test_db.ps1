$ErrorActionPreference = "Stop"

. "$PSScriptRoot\dashboard_env.ps1"

$env:DASHBOARD_DB_NAME = "etl_datasync_replenishment_test"
$env:DASHBOARD_TARGET_SCHEMA = "etl_datasync_replenishment_test"

$Python = Get-DashboardPython
& $Python -m etl.replenishment_test_db @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
