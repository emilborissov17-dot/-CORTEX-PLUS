#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/transfer_tasks.py — A LATENT GRAMMAR WITH COMPOSITIONAL HOLD-OUTS. (T1.)

T1 asks one question: does retrieving the system's OWN verified past work improve
performance on a NEW task? If not, the knowledge layer has no consumer.

WHY THIS FILE WAS REWRITTEN, and it is the point of the design
---------------------------------------------------------------
The first version drew each task from one of six flat regimes, and the memory set and
the test set shared all six. Every test task therefore came from a regime memory had
already seen whole. A pass would have shown RECOGNITION — "I have met this exact kind
of series before" — and been reported as transfer. The two are not the same claim, and
the weaker one is the one that would have been easy to get.

So the six become PRIMITIVES, and a task's latent structure is one primitive or a
COMPOSITION of two. Memory holds every single primitive and SOME compositions. The test
set includes COMPOSITIONAL HOLD-OUTS: compositions that appear nowhere in memory, built
from primitives that do. Answering a hold-out by retrieval requires carrying something
from the parts to a whole never seen — which is transfer, and is what T1 claims to test.

THE HOLD-OUT SPLIT IS ASSERTED, NOT INTENDED. A hold-out that leaked into memory would
turn the hardest condition into the easiest and the experiment would report the
opposite of the truth. _selftest() proves the disjointness and fails loud.

THE LATENT LABEL IS NEVER SHOWN. Not in a prompt, not in an episode, not in the
retrieval key. An episode records what the series looked like, what was answered and
whether it was RIGHT — the three things the system already records about its own work.
A leaked primitive name would make MEMORY ON an answer key.

WHAT A TASK ASKS. The direction of the next step, plus a probability. One question
yields both metrics: success rate from the direction, Brier from the probability. A
"predict the next value" question was rejected because scoring it needs a tolerance, and
a tolerance is a free parameter that could be chosen after seeing the results.

MEAN_REVERTING WAS FIXED BY ITS PARAMETERS, not by relaxing the guard. At a pull of
0.65 the series converged inside eight steps and the final step fell under the
flat-step floor, so generation failed. The pull is now weaker and the starting
deviation larger. The floor stands: a task whose answer is a coin flip is refused, not
scored.

  venv\\Scripts\\python.exe tools/transfer_tasks.py --selftest
  venv\\Scripts\\python.exe tools/transfer_tasks.py --show 4 --phase test
  venv\\Scripts\\python.exe tools/transfer_tasks.py --ledger
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys

import numpy as np

METHOD_VERSION = "transfer_tasks/2"

MASTER_SEED = 20260917
SERIES_LEN = 9            # 8 shown + 1 held out as the answer
FLAT_FLOOR = 0.25         # |last step| below this has no direction; the draw is refused

PRIMITIVES = ("linear_trend", "mean_reverting", "alternating", "accelerating",
              "level_shift", "damped_oscillation")

# Which two-primitive compositions MEMORY is allowed to contain. The rest are
# hold-outs. Chosen once, here, and frozen — not sampled per run, or the split would
# differ between the prereg and the run.
MEMORY_COMPOSITIONS = (
    ("linear_trend", "alternating"),
    ("linear_trend", "mean_reverting"),
    ("accelerating", "alternating"),
    ("level_shift", "mean_reverting"),
    ("damped_oscillation", "linear_trend"),
)


def all_compositions() -> tuple:
    return tuple(itertools.combinations(PRIMITIVES, 2))


def holdout_compositions() -> tuple:
    mem = {frozenset(c) for c in MEMORY_COMPOSITIONS}
    return tuple(c for c in all_compositions() if frozenset(c) not in mem)


