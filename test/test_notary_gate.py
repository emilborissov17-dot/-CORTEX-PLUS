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

DO NOT "FIX" THE TYPO IN ISOLATION. IT OPENS THE GATE.
-------------------------------------------------------
`core/notary.py:_age_state` returns FULL(3) for an EMPTY inputs list
("стъпката не чете входове"). So both obvious cleanups are unsafe:

    filter _IGNORE out of the harvest -> inputs = []  -> age FULL -> level_3
    correct the name to a real file   -> all inputs exist -> age FULL -> level_3

Either way `own` becomes 3, the inheritance loop `for rel in inputs:` stops running
at all, and the step that rewrites the system's own source carries level_3 — the
maximum stamp the notary can issue, comfortably over IRREVERSIBLE_MIN(2).

This is not hypothetical. The same defect ALREADY runs in the open direction:
`self_modifier` and `github_publish` both harvest to `[]` and have passed the gate
at level_3 on every attestation on record.

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
    monkeypatch.setattr(notary, "_promise_state",
                        lambda prev: (notary.FULL, "forced FULL for this test"))
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


@pytest.mark.xfail(
    strict=True,
    reason="core/cycle_graph.py:23-26 promises the unknown is not passable; "
           "_age_state does the opposite. When this xfail starts PASSING, the "
           "design has been made consistent.")
def test_an_empty_inputs_list_is_not_a_reason_to_trust(notary):
    """An empty requires list is ignorance, and ignorance is not evidence of freshness.

    core/cycle_graph.py:23-26 states the rule the graph was written to establish:

        „Каквото не е изведено, стои като НЕИЗВЕСТНО — и неизвестното НЕ е
         пропускаемо. Точно обратното на старото правило, където необявеното
         минаваше за безопасно."

    core/notary.py:_age_state does the old thing:

        if not inputs:
            return FULL, "стъпката не чете входове"

    Empty means the harvester found nothing, and it finds nothing constantly: 32 of
    52 steps harvest to `[]`, including `self_modifier` and `github_publish`, both of
    which are irreversible and both of which have passed the gate at level_3 on every
    attestation on record. The harvester cannot see modules reached through
    `__import__(...)` or through a wrapper, so "no inputs" is usually a statement
    about the scanner, not about the step.

    EXPECTED TO FAIL TODAY. It is not a bug report against a line of code — it is the
    contradiction between two files, held open where it can be seen.
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
