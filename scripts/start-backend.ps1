# Backend ishga tushirish (8000-portni avval bo'shatadi)
# Foydalanish: .\scripts\start-backend.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Port = 8000

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Virtual env topilmadi. Avval: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

$listeners = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING"
foreach ($line in $listeners) {
    $pid = ($line -split '\s+')[-1]
    if ($pid -match '^\d+$') {
        Write-Host "8000-port band (PID $pid). To'xtatilmoqda..." -ForegroundColor Yellow
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1

Write-Host "Backend: http://127.0.0.1:$Port" -ForegroundColor Cyan
& (Join-Path $Root ".venv\Scripts\python.exe") -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
