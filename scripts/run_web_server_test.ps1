$ErrorActionPreference = "Stop"

. "$PSScriptRoot\dashboard_env.ps1"

# Keep the test server off the application port. A local override may change
# the host, database, or port after the shared environment has loaded.
$env:DASHBOARD_PORT = "8001"
$TestEnvScript = Join-Path $PSScriptRoot "dashboard_env.test.ps1"
if (Test-Path -LiteralPath $TestEnvScript) {
    . $TestEnvScript
}

$ProjectRoot = Get-DashboardProjectRoot
$PythonExe = Get-DashboardPython
$HostAddress = $env:DASHBOARD_HOST
$Port = [int]$env:DASHBOARD_PORT

Set-Location $ProjectRoot

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    Stop-Process -Id $listener.OwningProcess -Force
}

Write-Host "Starting TEST dashboard web server on http://$HostAddress`:$Port"
Write-Host "Project root: $ProjectRoot"
& $PythonExe -m uvicorn app.main:app --host $HostAddress --port $Port
