# Installe (ou desinstalle) la tache planifiee Windows pour l'archivage quotidien des prix.
param(
    [switch]$Uninstall,
    [string]$StartAt = "08:00"
)

$ErrorActionPreference = "Stop"

$TaskName = "MTG Tracker - Archivage prix"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ScriptPath = Join-Path $RepoRoot "launcher\daily_price_scheduler.py"

if (-not (Test-Path $ScriptPath)) {
    throw "Script introuvable: $ScriptPath"
}

$Python = (Get-Command python -ErrorAction Stop).Source
$PythonDir = Split-Path $Python -Parent
$PythonW = Join-Path $PythonDir "pythonw.exe"
if (-not (Test-Path $PythonW)) {
    Write-Warning "pythonw.exe introuvable, utilisation de python.exe (fenetre console possible)."
    $PythonW = $Python
}

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tache supprimee: $TaskName"
    } else {
        Write-Host "Aucune tache a supprimer."
    }
    exit 0
}

$Action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument "`"$ScriptPath`"" `
    -WorkingDirectory $RepoRoot

# Verifie toutes les heures : sortie immediate si deja archive ; snooze 1 h apres refus.
$Trigger = New-ScheduledTaskTrigger -Once -At $StartAt `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "MTG Tracker - propose l archivage quotidien des prix (MTGJSON + Cardmarket) si non fait aujourd hui." `
    -Force | Out-Null

Write-Host "Tache installee: $TaskName"
Write-Host "  Script : $ScriptPath"
Write-Host "  Python : $PythonW"
Write-Host "  Frequence : toutes les heures (a partir de $StartAt)"
Write-Host ""
Write-Host ('Test manuel : pythonw "' + $ScriptPath + '"')
Write-Host 'Desinstallation : scripts\install-daily-price-task.ps1 -Uninstall'
