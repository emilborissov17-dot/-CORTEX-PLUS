#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC4 Part D2 - REPLAY, WEIGHT, AND A HELD-OUT SET.

Part D found a signal and could not use it. A correct twelve was sampled in round 0,
before any reward - 50 correct out-of-range samples in 2,688 (1.86%) over the run -
and twenty optimiser steps did not move P(correct|10+2) off zero. The diagnosis was in
the budget, not in the idea: each rewarded out-of-range sample was one of roughly
2,200 rows, about 0.2% of a batch otherwise made of the 102 in-range rows carried in
to hold in-range accuracy still.

D2 changes exactly three things and keeps everything else identical:

  1. A REPLAY BUFFER. Every correct out-of-range sample is kept and re-used in every
     later round, so a success found in round 3 is still teaching in round 19 instead
     of evaporating with the batch that found it.
  2. REWARD MASS FIXED AT ~20% OF THE BATCH. In D the signal was 0.2% of the rows by
     accident of counting. Here it is 20% by construction, with the in-range rows
     still present and still holding in-range accuracy in place.
  3. A HELD-OUT OUT-OF-RANGE SET, never sampled for reward and never in the buffer.
     D could only report whether the model got better at the four prompts it was paid
     for, which is not the question. This asks whether anything generalises.

Unchanged from D and pinned: verifier, reward (1.0 / 1.5 / 0), leakage rule
(baseline + 0.05, STOP on breach), control, seed, warm start procedure, lr, one SFT
step per round, 20 rounds, K = 32, temperature 1.0, threads pinned to 1.

A HELD-OUT PROMPT THAT CANNOT BE ASKED
    The brief names four held-out prompts: 8+5, 10+3, 9+5 and 11+3. The first three
    are fine. THE FOURTH IS NOT REPRESENTABLE: the input vocabulary covers 0..10, so
    there is no symbol for eleven, and the model has never seen an eleven on the input
    side. Adding one would change V, and therefore the model's shape, and therefore
    the warm start - which the brief pins as "same as D". The held-out set is the
    three askable prompts; 11+3 is reported NOT EVALUABLE with this reason, rather
    than scored as a zero that would drag the primary metric down by a quarter for a
    vocabulary reason instead of a reasoning one.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.pc4_partc import EQ, END, PAD, TRAIN_MAX, build_data, vocabulary  # noqa: E402
from tools.pc4_partd import (LEAKAGE_SLACK, MAX_NEW, N_THREADS, OUT_OF_RANGE_D,  # noqa: E402
                             SEED, TEMPERATURE, build_model, greedy_accuracy,
                             pin_threads, pretrain, reward_for, sample_completions,
                             verify, weighted_loss)

# never sampled for reward, never in the buffer, never in a training batch
HELD_OUT_OOR = [(8, 5), (10, 3), (9, 5)]
NOT_EVALUABLE = [(11, 3)]           # no input symbol for 11; see the module docstring
REWARD_MASS = 0.20                  # rewarded rows as a fraction of total batch weight
EVAL_ROUNDS = (0, 5, 10, 15, 20)


def scale_to_reward_mass(rewards: list, n_in_range: int,
                         mass: float = REWARD_MASS) -> list:
    """Scale the reward weights so they carry `mass` of the batch's total weight.

    The in-range rows weigh 1.0 each and stay. Solving
        S / (S + n_in_range) = mass    ->    S = mass * n_in_range / (1 - mass)
    and distributing S across the rewarded rows in proportion to their own rewards,
    so the 1.0 / 1.5 structure survives the rescaling and only the overall share
    changes. In D this share was ~0.2% by accident; here it is 20% on purpose.
    """
    if not rewards:
        return []
    total = float(sum(rewards))
    if total <= 0:
        return [0.0] * len(rewards)
    S = mass * n_in_range / (1.0 - mass)
    return [r * S / total for r in rewards]


def eval_prompts(model, pairs, vocab, stoi, itos, k, rng_seed):
    """K sampled completions AND the greedy one, per prompt. Read-only: this never
    feeds the buffer and never reaches a training batch."""
    import torch
    mark = vocab["mark"]

    def enc(a, b):
        return [vocab["num"][a], vocab["ops"]["+"], vocab["num"][b], EQ]

    prompts = [enc(a, b) for a, b in pairs]
    sampled = sample_completions(model, prompts, stoi, itos, k, TEMPERATURE,
                                 mark, rng_seed)
    out = {}
    model.eval()
    with torch.no_grad():
        cur = torch.tensor([[stoi[t] for t in p] for p in prompts])
        B = cur.size(0)
        done = torch.zeros(B, dtype=torch.bool)
        greedy = [[] for _ in range(B)]
        for _ in range(MAX_NEW):
            nxt = model(cur)[:, -1].argmax(-1)
            nxt = torch.where(done, torch.full_like(nxt, stoi[PAD]), nxt)
            for i in range(B):
                if not bool(done[i]) and int(nxt[i]) != stoi[END]:
                    greedy[i].append(itos[int(nxt[i])])
            done = done | (nxt == stoi[END])
            cur = torch.cat([cur, nxt.unsqueeze(1)], 1)
            if bool(done.all()):
                break
    n_ok = 0
    for (a, b), comps, g in zip(pairs, sampled, greedy):
        ok = sum(verify(c, a, b, mark) for c in comps)
        n_ok += ok
        out[f"{a}+{b}"] = {"p_correct": round(ok / k, 4),
                           "greedy_correct": bool(verify(g, a, b, mark)),
                           "greedy_marks": len(g)}
    out["_overall_p_correct"] = round(n_ok / (k * len(pairs)), 4)
    return out


