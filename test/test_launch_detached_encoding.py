"""tools/launch_detached.ps1 must hand every child a UTF-8 stdout.

Why this test exists (5 Sep 2026): the detached suite run of 00:27 completed, then crashed
on its final print because the child had no PYTHONIOENCODING and cp1252 could not encode
U+FFFD. Its .out.log was left at 0 bytes. A launcher whose children can die on the last
line of their own report is a launcher that eats verdicts.

Two tests, one static and one behavioural:
  * the static one fails if the assignment is ever removed or moved below Start-Process
    (comment lines excluded - see _code_only);
  * the behavioural one launches a real child through the script that prints U+FFFD and
    reads it back from the .out.log the script names. It is the one that would actually
    have caught the 00:27 crash. It only runs on Windows, where the script can run.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "launch_detached.ps1"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8-sig")


def _code_only(text: str) -> str:
    """The script minus its comment lines. First version of this test searched the raw text
    for "Start-Process" and found the one in the header COMMENT (offset 1039), so it failed
    against a correct script on 5 Sep 15:34 - a check answering a different question than the
    one asked. Only code counts."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def test_script_sets_utf8_before_start_process():
    code = _code_only(_script_text())
    assign = code.find('$env:PYTHONIOENCODING = "utf-8"')
    start = code.find("Start-Process")
    assert assign != -1, "launch_detached.ps1 no longer sets PYTHONIOENCODING for its children"
    assert start != -1, "launch_detached.ps1 no longer calls Start-Process?"
    assert assign < start, "PYTHONIOENCODING is set AFTER Start-Process - the child never sees it"


def test_static_check_ignores_comments():
    # The check must not be satisfiable, or breakable, by a comment.
    fake = '# Start-Process mentioned here\n$env:PYTHONIOENCODING = "utf-8"\n$p = Start-Process x\n'
    code = _code_only(fake)
    assert code.find('$env:PYTHONIOENCODING') < code.find("Start-Process")
    fake2 = '# $env:PYTHONIOENCODING = "utf-8"\n$p = Start-Process x\n'
    assert _code_only(fake2).find('$env:PYTHONIOENCODING') == -1


@pytest.mark.skipif(sys.platform != "win32", reason="the launcher is a PowerShell script")
def test_detached_child_can_print_replacement_character():
    tmp = Path(tempfile.mkdtemp(prefix="k1b_launch_"))
    child = tmp / "child.py"
    # The child must not rely on the env it is testing for anything but stdout.
    child.write_text(
        "import sys\n"
        "sys.stdout.write('MARK \\ufffd END\\n')\n"
        "sys.stdout.flush()\n",
        encoding="utf-8",
    )
    log = tmp / "probe.log"
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(SCRIPT),
        "-Exe", sys.executable,
        "-Arguments", f'"{child}"',
        "-Log", str(log),
    ]
    env = dict(os.environ)
    env.pop("PYTHONIOENCODING", None)  # the launcher, not the caller, must supply it
    env.pop("PYTHONUTF8", None)
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO), env=env, timeout=60)
    assert res.returncode == 0, res.stderr
    out_log = tmp / "probe.out.log"
    err_log = tmp / "probe.err.log"
    deadline = time.time() + 30
    data = ""
    while time.time() < deadline:
        if out_log.exists():
            data = out_log.read_text(encoding="utf-8", errors="replace")
            if "END" in data or (err_log.exists() and err_log.stat().st_size > 0):
                break
        time.sleep(0.5)
    err = err_log.read_text(encoding="utf-8", errors="replace") if err_log.exists() else ""
    assert "UnicodeEncodeError" not in err, err
    assert "MARK � END" in data, f"stdout={data!r} stderr={err!r}"
