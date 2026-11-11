@echo off
echo Starting Google Chrome with Remote Debugging Port 9222...
taskkill /F /IM chrome.exe >nul 2>&1
timeout /t 1 >nul
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
echo Chrome started! Your tabs and LinkedIn session will restore.

