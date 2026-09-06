# -*- coding: utf-8 -*-
"""
FIRST BET — the seven guard tests from claude/SPEC_7SEP_FIRST_BET.md.

Every one runs against a HAND-WRITTEN FAKE PAYLOAD. No live fetch, no GPU, no model.
That is not a convenience: the bet is sealed before reality grades it, so the sealing
path has to be provable without waiting a day and without spending a night's GPU on a
test.

The gate is NOT reimplemented here. `core.proposal_intake.judge` is the per-proposal
decision that `admit` applies to every proposal, and `admit` is what
fast_cycle_runner.py:1600 calls. test_the_gate_is_the_live_one pins that equivalence, so
if the live door ever stops using this decision the claim "same gate" fails loudly
instead of quietly becoming false.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.first_bet import (SERIES_DEFAULT, choose, gate_all,  # noqa: E402
                             median_abs_daily_change, parse_completion,
                             seal_bet, series_moved)

TODAY = date(2026, 9, 7)
TOMORROW = (TODAY + timedelta(days=1)).isoformat()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
SERIES = "CLIMATE_GLOBAL_RISK_REVIEW"


# ── injected gate collaborators: a synthetic axis must not make a claim about a
# real one, which is why judge() takes these (same reason `resolver` exists).
def _resolver(axis, metric=None):
    return (427.15, None) if axis == SERIES else (None, f"no series {axis!r}")


def _cadence_ok(indicator, deadline):
    return None                      # daily tier, deadline inside the horizon


def _scale_ok(indicator, delta):
    return (None, "verified against 30 observations, range 2")


INJECT = dict(resolver=_resolver, cadence_check=_cadence_ok, scale_check=_scale_ok)


def _completion(indicator=SERIES, delta="0.12", deadline=TOMORROW, confidence=None,
                drop=None):
    lines = [f"INDICATOR: {indicator}",
             f"EXPECTED_DELTA: {delta}",
             f"DEADLINE: {deadline}"]
    if drop is not None:
        lines = [l for l in lines if not l.startswith(drop)]
    if confidence is not None:
        lines.append(f"CONFIDENCE: {confidence}")
    return "\n".join(lines)


def _eight(**over):
    """The hand-written fake payload: eight completions from one prompt."""
    base = [
        _completion(delta="0.10", confidence=0.9),
        _completion(delta="0.25", confidence=0.4),
        _completion(delta="-0.05", confidence=0.7),
        _completion(drop="DEADLINE"),                        # 2-line  -> test 1
        _completion(delta="a lot"),                          # non-num -> test 2
        _completion(deadline=YESTERDAY),                     # past    -> test 3
        _completion(indicator="GDELT_DAILY"),                # name    -> test 7
        _completion(delta="0.03", confidence=0.55),
    ]
    return over.get("completions", base)


def _records():
    parsed = [parse_completion(c) for c in _eight()]
    return gate_all(parsed, SERIES, today=TODAY, **INJECT)


# ── 1 ───────────────────────────────────────────────────────────────────────
def test_a_two_line_completion_is_rejected():
    """A completion missing DEADLINE is not a forecast — it cannot be graded, which
    is the whole point of betting."""
    p = parse_completion(_completion(drop="DEADLINE"))
    assert p["deadline"] is None
    assert "DEADLINE" in p["missing_fields"]
    r = gate_all([p], SERIES, today=TODAY, **INJECT)[0]
    assert r["verdict"] == "REFUSED"
    assert "deadline" in r["missing"]
    assert r["refusal"], "a refusal must carry its exact string"


# ── 2 ───────────────────────────────────────────────────────────────────────
def test_a_non_numeric_delta_is_refused():
    r = gate_all([parse_completion(_completion(delta="a lot"))], SERIES,
                 today=TODAY, **INJECT)[0]
    assert r["verdict"] == "REFUSED"
    assert "expected_delta" in r["missing"]
    assert "must be a number" in r["refusal"]


# ── 3 ───────────────────────────────────────────────────────────────────────
def test_a_past_deadline_is_refused():
    r = gate_all([parse_completion(_completion(deadline=YESTERDAY))], SERIES,
                 today=TODAY, **INJECT)[0]
    assert r["verdict"] == "REFUSED"
    assert "deadline" in r["missing"]
    assert "not after today" in r["refusal"]


# ── 7 (named early because 1–3 share its fixture) ───────────────────────────
def test_a_completion_naming_a_different_indicator_is_refused():
    """The project's recurring defect: a name asserting a property the code never
    checks. The model may write any INDICATOR it likes; the bet is on the series that
    was actually fetched, and a mismatch is refused BEFORE the shared gate sees it."""
    r = gate_all([parse_completion(_completion(indicator="GDELT_DAILY"))], SERIES,
                 today=TODAY, **INJECT)[0]
    assert r["verdict"] == "REFUSED"
    assert "indicator" in r["missing"]
    assert "GDELT_DAILY" in r["refusal"] and SERIES in r["refusal"]
    assert r["refusal"].startswith("name:")


# ── 5 ───────────────────────────────────────────────────────────────────────
def test_all_eight_raw_candidates_are_recorded_with_a_verdict(tmp_path):
    recs = _records()
    assert len(recs) == 8
    for i, r in enumerate(recs):
        assert r["raw"] == _eight()[i], "the RAW completion must survive verbatim"
        assert r["verdict"] in ("ADMITTED", "REFUSED")
        assert "parsed" in r
        if r["verdict"] == "REFUSED":
            assert r["refusal"]
    assert sum(r["verdict"] == "ADMITTED" for r in recs) == 4
    assert sum(r["verdict"] == "REFUSED" for r in recs) == 4

    out = seal_bet(recs, series_id=SERIES, v0=427.15, v0_date="2026-09-06",
                   ref_delta=0.02, today=TODAY, ledger_dir=tmp_path)
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    assert len(payload["all_8_candidates"]) == 8
    assert [c["raw"] for c in payload["all_8_candidates"]] == _eight()
    assert all("verdict" in c for c in payload["all_8_candidates"])


# ── 4 ───────────────────────────────────────────────────────────────────────
def test_the_persistence_baseline_is_sealed_in_the_same_file(tmp_path):
    """The null the bet must beat, sealed at the same instant and in the same file —
    a baseline computed after the outcome is not a baseline."""
    out = seal_bet(_records(), series_id=SERIES, v0=427.15, v0_date="2026-09-06",
                   ref_delta=0.02, today=TODAY, ledger_dir=tmp_path)
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    assert payload["persistence_predicted_value"] == 427.15
    assert payload["persistence_predicted_value"] == payload["V0"]
    assert payload["deadline"] == payload["persistence_deadline"]


# ── 6 ───────────────────────────────────────────────────────────────────────
def test_exactly_one_candidate_is_sealed_and_the_sha_covers_the_three_fields(tmp_path):
    out = seal_bet(_records(), series_id=SERIES, v0=427.15, v0_date="2026-09-06",
                   ref_delta=0.02, today=TODAY, ledger_dir=tmp_path)
    p = json.loads(Path(out).read_text(encoding="utf-8"))
    assert sum(c.get("sealed", False) for c in p["all_8_candidates"]) == 1
    assert p["indicator"] == SERIES
    assert p["predicted_value"] == pytest.approx(p["V0"] + p["predicted_delta"])

    want = hashlib.sha256(json.dumps(
        {"indicator": p["indicator"], "expected_delta": p["predicted_delta"],
         "deadline": p["deadline"]},
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert p["sha256_of_sealed_fields"] == want

    tampered = dict(p, predicted_delta=p["predicted_delta"] + 1)
    other = hashlib.sha256(json.dumps(
        {"indicator": tampered["indicator"],
         "expected_delta": tampered["predicted_delta"],
         "deadline": tampered["deadline"]},
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert other != p["sha256_of_sealed_fields"], "the seal must move if the bet moves"


# ── the gate is the live one, not a copy ────────────────────────────────────
def test_the_gate_is_the_live_one():
    """fast_cycle_runner.py:1600 calls proposal_intake.admit; admit applies judge to
    every proposal; first_bet calls judge. If that chain is ever broken, "same gate"
    stops being true and this fails."""
    import inspect

    from core import proposal_intake as pi
    assert "judge(p, today=today" in inspect.getsource(pi.admit)
    assert "_pi.admit(" in (REPO / "fast_cycle_runner.py").read_text(
        encoding="utf-8", errors="replace")
    import tools.first_bet as fb
    assert "judge" in inspect.getsource(fb.gate_all)
    assert "def judge" not in inspect.getsource(fb), "the gate must not be reimplemented"


# ── the frozen-series precondition ──────────────────────────────────────────
def test_a_frozen_series_is_detected_before_any_bet_is_made():
    """The spec requires the series to have MOVED across the last 3 available days.
    CO2 is the only gate-resolvable daily indicator and it publishes weekly, so this
    precondition is the one most likely to fire in production."""
    assert series_moved([427.13, 427.14, 427.15]) is True
    assert series_moved([427.15, 427.15, 427.15]) is False
    assert series_moved([1.0, 2.0]) is False, "fewer than 3 days cannot be confirmed"


def test_the_reference_delta_is_the_median_absolute_daily_change():
    assert median_abs_daily_change([1.0, 1.5, 2.0, 2.5]) == pytest.approx(0.5)
    assert median_abs_daily_change([5.0]) is None


def test_choose_prefers_the_narrowest_confidence_then_the_reference_delta():
    recs = _records()
    idx, reason = choose(recs, ref_delta=0.02)
    assert recs[idx]["verdict"] == "ADMITTED"
    assert "confidence" in reason
    # with no confidence anywhere, it falls back to the reference delta
    stripped = [dict(r, parsed=dict(r["parsed"], confidence=None)) for r in recs]
    idx2, reason2 = choose(stripped, ref_delta=0.02)
    assert stripped[idx2]["verdict"] == "ADMITTED"
    assert "closest" in reason2


def test_the_default_series_is_the_one_the_spec_names():
    assert SERIES_DEFAULT == "GDELT_DAILY"


# ── the --live path, added 7 Sep so tomorrow's run is possible at all ───────
def test_live_refuses_while_a_cycle_lock_is_present(tmp_path, monkeypatch, capsys):
    """A generation that starts while the 03:04 cycle is still running competes with
    it for the GPU and the ladder — which is how A3 died four times on 6 September."""
    import tools.first_bet as fb
    lock = tmp_path / "cycle.lock"
    lock.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(fb, "REPO", tmp_path.parent)
    monkeypatch.setattr(fb.Path, "exists", lambda self: str(self).endswith("cycle.lock"))
    monkeypatch.setattr(sys, "argv", ["first_bet.py", "--live"])
    monkeypatch.setattr(fb, "_gpu_used_mib", lambda: 0)
    monkeypatch.setattr("core.proposal_intake._default_resolver",
                        lambda a, m=None: (100.0, None))
    rc = fb.main()
    assert rc == 4
    assert "cycle is running" in capsys.readouterr().out


def test_live_refuses_when_gpu_occupancy_is_unknown(monkeypatch, capsys):
    """None is NOT zero. An unknown occupancy is a refusal, not a green light —
    the same defect the sampler had on 4 September."""
    import tools.first_bet as fb
    monkeypatch.setattr(sys, "argv", ["first_bet.py", "--live"])
    monkeypatch.setattr(fb, "_gpu_used_mib", lambda: None)
    monkeypatch.setattr(fb.Path, "exists", lambda self: False)
    monkeypatch.setattr("core.proposal_intake._default_resolver",
                        lambda a, m=None: (100.0, None))
    assert fb.main() == 4
    assert "UNKNOWN" in capsys.readouterr().out


def test_live_refuses_when_the_card_is_busy(monkeypatch, capsys):
    import tools.first_bet as fb
    monkeypatch.setattr(sys, "argv", ["first_bet.py", "--live"])
    monkeypatch.setattr(fb, "_gpu_used_mib", lambda: 3358)
    monkeypatch.setattr(fb.Path, "exists", lambda self: False)
    monkeypatch.setattr("core.proposal_intake._default_resolver",
                        lambda a, m=None: (100.0, None))
    assert fb.main() == 4
    assert "3358 MiB" in capsys.readouterr().out


def test_with_neither_flag_nothing_runs(monkeypatch, capsys):
    import tools.first_bet as fb
    monkeypatch.setattr(sys, "argv", ["first_bet.py"])
    monkeypatch.setattr("core.proposal_intake._default_resolver",
                        lambda a, m=None: (100.0, None))
    assert fb.main() == 3
    assert "nothing ran" in capsys.readouterr().out
