"""
The training record and the first learnable head.

Two guarantees, and they are the whole point of the pair:

1. AN ASSERTED TARGET NEVER ENTERS TRAINING.
   memory/goal_score_history.json is two-thirds model opinion recorded in the
   same typeface as a NOAA reading. A model trained on that mixture learns its
   own hallucinations and hands them back as confidence. So provenance is
   attached at birth, classified by the SAME module that judges the composite
   (core/measurement_honesty), and the default is fail-closed: an unknown source
   is ASSERTED and stays out.

2. AN INVERTED INTERVAL IS IMPOSSIBLE BY CONSTRUCTION.
   The head predicts a centre and the LOGARITHM of a half-width, so lo <= hi
   holds for every weight vector — before training, after a diverged run, at
   absurd magnitudes. Not checked afterwards and repaired; unrepresentable.

The held-out split is by STEP, never by row: with one embedding per step name, a
random row split would be testing memorisation and reporting it as skill.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]

from core import interval_head as ih  # noqa: E402
from core import training_log as tl  # noqa: E402
from core.measurement_honesty import ASSERTED, CARRIED, MEASURED  # noqa: E402


# --------------------------------------------------------------------------- #
# (a) provenance, fail-closed
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("source,expected", [
    ("measured", MEASURED),
    ("composed", MEASURED),
    ("scorer", MEASURED),
    ("real", MEASURED),
    ("carried", CARRIED),
    ("llm_level", ASSERTED),
    ("unlabelled", ASSERTED),
    ("satellite_v2_that_nobody_whitelisted", ASSERTED),
    ("", "ABSENT"),
])
def test_the_source_decides_the_kind(source, expected):
    row = tl.make_row("t", "k", 1.0, source=source, how="test")
    assert row["provenance"]["kind"] == expected


def test_an_unknown_source_is_never_trainable():
    """NEGATIVE CONTROL, and the direction the error must fall in. A source
    somebody forgot to whitelist costs the model DATA, never truthfulness."""
    row = tl.make_row("t", "k", 1.0, source="brand_new_instrument", how="?")
    assert row["provenance"]["kind"] == ASSERTED
    assert tl.is_trainable(row) is False


def test_a_carried_value_is_not_trainable():
    """It is a real reading REPEATED. Training on it would weight one
    observation as if it were several."""
    assert tl.is_trainable(
        tl.make_row("t", "k", 1.0, source="carried", how="?")) is False


def test_a_row_with_no_value_is_not_trainable():
    assert tl.is_trainable(
        tl.make_row("t", "k", None, source="measured", how="?")) is False


def test_excluded_rows_are_counted_not_dropped(tmp_path):
    """A training set that cannot say what it refused cannot be audited for
    what it accepted."""
    p = tmp_path / "log.jsonl"
    tl.append([
        tl.make_row("t", "a", 1.0, source="measured", how="clock"),
        tl.make_row("t", "b", 2.0, source="llm_level", how="a model"),
        tl.make_row("t", "c", 3.0, source="who_knows", how="?"),
    ], p)
    s = tl.stats(p)
    assert s["total"] == 3
    assert s["trainable"] == 1
    assert s["excluded"] == 2
    assert s["by_kind"][ASSERTED] == 2
    assert len(tl.rows(path=p)) == 1
    assert len(tl.rows(include_asserted=True, path=p)) == 3


# --------------------------------------------------------------------------- #
# (b) the harvest refuses impossible durations, loudly
# --------------------------------------------------------------------------- #

def test_the_impossible_bound_comes_from_the_guarded_config():
    """Not a taste. The watchdog's largest declared ceiling plus one supervisor
    tick is the most any step can survive before it is killed."""
    sched = json.loads((BASE / "config" / "scheduler.json").read_text(encoding="utf-8"))
    biggest = max(v for v in sched["step_ceilings_sec"].values()
                  if isinstance(v, (int, float)))
    assert ih is not None
    assert tl._impossible_above() == float(biggest) + tl.WATCHDOG_TICK_SEC


def test_a_gap_between_cycles_is_not_a_step_duration(tmp_path):
    """A pair of beats spanning a cycle boundary measured the machine being
    ASLEEP. Measured on this repo before the fix: a 44302 s 'step'."""
    log = tmp_path / "beats.jsonl"
    rows = [
        {"ts": "2026-08-20T10:00:00+00:00", "step": "daily_analysis", "sec": 1.0},
        {"ts": "2026-08-20T10:10:00+00:00", "step": "data_scout", "sec": 1.0},
        # 12 hours later, a new cycle starts
        {"ts": "2026-08-20T22:10:00+00:00", "step": "boot", "sec": 1.0},
        {"ts": "2026-08-20T22:10:30+00:00", "step": "body_scan", "sec": 1.0},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = tl.harvest_step_seconds(baseline=tmp_path / "nope.json", brain_log=log)
    keys = {r["key"]: r["value"] for r in out}
    assert "daily_analysis" in keys
    assert keys["daily_analysis"] == pytest.approx(599.0)
    assert "data_scout" not in keys, (
        "the 12-hour gap before `boot` was recorded as a step duration")


def test_a_duration_above_the_bound_is_dropped_and_counted(tmp_path, capsys):
    log = tmp_path / "beats.jsonl"
    rows = [
        {"ts": "2026-08-20T00:00:00+00:00", "step": "scoring_engine", "sec": 0.0},
        {"ts": "2026-08-20T11:00:00+00:00", "step": "deduction", "sec": 0.0},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = tl.harvest_step_seconds(baseline=tmp_path / "nope.json", brain_log=log)
    assert out == []
    assert "dropped 1" in capsys.readouterr().out, (
        "a silently discarded row is indistinguishable from one that never "
        "existed — NO SILENT CAPS")


# --------------------------------------------------------------------------- #
# (c) the interval cannot invert
# --------------------------------------------------------------------------- #

def test_hi_is_never_below_lo_at_any_weights():
    rng = np.random.default_rng(11)
    for scale in (0.1, 1.0, 10.0, 100.0):
        head = ih.IntervalHead(dim=8, hidden=4, seed=int(scale * 7))
        for name in ("W1", "W2", "W3", "b1", "b2", "b3"):
            p = getattr(head, name)
            setattr(head, name, rng.normal(0, scale, size=p.shape))
        lo, hi = head.predict(rng.normal(0, 3, size=(300, 8)))
        assert bool(np.all(hi >= lo)), f"inverted interval at scale {scale}"


def test_an_untrained_head_already_produces_a_valid_interval():
    head = ih.IntervalHead(dim=16, hidden=8, seed=2)
    lo, hi = head.predict(np.random.default_rng(0).normal(0, 1, size=(50, 16)))
    assert bool(np.all(hi > lo))


# --------------------------------------------------------------------------- #
# (d) the loss is the loss
# --------------------------------------------------------------------------- #

def test_width_always_costs():
    y = np.array([1.0])
    a = ih.IntervalHead.winkler(np.array([0.99]), np.array([1.01]), y)[0]
    b = ih.IntervalHead.winkler(np.array([0.5]), np.array([1.5]), y)[0]
    assert 0 < a < b


def test_a_miss_costs_more_than_its_distance():
    """The (2/alpha) factor is what stops a confident wrong interval being
    cheap. At alpha=0.2 a miss is charged ten times the distance."""
    y = np.array([1.0])
    miss = ih.IntervalHead.winkler(np.array([2.0]), np.array([2.0]), y,
                                   alpha=0.2)[0]
    assert miss == pytest.approx(10.0)


def test_the_gradient_matches_the_loss_away_from_kinks():
    """The loss is piecewise linear; a coordinate is only checked where the
    active set does not change between the two probes."""
    rng = np.random.default_rng(4)
    head = ih.IntervalHead(dim=6, hidden=5, seed=9)
    X = rng.normal(0, 1, size=(20, 6))
    y = rng.normal(0, 1, size=20)
    g = head.grads(X, y)

    def active():
        f = head.forward(X)
        c, s = f["z3"][:, 0], f["z3"][:, 1]
        h = np.exp(np.clip(s, -20, 20))
        return (np.sign(f["z1"]).tobytes(), np.sign(f["z2"]).tobytes(),
                (y < c - h).tobytes(), (y > c + h).tobytes())

    checked = 0
    for name in ("W1", "b1", "W2", "b2", "W3", "b3"):
        flat = getattr(head, name).ravel()
        gflat = g[name].ravel()
        for i in (0, len(flat) - 1):
            eps, old = 1e-6, flat[i]
            flat[i] = old + eps
            a1, l1 = active(), head.loss(X, y)
            flat[i] = old - eps
            a0, l0 = active(), head.loss(X, y)
            flat[i] = old
            if a1 != a0:
                continue
            checked += 1
            assert (l1 - l0) / (2 * eps) == pytest.approx(gflat[i], abs=1e-6)
    assert checked >= 8, "too few coordinates were away from a kink to check"


# --------------------------------------------------------------------------- #
# (e) the split holds out whole steps
# --------------------------------------------------------------------------- #

def test_no_step_is_split_across_train_and_holdout():
    keys = [f"step_{i % 12}" for i in range(240)]
    tr, va, held = ih.split_by_step(keys, np.zeros(240))
    assert not ({keys[i] for i in tr} & {keys[i] for i in va})
    assert set(held) == {keys[i] for i in va}
    assert len(tr) + len(va) == 240


def test_the_holdout_is_not_empty_even_with_few_steps():
    keys = ["a", "a", "b", "b"]
    tr, va, held = ih.split_by_step(keys, np.zeros(4))
    assert len(va) > 0 and len(tr) > 0


# --------------------------------------------------------------------------- #
# (f) the live dataset and the committed curve
# --------------------------------------------------------------------------- #

def test_not_one_asserted_row_reaches_the_dataset():
    """THE DELIVERABLE. The dataset re-checks provenance itself rather than
    trusting the harvester that produced it."""
    data = ih.dataset()
    leaked = [r for r in data["rows"] if not tl.is_trainable(r)]
    assert leaked == [], f"{len(leaked)} asserted rows reached training"
    for r in data["rows"]:
        assert r["provenance"]["kind"] == MEASURED


def test_the_committed_curve_reports_a_holdout_number():
    """A curve without a held-out column is a claim about memorisation."""
    if not ih.CURVE.exists():
        pytest.skip("no training run recorded yet")
    run = json.loads(ih.CURVE.read_text(encoding="utf-8"))
    assert run["curve"], "the run recorded no curve at all"
    for point in run["curve"]:
        assert "train" in point and "heldout" in point
    assert run["steps_heldout"], "nothing was held out"
    assert run["final"]["heldout"] is not None
    assert run["flat_baseline"]["heldout"] is not None


def test_the_run_records_which_embedding_it_actually_used():
    """A fallback representation reported as the real one is exactly the silent
    degradation this repo exists to stop."""
    if not ih.CURVE.exists():
        pytest.skip("no training run recorded yet")
    run = json.loads(ih.CURVE.read_text(encoding="utf-8"))
    assert run["embedding"] in ("ollama:qwen2.5:3b", "hashed_fallback",
                                "hashed_control")
    assert run["embedding_dim"] > 0
