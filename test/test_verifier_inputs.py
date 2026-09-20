# -*- coding: utf-8 -*-
"""
core.notary.VERIFIERS vs config/step_inputs.json — the landmine, as a test.

THE DEFECT THIS EXISTS TO MAKE IMPOSSIBLE (written 5 Sep 2026)
--------------------------------------------------------------
A step in VERIFIERS is one the notary lets BREAK inherited provenance: it
verifies against a live external source, so it may wash a low level clean. That
is a privilege. The privilege is granted by NAME, in a set literal, and nothing
has ever checked that the named step can actually say what it reads.

A step whose inputs resolve to [] gets `_age_state([]) -> UNKNOWN(0)`
(core/notary.py:301-312, "no declared inputs - provenance unknown"). Its own
level becomes min(..., 0) = 0, that level is stamped on the artifacts it
produces, and every irreversible step that declares those artifacts as inputs
inherits level_0 and is refused by the gate — every night, until a human
declares the inputs by hand.

That is not a hypothesis. It has now happened twice, measured:

  * `web_intelligence` was in VERIFIERS with no declared inputs. From
    2026-08-17 the notary refused `github_publish` on **15 consecutive nights**
    with "level_0 (неизвестен произход) — слабо звено: no declared inputs".
    Publishing to the public repo stopped for 13 nights. Fixed on 2026-08-31
    (commit 467bcf6) by declaring one step's inputs.

  * `self_modifier` has been refused on **19 consecutive nights** and is still
    refusing as of 2026-09-04, for the same reason one level down.

Both remedies were per-step and manual. A per-step manual remedy is not a fix;
it is the same defect waiting for the next name added to the set. This test is
the structural version: **you may not join VERIFIERS without declaring what you
read.**

WHY THIS TEST WAS RED, AND WHAT CLOSED IT
-----------------------------------------
Four of the five verifiers could not say what they read. Three were declared by
reading the module the step actually calls. The fourth, browser_scout, could not
be: on the cycle path it opens NO repo file at all — run_all() loops a table of
URLs and fetches each over HTTP. Its input is the world.

That was not a configuration gap, it was a hole in the model. A step was in
VERIFIERS — the list allowed to BREAK inherited provenance, granted precisely for
checking against a live external source — and was scored UNKNOWN(0) for having no
file to be aged by. Both available answers were worse than the defect: declaring
a file it does not read is fabricated provenance, and declaring the directory it
WRITES makes the step grade itself off its own cache.

So on 20 Sep 2026 the model grew the category it was missing. A LIVE FETCH is
aged by its own fetch timestamp — the moment the record was fetched, written into
the record at fetch time — which is the observation date, which is what the age
dimension asks every other step for. config/passage_rules.json was not touched:
browser_scout is a verifier and its name stays.

An xfail here would be the exact defect the whole file is about: a failure
rendered as something plausible. So it fails instead.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.declared_inputs import for_step, live_fetch_for   # noqa: E402
from core.notary import (VERIFIERS, _age_state, _declares_provenance,  # noqa: E402
                         _fetch_age_state, _inputs_for)

# THE LEDGER. A set, not a comment, so that a NEWLY added landmine fails on its
# own line instead of disappearing into an already-red test. Every name in it
# still fails test_every_verifier_declares_what_it_reads; being listed buys a
# step nothing except being told apart from the next one.
#
# HOW THE FOUR WERE PAID OFF, each by reading the module the cycle actually calls:
#   global_indicators      -> data/ucdp, 8 Sep. _resolve_ucdp_csv/
#                             _fetch_ucdp_local_csv. Its one local input, and its
#                             age is a real fact: the active-conflict count is
#                             exactly as old as that CSV. MINIMAL(1) — lower than
#                             anyone would like, and TRUE, where it had been
#                             UNKNOWN(0).
#   sensorium_ingest       -> memory/sensorium, memory/penumbra, 8 Sep. verify()
#                             re-hashes both chains; the drop paths come out of
#                             the leaf records at runtime, so the trees are what
#                             is declared. REDUCED(2).
#   internet_intelligence  -> 19 Sep, from read_pantry()'s own docstring: the
#                             queue cards, the news and memory/transcript_cache.
#   browser_scout          -> 20 Sep, and NOT by a declaration of files. See below.
KNOWN_UNDECLARED: set = set()
# EMPTY SINCE 20 SEP 2026, and the last name left by a change to the model rather
# than by a declaration.
#
# browser_scout could not be declared the ordinary way, and the entry here said
# so: it opens NO repo file, so it had no artifact whose age could grade it, and
# the only two moves available were to fabricate a file input or to take it out of
# config/passage_rules.json VERIFIERS — a file this work may not touch, and a
# removal that would have been false anyway, since the step really does verify
# against a live external source.
#
# The third move is the one taken: a step that reads the world declares
# `live_fetch` in config/step_inputs.json, and core/notary._fetch_age_state ages
# it by the timestamp the fetch itself recorded. Measured on this repo the day it
# landed: FULL(3), "най-старо теглене memory/browse_sources/social_conflicts.json:
# 0.3 дни", where the same step scored UNKNOWN(0) the day before.
#
# The set stays, and so do the three tests around it. A name added to VERIFIERS
# tomorrow with provenance of NEITHER kind fails
# test_no_verifier_becomes_undeclared_that_was_not_already, and it fails alone,
# which is the whole reason the ledger was written as a set and not as a comment.

# A name no step has ever had, used where the mechanism must still be exercised
# after the last real debt is paid. It declares nothing by construction, so the
# notary answers UNKNOWN for it for exactly the reason under test.
_NO_SUCH_STEP = "__no_step_by_this_name__"

REMEDY = (
    "Declare its inputs in config/step_inputs.json under 'steps', following that "
    "file's _how_to_add_a_step: read the module the step actually calls, list what "
    "it opens on THAT path, and fill in 'derived_from'. If it reads no repo file "
    "because it reads the WORLD, declare 'live_fetch' instead — the records its "
    "fetch writes and the field that holds the fetch timestamp — and it will be "
    "aged by when it last looked. If the step does not belong in VERIFIERS, remove "
    "it from core.notary.VERIFIERS instead. Any of the three is acceptable; "
    "leaving it undeclared is not."
)


def _undeclared() -> list[str]:
    """Verifiers that cannot say where their knowledge comes from.

    TWO WAYS TO SAY IT, since 20 Sep 2026, and a step needs exactly one:
      * file inputs — for_step() returns None for 'nobody wrote a declaration'
        and [] for 'a declaration exists and is empty or broken'. Both produce
        UNKNOWN provenance, so both still fail here.
      * a live fetch — live_fetch_for() returns the records and the field holding
        the fetch timestamp, or None. A step that reads the world and records
        when it looked is not blind; it is datable, and it can be graded LOW for
        having looked a long time ago, which is a verdict and not an absence.

    Asked through core.notary._declares_provenance, so this test cannot answer
    differently from the gate it is guarding.
    """
    return sorted(s for s in VERIFIERS if not _declares_provenance(s))


# ── the requirement ──────────────────────────────────────────────────────────

def test_every_verifier_declares_what_it_reads():
    """A step may not hold the right to break inherited provenance while being
    unable to state its own. Fails until every name in VERIFIERS is declared."""
    missing = _undeclared()
    assert not missing, (
        "these steps are in core.notary.VERIFIERS with NO declared inputs in "
        "config/step_inputs.json:\n  "
        + "\n  ".join(missing)
        + "\n\nEach resolves to _age_state([]) -> UNKNOWN(0), which stamps level_0 "
          "on everything it produces and refuses every irreversible step that "
          "inherits from it. This is what cost 15 nights of github_publish and 19 "
          "of self_modifier.\n\n" + REMEDY
    )


# ── the ratchet: a NEW landmine must be distinguishable from the old four ────

def test_no_verifier_becomes_undeclared_that_was_not_already():
    """The structural guard. Adding a name to VERIFIERS without declaring its
    inputs fails HERE, separately from the four legacy debts, so it cannot hide
    inside an already-red test."""
    new = sorted(set(_undeclared()) - KNOWN_UNDECLARED)
    assert not new, (
        "NEW undeclared verifier(s): " + ", ".join(new)
        + "\nThis is the landmine being laid again. " + REMEDY
    )


def test_the_ledger_does_not_outlive_the_debt():
    """When a legacy debt is paid, its name must leave KNOWN_UNDECLARED. A stale
    ledger entry silently re-permits the same step if it regresses later."""
    paid = sorted(KNOWN_UNDECLARED - set(_undeclared()))
    assert not paid, (
        "these steps now declare their inputs and must be removed from "
        "KNOWN_UNDECLARED in this file: " + ", ".join(paid)
    )


def test_every_name_in_the_ledger_is_still_a_verifier():
    """A step removed from VERIFIERS is no longer a debt. Keeping it listed makes
    the ledger describe a system that no longer exists."""
    gone = sorted(KNOWN_UNDECLARED - set(VERIFIERS))
    assert not gone, (
        "no longer in core.notary.VERIFIERS, so remove from KNOWN_UNDECLARED: "
        + ", ".join(gone)
    )


# ── the mechanism, so the requirement above cannot be argued with ────────────

@pytest.mark.parametrize("step", sorted(KNOWN_UNDECLARED) or [_NO_SUCH_STEP])
def test_an_undeclared_verifier_really_does_score_unknown(step):
    """Not an assumption: each named step is asked, right now, through the
    notary's own code path, and answers UNKNOWN(0).

    With the ledger empty the parameter falls back to a name that is not a step at
    all, so the MECHANISM stays asserted. Letting an empty set collapse the
    parametrisation would delete this check silently on the day the last debt was
    paid — the one day it is most worth keeping."""
    if for_step(step) or live_fetch_for(step):
        pytest.skip(f"{step} now has a declaration — see the ledger test")
    inputs, source = _inputs_for(step)
    level, why = _age_state(inputs, source)
    assert level == 0, f"{step} scored {level}: {why}"
    assert "no declared inputs" in why, why


# ── the refusal must not present blindness as a verdict ──────────────────────
# A refusal caused by a step that never declared what it reads used to come back
# as "level_0 (неизвестен произход)" plus the name of an input — which reads as a
# judgement about the QUALITY of that input. It is not: nothing was measured and
# found wanting, nothing was measured at all. The two want different responses,
# and nineteen nights of self_modifier were spent on the wrong one.

def test_a_blind_step_is_named_as_blind_not_scored_as_poor():
    """The step's own blindness, in words, ahead of the level number."""
    step = (sorted(KNOWN_UNDECLARED) or [_NO_SUCH_STEP])[0]
    if for_step(step) or live_fetch_for(step):
        pytest.skip(f"{step} now has a declaration")
    from core.notary import _blindness
    said = _blindness(step, {})
    assert "never declared what it reads" in said, said
    assert repr(step) in said, said


