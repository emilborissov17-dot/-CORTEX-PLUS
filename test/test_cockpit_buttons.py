"""The bottom buttons either show their result or take you to the trigger.

All four did the same thing: prefill(), which switches to TERMINAL and writes the
command to the shell's stdin — but only if a websocket is already connected.
Nothing auto-connects, so for Emil all four buttons did nothing at all, and the
one line explaining why was inside the terminal tab he had not reached.

Split by RISK:

  supervisor status, git status   QUESTIONS. Run server-side against a strict
                                  allowlist, answered in an overlay. Four
                                  gestures of ceremony around a read is three
                                  too many.
  run full cycle, claude code     ACTIONS. Still the terminal, still a human
                                  pressing Enter. What changes is that the tab
                                  switches, the input takes focus and a banner
                                  names the next gesture.

THE ALLOWLIST IS THE SECURITY ARGUMENT. /api/run takes a KEY, never a command,
so no string from the browser reaches a process. shell=False, fixed argv, a
timeout, and both commands only read.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from test_cockpit_doors import (FIXTURES, REPO, needs_node,  # noqa: F401
                                run_probe)

sys.path.insert(0, str(REPO))

RUN_FIXTURE = """
FIXTURES['/api/run/git_status'] = {ok:true, key:'git_status', label:'git status',
  argv:['git','status','--short','--branch'], exit_code:0, seconds:0.09,
  stdout:'## feature/x...origin/feature/x [ahead 12]\\n M cockpit/server.py',
  stderr:'', stdout_truncated:false, what:'what is modified'};
"""


# ── the read-only half ──────────────────────────────────────────────────────

@needs_node
def test_a_read_only_button_shows_its_output_without_a_terminal(tmp_path):
    """THE HEADLINE. No tab switch, no connect, no Enter."""
    r = run_probe(tmp_path, FIXTURES + RUN_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  const b = document.querySelectorAll('.ask-run').find(x => x.dataset.run === 'git_status');
  if(!b) return {found:false};
  await b.onclick();
  return {found:true,
          hidden: document.querySelector('#runwrap').hidden,
          out: document.querySelector('#runout').textContent,
          meta: document.querySelector('#runmeta').textContent,
          argv: document.querySelector('#runargv').textContent,
          tab: LOG.stored['cortex.cockpit.tab'] || 'overview',
          sockets: LOG.sockets.length};
};
""")
    res = r["result"]
    assert res["found"] is True, "no read-only buttons in the control bar"
    assert res["hidden"] is False, "the output panel never opened"
    assert "ahead 12" in res["out"], "the command's output was not rendered"
    assert "exit 0" in res["meta"]
    assert "git status --short --branch" in res["argv"], (
        "the panel does not show what it ran, so it has to be believed")
    assert res["tab"] != "terminal", "a read-only button detoured through the terminal"
    assert res["sockets"] == 0, "a read-only button opened a shell"


@needs_node
def test_the_output_panel_is_outside_view_so_a_tick_cannot_erase_it(tmp_path):
    """render() replaces #view every 15 seconds."""
    r = run_probe(tmp_path, FIXTURES + RUN_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  const b = document.querySelectorAll('.ask-run').find(x => x.dataset.run === 'git_status');
  await b.onclick();
  await render();                       // what tick() does
  return {out: document.querySelector('#runout').textContent,
          hidden: document.querySelector('#runwrap').hidden};
};
""")
    res = r["result"]
    assert res["hidden"] is False and "ahead 12" in res["out"], (
        "the answer vanished on the next 15-second re-render")


@needs_node
def test_the_panel_closes(tmp_path):
    r = run_probe(tmp_path, FIXTURES + RUN_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  await document.querySelectorAll('.ask-run')[0].onclick();
  document.querySelector('#runclose').onclick();
  return {hidden: document.querySelector('#runwrap').hidden};
};
""")
    assert r["result"]["hidden"] is True


# ── the action half ─────────────────────────────────────────────────────────

@needs_node
def test_an_action_button_switches_tab_prefills_and_asks_for_enter(tmp_path):
    """It must still be the human who presses Enter."""
    r = run_probe(tmp_path, FIXTURES + RUN_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('terminal');            // the tab connects itself now
  await settle();
  const b = document.querySelectorAll('.cmd').find(
    x => (x.dataset.cmd||'').includes('fast_cycle_runner'));
  if(!b) return {found:false};
  b.onclick();
  await settle();                        // prefill waits for the tab to mount
  return {found:true, tab: LOG.stored['cortex.cockpit.tab'],
          sends: LOG.socketSends, focused: LOG.focused,
          note: document.querySelector('#asknote').innerHTML,
          status: document.querySelector('#termstatus').textContent};
};
""")
    res = r["result"]
    assert res["found"] is True
    assert res["tab"] == "terminal", "the action button did not go to the terminal"
    typed = [s for s in res["sends"] if "fast_cycle_runner" in s]
    assert typed, "the command was never typed into the shell"
    assert not any(s.endswith('\\n"}') or "\\r" in s for s in typed), (
        "a newline was sent — the human must be the one to press Enter")
    assert "xterm" in res["focused"], (
        "the terminal did not take focus, so the Enter the banner asks for would "
        "go to the page instead of the shell")
    assert "press Enter" in res["note"], "no banner names the next gesture"


def test_the_runner_only_accepts_keys_from_its_own_allowlist():
    """No string from the browser reaches a process."""
    from cockpit import server as srv
    client = srv.app.test_client()

    bad = client.get("/api/run/not_a_command")
    assert bad.status_code == 404
    body = bad.get_json()
    assert body["ok"] is False
    assert sorted(body["allowed"]) == ["git_status", "supervisor_status"]

    good = client.get("/api/run/git_status")
    assert good.status_code == 200
    d = good.get_json()
    assert d["argv"] == ["git", "status", "--short", "--branch"]


def test_no_command_string_is_ever_taken_from_the_request():
    """ast: the argv must be a literal in the allowlist, never assembled."""
    import ast
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "api_run"), None)
    assert fn is not None, "api_run is gone"
    body = ast.unparse(fn)
    assert "request.args" not in body and "get_json" not in body, (
        "api_run reads from the request — the allowlist is the whole security "
        "argument and it only holds if the command is chosen by KEY")
    assert "shell=True" not in body
    assert "timeout=" in body, "an unbounded read-only command can still hang the page"


def test_both_allowlisted_commands_only_read():
    """A 'read-only' list with a writing command in it is worse than no list."""
    from cockpit import server as srv
    for key, spec in srv.READ_ONLY_COMMANDS.items():
        argv = " ".join(spec["argv"]).lower()
        for verb in ("commit", "push", "reset", "clean", "rm ", "--run-now",
                     "fast_cycle_runner", "checkout", "install"):
            assert verb not in argv, f"{key} is not read-only: {argv!r}"
