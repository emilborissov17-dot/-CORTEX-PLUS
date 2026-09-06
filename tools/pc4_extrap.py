#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC4 — does the model produce a result it has NEVER seen, from a rule it could have
induced?

WHY SYMBOLS AND NOT DIGITS
    Pretraining knows arithmetic. Digits would test recall. Every number and both
    operators are replaced by invented tokens under a fixed seed, so the only route
    to a correct out-of-range answer is a rule induced from the training pairs.

WHY THE VOCABULARY IS 0..15 AND NOT 0..12
    The spec said 0..12, and two of its own out-of-range cases are 9+4=13 and
    10+5=15. In a 0..12 vocabulary those have NO TOKEN: a model with a perfect rule
    could not emit them, so scoring them would measure the vocabulary rather than
    the model. The range is widened to cover the test set; 11..15 still never appear
    as a training target, which is the property that matters.

THE TWO CONTROLS, and neither is optional
    in-range held-out  - below 95% there is no rule, so the out-of-range number
                         means nothing and the run reports UNRESOLVABLE.
    shuffled targets   - same architecture, same inputs, permuted answers. Must be
                         ~0% on held-out. If it is not, the split leaks.

    venv_train\\Scripts\\python.exe tools/pc4_extrap.py --seeds 5
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEED = 20260906
MAXV = 15                      # tokens exist for 0..15
TRAIN_MAX = 10                 # but nothing above 10 is ever a TARGET

OUT_OF_RANGE = [(10, 2), (9, 4), (10, 5), (8, 3), (7, 5), (10, 1), (9, 2), (6, 6)]


