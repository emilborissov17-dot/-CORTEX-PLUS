#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_corrections_27.py — THE FOUR CORRECTIONS FROM COMMAND 27 PART 2.

Each one closes a case where the system said something confidently and wrongly.
The tests are written against the actual failing input where one exists.

    venv/Scripts/python.exe -m pytest test/test_corrections_27.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import homeostasis as h        # noqa: E402
from core import p_survive as ps         # noqa: E402

RAM = {"unit": "MB", "levels": {"notice": 1200, "action": 900, "gate": 600},
       "hysteresis": 300}

# The exact readings taken on 23 Aug 2026 that produced "105 minutes to gate".
THE_NOISY_SERIES = [3708, 3704, 3730, 3744, 3628, 3645, 3735, 3672, 3653.543]


def _hist(values, dt=15.0):
    return [[i * dt, float(v)] for i, v in enumerate(values)]


# ── 2.1  the TTT stops lying ────────────────────────────────────────────────

def test_the_series_that_lied_now_reports_flat_and_no_ttt():
    """The headline. Nine samples of pure scatter must not become a deadline."""
    info = h.interoception("ram_free", THE_NOISY_SERIES[-1], RAM,
                           _hist(THE_NOISY_SERIES))
    assert info["direction"] == "flat", info["direction"]
    assert info["ttt_seconds"] is None, info["ttt_seconds"]
    assert info["rate_significant"] is False
    assert info["samples"] == 9


def test_no_ttt_means_no_ttt_confidence():
    """'confidence: high' beside a withheld number reads as certainty about the
    withholding. That was the label that made the wrong number believable."""
    info = h.interoception("ram_free", THE_NOISY_SERIES[-1], RAM,
                           _hist(THE_NOISY_SERIES))
    assert info["ttt_confidence"] == "none"


def test_a_real_fall_still_produces_a_ttt():
    """The correction must not silence the signal it was built to protect."""
    vals = [3000 - i * 11.25 for i in range(9)]        # steady, no scatter
    info = h.interoception("ram_free", vals[-1], RAM, _hist(vals))
    assert info["direction"] == "falling"
    assert info["rate_significant"] is True
    assert info["ttt_seconds"] is not None
    assert info["ttt_confidence"] == "high"


def test_a_real_fall_buried_in_noise_still_fires():
    """A slope four times its own scatter is a slope."""
    vals = [3000 - i * 100 + (17 if i % 2 else -17) for i in range(9)]
    info = h.interoception("ram_free", vals[-1], RAM, _hist(vals))
    assert info["rate_significant"] is True
    assert info["direction"] == "falling"


def test_flat_and_confidently_flat_are_different_answers():
    """ttt None = "we cannot tell". ttt inf = "it is not heading there"."""
    noisy = h.interoception("ram_free", THE_NOISY_SERIES[-1], RAM,
                            _hist(THE_NOISY_SERIES))
    rising = h.interoception("ram_free", 3000.0, RAM,
                             _hist([2000 + i * 125 for i in range(9)]))
    assert noisy["ttt_seconds"] is None
    assert rising["ttt_seconds"] == "inf"
    assert rising["rate_significant"] is True


def test_the_bar_is_two_standard_errors_and_it_is_named():
    assert h.SLOPE_SIGNIFICANCE_SE == 2.0
    info = h.interoception("ram_free", THE_NOISY_SERIES[-1], RAM,
                           _hist(THE_NOISY_SERIES))
    slope = abs(info["rate_per_second"])
    se = info["rate_stderr_per_second"]
    assert slope < 2.0 * se, (slope, se)


def test_p_survive_refuses_to_launder_scatter_into_a_decimal():
    """0.9416 was computed from that same noise. It must now be excluded."""
    ev = {"config_sha256": "t", "ts": "t", "variables": {
        "ram_free": h.interoception("ram_free", THE_NOISY_SERIES[-1], RAM,
                                    _hist(THE_NOISY_SERIES))}}
    ev["variables"]["ram_free"]["level"] = "clear"
    cfg = {"variables": {"ram_free": {"levels": {"notice": 1200, "action": 900,
                                                 "gate": 600}}}}
    r = ps.compute(evaluation=ev, cfg=cfg, horizon=6720.0)
    assert r["value"] is None
    assert "ram_free" in r["excluded"]
    assert "within its own noise" in r["variables"]["ram_free"]["why"]


# ── 2.2  a live writer is protected by name ─────────────────────────────────

