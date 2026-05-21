param(
    [string]$StartFrom = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$CommonArgs = @(
    "--snapshot-date", "2026-04-30",
    "--batch-size", "5000"
)

$ProductRuns = @(
    @{ Label = "2025-12-11~2025-12-31"; BizDate = "2025-12-31"; RefreshDays = "21" },
    @{ Label = "2026-01-01~2026-01-31"; BizDate = "2026-01-31"; RefreshDays = "31" },
    @{ Label = "2026-02-01~2026-02-28"; BizDate = "2026-02-28"; RefreshDays = "28" },
    @{ Label = "2026-03-01~2026-03-31"; BizDate = "2026-03-31"; RefreshDays = "31" },
    @{ Label = "2026-04-01~2026-04-29"; BizDate = "2026-04-29"; RefreshDays = "29" }
)

$ShouldRun = [string]::IsNullOrWhiteSpace($StartFrom)
foreach ($Run in $ProductRuns) {
    if (-not $ShouldRun) {
        if ($Run.Label -eq $StartFrom) {
            $ShouldRun = $true
        } else {
            Write-Host "[skip] product_performance_daily $($Run.Label)"
            continue
        }
    }

    Write-Host "[run] product_performance_daily $($Run.Label)"
    & "$PSScriptRoot\run_dashboard_daily_update.ps1" `
        "--steps" "product_performance_daily" `
        "--no-auto-full-load" `
        "--biz-date" $Run.BizDate `
        "--product-refresh-days" $Run.RefreshDays `
        @CommonArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Write-Host "[run] snapshots and period preset tables"
& "$PSScriptRoot\run_dashboard_daily_update.ps1" `
    "--steps" "restock_snapshot,inventory_snapshot,listing_price_snapshot,limit_price_snapshot,period_preset_snapshots" `
    "--biz-date" "2026-04-29" `
    "--period-end" "2026-04-29" `
    "--period-days" "90" `
    @CommonArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "[done] initial full refresh completed"
