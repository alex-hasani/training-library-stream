# Run once in an Administrator PowerShell window to keep the catalog running after boot.
$ErrorActionPreference = 'Stop'

$taskName = 'Training Library Stream'
$root = Split-Path -Parent $PSCommandPath
$pythonPath = 'C:\Python314\python.exe'
$tailscale = Get-Command tailscale -ErrorAction Stop

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python was not found at $pythonPath. Update `$pythonPath, then run this installer again."
}

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"' + (Join-Path $root 'server.py') + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Keeps Training Library Stream available on this PC and Tailnet.' -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
& $tailscale.Source serve --https=443 --bg http://127.0.0.1:8794
Write-Host 'Installed: starts at boot, restarts after failure, and is available through Tailscale HTTPS.'
