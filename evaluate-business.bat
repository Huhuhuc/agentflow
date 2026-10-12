@echo off
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo Backend .venv is missing. Install backend dependencies first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app.business_evaluation --mode mock --split dev --output evaluation/reports/business-mock-dev.json
if errorlevel 1 (
  pause
  exit /b 1
)
echo Reports saved to backend\evaluation\reports.
echo Import business-mock-dev.json in the enterprise Agent evaluation panel.
pause
