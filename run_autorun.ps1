# run_autorun.ps1
# Activates the job-agent virtual environment and runs the full automated pipeline.
# Edit the arguments below to tune scouting and apply limits.
#
# Usage (manual one-off):
#   .\run_autorun.ps1
#
# The script is also called automatically by Windows Task Scheduler
# when you register it with schedule_autorun.ps1.

$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\job-agent"
$VenvActivate = "$ProjectRoot\.venv\Scripts\Activate.ps1"
$MainScript  = "$ProjectRoot\app\main.py"

if (-not (Test-Path $VenvActivate)) {
    Write-Error "Virtual environment not found at $VenvActivate. Run: python -m venv .venv && .\.venv\Scripts\Activate.ps1 && pip install -r requirements.txt"
    exit 1
}

& $VenvActivate

python $MainScript autorun `
    --keyword-count 6 `
    --max-per-search 8 `
    --limit 25 `
    --apply-limit 10 `
    --fresh-only `
    --fresh-days 15

# Exit code is propagated from Python so Task Scheduler can detect failures.
exit $LASTEXITCODE

