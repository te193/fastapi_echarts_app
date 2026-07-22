[CmdletBinding()]
param(
    [string]$TaskName = "DashboardWebServer",
    [switch]$Start
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
$LauncherScript = Join-Path $ProjectRoot "run_lan_server.ps1"
if (-not (Test-Path -LiteralPath $LauncherScript)) {
    throw "Web launcher script was not found: $LauncherScript"
}

$TaskArgument = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$LauncherScript`""

$Action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
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