def vocabulary(seed: int = SEED) -> dict:
    """value -> invented token, and the two operators. Generated, not hand-picked,
    so nobody can accidentally choose symbols that carry order."""
    rnd = random.Random(seed)
    letters = [f"Q{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    rnd.shuffle(letters)
    num = {v: letters[v] for v in range(MAXV + 1)}
    ops = {"+": letters[MAXV + 1], "-": letters[MAXV + 2]}
    return {"num": num, "ops": ops}


def build_data(vocab: dict):
    """(train, held_in, held_out_of_range) as (prompt_tokens, target_token)."""
    num, ops = vocab["num"], vocab["ops"]
    pairs = []
    for a in range(TRAIN_MAX + 1):
        for b in range(TRAIN_MAX + 1):
            for sym in ("+", "-"):
                r = a + b if sym == "+" else a - b
                if 0 <= r <= TRAIN_MAX:                 # never a target above 10
                    pairs.append((a, sym, b, r))
    rnd = random.Random(SEED)
    rnd.shuffle(pairs)
    held_in = pairs[:30]
    train = pairs[30:]
    oor = [(a, "+", b, a + b) for a, b in OUT_OF_RANGE]

    def enc(rows):
        return [([num[a], ops[s], num[b]], num[r]) for a, s, b, r in rows]

    return enc(train), enc(held_in), enc(oor), train, held_in, oor


def run_seed(seed: int, train, held_in, oor, vocab, shuffle_targets=False,
             epochs=400, device="cpu", weight_decay=0.0, curve_every=0):
    import torch
    import torch.nn as nn

    torch.manual_seed(seed)
    toks = sorted({t for p, y in train + held_in + oor for t in p + [y]})
    stoi = {t: i for i, t in enumerate(toks)}
    V = len(stoi)

    def to_t(rows):
        X = torch.tensor([[stoi[t] for t in p] for p, _ in rows])
        Y = torch.tensor([stoi[y] for _, y in rows])
        return X, Y

    tr = list(train)
    if shuffle_targets:
        ys = [y for _, y in tr]
        rnd = random.Random(seed + 999)
        rnd.shuffle(ys)
        tr = [(p, y) for (p, _), y in zip(tr, ys)]

    Xtr, Ytr = to_t(tr)
    Xin, Yin = to_t(held_in)
    Xoo, Yoo = to_t(oor)

    class Tiny(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(V, 64)
            self.pos = nn.Parameter(torch.zeros(1, 3, 64))
            layer = nn.TransformerEncoderLayer(64, 4, 128, batch_first=True,
                                               dropout=0.0)
            self.enc = nn.TransformerEncoder(layer, 2)
            self.head = nn.Linear(64, V)

        def forward(self, x):
            h = self.enc(self.emb(x) + self.pos)
            return self.head(h.mean(dim=1))

    m = Tiny().to(device)
    n_params = sum(p.numel() for p in m.parameters())
    opt = torch.optim.AdamW(m.parameters(), lr=3e-3, weight_decay=weight_decay)
    lossf = nn.CrossEntropyLoss()

    def _acc(X, Y):
        m.eval()
        with torch.no_grad():
            return (m(X).argmax(1) == Y).float().mean().item()

    # THE CURVE IS THE POINT OF A2. Memorise-then-generalise is only distinguishable
    # from "never generalised" if the intermediate accuracies are on record; an
    # endpoint alone cannot tell a late jump from a flat line.
    curve = []
    for step in range(epochs):
        if curve_every and (step % curve_every == 0):
            curve.append({"step": step, "train": round(_acc(Xtr, Ytr), 4),
                          "in_range": round(_acc(Xin, Yin), 4),
                          "out_of_range": round(_acc(Xoo, Yoo), 4)})
        m.train()
        opt.zero_grad()
        loss = lossf(m(Xtr), Ytr)
        loss.backward()
        opt.step()
    if curve_every:
        curve.append({"step": epochs, "train": round(_acc(Xtr, Ytr), 4),
                      "in_range": round(_acc(Xin, Yin), 4),
                      "out_of_range": round(_acc(Xoo, Yoo), 4)})

    m.eval()
    with torch.no_grad():
        tr_acc = (m(Xtr).argmax(1) == Ytr).float().mean().item()
        in_acc = (m(Xin).argmax(1) == Yin).float().mean().item()
        pred_oo = m(Xoo).argmax(1)
        oo_acc = (pred_oo == Yoo).float().mean().item()

    itos = {i: t for t, i in stoi.items()}
    inv = {v: k for k, v in vocab["num"].items()}
    answers = []
    for (p, y), pr in zip(oor, pred_oo.tolist()):
        got = itos[pr]
        answers.append({"prompt": p, "want": inv.get(y, y),
                        "got": inv.get(got, got)})
    # THE ORDER PROBE (added for Part C, applied back to A2 so the two are
    # comparable). Only values 0..10 are read: tokens for 11..15 exist in the
    # vocabulary because they are out-of-range TARGETS, but they never appear as an
    # INPUT, so their embedding rows never took a gradient and are still at
    # initialisation. Including them would measure the initialiser.
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))               # run as a script, not a package
    from tools.pc4_partc import order_probe          # noqa: E402
    probe = order_probe(m.emb.weight.detach().numpy(), stoi,
                        {v: vocab["num"][v] for v in range(11)})

    return {"seed": seed, "params": n_params, "order_probe": probe,
            "train_acc": round(tr_acc, 4),
            "in_range_acc": round(in_acc, 4), "out_of_range_acc": round(oo_acc, 4),
            "answers": answers, "final_loss": round(float(loss.item()), 5),
            "weight_decay": weight_decay, "steps": epochs, "curve": curve}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--weight-decay", type=float, default=0.0,
                    help="A2 grokking regime uses 1.0; Part A used 0.0")
    ap.add_argument("--curve-every", type=int, default=0,
                    help="log held-out accuracy every N steps (0 = off)")
    ap.add_argument("--out", default="claude/reports/PC4_PARTA.json")
    a = ap.parse_args()

    vocab = vocabulary()
    train, held_in, oor, raw_tr, raw_in, raw_oo = build_data(vocab)
    print(f"vocabulary (value -> token): "
          f"{ {k: v for k, v in list(vocab['num'].items())} }")
    print(f"operators: {vocab['ops']}")
    print(f"train {len(train)}  held-in {len(held_in)}  out-of-range {len(oor)}")
    targets = sorted({r for _, _, _, r in raw_tr})
    print(f"training TARGETS seen: {targets}")
    assert max(targets) <= TRAIN_MAX, "a target above 10 leaked into training"

    kw = dict(epochs=a.epochs, weight_decay=a.weight_decay,
              curve_every=a.curve_every)
    runs = []
    for i in range(a.seeds):
        r = run_seed(SEED + i, train, held_in, oor, vocab, **kw)
        runs.append(r)
        if r["curve"]:
            print(f"  seed {r['seed']} curve (step: train / in-range / out-of-range)")
            for c in r["curve"]:
                print(f"    {str(c['step']).rjust(6)}  {c['train']:.3f}  "
                      f"{c['in_range']:.3f}  {c['out_of_range']:.3f}")
    # the leak check runs at the SAME budget: a control at 400 steps says nothing
    # about a run at 20,000.
    ctrl = run_seed(SEED, train, held_in, oor, vocab, shuffle_targets=True, **kw)

    for r in runs:
        print(f"  seed {r['seed']}  params {r['params']}  train {r['train_acc']:.3f}"
              f"  in-range {r['in_range_acc']:.3f}  out-of-range {r['out_of_range_acc']:.3f}")
    print(f"  SHUFFLED-TARGET control: in-range {ctrl['in_range_acc']:.3f} "
          f"(must be ~0)")

    Path(a.out).write_text(json.dumps(
        {"vocab": {str(k): v for k, v in vocab["num"].items()},
         "ops": vocab["ops"], "runs": runs, "shuffled_control": ctrl,
         "n_train": len(train), "n_held_in": len(held_in), "n_oor": len(oor)},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
