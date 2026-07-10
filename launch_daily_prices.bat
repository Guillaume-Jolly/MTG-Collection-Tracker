@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo [MTG Tracker] Python introuvable — installez Python 3.11+
  pause
  exit /b 1
)

set "PYTHONW=pythonw"
where pythonw >nul 2>&1
if errorlevel 1 set "PYTHONW=python"

start "" "%PYTHONW%" "%~dp0launcher\daily_price_scheduler.py" --manual
exit /b 0
