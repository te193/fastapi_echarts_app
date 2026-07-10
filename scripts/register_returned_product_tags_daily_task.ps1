param(
    [string]$TaskName = "FastAPI ECharts Returned Product Tags Update",
    [string]$RunAsUser = $env:USERNAME
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $ProjectRoot "scripts\run_returned_product_tags_update.ps1"

if (-not (Test-Path -LiteralPath $Runner)) {
    throw "Runner script was not found: $Runner"
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
$Trigger = New-ScheduledTaskTrigger -Daily -At 11:00
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -User $RunAsUser `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' to run daily at 11:00."
