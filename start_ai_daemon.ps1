# AI Engine Daemon for Job Agent
# Keeps the local Ollama server running indefinitely and restarts it instantly if it crashes under heavy load.

$ollamaExe = "ollama"

Write-Host "Starting AI Engine Daemon..."
while ($true) {
    Write-Host "Checking if Ollama is running..."
    $process = Get-Process ollama -ErrorAction SilentlyContinue
    
    if (-not $process) {
        Write-Host "Ollama is down. Starting..."
        Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    } else {
        Write-Host "Ollama is already running."
    }
    
    # Wait for 30 seconds before checking again
    Start-Sleep -Seconds 30
}