def test_the_blind_step_named_is_the_UPSTREAM_one_not_the_consumer(monkeypatch):
    """THE CASE THAT WAS INVISIBLE. A step can declare every one of its own
    inputs and still be refused, because the step that PRODUCED one of them
    declares none. The refusal must name that upstream step, not blame the
    artifact or the consumer.

    HERMETIC SINCE 8 SEP 2026, AND THAT IS THE POINT. This test used the live
    pair self_modifier <- hyperclaw_plan <- memory/improvement_proposals.json,
    which was true every night until hyperclaw_plan was declared in
    config/step_inputs.json. The assertion then pinned a fact that had stopped
    being true and failed for a reason that had nothing to do with the mechanism
    under test — the same defect this file's own _how_to_add_a_step warns about
    for hardcoded copies of declared lists. The pair is now built here, so the
    test survives every future declaration and still goes red if _blindness()
    stops naming the upstream step.
    """
    from core import notary as _N
    from core.notary import _blindness

    monkeypatch.setattr(_N, "_inputs_for",
                        lambda step: (["memory/thing.json"], "written")
                        if step == "consumer" else ([], "scanner"))
    monkeypatch.setattr(_N, "_producers_of",
                        lambda art: ["upstream_blind"]
                        if art == "memory/thing.json" else [])

    rec = {"inherited_from": "memory/thing.json", "inherited": 0, "own": 1}
    said = _blindness("consumer", rec)
    assert "upstream_blind" in said, said
    assert "consumer" not in said, ("the consumer is being blamed for its "
                                    "producer's blindness: " + said)
    assert "never declared what it reads" in said, said
    assert "memory/thing.json" in said, said