def _component(primitive: str, rng, n: int, base: float) -> np.ndarray:
    """One primitive's contribution, centred so two can be added without one
    swamping the other by its offset alone."""
    if primitive == "linear_trend":
        slope = float(rng.uniform(1.5, 6.0)) * (1 if rng.random() < 0.5 else -1)
        return slope * np.arange(n)
    if primitive == "mean_reverting":
        # Pull weakened from 0.65 to 0.28 and the starting deviation widened: at 0.65
        # the series was flat by step 6 and the final step fell under FLAT_FLOOR, so
        # generation failed outright for some seeds.
        dev = float(rng.uniform(18, 34)) * (1 if rng.random() < 0.5 else -1)
        out = np.empty(n); out[0] = dev
        for i in range(1, n):
            out[i] = out[i - 1] * (1 - 0.28)
        return out
    if primitive == "alternating":
        # THE PHASE MUST BE RANDOM. Without it the sign at index 7 is always -1 and at
        # index 8 always +1, so the final step is ALWAYS UP and the task is answerable
        # by a constant guess. Measured before the fix: alternating alone came out
        # up=4 down=0, and every composition containing it inherited the bias.
        step = float(rng.uniform(4, 11))
        ph = 0 if rng.random() < 0.5 else 1
        return step * np.array([1.0 if (i + ph) % 2 == 0 else -1.0 for i in range(n)])
    if primitive == "accelerating":
        a = float(rng.uniform(0.4, 1.6)) * (1 if rng.random() < 0.5 else -1)
        return a * (np.arange(n) ** 2) / 2.0
    if primitive == "level_shift":
        # A PURE JUMP IS NOT FORECASTABLE, and the first version was one: the shift
        # landed at index 3..6 of a 9-long series, so steps 7->8 were always flat and
        # generation failed on the flat-step floor for every seed. Loosening the floor
        # was the wrong fix — it would have admitted tasks whose answer is a coin flip.
        # The primitive is instead what a level shift actually is in a series: the
        # process moves to a NEW LEVEL AND CONTINUES THERE with its own drift. The
        # post-shift drift is what makes the final step answerable.
        at = int(rng.integers(2, n - 2))
        jump = float(rng.uniform(15, 40)) * (1 if rng.random() < 0.5 else -1)
        post = float(rng.uniform(1.2, 3.5)) * (1 if rng.random() < 0.5 else -1)
        return np.array([0.0 if i < at else jump + post * (i - at) for i in range(n)])
    if primitive == "damped_oscillation":
        # Same fixed-phase defect as `alternating`, same measurement: up=4 down=0.
        amp = float(rng.uniform(10, 25)); decay = float(rng.uniform(0.6, 0.85))
        ph = 0 if rng.random() < 0.5 else 1
        return amp * (decay ** np.arange(n)) * np.array(
            [1.0 if (i + ph) % 2 == 0 else -1.0 for i in range(n)])
    raise ValueError(f"unknown primitive {primitive!r}")


def _draw(latent: tuple, rng) -> np.ndarray:
    n = SERIES_LEN
    base = float(rng.uniform(20, 120))
    x = np.full(n, base)
    for p in latent:
        x = x + _component(p, rng, n, base)
    return np.round(x, 2)


def make_task(index: int, phase: str, latent: tuple,
              master: int = MASTER_SEED) -> dict:
    """One task with a DECLARED latent structure. Deterministic in its arguments."""
    key = f"{master}|{phase}|{index}|{'+'.join(latent)}"
    seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)

    for _ in range(200):
        s = _draw(latent, rng)
        shown, held = s[:-1], s[-1]
        if abs(held - shown[-1]) >= FLAT_FLOOR:
            break
    else:
        raise RuntimeError(
            f"{phase}/{index} {latent}: no draw with a non-flat final step in 200 "
            f"tries — the primitive parameters make this composition degenerate")

    return {
        "task_id": f"{phase}-{index:03d}",
        "phase": phase,
        "latent": list(latent),            # EXPERIMENTER ONLY — never prompted
        "n_primitives": len(latent),
        "composition": len(latent) > 1,
        "series": [float(v) for v in shown],
        "answer_value": float(held),
        "answer_up": bool(held > shown[-1]),
        "seed": seed,
        "method_version": METHOD_VERSION,
    }


def memory_set(master: int = MASTER_SEED, per_primitive: int = 6,
               per_composition: int = 4) -> list:
    """Episodes: every single primitive, and only the ALLOWED compositions."""
    out, i = [], 0
    for p in PRIMITIVES:
        for _ in range(per_primitive):
            out.append(make_task(i, "memory", (p,), master)); i += 1
    for c in MEMORY_COMPOSITIONS:
        for _ in range(per_composition):
            out.append(make_task(i, "memory", c, master)); i += 1
    return out


def test_set(master: int = MASTER_SEED, n_single: int = 24,
             n_seen_comp: int = 24, n_holdout: int = 16) -> list:
    """NEW tasks. Three strata, kept separate so the report can state hold-outs alone.

      single        a primitive memory has seen alone
      seen_comp     a composition memory contains
      holdout       a composition memory does NOT contain, from primitives it does
    """
    out, i = [], 0
    hold = holdout_compositions()
    for k in range(n_single):
        out.append({**make_task(i, "test", (PRIMITIVES[k % len(PRIMITIVES)],), master),
                    "stratum": "single"}); i += 1
    for k in range(n_seen_comp):
        out.append({**make_task(i, "test", MEMORY_COMPOSITIONS[k % len(MEMORY_COMPOSITIONS)],
                                master), "stratum": "seen_composition"}); i += 1
    for k in range(n_holdout):
        out.append({**make_task(i, "test", hold[k % len(hold)], master),
                    "stratum": "holdout_composition"}); i += 1
    return out


