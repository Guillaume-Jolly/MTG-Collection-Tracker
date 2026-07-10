# Raccourci bureau / barre des taches pour l archivage manuel des prix.
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LauncherBat = Join-Path $RepoRoot "launch_daily_prices.bat"
$IconPng = Join-Path $RepoRoot "scripts\prod_launcher\mtg-tracker.png"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "MTG Tracker (Prix).lnk"

if (-not (Test-Path $LauncherBat)) {
    throw "Launcher introuvable: $LauncherBat"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $LauncherBat
$Shortcut.WorkingDirectory = $RepoRoot
if (Test-Path $IconPng) {
    $Shortcut.IconLocation = "$IconPng,0"
}
$Shortcut.Description = "MTG Tracker - archivage manuel des prix"
$Shortcut.Save()

Write-Host "Raccourci cree: $ShortcutPath"
Write-Host "Cible: $LauncherBat"
Write-Host ""
Write-Host "Pour l epingler a la barre des taches:"
Write-Host "  1. Glissez le raccourci vers la barre, ou"
Write-Host "  2. Clic droit sur le raccourci - Epingler a la barre des taches"
