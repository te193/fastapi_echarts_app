$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $ProjectRoot "scripts\run_web_server.ps1") @args
exit $LASTEXITCODE
