# schedule_autorun.ps1
# Registers (or replaces) a Windows Task Scheduler task called "JobAgentAutorun"
# that runs run_autorun.ps1 every day at the time configured below.
#
# Run once from an elevated (Administrator) PowerShell to install the schedule:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\schedule_autorun.ps1
#
# To remove the task later:
#   Unregister-ScheduledTask -TaskName "JobAgentAutorun" -Confirm:$false

$ErrorActionPreference = "Stop"

# ── Configuration ────────────────────────────────────────────────────────────
$TaskName    = "JobAgentAutorun"
$ProjectRoot = "D:\job-agent"
$Script      = "$ProjectRoot\run_autorun.ps1"

# Time to run daily (24-hour format)
$RunHour   = 9
$RunMinute = 0
# ─────────────────────────────────────────────────────────────────────────────

if (-not (Test-Path $Script)) {
    Write-Error "Launcher script not found: $Script. Make sure run_autorun.ps1 exists in $ProjectRoot."
    exit 1
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At "$($RunHour):$($RunMinute.ToString('D2'))"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

# Remove existing task of the same name if present
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Daily job-agent autorun: scout -> shortlist -> fill (no auto-submit)." `
    -RunLevel Limited | Out-Null

Write-Host ""
Write-Host "✓ Task '$TaskName' registered successfully." -ForegroundColor Green
Write-Host "  Runs daily at $($RunHour):$($RunMinute.ToString('D2'))"
Write-Host "  Script: $Script"
Write-Host ""
Write-Host "To run immediately for testing:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "To view the task:"
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host ""
Write-Host "To remove the task:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"

