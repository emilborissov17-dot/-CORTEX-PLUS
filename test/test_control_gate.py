"""control/gate.py - the gate in front of Claude Code (Kimi R71/R72, Emil R47/R48/R61).
Every test builds a throwaway repo in tmp: control/ copied from this repo, its own seal and ledger.
Forbidden strings are assembled from pieces here so this file itself carries none of them."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GROQ = "api." + "groq" + ".com"
ENV = dict(os.environ, CONTROL_NO_TELEGRAM="1")


@pytest.fixture
def box(tmp_path):
    (tmp_path / "control").mkdir()
    for f in ("gate.py", "forbidden.tsv"):
        shutil.copyfile(REPO / "control" / f, tmp_path / "control" / f)
    (tmp_path / "memory").mkdir()
    run(tmp_path, ["seal", "control/forbidden.tsv", "control/gate.py"])
    return tmp_path


def run(box, args, stdin=b""):
    return subprocess.run([sys.executable, str(box / "control" / "gate.py"), *args],
                          input=stdin, capture_output=True, env=ENV, cwd=box)


def hook(box, tool, tool_input, event="PreToolUse"):
    data = {"hook_event_name": event, "tool_name": tool, "tool_input": tool_input}
    if event == "UserPromptSubmit":
        data = {"hook_event_name": event, "prompt": tool_input}
    return run(box, ["hook"], json.dumps(data).encode())


def rows(box):
    p = box / "memory" / "control" / "gate_ledger.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_a_cloud_model_call_is_blocked_and_written(box):
    r = hook(box, "Bash", {"command": f"curl -s https://{GROQ}/openai/v1/models"})
    assert r.returncode == 2 and b"F01" in r.stderr
    assert rows(box)[-1]["decision"] == "BLOCK" and rows(box)[-1]["rule"] == "F01"


def test_an_ordinary_command_is_allowed_and_written(box):
    r = hook(box, "Bash", {"command": "git status --short | wc -l"})
    assert r.returncode == 0
    assert rows(box)[-1]["decision"] == "ALLOW"


def test_a_read_is_allowed_and_not_written(box):
    assert hook(box, "Read", {"file_path": str(box / "control" / "gate.py")}).returncode == 0
    assert rows(box) == []


def test_the_powershell_tool_is_checked_too(box):
    r = hook(box, "PowerShell", {"command": f"Invoke-WebRequest https://{GROQ}"})
    assert r.returncode == 2


def test_writing_the_list_or_the_ledger_is_blocked(box):
    for target in ("control/forbidden.tsv", "memory/control/gate_ledger.jsonl", ".claude/settings.json",
                   ".git/hooks/pre-commit"):
        r = hook(box, "Write", {"file_path": str(box / target), "content": "x"})
        assert r.returncode == 2 and b"R71 B6" in r.stderr, target


def test_a_shell_write_into_the_control_is_blocked(box):
    r = hook(box, "Bash", {"command": "echo ok > control/forbidden.tsv"})
    assert r.returncode == 2 and b"P02" in r.stderr
    assert hook(box, "Bash", {"command": "cat control/forbidden.tsv"}).returncode == 0


def test_a_stream_redirect_is_not_a_write_but_a_real_write_still_is(box):
    assert hook(box, "Bash", {"command": "venv/Scripts/python.exe control/gate.py canary 2>&1"}).returncode == 0
    assert hook(box, "Bash", {"command": "git log -1 -- control/gate.py 2>/dev/null"}).returncode == 0
    r = hook(box, "Bash", {"command": "echo ok > control/forbidden.tsv 2>&1"})
    assert r.returncode == 2 and b"P02" in r.stderr


def test_code_importing_a_cloud_model_is_blocked(box):
    r = hook(box, "Write", {"file_path": str(box / "core" / "x.py"), "content": "import " + "groq\n"})
    assert r.returncode == 2 and b"F11" in r.stderr


def test_a_7b_model_name_is_blocked_but_a_bare_7b_is_not(box):
    r = hook(box, "Edit", {"file_path": str(box / "core" / "m.py"), "old_string": "a",
                           "new_string": 'MODEL = "qwen2.5:' + '7b"'})
    assert r.returncode == 2 and b"F31" in r.stderr
    r = hook(box, "Edit", {"file_path": str(box / "core" / "m.py"), "old_string": "a",
                           "new_string": "# a 7B parameter model cannot be trained on 4 GB"})
    assert r.returncode == 0


def test_deleting_a_tree_at_once_is_blocked(box):
    r = hook(box, "Bash", {"command": "rm -" + "rf build/"})
    assert r.returncode == 2 and b"F25" in r.stderr


def test_a_report_that_opens_with_what_works_is_blocked(box):
    r = hook(box, "Write", {"file_path": str(box / "claude" / "reports" / "R.md"),
                            "content": "# What " + "works\n\nall of it"})
    assert r.returncode == 2 and b"F42" in r.stderr


def test_a_pasted_prompt_is_logged_not_blocked(box):
    r = hook(box, "", f"remove the call to {GROQ} from core/x.py", event="UserPromptSubmit")
    assert r.returncode == 0 and rows(box)[-1]["decision"] == "LOGGED"


def test_an_edited_list_blocks_everything(box):
    with (box / "control" / "forbidden.tsv").open("a", encoding="utf-8") as fh:
        fh.write("# one more line\n")
    r = hook(box, "Bash", {"command": "ls"})
    assert r.returncode == 2 and b"sealed file changed" in r.stderr


def test_a_missing_seal_or_garbage_input_blocks(box):
    assert run(box, ["hook"], b"not json").returncode == 2
    (box / "control" / "SEAL.json").unlink()
    assert hook(box, "Bash", {"command": "ls"}).returncode == 2


def test_the_ledger_is_a_chain_and_an_edited_row_is_found(box):
    hook(box, "Bash", {"command": "ls"})
    hook(box, "Bash", {"command": "pwd"})
    assert run(box, ["verify"]).returncode == 0
    p = box / "memory" / "control" / "gate_ledger.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"ALLOW"', '"BLOCK"')
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert run(box, ["verify"]).returncode == 1


def test_the_canary_is_blocked(box):
    r = run(box, ["canary"])
    assert r.returncode == 0 and b"CANARY OK" in r.stdout


def _git(box, *a):
    return subprocess.run(["git", *a], cwd=box, capture_output=True, text=True, env=ENV)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_commit_and_push_go_through_the_gate(box):
    _git(box, "init", "-q")
    _git(box, "config", "user.email", "t@t")
    _git(box, "config", "user.name", "t")
    (box / "core").mkdir()
    (box / "core" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(box, "add", "core/a.py")
    assert run(box, ["pre-commit"]).returncode == 0
    _git(box, "commit", "-qm", "a")
    assert run(box, ["post-commit"]).returncode == 0
    (box / "core" / "b.py").write_text(f'URL = "https://{GROQ}"\n', encoding="utf-8")
    _git(box, "add", "core/b.py")
    r = run(box, ["pre-commit"])
    assert r.returncode == 2 and b"F01" in r.stderr
    _git(box, "commit", "-qm", "b", "--no-verify")           # a commit that skipped the gate
    head = _git(box, "rev-parse", "HEAD").stdout.strip()
    push = f"refs/heads/m {head} refs/heads/m {'0' * 40}\n".encode()
    r = run(box, ["pre-push", "origin", "x"], push)
    assert r.returncode == 2 and b"P03" in r.stderr


def _bash():
    """POSIX bash on Linux; on Windows only Git Bash counts (the bash.exe on the Windows PATH is WSL)."""
    if os.name != "nt":
        return shutil.which("bash")
    pf = os.environ.get("ProgramFiles")
    b = Path(pf) / "Git" / "bin" / "bash.exe" if pf else None
    return str(b) if b is not None and b.exists() else None


def _interpreter_in(box):
    """Give the box an interpreter where the hook command looks for one. Linux: a symlink to
    this interpreter. Windows: a copy of this repo's venv launcher and its pyvenv.cfg (the gate
    needs the standard library only); no link, so nothing outside the box can be removed with it."""
    if os.name == "nt":
        (box / "venv" / "Scripts").mkdir(parents=True)
        shutil.copyfile(REPO / "venv" / "Scripts" / "python.exe", box / "venv" / "Scripts" / "python.exe")
        shutil.copyfile(REPO / "venv" / "pyvenv.cfg", box / "venv" / "pyvenv.cfg")
    else:
        (box / "venv" / "bin").mkdir(parents=True)
        (box / "venv" / "bin" / "python").symlink_to(sys.executable)


@pytest.mark.skipif(_bash() is None, reason="no POSIX bash (on Windows only Git Bash counts)")
def test_the_hook_command_lets_the_gate_decide_and_blocks_when_the_gate_is_missing(box):
    cmd = json.loads((REPO / "control" / "settings.json").read_text(encoding="utf-8"))
    hook_cmd = cmd["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd["hooks"]["PreToolUse"][0]["matcher"] == "*"
    bash = _bash()
    env = dict(ENV, CLAUDE_PROJECT_DIR=str(box))
    _interpreter_in(box)                        # with an interpreter in place the gate decides
    ok = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    bad = dict(ok, tool_input={"command": f"curl https://{GROQ}"})
    r_ok = subprocess.run([bash, "-c", hook_cmd], input=json.dumps(ok).encode(), capture_output=True, env=env)
    assert r_ok.returncode == 0, r_ok.stderr
    r_bad = subprocess.run([bash, "-c", hook_cmd], input=json.dumps(bad).encode(), capture_output=True, env=env)
    assert r_bad.returncode == 2 and b"F01" in r_bad.stderr, r_bad.stderr
    (box / "control" / "gate.py").rename(box / "control" / "gone.py")
    r = subprocess.run([bash, "-c", hook_cmd], input=b"{}", capture_output=True, env=env)
    assert r.returncode == 2 and b"MISSING" in r.stderr
