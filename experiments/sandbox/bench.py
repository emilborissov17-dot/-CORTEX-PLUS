#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/sandbox/bench.py — T8, T6 and T12 on the hidden world.

  T8  (points 5/8)  Train on 400 observational rows. Test on 100 interventions
                    the learner never saw. Per learner: direction accuracy on
                    variables that truly move, MAE of the predicted post-
                    intervention means, and the FALSE-MOVE rate on non-
                    descendants (the confounding trap). Baseline: "nothing
                    changes" (persistence). Ceiling: the truth.
  T6  (point 6)     Credit: for a target variable, WHICH single intervention
                    moves it most? Learner's pick vs the true best; hit-rate vs
                    random (1/9).
  T12 (point 12)    Action -> consequence -> revision: the causal learner spends
                    a budget of interventions of its own choosing (the ones its
                    graph is least sure about), updates, and is re-scored on a
                    fixed held-out set each round. The curve must fall; if it
                    does not, acting taught it nothing.
  T6A (6 after 12)  Does CREDIT learn from action the way STRUCTURE does? The
                    identical credit questions of T6 — same targets, same
                    candidate values, same Monte-Carlo ground truth — put to the
                    T12 learner AFTER its 20 self-chosen interventions. T12
                    already proves acting buys the graph; this asks whether the
                    graph it buys is good enough to answer "who moved this".
                    The questions are built once (`_t6_questions`) and scored by
                    a function that touches neither the world nor the RNG
                    (`_t6_score`): a second `_t6_questions` call would draw new
                    targets and fresh truth, and before/after would not be the
                    same test. test_sandbox.py holds the net.

Pre-registered pass rules (written before the first run, 10 Sep 2026;
T6A added and registered 10 Sep 2026 before it was first executed):
  T8  PASS  anm_causal direction accuracy >= naive + 0.15 AND
            anm_causal non-descendant false-move rate <= 0.5 * naive's
  T6  PASS  anm_causal hit-rate >= 0.5 and > naive
  T12 PASS  MAE after 5 rounds <= 0.8 * MAE at round 0
  T6A PASS  after-action hit-rate >= before-action hit-rate + 0.15 AND
            after-action hit-rate > naive_correlation's
Averaged over 5 seeds. Everything else is a FAIL and is reported as one. A
T6A that lands on top of T6 is the interesting negative result, not a bug to
be tuned away: it would mean action repairs the structure and not the credit.

Usage:
  venv\\Scripts\\python.exe experiments/sandbox/bench.py [--seeds 5] [--write]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from world import World, descendants, truth_for_grader  # noqa: E402
from learners import LEARNERS, ANMCausal  # noqa: E402

N_OBS, N_INT, N_PER_INT, MOVE_EPS = 400, 100, 300, 0.10
REPORT = REPO / "claude" / "reports" / "SANDBOX_BENCH.md"
READING_MARK = "## Reading"


def _interventions(world: World, rng: np.random.Generator, X_obs: np.ndarray, k: int):
    mu, sd = X_obs.mean(axis=0), X_obs.std(axis=0) + 1e-9
    names = world.variables()
    out = []
    for _ in range(k):
        i = int(rng.integers(len(names)))
        v = float(mu[i] + rng.choice([-1.5, 1.5]) * sd[i])
        out.append((names[i], v))
    return out


def _truth_means(world: World, var: str, value: float) -> dict:
    X = world.intervene(var, value, N_PER_INT)
    return {nm: float(X[:, j].mean()) for j, nm in enumerate(world.variables()) if nm != var}


