$ErrorActionPreference = "Stop"

. "$PSScriptRoot\dashboard_env.ps1"

$ProjectRoot = Get-DashboardProjectRoot
$PythonExe = Get-DashboardPython
$HostAddress = $env:DASHBOARD_HOST
$Port = [int]$env:DASHBOARD_PORT

Set-Location $ProjectRoot

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    Stop-Process -Id $listener.OwningProcess -Force
}

Write-Host "Starting dashboard web server on http://$HostAddress`:$Port"
& $PythonExe -m uvicorn app.main:app --host $HostAddress --port $Port
