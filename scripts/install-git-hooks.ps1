param()

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

git config core.hooksPath .githooks
Write-Host "Configured git core.hooksPath=.githooks"
Write-Host "Pre-commit full validation is disabled by default."
Write-Host 'Set OCTOPUS_FULL_VERIFY=1 for a commit to run: uv run python scripts/verify.py --pre-commit'
