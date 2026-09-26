# tools/install_resolver_task.ps1 - registers CORTEX_ResolveForward (task #30, 26 Sep 2026).
#
# Monthly on the 5th and the 22nd at 06:00, every month, running tools\run_resolver.ps1
# (resolver under the witness, role "resolver", through launch_detached). schtasks.exe
# /SC MONTHLY takes one day only, so the trigger is built through the Task Scheduler
# COM API: one monthly trigger, DaysOfMonth = 5 and 22. WakeToRun ON (Emil, 26 Sep 2026: unattended nights).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_resolver_task.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$name = "CORTEX_ResolveForward"
$svc = New-Object -ComObject Schedule.Service
$svc.Connect()
$def = $svc.NewTask(0)
$def.RegistrationInfo.Description = "Institution 0 forward-row resolver (resolve_forward_rows.py --publish), witnessed as role=resolver."
$def.Settings.StartWhenAvailable = $true
$def.Settings.WakeToRun = $true
$def.Settings.DisallowStartIfOnBatteries = $false
$def.Settings.StopIfGoingOnBatteries = $false
$def.Settings.ExecutionTimeLimit = "PT1H"
$t = $def.Triggers.Create(4)                    # TASK_TRIGGER_MONTHLY
$t.StartBoundary = "2026-10-05T06:00:00"
$t.DaysOfMonth = (1 -shl 4) -bor (1 -shl 21)    # bit n-1 = day n: the 5th and the 22nd
$t.MonthsOfYear = 4095                          # all twelve months
$a = $def.Actions.Create(0)                     # TASK_ACTION_EXEC
$a.Path = "powershell.exe"
$a.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$repo\tools\run_resolver.ps1`""
$a.WorkingDirectory = $repo
$svc.GetFolder("\").RegisterTaskDefinition($name, $def, 6, $null, $null, 3) | Out-Null   # create/update, interactive token
Write-Output "$name registered: monthly on the 5th and 22nd at 06:00 -> tools\run_resolver.ps1"
