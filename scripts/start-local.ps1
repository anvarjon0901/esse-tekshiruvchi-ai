# Mahalliy ishga tushirish: backend + ixtiyoriy cloudflared tunnel
# Foydalanish: .\scripts\start-local.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Virtual env topilmadi. Avval: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

$python = Join-Path $Root ".venv\Scripts\python.exe"
$logsDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

# Eski bot instance bo'lmasin (faqat alohida bot ishga tushirganda RUN_BOT_WITH_WEB=false qiling)
$env:RUN_BOT_WITH_WEB = "true"
$env:TELEGRAM_BOT_MODE = "polling"

$listeners = netstat -ano | Select-String ":8000\s" | Select-String "LISTENING"
foreach ($line in $listeners) {
    $pid = ($line -split '\s+')[-1]
    if ($pid -match '^\d+$') {
        Write-Host "8000-port band (PID $pid). To'xtatilmoqda..." -ForegroundColor Yellow
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1

Write-Host "Backend ishga tushmoqda: http://127.0.0.1:8000" -ForegroundColor Cyan
$backend = Start-Process -FilePath $python -ArgumentList @(
    "-m", "uvicorn", "app.main:app",
    "--host", "127.0.0.1",
    "--port", "8000",
    "--reload"
) -PassThru -RedirectStandardOutput (Join-Path $logsDir "backend-local.out.log") `
    -RedirectStandardError (Join-Path $logsDir "backend-local.err.log") -WindowStyle Hidden

Start-Sleep -Seconds 3
if ($backend.HasExited) {
    Write-Host "Backend ishga tushmadi. logs\backend-local.err.log ni tekshiring." -ForegroundColor Red
    exit 1
}

$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($cloudflared) {
    Write-Host "Cloudflare tunnel (http2) ishga tushmoqda..." -ForegroundColor Cyan
    Write-Host "Tunnel URL logs\cloudflared-local.out.log faylida paydo bo'ladi." -ForegroundColor DarkGray
    Start-Process -FilePath $cloudflared.Source -ArgumentList @(
        "tunnel",
        "--url", "http://127.0.0.1:8000",
        "--protocol", "http2",
        "--no-autoupdate"
    ) -RedirectStandardOutput (Join-Path $logsDir "cloudflared-local.out.log") `
        -RedirectStandardError (Join-Path $logsDir "cloudflared-local.err.log") -WindowStyle Hidden
} else {
    Write-Host "cloudflared topilmadi. Faqat localhost ishlaydi." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Tayyor." -ForegroundColor Green
Write-Host "  Backend:  http://127.0.0.1:8000"
Write-Host "  To'xtatish: Stop-Process -Id $($backend.Id)"
Write-Host "  Tunnel URL: Select-String -Path logs\cloudflared-local.out.log -Pattern 'https://.*trycloudflare.com'"
