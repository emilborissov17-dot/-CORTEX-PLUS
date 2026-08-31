#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_notary_gate.py — THE GATE ON SELF-MODIFICATION IS HELD SHUT BY A TYPO.

WHAT IS ACTUALLY HOLDING THE GATE (measured 17 August 2026, not assumed)
------------------------------------------------------------------------
`execute_patches` is one of the three irreversible steps in the cycle — it is the
step that REWRITES THE SYSTEM'S OWN CODE (fast_cycle_runner.py:1900, via
`_witness_or_refuse` -> `core.notary.may_act`). Tonight it was refused, and the
whole reason it was refused is a filename that does not exist:

    attest("execute_patches") ->
        vector {witness:3, human:3, thought:3, age:0, promise:3}
        why.age = "вход липсва: memory/last_attempt.txt"
        own = min(...) = 0  ->  level_0  ->  may_act() = False

`memory/last_attempt.txt` is a PHANTOM. It is a truncation of the real file
`memory/last_attempted_cycle_id.txt` (fast_cycle_runner.py:36, 32 bytes, written
every night). The truncated name has NO WRITER ANYWHERE in the repo — the only two
occurrences are the one inside `_IGNORE` itself and a tmp fixture name in
test/test_boot_guard.py:64. `_age_state` stats it, `stat()` raises, and the whole
step drops to UNKNOWN.

