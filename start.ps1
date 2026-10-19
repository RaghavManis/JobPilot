# ============================================================
#  JobPilot - Start All Servers
#  Usage: .\start.ps1   (run from project root)
# ============================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   JobPilot - Starting All Servers" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# -- 1. Kill anything already using ports 8000 or 8001 ------
foreach ($port in 8000, 8001) {
    $pids = (netstat -ano | Select-String ":$port\s") |
            ForEach-Object { ($_ -split '\s+')[-1] } |
            Sort-Object -Unique
    foreach ($p in $pids) {
        if ($p -match '^\d+$' -and [int]$p -ne 0) {
            try {
                Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue
                Write-Host "  [CLEANUP] Killed PID $p on port $port" -ForegroundColor Yellow
            } catch {}
        }
    }
}

Start-Sleep -Milliseconds 800

# -- 2. Start Mock Form Server (port 8001) ------------------
Write-Host "  [1/2] Starting Mock Form Server on http://localhost:8001 ..." -ForegroundColor Green

$mockProc = Start-Process `
    -FilePath ".\venv\Scripts\python.exe" `
    -ArgumentList "scripts/serve_mock.py" `
    -WorkingDirectory (Get-Location).Path `
    -PassThru

if ($null -ne $mockProc) {
    Write-Host "  [MOCK] Mock server started (PID $($mockProc.Id))" -ForegroundColor Green
} else {
    Write-Host "  [WARN] Mock server could not start. Check .\venv\Scripts\python.exe exists." -ForegroundColor Red
}

Start-Sleep -Milliseconds 1200

# -- 3. Start FastAPI Backend (port 8000) in foreground -----
Write-Host "  [2/2] Starting FastAPI Backend on http://localhost:8000 ..." -ForegroundColor Green
Write-Host ""
Write-Host "  Frontend UI  -> http://localhost:8000" -ForegroundColor Cyan
Write-Host "  Mock Form    -> http://localhost:8001/mock_form.html" -ForegroundColor Cyan
Write-Host "  API Docs     -> http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

try {
    .\venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
} finally {
    Write-Host ""
    if (($null -ne $mockProc) -and (-not $mockProc.HasExited)) {
        Write-Host "  Shutting down Mock Form Server (PID $($mockProc.Id))..." -ForegroundColor Yellow
        Stop-Process -Id $mockProc.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "  All servers stopped." -ForegroundColor Red
}
