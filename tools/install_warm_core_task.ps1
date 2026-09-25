# tools/install_warm_core_task.ps1 - registers CORTEX_WarmCore (task #8 part 1, 24 Sep 2026).
#
# The task runs tools\ollama_serve.ps1 -WarmCore at logon and daily at 02:50 (before
# the 02:00-collectors/03:00-spine night is under way; added 25 Sep 2026), so the
# cycle's one local model is resident before any cycle asks for it: a cycle never loads
# a model, and a local call whose model is absent is refused ("warm core absent").
# WakeToRun is OFF - the warm core must not wake a sleeping laptop.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_warm_core_task.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_warm_core_task.ps1 -Show
#
# No AtStartup trigger (decision, 25 Sep 2026): it needs an elevated shell, and logon +
# 02:50 already put the core in place before any night; one registration path, no fallback.
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
$daily = New-ScheduledTaskTrigger -Daily -At "02:50"

Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $daily) -Settings $settings -Force | Out-Null
Write-Output "${name}: registered (at logon + daily 02:50), WakeToRun off"
