# -*- coding: utf-8 -*-
"""ITEM 14 — the compass runs from the system, and K2 refuses on purpose.

tools/compass.py could produce all four needles from the day it was written. It
produced them only when a human typed the command, which made this project's
stated success criterion a thing somebody had to remember to ask for. Step 25.8
is the nerve.

THE OTHER HALF IS A REFUSAL, AND IT IS THE HARDER HALF. K2 counts promotions to
TRUSTED in memory/source_lifecycle_ledger.jsonl. Kimi ruled: "A transition to
TRUSTED that no consumer reads is not a source earning trust - it is a source
receiving a word." So K2 reports NOT_WIRED — value withheld, every diagnostic
kept.

WHAT THIS FILE MOSTLY DEFENDS IS THE EXPIRY, because a placeholder is the thing
most likely to quietly become permanent. Kimi's own objection to its own ruling:

    "A constant with an expiry is still a constant, not a measurement... expiry
     day likely produces a date bump or removal rather than a real check - the
     placeholder becomes a recurring to-do that never graduates to computation."

test_the_expiry_cannot_be_bumped_without_saying_why is that objection turned
into a gate. It holds a recorded (date, reason-digest) PAIR. Moving the date
while leaving the reason alone leaves this test red, so a bump costs a sentence
explaining why the world-check still cannot be written. Somebody made to write
that sentence three times writes the check instead.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from tools import compass as C  # noqa: E402


# ── THE EXPIRY ─────────────────────────────────────────────────────────────
#
# THE RECORDED PAIR. Both halves are pinned here, in the test, on purpose: a
# constant that guards itself guards nothing. Changing tools/compass.py alone
# turns this red, which is the entire mechanism.
KNOWN_UNTIL = "2026-10-01"
KNOWN_REASON_SHA = "c670c5b5d918f0c6fd9124d50f34a11c6f9aa39ea2fc97234b65e2fdf377522f"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_the_expiry_has_not_passed():
    """On or after the date, this goes red and stays red until somebody decides.

    It is deliberately not a warning. A warning about a placeholder is read
    exactly as often as the placeholder is — never.
    """
    until = dt.date.fromisoformat(C.K2_NOT_WIRED_UNTIL)
    today = dt.date.today()
    assert today < until, (
        f"K2_NOT_WIRED_UNTIL = {C.K2_NOT_WIRED_UNTIL} and today is {today}.\n"
        f"The review is due. Three honest outcomes, in order of preference:\n"
        f"  1. WIRE IT. The DMZ worker (scripts/openclaw_axis_worker.py) has no\n"
        f"     production caller; give it one, and being TRUSTED starts changing\n"
        f"     what the running system does. Then delete NOT_WIRED from k2().\n"
        f"  2. Decide K2 is the wrong needle and replace it, saying so.\n"
        f"  3. Move the date AND rewrite K2_NOT_WIRED_REASON to say why the\n"
        f"     world-check still cannot be written, then update KNOWN_UNTIL and\n"
        f"     KNOWN_REASON_SHA here. A bare date bump will not pass.\n"
        f"Kimi predicted outcome 3 and called it the failure mode. Prove it wrong.")


def test_the_expiry_cannot_be_bumped_without_saying_why():
    """The date and the reason move TOGETHER or not at all.

    This is the shape Kimi's objection asked for. A date is cheap to change; a
    sentence explaining a second failure to build the real check is not, and the
    cost is the point.
    """
    date_moved = C.K2_NOT_WIRED_UNTIL != KNOWN_UNTIL
    reason_moved = _sha(C.K2_NOT_WIRED_REASON) != KNOWN_REASON_SHA

    if date_moved and not reason_moved:
        raise AssertionError(
            f"K2_NOT_WIRED_UNTIL moved from {KNOWN_UNTIL} to "
            f"{C.K2_NOT_WIRED_UNTIL} and K2_NOT_WIRED_REASON did not change one "
            f"character.\nThat is the exact move this test exists to stop: "
            f"'expiry day likely produces a date bump... the placeholder becomes "
            f"a recurring to-do that never graduates to computation.'\n"
            f"Rewrite the reason to say why the world-check STILL cannot be "
            f"written, then update KNOWN_UNTIL and KNOWN_REASON_SHA here.")

    if reason_moved and not date_moved:
        raise AssertionError(
            "K2_NOT_WIRED_REASON changed while K2_NOT_WIRED_UNTIL stayed at "
            f"{KNOWN_UNTIL}.\nIf the reason is now different the review clock "
            "should restart from the new argument, or the needle should be "
            "wired. Update KNOWN_REASON_SHA here with the date you intend.")


def test_the_reason_is_a_finding_and_not_a_promise():
    """A placeholder that says 'not yet' teaches nothing. This one has to carry
    the measurement it rests on, so a reader can check it rather than trust it."""
    r = C.K2_NOT_WIRED_REASON
    assert "openclaw_axis_worker" in r, "the reason names no module"
    assert "external_feeds.jsonl" in r, "the reason names no artifact"
    assert any(ch.isdigit() for ch in r), "the reason cites no line or date"
    assert len(r) > 400, (
        "the reason is too short to be a finding — it should say what was "
        "searched, what was found, and what would end the refusal")


# ── K2's SHAPE: WITHHOLD THE HEADLINE, KEEP EVERY DIAGNOSTIC ───────────────

def _k2_on(tmp_path, rows):
    """k2() against a fixture ledger. Never the live file: a test that reads
    live state votes on the build with data no commit controls."""
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "source_lifecycle_ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    real = C.BASE
    try:
        C.BASE = tmp_path
        return C.k2()
    finally:
        C.BASE = real


_LEDGER = [
    {"ts": "2026-08-20T21:00:00Z", "state_before": "CANDIDATE",
     "state_after": "TRUSTED", "transition": "CANDIDATE -> TRUSTED"},
    {"ts": "2026-08-20T21:01:00Z", "state_before": "CANDIDATE",
     "state_after": "TRUSTED", "transition": "CANDIDATE -> TRUSTED"},
    {"ts": "2026-08-20T21:02:00Z", "state_before": "TRUSTED",
     "state_after": "TRUSTED", "event": "clean"},          # a label, not a change
]


def test_k2_withholds_the_number(tmp_path):
    n = _k2_on(tmp_path, _LEDGER)
    assert n["value"] is None, "K2 still puts a headline number on the compass"
    assert n["status"] == C.NOT_WIRED, n["status"]


def test_k2_keeps_every_diagnostic_it_had(tmp_path):
    """Kimi: 'diagnostic visibility is preserved, only the headline is withheld.
    NOT_WIRED is a reportable state, not an erasure.' This is that sentence as a
    test — the three fields that existed before the refusal must survive it."""
    n = _k2_on(tmp_path, _LEDGER)
    assert n["promotions"] == 2, n["promotions"]
    assert n["withdrawals"] == 0
    assert n["last_promotion_ts"] == "2026-08-20T21:01:00Z"
    assert n["rows_total"] == 3


def test_last_transition_ts_is_any_change_not_just_a_promotion(tmp_path):
    """WHY THIS FIELD EXISTS, and it is not decoration. Kimi ruled
    WIRE-FIRST-DEMOTE-AFTER and objected to its own ruling: 'the jump from 20 to
    NOT_WIRED looks like a wiring change rather than a data correction, and we
    lose the verification that RE-QUALIFY actually changed something.'

    With this field ITEM 37's demotion shows up as withdrawals beside a moved
    timestamp, visible without opening the raw ledger. So it must track a
    WITHDRAWAL too — a field that only ever moved on promotion would answer the
    objection in the one direction that was never in doubt."""
    n = _k2_on(tmp_path, _LEDGER)
    assert n["last_transition_ts"] == "2026-08-20T21:01:00Z", (
        "the third row carries no `transition` key and must not count")

    demoted = _LEDGER + [{"ts": "2026-09-01T10:00:00Z", "state_before": "TRUSTED",
                          "state_after": "DEMOTED",
                          "transition": "TRUSTED -> DEMOTED"}]
    n = _k2_on(tmp_path, demoted)
    assert n["withdrawals"] == 1
    assert n["last_transition_ts"] == "2026-09-01T10:00:00Z", (
        "a withdrawal did not move last_transition_ts — ITEM 37's demotion would "
        "be invisible on the needle, which is the whole reason for the field")
    assert n["last_promotion_ts"] == "2026-08-20T21:01:00Z", (
        "last_promotion_ts must NOT move on a withdrawal; the two fields "
        "answering the same question would leave the objection unanswered")


def test_a_missing_ledger_outranks_not_wired(tmp_path):
    """A source verdict beats a measurement verdict. Reporting 'the meaning is
    unwired' about a file that is not there would hide the more basic fact."""
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    real = C.BASE
    try:
        C.BASE = tmp_path
        n = C.k2()
    finally:
        C.BASE = real
    assert n["status"] == C.MISSING, n["status"]


