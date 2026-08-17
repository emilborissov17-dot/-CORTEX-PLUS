#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_approval_server_is_closed.py — THE APPROVAL GATE IS NOT A PUBLIC ENDPOINT.

WHAT WENT WRONG (measured 17 August 2026)
------------------------------------------
`cortex_approval_server.py` ended in:

    app.run(host="0.0.0.0", port=5000, debug=False)

That server has NO authentication of any kind — no token, no session, no origin check.
Bound to all interfaces, any device on the LAN could POST /api/approve/<n> and approve
a self-modification proposal. The gate whose entire purpose is to make a human decide
was answering to whoever asked first.

Before narrowing it, who reaches it was checked rather than assumed: no uvicorn, ngrok,
cloudflared or tailscale anywhere in the repo; no code fetches :5000; no scheduled task
starts it; `memory/approval_queue.json` — the only thing it writes — is read by nobody
and last changed 13 Apr 2026. The human approval gate that IS live runs over Telegram
(memory/pending_approvals.json -> experiments/needs/approve_reader.py). Nothing
off-machine wanted this port, so it is now 127.0.0.1.

The second defect was in the same file and had nothing to do with the port. The
dashboard rendered proposals by interpolating their fields straight into innerHTML.
Those fields are composed by goal_planner and self_observer — by a model — so a
proposal containing markup executed inside the one page whose purpose is letting a
human judge that proposal before it runs.

WHY THESE ARE TESTS AND NOT A COMMIT MESSAGE
---------------------------------------------
Both defects are one token wide. `127.0.0.1` becomes `0.0.0.0` in a debugging session
that nobody reverts; `esc(p.problem)` becomes `p.problem` in a refactor that looks like
tidying. Neither leaves a trace at runtime — the server works identically either way,
right up until it doesn't.

WHAT THIS FILE DOES NOT DO
---------------------------
It reads source as text. It starts no server, opens no socket, touches no runtime
state, and — see test_esc_escapes_every_character_that_can_open_a_tag — it does NOT
execute the JavaScript. It proves the shape of the code, not the behaviour of a
browser. Those are different claims and only the first one is made here.

    venv\\Scripts\\python.exe -m pytest test/test_approval_server_is_closed.py -v
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "cortex_approval_server.py"


# ---------------------------------------------------------------------------
# (a) No service anywhere binds all interfaces
# ---------------------------------------------------------------------------

# Each pattern requires a BINDING CONTEXT, never a bare dotted quad. That is
# deliberate: this very file discusses 0.0.0.0 in prose, and a detector that fired on
# the string alone could not be written about. It must match the act, not the topic.
_ALL_INTERFACES = (
    # host="0.0.0.0" / host = '0.0.0.0'  (flask app.run, uvicorn.run, anything)
    re.compile(r"""host\s*=\s*["']0\.0\.0\.0["']"""),
    # host="" — the empty host is ALSO every interface, and reads as harmless
    re.compile(r"""host\s*=\s*["']["']"""),
    # positional: app.run("0.0.0.0", ...) / run('0.0.0.0')
    re.compile(r"""\.run\(\s*["']0\.0\.0\.0["']"""),
    # raw sockets: s.bind(("0.0.0.0", p)) and s.bind(("", p))
    re.compile(r"""\.bind\(\s*\(\s*["'](?:0\.0\.0\.0)?["']\s*,"""),
)


def _find_all_interface_binds(text: str, label: str = "<memory>") -> list[str]:
    """Return 'file:line: source' for every all-interfaces bind in `text`."""
    hits = []
    for n, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue                      # a comment cannot bind a socket
        for pat in _ALL_INTERFACES:
            if pat.search(line):
                hits.append(f"{label}:{n}: {line.strip()}")
                break
    return hits


def _tracked_python_files() -> list[Path]:
    """Git-tracked .py files. Tracked, not globbed: an untracked scratch file is not
    something this repo ships, and venv/ would otherwise drown the scan."""
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=str(REPO),
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        pytest.skip(f"git ls-files unavailable: {out.stderr.strip()[:200]}")
    files = [REPO / p for p in out.stdout.splitlines() if p.strip()]
    assert files, "git ls-files returned no .py files — the scan would pass on nothing"
    return files


