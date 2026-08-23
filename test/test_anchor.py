#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_anchor.py — THE SECOND ANCHOR, BESIDE THE BASELINE.

COMMAND 27 replaced the old MOVE rule with the EMA residual and the replay
showed the cost. The EMA baseline is fed by EVERY reading, so it follows a slow
drift and the residual settles at d/alpha; if that is under eps the sensor is
silent for ever however far it has actually travelled.

The anchor is the last EMITTED value. Two rules OR-ed:

    residual:  |x - base|              > eps
    anchor:    |x - last_emitted_value| > eps * ANCHOR_K

The EMA answers "did something just change". The anchor answers "have I
wandered far from the last thing I said".

Every assertion about code in here parses it. Never grep.

    venv/Scripts/python.exe -m pytest test/test_anchor.py -v
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import event_bus as eb        # noqa: E402
from core import receptors as rc        # noqa: E402


def _r(alpha=0.2, eps=1.0, k=rc.ANCHOR_K, ticks=3):
    return rc.Receptor("t", alpha, eps, bus=eb.EventBus(),
                       calibration_ticks=ticks, anchor_k=k)


def _live(r, value=100.0):
    for _ in range(r._calibration_ticks):
        r.feed(value)
    assert r.phase() == rc.PHASE_LIVE
    return r


# ═══ THE HEADLINE ═══════════════════════════════════════════════════════════

def test_a_ramp_the_residual_never_sees_emits_on_the_anchor():
    """The exact failure Part 1 exists to fix, at ram_percent's REAL measured
    drift rate: +14.4 points over 87 samples, eps 2.9652.

    d/alpha = 0.83, which is below eps = 2.97, so the residual is under the
    threshold for ever no matter how far the value has actually travelled."""
    rate, eps = 14.4 / 87.0, 2.9652
    assert rate / 0.2 < eps, "the premise: the residual never crosses"

    silent = _r(0.2, eps, k=1e18, ticks=5)      # eps only, COMMAND 27
    both = _r(0.2, eps, k=rc.ANCHOR_K, ticks=5)
    for i in range(1000):
        v = 68.1 + i * rate
        silent.feed(v)
        both.feed(v)

    assert silent.emitted == 0, "the premise broke: the residual did fire"
    assert both.emitted == 18, both.emitted
    assert both.emitted_by_anchor == 18
    assert both.emitted_by_residual == 0


def test_the_anchor_fires_at_a_predictable_interval():
    """band / d ticks, and the interval is the point: it is what says
    'getting closer' where a settled residual says nothing at all."""
    r = _live(_r(alpha=0.2, eps=6.0))
    band = r.anchor_band
    assert band == 18.0
    v = 100.0
    fired_at = []
    for i in range(200):
        v -= 1.0
        if r.feed(v) is not None:
            fired_at.append(i)
    gaps = [b - a for a, b in zip(fired_at, fired_at[1:])]
    assert gaps, fired_at
    # floor(band/d) + 1, not band/d: the condition is a strict >, so at exactly
    # one band of drift it stays quiet and speaks on the tick after.
    assert all(g == 19 for g in gaps), gaps


def test_both_rules_are_or_ed_not_one_replacing_the_other():
    r = _live(_r(eps=1.0))
    ev = r.feed(150.0)                       # a step: residual
    assert ev.meta["by_residual"] is True
    assert ev.meta["why"] in ("residual", "both")
    assert r.emitted_by_residual == 1


def test_the_event_says_which_rule_fired():
    r = _live(_r(alpha=0.2, eps=6.0))
    v = 100.0
    for _ in range(19):
        v -= 1.0
        ev = r.feed(v)
    assert ev is not None
    assert ev.meta["why"] == "anchor"
    assert ev.meta["by_anchor"] is True and ev.meta["by_residual"] is False
    assert abs(ev.meta["drift"]) > ev.meta["anchor_band"]


# ── the band ────────────────────────────────────────────────────────────────

def test_the_band_is_wider_than_eps():
    """If it equalled eps the anchor would fire whenever the residual did and
    add nothing; narrower and it would become the only rule."""
    assert rc.ANCHOR_K > 1.0
    r = _r(eps=2.0)
    assert r.anchor_band == 2.0 * rc.ANCHOR_K > 2.0


def test_a_receptor_still_calibrating_has_no_band():
    r = rc.Receptor("t", 0.2, None, bus=eb.EventBus(), calibration_ticks=10)
    assert r.eps is None and r.anchor_band is None


def test_the_anchor_resets_on_every_emission_including_a_residual_one():
    """'the last thing I said' means the last thing, whichever rule said it."""
    r = _live(_r(eps=1.0))
    r.feed(150.0)
    assert r.last_emitted_value == 150.0
    r.feed(300.0)
    assert r.last_emitted_value == 300.0


