"""The ledger that proves the extra calls did not cost the cycle.

core/extra_calls.py guards each call; this measures whether the guarding
worked. The unit of judgement is the PHASE and the CYCLE, not the call: the
fear was never one slow reaction, it was 126 of them quietly adding a fifth to
the night with no single line looking wrong.

The boundary tests below are the whole point. A ceiling that fires at 15% and
also at 14.9% is a ceiling nobody can plan against.
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import extra_calls as ec            # noqa: E402
from core import extra_calls_ledger as led    # noqa: E402


@pytest.fixture
def sandbox(tmp_path):
    """Every path this module can write, pointed away from the repo."""
    return {"path": tmp_path / "log.jsonl",
            "flag_path": tmp_path / "suspended.flag",
            "proposals_path": tmp_path / "proposals.json"}


def _boom(*_a, **_k):
    raise OSError("down")


@pytest.fixture
def roomy(monkeypatch):
    """A machine with room and an idle GPU.

    Without this the outcome depends on how busy this laptop happens to be:
    the first run of the test below recorded SKIPPED_RESOURCES because the
    full suite was running beside it, which is the door working correctly and
    the test asking the wrong question.
    """
    monkeypatch.setattr(ec, "_ram_free_mb", lambda: 8000.0)
    monkeypatch.setattr(ec, "_vram_free_mb", lambda: (8000.0, None))
    monkeypatch.setattr(ec, "_models_running", lambda *a, **k: (0, None))


def _cycle(sb, cycle_id, phase_ms, cycle_s, phase="E_PROPOSE"):
    led.record("COMPLETED", cycle_id, phase, "reaction",
               phase_total_time_ms=phase_ms, path=sb["path"])
    return led.seal_cycle(cycle_id, cycle_s, **sb)


# -- the ceiling, at the edge --------------------------------------------

def test_a_phase_at_15_1_percent_is_a_breach(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    s = _cycle(sandbox, "C2", 1151, 100.0)
    assert s["worst_phase_delta_percent"] == 15.1
    assert s["phase_breach"] is True
    assert s["breach"] is True


def test_a_phase_at_14_9_percent_is_not(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    s = _cycle(sandbox, "C2", 1149, 100.0)
    assert s["worst_phase_delta_percent"] == 14.9
    assert s["phase_breach"] is False, (
        "the ceiling fired below itself; a ceiling nobody can plan against")
    assert s["breach"] is False


def test_exactly_15_percent_is_not_a_breach(sandbox):
    """Strictly greater. 15.0 is the ceiling, not past it."""
    _cycle(sandbox, "C1", 1000, 100.0)
    s = _cycle(sandbox, "C2", 1150, 100.0)
    assert s["worst_phase_delta_percent"] == 15.0
    assert s["phase_breach"] is False


def test_a_cycle_at_10_1_percent_is_a_breach(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    s = _cycle(sandbox, "C2", 1000, 110.1)
    assert s["cycle_delta_percent"] == 10.1
    assert s["cycle_breach"] is True
    assert s["phase_breach"] is False, "the phase was flat; only the cycle moved"


def test_a_cycle_at_9_9_percent_is_not(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    s = _cycle(sandbox, "C2", 1000, 109.9)
    assert s["cycle_delta_percent"] == 9.9
    assert s["cycle_breach"] is False
    assert s["breach"] is False


def test_exactly_10_percent_is_not_a_breach(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    s = _cycle(sandbox, "C2", 1000, 110.0)
    assert s["cycle_delta_percent"] == 10.0
    assert s["cycle_breach"] is False


def test_either_one_alone_is_enough(sandbox):
    """OR, not AND. A phase can double while the night stays the same length."""
    _cycle(sandbox, "C1", 1000, 100.0)
    s = _cycle(sandbox, "C2", 2000, 100.0)
    assert s["cycle_breach"] is False and s["phase_breach"] is True
    assert s["breach"] is True


# -- no history is not a baseline of zero --------------------------------

def test_the_first_cycle_cannot_breach(sandbox):
    r = led.record("COMPLETED", "C1", "E_PROPOSE", "reaction",
                   phase_total_time_ms=99999, path=sandbox["path"])
    assert r["baseline_phase_time_ms"] is None
    assert r["delta_percent"] is None, (
        "an absent baseline was read as zero, which makes every first night a "
        "100% regression")
    assert "does not exist" in r["baseline_why"]
    s = led.seal_cycle("C1", 99999.0, **sandbox)
    assert s["breach"] is False
    assert not sandbox["flag_path"].exists()


def test_a_phase_never_seen_before_has_no_baseline_even_late(sandbox):
    for i in range(5):
        _cycle(sandbox, "C%d" % i, 1000, 100.0, phase="E_PROPOSE")
    r = led.record("COMPLETED", "C9", "G_LEARN", "perplexity",
                   phase_total_time_ms=50000, path=sandbox["path"])
    assert r["baseline_phase_time_ms"] is None, (
        "one phase's history was used as another phase's baseline")


# -- the baseline is per cycle, and it is the last ten --------------------

def test_four_calls_in_one_phase_do_not_weigh_four_times(sandbox):
    for _ in range(4):
        led.record("COMPLETED", "C1", "E_PROPOSE", "reaction",
                   phase_total_time_ms=1000, path=sandbox["path"])
    led.seal_cycle("C1", 100.0, **sandbox)
    led.record("COMPLETED", "C2", "E_PROPOSE", "reaction",
               phase_total_time_ms=3000, path=sandbox["path"])
    led.seal_cycle("C2", 100.0, **sandbox)
    base, n = led.phase_baseline_ms("E_PROPOSE", exclude_cycle_id="C3",
                                    path=sandbox["path"])
    assert n == 2, "rows were counted instead of cycles: %r" % n
    assert base == 2000.0


def test_only_the_last_ten_cycles_count(sandbox):
    for i in range(10):
        _cycle(sandbox, "OLD%d" % i, 100, 10.0)
    for i in range(10):
        _cycle(sandbox, "NEW%d" % i, 1000, 100.0)
    base, n = led.phase_baseline_ms("E_PROPOSE", path=sandbox["path"])
    assert n == 10
    assert base == 1000.0, (
        "the baseline reached past ten cycles, so a machine that got slower "
        "for good reasons would breach for ever")


def test_a_cycle_is_not_its_own_baseline(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    led.record("COMPLETED", "C2", "E_PROPOSE", "reaction",
               phase_total_time_ms=5000, path=sandbox["path"])
    r = led.record("COMPLETED", "C2", "E_PROPOSE", "perplexity",
                   phase_total_time_ms=5000, path=sandbox["path"])
    assert r["baseline_phase_time_ms"] == 1000.0, (
        "the second call in a phase was measured against the first one, so a "
        "slow phase would normalise itself mid-flight")


# -- the skips are in there too ------------------------------------------

@pytest.mark.parametrize("outcome", [ec.SKIPPED_BUSY, ec.SKIPPED_RESOURCES,
                                     ec.TIMEOUT, ec.BREAKER_OFF])
def test_attempts_that_never_became_calls_are_still_recorded(sandbox, outcome):
    led.record(outcome, "C1", "E_PROPOSE", "reaction", queue_wait_ms=5000,
               phase_total_time_ms=1000, path=sandbox["path"])
    rows = [json.loads(l) for l in
            sandbox["path"].read_text(encoding="utf-8").splitlines()]
    assert rows[0]["outcome"] == outcome
    assert rows[0]["queue_wait_ms"] == 5000, (
        "a skip that spent five seconds polling was recorded as free")


# -- what the breach does ------------------------------------------------

def test_the_breach_names_the_numbers_in_a_pending_item(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    _cycle(sandbox, "C2", 1151, 100.0)
    blob = json.loads(sandbox["proposals_path"].read_text(encoding="utf-8"))
    item = blob["proposals"][-1]
    assert item["generated_by"] == "EXTRA_CALLS_BREACH"
    for number in ("E_PROPOSE", "1151", "1000", "15.1"):
        assert number in item["problem"], (
            "the pending item does not name %r, so nobody can act on it: %s"
            % (number, item["problem"]))


def test_the_flag_is_written_and_says_who_may_switch_things_off(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    _cycle(sandbox, "C2", 1151, 100.0)
    assert sandbox["flag_path"].exists()
    d = json.loads(sandbox["flag_path"].read_text(encoding="utf-8"))
    assert d["cycle_id"] == "C2"
    assert "reactions.json" in d["note"], (
        "the flag does not say that the switches are human-written, and the "
        "next reader of it is deciding whether to go and flip one")


def test_one_clean_cycle_clears_the_flag(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    _cycle(sandbox, "C2", 1151, 100.0)
    assert sandbox["flag_path"].exists()
    s = _cycle(sandbox, "C3", 1000, 100.0)
    assert s["suspension_cleared"] is True
    assert not sandbox["flag_path"].exists()


def test_a_second_breach_does_not_clear_the_flag(sandbox):
    _cycle(sandbox, "C1", 1000, 100.0)
    _cycle(sandbox, "C2", 1151, 100.0)
    _cycle(sandbox, "C3", 5000, 100.0)
    assert sandbox["flag_path"].exists()


def test_the_flag_stops_the_next_call_at_the_door(sandbox):
    sandbox["flag_path"].write_text("{}", encoding="utf-8")
    called = []
    r = ec.guarded_extra_call("reaction", "hi",
                              flag_path=sandbox["flag_path"],
                              opener=lambda *a, **k: called.append(1),
                              sleep=lambda *_: None)
    assert r["outcome"] == ec.SKIPPED_SUSPENDED
    assert not called, "a call went out while extra calls were suspended"


def test_the_flag_is_checked_before_resources_are_even_read(sandbox, monkeypatch):
    """Nothing to measure and no room to argue: it is the previous verdict."""
    sandbox["flag_path"].write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ec, "_ram_free_mb",
                        lambda: pytest.fail("resources were read anyway"))
    r = ec.guarded_extra_call("x", "hi", flag_path=sandbox["flag_path"])
    assert r["outcome"] == ec.SKIPPED_SUSPENDED


# -- the door writes the line, and only when there is a cycle -------------

def test_the_door_writes_one_line_per_attempt(sandbox, roomy):
    ec.reset_cycle()
    ec.guarded_extra_call(
        "reaction", "hi", cycle={"cycle_id": "C7", "phase": "E_PROPOSE",
                                 "phase_total_time_ms": 1000},
        flag_path=sandbox["flag_path"], ledger_path=sandbox["path"],
        opener=_boom, sleep=lambda *_: None)
    ec.reset_cycle()
    rows = [json.loads(l) for l in
            sandbox["path"].read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["cycle_id"] == "C7" and rows[0]["outcome"] == ec.FAILED


def test_without_a_cycle_the_door_writes_nothing(sandbox, roomy):
    """Which is what keeps every other test in the suite off the real ledger."""
    ec.reset_cycle()
    ec.guarded_extra_call("reaction", "hi", flag_path=sandbox["flag_path"],
                          ledger_path=sandbox["path"], opener=_boom,
                          sleep=lambda *_: None)
    ec.reset_cycle()
    assert not sandbox["path"].exists()


# -- the switches stay Emil's -------------------------------------------

def test_the_ledger_never_writes_the_switch_file():
    src = (REPO / "core" / "extra_calls_ledger.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name in ("write_text", "dump", "writelines", "unlink"):
                ctx = "\n".join(src.splitlines()[max(0, n.lineno - 5):n.lineno])
                assert "reactions.json" not in ctx and "REACTIONS" not in ctx, (
                    "the ledger writes config/reactions.json at line %d" % n.lineno)


def test_a_breach_leaves_the_live_files_byte_identical(sandbox):
    watched = [REPO / "config" / "reactions.json",
               REPO / "memory" / "improvement_proposals.json"]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in watched if p.exists()}
    assert before, "nothing was actually being watched"
    _cycle(sandbox, "C1", 1000, 100.0)
    _cycle(sandbox, "C2", 1151, 100.0)
    for p, h in before.items():
        assert hashlib.sha256(p.read_bytes()).hexdigest() == h, (
            "%s changed while a sandboxed breach was being tested" % p.name)
    assert not (REPO / "memory" / "extra_calls_suspended.flag").exists()


def test_the_module_dry_runs_when_run_bare():
    """Three live-state breaches happened on 27 Aug. Looking is free."""
    src = (REPO / "core" / "extra_calls_ledger.py").read_text(encoding="utf-8-sig")
    assert "DRY RUN" in src
    tree = ast.parse(src)
    main = [n for n in tree.body if isinstance(n, ast.If)
            and getattr(getattr(n.test, "left", None), "id", None) == "__name__"]
    assert main, "no __main__ guard"
    # CALLS, not the word. The __main__ block names seal_cycle in the sentence
    # it prints, and a test that greps the dump would fail on the explanation
    # rather than on the behaviour.
    called = {n.func.id for n in ast.walk(main[0])
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"seal_cycle", "record", "_suspend", "_raise_pending"}, (
        "running this module bare would write to the real ledger: %s" % called)


def test_the_cycle_actually_closes_the_ledger():
    """A ledger nothing seals is a file, not a measurement."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    seals = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "seal_cycle"]
    assert len(seals) == 1, (
        "fast_cycle_runner seals the extra-calls ledger %d times" % len(seals))


def test_the_door_is_the_only_thing_that_writes_a_row():
    """Two callers each remembering to log is two chances to forget."""
    writers = []
    for p in sorted(REPO.glob("*.py")) + sorted((REPO / "core").glob("*.py")):
        if p.name in ("extra_calls.py", "extra_calls_ledger.py"):
            continue
        tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "record"
                    and getattr(n.func.value, "id", "").endswith(("led", "_ecl",
                                                                  "ledger"))):
                writers.append("%s:%d" % (p.name, n.lineno))
    assert not writers, (
        "something other than the guarded door appends ledger rows: %s" % writers)