def t8(world: World, learners: dict, X_obs: np.ndarray, ints: list, sd: np.ndarray) -> dict:
    names = world.variables()
    mu = {nm: float(X_obs[:, j].mean()) for j, nm in enumerate(names)}
    truths = [(var, val, _truth_means(world, var, val)) for var, val in ints]
    res = {}
    for lname, L in list(learners.items()) + [("persistence", None)]:
        dir_ok = dir_n = 0
        abs_err = []
        false_move = fm_n = 0
        for var, val, tm in truths:
            pred = {nm: mu[nm] for nm in tm} if L is None else L.predict(var, val)
            desc = descendants(world, var)
            for nm, tv in tm.items():
                s = sd[names.index(nm)]
                true_d, pred_d = (tv - mu[nm]) / s, (pred[nm] - mu[nm]) / s
                abs_err.append(abs(true_d - pred_d))
                if abs(true_d) > MOVE_EPS:
                    dir_n += 1
                    dir_ok += int(np.sign(true_d) == np.sign(pred_d))
                if nm not in desc:
                    fm_n += 1
                    false_move += int(abs(pred_d) > MOVE_EPS)
        res[lname] = {"direction_acc": round(dir_ok / dir_n, 4) if dir_n else None,
                      "mae_sd_units": round(float(np.mean(abs_err)), 4),
                      "false_move_nondesc": round(false_move / fm_n, 4) if fm_n else None,
                      "n_pairs": len(abs_err)}
    return res


def _t6_questions(world: World, X_obs: np.ndarray, rng: np.random.Generator, sd: np.ndarray, k: int = 20):
    """The credit questions, built ONCE per world: a target, the nine candidate
    interventions, the true best of them, and the random baseline's pick.

    Both the before-action learners (T6) and the after-action learner (T6A) are
    scored on THIS list. Calling this a second time would draw different targets
    and re-estimate the truth from fresh Monte-Carlo samples, so the two
    hit-rates would no longer be answers to the same questions — the easy
    mistake this split exists to make impossible.
    """
    names = world.variables()
    mu = X_obs.mean(axis=0)
    questions, rand_hits = [], 0
    for _ in range(k):
        t = int(rng.integers(len(names)))
        target = names[t]
        cands = [(nm, float(mu[j] + 1.5 * sd[j])) for j, nm in enumerate(names) if j != t]
        true_eff = {nm: abs(_truth_means(world, nm, v)[target] - mu[t]) for nm, v in cands}
        best = max(true_eff, key=true_eff.get)
        rand_hits += int(cands[int(rng.integers(len(cands)))][0] == best)
        questions.append({"target": target, "mu_target": float(mu[t]), "cands": cands, "best": best})
    return questions, rand_hits


def _t6_score(questions: list, learners: dict) -> dict:
    """Hit-rate of each learner on a fixed question list. Pure: no world call,
    no RNG draw. Anything else and the after-action score is measured against a
    different truth than the before-action one."""
    out = {}
    for ln, L in learners.items():
        hits = 0
        for q in questions:
            target, mu_t = q["target"], q["mu_target"]
            pick = max(q["cands"], key=lambda c: abs(L.predict(c[0], c[1])[target] - mu_t))[0]
            hits += int(pick == q["best"])
        out[ln] = round(hits / len(questions), 3)
    return out


def t12(world: World, X_obs: np.ndarray, rng: np.random.Generator, sd: np.ndarray, rounds: int = 5, per_round: int = 4) -> list:
    names = world.variables()
    L = ANMCausal().fit(X_obs, names)
    held = _interventions(world, rng, X_obs, 50)
    truths = [(var, val, _truth_means(world, var, val)) for var, val in held]
    mu = {nm: float(X_obs[:, j].mean()) for j, nm in enumerate(names)}

    def score():
        errs = []
        for var, val, tm in truths:
            p = L.predict(var, val)
            errs += [abs((tm[nm] - p[nm]) / sd[names.index(nm)]) for nm in tm]
        return round(float(np.mean(errs)), 4)
    truth = truth_for_grader(world)["parents"]

    def recall():
        d = L.discovered()
        tp = sum(1 for v, ps in truth.items() for p in ps if p in d[v])
        return round(tp / max(1, sum(len(ps) for ps in truth.values())), 3)
    curve = [score()]
    recalls = [recall()]
    for _ in range(rounds):
        # act where the model is least sure: the variables with the most discovered parents
        # get their mechanisms probed; a random value inside the observed range
        order = L.least_known()
        for i in order[:per_round]:
            var = names[i]
            val = float(mu[var] + rng.choice([-1.5, -0.75, 0.75, 1.5]) * sd[i])
            X_int = world.intervene(var, val, 50)
            L.update(var, val, X_int)
        curve.append(score())
        recalls.append(recall())
    # the learner itself goes back to the caller: T6A re-asks the T6 credit
    # questions of exactly this object, after exactly these interventions
    return {"curve": curve, "recall": recalls, "learner": L, "n_interventions": rounds * per_round}


