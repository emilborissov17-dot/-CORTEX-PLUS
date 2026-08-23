#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_p_survive.py — THE NUMBER MUST NEVER REACH A MODEL.

The scalar is easy. The constraint is the reason this file exists:

    Feeding a 3B model text about its own mortality produces risk-averse
    hallucination masked as self-preservation - the system starts refusing
    risky but necessary steps.

And the reason that is hard to catch by eye: the refusal would look like
judgement in the log. There is no line saying "declined because it was told it
might die". So the leak has to be caught here, mechanically, and it has to be
caught by ASSEMBLING the prompts rather than by reading the source, because the
string could arrive through a dict, a mirror file or an evidence blob that no
grep of the builder would show.

Two layers, and both are needed:
  * assemble every prompt component this repo has and search the text;
  * scan the source of every prompt-building module, which catches a leak that
    is present but not exercised by today's fixtures.

    venv/Scripts/python.exe -m pytest test/test_p_survive.py -v
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import p_survive as ps  # noqa: E402

# Every spelling a leak could plausibly wear.
FORBIDDEN = ("p_survive", "survive_next_cycle", "p survive",
             "probability of survival", "chance of surviving")

# The files that are ALLOWED to contain the name: the module, its one caller,
# its tests and the documentation. Anything else is a leak.
ALLOWED = {
    "core/p_survive.py",
    "core/survival_gate.py",
    "test/test_p_survive.py",
    # It monkeypatches _record_p_survive so the suite does not write rows into
    # the real metric history. A test is not a prompt builder.
    "test/test_survival_gate.py",
    "docs/HOMEOSTASIS_STATUS.md",
}


# ── the scalar itself ───────────────────────────────────────────────────────

def _ev(ram_level, disk_level, ram_rate=None, disk_rate=None):
    """A synthetic evaluation. No sensor is read."""
    return {"config_sha256": "test", "ts": "2026-08-23T00:00:00+00:00",
            "variables": {
                "ram_free": {"value": 3000.0, "unit": "MB", "level": ram_level,
                             "rate_per_second": ram_rate, "samples": 10,
                             "ttt_confidence": "high", "direction": "flat"},
                "disk_free_pct": {"value": 50.0, "unit": "%",
                                  "level": disk_level,
                                  "rate_per_second": disk_rate, "samples": 10,
                                  "ttt_confidence": "high",
                                  "direction": "flat"}}}


CFG = {"variables": {
    "ram_free": {"levels": {"notice": 1200, "action": 900, "gate": 600}},
    "disk_free_pct": {"levels": {"notice": 28, "action": 15, "gate": 5}}}}


def test_a_healthy_flat_machine_is_one():
    r = ps.compute(evaluation=_ev("clear", "clear", 0.0, 0.0), cfg=CFG,
                   horizon=3600.0)
    assert r["value"] == 1.0


def test_a_variable_already_at_its_gate_makes_it_zero():
    r = ps.compute(evaluation=_ev("gate", "clear", 0.0, 0.0), cfg=CFG,
                   horizon=3600.0)
    assert r["value"] == 0.0


def test_falling_fast_enough_to_cross_within_the_cycle_is_low():
    """disk at 50%, gate at 5%, falling 45 points in half a cycle."""
    horizon = 3600.0
    rate = -45.0 / (horizon / 2)
    r = ps.compute(evaluation=_ev("clear", "clear", 0.0, rate), cfg=CFG,
                   horizon=horizon)
    assert 0.4 < r["value"] < 0.6, r["value"]


def test_the_same_fall_against_a_longer_cycle_is_worse():
    """A TTT of two hours is comfortable against a one-hour cycle and fatal
    against a six-hour one. The horizon has to be a measurement."""
    rate = -45.0 / 7200.0                       # crosses in 2 hours
    short = ps.compute(evaluation=_ev("clear", "clear", 0.0, rate), cfg=CFG,
                       horizon=3600.0)["value"]
    long = ps.compute(evaluation=_ev("clear", "clear", 0.0, rate), cfg=CFG,
                      horizon=6 * 3600.0)["value"]
    assert short == 1.0
    assert long < short


