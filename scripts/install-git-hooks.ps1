param()

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

git config core.hooksPath .githooks
Write-Host "Configured git core.hooksPath=.githooks"
Write-Host "Pre-commit now runs: uv run python scripts/verify.py --pre-commit"