def test_not_wired_outranks_stale(tmp_path):
    """The live ledger is 207h old. NOT_WIRED must survive that, because a
    fresher file would not make the number mean any more than it does now."""
    import os
    import time
    n = _k2_on(tmp_path, _LEDGER)          # writes the fixture
    p = tmp_path / "memory" / "source_lifecycle_ledger.jsonl"
    old = time.time() - (C.STALE_HOURS + 200) * 3600
    os.utime(p, (old, old))
    real = C.BASE
    try:
        C.BASE = tmp_path
        n = C.k2()
    finally:
        C.BASE = real
    assert n["status"] == C.NOT_WIRED, n["status"]
    assert n["age_hours"] > C.STALE_HOURS, (
        "the age must still be reported — the staleness is hidden otherwise")


def test_the_refusal_carries_the_census_it_rests_on(tmp_path):
    """The reason string is a census taken by hand on one day. `consumers`
    re-takes it every run, so the day it stops being true the needle says so on
    its own face instead of carrying a frozen sentence."""
    n = _k2_on(tmp_path, _LEDGER)
    c = n["consumers"]
    assert c["searched_for"] == list(C._TRUST_ARTIFACTS)
    for name in C._TRUST_ARTIFACTS:
        assert set(c["found"][name]) == {"production", "tests", "self"}, (
            "readers must be split three ways: a test reading a file is not a "
            "consumer of it, and this module quoting the name in its own reason "
            "string is certainly not")