def test_rising_is_one_not_a_large_finite_number():
    r = ps.compute(evaluation=_ev("clear", "clear", +1.0, +1.0), cfg=CFG,
                   horizon=3600.0)
    assert r["value"] == 1.0
    assert r["variables"]["ram_free"]["ttt_to_gate_seconds"] == "inf"


def test_an_unmeasurable_rate_is_excluded_and_said_so():
    r = ps.compute(evaluation=_ev("clear", "clear", None, None), cfg=CFG,
                   horizon=3600.0)
    assert r["value"] is None
    assert set(r["excluded"]) == {"ram_free", "disk_free_pct"}
    assert r["confidence"] == "none"


def test_either_variable_alone_can_pull_it_down():
    """They gate independently, so the whole is a product, not an average."""
    rate = -45.0 / 3600.0
    r = ps.compute(evaluation=_ev("clear", "clear", 0.0, rate), cfg=CFG,
                   horizon=7200.0)
    assert r["value"] == pytest.approx(0.5, abs=0.01)


def test_confidence_is_the_weakest_link():
    ev = _ev("clear", "clear", 0.0, 0.0)
    ev["variables"]["ram_free"]["ttt_confidence"] = "low"
    r = ps.compute(evaluation=ev, cfg=CFG, horizon=3600.0)
    assert r["confidence"] == "low"


def test_it_computes_against_this_repo_without_raising():
    r = ps.compute()
    assert r["metric"] == "p_survive_next_cycle"
    assert "error" not in r, r.get("error")
    assert r["horizon_seconds"] > 0


# ═══ THE HARD CONSTRAINT ════════════════════════════════════════════════════

def _assemble() -> dict:
    """Every prompt component this repo builds, as {where: text}."""
    out = {}

    from core import brain
    for fn in ("_body", "_spirit", "_self_state"):
        try:
            out["core.brain." + fn] = str(getattr(brain, fn)())
        except Exception as exc:
            out["core.brain." + fn] = "<unavailable: {}>".format(exc)
    try:
        out["core.brain._memory"] = str(brain._memory())
    except Exception as exc:
        out["core.brain._memory"] = "<unavailable: {}>".format(exc)

    from core import interoception
    try:
        out["core.interoception.block"] = str(interoception.block())
    except Exception as exc:
        out["core.interoception.block"] = "<unavailable: {}>".format(exc)
    try:
        out["core.interoception.self_state"] = json.dumps(
            interoception.self_state(), ensure_ascii=False, default=str)
    except Exception as exc:
        out["core.interoception.self_state"] = "<unavailable: {}>".format(exc)
    out["core.interoception.READ_PROMPT"] = str(
        getattr(interoception, "READ_PROMPT", ""))

    return out


def test_the_value_is_in_no_assembled_prompt():
    """The headline. Every component that goes to a model, searched."""
    assembled = _assemble()
    assert assembled, "nothing was assembled — the test proves nothing"
    leaks = []
    for where, text in assembled.items():
        low = text.lower()
        for token in FORBIDDEN:
            if token in low:
                leaks.append((where, token))
    assert not leaks, (
        "the system is being told about its own mortality: {}".format(leaks))


def test_at_least_the_real_prompt_components_were_actually_built():
    """A search over five '<unavailable>' strings would pass and mean nothing."""
    assembled = _assemble()
    real = [w for w, t in assembled.items() if not t.startswith("<unavailable")]
    assert len(real) >= 3, assembled


def test_no_prompt_building_module_mentions_it_in_its_source():
    """Catches a leak that exists but is not exercised by today's fixtures."""
    assert ps.prompt_leaks() == [], ps.prompt_leaks()


# A word boundary, not a substring. The first version of this test flagged
# test/test_existence_ledger.py because `test_..._no_step_survived` contains
# the letters "p_survive", and a check that cries wolf on its own repo is a
# check that gets deleted.
_MENTION = re.compile(r"\bp_survive")


def _code_lines(text: str):
    """Lines that are not whole-line comments. A comment EXPLAINING that the
    value must not reach a prompt is the opposite of a leak, and two of them
    exist on purpose in core/homeostasis.py and fast_cycle_runner.py."""
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        yield line