def features(task: dict) -> str:
    """The text an episode is indexed and retrieved by.

    SURFACE ONLY: the series as seen, and its step differences. No latent label, no
    answer. Whatever is in here is what MEMORY ON gets to see.
    """
    s = task["series"]
    diffs = [round(b - a, 2) for a, b in zip(s, s[1:])]
    return (f"series {', '.join(str(v) for v in s)}; "
            f"steps {', '.join(str(d) for d in diffs)}")


def latent_similarity(a: dict, b: dict) -> float:
    """Jaccard over latent primitives. The structural axis of the prereg's analysis."""
    A, B = set(a["latent"]), set(b["latent"])
    return len(A & B) / len(A | B) if (A | B) else 0.0


def surface_similarity(a: dict, b: dict) -> float:
    """Token overlap of the retrieval keys. The surface axis, deliberately naive —
    it is the thing latent similarity must be distinguished FROM."""
    A = set(features(a).replace(";", " ").replace(",", " ").split())
    B = set(features(b).replace(";", " ").replace(",", " ").split())
    return len(A & B) / len(A | B) if (A | B) else 0.0


def answer_leak_audit(tests: list, episodes: list) -> dict:
    """Does any test ANSWER appear in memory? Structural and n-gram.

    Structural: the exact answer value against every value in every episode series
    and every episode answer. N-gram: the last three shown values of a test task as a
    contiguous run inside any episode series — a retrieved episode that contains the
    test's own tail would hand over the continuation directly.
    """
    ep_vals, ep_runs = set(), set()
    for e in episodes:
        ep_vals.update(e["series"]); ep_vals.add(e["answer_value"])
        s = e["series"] + [e["answer_value"]]
        for i in range(len(s) - 2):
            ep_runs.add(tuple(s[i:i + 3]))

    val_hits, run_hits = [], []
    for t in tests:
        if t["answer_value"] in ep_vals:
            val_hits.append({"task_id": t["task_id"], "value": t["answer_value"]})
        if tuple(t["series"][-3:]) in ep_runs:
            run_hits.append({"task_id": t["task_id"], "tail": t["series"][-3:]})
    # TWO DIFFERENT THINGS, AND ONLY ONE IS A LEAK.
    #
    # A test's answer value equalling some number in some unrelated episode is a float
    # COINCIDENCE: 504 values rounded to 2dp across a bounded range collide by the
    # birthday argument, and an episode containing 47.3 somewhere tells a retriever
    # nothing about a test whose answer happens to be 47.3. Measured here: 2 of 504.
    # Failing on that would have forced a re-seed that fixed nothing.
    #
    # A test's own 3-value TAIL appearing as a contiguous run inside an episode IS a
    # leak: the episode then carries this task's context and what came next, and a
    # retrieved episode would hand over the continuation directly. That is the hard
    # failure, and it is 0.
    rate = len(val_hits) / max(1, len(tests))
    return {"answer_value_coincidence": val_hits,
            "answer_value_coincidence_rate": round(rate, 4),
            "tail_3gram_in_memory": run_hits,
            "leaked": bool(run_hits),
            "coincidence_implausible": rate > 0.10,
            "clean": not run_hits and rate <= 0.10,
            "n_tests": len(tests), "n_episodes": len(episodes),
            "n_memory_values": sum(len(e["series"]) + 1 for e in episodes)}


def ledger(master: int = MASTER_SEED) -> dict:
    """The frozen description of the task set, for the pre-registration."""
    eps, tests = memory_set(master), test_set(master)
    blob = json.dumps({"episodes": eps, "tests": tests}, sort_keys=True,
                      ensure_ascii=False).encode("utf-8")
    return {
        "method_version": METHOD_VERSION, "master_seed": master,
        "primitives": list(PRIMITIVES),
        "memory_compositions": [list(c) for c in MEMORY_COMPOSITIONS],
        "holdout_compositions": [list(c) for c in holdout_compositions()],
        "n_episodes": len(eps), "n_tests": len(tests),
        "strata": {s: sum(1 for t in tests if t["stratum"] == s)
                   for s in ("single", "seen_composition", "holdout_composition")},
        "leak_audit": {k: v for k, v in answer_leak_audit(tests, eps).items()
                       if k != "answer_value_coincidence" or v},
        "sha256": hashlib.sha256(blob).hexdigest(),
    }


