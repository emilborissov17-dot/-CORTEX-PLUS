' CORTEX collector launcher — runs run_collector.ps1 HIDDEN (no console flash), with the
' whole transcript appended to memory/collector_runs.log so a 4-hourly unattended run is
' still readable afterwards. Fired by the CORTEX_Collector scheduled task.
Dim repo, ps1, logf, cmd, sh, fso
repo = "C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED"
ps1  = repo & "\experiments\collector\run_collector.ps1"
logf = repo & "\memory\collector_runs.log"

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

' WScript.Arguments are passed through to the collector (e.g. --dry)
Dim extra, i
extra = ""
For i = 0 To WScript.Arguments.Count - 1
  extra = extra & " " & WScript.Arguments(i)
Next

cmd = "cmd /c powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """" & _
      extra & " >> """ & logf & """ 2>&1"
sh.Run cmd, 0, False