def run_loop2(model, vocab, train, held_in, stoi, itos, V, rounds, k, seed,
              include_out_of_range: bool, lr, label, dump=None):
    import torch
    mark = vocab["mark"]
    in_prompts = [(a, b) for a in range(TRAIN_MAX + 1) for b in range(TRAIN_MAX + 1)
                  if a + b <= TRAIN_MAX]
    oor_prompts = list(OUT_OF_RANGE_D) if include_out_of_range else []
    if not include_out_of_range:
        assert oor_prompts == [], "the control was given out-of-range prompts"
    # THE HELD-OUT SET IS NOT IN THE PROMPT LIST. Asserted here as well as in the
    # tests: a held-out prompt that leaked into the reward loop would make the
    # primary metric a training accuracy while every number still looked plausible.
    assert not (set(oor_prompts) & set(HELD_OUT_OOR)), "a held-out prompt is being trained on"
    pairs = in_prompts + oor_prompts

    def enc(a, b):
        return [vocab["num"][a], vocab["ops"]["+"], vocab["num"][b], EQ]

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.0)
    buffer = []                      # (row, reward) for every correct OOR sample
    rows_log, leak_series, held_out_log = [], [], {}
    baseline_leak = None
    first_correct_12 = None
    stop_reason = None

    for r in range(rounds + 1):
        samples = sample_completions(model, [enc(a, b) for a, b in pairs], stoi, itos,
                                     k, TEMPERATURE, mark, seed * 1000 + r)
        fresh_rows, fresh_w = [], []
        n_oor = n_oor_ok = ok_10p2 = 0
        long_in_range = n_in_range_samples = 0
        for (a, b), comps in zip(pairs, samples):
            oor = a + b > TRAIN_MAX
            for c in comps:
                ok = verify(c, a, b, mark)
                if oor:
                    n_oor += 1
                    n_oor_ok += int(ok)
                    if (a, b) == (10, 2) and ok:
                        ok_10p2 += 1
                    if ok and a + b == 12 and first_correct_12 is None:
                        first_correct_12 = r
                else:
                    n_in_range_samples += 1
                    # THE RULE SAYS MARKS. It said marks in the
                    # pre-registration and it counted tokens in the code
                    # until 6 Sep. Both series are reported for the runs
                    # already done; from here it counts what it says.
                    if sum(1 for t in c if t == mark) >= TRAIN_MAX + 1:
                        long_in_range += 1
                w = reward_for(ok, a, b)
                if dump is not None:
                    dump.append({"arm": label, "round": r, "prompt": f"{a}+{b}",
                                 "a": a, "b": b, "completion": list(c),
                                 # n_tokens is the LENGTH; n_marks counts MARKS ONLY.
                                 # They were one field called n_marks until an
                                 # independent recount found it counting non-marks
                                 # too, which made the pre-registered leakage rule
                                 # "P(>= 11 MARKS)" run as P(length >= 11).
                                 "n_tokens": len(c),
                                 "n_marks": sum(1 for t in c if t == mark),
                                 "verifier_correct": bool(ok),
                                 "reward": w})
                if w > 0:
                    fresh_rows.append((enc(a, b), c))
                    fresh_w.append(w)
                    if oor:
                        buffer.append(((enc(a, b), c), w))   # REPLAY

        leak = long_in_range / max(1, n_in_range_samples)
        if baseline_leak is None:
            baseline_leak = leak
        leak_series.append(round(leak, 4))

        if r in EVAL_ROUNDS:
            held_out_log[str(r)] = eval_prompts(model, HELD_OUT_OOR, vocab, stoi,
                                                itos, k, seed * 7919 + r)

        rows_log.append({
            "round": r,
            "exploration_rate": round(n_oor_ok / n_oor, 4) if n_oor else None,
            "p_correct_10p2": round(ok_10p2 / k, 4) if oor_prompts else None,
            "p_correct_any_oor": round(n_oor_ok / n_oor, 4) if n_oor else None,
            "in_range_heldout": round(greedy_accuracy(model, held_in, stoi, itos), 4),
            "leak_p_ge_11_marks_in_range": round(leak, 4),
            "buffer_size": len(buffer),
            "n_rewarded_fresh": len(fresh_rows),
            "held_out": held_out_log.get(str(r)),
        })

        if r == 0 and include_out_of_range and rows_log[-1]["exploration_rate"] == 0.0:
            stop_reason = "no exploration, no signal"
            break
        if r > 0 and leak > baseline_leak + LEAKAGE_SLACK:
            stop_reason = "reward hacking"
            break
        if r == rounds:
            break

        rewarded = fresh_rows + [row for row, _ in buffer]
        raw_w = fresh_w + [w for _, w in buffer]
        scaled = scale_to_reward_mass(raw_w, len(train))
        rows = rewarded + list(train)
        ws = scaled + [1.0] * len(train)
        model.train()
        opt.zero_grad()
        weighted_loss(model, rows, ws, stoi, V).backward()
        opt.step()

    return {"label": label, "rounds": rows_log, "leak_series": leak_series,
            "baseline_leak": round(baseline_leak, 4) if baseline_leak is not None else None,
            "first_correct_12": first_correct_12, "stop_reason": stop_reason,
            "held_out_by_round": held_out_log, "final_buffer_size": len(buffer)}


