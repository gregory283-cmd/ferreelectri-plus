param(
    [string]$TaskName = 'FERREELECTRI PLUS - Backup diario'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repoRoot '.venv-1\Scripts\python.exe'
$manage = Join-Path $repoRoot 'manage.py'

if (-not (Test-Path $python)) {
    throw "No se encontró el intérprete del proyecto: $python"
}
if (-not (Test-Path $manage)) {
    throw "No se encontró manage.py: $manage"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$manage`" create_system_backup" `
    -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour 2 -Minute 0 -Second 0)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType S4U `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Backup diario verificado de PostgreSQL, auditoría, media y comprobantes privados.' `
    -Force | Out-Null

$markerDirectory = Join-Path $repoRoot 'backups'
New-Item -ItemType Directory -Path $markerDirectory -Force | Out-Null
$markerPath = Join-Path $markerDirectory 'backup-schedule.json'
[ordered]@{
    task_name = $TaskName
    cadence = 'daily'
    local_time = '02:00'
    registered_at_utc = (Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json -Compress | Set-Content -Path $markerPath -Encoding Ascii

Write-Output "Tarea '$TaskName' registrada para ejecutarse diariamente a las 02:00."
