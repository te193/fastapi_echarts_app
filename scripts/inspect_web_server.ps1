[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess

Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
    Select-Object ProcessId, ParentProcessId, CommandLine |
    Format-List

Get-CimInstance Win32_Process -Filter "name = 'powershell.exe'" |
    Select-Object ProcessId, ParentProcessId, CommandLine |
    Format-List

Get-ScheduledTask -TaskName DashboardWebServer -ErrorAction SilentlyContinue |
    Select-Object TaskName, State, TaskPath

Get-ScheduledTaskInfo -TaskName DashboardWebServer -ErrorAction SilentlyContinue |
    Select-Object LastRunTime, LastTaskResult, NextRunTime, NumberOfMissedRuns