def test_no_blindness_is_claimed_when_the_producer_IS_declared():
    """The clause must be earned. web_intelligence declares its inputs, so a low
    level inherited from it is a real verdict and must not be excused as
    blindness."""
    from core.notary import _blindness
    rec = {"inherited_from": "memory/web_intelligence", "inherited": 0, "own": 2}
    assert _blindness("github_publish", rec) == ""


def test_the_blindness_clause_survives_the_refusal_reader_truncation(monkeypatch):
    """tools/read_the_refusals.py prints reason[:150]. The name of the blind step
    must fall inside that, or the streak report shows the boilerplate and hides
    the one word a human needs.

    Hermetic for the same reason as the test above, and with a deliberately long
    artifact path: if the name were placed after the path, a realistic path would
    push it past the truncation and the report would again show only boilerplate.
    """
    from core import notary as _N
    from core.notary import _blindness

    art = "memory/a_realistically_long_artifact_name_latest.json"
    monkeypatch.setattr(_N, "_inputs_for",
                        lambda step: ([art], "written")
                        if step == "consumer" else ([], "scanner"))
    monkeypatch.setattr(_N, "_producers_of",
                        lambda a: ["upstream_blind"] if a == art else [])

    rec = {"inherited_from": art, "inherited": 0, "own": 1}
    assert "upstream_blind" in _blindness("consumer", rec)[:150]