def run(seeds: int = 5) -> dict:
    per_seed = []
    for s in range(seeds):
        world = World(seed=1000 + s)
        rng = np.random.default_rng(7 + s)
        X_obs = world.observe(N_OBS)
        sd = X_obs.std(axis=0) + 1e-9
        names = world.variables()
        learners = {ln: cls().fit(X_obs, names) for ln, cls in LEARNERS.items()}
        ints = _interventions(world, rng, X_obs, N_INT)
        r8 = t8(world, learners, X_obs, ints, sd)
        questions, rand_hits = _t6_questions(world, X_obs, rng, sd)
        r6 = _t6_score(questions, learners)
        r6["random"] = round(rand_hits / len(questions), 3)
        # T12 runs next and consumes the rng after T6, exactly as before; T6A is
        # scored afterwards and draws nothing, so T8/T6/T12 are bit-identical to
        # the run that produced the report this replaces.
        r12 = t12(world, X_obs, rng, sd)
        r12_curve, r12_recall = r12["curve"], r12["recall"]
        r6_after = _t6_score(questions, {"anm_causal_after_action": r12["learner"]})["anm_causal_after_action"]
        # how much of the hidden graph the causal learner recovered (grader-side)
        truth = truth_for_grader(world)["parents"]
        disc = learners["anm_causal"].discovered()
        tp = sum(1 for v, ps in truth.items() for p in ps if p in disc[v])
        n_true = sum(len(ps) for ps in truth.values())
        n_disc = sum(len(ps) for ps in disc.values())
        per_seed.append({"seed": world.seed, "t8": r8, "t6": r6, "t6_after": r6_after,
                         "t12_curve": r12_curve, "t12_recall": r12_recall,
                         "t12_interventions": r12["n_interventions"],
                         "graph_recall": round(tp / n_true, 3) if n_true else None,
                         "graph_precision": round(tp / n_disc, 3) if n_disc else None,
                         "spent": world.spent()})

    def avg(path):
        vals = []
        for r in per_seed:
            v = r
            for k in path:
                v = v[k]
            if v is not None:
                vals.append(v)
        return round(float(np.mean(vals)), 4) if vals else None
    L = list(LEARNERS) + ["persistence"]
    summary = {"t8": {ln: {m: avg(["t8", ln, m]) for m in ("direction_acc", "mae_sd_units", "false_move_nondesc")} for ln in L},
               "t6": {ln: avg(["t6", ln]) for ln in list(LEARNERS) + ["random"]},
               "t6_after": avg(["t6_after"]),
               "t12_interventions": per_seed[0]["t12_interventions"],
               "t12_curve": [round(float(np.mean([r["t12_curve"][k] for r in per_seed])), 4) for k in range(len(per_seed[0]["t12_curve"]))],
               "t12_recall": [round(float(np.mean([r["t12_recall"][k] for r in per_seed])), 3) for k in range(len(per_seed[0]["t12_recall"]))],
               "graph_recall": avg(["graph_recall"]), "graph_precision": avg(["graph_precision"])}
    summary["verdict"] = verdicts(summary)
    return {"seeds": seeds, "n_obs": N_OBS, "n_int": N_INT, "summary": summary, "per_seed": per_seed}


T6A_MARGIN = 0.15


