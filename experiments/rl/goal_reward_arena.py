#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/rl/goal_reward_arena.py — E8: reward = closeness to the goal.

Emil's frame (30 Jul 2026), taken as the spec: the goal is effectively unbounded,
so the reward field is inexhaustible. Reward = movement TOWARD the goal (potential-
based shaping: r = improvement in the focused axis toward its 1.0 ceiling). A
POPULATION of strategies (each a different way to choose where to push) competes; the
one that earns the most goal-progress becomes the shared ELITE whose focus is
published for the others. Justified TEMPORARY dips are not punished: a strategy is
credited with its best result within a patience window, so a "plan inside the plan"
that dips now to climb later is not scored as failure.

This is the CPU form — runs today, needs no GPU/torch. The neural upgrade (a learned
goal-conditioned policy on the GTX 1650) slots in behind the same reward + population
+ shared-elite scaffold once torch+CUDA is installed.

HONEST about what a BACKTEST can and cannot show: on recorded history the strategies
did not actually ACT, so we measure SELECTION skill — did a strategy point at axes
that then moved toward the goal, better than random? Causal reward (the push actually
caused the gain) only comes from live action, human-gated.

PRE-DECLARED (before seeing results):
  SUCCESS : the population's elite strategy earns >= 15% more goal-progress than
            uniform-random selection, over >= 20 decision points.
  FAIL    : elite <= random -> strategy selection has no edge on this signal; say so.

  python experiments/rl/goal_reward_arena.py --backtest
  python experiments/rl/goal_reward_arena.py --selftest
  python experiments/rl/goal_reward_arena.py --recommend   # live: publish elite focus
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
GOAL_SCORE_HISTORY = REPO / "memory" / "goal_score_history.json"
ELITE_OUT          = REPO / "memory" / "e8_elite.json"

SUCCESS_EDGE   = 0.15    # elite must beat random goal-progress by >=15%
SUCCESS_MIN_DP = 20      # over >=20 decision points
PATIENCE       = 2       # credit best improvement within the next PATIENCE steps


# ── strategies: state (per-axis recent series) -> chosen axis ────────────────
# Each returns the axis it would push this step.

def _last(series):   return series[-1]
def _delta(series):  return series[-1] - series[-2] if len(series) >= 2 else 0.0

def strat_worst_gap(state):      # push the axis furthest from the 1.0 goal
    return min(state, key=lambda a: _last(state[a]))

def strat_momentum(state):       # ride what is already rising
    return max(state, key=lambda a: _delta(state[a]))

def strat_contrarian(state):     # catch what is falling before it drags the goal
    return min(state, key=lambda a: _delta(state[a]))

def strat_diversify(state):      # the axis with the least recent change (neglected)
    return min(state, key=lambda a: abs(_delta(state[a])))

def strat_explore(state, step=0):  # deterministic pseudo-spread (no RNG by env rule)
    axes = sorted(state)
    return axes[step % len(axes)]

STRATEGIES = {
    "worst_gap":  lambda st, step=0: strat_worst_gap(st),
    "momentum":   lambda st, step=0: strat_momentum(st),
    "contrarian": lambda st, step=0: strat_contrarian(st),
    "diversify":  lambda st, step=0: strat_diversify(st),
    "explore":    lambda st, step=0: strat_explore(st, step),
}


def _reward(series, t):
    """Potential-based, patience-tolerant: best improvement of this axis within the
    next PATIENCE steps (so a justified temporary dip that recovers is not a loss)."""
    base = series[t]
    hi = base
    for k in range(1, PATIENCE + 1):
        if t + k < len(series):
            hi = max(hi, series[t + k])
    return hi - base


class Population:
    """Cumulative-reward bandit over the strategies; elite = top earner."""

    def __init__(self):
        self.earned = {name: 0.0 for name in STRATEGIES}
        self.picks  = {name: 0 for name in STRATEGIES}

    def step(self, state, series_by_axis, t):
        for name, fn in STRATEGIES.items():
            axis = fn(state, t)
            r = _reward(series_by_axis[axis], t)
            self.earned[name] += r
            self.picks[name] += 1

    def elite(self):
        return max(self.earned, key=self.earned.get)

    def weights(self):
        import math
        m = max(self.earned.values()) if self.earned else 0.0
        w = {k: math.exp(4.0 * (v - m)) for k, v in self.earned.items()}
        z = sum(w.values()) or 1.0
        return {k: round(v / z, 3) for k, v in w.items()}


# ── data ─────────────────────────────────────────────────────────────────────

