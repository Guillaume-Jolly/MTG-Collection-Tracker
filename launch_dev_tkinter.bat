@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo [MTG Tracker Dev] Python introuvable dans le PATH.
  pause
  exit /b 1
)

where pythonw >nul 2>&1
if not errorlevel 1 (
  start "" pythonw "%~dp0launcher\dev_control_panel.py"
  exit /b 0
)

python "%~dp0launcher\dev_control_panel.py"
exit /b %ERRORLEVEL%
