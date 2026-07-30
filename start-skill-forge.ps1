$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $scriptDir 'skill-forge\app.py'

Write-Host ''
Write-Host '   Starting SkillForge...' -ForegroundColor Cyan
Write-Host ''

Write-Host '   [1/2] Starting backend...' -ForegroundColor Yellow
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Host '   [ERROR] Python not found in PATH' -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

$proc = Start-Process -FilePath $python.Source -ArgumentList "`"$backend`"" -PassThru -WindowStyle Minimized
Write-Host "   Backend PID: $($proc.Id)" -ForegroundColor Green

Write-Host '   Waiting for backend...' -ForegroundColor DarkGray
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/health' -UseBasicParsing -TimeoutSec 1
        if ($r.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {}
    Start-Sleep -Milliseconds 250
}

if (-not $ready) {
    Write-Host '   [WARN] Backend did not respond in time, trying to open browser anyway...' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '   [2/2] Opening browser...' -ForegroundColor Yellow
Start-Process 'http://127.0.0.1:8765'

Write-Host ''
Write-Host '   SkillForge is ready.' -ForegroundColor Green
Write-Host '   Backend: http://127.0.0.1:8765' -ForegroundColor Cyan
Write-Host '   Close this window to stop.' -ForegroundColor Gray
Write-Host ''

try {
    $proc.WaitForExit()
} catch {}
