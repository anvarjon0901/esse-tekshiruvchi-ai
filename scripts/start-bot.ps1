# Telegram botni to'g'ri ishga tushirish
# Foydalanish (loyiha ildizidan): .\scripts\start-bot.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Virtual env topilmadi. Avval bajaring:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\activate"
    Write-Host "  pip install -r requirements.txt"
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host ".env fayli topilmadi. .env.example dan nusxa oling." -ForegroundColor Yellow
    exit 1
}

$env:RUN_BOT_WITH_WEB = "false"
$env:TELEGRAM_BOT_MODE = "polling"

$runningBots = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*bot.main*" }
if ($runningBots) {
    Write-Host "Eski bot jarayonlari to'xtatilmoqda..." -ForegroundColor Yellow
    $runningBots | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

Write-Host "Bot ishga tushmoqda..." -ForegroundColor Cyan
Write-Host "To'xtatish: Ctrl+C" -ForegroundColor DarkGray
& (Join-Path $Root ".venv\Scripts\python.exe") -m bot.main