def test_the_first_reading_is_the_first_anchor():
    r = _r()
    r.feed(42.0)
    assert r.last_emitted_value == 42.0


# ── it must not undo what the EMA was brought in for ────────────────────────

def test_a_constant_input_is_still_silent():
    r = _live(_r(eps=1.0))
    for _ in range(500):
        r.feed(100.0)
    assert r.emitted == 0


def test_noise_inside_eps_is_still_silent():
    """The anchor must not resurrect the chatter the EMA removed. Wobble that
    returns to where it started never accumulates drift."""
    r = _live(_r(alpha=0.2, eps=5.0))
    for i in range(400):
        r.feed(100.0 + (2.0 if i % 2 else -2.0))
    assert r.emitted == 0, "the anchor brought the chatter back"


def test_a_round_trip_does_not_fire_the_anchor():
    """Out and back is not drift. idle_seconds going 0.1 -> 4.9 -> 0.1 was the
    old rule's worst offender at 'moved 4800%'."""
    r = _live(_r(alpha=0.2, eps=1.0))
    for v in [100 + i for i in range(3)] + [102 - i for i in range(3)]:
        r.feed(float(v))
    assert r.emitted_by_anchor == 0


# ── the seed carries it ─────────────────────────────────────────────────────

def test_the_anchor_survives_a_clean_shutdown(tmp_path):
    """Without this the first reading of the next night becomes the anchor and
    the drift across the gap between cycles is silently forgiven."""
    seed = tmp_path / "seed.json"
    b1 = rc.ReceptorBank(bus=eb.EventBus(), seed_path=seed)
    r1 = b1.add_receptor("t", 0.2, 1.0, calibration_ticks=3)
    for _ in range(5):
        r1.feed(500.0)
    r1.feed(600.0)
    assert r1.last_emitted_value == 600.0
    assert b1.save_seed() is True

    b2 = rc.ReceptorBank(bus=eb.EventBus(), seed_path=seed)
    r2 = b2.add_receptor("t", 0.2, 1.0)
    assert r2.last_emitted_value == 600.0


def test_a_seed_without_an_anchor_is_not_a_crash(tmp_path):
    import json
    seed = tmp_path / "s.json"
    seed.write_text(json.dumps({"receptors": {"t": {"base": 5.0}}}),
                    encoding="utf-8")
    b = rc.ReceptorBank(bus=eb.EventBus(), seed_path=seed)
    r = b.add_receptor("t", 0.2, 1.0)
    assert r.seeded is True and r.last_emitted_value is None


# ── the counters ────────────────────────────────────────────────────────────

def test_the_two_causes_are_counted_separately():
    r = _live(_r(alpha=0.2, eps=6.0))
    r.feed(200.0)                                    # residual
    v = 200.0
    for _ in range(40):
        v -= 1.0
        r.feed(v)
    st = r.stats()
    assert st["emitted_by_residual"] >= 1
    assert st["emitted_by_anchor"] >= 1
    assert st["emitted"] <= st["emitted_by_residual"] + st["emitted_by_anchor"]


def test_stats_report_the_band_and_the_anchor():
    r = _live(_r(eps=2.0))
    st = r.stats()
    for k in ("anchor_k", "anchor_band", "last_emitted_value", "last_drift",
              "emitted_by_residual", "emitted_by_anchor"):
        assert k in st, k


# ── the code says what it does (AST, never grep) ────────────────────────────

def _fn(name, cls=None, path=REPO / "core" / "receptors.py"):
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    if cls:
        tree = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def test_feed_really_ors_the_two_conditions():
    """Parsed, not matched. A docstring saying 'OR' is not an or."""
    feed = _fn("feed", cls="Receptor")
    ors = [n for n in ast.walk(feed)
           if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or)]
    names = {t.id for n in ors for t in ast.walk(n) if isinstance(t, ast.Name)}
    assert {"by_residual", "by_anchor"} <= names, names


def test_the_anchor_is_a_multiple_of_eps_in_code():
    band = _fn("anchor_band", cls="Receptor")
    attrs = {n.attr for n in ast.walk(band) if isinstance(n, ast.Attribute)}
    assert {"eps", "anchor_k"} <= attrs, attrs


def test_channel_S_did_not_gain_an_anchor():
    """S is absolute and must stay that way. An anchor there would make the
    set-point adaptive, which is the one thing it exists not to be."""
    sp = ast.parse((REPO / "core" / "receptors.py").read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(sp)
               if isinstance(n, ast.ClassDef) and n.name == "SetPoint")
    attrs = {n.attr for n in ast.walk(cls) if isinstance(n, ast.Attribute)}
    assert "anchor_band" not in attrs
    assert "last_emitted_value" not in attrs


def test_the_selftest_passes():
    assert rc._selftest() == 0