def test_the_compass_does_not_count_a_withheld_needle(tmp_path):
    """The headline is the thing a human reads. K2 must not inflate it."""
    n = _k2_on(tmp_path, _LEDGER)
    assert not (n.get("value") is not None and n.get("status") == "OK")


# ── THE WIRING, IN ALL FIVE DECLARATION SITES ──────────────────────────────

def _beats():
    tree = ast.parse((BASE / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    out = {}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "beat" and len(n.args) > 1
                and all(isinstance(a, ast.Constant) for a in n.args[:2])):
            out[n.args[0].value] = n.args[1].value
    return out


def test_site_1_the_runner_beats_it():
    assert "compass" in _beats(), (
        "nothing in the cycle calls compass() — the defect ITEM 14 exists for")


def test_site_2_cycle_map_declares_it():
    from core import cycle_map
    assert any(s[0] == "compass" for s in cycle_map.STEPS)
    assert cycle_map.resolve("compass")[0] == "compass"


def test_site_3_and_4_cycle_phases_lists_it_and_its_range_reaches_it():
    """The FOURTH site is the one that hides. On 2026-08-29 cortex_scan was added
    to G_LEARN's steps while index_range still ended at 25.6, so the phase
    declared a step outside its own range and only a failing test found it."""
    g = json.loads((BASE / "config" / "cycle_phases.json")
                   .read_text(encoding="utf-8"))["phases"]["G_LEARN"]
    assert any(s["name"] == "compass" for s in g["steps"])
    assert float(g["index_range"][1]) >= 25.8, (
        f"G_LEARN's index_range ends at {g['index_range'][1]} but its last step "
        f"is 25.8 — the phase declares a step outside itself")
    assert "memory/compass_latest.json" in g["produces"]


def test_site_5_it_goes_through_run_and_records_a_checkpoint():
    """THE FIFTH SITE IS _run() COVERAGE ITSELF. A step added with a bare
    try/except records nothing: no checkpoint, no step contract, and (ITEM 21c)
    no word to the phase report when it raises. ITEM 7.1 and ITEM 11 both
    shipped that way and stayed invisible inside the ratchet's slack."""
    src = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    labels = {n.args[0].value for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_run" and n.args
              and isinstance(n.args[0], ast.Constant)}
    assert "compass" in labels, (
        "the compass step does not go through _run(), so it records no "
        "checkpoint — add it to _run(), do not raise UNCOVERED_STEP_LIMIT")


def test_it_runs_after_the_steps_that_write_what_it_reads():
    """K1's source is written by measurement_honesty at 20.1. A compass that ran
    first would measure last night and say it measured this one."""
    b = _beats()
    for earlier in ("measurement_honesty", "cycle_report", "cortex_scan"):
        assert float(b["compass"]) > float(b[earlier]), (
            f"compass runs before {earlier}, whose output it reads")


def test_the_cycle_writes_the_file_without_going_through_argv():
    """--write stays the human path. A runner that shells its own module through
    main() inherits an argument parser it does not control."""
    src = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8")
    i = src.index('beat("compass"')
    j = src.index('_run("compass"', i)
    body = src[i:j]
    assert "from tools.compass import" in body
    assert "compass_out.write_text" in body or "write_text" in body
    assert "main(" not in body, "the cycle calls main(), inheriting its argv"


# ── THE BASELINE ENTRY THAT MUST NOT OUTLIVE THE FIX ───────────────────────

def test_no_compass_entry_in_the_orphan_baseline_still_claims_item_14_is_pending():
    """ITEM 32 recorded seven tools/compass.py entries with
    expires: 'on ITEM 14 wiring'. ITEM 14 has now landed. An expiring baseline
    entry left in place past its expiry is the ITEM 38 slack defect wearing a
    different hat: it reserves room for a fixed thing to look unfixed.

    NOT asserting the entries are gone — six of the seven are ordinary
    internal-helper orphans that wiring does not touch (k1..k4 are called only
    by compass(), main and selftest only by __main__). Asserting that none of
    them still carries the expiry, because that claim is now false."""
    bl = json.loads((BASE / "config" / "orphan_baseline.json")
                    .read_text(encoding="utf-8"))
    stale = {k: v for k, v in (bl.get("orphans") or {}).items()
             if "compass" in k and v.get("expires") == "on ITEM 14 wiring"}
    assert not stale, (
        "these baseline entries still say ITEM 14 wiring is outstanding, and it "
        f"is not: {sorted(stale)}")


def test_the_entrypoint_that_the_wiring_actually_reaches_is_no_longer_an_orphan():
    """compass() is the one the cycle calls, so it is the one that must have
    left the baseline. If it is still recorded as debt, the wiring did not take."""
    bl = json.loads((BASE / "config" / "orphan_baseline.json")
                    .read_text(encoding="utf-8"))
    assert "tools/compass.py::compass" not in (bl.get("orphans") or {}), (
        "tools/compass.py::compass is still in the orphan baseline although the "
        "cycle now calls it at step 25.8")