def _axis_series():
    try:
        recs = json.loads(GOAL_SCORE_HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return {}
    by = {}
    for r in recs:
        sc = r.get("scores") if isinstance(r, dict) else None
        if isinstance(sc, dict):
            for a, v in sc.items():
                try:
                    by.setdefault(a, []).append(float(v) / 100.0)
                except Exception:
                    pass
    # keep axes with enough length, aligned to the shortest common tail
    by = {a: s for a, s in by.items() if len(s) >= 4}
    if not by:
        return {}
    n = min(len(s) for s in by.values())
    return {a: s[-n:] for a, s in by.items()}


def _run(series_by_axis):
    axes = list(series_by_axis)
    n = len(next(iter(series_by_axis.values())))
    pop = Population()
    rand_reward, dp = 0.0, 0
    for t in range(1, n - 1):
        state = {a: series_by_axis[a][:t + 1] for a in axes}
        pop.step(state, series_by_axis, t)
        rand_reward += sum(_reward(series_by_axis[a], t) for a in axes) / len(axes)
        dp += 1
    return pop, rand_reward, dp


def run_backtest():
    sba = _axis_series()
    print("=" * 66)
    print("E8 GOAL-REWARD ARENA — backtest on REAL goal_score_history")
    print(f"pre-declared: SUCCESS if elite beats random goal-progress by >= "
          f"{int(SUCCESS_EDGE*100)}% over >= {SUCCESS_MIN_DP} decision points")
    print("=" * 66)
    if not sba:
        print("no usable per-axis history -> INSUFFICIENT DATA (verdict pending #3 signal)")
        return
    pop, rand_reward, dp = _run(sba)
    elite = pop.elite()
    elite_reward = pop.earned[elite]
    edge = None if rand_reward == 0 else (elite_reward - rand_reward) / rand_reward
    print(f"axes: {len(sba)} | decision points: {dp}")
    print("cumulative goal-progress earned by each strategy:")
    for name, v in sorted(pop.earned.items(), key=lambda kv: -kv[1]):
        print(f"   {name:11} {v:+.4f}   (weight {pop.weights()[name]})")
    print(f"random (uniform) baseline: {rand_reward:+.4f}")
    print(f"ELITE: {elite}  |  edge over random: "
          f"{'n/a' if edge is None else f'{edge*100:+.1f}%'}")
    if dp < SUCCESS_MIN_DP:
        print(f"VERDICT: INSUFFICIENT DATA — only {dp} decision points (< {SUCCESS_MIN_DP}). "
              "The arena is real; verdict accumulates as the moving signal (#3) grows.")
    elif edge is not None and edge >= SUCCESS_EDGE:
        print("VERDICT: PASS (preliminary) — elite selection beats random. Confirm live.")
    else:
        print("VERDICT: FAIL (pre-declared) — no selection edge on this signal. Reported plainly.")


def run_recommend():
    """Live: rank strategies on history, publish the elite's next focus for the cycle."""
    sba = _axis_series()
    if not sba:
        print("[E8] no data -> no recommendation")
        return
    pop, _, _ = _run(sba)
    elite = pop.elite()
    state = {a: sba[a] for a in sba}
    focus = STRATEGIES[elite](state, len(next(iter(sba.values()))))
    out = {"ts": datetime.now(timezone.utc).isoformat(), "elite_strategy": elite,
           "recommended_focus_axis": focus, "weights": pop.weights(),
           "note": "advisory — reward = goal-progress; human-gated like everything"}
    try:
        ELITE_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    print(f"[E8] elite='{elite}' recommends focus -> {focus}  (-> memory/e8_elite.json)")


def run_selftest():
    print("SELFTEST on SYNTHETIC axes — algorithm sanity only, NO system claim.\n")
    # axis A steadily climbs (momentum/worst-gap-then-rise), B flat, C dips then recovers
    A = [0.2 + 0.05 * i for i in range(12)]
    B = [0.6] * 12
    C = [0.5, 0.45, 0.4, 0.5, 0.6, 0.7, 0.65, 0.7, 0.75, 0.8, 0.82, 0.85]
    sba = {"A": A, "B": B, "C": C}
    pop, rr, dp = _run(sba)
    print(f"decision points: {dp}")
    for name, v in sorted(pop.earned.items(), key=lambda kv: -kv[1]):
        print(f"   {name:11} {v:+.4f}")
    print(f"random baseline: {rr:+.4f} | elite: {pop.elite()}")
    print("\nExpected: momentum/worst_gap earn most (they ride A's climb & C's recovery); "
          "elite beats the random baseline; C's early dip is forgiven by the patience window.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        run_selftest()
    elif "--recommend" in sys.argv:
        run_recommend()
    else:
        run_backtest()
