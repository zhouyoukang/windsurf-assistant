$TaskName   = 'WindsurfWuWeiGuard'
$NodeExe    = (Get-Command node -ErrorAction SilentlyContinue).Source
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$WatchdogJs = Join-Path $ScriptDir '_watchdog_wuwei.js'

Write-Host "[autostart] TaskName=$TaskName"
Write-Host "[autostart] NodeExe=$NodeExe"
Write-Host "[autostart] WatchdogJs=$WatchdogJs"

if (-not $NodeExe) { Write-Host 'ERROR: node not found'; exit 1 }
if (-not (Test-Path $WatchdogJs)) { Write-Host "ERROR: $WatchdogJs not found"; exit 1 }

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action   = New-ScheduledTaskAction -Execute $NodeExe -Argument "`"$WatchdogJs`"" -WorkingDirectory $ScriptDir
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = 'PT30S'
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'WuWei Guard: auto rate-limit handler' -Force | Format-List TaskName, State
Write-Host 'OK'
