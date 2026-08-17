"""Not looking must never be worth more than looking and not liking what you see.

THE DEFECT (measured 17 Aug 2026, before the fix)
--------------------------------------------------
`core/notary.py:_human_state` graded the human channel like this:

    no record at all (never checked)  -> REDUCED(2)   PASSES the gate
    record unreadable                 -> REDUCED(2)   PASSES the gate
    checked, channel DEAD             -> UNKNOWN(0)   blocks
    alive, ZERO human messages ever   -> FULL(3)      PASSES the gate

IRREVERSIBLE_MIN is REDUCED, so two of those three permissive rows opened the
gate on github_publish, self_modifier and execute_patches. The cheapest way
through the notary was to never look: absence of a check scored two levels above
a check that came back bad. And the top grade — the highest confidence this
system can express about human provenance — was being awarded to the fact that
an HTTP endpoint returned 200 with an empty body.

WHY NOBODY NOTICED
------------------
`test_notary_gate.py::healthy_environment` monkeypatches `_human_state` to FULL,
by design, to isolate the `age` dimension. Every other notary test inherits it.
So the suite had a positive control for the gate opening — and it ran with the
human dimension stubbed out. The real function was never once executed by a test.
That is the gap this file closes; see
test_the_gate_can_say_yes_through_the_real_human_channel.

WHAT THE CHANNEL CAN AND CANNOT PROVE
--------------------------------------
    REACHABILITY  Telegram answered 200. The transport works. Says nothing
                  whatsoever about a human.
    ATTENDANCE    a human actually wrote something recently. Weak, but real.
    CONSENT       a human approved THIS action. The channel can NEVER show this
                  — consent is per-action and lives in pending_approvals /
                  declined_approvals, not in a liveness probe.

The grading now caps at what is actually witnessed: FULL requires attendance,
reachability alone earns at most REDUCED, and nothing here ever claims consent.
"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

NOTARY_SRC = REPO / "core" / "notary.py"
STEP = "self_modifier"


def _pristine_notary():
    """An unpatched copy of core/notary.py — see test_notary_gate.py for why."""
    spec = importlib.util.spec_from_file_location("_notary_human_under_test", NOTARY_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def notary(tmp_path, monkeypatch):
    mod = _pristine_notary()
    chain = tmp_path / "attestation"
    chain.mkdir()
    monkeypatch.setattr(mod, "ATTEST_DIR", chain)
    monkeypatch.setattr(mod, "ATTEST_LOG", chain / "attest.jsonl")
    monkeypatch.setattr(mod, "ATTEST_HEAD", chain / "chain.head")
    return mod


@pytest.fixture
def channel(tmp_path, monkeypatch):
    """Point approve_reader's channel record at a throwaway file.

    Returns a writer. `None` means NO RECORD AT ALL — the never-checked case,
    which is the whole subject of this file.
    """
    from experiments.needs import approve_reader as ar
    path = tmp_path / "human_channel_state.json"
    monkeypatch.setattr(ar, "CHANNEL_STATE", path)

    def write(doc):
        if doc is None:
            if path.exists():
                path.unlink()
            return path
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path

    return write


def _now():
    return datetime.now(timezone.utc)


def _alive(hours_since_check=0.0, human_hours_ago=None, msgs=0):
    doc = {"ts": (_now() - timedelta(hours=hours_since_check)).isoformat(),
           "state": "alive", "why": f"200 OK, {msgs} нови съобщения",
           "human_msgs": msgs, "last_human_msg_utc": None}
    if human_hours_ago is not None:
        doc["last_human_msg_utc"] = (_now() - timedelta(hours=human_hours_ago)).isoformat()
    return doc


# ---------------------------------------------------------------------------
# THE INVARIANT
# ---------------------------------------------------------------------------

def test_failure_to_check_never_outranks_a_checked_failure(notary, channel):
    """The rule, stated as an ordering over every state the channel can be in.

    A checked failure (dead) is the worst honest news there is. Nothing that
    represents NOT KNOWING may score above it, or the cheapest route through the
    gate is to make sure no check ever happens.
    """
    channel({"ts": _now().isoformat(), "state": "dead", "why": "HTTP 000"})
    checked_failure, _ = notary._human_state()

    unchecked = {}
    channel(None)
    unchecked["no record at all"] = notary._human_state()[0]
    corrupt = channel(None)
    corrupt.write_text("{ not json", encoding="utf-8")
    unchecked["record unreadable"] = notary._human_state()[0]
    channel({"ts": _now().isoformat(), "why": "no state field"})
    unchecked["record has no state"] = notary._human_state()[0]

    for label, lvl in unchecked.items():
        assert lvl <= checked_failure, (
            f"{label!r} scored {lvl} while a CHECKED dead channel scored "
            f"{checked_failure}. Not looking is now worth more than looking — "
            f"which makes 'never run approve_reader' the cheapest way through "
            f"the irreversible gate.")
        assert lvl < notary.IRREVERSIBLE_MIN, (
            f"{label!r} scored {lvl}, at or above IRREVERSIBLE_MIN "
            f"({notary.IRREVERSIBLE_MIN}) — an unchecked channel is authorising "
            f"github_publish / self_modifier / execute_patches")


def test_transport_liveness_is_not_a_human(notary, channel):
    """200 OK with an empty inbox used to earn FULL — the top grade for human
    provenance, awarded to a fact about an HTTP endpoint."""
    channel(_alive(msgs=0))
    lvl, why = notary._human_state()

    assert lvl < notary.FULL, (
        f"a reachable channel with no human activity scored {lvl} (FULL is "
        f"{notary.FULL}). Reachability is not attendance and neither is consent: "
        f"why={why!r}")
    assert lvl == notary.REDUCED, f"expected REDUCED for a live-but-silent channel, got {lvl}"


def test_a_human_who_actually_wrote_earns_more_than_one_who_did_not(notary, channel):
    """The distinction the old grading could not make at all."""
    channel(_alive(msgs=0))
    silent, _ = notary._human_state()
    channel(_alive(human_hours_ago=2, msgs=1))
    attended, why = notary._human_state()

    assert attended > silent, (
        "a channel a human actually wrote to scores no higher than one nobody "
        "has ever touched — the attendance evidence is not being read")
    assert attended == notary.FULL
    assert "човек е писал" in why


def test_a_stale_check_decays_below_the_gate(notary, channel):
    """A record from last night describes last night, not now."""
    channel(_alive(hours_since_check=notary.HUMAN_CHECK_FRESH_H + 14,
                   human_hours_ago=1, msgs=1))
    lvl, why = notary._human_state()
    assert lvl < notary.IRREVERSIBLE_MIN, (
        f"a check {notary.HUMAN_CHECK_FRESH_H + 14}h old still authorises "
        f"irreversible action (level {lvl}): {why}")


def test_an_unconfigured_channel_is_known_but_still_blocks(notary, channel):
    """not_configured is a CHECKED answer, so it may rank above 'dead' — but
    there is no path to a human, so it must not reach the gate."""
    channel({"ts": _now().isoformat(), "state": "not_configured", "why": "no token"})
    lvl, _ = notary._human_state()
    assert lvl == notary.MINIMAL
    assert lvl < notary.IRREVERSIBLE_MIN


def test_channel_alive_refuses_when_it_was_never_checked(channel):
    """The runner's own fast pre-filter, `_witness_or_refuse`, reads this bool.

    It used to return True with "няма запис за канала — не се третира като отказ",
    so an unchecked channel sailed past the runner too.
    """
    from experiments.needs import approve_reader as ar
    channel(None)
    ok, why = ar.channel_alive()
    assert ok is False, f"an unchecked channel reported itself alive: {why}"

    channel(_alive(msgs=1, human_hours_ago=1))
    ok, _ = ar.channel_alive()
    assert ok is True, "a live channel is being reported dead — the fix overshot"


# ---------------------------------------------------------------------------
# THE POSITIVE CONTROL THE SUITE DID NOT HAVE
# ---------------------------------------------------------------------------

def test_the_gate_can_say_yes_through_the_real_human_channel(notary, channel, monkeypatch):
    """may_act() must be able to return True with `_human_state` NOT stubbed.

    Every existing notary test runs under `healthy_environment`, which pins
    `_human_state` to FULL. So the suite proved the gate could open, and proved
    nothing at all about the function that decides the human dimension — the one
    that had been handing REDUCED to a channel nobody had ever checked.

    Here the other four dimensions are pinned instead, and the human dimension is
    the real code reading a real record. Both directions are asserted in the same
    test, so a `_human_state` that returned a constant — FULL or UNKNOWN — fails.
    """
    for name in ("_witness_state", "_thought_state"):
        monkeypatch.setattr(notary, name,
                            lambda: (notary.FULL, "pinned for this test"))
    monkeypatch.setattr(notary, "_age_state",
                        lambda *_a: (notary.FULL, "pinned for this test"))
    monkeypatch.setattr(notary, "_promise_state",
                        lambda *_a: (notary.FULL, "pinned for this test"))

    # A human wrote an hour ago and the channel was checked just now: the best
    # honest state this system can actually be in.
    channel(_alive(human_hours_ago=1, msgs=1))
    ok, why = notary.may_act(STEP, prev_step="canon_load")
    assert ok, (
        f"the gate cannot open even on the best night this system can have: "
        f"{why}. If the human dimension can never reach REDUCED, the three "
        f"irreversible steps are dead code and nobody is being told.")

    # ...and the same call must refuse when the channel was never checked.
    channel(None)
    ok_unchecked, why_unchecked = notary.may_act(STEP, prev_step="canon_load")
    assert not ok_unchecked, (
        f"the gate opened with NO channel record at all: {why_unchecked}")

    assert ok != ok_unchecked, \
        "may_act returned the same answer either way — it is not reading the channel"