def test_the_all_interfaces_detector_actually_detects():
    """POSITIVE CONTROL for (a). A scan that finds nothing proves nothing until the
    scanner is shown catching what it is for.

    The bad hosts are built by concatenation so the literal never appears in this file
    — otherwise this test would be the repo's only offender and (a) could never pass.
    """
    quad = "0.0.0." + "0"
    for bad in (f'app.run(host="{quad}", port=5000)',
                f"uvicorn.run(app, host='{quad}', port=8000)",
                f'sock.bind(("{quad}", 5000))',
                'srv.run(host="")',
                'sock.bind(("", 5000))'):
        assert _find_all_interface_binds(bad), f"detector MISSED a real bind: {bad!r}"

    for good in ('app.run(host="127.0.0.1", port=5000)',
                 "uvicorn.run(app, host='localhost')",
                 'sock.bind(("127.0.0.1", 5000))',
                 f'# on {quad} any device on the LAN could approve'):
        assert not _find_all_interface_binds(good), f"detector FALSE-POSITIVED on {good!r}"


def test_no_service_binds_all_interfaces():
    """No service in this repo may listen on every interface.

    THE STAKE: cortex_approval_server.py has no authentication of any kind. On
    0.0.0.0 any device on the LAN could POST /api/approve/<n> and approve a
    self-modification proposal — the system rewriting its own code with the human
    step satisfied by a stranger. The same is true of any future service that copies
    this shape, which is why the scan is repo-wide and not one file.
    """
    offenders = []
    for f in _tracked_python_files():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        offenders += _find_all_interface_binds(text, f.relative_to(REPO).as_posix())

    assert not offenders, (
        "These bind to ALL network interfaces:\n  " + "\n  ".join(offenders) +
        "\n\nBind to 127.0.0.1. If a service genuinely must be reachable off-machine, "
        "make it opt-in and closed by default:\n"
        '    host = os.getenv("<NAME>_HOST", "127.0.0.1")\n'
        "and give it authentication before you open it — cortex_approval_server.py "
        "has none.")


# ---------------------------------------------------------------------------
# (b) Every model-written field reaches innerHTML escaped
# ---------------------------------------------------------------------------

def _render_block(src: str) -> str:
    """The innerHTML template that renders proposals."""
    start = src.find("list.innerHTML = proposals.map(")
    assert start != -1, (
        "could not find the proposals innerHTML template in cortex_approval_server.py "
        "— it was renamed or restructured. This test is now blind; fix the anchor "
        "before trusting a green run.")
    end = src.find(".join('')", start)
    assert end != -1, "found the map( but not its .join('') — anchor is stale"
    return src[start:end]


def _interpolations(block: str) -> list[str]:
    """Every ${...} in the block, at EVERY nesting depth, brace-balanced.

    Depth matters: the solution field sits inside a ternary inside the outer template,
    and a scanner that stopped at depth 1 would never look at it.
    """
    out, i = [], 0
    while (k := block.find("${", i)) != -1:
        depth, j = 1, k + 2
        while j < len(block) and depth:
            if block[j] == "{":
                depth += 1
            elif block[j] == "}":
                depth -= 1
            j += 1
        out.append(block[k + 2: j - 1])
        i = k + 2          # step INSIDE, so nested interpolations are found too
    return out


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_NESTED = re.compile(r"\$\{[^}]*\}")
_FIELD = re.compile(r"\bp\.\w+")


def _unsafe_interpolations(block: str) -> list[str]:
    """Interpolations that put a model-written value into HTML unescaped.

    Three shapes are safe, and only three:
      esc(...)        the value is escaped
      i               the Number()-coerced index, an int from enumerate()
      p.field ? A : B the field is a TRUTHINESS GUARD — it is tested, never emitted.
                      Its branches are still checked: `${p.a ? p.b : ''}` emits p.b
                      raw and must fail.
    """
    unsafe = []
    for expr in _interpolations(block):
        e = expr.strip()
        if e == "i" or e.startswith("esc("):
            continue
        if re.match(r"^p\.\w+\s*\?", e):                 # guard — check its branches
            rest = e.split("?", 1)[1]
            rest = _NESTED.sub("", rest)                 # nested ${} checked separately
            rest = _QUOTED.sub("", rest)
            if not _FIELD.search(rest):
                continue
        unsafe.append(e)
    return unsafe


