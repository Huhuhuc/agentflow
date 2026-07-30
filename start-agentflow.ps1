$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Backend virtual environment was not found." -ForegroundColor Red
    Write-Host "Run this first:"
    Write-Host "  cd `"$backend`""
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "npm was not found. Please install Node.js first." -ForegroundColor Red
    exit 1
}

$backendCommand = "Set-Location `"$backend`"; & `"$python`" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
$frontendCommand = "Set-Location `"$frontend`"; npm run dev -- --host 127.0.0.1"

Start-Process powershell.exe -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCommand
Start-Process powershell.exe -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $frontendCommand

Write-Host ""
Write-Host "AgentFlow is starting..." -ForegroundColor Green
Write-Host "Backend:  http://127.0.0.1:8000/health/live"
Write-Host "Frontend: http://127.0.0.1:5173/"
Write-Host ""
Write-Host "Demo account:"
Write-Host "  demo@agentflow.dev"
Write-Host "  demo1234"

