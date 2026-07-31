' CORTEX approvals launcher — runs approve_reader.py HIDDEN (no console flash),
' meant to be fired by a 1-minute scheduled task so a Telegram "OK <id>" is applied
' within ~1 minute, hands-off. If pythonw is missing it falls back to python.
Dim repo, py, script, sh
repo = "C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED"
py = repo & "\venv\Scripts\pythonw.exe"
script = repo & "\experiments\needs\approve_reader.py"
Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists(py) Then py = repo & "\venv\Scripts\python.exe"
Set sh = CreateObject("WScript.Shell")
sh.Run """" & py & """ """ & script & """", 0, False
