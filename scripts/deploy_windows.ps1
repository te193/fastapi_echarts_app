[CmdletBinding()]
param(
    [string]$TaskName = "DashboardDailyUpdate",
    [string]$TaskTime = "10:00",
    [switch]$SkipInstall,
    [switch]$SkipConnectionTest,
    [switch]$SkipScheduledTask,
    [switch]$RunUpdateNow,
    [switch]$StartServer,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

function Assert-NativeExitCode {
    param([Parameter(Mandatory = $true)][string]$Action)

    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-ProjectVenv {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$VenvDir
    )

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3 -m venv $VenvDir
        Assert-NativeExitCode "Creating Python virtual environment"
        return
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & $pythonCommand.Source -m venv $VenvDir
        Assert-NativeExitCode "Creating Python virtual environment"
        return
    }

    throw "Python was not found. Install Python 3.11+ first."
}

function Register-DashboardDailyTask {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$ScriptDir,
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$TaskTime
    )

    if ($TaskTime -notmatch '^(?:[01]\d|2[0-3]):[0-5]\d$') {
        throw "TaskTime must use HH:mm format, for example 10:00."
    }

    $timeParts = $TaskTime.Split(":")
    $triggerAt = Get-Date -Hour ([int]$timeParts[0]) -Minute ([int]$timeParts[1]) -Second 0
    $taskScript = Join-Path $ScriptDir "run_daily_update_task.ps1"
    $taskArgument = '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $taskScript
    $powerShellExe = (Get-Command powershell.exe).Source

    $action = New-ScheduledTaskAction `
        -Execute $powerShellExe `
        -Argument $taskArgument `
        -WorkingDirectory $ProjectRoot

    $trigger = New-ScheduledTaskTrigger -Daily -At $triggerAt
    $principal = New-ScheduledTaskPrincipal `
        -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Description "Run dashboard ETL every day at $TaskTime. Remote source is read-only; local database receives writes." `
        -Force | Out-Null
}

function Enable-DashboardFirewallRule {
    param([Parameter(Mandatory = $true)][int]$Port)

    if (-not (Test-Admin)) {
        Write-Warning "Firewall rule was skipped because the current PowerShell session is not running as Administrator."
        return
    }

    $ruleName = "Dashboard FastAPI TCP $Port"
    $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($existingRule) {
        Set-NetFirewallRule -DisplayName $ruleName -Enabled True | Out-Null
        return
    }

    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $Port | Out-Null
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"

Set-Location $ProjectRoot
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "backups") | Out-Null

Write-Host "Project root: $ProjectRoot"

if (-not $SkipInstall) {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Host "Creating Python virtual environment..."
        New-ProjectVenv -ProjectRoot $ProjectRoot -VenvDir $VenvDir
    }

    Write-Host "Installing Python dependencies..."
    & $VenvPython -m pip install --upgrade pip
    Assert-NativeExitCode "Upgrading pip"
    & $VenvPython -m pip install -r $Requirements
    Assert-NativeExitCode "Installing Python dependencies"
}

. "$ScriptDir\dashboard_env.ps1"
$PythonExe = Get-DashboardPython

if (-not $SkipConnectionTest) {
    Write-Host "Testing local target and remote read-only source database connections..."
    & $PythonExe -m etl.dashboard_daily_update --connection-test
    Assert-NativeExitCode "Testing database connections"
}

if ($OpenFirewall) {
    Enable-DashboardFirewallRule -Port ([int]$env:DASHBOARD_PORT)
}

if (-not $SkipScheduledTask) {
    Write-Host "Registering Windows scheduled task: $TaskName at $TaskTime every day..."
    Register-DashboardDailyTask -ProjectRoot $ProjectRoot -ScriptDir $ScriptDir -TaskName $TaskName -TaskTime $TaskTime
}

if ($RunUpdateNow) {
    Write-Host "Running dashboard ETL once now..."
    & (Join-Path $ScriptDir "run_daily_update_task.ps1")
    if (-not $?) {
        throw "Running dashboard ETL failed."
    }
}

Write-Host ""
Write-Host "Deployment script finished."
Write-Host "Daily task : $TaskName at $TaskTime"
Write-Host "Web script : .\scripts\run_web_server.ps1"
Write-Host "ETL script : .\scripts\run_daily_update_task.ps1"
Write-Host "Logs       : .\logs"

if ($StartServer) {
    & (Join-Path $ScriptDir "run_web_server.ps1")
    if (-not $?) {
        throw "Starting dashboard web server failed."
    }
}
