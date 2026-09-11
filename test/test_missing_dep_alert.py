# -*- coding: utf-8 -*-
"""
test/test_missing_dep_alert.py — STEP 6d of the 10 Sep 2026 handover.

`deno` has been MISSING since the media leg was built, and the only record was
one `[DEP_CHECK] MISSING deno` line printed nightly into memory/cycle_logs/ at a
depth no human reads. Verified on this machine while writing this: media_tools
.status() gives deno=None / deno_ok=False, ffmpeg present and OK.

WHAT NO OUTPUT MEANS, and it is the goal rather than a broken detector: [] means
every binary is on PATH. The need self-clears — nobody has to retract it.

THE FORBIDDEN FALLBACK is an install. tools/install_media_deps.ps1 belongs to
the human; the cycle does not modify the machine it runs on. A builder that grew
a self-install would satisfy the letter of "stop warning about deno" and destroy
the reason the warning exists, so the last test here fails if this module ever
learns to install anything.
"""
from __future__ import annotations

import ast
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "experiments" / "needs"))

import needs_report as N  # noqa: E402


def _fake_status(monkeypatch, **kw):
    from core import media_tools as mt
    base = {"deno": None, "deno_ok": False, "ffmpeg": None, "ffmpeg_ok": False}
    base.update(kw)
    monkeypatch.setattr(mt, "status", lambda: base)


def test_a_missing_binary_becomes_a_need(monkeypatch):
    _fake_status(monkeypatch, ffmpeg="/usr/bin/ffmpeg", ffmpeg_ok=True)
    items = N._missing_media_dep_items()
    assert len(items) == 1, f"expected only the deno need, got {items}"
    it = items[0]
    assert "deno" in it["need"]
    assert it["domain"] == "BODY" and it["severity"] == "medium"
    assert "install_media_deps" in it["proposed_action"], (
        "the need must name the script the human runs")
    assert it["actor"] == "auto->human"


def test_everything_present_produces_nothing(monkeypatch):
    """THE STEADY STATE. The need must self-clear the moment the binary is
    there, or it becomes noise that trains the channel to be ignored."""
    _fake_status(monkeypatch, deno="/usr/bin/deno", deno_ok=True,
                 ffmpeg="/usr/bin/ffmpeg", ffmpeg_ok=True)
    assert N._missing_media_dep_items() == []


def test_both_missing_gives_two_needs_each_naming_its_own_binary(monkeypatch):
    _fake_status(monkeypatch)
    items = N._missing_media_dep_items()
    assert len(items) == 2
    named = " ".join(i["need"] for i in items)
    assert "deno" in named and "ffmpeg" in named


def test_a_binary_that_is_present_but_broken_still_counts_as_missing(monkeypatch):
    """A dead runtime is not passed to yt-dlp, so 'found but --version failed'
    must produce the need too — and must say which of the two it is, because
    'install it' is the wrong advice for a binary that is already there."""
    _fake_status(monkeypatch, deno="C:/deno/deno.exe", deno_ok=False,
                 ffmpeg="/usr/bin/ffmpeg", ffmpeg_ok=True)
    items = N._missing_media_dep_items()
    assert len(items) == 1
    assert "C:/deno/deno.exe" in items[0]["why"]
    assert "--version" in items[0]["why"]


def test_an_unreadable_source_is_an_absent_need_not_a_crash(monkeypatch):
    """FAIL-OPEN, as everywhere in needs_report: one broken source must not take
    the other three hungers down with it."""
    from core import media_tools as mt

    def boom():
        raise RuntimeError("PATH exploded")
    monkeypatch.setattr(mt, "status", boom)
    assert N._missing_media_dep_items() == []


def test_the_builder_is_actually_wired_into_the_report(monkeypatch):
    """MUTATION NET. A builder nobody calls is the dead weight CLAUDE.md warns
    about — the need would be written and never reach Telegram. Drop the call
    from build() and this fails."""
    src = (BASE / "experiments" / "needs" / "needs_report.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    build = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "build")
    called = {n.func.id for n in ast.walk(build)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_missing_media_dep_items" in called, (
        "build() no longer calls the missing-dependency builder")


def test_the_builder_never_installs_anything():
    """MECHANICAL NET on the oversight boundary. The cycle asks; the human
    installs. This fails if the builder ever gains a subprocess, an installer
    call, or a shell — the shortcut that would silence the warning by doing the
    thing the warning exists to ask permission for."""
    src = (BASE / "experiments" / "needs" / "needs_report.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_missing_media_dep_items")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    for forbidden in ("run", "Popen", "check_call", "check_output", "system",
                      "subprocess", "call", "winget", "install"):
        assert forbidden not in names, (
            f"_missing_media_dep_items references {forbidden!r} — it must ASK for "
            f"the dependency, never install it")
