#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC4 Part C - does the REPRESENTATION decide whether extrapolation is possible?

Part A2 settled that a small transformer can be made to generalise in-range (median
0.800 held-out at full memorisation, up from 0.433 without weight decay) and that
this moves out-of-range accuracy by exactly nothing: 0.000 at all 123 logged
checkpoints, every wrong answer clamped at 10, the largest target it had ever seen.

That result is about ONE representation: a number is an atom and the answer is a
single symbol from a fixed set. Under that encoding "12" is a token the model has
never emitted, and no rule can make it emit one. The clamp is not a failure of
reasoning; it is the encoding's ceiling.

Part C changes only the OUTPUT REPRESENTATION, and makes the output a SEQUENCE the
model has to terminate itself:

  C1  TEN-PLUS-REMAINDER  a number <= 10 is one symbol; a number > 10 is the
                          ten-marker then the remainder. 12 = <ten> <2>. Every
                          symbol in that answer has been emitted before - the
                          ten-marker as the answer 10, and 2 as the answer 2. Only
                          their COMPOSITION is new. If the clamp was an encoding
                          ceiling, this is the representation that removes it.

  C2  TALLY               a number is that many marks. 12 is twelve marks. No new
                          symbol at all - only a LENGTH never produced. This is the
                          textbook place transformers fail, and it belongs here as
                          the harder half of the same question.

Both are scored EXACT-MATCH on the whole emitted sequence, decoded greedily until
the model emits END. An answer that is right except for its length is wrong.

    venv_train\\Scripts\\python.exe tools/pc4_partc.py --rep c1 --seeds 3
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np

SEED = 20260906
TRAIN_MAX = 10                 # nothing above 10 is ever a training RESULT
MAX_RESULT = 15                # the out-of-range test tops out at 10+5
OUT_OF_RANGE = [(10, 2), (9, 4), (10, 5), (8, 3), (7, 5), (10, 1), (9, 2), (6, 6)]
N_HELD_IN = 30

PAD, END, EQ = "<pad>", "<end>", "<eq>"


