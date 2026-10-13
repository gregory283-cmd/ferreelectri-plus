param(
    [string]$TaskName = 'FERREELECTRI PLUS - Backup diario'
)

$ErrorActionPreference = 'Stop'
$dailyInstaller = Join-Path $PSScriptRoot 'install_daily_backup_task.ps1'
if (-not (Test-Path $dailyInstaller)) {
    throw "No se encontró el instalador diario: $dailyInstaller"
}

& $dailyInstaller -TaskName $TaskName