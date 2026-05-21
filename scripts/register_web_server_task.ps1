[CmdletBinding()]
param(
    [string]$TaskName = "DashboardWebServer",
    [switch]$Start
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python virtual environment was not found. Run scripts\deploy_windows.ps1 first."
}

$TaskArgument = '-m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level info'

$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument $TaskArgument `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Description "Run dashboard FastAPI web server at user logon." `
    -Force | Out-Null

if ($Start) {
    Start-ScheduledTask -TaskName $TaskName
}

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName,State,TaskPath
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime,LastTaskResult,NextRunTime,NumberOfMissedRuns