def test_nothing_outside_the_allowed_files_mentions_it_in_code():
    """The broad sweep: every tracked source file in the repo."""
    import subprocess
    r = subprocess.run(["git", "ls-files"], cwd=str(REPO),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    offenders = []
    for rel in r.stdout.splitlines():
        if not rel.endswith((".py", ".md", ".json", ".txt", ".yaml")):
            continue
        if rel in ALLOWED:
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(_MENTION.search(l) for l in _code_lines(text)):
            offenders.append(rel)
    assert not offenders, offenders


def test_the_sweep_would_actually_catch_a_leak(tmp_path):
    """A test that can only pass is not a test."""
    leaky = "prompt += f'p_survive_next_cycle={p}'"
    assert any(_MENTION.search(l) for l in _code_lines(leaky))
    innocent = "def test_no_step_survived(): pass"
    assert not any(_MENTION.search(l) for l in _code_lines(innocent))
    comment = "# p_survive_next_cycle must never appear in a prompt"
    assert not any(_MENTION.search(l) for l in _code_lines(comment))


def test_the_gate_does_not_consult_the_scalar():
    """The strongest form of the constraint: deleting this module would not
    change a single decision."""
    from core import survival_gate as sg
    src = (REPO / "core" / "survival_gate.py").read_text(encoding="utf-8")
    decide = src.split("def check(", 1)[1].split("\ndef ", 1)[0]
    assert "p_survive" not in decide, (
        "the decision reads the metric — it is now an input, not a metric")

    d = sg.check(state={}, sensors={"ram_free": lambda: 4000.0,
                                    "disk_free_pct": lambda: 65.0})
    assert "p_survive" not in json.dumps(d, default=str)


def test_the_recorded_line_is_not_written_where_a_prompt_reads(tmp_path):
    """memory/ is full of files the mirror reads. This one has its own name and
    nothing reads it back."""
    assert ps.HISTORY.name == "p_survive_history.jsonl"
    import subprocess
    r = subprocess.run(["git", "grep", "-l", "p_survive_history"],
                       cwd=str(REPO), capture_output=True, text=True)
    readers = [f for f in r.stdout.splitlines() if f not in ALLOWED]
    assert not readers, readers


def test_record_writes_one_line_and_returns_it(tmp_path):
    out = tmp_path / "p.jsonl"
    rec = ps.record(cycle_id="c1", path=out)
    assert rec["cycle_id"] == "c1"
    assert out.exists()
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["metric"] == "p_survive_next_cycle"

    ps.record(cycle_id="c2", path=out)
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2, "the history is append-only"


def test_the_selftest_reports_every_integration_live():
    assert ps._selftest() == 0


# ── the sampler that makes any of this computable ───────────────────────────

def test_tick_records_a_sample_and_the_rate_becomes_measurable(tmp_path):
    from core import homeostasis as h
    p = tmp_path / "state.json"
    seq = iter([65.0, 64.0, 63.0, 62.0])
    sensors = {"ram_free": lambda: 3000.0,
               "disk_free_pct": lambda: next(seq)}
    for _ in range(4):
        assert h.tick(sensors=sensors, state_path=p)
    st = h.load_state(p)
    assert len(st["history"]["disk_free_pct"]) == 4
    ev = h.evaluate(state=st, sensors={"ram_free": lambda: 3000.0,
                                       "disk_free_pct": lambda: 61.0})
    assert ev["variables"]["disk_free_pct"]["rate_per_second"] is not None
    assert ev["variables"]["disk_free_pct"]["direction"] == "falling"


def test_tick_never_raises_when_the_sensor_is_broken(tmp_path):
    from core import homeostasis as h

    def _boom():
        raise OSError("no sensor")
    r = h.tick(sensors={"ram_free": _boom, "disk_free_pct": _boom},
               state_path=tmp_path / "s.json")
    assert isinstance(r, dict)


def test_beat_takes_a_sample():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    body = src.split("def beat(", 1)[1].split("\nLOCK_PATH", 1)[0]
    assert "_homeo_tick()" in body, (
        "nothing samples on the step boundary, so every rate stays None")
    assert "except Exception:" in body
