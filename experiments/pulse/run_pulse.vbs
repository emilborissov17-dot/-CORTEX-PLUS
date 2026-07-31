' CORTEX pulse launcher - runs run_pulse.ps1 HIDDEN, every 5 minutes, appending the
' transcript to memory/pulse_runs.log. The stream itself is memory/pulse_stream.jsonl;
' this log is only for reading what a given tick printed.
Dim repo, ps1, logf, cmd, sh
repo = "C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED"
ps1  = repo & "\experiments\pulse\run_pulse.ps1"
logf = repo & "\memory\pulse_runs.log"

Dim extra, i
extra = ""
For i = 0 To WScript.Arguments.Count - 1
  extra = extra & " " & WScript.Arguments(i)
Next

Set sh = CreateObject("WScript.Shell")
cmd = "cmd /c powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """" & _
      extra & " >> """ & logf & """ 2>&1"
sh.Run cmd, 0, False
