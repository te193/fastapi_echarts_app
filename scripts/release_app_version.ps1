[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TagName,
    [string]$Message = "",
    [string]$ReleaseBranch = "release",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

function Assert-NativeExitCode {
    param([Parameter(Mandatory = $true)][string]$Action)

    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

. "$PSScriptRoot\dashboard_env.ps1"

$ProjectRoot = Get-DashboardProjectRoot
$PythonExe = Get-DashboardPython
Set-Location $ProjectRoot

$currentBranch = (git branch --show-current).Trim()
if ($currentBranch -ne $ReleaseBranch) {
    throw "Refusing to release from '$currentBranch'. Switch to '$ReleaseBranch' or pass -ReleaseBranch."
}

$status = git status --porcelain
if ($status) {
    throw "Working tree is not clean. Commit all release changes before tagging."
}

$existingTag = git tag --list $TagName
if ($existingTag) {
    throw "Tag already exists: $TagName"
}

if (-not $SkipTests) {
    & $PythonExe -m pytest
    Assert-NativeExitCode "Running tests before release"
}

if (-not $Message) {
    $Message = "Release $TagName"
}

git tag -a $TagName -m $Message
Assert-NativeExitCode "Creating release tag"

Write-Host "Release tag created: $TagName"
Write-Host "Restart the application server with .\scripts\run_web_server.ps1"