def test_the_live_cycle_log_directory_is_on_the_negative_list():
    from core import disk_actuator as da
    assert "memory/cycle_logs" in da.NEGATIVE_DIRS
    ok, why = da.is_protected(REPO / "memory" / "cycle_logs" / "cycle_x.log",
                              REPO, tracked=frozenset())
    assert ok is True
    assert "cycle_logs" in why


def test_that_directory_is_the_one_the_supervisor_actually_opens():
    """Protecting the wrong path is the failure this correction exists to fix."""
    sup = (REPO / "supervisor.py").read_text(encoding="utf-8")
    assert 'BASE / "memory" / "cycle_logs"' in sup
    cl = (REPO / "core" / "cycle_log.py").read_text(encoding="utf-8")
    assert 'BASE / "memory" / "cycle_logs"' in cl


def test_cycle_log_at_the_root_is_deliberately_not_protected():
    """It has no writer. Protecting it would assert a relationship that does
    not exist - the same error as the one being corrected, reversed."""
    from core import disk_actuator as da
    names = {f.lower() for f in da.NEGATIVE_FILES}
    assert "cycle.log" not in names
    assert not any(g == "*.log" for g in da.NEGATIVE_GLOBS)
    backlog = (REPO / "docs" / "ENGINEERING_BACKLOG.md").read_text(
        encoding="utf-8")
    assert "cycle.log" in backlog, "it is not protected AND not recorded"


def test_the_manifest_hash_still_matches_after_the_amendment():
    from core import disk_actuator as da
    assert da.manifest_sha256() == da.MANIFEST_SHA256


# ── 2.3  history is annotated, never edited ─────────────────────────────────

def test_the_five_test_rows_are_still_there():
    p = REPO / "memory" / "p_survive_history.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    data = [r for r in rows if r.get("kind") != "ANNOTATION"]
    assert len(data) == 5, "a history line was deleted: {}".format(len(data))


def test_an_annotation_explains_them():
    p = REPO / "memory" / "p_survive_history.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    notes = [r for r in rows if r.get("kind") == "ANNOTATION"]
    assert len(notes) == 1, notes
    n = notes[0]
    assert n["annotates"]["rows"] == 5
    assert "TEST ARTEFACTS" in n["reason"]
    assert "test/test_survival_gate.py" in n["reason"]
    assert n["annotates"]["first_ts"] and n["annotates"]["last_ts"]
    assert "KEPT" in n["disposition"]


def test_the_annotation_comes_after_what_it_annotates():
    p = REPO / "memory" / "p_survive_history.jsonl"
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert json.loads(lines[-1]).get("kind") == "ANNOTATION"


# ── 2.4  a refusal is not an incomplete cycle ───────────────────────────────

def test_a_refused_cycle_reads_as_refused(tmp_path):
    from core import interoception as io
    led = tmp_path / "ledger.jsonl"
    led.write_text(json.dumps({
        "seq": 1, "event": "CYCLE_REFUSED_SURVIVAL_GATE",
        "variables": [{"variable": "disk_free_pct", "value": 3.0,
                       "threshold": 5}]}) + "\n", encoding="utf-8")
    got = io._last_cycle(led)
    assert "REFUSED" in got, got
    assert "disk_free_pct" in got, got
    assert "unknown" not in got.lower(), got


def test_the_event_is_in_the_terminal_set():
    from core import interoception as io
    assert "CYCLE_REFUSED_SURVIVAL_GATE" in io.TERMINAL


def test_a_finished_cycle_still_reads_finished(tmp_path):
    from core import interoception as io
    led = tmp_path / "l.jsonl"
    led.write_text(json.dumps({"seq": 1, "event": "CYCLE_FINISHED"}) + "\n",
                   encoding="utf-8")
    assert io._last_cycle(led) == "FINISHED"


def test_a_refusal_with_no_variables_still_renders(tmp_path):
    from core import interoception as io
    led = tmp_path / "l.jsonl"
    led.write_text(json.dumps({"seq": 1,
                               "event": "CYCLE_REFUSED_SURVIVAL_GATE"}) + "\n",
                   encoding="utf-8")
    got = io._last_cycle(led)
    assert "REFUSED" in got and "defended variable" in got


def test_the_row_is_still_one_line():
    """The mirror is five positional rows. A newline here breaks the format."""
    from core import interoception as io
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        led = pathlib.Path(d) / "l.jsonl"
        led.write_text(json.dumps({
            "seq": 1, "event": "CYCLE_REFUSED_SURVIVAL_GATE",
            "variables": [{"variable": "ram_free"},
                          {"variable": "disk_free_pct"}]}) + "\n",
            encoding="utf-8")
        assert "\n" not in io._last_cycle(led)
