# Compile un executable Windows pour le panneau de controle dev.
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DistDir = Join-Path $RepoRoot "dist"
$ExePath = Join-Path $DistDir "MTG Tracker Dev.exe"

python -m pip install --upgrade pyinstaller | Out-Host

Push-Location $RepoRoot
try {
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name "MTG Tracker Dev" `
        --distpath $DistDir `
        --workpath (Join-Path $RepoRoot "build\dev-launcher") `
        --specpath (Join-Path $RepoRoot "build\dev-launcher") `
        launcher\dev_control_panel.py
}
finally {
    Pop-Location
}

Copy-Item -Force $ExePath (Join-Path $RepoRoot "MTG Tracker Dev.exe")

Write-Host ""
Write-Host "Executable cree : $ExePath"
Write-Host "Copie racine projet : $(Join-Path $RepoRoot 'MTG Tracker Dev.exe')"
Write-Host "Python doit rester installe pour demarrer run_mvp.py."
