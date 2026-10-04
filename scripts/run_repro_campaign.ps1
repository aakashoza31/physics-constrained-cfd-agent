$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

if (-not $env:GEMINI_API_KEY) {
    throw "GEMINI_API_KEY is not configured in this PowerShell session."
}
if (-not $env:GEMINI_MODEL) { $env:GEMINI_MODEL = "gemini-3.5-flash-lite" }  # model used for the paper's text calls

$Out = Join-Path $Repo "demo\runs\nozzle_feedback"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

Write-Host "`n=== ENVIRONMENT CHECK ===" -ForegroundColor Cyan
python .\scripts\check_environment.py
if ($LASTEXITCODE -ne 0) { throw "Environment check failed." }

Write-Host "`n=== CASE A: FORCED FEEDBACK DEMONSTRATION ===" -ForegroundColor Cyan
python .\scripts\run_nozzle_feedback.py `
    --case A `
    --out $Out `
    --feedback-demo `
    --feedback-first-end-time 0.001 `
    --end-time 0.006 `
    --max-end-time 0.020 `
    --feedback-increment 0.005 `
    --max-iterations 4 `
    --max-diagnostic-requests 2 `
    --require-visuals
if ($LASTEXITCODE -ne 0) { throw "Case A failed." }

foreach ($Case in @("B", "C")) {
    Write-Host "`n=== CASE $Case ===" -ForegroundColor Cyan
    python .\scripts\run_nozzle_feedback.py `
        --case $Case `
        --out $Out `
        --end-time 0.006 `
        --max-end-time 0.020 `
        --feedback-increment 0.005 `
        --max-iterations 4 `
        --max-diagnostic-requests 2 `
        --require-visuals
    if ($LASTEXITCODE -ne 0) { throw "Case $Case failed." }
}

Write-Host "`n=== BUILD SANITIZED CAMPAIGN SUMMARY ===" -ForegroundColor Cyan
python .\scripts\build_nozzle_campaign_summary.py `
    --root $Out `
    --out (Join-Path $Out "CAMPAIGN_SUMMARY.json")
if ($LASTEXITCODE -ne 0) { throw "Campaign summary indicates a failed case." }

Write-Host "`n=== CAMPAIGN COMPLETE ===" -ForegroundColor Green
Write-Host "Evidence root: $Out" -ForegroundColor Green
