# Raccourci bureau pour le launcher dev.
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LauncherBat = Join-Path $RepoRoot "launch_dev.bat"
$ExePath = Join-Path $RepoRoot "MTG Tracker Dev.exe"
$DistExePath = Join-Path $RepoRoot "dist\MTG Tracker Dev.exe"
$IconPng = Join-Path $PSScriptRoot "prod_launcher\mtg-tracker.png"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "MTG Tracker (Dev).lnk"

if (-not (Test-Path $LauncherBat) -and -not (Test-Path $ExePath) -and -not (Test-Path $DistExePath)) {
    throw "Launcher introuvable dans $RepoRoot"
}

$Target = if (Test-Path $ExePath) { $ExePath } elseif (Test-Path $DistExePath) { $DistExePath } else { $LauncherBat }
$WorkingDir = $RepoRoot

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = $WorkingDir
if (Test-Path $IconPng) {
    $Shortcut.IconLocation = "$IconPng,0"
}
$Shortcut.Description = "MTG Tracker - panneau de controle dev"
$Shortcut.Save()

Write-Host "Raccourci cree: $ShortcutPath"
Write-Host "Cible: $Target"
