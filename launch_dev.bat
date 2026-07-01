@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where node >nul 2>&1
if errorlevel 1 (
  echo [MTG Tracker Dev] Node.js introuvable — installez Node ou utilisez launch_dev_tkinter.bat
  pause
  exit /b 1
)

call "%~dp0Dev Launcher.bat"
exit /b %ERRORLEVEL%