def vocabulary(rep: str, seed: int = SEED) -> dict:
    """value -> symbol, generated rather than chosen.

    A DEVIATION FROM THE BRIEF, and it costs nothing. The brief names the letters
    A..J for 1..9, K for 10, Z for 0. That assignment is alphabetically ordered in
    value order, which is the one property Part A went out of its way to destroy -
    its test_the_symbols_carry_no_order exists because a symbol that reveals its own
    value turns induction into reading. So the letters are shuffled under a fixed
    seed and the ten-marker is drawn from the same pool. Emil's SCHEME is untouched:
    one symbol at or below ten, ten-marker plus remainder above it. The mapping is
    printed by the harness and goes into the report, so it can be checked.
    """
    rnd = random.Random(seed)
    letters = [f"Q{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    rnd.shuffle(letters)
    if rep == "c1":
        # symbols for 0..10 ONLY. 11..15 have no symbol of their own - that is the
        # point; they must be composed.
        num = {v: letters[v] for v in range(TRAIN_MAX + 1)}
        ops = {"+": letters[TRAIN_MAX + 1], "-": letters[TRAIN_MAX + 2]}
        return {"num": num, "ops": ops, "ten": num[TRAIN_MAX], "rep": "c1"}
    # c2: one mark and nothing else on the output side.
    mark = letters[0]
    ops = {"+": letters[1], "-": letters[2]}
    # Inputs still use single symbols. Only the OUTPUT representation is the
    # variable under test, so the input side is held identical to C1 - otherwise a
    # difference in the result could be the longer input rather than the longer
    # answer.
    num = {v: letters[3 + v] for v in range(TRAIN_MAX + 1)}
    return {"num": num, "ops": ops, "mark": mark, "rep": "c2"}


def encode_result(vocab: dict, r: int) -> list:
    """The result as the sequence the model must emit, END excluded."""
    if vocab["rep"] == "c1":
        if r <= TRAIN_MAX:
            return [vocab["num"][r]]
        return [vocab["ten"], vocab["num"][r - TRAIN_MAX]]
    return [vocab["mark"]] * r          # r == 0 emits nothing but END


def build_data(vocab: dict):
    pairs = []
    for a in range(TRAIN_MAX + 1):
        for b in range(TRAIN_MAX + 1):
            for sym in ("+", "-"):
                r = a + b if sym == "+" else a - b
                if 0 <= r <= TRAIN_MAX:
                    pairs.append((a, sym, b, r))
    rnd = random.Random(SEED)
    rnd.shuffle(pairs)
    held_in, train = pairs[:N_HELD_IN], pairs[N_HELD_IN:]
    oor = [(a, "+", b, a + b) for a, b in OUT_OF_RANGE]

    def enc(rows):
        return [([vocab["num"][a], vocab["ops"][s], vocab["num"][b], EQ],
                 encode_result(vocab, r)) for a, s, b, r in rows]

    return enc(train), enc(held_in), enc(oor), train, held_in, oor


# --- the order probe --------------------------------------------------------
def _ranks(a):
    a = np.asarray(a, dtype=float)
    order = np.argsort(a, kind="stable")
    r = np.empty(len(a), dtype=float)
    r[order] = np.arange(len(a), dtype=float)
    return r


def spearman(x, y) -> float:
    rx, ry = _ranks(x), _ranks(y)
    rx, ry = rx - rx.mean(), ry - ry.mean()
    den = float(np.sqrt((rx @ rx) * (ry @ ry)))
    return 0.0 if den == 0 else float((rx @ ry) / den)


def order_probe(emb_weight, stoi: dict, symbols: dict) -> dict:
    """PCA-1 of the learned number embeddings against the values they stand for.

    "Did it learn the line" - whether the model's internal picture of the numbers is
    ordered like the numbers, or an unordered lookup table that happens to answer
    correctly. Only symbols the model actually SEES are included: a row that never
    took a gradient is still at its initialisation and would put noise into the
    correlation.
    """
    vals = sorted(symbols)
    E = np.asarray(emb_weight, dtype=float)
    rows = np.stack([E[stoi[symbols[v]]] for v in vals])
    X = rows - rows.mean(axis=0, keepdims=True)
    _, _, Vt = np.linalg.svd(X, full_matrices=False)
    pc1 = X @ Vt[0]
    rho = spearman(pc1, vals)
    return {"spearman": round(rho, 4), "abs_spearman": round(abs(rho), 4),
            "n_values": len(vals),
            "pc1_by_value": {str(v): round(float(p), 4) for v, p in zip(vals, pc1)}}


# --- the model --------------------------------------------------------------
def run_seed(seed: int, train, held_in, oor, vocab, raw_oor, shuffle_targets=False,
             steps=20000, weight_decay=1.0, curve_every=500, lr=3e-3):
    import torch
    import torch.nn as nn

    torch.manual_seed(seed)
    seen = sorted({t for p, y in train + held_in + oor for t in p + y})
    toks = [PAD, END, EQ] + [t for t in seen if t not in (PAD, END, EQ)]
    stoi = {t: i for i, t in enumerate(toks)}
    V = len(stoi)
    maxlen = 4 + MAX_RESULT + 2

    def rows_to_tensors(rows):
        """[prompt, answer, END] with the label mask over answer and END only.
        Predicting the question back is not the task."""
        seqs, labs = [], []
        for p, y in rows:
            full = p + y + [END]
            seqs.append([stoi[t] for t in full])
            labs.append([-100] * len(p) + [stoi[t] for t in y + [END]])
        n = max(len(s) for s in seqs)
        X = torch.tensor([s + [stoi[PAD]] * (n - len(s)) for s in seqs])
        Y = torch.tensor([lb + [-100] * (n - len(lb)) for lb in labs])
        return X, Y

    tr = list(train)
    if shuffle_targets:
        ys = [y for _, y in tr]
        random.Random(seed + 999).shuffle(ys)
        tr = [(p, y) for (p, _), y in zip(tr, ys)]

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
            h = self.enc(self.emb(x) + self.pos[:, :T], mask=mask)
            return self.head(h)

    m = TinyLM()
    n_params = sum(p.numel() for p in m.parameters())
    opt = torch.optim.AdamW(m.parameters(), lr=lr, weight_decay=weight_decay)
    lossf = nn.CrossEntropyLoss(ignore_index=-100)
    Xtr, Ytr = rows_to_tensors(tr)

    @torch.no_grad()
    def decode(rows):
        """Greedy, until END, then compare the WHOLE sequence."""
        m.eval()
        want = [y for _, y in rows]
        cur = torch.tensor([[stoi[t] for t in p] for p, _ in rows])
        B = cur.size(0)
        done = torch.zeros(B, dtype=torch.bool)
        got = [[] for _ in range(B)]
        for _ in range(MAX_RESULT + 2):
            nxt = m(cur)[:, -1].argmax(-1)
            nxt = torch.where(done, torch.full_like(nxt, stoi[PAD]), nxt)
            for i in range(B):
                if not bool(done[i]) and int(nxt[i]) != stoi[END]:
                    got[i].append(toks[int(nxt[i])])
            done = done | (nxt == stoi[END])
            cur = torch.cat([cur, nxt.unsqueeze(1)], dim=1)
            if bool(done.all()):
                break
        acc = float(np.mean([g == w for g, w in zip(got, want)]))
        return acc, got

    curve = []
    for step in range(steps):
        if curve_every and step % curve_every == 0:
            curve.append({"step": step, "train": round(decode(tr)[0], 4),
                          "in_range": round(decode(held_in)[0], 4),
                          "out_of_range": round(decode(oor)[0], 4)})
        m.train()
        opt.zero_grad()
        logits = m(Xtr)[:, :-1]
        loss = lossf(logits.reshape(-1, V), Ytr[:, 1:].reshape(-1))
        loss.backward()
        opt.step()

    tr_acc, _ = decode(tr)
    in_acc, _ = decode(held_in)
    oo_acc, oo_got = decode(oor)
    curve.append({"step": steps, "train": round(tr_acc, 4),
                  "in_range": round(in_acc, 4), "out_of_range": round(oo_acc, 4)})

    probe = (order_probe(m.emb.weight.detach().numpy(), stoi, vocab["num"])
             if vocab["rep"] == "c1" else None)

    answers = [{"prompt": f"{a}{s}{b}", "want": r,
                "want_seq": " ".join(encode_result(vocab, r)),
                "got_seq": " ".join(g) if g else "(empty)",
                "got_len": len(g)}
               for (a, s, b, r), g in zip(raw_oor, oo_got)]

    return {"seed": seed, "params": n_params, "vocab_size": V,
            "train_acc": round(tr_acc, 4), "in_range_acc": round(in_acc, 4),
            "out_of_range_acc": round(oo_acc, 4), "curve": curve,
            "order_probe": probe, "answers": answers,
            "final_loss": round(float(loss.item()), 5)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rep", choices=["c1", "c2"], required=True)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--steps", type=int, default=20000)
    ap.add_argument("--weight-decay", type=float, default=1.0)
    ap.add_argument("--curve-every", type=int, default=500)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = a.out or f"claude/reports/PC4_PART{a.rep.upper()}.json"

    vocab = vocabulary(a.rep)
    train, held_in, oor, raw_tr, raw_in, raw_oo = build_data(vocab)
    print(f"representation: {a.rep}")
    print(f"input symbols: {vocab['num']}")
    print(f"operators: {vocab['ops']}")
    key = "ten" if a.rep == "c1" else "mark"
    print(f"{key}: {vocab[key]}   12 -> {' '.join(encode_result(vocab, 12))}")
    print(f"train {len(train)}  held-in {len(held_in)}  out-of-range {len(oor)}")
    targets = sorted({r for _, _, _, r in raw_tr})
    print(f"training RESULTS seen: {targets}")
    assert max(targets) <= TRAIN_MAX, "a result above 10 leaked into training"
    lens = sorted({len(y) for _, y in train})
    print(f"training ANSWER LENGTHS seen: {lens}")
    print(f"out-of-range answer lengths: {sorted({len(y) for _, y in oor})}")

    runs = []
    for i in range(a.seeds):
        r = run_seed(SEED + i, train, held_in, oor, vocab, raw_oo, steps=a.steps,
                     weight_decay=a.weight_decay, curve_every=a.curve_every)
        runs.append(r)
        tail = (f"  |rho| {r['order_probe']['abs_spearman']:.3f}"
                if r["order_probe"] else "")
        print(f"  seed {r['seed']}  params {r['params']}  train {r['train_acc']:.3f}"
              f"  in-range {r['in_range_acc']:.3f}"
              f"  out-of-range {r['out_of_range_acc']:.3f}{tail}", flush=True)
    ctrl = run_seed(SEED, train, held_in, oor, vocab, raw_oo, shuffle_targets=True,
                    steps=a.steps, weight_decay=a.weight_decay,
                    curve_every=a.curve_every)
    print(f"  SHUFFLED-TARGET control: in-range {ctrl['in_range_acc']:.3f} (must be ~0)")

    Path(out).write_text(json.dumps(
        {"rep": a.rep, "symbols": {str(k): v for k, v in vocab["num"].items()},
         "ops": vocab["ops"], "ten_or_mark": vocab[key], "runs": runs,
         "shuffled_control": ctrl, "n_train": len(train),
         "answer_lengths_trained": lens, "steps": a.steps,
         "weight_decay": a.weight_decay},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
