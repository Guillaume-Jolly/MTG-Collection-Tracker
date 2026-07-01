# Cree le launcher prod local (dossier gitignore local_prod/).
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProdRoot = Join-Path $RepoRoot "local_prod"
$LauncherDir = Join-Path $ProdRoot "launcher"
$ProdDataDir = Join-Path $ProdRoot "data"
$TemplateDir = Join-Path $PSScriptRoot "prod_launcher"
$IconPng = Join-Path $TemplateDir "mtg-tracker.png"
$IconIco = Join-Path $LauncherDir "mtg-tracker.ico"

New-Item -ItemType Directory -Force -Path $LauncherDir, $ProdDataDir | Out-Null

if (-not (Test-Path $IconPng)) {
    throw "Image manquante: $IconPng"
}

Copy-Item $IconPng (Join-Path $LauncherDir "mtg-tracker.png") -Force

Add-Type -AssemblyName System.Drawing
$bitmap = [System.Drawing.Bitmap]::FromFile($IconPng)
$iconHandle = $bitmap.GetHicon()
$icon = [System.Drawing.Icon]::FromHandle($iconHandle)
$stream = [System.IO.File]::Create($IconIco)
$icon.Save($stream)
$stream.Close()
$icon.Dispose()
$bitmap.Dispose()

$LaunchBat = Join-Path $LauncherDir "launch.bat"
@'
@echo off
setlocal EnableExtensions
cd /d "%~dp0..\.."
set "ROOT=%CD%"

set "MTG_PWA_DB=%ROOT%\local_prod\data\mtg_prod.sqlite3"
set "MTG_PWA_PRICES_DB=%ROOT%\data\mtg_pwa.sqlite3"
set "MTG_PWA_CACHE=%ROOT%\data\cache"
set "MTG_PWA_PORT=8001"
set "MTG_PWA_PROFILE=prod"

if not exist "%MTG_PWA_PRICES_DB%" (
  echo [MTG Tracker Prod] Base dev introuvable:
  echo   %MTG_PWA_PRICES_DB%
  echo Importez d'abord les prix en dev, puis relancez.
  pause
  exit /b 1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8001 .*LISTENING"') do (
  echo [MTG Tracker Prod] Deja actif sur http://127.0.0.1:8001/
  start "" "http://127.0.0.1:8001/"
  exit /b 0
)

start "MTG Tracker (Prod)" /MIN cmd /c "cd /d "%ROOT%" && python run_mvp.py --port 8001"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8001/"
exit /b 0
'@ | Set-Content -Path $LaunchBat -Encoding ASCII

$CreateShortcut = Join-Path $LauncherDir "create_desktop_shortcut.ps1"
@'
$LauncherBat = Join-Path $PSScriptRoot "launch.bat"
$Icon = Join-Path $PSScriptRoot "mtg-tracker.ico"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "MTG Tracker.lnk"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $LauncherBat
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.IconLocation = "$Icon,0"
$Shortcut.Description = "MTG Tracker - version production"
$Shortcut.Save()

Write-Host "Raccourci cree: $ShortcutPath"
'@ | Set-Content -Path $CreateShortcut -Encoding UTF8

$Readme = Join-Path $ProdRoot "README.txt"
@'
MTG Tracker - environnement PROD (local, non versionne)

- Collection, decks possedes et metadonnees: local_prod\data\mtg_prod.sqlite3
- Prix / cartes / MTGJSON: partages avec le dev via data\mtg_pwa.sqlite3
- Cache images: partage via data\cache
- Port: 8001 (dev reste sur 8000)

Lancer: double-clic sur launcher\launch.bat
Raccourci bureau: powershell -ExecutionPolicy Bypass -File launcher\create_desktop_shortcut.ps1
'@ | Set-Content -Path $Readme -Encoding UTF8

Write-Host "Launcher prod installe dans: $ProdRoot"
Write-Host "Pour un raccourci sur le bureau:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$CreateShortcut`""
