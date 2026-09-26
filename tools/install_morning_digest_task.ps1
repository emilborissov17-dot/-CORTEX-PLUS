# tools/install_morning_digest_task.ps1 - registers CORTEX_MorningDigest (C2c, 26 Sep 2026).
#
# Daily at 07:00 and 09:05 local. Both run tools\morning_digest.py, which sends only if
# nothing was delivered for today - so 09:05 is the retry. WakeToRun on.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_morning_digest_task.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$name = "CORTEX_MorningDigest"
$py = Join-Path $repo "venv\Scripts\python.exe"
$cmd = "`$env:PYTHONIOENCODING='utf-8'; & '$py' '$repo\tools\morning_digest.py' *>> '$repo\memory\morning_digest_run.log'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$cmd`"" `
    -WorkingDirectory $repo
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$settings.WakeToRun = $true
$t1 = New-ScheduledTaskTrigger -Daily -At "07:00"
$t2 = New-ScheduledTaskTrigger -Daily -At "09:05"
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($t1, $t2) -Settings $settings -Force | Out-Null
Write-Output "${name}: registered (daily 07:00 and 09:05), WakeToRun on"
