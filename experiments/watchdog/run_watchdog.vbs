' CORTEX trigger-watchdog launcher - runs run_watchdog.ps1 HIDDEN, appending its
' transcript to memory/watchdog_runs.log. Fired by the CORTEX_TriggerWatchdog task on a
' schedule of its own, deliberately not shared with CORTEX_Pulse.
Dim repo, ps1, logf, cmd, sh, extra, i
repo = "C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED"
ps1  = repo & "\experiments\watchdog\run_watchdog.ps1"
logf = repo & "\memory\watchdog_runs.log"

extra = ""
For i = 0 To WScript.Arguments.Count - 1
  extra = extra & " " & WScript.Arguments(i)
Next

Set sh = CreateObject("WScript.Shell")
cmd = "cmd /c powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """" & _
      extra & " >> """ & logf & """ 2>&1"
sh.Run cmd, 0, False
