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


def test_the_phantom_is_still_the_thing_holding_the_gate(
        healthy_environment, live_harvest, phantom_is_the_only_gap, monkeypatch):
    """Tripwire: name the load-bearing typo, and PROVE it is load-bearing.

    This is the narrow, literal guard that the invariant test above cannot give you —
    a failure message that says WHICH string was removed and WHY the removal matters.

    The last assertion is a POSITIVE CONTROL. A guard that only ever asserts the safe
    state cannot tell you whether it is still guarding anything; this one re-runs the
    real notary with the phantom filtered out and checks that the level really does
    jump to FULL. If that stops being true, either the coupling is gone (good — this
    whole file is obsolete, delete it) or something else changed underneath it (bad —
    find out what before trusting the green).

    Expected to become obsolete: once `_age_state` treats emptiness and absence
    honestly, delete this test. Until then, removing the phantom without touching
    `_age_state` should cost somebody a red suite and thirty seconds of reading.
    """
    from core.metta_check import _IGNORE
    notary = healthy_environment
    mc = importlib.import_module("core.metta_check")

    assert PHANTOM in _IGNORE, (
        f"{PHANTOM!r} is gone from core/metta_check.py:_IGNORE.\n"
        f"That string is a phantom — a truncation of {REAL_FILE!r}, with no writer "
        f"anywhere in the repo — and removing it is not a cleanup: it is the only "
        f"missing input on {STEP}, therefore the only thing keeping the notary's "
        f"gate on self-modification shut.\n"
        f"Removing it hands {STEP} level_3. Read the docstring at the top of this "
        f"file before deciding this test is wrong.")

    assert PHANTOM in live_harvest, (
        f"{PHANTOM!r} is still in _IGNORE but no longer reaches {STEP}'s requires.\n"
        f"Harvested instead: {live_harvest}\n"
        f"core/cycle_graph.py:scan_requires() changed. The gate may now be open — "
        f"check test_execute_patches_never_reaches_full_trust.")

    # POSITIVE CONTROL: take the phantom out and watch the gate swing open.
    without = [r for r in live_harvest if r != PHANTOM]
    monkeypatch.setitem(mc._REQ, STEP, without)
    rec = notary.attest(STEP)
    ok, _why = notary.may_act(STEP)

    assert rec["level"] == notary.FULL and ok, (
        f"Removing {PHANTOM!r} no longer promotes {STEP} to full trust "
        f"(got {rec['level_name']}, may_act={ok}, vector={rec['vector']}).\n"
        f"The coupling this file guards has changed. If core/notary.py:_age_state "
        f"was made honest about unknown provenance, this file has done its job — "
        f"delete it. If not, find out what else moved before trusting the green.")


# ---------------------------------------------------------------------------
# THE PROMISE DIMENSION MUST NOT BE FULL BY DEFAULT
#
# may_act() used to call attest(step) with no prev_step. _promise_state(None)
# returned FULL, "няма предишна стъпка" — so at the ONE place the vector is
# enforced, one of its five dimensions was structurally maximal. Measured on the
# live chain, 17 Aug: github_publish attested TWICE in the same second, level_0 from
# the heartbeat (which passes prev_step) and level_3 from the gate (which did not).
# The gate acted on its own row. The audit log and the decision disagreed.
# ---------------------------------------------------------------------------

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
