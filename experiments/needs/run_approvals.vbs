' CORTEX approvals launcher — runs the TELEGRAM DISPATCHER hidden (no console
' flash), fired by the 1-minute \CORTEX_Approvals task so a reply is applied
' within ~1 minute, hands-off. If pythonw is missing it falls back to python.
'
' 18 Sep 2026: this launched approve_reader.py directly until today, and that was
' the bug. getUpdates acknowledges SERVER-SIDE PER BOT TOKEN, so the reader that
' runs every minute deletes every other reader's messages. It consumed Emil's
' witness reply within sixty seconds and recorded nothing, because it matches
' only "OK <id>" / "NO <id>" and drops the rest silently.
'
' The dispatcher makes the ONE fetch with the ONE offset and routes: OK/NO into
' approve_reader's logic, unchanged and still refusing everything outside its
' three action types, and USED/NOTHING/COUNTERMANDED into the witness reader.
' Anything else is logged as unparsed. The scheduled task itself is untouched.
Dim repo, py, script, sh
repo = "C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED"
py = repo & "\venv\Scripts\pythonw.exe"
script = repo & "\experiments\institution\telegram_dispatcher.py"
Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists(py) Then py = repo & "\venv\Scripts\python.exe"
Set sh = CreateObject("WScript.Shell")
sh.Run """" & py & """ """ & script & """", 0, False
