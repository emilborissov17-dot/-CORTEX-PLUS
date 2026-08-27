"""The terminal connects itself and takes typing immediately.

From Emil's walk: clicking the TERMINAL tab and typing produced nothing. Three
separate reasons, none of them visible from the page:

  * nothing auto-connected. showTerminalTab() mounted an xterm and set the text
    "not started — click connect", so the tab's first instruction was to do
    again what opening it had already said;
  * term.onData only forwards when readyState === 1, so with no socket every
    keystroke was dropped in silence;
  * nothing ever called term.focus() and the cursor did not blink, so there was
    no cursor and no clue where the keys were supposed to go.

The security model is deliberately UNCHANGED: same token on the handshake, same
loopback Origin check, same logged I/O. This is ergonomics, not rights — and one
test here exists solely to keep it that way.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

from test_cockpit_doors import (FIXTURES, REPO, TEMPLATE, needs_node,  # noqa: F401
                                run_probe)

sys.path.insert(0, str(REPO))
PAGE = TEMPLATE.read_text(encoding="utf-8")

TERM = """
FIXTURES['/api/panels'] = {panels:[{panel:'terminal',live:true}]};
"""


@needs_node
def test_opening_the_tab_opens_the_session(tmp_path):
    """THE HEADLINE. The handshake fires on tab activation."""
    r = run_probe(tmp_path, FIXTURES + TERM + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('terminal');
  await settle();                        // let the socket report onopen
  return {sockets: LOG.sockets, sends: LOG.socketSends,
          state: document.querySelector('#tstate').textContent};
};
""")
    res = r["result"]
    assert res["sockets"] == ["ws://127.0.0.1:5056"], (
        f"the tab did not connect itself: {res['sockets']}")
    assert res["sends"], "the handshake frame was never sent"
    assert "__COCKPIT_TOKEN__" in res["sends"][0], (
        "the handshake went out without the token — the bridge would refuse it")
    assert res["state"] == "connected"


@needs_node
def test_the_terminal_takes_focus_so_typing_lands_in_the_shell(tmp_path):
    r = run_probe(tmp_path, FIXTURES + TERM + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('terminal');
  await settle();
  return {focused: LOG.focused};
};
""")
    assert "xterm" in r["result"]["focused"], (
        "the terminal never took focus, so keystrokes go to the page")


@needs_node
def test_the_state_is_one_word(tmp_path):
    """"is it up?" must be answerable without parsing a sentence."""
    r = run_probe(tmp_path, FIXTURES + TERM + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('terminal');
  await settle();
  const connected = document.querySelector('#tstate').textContent;
  closeTab(curTab);
  const closed = document.querySelector('#tstate').textContent;
  return {connected, closed};
};
""")
    res = r["result"]
    assert res["connected"] == "connected"
    assert res["closed"] == "closed"
    for word in (res["connected"], res["closed"]):
        assert " " not in word, f"the state is a sentence, not a word: {word!r}"


@needs_node
def test_a_session_the_human_closed_is_not_reconnected(tmp_path):
    """Helpfully reopening a session somebody just ended is not helpful."""
    r = run_probe(tmp_path, FIXTURES + TERM + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('terminal');
  await settle();
  const before = LOG.sockets.length;
  closeTab(curTab);
  return {before, after: LOG.sockets.length,
          state: document.querySelector('#tstate').textContent};
};
""")
    res = r["result"]
    assert res["after"] == res["before"], (
        "closing the session opened a new one")
    assert res["state"] == "closed"


@needs_node
def test_no_token_says_so_instead_of_opening_a_socket(tmp_path):
    """An empty token means the bridge did not start. Say that."""
    r = run_probe(tmp_path, FIXTURES + TERM + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('terminal');
  await settle();
  closeTab(curTab);
  document.querySelector('#tok').value = '';   // as if the bridge never started
  const before = LOG.sockets.length;
  connectTab(curTab);
  await settle();
  return {opened: LOG.sockets.length - before,
          state: document.querySelector('#tstate').textContent,
          status: document.querySelector('#termstatus').textContent};
};
""")
    res = r["result"]
    assert res["opened"] == 0, "opened a socket with no token"
    assert res["state"] == "closed"
    assert "bridge did not start" in res["status"]


def test_the_token_is_never_displayed():
    """Out of sight, still required."""
    assert 'type="hidden" id="tok"' in PAGE, (
        "the token is still rendered as a visible text field")
    assert "session token (injected by the server)" not in PAGE, (
        "the placeholder that advertised the token is still there")


def test_the_cursor_blinks():
    assert "cursorBlink:true" in PAGE.replace(" ", ""), (
        "no visible cursor: a terminal without one reads as a dead pane")


def test_clicking_the_pane_focuses_the_terminal():
    fn = PAGE.split("function mountSession(tab){")[1].split("\n}")[0]
    assert "mousedown" in fn and "focusTerminal" in fn, (
        "clicking the terminal area does not focus it; xterm hides its textarea "
        "and a click anywhere else does nothing")


def test_the_security_model_is_untouched():
    """THE GUARD ON THIS WHOLE PART. Ergonomics, not rights.

    Auto-connecting is only acceptable while every check that made the manual
    connect safe is still on the socket.
    """
    fn = PAGE.split("function connectTab(tab){")[1].split("\nfunction ")[0]
    assert "ws://127.0.0.1:5056" in fn, "the bridge is no longer loopback-only"
    assert "token" in fn, "the handshake no longer carries the token"

    from cockpit import terminal as term
    src = (REPO / "cockpit" / "terminal.py").read_text(encoding="utf-8-sig")
    assert "Origin" in src or "origin" in src, (
        "the bridge no longer checks the Origin")
    assert "token" in src, "the bridge no longer requires a token"


def test_the_bridge_still_logs_its_io():
    src = (REPO / "cockpit" / "terminal.py").read_text(encoding="utf-8-sig")
    assert "log_path" in src, "the terminal bridge stopped logging its I/O"
