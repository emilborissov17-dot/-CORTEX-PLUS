# CORTEX++ — agent instructions

## Python interpreter

Never call bare `python` in shell commands on this machine — it is not on PATH and fails silently (empty output, exit code often swallowed by a trailing `2>/dev/null`). Always invoke the venv interpreter explicitly and force UTF-8 I/O:

```
PYTHONIOENCODING=utf-8 venv/Scripts/python.exe -c "..."
PYTHONIOENCODING=utf-8 venv/Scripts/python.exe script.py
```