def _provenance(cmd):
    import torch
    src = Path(__file__).read_bytes()
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, cwd=REPO).stdout.strip()
    except Exception:
        sha = "unknown"
    return {"script_sha256": hashlib.sha256(src).hexdigest(),
            "script_bytes": len(src), "command": " ".join(cmd),
            "venv": sys.executable, "python": sys.version.split()[0],
            "torch": torch.__version__, "threads": torch.get_num_threads(),
            "git_commit": sha,
            "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--k", type=int, default=32)
    ap.add_argument("--pretrain-steps", type=int, default=8000)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default="claude/reports/PC4_PARTD2.json")
    ap.add_argument("--dump-samples", default="claude/reports/PC4_PARTD2_samples.jsonl")
    a = ap.parse_args()

    pin_threads()
    import torch
    assert torch.get_num_threads() == N_THREADS
    prov = _provenance(sys.argv)

    vocab = vocabulary("c2")
    train, held_in, oor, *_ = build_data(vocab)
    maxlen = 4 + MAX_NEW + 2
    toks = [PAD, END, EQ] + sorted({t for p, y in train + held_in + oor for t in p + y})
    toks = list(dict.fromkeys(toks))
    stoi = {t: i for i, t in enumerate(toks)}
    itos = {i: t for t, i in stoi.items()}
    V = len(stoi)

    print(f"reward mass target: {REWARD_MASS}   replay: on   rounds: {a.rounds}")
    print(f"paid out-of-range prompts : {[(x, y, x + y) for x, y in OUT_OF_RANGE_D]}")
    print(f"HELD-OUT out-of-range     : {[(x, y, x + y) for x, y in HELD_OUT_OOR]}")
    print(f"NOT EVALUABLE             : {[(x, y, x + y) for x, y in NOT_EVALUABLE]}"
          f"  (no input symbol for 11)")

    model, sel = pretrain(vocab, train, held_in, stoi, itos, V, maxlen,
                          a.pretrain_steps, a.seed)
    print(f"warm start selected at step {sel['selected_step']}, "
          f"in-range {sel['in_range_at_selection']}")

    dump = []
    main_run = run_loop2(copy.deepcopy(model), vocab, train, held_in, stoi, itos, V,
                         a.rounds, a.k, a.seed, True, a.lr, "main", dump)
    ctrl_run = run_loop2(copy.deepcopy(model), vocab, train, held_in, stoi, itos, V,
                         a.rounds, a.k, a.seed, False, a.lr, "control", dump)

    for run in (main_run, ctrl_run):
        print(f"\n--- {run['label']} ---  stop={run['stop_reason']}  "
              f"first_correct_12={run['first_correct_12']}  "
              f"buffer={run['final_buffer_size']}")
        print(" round  explore  P(10+2)  in-range   leak   buffer  HELD-OUT")
        for r in run["rounds"]:
            def f(x):
                return "  n/a " if x is None else f"{x:6.4f}"
            ho = r["held_out"]["_overall_p_correct"] if r["held_out"] else None
            print(f" {r['round']:>5}  {f(r['exploration_rate'])}  {f(r['p_correct_10p2'])}"
                  f"  {r['in_range_heldout']:6.4f}  {r['leak_p_ge_11_marks_in_range']:6.4f}"
                  f"  {r['buffer_size']:>5}   {'' if ho is None else f'{ho:6.4f}'}")

    prov["ended_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    Path(a.dump_samples).write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in dump) + "\n",
        encoding="utf-8")
    Path(a.out).write_text(json.dumps(
        {"provenance": prov, "seed": a.seed, "k": a.k, "lr": a.lr,
         "reward_mass": REWARD_MASS, "warm_start": sel,
         "paid_oor": [[x, y] for x, y in OUT_OF_RANGE_D],
         "held_out_oor": [[x, y] for x, y in HELD_OUT_OOR],
         "not_evaluable": [[x, y] for x, y in NOT_EVALUABLE],
         "main": main_run, "control": ctrl_run},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {a.out}\n-> {a.dump_samples}  ({len(dump)} sampled completions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
