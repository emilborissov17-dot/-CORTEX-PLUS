#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC4 Part D - REWARD FOR THE NEW.

Parts A2 and C established that a model trained only on results 0..10 answers 0 of 8
out-of-range questions, at every one of 369 checkpoints, across three representations
and nine seeds - and that the failure has one shape: it emits a complete, legal answer
meaning ten and stops. Nothing in 102 examples ever rewarded continuing past a
complete answer, so the rule induced is "produce the result, then stop", which is
correct on every training example and silent about 12.

Part D removes exactly that. It never shows the model an out-of-range TARGET. It only
samples, verifies with the rule, and pays more for a correct answer above ten. If the
clamp is a missing incentive rather than a missing capability, this is what dissolves
it. If the model can never SAMPLE a correct 12 in the first place, no reward can
teach it one, and that is a finding rather than a failure of the method.

WHICH REPRESENTATION, AND WHY IT CANNOT BE A2's
    The brief says "start from the A2 checkpoint" and also "verify with the RULE
    (count marks == a+b)". Those cannot both be taken literally. A2's answer is ONE
    ATOMIC SYMBOL - there are no marks to count, and no token for 12 exists at all,
    so P(output >= 11 marks) and "a correct 12" are undefined there.
    Every quantity the brief asks for - the verifier, the 1.5 reward, the leakage
    series, "the first round with a correct 12" - is defined in MARKS. So Part D runs
    on the TALLY representation from Part C2, warm-started on in-range results 0..10
    exactly as A2 was. That is the reading under which the whole specification is
    coherent, and it is the only one.

REPRODUCIBILITY (88dafd5)
    Part C established that this regime's endpoints are not portable across thread
    counts: the same seed gives in-range 0.400 at one OMP_NUM_THREADS and 0.467 at
    another, both reproducing exactly under their own command. So threads are PINNED
    IN CODE here, not left to the environment, and a guard test asserts it.

    venv_train\\Scripts\\python.exe tools/pc4_partd.py --rounds 20
"""
from __future__ import annotations

import argparse
import copy
import json
import random
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
import sys                                                          # noqa: E402
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.pc4_partc import (PAD, END, EQ, TRAIN_MAX,               # noqa: E402
                             build_data, encode_result, vocabulary)

SEED = 20260906
N_THREADS = 1                       # pinned; see the reproducibility note above
K_SAMPLES = 32
TEMPERATURE = 1.0
ROUNDS = 20
MAX_NEW = 20                        # > 14, so an over-long answer is OBSERVABLE
LEAKAGE_SLACK = 0.05

# results 12, 12, 13, 14 - never a training target, and never shown as one
OUT_OF_RANGE_D = [(10, 2), (7, 5), (9, 4), (10, 4)]


def pin_threads() -> None:
    import torch
    torch.set_num_threads(N_THREADS)


# ── the verifier: the RULE, never a lookup table ────────────────────────────
def verify(completion: list, a: int, b: int, mark: str) -> bool:
    """Correct iff the completion is MARKS ONLY and there are exactly a+b of them.

    Both halves matter. Counting length alone would accept twelve of the wrong
    symbol, which is not the answer twelve - it is a sequence that happens to be
    twelve long. There is no table of answers anywhere in this function; it
    recomputes a+b every time it is called.
    """
    if any(t != mark for t in completion):
        return False
    return len(completion) == a + b


def reward_for(correct: bool, a: int, b: int) -> float:
    """1.0 for correct, 1.5 for correct AND above ten, 0.0 for wrong.

    The bonus is gated on `correct` FIRST. A wrong answer to an out-of-range prompt
    must never be paid more than a wrong answer to an in-range one, or the model is
    being paid for the attempt rather than the result.
    """
    if not correct:
        return 0.0
    return 1.5 if a + b > TRAIN_MAX else 1.0


# ── the model ───────────────────────────────────────────────────────────────
def build_model(V: int, maxlen: int, seed: int):
    import torch
    import torch.nn as nn

    torch.manual_seed(seed)

    class TinyLM(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(V, 64)
            self.pos = nn.Parameter(torch.zeros(1, maxlen, 64))
            layer = nn.TransformerEncoderLayer(64, 4, 128, batch_first=True,
                                               dropout=0.0)
            self.enc = nn.TransformerEncoder(layer, 2)
            self.head = nn.Linear(64, V)

        def forward(self, x):
            T = x.size(1)
            mask = torch.triu(torch.ones(T, T, dtype=torch.bool), diagonal=1)
            return self.head(self.enc(self.emb(x) + self.pos[:, :T], mask=mask))

    return TinyLM()


def _pack(rows, stoi, device="cpu"):
    import torch
    seqs, labs = [], []
    for p, y in rows:
        seqs.append([stoi[t] for t in p + y + [END]])
        labs.append([-100] * len(p) + [stoi[t] for t in y + [END]])
    n = max(len(s) for s in seqs)
    X = torch.tensor([s + [stoi[PAD]] * (n - len(s)) for s in seqs], device=device)
    Y = torch.tensor([lb + [-100] * (n - len(lb)) for lb in labs], device=device)
    return X, Y


def weighted_loss(model, rows, weights, stoi, V):
    """Cross-entropy per sequence, scaled by that sequence's reward."""
    import torch
    import torch.nn.functional as F
    X, Y = _pack(rows, stoi)
    logits = model(X)[:, :-1]
    tgt = Y[:, 1:]
    per_tok = F.cross_entropy(logits.reshape(-1, V), tgt.reshape(-1),
                              ignore_index=-100, reduction="none")
    per_tok = per_tok.view(tgt.shape)
    mask = (tgt != -100).float()
    per_seq = (per_tok * mask).sum(1) / mask.sum(1).clamp(min=1)
    w = torch.tensor(weights, dtype=per_seq.dtype)
    return (per_seq * w).sum() / w.sum().clamp(min=1e-8)


