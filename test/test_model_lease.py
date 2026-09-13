#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_model_lease.py — the loan has an end date and an owner.

THE FINDING OF 13 SEPTEMBER 2026, and it is the one worth remembering: the pin
survives the death of the cycle. /api/ps showed qwen2.5:3b with
`expires 2318-12-24` — two hundred and ninety-two years — holding 1139 MB of
system RSS and 2208 MB of VRAM. Three cycles died that day and each left the hold
behind, so the next cycle started in memory the dead had not released. The 09:34
catch-up began with 138 MB free, and over a gigabyte of what was missing was held
by a corpse.

WHAT IS NOT CHANGED. keep_alive outside the window still holds the small model
resident, because the load/unload alternation model_window exists to stop is real
and was measured. A living cycle beats, a beat renews, so the hold is continuous
for as long as anything is using it.

TWO MECHANISMS, because one is not enough. The lease covers an unattended machine
on the scale of an hour. The supervisor's release after CYCLE_DIED covers the
night: today's collapse took fifteen minutes from the first death to an exhausted
budget, and a seventy-minute lease would have slept through all of it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import model_window as mw          # noqa: E402


# ── the lease is derived, never typed ────────────────────────────────────────

def test_the_lease_comes_from_scheduler_json_and_follows_it(tmp_path):
    """A ceiling raised by a human must move the lease without anyone
    remembering to. The number is not allowed to live in two places."""
    cfg = tmp_path / "scheduler.json"
    cfg.write_text(json.dumps({"step_ceilings_sec": {"_default": 900, "slow": 7200}}),
                   encoding="utf-8")
    assert mw.lease_seconds(cfg) == 7200 + mw.LEASE_MARGIN_SEC


def test_the_lease_outlasts_the_longest_ceiling_the_repo_actually_has():
    """Otherwise it expires in the middle of honest work. The longest a step may
    go without beating IS the largest per-step ceiling."""
    ceilings = json.loads((REPO / "config" / "scheduler.json").read_text("utf-8"))
    biggest = max(int(v) for v in ceilings["step_ceilings_sec"].values())
    assert mw.lease_seconds() > biggest, (
        f"lease {mw.lease_seconds()}s does not outlast the {biggest}s ceiling")
    assert mw.lease_seconds() == biggest + mw.LEASE_MARGIN_SEC


def test_an_unreadable_config_falls_back_to_a_stated_number(tmp_path):
    missing = tmp_path / "not_here.json"
    assert mw.lease_seconds(missing) == mw.LEASE_FALLBACK_SEC
    assert mw.LEASE_FALLBACK_SEC > 3600


# ── pin_small no longer asks for eternity ────────────────────────────────────

def test_pin_small_sends_the_lease_and_not_forever(monkeypatch):
    sent = {}
    monkeypatch.setattr(mw, "_set_keep_alive",
                        lambda model, ka, url=None: sent.update(model=model, ka=ka) or True)
    mw.pin_small()
    assert sent["ka"] == mw.lease_seconds()
    assert sent["ka"] != mw.FOREVER, (
        "the pin still asks for eternity; a hold nobody owns outlives its owner")
    assert sent["ka"] > 0


def test_a_caller_may_still_name_its_own_term(monkeypatch):
    sent = {}
    monkeypatch.setattr(mw, "_set_keep_alive",
                        lambda model, ka, url=None: sent.update(ka=ka) or True)
    mw.pin_small(seconds=123)
    assert sent["ka"] == 123


# ── renewal: by the living, and throttled ────────────────────────────────────

def test_renewal_is_throttled(monkeypatch):
    calls = []
    monkeypatch.setattr(mw, "_set_keep_alive",
                        lambda model, ka, url=None: calls.append(ka) or True)
    monkeypatch.setattr(mw, "_LAST_RENEWAL", 0.0, raising=False)
    assert mw.renew_small(min_gap_sec=300) is True
    assert mw.renew_small(min_gap_sec=300) is False, (
        "beat() runs 75 times a night; an HTTP round trip on each is paid for nothing")
    assert len(calls) == 1


def test_renewal_never_raises(monkeypatch):
    def _boom(*a, **k):
        raise OSError("ollama is not there")
    monkeypatch.setattr(mw, "_set_keep_alive", _boom)
    monkeypatch.setattr(mw, "_LAST_RENEWAL", 0.0, raising=False)
    assert mw.renew_small(min_gap_sec=0) is False


def test_the_heartbeat_is_what_renews_it():
    """Structural: beat() is the one gate all 75 steps pass, which is why the
    renewal hangs there. If it moves, a step that does not beat stops paying."""
    import ast
    src = (REPO / "memory" / "heartbeat.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "beat")
    names = {getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
             for sub in ast.walk(fn) if isinstance(sub, ast.Call)}
    assert "_renew" in names or "renew_small" in names, (
        "beat() no longer renews the lease; a live cycle would lose its model")


# ── the supervisor cleans up after the corpse, in the right order ────────────

def test_the_supervisor_releases_the_hold_when_it_records_a_death(monkeypatch):
    import supervisor as sup
    released = []
    monkeypatch.setattr("core.aggressive_cleanup.release_ollama",
                        lambda **k: released.append(k) or {"released": ["qwen2.5:3b"],
                                                           "ram_free_mb_before": 138.0,
                                                           "ram_free_mb_after": 1290.0})
    rec = sup._release_after_death("some-cycle")
    assert released and released[0].get("apply") is True
    assert rec["released"] == ["qwen2.5:3b"]


def test_the_release_never_raises_and_says_so(monkeypatch):
    import supervisor as sup
    def _boom(**k):
        raise RuntimeError("no ollama")
    monkeypatch.setattr("core.aggressive_cleanup.release_ollama", _boom)
    rec = sup._release_after_death("x")
    assert "error" in rec


def test_the_death_path_calls_it_before_anything_reads_memory():
    """Structural, and it is the ordering the whole fix turns on: the release must
    sit in the branch that records the death, so the NEXT tick's memory check sees
    freed memory. Otherwise the guard refuses to spawn because of memory a corpse
    is holding."""
    import ast
    src = (REPO / "supervisor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "tick")
    calls = [sub for sub in ast.walk(fn) if isinstance(sub, ast.Call)]
    names = [getattr(c.func, "id", None) or getattr(c.func, "attr", None) for c in calls]
    assert "_release_after_death" in names, "tick() never releases after a death"
    order = {n: i for i, n in enumerate(names) if n}
    assert order.get("record_death", 0) < order["_release_after_death"], (
        "the release must follow the death record, not precede it")
