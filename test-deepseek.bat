@echo off
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo Backend .venv is missing. Install dependencies first.
  pause
  exit /b 1
)
echo This sends ONE synthetic Agent task to DeepSeek and uses API credits.
".venv\Scripts\python.exe" -m app.check_model --live
set "CHECK_RESULT=%ERRORLEVEL%"
if not "%CHECK_RESULT%"=="0" echo Check failed. Read the message above and check backend\.env.
pause
exit /b %CHECK_RESULT%
