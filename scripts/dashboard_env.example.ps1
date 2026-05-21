$ErrorActionPreference = "Stop"

$Script:DashboardScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:ProjectRoot = Resolve-Path (Join-Path $Script:DashboardScriptDir "..")

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# Web server
$env:DASHBOARD_HOST = "0.0.0.0"
$env:DASHBOARD_PORT = "8000"
$env:DASHBOARD_DEFAULT_PERIOD_DAYS = "90"

# Local write database. All CREATE/DELETE/INSERT operations happen here.
$env:DASHBOARD_DB_HOST = "127.0.0.1"
$env:DASHBOARD_DB_PORT = "3306"
$env:DASHBOARD_DB_USER = "your_local_user"
$env:DASHBOARD_DB_PASSWORD = "your_local_password"
$env:DASHBOARD_DB_NAME = "etl_datasync_test"
$env:DASHBOARD_DB_CHARSET = "utf8mb4"

# Remote read-only source database. The ETL runner only executes SELECT/WITH statements here.
$env:DASHBOARD_SOURCE_DB_HOST = "your_remote_host"
$env:DASHBOARD_SOURCE_DB_PORT = "3306"
$env:DASHBOARD_SOURCE_DB_USER = "your_remote_user"
$env:DASHBOARD_SOURCE_DB_PASSWORD = "your_remote_password"
$env:DASHBOARD_SOURCE_DB_NAME = ""
$env:DASHBOARD_SOURCE_DB_CHARSET = "utf8mb4"

# Target tables are written to the local schema. Source schemas are read from the remote connection.
$env:DASHBOARD_TARGET_SCHEMA = "etl_datasync_test"
$env:DASHBOARD_ETL_SOURCE_SCHEMA = "etl_datasync"
$env:DASHBOARD_DWD_SOURCE_SCHEMA = "dwd_datasync"
$env:DASHBOARD_PRICING_SOURCE_SCHEMA = "temporary_dwd"
$env:DASHBOARD_PRICE_QUEUE_SOURCE_SCHEMA = "temporary_APP"
$env:DASHBOARD_PRICE_QUEUE_LOOKBACK_DAYS = "20"
$env:DASHBOARD_PRICE_REVIEW_LOOKBACK_DAYS = "80"

$LocalEnvScript = Join-Path $Script:DashboardScriptDir "dashboard_env.local.ps1"
if (Test-Path -LiteralPath $LocalEnvScript) {
    . $LocalEnvScript
}

function Get-DashboardProjectRoot {
    return $Script:ProjectRoot
}

function Get-DashboardPython {
    $venvPython = Join-Path $Script:ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    throw "Python was not found. Install Python 3.11+ or run scripts\deploy_windows.ps1 first."
}