def _selftest() -> int:
    print("tools/transfer_tasks.py --selftest")
    fails = []

    def check(name, cond):
        print(f"  {'OK  ' if cond else 'FAIL'}   {name}")
        if not cond:
            fails.append(name)

    eps = memory_set()
    tests = test_set()

    check("every primitive appears in memory as a single",
          {tuple(e["latent"])[0] for e in eps if e["n_primitives"] == 1} == set(PRIMITIVES))
    check("memory contains only the ALLOWED compositions",
          {frozenset(e["latent"]) for e in eps if e["composition"]}
          == {frozenset(c) for c in MEMORY_COMPOSITIONS})

    hold = {frozenset(c) for c in holdout_compositions()}
    mem_comps = {frozenset(e["latent"]) for e in eps if e["composition"]}
    check("THE HOLD-OUT COMPOSITIONS ARE ABSENT FROM MEMORY — the whole design "
          "rests on this", not (hold & mem_comps))
    check("a hold-out is built only from primitives memory HAS seen",
          all(set(c) <= set(PRIMITIVES) for c in holdout_compositions()))
    check("there are hold-out compositions to test at all", len(hold) >= 5)

    ho = [t for t in tests if t["stratum"] == "holdout_composition"]
    check(f"at least 16 compositional hold-outs ({len(ho)})", len(ho) >= 16)
    check(f"at least 64 test instances ({len(tests)})", len(tests) >= 64)
    check("every hold-out test task really is a hold-out composition",
          all(frozenset(t["latent"]) in hold for t in ho))
    check("the three strata are disjoint and exhaustive",
          sum(1 for t in tests if t["stratum"] in
              ("single", "seen_composition", "holdout_composition")) == len(tests))

    check("every task has a strictly up or down answer",
          all(abs(t["answer_value"] - t["series"][-1]) >= FLAT_FLOOR for t in eps + tests))
    check("answer_up agrees with the numbers",
          all(t["answer_up"] == (t["answer_value"] > t["series"][-1]) for t in eps + tests))
    ups = sum(t["answer_up"] for t in tests)
    check(f"test answers are not one-sided ({ups} up of {len(tests)}) — a constant "
          f"guess cannot score well", 0.3 <= ups / len(tests) <= 0.7)

    audit = answer_leak_audit(tests, eps)
    check("NO test task's 3-value tail appears as a run inside any episode — THIS is "
          "the leak that would hand over the continuation",
          not audit["tail_3gram_in_memory"])
    check(f"bare answer-value collisions stay at coincidence level "
          f"({len(audit['answer_value_coincidence'])} of {audit['n_memory_values']} "
          f"memory values, rate {audit['answer_value_coincidence_rate']})",
          not audit["coincidence_implausible"])
    check("the audit reports both and calls only one of them a leak",
          audit["clean"] and not audit["leaked"])

    f = features(tests[0])
    check("THE RETRIEVAL KEY LEAKS NO LATENT LABEL",
          all(p not in f for p in PRIMITIVES))
    check("...and no answer", str(tests[0]["answer_value"]) not in f)

    check("mean_reverting alone is generable — the 0.65 pull made it degenerate",
          bool(make_task(0, "probe", ("mean_reverting",))))
    check("every single primitive is generable", all(
        make_task(0, "probe", (p,)) for p in PRIMITIVES))
    check("every composition is generable, memory and hold-out alike",
          all(make_task(0, "probe", c) for c in all_compositions()))

    check("the same arguments reproduce the same task",
          make_task(3, "test", ("linear_trend",)) == make_task(3, "test", ("linear_trend",)))
    check("a different master seed gives a different series",
          make_task(0, "test", ("linear_trend",), master=1)["series"]
          != make_task(0, "test", ("linear_trend",))["series"])

    a = [t for t in tests if t["latent"] == ["linear_trend"]][0]
    b = [t for t in tests if "linear_trend" in t["latent"] and t["composition"]][0]
    c = [t for t in tests if "linear_trend" not in t["latent"]][0]
    check("latent similarity is higher for a shared primitive than for none",
          latent_similarity(a, b) > latent_similarity(a, c))
    check("latent similarity of a task with itself is 1.0",
          latent_similarity(a, a) == 1.0)

    led = ledger()
    check("the ledger carries a sha256 of the frozen task set", len(led["sha256"]) == 64)
    check("the ledger reports the strata", led["strata"]["holdout_composition"] >= 16)

    print("")
    if fails:
        print(str(len(fails)) + " FAILED: " + str(fails))
    else:
        print("ALL " + str(25) + " checks passed")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ledger", action="store_true")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--phase", default="test", choices=("memory", "test"))
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.ledger:
        print(json.dumps(ledger(), ensure_ascii=False, indent=2))
        return 0
    rows = memory_set() if a.phase == "memory" else test_set()
    for t in rows[:a.show or 4]:
        print(f"{t['task_id']}  {t.get('stratum', 'episode'):22s} "
              f"latent={'+'.join(t['latent']):40s} -> {t['answer_value']} "
              f"({'UP' if t['answer_up'] else 'DOWN'})")
        print(f"    key: {features(t)[:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
