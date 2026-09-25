# tools/install_warm_core_task.ps1 - registers CORTEX_WarmCore (task #8 part 1, 24 Sep 2026).
#
# The task runs tools\ollama_serve.ps1 -WarmCore at logon, at system startup and daily at
# 02:50 (before the 03:00 cycle; added 25 Sep 2026), so the
# cycle's one local model is resident before any cycle asks for it: a cycle never loads
# a model, and a local call whose model is absent is refused ("warm core absent").
# WakeToRun is OFF - the warm core must not wake a sleeping laptop.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_warm_core_task.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_warm_core_task.ps1 -Show
#
# An AtStartup trigger needs an elevated shell; without one the task is registered with
# the logon trigger only, and the script says so instead of failing silently.
param([switch]$Show)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$name = "CORTEX_WarmCore"
$script = Join-Path $repo "tools\ollama_serve.ps1"

if ($Show) {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Output "${name}: not registered"; exit 1 }
    Write-Output "${name}: state=$($t.State) wake=$($t.Settings.WakeToRun) triggers=$(($t.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ', ')"
    exit 0
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -WarmCore" `
    -WorkingDirectory $repo
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$settings.WakeToRun = $false
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$startup = New-ScheduledTaskTrigger -AtStartup
$daily = New-ScheduledTaskTrigger -Daily -At "02:50"

try {
    Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $startup, $daily) -Settings $settings -Force | Out-Null
    Write-Output "${name}: registered (at logon + at startup + daily 02:50), WakeToRun off"
} catch {
    Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $daily) -Settings $settings -Force | Out-Null
    Write-Output "${name}: registered at logon + daily 02:50 - the STARTUP trigger needs an elevated shell ($($_.Exception.Message))"
}