def sample_completions(model, prompts, stoi, itos, k: int, temperature: float,
                       mark: str, rng_seed: int, chunk: int = 512):
    """K sampled completions per prompt at the given temperature. NOT greedy.

    Sampling is the whole point: greedy decoding can only ever produce the clamp, so
    a greedy loop would measure nothing and could learn nothing.
    """
    import torch
    model.eval()
    g = torch.Generator().manual_seed(rng_seed)
    flat = [p for p in prompts for _ in range(k)]
    out = []
    with torch.no_grad():
        for s in range(0, len(flat), chunk):
            batch = flat[s:s + chunk]
            cur = torch.tensor([[stoi[t] for t in p] for p in batch])
            B = cur.size(0)
            done = torch.zeros(B, dtype=torch.bool)
            got = [[] for _ in range(B)]
            for _ in range(MAX_NEW):
                logits = model(cur)[:, -1] / temperature
                probs = torch.softmax(logits, dim=-1)
                nxt = torch.multinomial(probs, 1, generator=g).squeeze(1)
                nxt = torch.where(done, torch.full_like(nxt, stoi[PAD]), nxt)
                for i in range(B):
                    if not bool(done[i]) and int(nxt[i]) != stoi[END]:
                        got[i].append(itos[int(nxt[i])])
                done = done | (nxt == stoi[END])
                cur = torch.cat([cur, nxt.unsqueeze(1)], 1)
                if bool(done.all()):
                    break
            out.extend(got)
    return [out[i * k:(i + 1) * k] for i in range(len(prompts))]


def greedy_accuracy(model, rows, stoi, itos):
    import torch
    model.eval()
    with torch.no_grad():
        cur = torch.tensor([[stoi[t] for t in p] for p, _ in rows])
        B = cur.size(0)
        done = torch.zeros(B, dtype=torch.bool)
        got = [[] for _ in range(B)]
        for _ in range(MAX_NEW):
            nxt = model(cur)[:, -1].argmax(-1)
            nxt = torch.where(done, torch.full_like(nxt, stoi[PAD]), nxt)
            for i in range(B):
                if not bool(done[i]) and int(nxt[i]) != stoi[END]:
                    got[i].append(itos[int(nxt[i])])
            done = done | (nxt == stoi[END])
            cur = torch.cat([cur, nxt.unsqueeze(1)], 1)
            if bool(done.all()):
                break
    return float(np.mean([g == y for g, (_, y) in zip(got, rows)]))


def leakage_breached(series: list, baseline: float) -> bool:
    """P(>= 11 marks | IN-RANGE prompt) must not rise above baseline + 0.05.

    This is the reward-hacking check. The bonus pays 1.5 for long correct answers;
    the cheapest way to collect it, if the model finds it, is to get longer
    everywhere. If in-range answers start growing, the model is being paid for
    length rather than for arithmetic and the run is over. Nothing gets tuned.
    """
    return any(v > baseline + LEAKAGE_SLACK for v in series)


