$env:PYTHONIOENCODING = "utf-8"

Write-Host "=============================================="
Write-Host " Job Agent - Nightly Pipeline  $(Get-Date)"
Write-Host "=============================================="

# Step 0: Kill any stale Chrome/Firefox processes
Write-Host "`n[Step 0] Clearing stale browser processes..."
taskkill /f /im chrome.exe 2>$null
taskkill /f /im firefox.exe 2>$null
taskkill /f /im geckodriver.exe 2>$null
Start-Sleep -Seconds 2

# Step 1: Ensure Ollama AI is running
Write-Host "`n[Step 1] Checking Ollama AI..."
$ollamaRunning = $false
try {
    Invoke-RestMethod -Uri http://localhost:11434/api/tags -ErrorAction Stop | Out-Null
    $ollamaRunning = $true
    Write-Host "  Ollama is already running."
} catch {
    Write-Host "  Ollama is down, starting it now..."
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 8
    Write-Host "  Ollama started."
}

# Step 2: Regenerate URLs (picks up any new roles/keywords)
Write-Host "`n[Step 2] Regenerating search URL permutations..."
& D:\job-agent\.venv\Scripts\python.exe generate_urls.py

# Step 3: NAUKRI Scout
Write-Host "`n[Step 3] Scouting NAUKRI (0-2 year experience roles)..."
& D:\job-agent\.venv\Scripts\python.exe -m app.main scout `
    --limit 100 `
    --max-per-search 10 `
    --max-pages-per-search 1 `
    --min-score 50 `
    --no-linkedin-jobs `
    --no-linkedin-posts `
    --fresh-only `
    --fresh-days 14

# Step 4: LINKEDIN Scout (discovery only)
Write-Host "`n[Step 4] Scouting LINKEDIN (job discovery)..."
& D:\job-agent\.venv\Scripts\python.exe -m app.main scout `
    --limit 60 `
    --max-per-search 8 `
    --max-pages-per-search 1 `
    --min-score 50 `
    --linkedin-jobs `
    --no-linkedin-posts `
    --fresh-only `
    --fresh-days 7

# Step 5: Expiry check and DB cleanup
Write-Host "`n[Step 5] Checking for expired links and purging..."
& D:\job-agent\.venv\Scripts\python.exe check_active_links.py

# Step 6: Bulk Fill and Submit
Write-Host "`n[Step 6] Bulk fill and auto-submit shortlisted jobs..."
& D:\job-agent\.venv\Scripts\python.exe auto_apply_all.py

Write-Host "`n=============================================="
Write-Host " Pipeline complete!  $(Get-Date)"
Write-Host " Open d:\job-agent\pending_applications.html"
Write-Host " to review and manually submit remaining jobs."
Write-Host "=============================================="

