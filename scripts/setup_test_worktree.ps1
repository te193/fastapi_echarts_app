[CmdletBinding()]
param(
    [string]$WorktreePath = ".worktrees\dashboard-test",
    [string]$BranchName = "test/dashboard-test",
    [string]$BaseBranch = ""
)

$ErrorActionPreference = "Stop"

function Assert-NativeExitCode {
    param([Parameter(Mandatory = $true)][string]$Action)

    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

$status = git status --porcelain
if ($status) {
    throw "Working tree is not clean. Commit or stash current application changes before creating an isolated test worktree."
}

if (-not $BaseBranch) {
    $BaseBranch = (git branch --show-current).Trim()
}
if (-not $BaseBranch) {
    throw "Cannot determine base branch. Pass -BaseBranch explicitly."
}

$resolvedWorktree = Join-Path $ProjectRoot $WorktreePath
if (Test-Path -LiteralPath $resolvedWorktree) {
    Write-Host "Test worktree already exists: $resolvedWorktree"
} else {
    Write-Host "Creating test worktree: $resolvedWorktree"
    Write-Host "Base branch: $BaseBranch"
    Write-Host "Test branch: $BranchName"
    git worktree add $resolvedWorktree -b $BranchName $BaseBranch
    Assert-NativeExitCode "Creating test worktree"
}

$testEnvExample = Join-Path $resolvedWorktree "scripts\dashboard_env.test.example.ps1"
$testEnv = Join-Path $resolvedWorktree "scripts\dashboard_env.test.ps1"
if ((Test-Path -LiteralPath $testEnvExample) -and -not (Test-Path -LiteralPath $testEnv)) {
    Copy-Item -LiteralPath $testEnvExample -Destination $testEnv
    Write-Host "Created test environment override: $testEnv"
}

Write-Host ""
Write-Host "Test worktree is ready."
Write-Host "Start it with:"
Write-Host "  cd `"$resolvedWorktree`""
Write-Host "  .\scripts\run_web_server_test.ps1"