WHERE THE PHANTOM CAME FROM — A LIST THAT MEANS THE OPPOSITE
-------------------------------------------------------------
All SEVEN of `execute_patches`' seven declared inputs are harvested out of
`core/metta_check.py:_IGNORE` — a NEGATIVE list whose own comment says these paths
must NOT count ("Собственото счетоводство на слоя НЕ се брои за продукт на
стъпката"). `core/cycle_graph.py:scan_requires()` greps imported modules' raw
source text with `_PATH_RE` and has no idea what the strings mean, so an ignore
list becomes a requires list. Not one of the seven is a real input. (The eighth
entry, `memory/cycle.lock`, escaped only because `.lock` is not in the regex's
extension alternation.)

The step's region imports `core.metta_check` only for a post-hoc cleanup call; the
module that does the work is loaded via `__import__("execute_patches", ...)`, a
function call that `_IMPORT_RE` — which matches import STATEMENTS — cannot see.

DO NOT "FIX" THE TYPO IN ISOLATION — AND THE REASON HAS SINCE BEEN CLOSED
--------------------------------------------------------------------------
Until 17 Aug 2026 `_age_state` returned FULL(3) for an EMPTY inputs list, so both
obvious cleanups were unsafe: filtering `_IGNORE` out of the harvest, or correcting
the name to a real file, each gave `inputs = []` or all-present inputs, `age` FULL,
and level_3 — the maximum stamp — on the step that rewrites the system's own source.
`self_modifier` and `github_publish` were already passing the gate that way, on
`[]`, on every attestation on record.

That fail-open is now closed: an empty list returns UNKNOWN, and the promise
dimension no longer defaults to FULL when nobody states a predecessor. The warning
in this heading still stands for a different reason — the phantom is no longer the
only thing holding the gate, so removing it changes less than it used to, but the
step's declared inputs remain seven entries harvested out of an ignore list, and
that is still not a description of what it reads.

WHAT THIS FILE LOCKS
--------------------
The invariant, not the typo: `execute_patches` must never reach full trust, even
when every other dimension is perfectly healthy. Whoever removes the phantom must
make `_age_state` honest about emptiness in the same change, or this test goes red.

    venv\\Scripts\\python.exe -m pytest test/test_notary_gate.py -v
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTARY_SRC = REPO_ROOT / "core" / "notary.py"
STEP = "execute_patches"
PHANTOM = "memory/last_attempt.txt"
REAL_FILE = "memory/last_attempted_cycle_id.txt"


def _pristine_notary():
    """Load core/notary.py as a private module object.

    conftest.py's autouse `_no_live_side_effects` fixture monkeypatches
    `core.notary.attest` to a recorder returning None — correctly, because the real
    one appends to the attestation chain and test-fabricated rows in that chain are
    exactly the contamination that fixture exists to prevent. But `may_act()` calls
    `attest()` through the module global, so through the patched module there is no
    way to reach the real arithmetic at all.

    Loading the same file under a private name gives an unpatched copy of the code
    AS IT IS ON DISK, without un-patching the live module for anyone else. Its
    write targets are redirected into tmp_path by the fixture below, so the real
    chain is never touched.
    """
    spec = importlib.util.spec_from_file_location("_notary_under_test", NOTARY_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def notary(tmp_path, monkeypatch):
    """Pristine notary whose append-only chain points at a throwaway directory."""
    mod = _pristine_notary()
    chain = tmp_path / "attestation"
    chain.mkdir()
    monkeypatch.setattr(mod, "ATTEST_DIR", chain)
    monkeypatch.setattr(mod, "ATTEST_LOG", chain / "attest.jsonl")
    monkeypatch.setattr(mod, "ATTEST_HEAD", chain / "chain.head")
    return mod


@pytest.fixture
def healthy_environment(notary, monkeypatch):
    """Pin the four non-age dimensions to FULL.

    The point is to isolate `age` as the only variable. A test that let witness or
    thought decide would pass for the wrong reason — MeTTa is not built in a fresh
    test process, so `_witness_state()` returns UNKNOWN and the level would be 0 no
    matter what the harvest says. That test would keep passing after someone
    removes the phantom, which is precisely the failure it is supposed to catch.

    So we ask the hardest question instead: on the best night this system can have,
    with the symbolic witness alive, the human channel answering, five thinking
    paths up and the previous step's promise kept — is the gate still shut?
    """
    for name in ("_witness_state", "_human_state", "_thought_state"):
        monkeypatch.setattr(notary, name, lambda: (notary.FULL, "forced FULL for this test"))
    # Two positional args since 17 Aug: _promise_state(prev_step, step). The stub
    # takes *a so a future signature change surfaces as a real assertion failure
    # rather than as a TypeError from the fixture.
    monkeypatch.setattr(notary, "_promise_state",
                        lambda *a: (notary.FULL, "forced FULL for this test"))
    return notary


@pytest.fixture
def live_harvest(monkeypatch):
    """Feed attest() the requires that the REAL harvester derives right now.

    `core.metta_check._REQ` is a lazily-built cache and is empty in a fresh
    process; `attest()` reads it directly. Left empty, every step would look
    input-free and the test would measure nothing. Populating it from the real
    `core.cycle_graph.scan_requires()` means this test tracks whatever the harvester
    actually produces today — including any change someone makes to `_IGNORE`.
    """
    from core.cycle_graph import scan_requires
    mc = importlib.import_module("core.metta_check")
    harvested = scan_requires().get(STEP, [])
    monkeypatch.setitem(mc._REQ, STEP, list(harvested))
    return harvested


@pytest.fixture
def phantom_is_the_only_gap(notary, live_harvest, tmp_path, monkeypatch):
    """Point BASE at a tmp repo where every harvested input EXISTS — except the phantom.

    WHY THIS FIXTURE EXISTS, measured 17 Aug 2026: without it this test passed for
    the wrong reason and would have kept passing after the phantom was removed.

    `_age_state` returns on the FIRST input it cannot stat, and the harvest is
    sorted, so `memory/heartbeat.json` is reached before `memory/last_attempt.txt`.
    Right now heartbeat.json does not exist — the cycle clears it on a clean finish —
    so against the live repo the step is refused because of the HEARTBEAT, and the
    phantom is never even reached. During a live cycle the heartbeat DOES exist and
    the phantom is the sole cause; that is the state the production gate runs in, and
    the one worth locking.

    Recreating that state deterministically also removes a nasty time dependency:
    against the live repo this test's answer would change depending on whether a
    cycle happened to be running when the suite ran.
    """
    for rel in live_harvest:
        if rel == PHANTOM:
            continue                      # the one gap, left open on purpose
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("fixture", encoding="utf-8")   # exists and is fresh
    monkeypatch.setattr(notary, "BASE", tmp_path)
    return tmp_path


def test_execute_patches_never_reaches_full_trust(healthy_environment, live_harvest,
                                                  phantom_is_the_only_gap):
    """The step that rewrites the system's own code must not carry the maximum stamp.

    WHY THIS MATTERS: level_3 is not a label, it is an open gate. `may_act()` returns
    True for anything at or above IRREVERSIBLE_MIN(2), and `_witness_or_refuse` lets
    `execute_patches` run on that True. Full trust on a self-modification step means
    the system may rewrite itself with nothing standing in the way — and, because the
    inheritance loop iterates over `inputs`, an empty or all-phantom input list also
    silently disables the one mechanism that could let a distrusted upstream product
    taint it.

    This asserts the INVARIANT, not the current bug. It is deliberately indifferent
    to *why* the level is below 3 — today it is the phantom filename, tomorrow it
    should be an honest treatment of unknown provenance. It goes red the moment the
    step becomes fully trusted, whichever cleanup got it there.
    """
    notary = healthy_environment
    rec = notary.attest(STEP)

    assert rec["level"] < notary.FULL, (
        f"{STEP} reached {rec['level_name']} — THE GATE ON SELF-MODIFICATION IS OPEN.\n"
        f"  vector : {rec['vector']}\n"
        f"  why    : {rec['why']}\n"
        f"  inputs : {rec['inputs']}\n\n"
        f"If you just removed {PHANTOM!r} from core/metta_check.py:_IGNORE, or "
        f"corrected it to {REAL_FILE!r}, that is this failure.\n"
        f"core/notary.py:_age_state returns FULL for an empty inputs list, so "
        f"removing the only missing file promotes this step to the maximum stamp.\n"
        f"Fix _age_state's treatment of the unknown in the SAME change, or the "
        f"cleanup is a regression.")

    ok, why = notary.may_act(STEP)
    assert not ok, f"may_act({STEP!r}) permitted an irreversible action: {why}"


def test_an_empty_inputs_list_is_not_a_reason_to_trust(notary):
    """An empty requires list is ignorance, and ignorance is not evidence of freshness.

    core/cycle_graph.py:23-26 states the rule the graph was written to establish:

        „Каквото не е изведено, стои като НЕИЗВЕСТНО — и неизвестното НЕ е
         пропускаемо. Точно обратното на старото правило, където необявеното
         минаваше за безопасно."

    core/notary.py:_age_state used to do the old thing:

        if not inputs:
            return FULL, "стъпката не чете входове"

    Empty means the harvester found nothing, and it finds nothing constantly: 32 of
    52 steps harvest to `[]`, including `self_modifier` and `github_publish`, both of
    which are irreversible and both of which passed the gate at level_3 on every
    attestation on record. The harvester cannot see modules reached through
    `__import__(...)` or through a wrapper, so "no inputs" is usually a statement
    about the scanner, not about the step.

    THIS TEST WAS AN xfail(strict=True) UNTIL 17 AUG 2026 — a specification held open
    where it could be seen, rather than a claim that the code was right. The flip
    landed and the marker came off: `_age_state([])` now returns UNKNOWN. Keep it
    passing. If it ever fails again, the fail-open has come back.
    """
    level, why = notary._age_state([])
    assert level != notary.FULL, (
        f"_age_state([]) returned FULL({notary.FULL}) with reason {why!r} — "
        f"an empty inputs list is being read as proof of freshness.")


def test_the_explicit_ceiling_is_the_thing_holding_the_gate(
        healthy_environment, live_harvest, phantom_is_the_only_gap, monkeypatch):
    """Tripwire: name what is ACTUALLY load-bearing, and PROVE it is.

    THIS TEST REPLACED A TRIPWIRE ON THE PHANTOM (31 Aug 2026), and the reason is
    the whole point of the file. Until 21 Aug the gate was held shut by
    `memory/last_attempt.txt` - a truncation of `memory/last_attempted_cycle_id.txt`
    that nothing anywhere writes. `_age_state` could not stat it, age fell to
    UNKNOWN, and the step that rewrites this system's own source was refused. The
    invariant was resting on a typo, and the old version of this test asserted the
    typo was still there.

    Commit 8b0bca6 (21 Aug) then declared the step's real input in
    config/step_inputs.json - correctly, because the notary was refusing for
    ignorance rather than for fault. The declaration beat the scanner, the phantom
    left the harvest, and the gate SWUNG OPEN. Measured in the live attestation
    chain: 2026-08-30T12:57:14 level=3, own=3, vector all threes, may_act True. It
    stayed open ten days. On 31 Aug it read level_2 only because the human channel
    had gone quiet for seven days - an accident standing in for a guard.

    So the phantom is no longer load-bearing and asserting that it is would be a
    lie. What holds the gate now is core/notary.MAX_LEVEL: a STATED ceiling. This
    test guards that, the same way the old one guarded the typo - by naming it and
    then removing it to watch the gate swing open.
    """
    notary = healthy_environment

    # 1. The ceiling exists, names this step, and sits below the action threshold.
    assert STEP in notary.MAX_LEVEL, (
        f"{STEP!r} has no entry in core/notary.MAX_LEVEL. The invariant "
        f"'{STEP} must never reach full trust' is back to resting on whatever "
        f"happens to be missing that night. See Ц3а, ruled 31 Aug 2026.")
    ceiling = notary.MAX_LEVEL[STEP]
    assert ceiling < notary.FULL, (
        f"the ceiling for {STEP!r} is {ceiling}, which is full trust - it caps "
        f"nothing")
    assert ceiling < notary.IRREVERSIBLE_MIN, (
        f"the ceiling for {STEP!r} is {ceiling}, at or above IRREVERSIBLE_MIN "
        f"({notary.IRREVERSIBLE_MIN}), so may_act() still permits the action. "
        f"Ц3а closed this gate by decision; raising it is AMENDMENT_001's "
        f"business and the cooling-off ends 19 Oct 2026.")

    # 2. It is the ceiling doing the work, and the refusal SAYS so.
    rec = notary.attest(STEP)
    assert rec["ceiling_binds"], (
        f"the ceiling is not binding: own={rec['own']}, ceiling={ceiling}. "
        f"Something else is holding the gate and this tripwire is not guarding "
        f"what it claims to guard.")
    ok, why = notary.may_act(STEP)
    assert not ok, f"may_act({STEP!r}) permitted an irreversible action: {why}"
    assert "ceiling" in why, (
        f"the refusal does not name the ceiling as its reason: {why!r}. A "
        f"decision a human made must not be blamed on an innocent input.")

    # 3. POSITIVE CONTROL. A guard that only ever asserts the safe state cannot
    #    tell you whether it is still guarding anything. Take the ceiling away and
    #    the gate must swing open - which is exactly what happened for ten days.
    monkeypatch.setattr(notary, "MAX_LEVEL", {})
    # FROM A CLEAN CHAIN. The capped attestations above stamped this step's own
    # products at the capped level, and execute_patches writes
    # memory/development_journal.json - which is also its declared input. Left
    # in place, the control would inherit level_1 from itself and "prove" the
    # ceiling was still binding after we removed it. (That self-inheritance is
    # correct behaviour in production: a capped step's outputs should carry the
    # reduced trust onward. It is only a contaminant here.)
    notary.ATTEST_LOG.write_text("", encoding="utf-8")
    rec_open = notary.attest(STEP)
    ok_open, _ = notary.may_act(STEP)
    assert rec_open["level"] == notary.FULL and ok_open, (
        f"with MAX_LEVEL emptied, {STEP} did NOT return to full trust "
        f"(got {rec_open['level_name']}, may_act={ok_open}, "
        f"vector={rec_open['vector']}). "
        f"The ceiling may no longer be the load-bearing thing. Find out what "
        f"else is holding the gate before trusting the green - that is the "
        f"mistake this file was written after.")


def test_the_phantom_is_no_longer_load_bearing_and_that_is_recorded():
    """The phantom string may still sit in _IGNORE; it must not be RELIED on.

    Kept as a fact, not a guard. If someone deletes `memory/last_attempt.txt`
    from core/metta_check.py:_IGNORE tomorrow, nothing about the gate changes -
    and this test says so out loud, so that the next reader of the file heading
    does not go looking for a coupling that was severed on 21 Aug 2026.
    """
    assert PHANTOM not in live_harvest_for(STEP), (
        f"{PHANTOM!r} is back in {STEP}'s harvest. That is not a restored "
        f"safety net - it is the typo returning. The gate is held by "
        f"core/notary.MAX_LEVEL now; see "
        f"test_the_explicit_ceiling_is_the_thing_holding_the_gate.")


def live_harvest_for(step: str) -> list:
    """The requires the REAL harvester derives right now, for one step."""
    from core.cycle_graph import scan_requires
    return scan_requires().get(step, [])

def test_an_unstated_predecessor_is_not_a_kept_promise(notary):
    """Nobody-said is UNKNOWN, not FULL.

    THE STAKE: this is the dimension that answers "did the step before this one
    actually produce what it promised". Defaulting it to FULL means the gate asks
    the question and accepts silence as a yes — on github_publish, which writes to a
    public repository, and self_modifier, which writes generated Python.
    """
    for absent in (None, notary.PREV_UNKNOWN, "", "   "):
        lvl, why = notary._promise_state(absent, "some_step")
        assert lvl == notary.UNKNOWN, (
            f"_promise_state({absent!r}) returned {lvl}, not UNKNOWN — an unstated "
            f"predecessor is being read as a kept promise ({why!r})")


def test_a_step_is_not_its_own_predecessor(notary):
    """prev_step == step must be UNKNOWN, never KEPT.

    All 53 brain rows on 17 Aug carry prev_step == step, because
    core/brain.py::_prev_step_output() reads the last `[STEP]` line of the cycle log
    and memory/heartbeat.py::beat() writes that line BEFORE calling the brain. So the
    "previous" step is the current one. This assertion does not repair that — it
    stops its output being scored as evidence.
    """
    lvl, why = notary._promise_state("github_publish", "github_publish")
    assert lvl == notary.UNKNOWN, (
        f"a step comparing against itself scored {lvl} ({why!r}) — self-comparison "
        f"is not evidence that a promise was kept")
    assert "себе си" in why or "own predecessor" in why.lower()


def test_explicitly_declared_first_step_is_the_only_full(notary):
    """POSITIVE CONTROL. If every input scored UNKNOWN the tests above would pass on
    a function that always returns 0, which would be a wall rather than a gate.
    Exactly one input means trust, and it has to be said out loud."""
    lvl, why = notary._promise_state(notary.PREV_NONE, "boot")
    assert lvl == notary.FULL, f"PREV_NONE must be FULL, got {lvl} ({why!r})"

    # ...and a real, different predecessor is evaluated rather than short-circuited.
    lvl2, why2 = notary._promise_state("self_observer", "self_modifier")
    assert lvl2 != notary.FULL or "self_observer" in why2, (
        "a genuine predecessor should be CHECKED, not waved through")


def test_may_act_defaults_to_unknown_not_trust(notary):
    """The default argument itself must not mean trust.

    A caller that forgets prev_step should lose a dimension, not gain one.
    """
    import inspect
    default = inspect.signature(notary.may_act).parameters["prev_step"].default
    assert default == notary.PREV_UNKNOWN, (
        f"may_act's prev_step defaults to {default!r} — the default must be the "
        f"UNKNOWN marker, never None-meaning-FULL and never a real step name")
    assert notary._promise_state(default, "x")[0] == notary.UNKNOWN


def test_the_gate_call_sites_pass_a_real_predecessor():
    """fast_cycle_runner must hand the gate the step that actually ran before.

    Source-structure: the predecessors come from the beat() order in the runner
    itself — github_publish <- hyperclaw_plan, self_modifier <- self_observer,
    execute_patches <- self_modifier — not from the cycle log, which reports the
    current step as its own predecessor.
    """
    import re
    src = (REPO_ROOT / "fast_cycle_runner.py").read_text(encoding="utf-8-sig")
    calls = dict(re.findall(r'_witness_or_refuse\("([^"]+)",\s*"([^"]+)"\)', src))

    expected = {"github_publish": "hyperclaw_plan",
                "self_modifier": "self_observer",
                "execute_patches": "self_modifier"}
    assert calls == expected, (
        f"gate call sites pass {calls}, expected {expected}. If the runner's step "
        f"order changed, re-derive from the beat() sequence — do not guess.")
    assert not re.search(r'_witness_or_refuse\("[^"]+"\)\s*[:)]', src), \
        "a gate call site is still passing only the step, with no predecessor"