def test_the_escaping_detector_actually_detects():
    """POSITIVE CONTROL for (b): feed it the exact pattern that shipped, and the
    subtler one where a field hides in a ternary branch."""
    bare = ("list.innerHTML = proposals.map(p => {\n"
            "  return `<div>${p.problem}</div>`;\n"
            "}).join('')")
    assert _unsafe_interpolations(_render_block(bare)) == ["p.problem"], \
        "detector missed a bare ${p.problem} — the exact bug that shipped"

    branch = ("list.innerHTML = proposals.map(p => {\n"
              "  return `<div>${p.solution ? p.problem : ''}</div>`;\n"
              "}).join('')")
    assert _unsafe_interpolations(_render_block(branch)), \
        "detector treated a ternary as safe without checking what its branches emit"

    ok = ("list.innerHTML = proposals.map(p => {\n"
          "  const i = Number(p.index);\n"
          "  return `<div id=\"x-${i}\">${esc(p.problem)}"
          "${p.solution ? `<b>${esc(p.solution)}</b>` : ''}</div>`;\n"
          "}).join('')")
    assert _unsafe_interpolations(_render_block(ok)) == [], \
        "detector false-positived on correctly escaped source"


def test_every_llm_written_field_reaches_innerhtml_escaped():
    """Proposal fields are written by a model; they must not reach innerHTML raw.

    THE STAKE: component, priority, problem and solution are composed by
    goal_planner and self_observer — by an LLM — into
    memory/improvement_proposals.json. This is the page where a human judges that
    model's proposal BEFORE it runs. A proposal carrying markup that executes in the
    reviewing page can rewrite what the reviewer sees, or act as the reviewer.

    The model does not have to be adversarial for this to matter. It only has to
    quote a snippet of HTML in a field describing an HTML bug.
    """
    unsafe = _unsafe_interpolations(_render_block(
        SERVER.read_text(encoding="utf-8", errors="replace")))

    assert not unsafe, (
        "These interpolations put a model-written value into innerHTML unescaped:\n  "
        + "\n  ".join(unsafe)
        + "\n\nWrap each in esc(). The index may be interpolated bare ONLY as the "
          "Number()-coerced `i`.")


# ---------------------------------------------------------------------------
# (c) esc() covers every character that can open a tag or break an attribute
# ---------------------------------------------------------------------------

def test_esc_escapes_every_character_that_can_open_a_tag():
    """The esc() replacement map must cover & < > " and '.

    THIS TEST IS STRUCTURAL. It reads the source of esc() as text and checks which
    characters appear in its character class and in its replacement map. It does NOT
    execute the JavaScript — there is no JS engine in this suite — so it cannot prove
    that esc() escapes correctly at runtime, only that no character was dropped from
    the two places a character gets dropped from.

    That limit is the point of saying it out loud: a green run here means "the map is
    complete", not "the page is safe". Proving the second needs a browser.

    Why all five and not just < >: ' and " break out of an attribute value
    (id="prop-…", style="…"), and & unescaped lets an entity reconstitute the others.
    Escaping four of five is the same as escaping none.
    """
    src = SERVER.read_text(encoding="utf-8", errors="replace")

    m = re.search(r"function esc\(v\)\s*\{(.*?)\n\}", src, re.S)
    assert m, ("esc() is gone from cortex_approval_server.py — if it was renamed, "
               "re-anchor this test; if it was removed, "
               "test_every_llm_written_field_reaches_innerhtml_escaped is now the "
               "only thing standing between a model's markup and the reviewer.")
    body = m.group(1)

    cls = re.search(r"replace\(\s*/\[([^\]]*)\]/g", body)
    assert cls, "esc() no longer replaces on a character class — cannot verify coverage"

    missing_from_class = [c for c in "&<>\"'" if c not in cls.group(1)]
    assert not missing_from_class, (
        f"esc()'s character class {cls.group(1)!r} does not match: {missing_from_class} "
        f"— those characters pass through unescaped.")

    missing_from_map = [c for c in "&<>\"'" if f"'{c}':" not in body
                        and f'"{c}":' not in body]
    assert not missing_from_map, (
        f"esc()'s replacement map has no entry for {missing_from_map} — the class "
        f"matches them, so they map to undefined and the value is corrupted.")
