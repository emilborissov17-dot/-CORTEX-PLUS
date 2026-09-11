# -*- coding: utf-8 -*-
"""
test/test_self_forecast.py — the system's multi-number self-forecast and the
per-kind scoreboard (10 Sep 2026).

TWO BIASES, DOUBLE DEFENSE (claude/NORM_TWO_BIASES_DOUBLE_DEFENSE_7SEP.md):
every guard below has a test that FAILS if the guard is removed. The failure
paths come first; the happy path last.

What a REFUSAL looks like here: `Refused` is RAISED and nothing is appended to
the ledger. The forbidden fallback is a prediction sealed "with a note" after
the night has started, or a rate over two nights presented as a self-model.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROPHECY = REPO / "experiments" / "prophecy"
sys.path.insert(0, str(PROPHECY))
sys.path.insert(0, str(REPO))

import prophecy_ledger as pl  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PROPHECY / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sf = _load("self_forecast")
sb = _load("scoreboard")


# ── fixtures: a private ledger per test, never the real one ─────────────────

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "prophecy_ledger.jsonl"
    monkeypatch.setattr(pl, "LEDGER_PATH", path)
    return path


def _ev(kind, ts, cycle_id, **k):
    return {"event": kind, "ts": ts, "cycle_id": cycle_id, **k}


def _fin(day, dur, degraded):
    cid = f"2026-09-{day:02d}T03:04:02.000000+03:00"
    return [_ev("CYCLE_STARTED", f"2026-09-{day:02d}T00:04:03+00:00", cid),
            _ev("CYCLE_FINISHED", f"2026-09-{day:02d}T02:00:00+00:00", cid,
                duration_sec=dur, degraded_steps=degraded, steps_completed=40)]


def _history(n=5):
    ev = []
    for i in range(1, n + 1):
        ev += _fin(i, 7000 + 100 * i, 1 if i % 2 else 0)
    return ev


def _logs(tmp_path, days, failing=("merkle_to_training",)):
    d = tmp_path / "cycle_logs"
    d.mkdir(exist_ok=True)
    for day in days:
        body = "[STEP] x\n" + "".join(f"[FAST_CYCLE] {s} -> FAILED: boom\n" for s in failing)
        (d / f"cycle_2026-09-{day:02d}_030402.log").write_text(body, encoding="utf-8")
    return d


# ── failure paths first ──────────────────────────────────────────────────────

def test_predict_refuses_while_a_cycle_is_running(ledger, tmp_path):
    ev = _history(5) + [_ev("CYCLE_STARTED", "2026-09-06T00:04:03+00:00", "2026-09-06T03:04:02+03:00")]
    with pytest.raises(sf.Refused):
        sf.cmd_predict(ev, _logs(tmp_path, range(1, 6)))
    assert not ledger.exists(), "a refusal must leave the ledger untouched"


def test_predict_refuses_on_too_little_history(ledger, tmp_path):
    ev = _history(sf.MIN_HISTORY - 1)
    with pytest.raises(sf.Refused):
        sf.cmd_predict(ev, _logs(tmp_path, range(1, sf.MIN_HISTORY)))
    assert not ledger.exists()


def test_mutation_the_running_guard_is_load_bearing(ledger, tmp_path, monkeypatch):
    """If cycle_is_running() were neutered, the seal would go through — this
    test exists so that removing the guard turns red somewhere."""
    monkeypatch.setattr(sf, "cycle_is_running", lambda events: False)
    ev = _history(5) + [_ev("CYCLE_STARTED", "2026-09-06T00:04:03+00:00", "2026-09-06T03:04:02+03:00")]
    sealed = sf.cmd_predict(ev, _logs(tmp_path, range(1, 6)))
    assert sealed, "with the guard removed the seal goes through — proving the guard did the refusing"


def test_predict_refuses_a_second_forecast_for_the_same_night(ledger, tmp_path):
    """One forecast per night. Two --predict runs with no cycle in between are
    the SAME forecast for the SAME night; sealing both makes one observation
    count twice in the Brier mean. The refusal must leave the ledger byte-
    identical — not append a note, not seal 'a second opinion'."""
    ev = _history(5)
    logs = _logs(tmp_path, range(1, 6))
    first = sf.cmd_predict(ev, logs)
    assert first
    before = ledger.read_bytes()
    with pytest.raises(sf.Refused):
        sf.cmd_predict(ev, logs)
    assert ledger.read_bytes() == before, "the refused second seal still wrote to the ledger"


def test_mutation_the_one_forecast_per_night_guard_is_load_bearing(ledger, tmp_path, monkeypatch):
    """Neuter the guard's only input and the duplicate goes through — so
    removing the guard turns this red instead of silently double-counting.
    Then prove the damage it prevents: BOTH copies get scored against the one
    night, i.e. two outcomes for a single observation."""
    ev = _history(5)
    logs = _logs(tmp_path, range(1, 7))
    sf.cmd_predict(ev, logs)
    n_first = len([r for r in pl.read_all() if r["event"] == pl.PREDICTION])
    real_read_all = pl.read_all
    monkeypatch.setattr(pl, "read_all", lambda: [])          # the guard sees no history
    sf.cmd_predict(ev, logs)
    monkeypatch.setattr(pl, "read_all", real_read_all)
    recs = pl.read_all()
    assert len([r for r in recs if r["event"] == pl.PREDICTION]) == 2 * n_first,         "with the guard blinded the duplicate seal goes through — proving the guard refused it"
    ev2 = ev + _fin(6, 7400, 0)
    sf.cmd_score(ev2, logs)
    outs = [r for r in pl.read_all() if r["event"] == pl.OUTCOME
            and r["target_kind"] == "self_duration"]
    assert len(outs) == 2, "the duplicate is scored too — one night, two observations"
    assert len({o["scored_cycle"] for o in outs}) == 1, "both score the SAME night"


def test_score_leaves_an_unfinished_night_open(ledger, tmp_path):
    ev = _history(5)
    sf.cmd_predict(ev, _logs(tmp_path, range(1, 6)))
    assert sf.cmd_score(ev, tmp_path / "cycle_logs") == 0
    assert not any(r["event"] == pl.OUTCOME for r in pl.read_all())


def test_score_never_scores_twice(ledger, tmp_path):
    ev = _history(5)
    logs = _logs(tmp_path, range(1, 7))
    sf.cmd_predict(ev, logs)
    ev2 = ev + _fin(6, 7400, 0)
    first = sf.cmd_score(ev2, logs)
    assert first > 0
    assert sf.cmd_score(ev2, logs) == 0
    outs = [r for r in pl.read_all() if r["event"] == pl.OUTCOME]
    assert len({r["ref_hash"] for r in outs}) == len(outs)


def test_step_fail_without_a_log_is_named_pending_not_scored(ledger, tmp_path):
    ev = _history(5)
    logs = _logs(tmp_path, range(1, 6))          # night 6 will have NO log
    sf.cmd_predict(ev, logs)
    ev2 = ev + _fin(6, 7400, 0)
    sf.cmd_score(ev2, logs)
    recs = pl.read_all()
    step_outs = [r for r in recs if r["event"] == pl.OUTCOME and r["target_kind"] == "self_step_fail"]
    pend = [r for r in recs if r["event"] == pl.PENDING]
    assert not step_outs and pend, "unknowable outcome must be a named absence, not a 0"


def test_scoreboard_refuses_a_broken_chain(ledger, tmp_path, monkeypatch):
    ev = _history(5)
    sf.cmd_predict(ev, _logs(tmp_path, range(1, 6)))
    lines = ledger.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0]); rec["learner"] = 0.0       # rewrite a sealed number
    lines[0] = json.dumps(rec, ensure_ascii=False)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(sb.ChainBroken):
        sb.build()


def test_brier_is_squared_not_absolute(ledger, tmp_path):
    """Mutation net: if the scorer fell back to |p - actual|, this exact value changes."""
    ev = _history(5)
    logs = _logs(tmp_path, range(1, 7))
    sf.cmd_predict(ev, logs)
    ev2 = ev + _fin(6, 7400, 1)
    sf.cmd_score(ev2, logs)
    deg = [r for r in pl.read_all() if r["event"] == pl.OUTCOME and r["target_kind"] == "self_degraded"][0]
    sealed = [r for r in pl.read_all() if r["hash"] == deg["ref_hash"]][0]
    assert deg["learner_err"] == pytest.approx((sealed["learner"] - 1) ** 2)
    assert deg["learner_err"] != pytest.approx(abs(sealed["learner"] - 1))


def test_degenerate_predictions_are_counted_not_compared(ledger):
    pl.seal_prediction("axis_next", "A::next", "h", 50.0, 50.0, basis="x", degenerate=True)
    h = pl.read_all()[-1]["hash"]
    pl.score_prediction(h, 50.0)
    row = sb.build()["rows"][0]
    assert row["scored"] == 1 and row["degenerate_excluded"] == 1 and row["compared"] == 0
    assert row["learner_beats_baseline"] is False


# ── happy path last ──────────────────────────────────────────────────────────

def test_full_round_trip_seals_three_kinds_and_scores_them(ledger, tmp_path):
    # 10 nights so that "recent" (7) differs from "all" — otherwise learner ==
    # baseline and the board rightly refuses to compare them.
    ev = _history(10)
    logs = _logs(tmp_path, range(1, 4), failing=())
    _logs(tmp_path, range(4, 12), failing=("merkle_to_training",))
    sealed = sf.cmd_predict(ev, logs)
    kinds = {r["target_kind"] for r in sealed}
    assert kinds == {"self_duration", "self_degraded", "self_step_fail"}
    step = [r for r in sealed if r["target_kind"] == "self_step_fail"][0]
    assert step["step"] == "merkle_to_training"
    assert 0.0 < step["learner"] < 1.0, "Laplace: never a free 0 or 1"
    assert step["learner"] != step["baseline"], "recent rate must differ from all-time here"
    ev2 = ev + _fin(11, 7400, 0)
    assert sf.cmd_score(ev2, logs) == 3
    board = sb.build()
    by = {r["kind"]: r for r in board["rows"]}
    assert by["self_duration"]["rule"] == "mae" and by["self_degraded"]["rule"] == "brier"
    assert by["self_step_fail"]["all_time"]["n"] == 1
    md = sb.to_markdown(board)
    assert "self_step_fail" in md and "| brier |" in md


# ── self_survive: p_survive sealed at boot, scored in the morning (11 Sep 2026) ─

def test_p_survive_is_sealed_as_a_prediction_and_note_pending_when_unmeasurable(ledger):
    ev = _history(5)
    r = sf.seal_survival("cyc-x", 0.05, "low", horizon_seconds=7200, events=ev)
    assert r["event"] == pl.PREDICTION and r["target_kind"] == sf.SURVIVE_KIND
    assert r["learner"] == 0.05 and 0 < r["baseline"] <= 1 and r["target_id"] == "cycle::cyc-x"
    r2 = sf.seal_survival("cyc-y", None, "none", events=ev)
    assert r2["event"] != pl.PREDICTION                    # no number -> no coin
    assert sum(1 for x in pl.read_all() if x.get("event") == pl.PREDICTION) == 1


def test_self_survive_is_scored_against_its_own_cycles_terminal_event(ledger):
    ev = _history(5)
    cid_ok, cid_dead = "cyc-ok", "cyc-dead"
    sf.seal_survival(cid_ok, 0.05, "low", events=ev)        # said 5% — it will finish
    sf.seal_survival(cid_dead, 0.9, "low", events=ev)       # said 90% — it will die
    sf.seal_survival("cyc-open", 0.5, "low", events=ev)     # no terminal event yet
    assert sf.cmd_score(events=ev) == 0                     # nothing has ended
    ev2 = ev + [_ev("CYCLE_STARTED", "2026-09-20T00:04:00+00:00", cid_ok),
                _ev("CYCLE_FINISHED", "2026-09-20T02:00:00+00:00", cid_ok, duration_sec=7000, degraded_steps=0),
                _ev("CYCLE_STARTED", "2026-09-21T00:04:00+00:00", cid_dead),
                _ev("CYCLE_KILLED", "2026-09-21T01:00:00+00:00", cid_dead)]
    assert sf.cmd_score(events=ev2) == 2
    outs = {r["scored_cycle"]: r for r in pl.read_all() if r.get("event") == pl.OUTCOME}
    assert outs[cid_ok]["actual"] == 1 and outs[cid_dead]["actual"] == 0
    assert outs[cid_ok]["learner_err"] == pytest.approx((0.05 - 1) ** 2)       # 0.9025: the 5% was badly wrong
    assert outs[cid_dead]["learner_err"] == pytest.approx(0.81)
    assert "cyc-open" not in outs


def test_predict_never_seals_self_survive(ledger, tmp_path):
    """The 09:00 run must not guess a number that is computed at 03:04."""
    ev = _history(5)
    _logs(tmp_path, range(1, 6))
    sf.cmd_predict(events=ev, logs_dir=tmp_path / "cycle_logs")
    kinds = {r.get("target_kind") for r in pl.read_all() if r.get("event") == pl.PREDICTION}
    assert sf.SURVIVE_KIND not in kinds and kinds


def test_survival_baseline_is_laplace_over_terminal_events():
    ev = _history(3) + [_ev("CYCLE_STARTED", "2026-09-09T00:00:00+00:00", "d"),
                        _ev("CYCLE_DIED", "2026-09-09T01:00:00+00:00", "d")]
    b = sf.survival_baseline(ev)
    assert 0.5 < b < 1.0                                    # 3 of 4 finished, smoothed


def test_survival_gate_seals_after_recording_and_the_decision_ignores_it(monkeypatch, tmp_path):
    """Structural: the seal happens inside _record_p_survive, after record(), and
    guard()'s decision is taken before it — deleting the seal changes no verdict."""
    import pathlib as _pl
    from core import survival_gate as sg
    src = _pl.Path(sg.__file__).read_text(encoding="utf-8")
    body = src[src.index("def _record_p_survive"):src.index("def guard")]
    assert body.index("p_survive.record(") < body.index("seal_survival(")
    assert "decision[\"p_survive\"] = _record_p_survive" in src
    gsrc = src[src.index("def guard"):]
    assert gsrc.index("decision = check(") < gsrc.index("_record_p_survive(")   # verdict first, metric after
