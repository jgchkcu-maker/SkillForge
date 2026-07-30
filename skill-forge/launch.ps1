$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Skill Forge Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $projectRoot

Write-Host "[1/3] Starting backend..." -ForegroundColor Yellow
$backendCmd = 'Set-Location "' + $projectRoot + '"; python app.py'
Start-Process powershell -ArgumentList @("-NoExit","-Command",$backendCmd) -WindowTitle "Skill Forge - Backend"

Write-Host "[2/3] Starting frontend..." -ForegroundColor Yellow
$frontendCmd = 'Set-Location "' + $projectRoot + '"; pnpm run dev'
Start-Process powershell -ArgumentList @("-NoExit","-Command",$frontendCmd) -WindowTitle "Skill Forge - Frontend"

Write-Host "[3/3] Waiting for backend and frontend..." -ForegroundColor Yellow
$maxWait = 30
$waited = 0
$backendReady = $false
$frontendReady = $false
while ($waited -lt $maxWait) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8765" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $backendReady = $true
        }
    } catch {}
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $frontendReady = $true
        }
    } catch {}
    if ($backendReady -and $frontendReady) { break }
    Start-Sleep -Seconds 1
    $waited++
}

if (-not $backendReady -or -not $frontendReady) {
    Write-Host "Warning: backend or frontend did not respond in time, opening browser anyway." -ForegroundColor Red
}

Start-Sleep -Milliseconds 500
Start-Process "http://localhost:5173"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Skill Forge is running!" -ForegroundColor Green
Write-Host "  Backend:  http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Close the Backend or Frontend window to stop." -ForegroundColor Gray

pause