def test_the_explanation_can_never_change_the_decision():
    """_blindness is called inside may_act's refusal path only, and its failure is
    recorded rather than swallowed. Asserted structurally: the call is wrapped and
    the except branch produces text, never a `pass` and never a re-raise."""
    src = (REPO / "core" / "notary.py").read_text(encoding="utf-8")
    i = src.index("blind = _blindness(step, rec)")
    tail = src[i:i + 400]
    assert "except Exception" in tail, tail
    assert "blindness check failed" in tail, (
        "the blindness check swallows its own failure silently")
    assert "return False" in tail, "the refusal must still be returned"


def test_a_declared_verifier_scores_above_unknown():
    """The counter-example, so the test above is not vacuously true of every
    step. web_intelligence is the one verifier whose inputs were declared, on
    2026-08-31, and it is the reason publishing resumed."""
    inputs, source = _inputs_for("web_intelligence")
    level, why = _age_state(inputs, source)
    assert inputs, "web_intelligence lost its declaration"
    assert level > 0, f"declared but still UNKNOWN: {why}"


# ── COMMIT C: a declaration must be BOUND to what the code opens ─────────────
# A verifier trusted to BREAK inherited provenance must declare the source it
# checks, or it cannot itself be trusted. And a declaration nobody verifies is a
# second copy free to drift from the code — the same defect one level up. These
# read the modules.

_DECLARED_VERIFIER_READS = {
    # step -> (module path, the constant that must still resolve to the declared
    #          path, the fragments that must appear in that constant)
    "global_indicators": ("core/global_indicators.py", "UCDP_LOCAL_DIR",
                          ("data", "ucdp")),
}