# ── the loop ────────────────────────────────────────────────────────────────
def pretrain(vocab, train, held_in, stoi, itos, V, maxlen, steps, seed, lr=3e-3,
             weight_decay=1.0, select_every=250):
    """Warm start on in-range results 0..10 only, exactly as A2 was.

    The checkpoint is SELECTED on held-out in-range accuracy rather than taken at the
    last step. Part C measured 81 of 123 C2 checkpoints below 0.5 training accuracy;
    starting Part D from whatever the last step happened to be would make the whole
    experiment a lottery on the warm start.
    """
    import torch
    model = build_model(V, maxlen, seed)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    X, Y = _pack(train, stoi)
    import torch.nn as nn
    lossf = nn.CrossEntropyLoss(ignore_index=-100)
    best, best_state, best_step = -1.0, None, -1
    for step in range(steps):
        if step % select_every == 0:
            acc = greedy_accuracy(model, held_in, stoi, itos)
            if acc > best:
                best, best_state, best_step = acc, copy.deepcopy(model.state_dict()), step
        model.train()
        opt.zero_grad()
        logits = model(X)[:, :-1]
        lossf(logits.reshape(-1, V), Y[:, 1:].reshape(-1)).backward()
        opt.step()
    acc = greedy_accuracy(model, held_in, stoi, itos)
    if acc > best:
        best, best_state, best_step = acc, copy.deepcopy(model.state_dict()), steps
    model.load_state_dict(best_state)
    return model, {"selected_step": best_step, "in_range_at_selection": round(best, 4)}


