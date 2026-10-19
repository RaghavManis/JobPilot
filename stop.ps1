# ============================================================
#  JobPilot - Stop All Servers Immediately
#  Usage: .\stop.ps1
# ============================================================

Write-Host "Stopping JobPilot servers on ports 8000 and 8001..." -ForegroundColor Cyan

$stopped = 0
foreach ($port in 8000, 8001) {
    $pids = (netstat -ano | Select-String ":$port\s") |
            ForEach-Object { ($_ -split '\s+')[-1] } |
            Sort-Object -Unique
    foreach ($p in $pids) {
        if ($p -match '^\d+$' -and [int]$p -ne 0) {
            try {
                Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue
                Write-Host "  Stopped PID $p (port $port)" -ForegroundColor Green
                $stopped++
            } catch {}
        }
    }
}

if ($stopped -eq 0) {
    Write-Host "No active servers found on ports 8000 or 8001." -ForegroundColor Yellow
} else {
    Write-Host "All JobPilot servers stopped successfully." -ForegroundColor Green
}