def verdicts(summary: dict) -> dict:
    """The pre-registered rules, as a pure function of the summary so they can be
    exercised on synthetic numbers (test_sandbox.py). Nothing but PASS or FAIL:
    there is no 'partial' and no 'inconclusive' to retreat into."""
    a, n = summary["t8"]["anm_causal"], summary["t8"]["naive_correlation"]
    t6a, t6b = summary["t6_after"], summary["t6"]["anm_causal"]
    return {
        "T8": "PASS" if (a["direction_acc"] >= n["direction_acc"] + 0.15 and a["false_move_nondesc"] <= 0.5 * n["false_move_nondesc"]) else "FAIL",
        "T6": "PASS" if (summary["t6"]["anm_causal"] >= 0.5 and summary["t6"]["anm_causal"] > summary["t6"]["naive_correlation"]) else "FAIL",
        "T12": "PASS" if summary["t12_curve"][-1] <= 0.8 * summary["t12_curve"][0] else "FAIL",
        "T6A": "PASS" if (t6a >= t6b + T6A_MARGIN and t6a > summary["t6"]["naive_correlation"]) else "FAIL",
        "rule": "pre-registered in bench.py docstring, 10 Sep 2026, before the first run",
    }


def markdown(r: dict) -> str:
    s = r["summary"]
    L = ["# SANDBOX BENCH — causal learning in a world with hidden structure",
         f"{r['seeds']} worlds (seeds 1000+), {r['n_obs']} observational rows, {r['n_int']} held-out interventions each, "
         "10 variables, non-linear mechanisms, collider + mediator + confounder forced.", "",
         "## T8 — observational training, interventional test",
         "| learner | direction acc (moving vars) | MAE (sd units) | false-move on non-descendants |", "|---|---:|---:|---:|"]
    for ln, m in s["t8"].items():
        L.append(f"| {ln} | {m['direction_acc']} | {m['mae_sd_units']} | {m['false_move_nondesc']} |")
    L += ["", f"Graph recovered by anm_causal: recall {s['graph_recall']}, precision {s['graph_precision']}.", "",
          "## T6 — credit: which single intervention moves the target most (hit-rate, 20 targets/world)",
          "| " + " | ".join(s["t6"].keys()) + " |", "|" + "---:|" * len(s["t6"]),
          "| " + " | ".join(str(v) for v in s["t6"].values()) + " |", "",
          "## T6A — the SAME credit questions, asked again after the T12 interventions",
          f"Identical targets, candidate values and ground truth as T6 above; the only difference is "
          f"{s['t12_interventions']} self-chosen interventions of the learner's own.", "",
          "| anm_causal before acting | anm_causal after acting | naive_correlation | random |", "|---:|---:|---:|---:|",
          f"| {s['t6']['anm_causal']} | {s['t6_after']} | {s['t6']['naive_correlation']} | {s['t6']['random']} |", "",
          "## T12 — action -> consequence -> revision (MAE on a fixed held-out set, per round)",
          "MAE by round:          " + "  ".join(f"{i}:{v}" for i, v in enumerate(s["t12_curve"])),
          "graph recall by round: " + "  ".join(f"{i}:{v}" for i, v in enumerate(s["t12_recall"])), "",
          "## Verdict (pre-registered rules)", ""]
    L += [f"- {k}: **{v}**" for k, v in s["verdict"].items()]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    seeds = int(sys.argv[sys.argv.index("--seeds") + 1]) if "--seeds" in sys.argv else 5
    r = run(seeds)
    md = markdown(r)
    if "--write" in sys.argv:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        # markdown() regenerates the measured tables only. The interpretation
        # under "## Reading" is written by a human after a run and cannot be
        # regenerated; --write used to silently delete it. Carry it across.
        old = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""
        tail = old[old.index(READING_MARK):] if READING_MARK in old else ""
        REPORT.write_text(md + ("\n" + tail if tail else ""), encoding="utf-8")
        (REPORT.with_suffix(".json")).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {REPORT}")
    print(md)