def run_loop(model, vocab, train, held_in, stoi, itos, V, rounds, k, seed,
             include_out_of_range: bool, lr=1e-3, label="main", dump=None):
    """`dump`, if given, is a list that receives ONE record per sampled
    completion. It is write-only bookkeeping: it never reads back, never
    branches, and never touches the torch Generator, so the run it records is
    the run that would have happened without it. That claim is not left as an
    assertion - the dump run is reproduced against the undumped one and the
    per-round numbers are compared."""
    import torch
    mark = vocab["mark"]
    in_prompts = [(a, b) for a in range(TRAIN_MAX + 1) for b in range(TRAIN_MAX + 1)
                  if a + b <= TRAIN_MAX]
    oor_prompts = list(OUT_OF_RANGE_D) if include_out_of_range else []
    # THE CONTROL MUST NEVER SEE THEM. Asserted here as well as in the tests,
    # because a control that quietly received the prompts would be the one bug that
    # invalidates the entire result while every number still looked plausible.
    if not include_out_of_range:
        assert oor_prompts == [], "the control was given out-of-range prompts"
    pairs = in_prompts + oor_prompts

    def enc_prompt(a, b):
        return [vocab["num"][a], vocab["ops"]["+"], vocab["num"][b], EQ]

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.0)
    rows_log, leak_series = [], []
    baseline_leak = None
    first_correct_12 = None
    stop_reason = None

    for r in range(rounds + 1):
        prompts = [enc_prompt(a, b) for a, b in pairs]
        samples = sample_completions(model, prompts, stoi, itos, k, TEMPERATURE,
                                     mark, seed * 1000 + r)

        rewarded_rows, weights = [], []
        n_oor_ok = n_oor = 0
        ok_10p2 = 0
        long_in_range = 0
        n_in_range_samples = 0
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
                    if len(c) >= TRAIN_MAX + 1:
                        long_in_range += 1
                w = reward_for(ok, a, b)
                if dump is not None:
                    dump.append({"arm": label, "round": r, "prompt": f"{a}+{b}",
                                 "a": a, "b": b, "completion": list(c),
                                 "n_marks": len(c),
                                 "verifier_correct": bool(ok), "reward": w})
                if w > 0:
                    rewarded_rows.append((enc_prompt(a, b), c))
                    weights.append(w)

        leak = long_in_range / max(1, n_in_range_samples)
        if baseline_leak is None:
            baseline_leak = leak
        leak_series.append(round(leak, 4))
        row = {
            "round": r,
            "exploration_rate": round(n_oor_ok / n_oor, 4) if n_oor else None,
            "p_correct_10p2": round(ok_10p2 / k, 4) if oor_prompts else None,
            "p_correct_any_oor": round(n_oor_ok / n_oor, 4) if n_oor else None,
            "in_range_heldout": round(greedy_accuracy(model, held_in, stoi, itos), 4),
            "leak_p_ge_11_marks_in_range": round(leak, 4),
            "n_rewarded": len(rewarded_rows),
        }
        rows_log.append(row)

        if r == 0 and include_out_of_range and row["exploration_rate"] == 0.0:
            stop_reason = "no exploration, no signal"
            break
        if r > 0 and leak > baseline_leak + LEAKAGE_SLACK:
            stop_reason = "reward hacking"
            break
        if r == rounds:
            break

        # ── one weighted-SFT step, rewarded samples only, with the in-range
        # training set kept in the batch so in-range accuracy cannot silently drop.
        rows = rewarded_rows + list(train)
        ws = weights + [1.0] * len(train)
        model.train()
        opt.zero_grad()
        weighted_loss(model, rows, ws, stoi, V).backward()
        opt.step()

    return {"label": label, "rounds": rows_log, "leak_series": leak_series,
            "baseline_leak": round(baseline_leak, 4) if baseline_leak is not None else None,
            "first_correct_12": first_correct_12, "stop_reason": stop_reason}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    ap.add_argument("--k", type=int, default=K_SAMPLES)
    ap.add_argument("--pretrain-steps", type=int, default=8000)
    ap.add_argument("--seed", type=int, default=SEED)
    # CALIBRATED ON THE CONTROL, never on the outcome. At lr=1e-3 a single weighted
    # step took the control's in-range accuracy from 0.60 to 0.03 - the model was
    # destroyed by round 1 and the loop would have measured nothing. The brief says
    # "keep the in-range training set in the batch so in-range accuracy cannot
    # silently drop"; a step size that drops it loudly fails the same requirement.
    ap.add_argument("--lr", type=float, default=3e-4,
                    help="SFT step size, calibrated on the control's in-range stability")
    ap.add_argument("--out", default="claude/reports/PC4_PARTD.json")
    ap.add_argument("--dump-samples", default=None,
                    help="JSONL path for every sampled completion")
    a = ap.parse_args()

    pin_threads()
    import torch
    assert torch.get_num_threads() == N_THREADS

    vocab = vocabulary("c2")
    train, held_in, oor, raw_tr, raw_in, raw_oo = build_data(vocab)
    maxlen = 4 + MAX_NEW + 2
    toks = [PAD, END, EQ] + sorted({t for p, y in train + held_in + oor
                                    for t in p + y})
    toks = list(dict.fromkeys(toks))
    stoi = {t: i for i, t in enumerate(toks)}
    itos = {i: t for t, i in stoi.items()}
    V = len(stoi)

    print(f"mark: {vocab['mark']}   12 = {' '.join(encode_result(vocab, 12))}")
    print(f"training answer lengths: {sorted({len(y) for _, y in train})}  "
          f"(never above {TRAIN_MAX})")
    print(f"out-of-range prompts: {[(a, b, a + b) for a, b in OUT_OF_RANGE_D]}  "
          f"- targets are NEVER shown")

    model, sel = pretrain(vocab, train, held_in, stoi, itos, V, maxlen,
                          a.pretrain_steps, a.seed)
    print(f"warm start selected at step {sel['selected_step']}, "
          f"in-range {sel['in_range_at_selection']}")

    dump = [] if a.dump_samples else None
    main_run = run_loop(copy.deepcopy(model), vocab, train, held_in, stoi, itos, V,
                        a.rounds, a.k, a.seed, include_out_of_range=True,
                        lr=a.lr, label="main", dump=dump)
    ctrl_run = run_loop(copy.deepcopy(model), vocab, train, held_in, stoi, itos, V,
                        a.rounds, a.k, a.seed, include_out_of_range=False,
                        lr=a.lr, label="control", dump=dump)
    if a.dump_samples:
        with open(a.dump_samples, "w", encoding="utf-8") as fh:
            for rec in dump:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"-> {a.dump_samples}  ({len(dump)} sampled completions)")

    for run in (main_run, ctrl_run):
        print(f"\n--- {run['label']} ---  stop_reason={run['stop_reason']}  "
              f"first_correct_12={run['first_correct_12']}")
        print(" round  explore  P(10+2)  P(any oor)  in-range  leak")
        for r in run["rounds"]:
            def f(x):
                return "  n/a " if x is None else f"{x:6.4f}"
            print(f" {r['round']:>5}  {f(r['exploration_rate'])}  "
                  f"{f(r['p_correct_10p2'])}  {f(r['p_correct_any_oor'])}  "
                  f"{r['in_range_heldout']:6.4f}  {r['leak_p_ge_11_marks_in_range']:6.4f}")

    Path(a.out).write_text(json.dumps(
        {"seed": a.seed, "k": a.k, "rounds": a.rounds, "temperature": TEMPERATURE,
         "threads": N_THREADS, "mark": vocab["mark"], "lr": a.lr,
         "out_of_range_prompts": [[x, y, x + y] for x, y in OUT_OF_RANGE_D],
         "warm_start": sel, "main": main_run, "control": ctrl_run},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