@pytest.mark.parametrize("step", sorted(_DECLARED_VERIFIER_READS))
def test_a_declared_verifier_input_is_one_its_code_actually_opens(step):
    """Binds config/step_inputs.json to the module's own path constants. If the
    constant is renamed or repointed, the declaration is stale and the gate is
    aging a file the step no longer reads."""
    import ast

    rel, const_name, fragments = _DECLARED_VERIFIER_READS[step]
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    consts = {n.targets[0].id: ast.dump(n.value)
              for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    assert const_name in consts, (
        f"{rel} no longer defines {const_name}; the declaration in "
        f"config/step_inputs.json for {step} is stale")
    for frag in fragments:
        assert repr(frag) in consts[const_name], (
            f"{const_name} in {rel} no longer contains {frag!r}; "
            f"{step} now declares a path its code does not open")


def test_sensorium_declares_both_chains_because_it_verifies_both():
    """verify() re-derives the verified chain AND the penumbra shadow
    independently — the module's contract is that a corrupted shadow must never
    cast doubt on verified sense. A stale shadow is therefore its own fact and
    must be its own declared input, not folded into the first."""
    declared = for_step("sensorium_ingest") or []
    assert "memory/sensorium" in declared
    assert "memory/penumbra" in declared, (
        "the shadow chain is verified on this step and is not declared, so its "
        "age cannot reach the gate")

    src = (REPO / "experiments" / "sensorium" / "sensorium.py").read_text(
        encoding="utf-8")
    for const in ("PENUMBRA_LEAVES", "PENUMBRA_ROOT", "LEAVES", "ROOT_FILE"):
        assert const in src, f"{const} is gone; re-derive the declaration"


def test_a_declared_verifier_no_longer_scores_unknown():
    """The point of the commit: these two stopped being blind. Their levels are
    LOW and that is honest — data/ucdp really is 57 days old — but low is a
    measurement and UNKNOWN is the absence of one."""
    for step in ("global_indicators", "sensorium_ingest"):
        inputs, source = _inputs_for(step)
        assert inputs, f"{step} lost its declaration"
        level, why = _age_state(inputs, source)
        assert level > 0, f"{step} still scores UNKNOWN: {why}"
        assert "no declared inputs" not in why


def test_no_verifier_declares_its_own_output_as_an_input():
    """A step whose age dimension depends on its own last output grades itself,
    and one missed night would hold it down for ever. This is the trap the two
    remaining undeclared verifiers would fall into if somebody declared their
    caches to make the ledger shrink."""
    import json as _json

    doc = _json.loads((REPO / "config" / "step_inputs.json").read_text(
        encoding="utf-8"))
    own_output = {
        "global_indicators": "snapshots/master/global_indicators_latest.json",
        "sensorium_ingest": None,
    }
    for step, product in own_output.items():
        if not product:
            continue
        entry = doc["steps"][step]
        assert product not in entry["inputs"], (
            f"{step} gates on its own output {product}")
        assert product in entry.get("also_reads", []), (
            f"{product} is read by {step} and is declared nowhere")


# ── THE LIVE FETCH: aged by when it looked, not by when a file was touched ──
# Added 20 Sep 2026 with the category itself. Every test below fails if the
# category is removed, weakened, or quietly turned back into mtime aging.

_LIVE_SPEC = {"records": ["memory/browse_sources/social_conflicts.json"],
              "timestamp_field": "extracted_at"}


def _record(tmp_path, monkeypatch, stamp, field="extracted_at"):
    """A fetch record with a chosen recorded timestamp and a FRESH mtime.

    The mtime is fresh by construction — the file is written right now. That is
    what makes these tests able to tell the two aging models apart: anything that
    still grades by mtime reads every one of them as brand new.
    """
    from core import notary as _N
    rel = "recs/one.json"
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    body = {} if stamp is None else {field: stamp}
    f.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(_N, "BASE", tmp_path)
    return {"records": [rel], "timestamp_field": "extracted_at"}


def test_a_live_fetch_is_aged_by_the_recorded_timestamp_and_not_by_mtime(
        tmp_path, monkeypatch):
    """THE WHOLE POINT, AND THE MUTATION NET UNDER IT.

    The record is written this second, so its mtime says 'brand new'. The
    timestamp INSIDE it says 400 days. The age model must answer 400 days. If
    _fetch_age_state is ever rewritten to stat the file — the obvious shortcut,
    since the record does sit on disk — this goes red instead of silently handing
    a year-old observation a FULL stamp every night.
    """
    from core.notary import FULL, UNKNOWN

    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    spec = _record(tmp_path, monkeypatch, old)
    level, why = _fetch_age_state(spec)
    assert level == UNKNOWN, f"400-day-old fetch scored {level}: {why}"
    assert level != FULL
    assert "400." in why, why


def test_a_fresh_fetch_scores_full(tmp_path, monkeypatch):
    """The counter-example, so the test above is not vacuously true of every
    input: a fetch recorded minutes ago is FULL."""
    from core.notary import FULL

    now = datetime.now(timezone.utc).isoformat()
    level, why = _fetch_age_state(_record(tmp_path, monkeypatch, now))
    assert level == FULL, why


def test_the_bands_are_the_same_ones_every_other_step_is_graded_by(
        tmp_path, monkeypatch):
    """A live fetch must not get its own, kinder thresholds. Both paths go
    through _by_days, so a widened band would show up for every step at once
    rather than quietly for this one."""
    from core.notary import _by_days, _STALE_DAYS

    d2, d30, _d365 = _STALE_DAYS
    for days in (0, d2 + 1, d30 + 1, 400):
        stamp = (datetime.now(timezone.utc) - timedelta(days=days, minutes=1)
                 ).isoformat()
        level, why = _fetch_age_state(_record(tmp_path, monkeypatch, stamp))
        assert level == _by_days(days + 0.001), (days, level, why)


@pytest.mark.parametrize("stamp,what", [
    (None, "no such field in the record"),
    ("", "an empty timestamp"),
    ("yesterday", "a timestamp that is not a date"),
    (1758326400, "a number where an ISO string belongs"),
])
def test_an_unreadable_fetch_timestamp_fails_closed(stamp, what, tmp_path,
                                                    monkeypatch):
    """FAIL CLOSED, like every other path in this subsystem. A record that cannot
    say when it was fetched is not fresh by default; it is UNKNOWN, which refuses.
    The forbidden fallback is to reach for the file's mtime when the field is
    missing — that turns every malformed record into a perfect score."""
    from core.notary import UNKNOWN

    level, why = _fetch_age_state(_record(tmp_path, monkeypatch, stamp))
    assert level == UNKNOWN, f"{what} scored {level}: {why}"


def test_a_missing_fetch_record_fails_closed(tmp_path, monkeypatch):
    """A step that has not fetched at all has no observation date, and no
    observation date is UNKNOWN — never 'nothing to be stale, so fine'. This is
    the same trap _age_state fell into until 17 Aug 2026."""
    from core import notary as _N
    from core.notary import UNKNOWN

    monkeypatch.setattr(_N, "BASE", tmp_path)
    level, why = _fetch_age_state({"records": ["recs/absent.json"],
                                   "timestamp_field": "extracted_at"})
    assert level == UNKNOWN, why


def test_a_naive_timestamp_is_read_as_utc_not_as_local_time():
    """A record written without an offset must not be read as local time: on a
    machine three hours ahead that would make a just-fetched record look three
    hours stale, and on one behind it would place the fetch in the future."""
    from core.notary import _parse_stamp

    naive = datetime(2026, 9, 20, 12, 0, 0)
    assert _parse_stamp(naive.isoformat()) == naive.replace(
        tzinfo=timezone.utc).timestamp()


def test_a_broken_live_declaration_is_no_declaration_at_all(tmp_path,
                                                            monkeypatch):
    """The safety property of the whole file, restated for the new key: a
    declaration that cannot be read must leave the step exactly where it was,
    which is UNKNOWN. It must never be half-honoured."""
    from core import declared_inputs as DI

    for broken in ({"timestamp_field": "extracted_at"},            # no records
                   {"records": [], "timestamp_field": "x"},        # empty
                   {"records": ["a.json"]},                        # no field
                   {"records": ["a.json"], "timestamp_field": ""},
                   {"records": ["C:/elsewhere/a.json"], "timestamp_field": "x"},
                   {"records": ["../outside.json"], "timestamp_field": "x"},
                   {"records": "a.json", "timestamp_field": "x"},
                   "not a dict"):
        f = tmp_path / "decl.json"
        f.write_text(json.dumps({"steps": {"s": {"inputs": [],
                                                 "live_fetch": broken}}}),
                     encoding="utf-8")
        monkeypatch.setattr(DI, "PATH", f)
        assert DI.live_fetch_for("s") is None, broken


# ── the declaration is BOUND to what the scout actually writes ──────────────

def test_the_declared_fetch_records_are_the_ones_the_scout_writes():
    """The same binding _DECLARED_VERIFIER_READS does for file inputs, for the
    fetch records: the declaration names one file per key of scout.SOURCES, and
    goes red if that table grows a key without the declaration following.

    NOT A GREP OVER PROSE — the table is imported and read. A source added to the
    scout and not declared here would otherwise be fetched every night and never
    counted when the step is aged, which means the OLDEST fetch could be arbitrarily
    stale while the step scored FULL on the one record that was declared.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "scout_for_test", REPO / "experiments" / "browser_scout" / "scout.py")
    scout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scout)

    expected = {f"memory/browse_sources/{key}.json" for key in scout.SOURCES}
    declared = set(live_fetch_for("browser_scout")["records"])
    assert declared == expected, (
        f"browser_scout declares {sorted(declared)} but scout.SOURCES writes "
        f"{sorted(expected)}. Every key of SOURCES is refreshed by run_all(), so "
        f"every one of them is part of this step's observation date.")


def test_the_declared_timestamp_field_is_one_the_scout_writes():
    """Binds the field name to the record the module builds. A renamed field
    would otherwise fail closed every night — correctly, and for a reason nobody
    could see from the declaration."""
    import ast

    src = (REPO / "experiments" / "browser_scout" / "scout.py").read_text(
        encoding="utf-8")
    keys = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    field = live_fetch_for("browser_scout")["timestamp_field"]
    assert field in keys, (
        f"scout.py writes no {field!r} key; the declaration in "
        f"config/step_inputs.json names a field the record does not carry")


# ── and the step itself, on this repo, right now ────────────────────────────

def test_browser_scout_is_aged_by_its_fetch_and_is_not_called_blind():
    """The live check, on this repo. Before 20 Sep this step scored UNKNOWN(0)
    and _blindness() named it as unable to say what it reads. It can say: it
    reports when it last looked."""
    from core.notary import _blindness

    spec = live_fetch_for("browser_scout")
    assert spec, "browser_scout lost its live-fetch declaration"
    level, why = _fetch_age_state(spec)
    assert level > 0, f"still UNKNOWN: {why}"
    assert "теглене" in why, why
    assert _blindness("browser_scout", {}) == "", (
        "a step that records when it looked is not blind; it is datable")


def test_a_live_fetch_declaration_does_not_open_the_inputs_door():
    """The ban it was carved around stays exactly where it was: the records are
    declared under their own key, and memory/browse_sources must never appear in
    'inputs', where it would be the step grading itself off its own output."""
    doc = json.loads((REPO / "config" / "step_inputs.json").read_text(
        encoding="utf-8"))
    entry = doc["steps"]["browser_scout"]
    assert entry["inputs"] == [], entry["inputs"]
    assert not any("browse_sources" in p for p in entry["inputs"])
    assert entry["live_fetch"]["records"], "the records are declared nowhere"


def test_the_gate_asks_the_fetch_path_and_not_the_file_path(monkeypatch):
    """MUTATION NET ON THE WIRING. The two functions can both be correct and the
    gate still never reach the new one — which is exactly what an unwired module
    looks like from the outside. vector() must consult the live-fetch path for a
    step that declares one, so removing the dispatch turns this red."""
    from core import notary as _N

    called = []
    monkeypatch.setattr(_N, "_fetch_age_state",
                        lambda spec: called.append(spec) or (3, "fetched"))
    vec = _N.vector("browser_scout", prev_step=_N.PREV_NONE)
    assert called, ("vector() graded browser_scout without asking "
                    "_fetch_age_state — the live-fetch path is not wired in")
    assert vec["why"]["age"] == "fetched", vec["why"]["age"]
