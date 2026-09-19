param([string]$Python = '', [string]$Project = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
if (-not $Python) { $Python = Join-Path $Project '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Create .venv and install requirements first.' }
$action = New-ScheduledTaskAction -Execute $Python -Argument '-m src.jobs.scheduler' -WorkingDirectory $Project
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'Fantasy League Intelligence' -Action $action -Trigger $trigger -Settings $settings -Description 'Timezone-aware Tuesday fantasy reports with hourly failure recovery.'
Write-Output 'Registered. Starts at sign-in; start it now with Start-ScheduledTask -TaskName "Fantasy League Intelligence". The computer must remain awake and signed in.'
