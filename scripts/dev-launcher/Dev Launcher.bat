@echo off
setlocal
cd /d "%~dp0"
title Dev Launcher

where node >nul 2>&1
if errorlevel 1 (
  echo [Erreur] Node.js requis — https://nodejs.org/
  pause
  exit /b 1
)

echo.
echo  Dev Launcher — %CD%
echo  Dashboard : voir dev-launcher.config.json ^(dashboardPort^)
echo  Fermez cette fenetre pour arreter le serveur dev et le lanceur.
echo.

node scripts\dev-launcher\server.mjs
if errorlevel 1 (
  echo.
  echo [Erreur] Le lanceur s'est arrete avec une erreur.
  pause
)
