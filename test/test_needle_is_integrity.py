"""The needle measures work done, not seconds elapsed.

It showed flow_score: a completeness ratio MULTIPLIED BY 60/median_step_seconds.
Unbounded above — the smallest non-zero median the contract can record is 0.005s,
so the ceiling is 12000 — and band() called anything over 4.0 "flowing". A cycle
whose steps all returned in milliseconds, one that did NOTHING, produced the
best reading the page could show. Emil saw 2.5272 one day and >13,000 another
for the same quantity.

Now the needle is integrity_ratio as a percentage, and the pace sits BESIDE it
as a plain labelled number with no colour and no verdict. Folding a speed into
a quality score is the specific mistake being undone; a test here refuses to let
it back in.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PAGE = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(encoding="utf-8")


def test_the_endpoint_returns_integrity_and_no_composite():
    from cockpit import server as srv
    d = srv.app.test_client().get("/api/flow").get_json()

    for banned in ("flow_score", "fs", "band", "computed_now"):
        assert banned not in d, (
            f"/api/flow still returns {banned!r} — the composite is what this "
            f"replaces")
    for k in ("integrity_pct", "integrity_ratio", "degraded_ratio",
              "failed_ratio", "cloud_success_ratio", "median_step_seconds"):
        assert k in d, f"/api/flow does not return {k}"

    assert d["red_below_pct"] == 60.0
    assert d["amber_below_pct"] == 85.0


def test_the_percentage_and_the_ratio_agree():
    from cockpit import server as srv
    d = srv.app.test_client().get("/api/flow").get_json()
    if d["integrity_ratio"] is None:
        pytest.skip("no steps on record")
    assert d["integrity_pct"] == pytest.approx(d["integrity_ratio"] * 100, abs=0.05)
    assert 0.0 <= d["integrity_pct"] <= 100.0, (
        "integrity is a percentage and cannot leave 0-100; the old score's "
        "ceiling was 12000")


def test_the_needle_reads_integrity_and_not_a_product():
    fn = PAGE.split("async function tabOverview(){")[1].split("\n}")[0]
    assert "f.integrity_pct" in fn, "the needle no longer reads integrity"
    assert "flow_score" not in fn.replace("It used to show flow_score", ""), (
        "the needle still reads the composite")
    assert "red_below_pct" in fn and "amber_below_pct" in fn, (
        "the three-band threshold is not applied")


def test_the_pace_is_shown_beside_the_needle_with_no_verdict():
    fn = PAGE.split("async function tabOverview(){")[1].split("\n}")[0]
    assert "median_step_seconds" in fn, "the pace is not shown at all"
    # the pace class must carry no colour verdict of its own
    css = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]
    pace = re.search(r"\.pace\{([^}]*)\}", css)
    assert pace, "no .pace rule"
    for verdict_colour in ("--red", "--grn", "--yel"):
        assert verdict_colour not in pace.group(1), (
            f".pace paints itself with {verdict_colour}: the pace is a fact "
            f"about the night, not a judgement of it")


def test_the_needle_has_three_grades_not_two():
    css = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]
    for grade in ("bad", "warn", "ok"):
        assert f".needle.{grade}" in css, f"the needle has no {grade} grade"


# ── band() is gone from both modules, loudly ────────────────────────────────

def test_band_raises_in_flow_score():
    from core import flow_score as fs
    with pytest.raises(NotImplementedError) as e:
        fs.band(9.0)
    assert "composite" in str(e.value)
    assert "cycle_integrity" in str(e.value), (
        "the removal does not say where to go instead")


def test_band_raises_in_cycle_integrity():
    from core import cycle_integrity as ci
    with pytest.raises(NotImplementedError):
        ci.band(9.0)


def test_compute_no_longer_bands():
    """compute() survives — steps_full and the median are honest inputs — but
    it stops calling anything a quality."""
    from core import flow_score as fs
    score = fs.compute(steps=[{"step": "a", "seconds": 1.0, "verdict": "OK"}])
    assert score.band == "", (
        f"compute() still returns a band ({score.band!r}); the verdict was on a "
        f"confounded number")


# ── no reader may silently see zero ─────────────────────────────────────────

def test_no_presenter_still_reads_the_composite():
    """ast-shaped: a reader left on flow_score would silently show 0 or None."""
    offenders = []
    for rel in ("cockpit/reflex.py", "cockpit/phase_voice.py",
                "cockpit/server.py"):
        src = (REPO / rel).read_text(encoding="utf-8-sig")
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        body = re.sub(r"#[^\n]*", "", body)
        for m in re.finditer(r'get\(\s*["\'](flow_score|band)["\']', body):
            offenders.append(f"{rel}: {m.group(0)}")
    assert not offenders, (
        "these still read the composite and would show a stale or empty "
        f"number: {offenders}")


def test_reflex_speaks_integrity_to_the_model():
    from cockpit import reflex as rx
    line = rx.render_state({"glyph": "x", "step": "a", "step_index": "1",
                            "integrity_pct": 93.5, "median_step_seconds": 22.21,
                            "degraded_steps": 2})
    assert "93.5% of steps did their work" in line
    assert "median step 22.21s" in line
    assert "flow score" not in line.lower(), (
        "the model is still being told a composite it cannot reason about")
