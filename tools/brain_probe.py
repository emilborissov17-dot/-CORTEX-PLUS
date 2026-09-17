#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/brain_probe.py — LOOK INSIDE THE LOCAL MODEL. (17 September 2026.)

Interpretations pre-committed at 1218a94 in claude/reports/BRAIN_PROBE_2026-09-17.md,
before this file existed. Nothing here may reinterpret them.

THIS IS THE 3B MODEL, NOT THE qwen3:8b THAT RAN T1. Base weights, no adapter.
A PROBE SHOWS WHAT IS READABLE, NOT WHAT IS USED.

WHY. T1 showed retrieved memory did not help and pushed the model toward "UP" — 49 UP
answers against 37 true, 38 without memory. We have open weights and have never looked
inside. Three questions:

  A  is the generative law visible inside?      probe the last prompt token -> primitive
  B  does it know when it says the wrong thing?  probe -> direction, beside what it SAYS
  C  what do memories do inside?                 flip the labels, watch both

HARD RULES, and why each is here
  * NEVER prepare_model_for_kbit_training(). It exists to make a quantised model
    trainable and it mutates the model: casts norms to fp32, enables grad checkpointing,
    turns on input-require-grads. We are reading a FROZEN model. Any of that changes the
    thing being measured.
  * NO bf16. This GPU is capability 7.5 and torch.cuda.is_bf16_supported() LIES on it —
    it returns True and there are no bf16 tensor cores. Gate on capability >= 8.0.
  * Embeddings cast to fp16 explicitly.

CONTROLS ARE NOT OPTIONAL. 2048 dimensions against 600 training rows can memorise
anything. Every probe is trained twice — real labels and labels SHUFFLED within the
train set — and only `selectivity = real - control` is a result. A probe that scores on
shuffled labels is reading the data's shape and its real number is inflated by exactly
that much.

THE RAW-INPUT BASELINE is the other half. If the same probe does as well on the eight
numbers as on the hidden state, the information is in the arithmetic and not in the
model, and the report must say "decodable is not the same as used" rather than claim a
representation.

RESUMABLE, because this runs detached and the harness has killed long jobs before. One
fsync'd row per task to memory/brain_probe/rows.jsonl; a restart skips what is on disk.

  venv_train\\Scripts\\python.exe tools/brain_probe.py --selftest
  venv_train\\Scripts\\python.exe tools/brain_probe.py --run
  venv_train\\Scripts\\python.exe tools/brain_probe.py --run --a 120 --c 40   # short
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import random
import sys
import time
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

METHOD_VERSION = "brain_probe/1"
MODEL_DIR = BASE / "models" / "Qwen2.5-3B-Instruct"
OUT_DIR = BASE / "memory" / "brain_probe"
ROWS = OUT_DIR / "rows.jsonl"
# VECTORS GO TO A FLAT BINARY FILE, NOT INTO THE JSONL.
# Measured on the smoke run: 28 rows of 37x2048 floats as JSON text came to 25.7 MB
# -- about 0.9 MB a row, which puts the full run near 1.4 GB of text that must be
# re-parsed on every resume. As float16 in a flat file a row is 37*2048*2 = 151,552
# bytes, the whole run is ~230 MB, and a resume memory-maps it instead of parsing it.
# The jsonl keeps the metadata and an offset, so it stays readable on its own.
VECS = OUT_DIR / 'vecs.f16'
N_LAYERS_EXPECTED = 37
VEC_DIM = 2048
REPORT_JSON = BASE / "claude" / "reports" / "BRAIN_PROBE_2026-09-17.json"

PROBE_SEED = 20260918            # NEVER the T1 master seed
N_A = 900                        # 150 per primitive
N_TRAIN = 600
N_C = 200
MAX_NEW = 24


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── tasks ────────────────────────────────────────────────────────────────────

def build_tasks(n_a: int = N_A):
    """n_a single-primitive tasks, balanced across the six primitives."""
    import transfer_tasks as TT
    per = n_a // len(TT.PRIMITIVES)
    out = []
    for pi, p in enumerate(TT.PRIMITIVES):
        for k in range(per):
            t = TT.make_task(pi * 10_000 + k, "probe", (p,), master=PROBE_SEED)
            t["primitive"] = p
            t["primitive_idx"] = pi
            out.append(t)
    return out


def raw_features(task) -> list:
    """The 8 values and their 7 differences — the raw-input baseline's input."""
    s = task["series"]
    return [float(v) for v in s] + [float(b - a) for a, b in zip(s, s[1:])]


# ── prompt: the exact T1 skeleton ────────────────────────────────────────────

def memory_block(kind: str, task, episodes, n_lines: int = 3) -> str:
    """filler | true | all_up | all_down. Equal length by construction.

    THE SERIES IN THE EPISODES IS IDENTICAL ACROSS true/all_up/all_down. Only the
    stated outcome changes. That is what makes C a test of label-copying rather than
    a test of which episodes were retrieved.
    """
    import transfer_test as TT_T
    if kind == "filler":
        probe_line = "- past case: " + ", ".join(str(v) for v in episodes[0]["series"]) \
            + " -> next step was UP"
        return TT_T.filler_block(n_lines, len(probe_line))
    lines = []
    for e in episodes[:n_lines]:
        up = (e["answer_up"] if kind == "true"
              else True if kind == "all_up" else False)
        lines.append(f"- past case: {', '.join(str(v) for v in e['series'])} "
                     f"-> next step was {'UP' if up else 'DOWN'}")
    return "\n".join(lines)


def build_prompt(task, block: str) -> str:
    import transfer_test as TT_T
    return TT_T.build_prompt(task, block)


# ── torch logistic probe (no scikit-learn in venv_train) ─────────────────────

# REGULARISATION IS CHOSEN, NOT ASSUMED. Measured 17 Sep on a synthetic separable
# signal (one informative dimension among 63 noise ones, 200 train rows): at
# weight_decay=1e-3 the probe reached TRAIN 1.0 and TEST 0.23 — it memorised the noise.
# With 2048 dimensions against 600 rows that failure is certain, and it would not show
# up as a wrong answer but as a uselessly flat result: both the real probe and the
# shuffled control land at chance and every selectivity reads ~0. The sweep below picks
# the strength on a validation split carved out of TRAIN, never on test, and the SAME
# sweep runs for the shuffled control so the two remain comparable.
LAM_GRID = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)


def fit_logistic(X, y, n_classes: int, lam: float = 1.0, seed: int = PROBE_SEED,
                 max_iter: int = 200):
    """Multinomial logistic regression, L2-penalised, solved with L-BFGS on CPU.

    Deliberately plain: a probe is meant to be a LINEAR readout. Anything with more
    capacity answers a different question — "can something be computed from this"
    rather than "is this linearly present".

    WHY L-BFGS AND NOT ADAM, measured rather than preferred. On a synthetic separable
    signal (one informative dimension among 63 noise ones, 200 train rows):
        Adam, wd 1e-3    TRAIN 1.0   TEST 0.23    memorised the noise
        AdamW, wd >= 1.0 TRAIN low   TEST 0.15    decay crushed the signal
    Logistic regression is convex; a first-order optimiser run for a few hundred
    full-batch steps either underfits or overfits depending on a learning rate nobody
    measured. L-BFGS converges on the actual optimum, so the L2 strength — which IS
    swept, on validation — becomes the only knob that matters.

    The penalty is written into the loss rather than passed as weight_decay so the grid
    means the same thing at every point: AdamW's decoupled decay interacts with the
    adaptive step and the grid barely moves the solution.
    """
    import torch
    torch.manual_seed(seed)
    X = torch.as_tensor(X, dtype=torch.float32)
    y = torch.as_tensor(y, dtype=torch.long)
    mu, sd = X.mean(0, keepdim=True), X.std(0, keepdim=True).clamp_min(1e-6)
    Xs = (X - mu) / sd
    n = Xs.shape[0]
    W = torch.zeros(Xs.shape[1], n_classes, requires_grad=True)
    b = torch.zeros(n_classes, requires_grad=True)
    opt = torch.optim.LBFGS([W, b], max_iter=max_iter, history_size=20,
                            line_search_fn="strong_wolfe")
    lossf = torch.nn.CrossEntropyLoss()

    def closure():
        opt.zero_grad()
        loss = lossf(Xs @ W + b, y) + lam * W.pow(2).sum() / (2 * n)
        loss.backward()
        return loss

    opt.step(closure)
    return {"W": W.detach(), "b": b.detach(), "mu": mu, "sd": sd, "lam": lam}


def predict(model, X):
    import torch
    X = torch.as_tensor(X, dtype=torch.float32)
    Xs = (X - model["mu"]) / model["sd"]
    return (Xs @ model["W"] + model["b"]).argmax(1).tolist()


def accuracy(pred, y) -> float:
    return round(sum(int(a == b) for a, b in zip(pred, y)) / max(1, len(y)), 4)


def fit_cv(Xtr, ytr, n_classes: int, seed: int = PROBE_SEED):
    """Fit with the weight decay that generalises best on a held-out slice of TRAIN.

    The validation split never touches the test set: choosing the strength on test
    would be selecting the probe that flatters the hypothesis.
    """
    rng = random.Random(seed)
    idx = list(range(len(Xtr)))
    rng.shuffle(idx)
    cut = max(1, int(0.8 * len(idx)))
    ti, vi = idx[:cut], idx[cut:]
    if not vi:
        return fit_logistic(Xtr, ytr, n_classes, seed=seed), None
    best, best_wd, best_acc = None, None, -1.0
    for wd in LAM_GRID:
        m = fit_logistic([Xtr[i] for i in ti], [ytr[i] for i in ti], n_classes,
                         lam=wd, seed=seed)
        a = accuracy(predict(m, [Xtr[i] for i in vi]), [ytr[i] for i in vi])
        if a > best_acc:
            best, best_wd, best_acc = m, wd, a
    # refit on ALL of train at the chosen strength
    return fit_logistic(Xtr, ytr, n_classes, lam=best_wd, seed=seed), best_wd


def probe_with_control(Xtr, ytr, Xte, yte, n_classes: int, seed: int = PROBE_SEED):
    """Real probe AND a shuffled-label control. Only selectivity is a result."""
    m, wd = fit_cv(Xtr, ytr, n_classes, seed=seed)
    real = accuracy(predict(m, Xte), yte)
    rng = random.Random(seed)
    ysh = list(ytr)
    rng.shuffle(ysh)
    mc, wdc = fit_cv(Xtr, ysh, n_classes, seed=seed)
    ctrl = accuracy(predict(mc, Xte), yte)
    return {"real": real, "control": ctrl, "selectivity": round(real - ctrl, 4),
            "chance": round(1.0 / n_classes, 4), "wd": wd, "wd_control": wdc}


# ── model ────────────────────────────────────────────────────────────────────

def load_model():
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    cap = torch.cuda.get_device_capability(0)
    if cap[0] >= 8:
        raise RuntimeError(f"capability {cap} >= 8.0 — revisit the bf16 gate before running")
    dtype = torch.float16          # NEVER bf16 here; is_bf16_supported() lies on 7.5
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=dtype,
                             bnb_4bit_use_double_quant=True)
    tok = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_DIR), quantization_config=bnb, device_map={"": 0}, dtype=dtype)
    # NO prepare_model_for_kbit_training() — this model is frozen and being READ.
    model.get_input_embeddings().to(dtype)
    model.eval()
    return tok, model


def last_token_states(tok, model, prompt: str):
    """-> (list of per-layer vectors at the LAST prompt token, input length)."""
    import torch
    text = tok.apply_chat_template([{"role": "user", "content": prompt}],
                                   tokenize=False, add_generation_prompt=True)
    ids = tok(text, return_tensors="pt").to(0)
    with torch.no_grad():
        out = model(**ids, output_hidden_states=True)
    vecs = [h[0, -1, :].float().cpu().tolist() for h in out.hidden_states]
    return vecs, int(ids["input_ids"].shape[1])


def speak(tok, model, prompt: str) -> dict:
    """Greedy answer, parsed by T1's rules. A refusal is a refusal."""
    import torch
    import transfer_test as TT_T
    text = tok.apply_chat_template([{"role": "user", "content": prompt}],
                                   tokenize=False, add_generation_prompt=True)
    ids = tok(text, return_tensors="pt").to(0)
    with torch.no_grad():
        g = model.generate(**ids, max_new_tokens=MAX_NEW, do_sample=False,
                           pad_token_id=tok.eos_token_id)
    txt = tok.decode(g[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
    p = TT_T.parse_reply(txt)
    return {"text": txt[:200], **p}


# ── the run ──────────────────────────────────────────────────────────────────

def _append(row, vecs=None):
    """One fsync'd row; vectors to the binary store.

    ORDER MATTERS. The vectors are written and fsync'd FIRST, then the row that points
    at them. A crash between the two leaves an orphan block in vecs.f16, which is
    harmless. The reverse would leave a row pointing at bytes that do not exist.
    """
    import numpy as np
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if vecs is not None:
        arr = np.asarray(vecs, dtype=np.float16)
        if arr.shape != (N_LAYERS_EXPECTED, VEC_DIM):
            raise RuntimeError("expected %s vectors, got %s - refusing a ragged store"
                               % ((N_LAYERS_EXPECTED, VEC_DIM), arr.shape))
        with open(VECS, "ab") as vf:
            row["vec_offset"] = vf.tell() // (arr.size * 2)
            vf.write(arr.tobytes()); vf.flush(); os.fsync(vf.fileno())
    with open(ROWS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + chr(10))
        fh.flush(); os.fsync(fh.fileno())


def _read_vecs(offset):
    """One row's 37x2048 block, memory-mapped."""
    import numpy as np
    n = N_LAYERS_EXPECTED * VEC_DIM
    mm = np.memmap(VECS, dtype=np.float16, mode="r")
    return np.asarray(mm[offset*n:(offset+1)*n]).reshape(
        N_LAYERS_EXPECTED, VEC_DIM).astype("float32")


def _done_keys() -> set:
    if not ROWS.exists():
        return set()
    out = set()
    for line in ROWS.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            out.add((d.get("stage"), d.get("key")))
        except Exception:                                        # noqa: BLE001
            continue
    return out


def run(n_a: int = N_A, n_c: int = N_C) -> dict:
    import transfer_tasks as TT
    tasks = build_tasks(n_a)
    tok, model = load_model()
    done = _done_keys()
    print(f"[probe] {len(tasks)} tasks, {len(done)} rows already on disk", flush=True)

    # ---- capture hidden states (A and B share them) ----
    t0 = time.time()
    for i, t in enumerate(tasks):
        key = t["task_id"] + "|" + t["primitive"]
        if ("state", key) in done:
            continue
        block = memory_block("filler", t, tasks)
        vecs, n_tok = last_token_states(tok, model, build_prompt(t, block))
        _append({"stage": "state", "key": key, "task_id": t["task_id"],
                 "primitive": t["primitive"], "primitive_idx": t["primitive_idx"],
                 "answer_up": t["answer_up"], "series": t["series"],
                 "n_tokens": n_tok, "ts": _now()}, vecs=vecs)
        if (i + 1) % 50 == 0:
            el = time.time() - t0
            print(f"  [state {i+1}/{len(tasks)}] {el:.0f}s "
                  f"({el/(i+1):.2f}s/task)", flush=True)

    # ---- spoken answers on the B/C subset ----
    sub = tasks[:n_c] if n_c <= len(tasks) else tasks
    for cond in ("filler", "true", "all_up", "all_down"):
        for j, t in enumerate(sub):
            key = f"{cond}|{t['task_id']}"
            if ("spoken", key) in done:
                continue
            eps = [e for e in tasks if e["primitive"] == t["primitive"]
                   and e["task_id"] != t["task_id"]][:3]
            block = memory_block(cond, t, eps)
            said = speak(tok, model, build_prompt(t, block))
            row = {"stage": "spoken", "key": key, "cond": cond,
                   "task_id": t["task_id"], "primitive": t["primitive"],
                   "answer_up": t["answer_up"], "parsed": said["parsed"],
                   "direction": said.get("direction"), "p": said.get("p"),
                   "why": said.get("why", ""), "ts": _now()}
            vv = None
            if cond != "filler":
                vv, _ = last_token_states(tok, model, build_prompt(t, block))
            _append(row, vecs=vv)
            if (j + 1) % 25 == 0:
                print(f"  [spoken {cond} {j+1}/{len(sub)}]", flush=True)
    return analyse()


# ── analysis ─────────────────────────────────────────────────────────────────

def analyse() -> dict:
    import transfer_tasks as TT
    rows = [json.loads(l) for l in ROWS.read_text(encoding="utf-8").splitlines() if l.strip()]
    states = [r for r in rows if r["stage"] == "state"]
    spoken = [r for r in rows if r["stage"] == "spoken"]
    if not states:
        return {"error": "no state rows"}

    n_layers = N_LAYERS_EXPECTED
    SV = [_read_vecs(r["vec_offset"]) for r in states]
    rng = random.Random(PROBE_SEED)
    idx = list(range(len(states)))
    rng.shuffle(idx)
    # PROPORTIONAL, not a hard 600. A partial or resumed run has fewer states, and a
    # fixed N_TRAIN left the test set EMPTY -- the smoke run died on exactly that.
    n_train = min(N_TRAIN, max(1, int(round(2 / 3 * len(states)))))
    tr, te = idx[:n_train], idx[n_train:]
    if not te:
        return {"error": "only %d states - no test split possible" % len(states)}

    out = {"ts": _now(), "method_version": METHOD_VERSION,
           "model": "models/Qwen2.5-3B-Instruct (4-bit NF4, fp16 compute)",
           "probe_seed": PROBE_SEED, "n_states": len(states), "n_layers": n_layers,
           "n_train": len(tr), "n_test": len(te)}

    # A: primitive, per layer
    yA = [states[i]["primitive_idx"] for i in range(len(states))]
    A = []
    for L in range(n_layers):
        X = [SV[i][L] for i in range(len(states))]
        A.append({"layer": L, **probe_with_control([X[i] for i in tr], [yA[i] for i in tr],
                                                   [X[i] for i in te], [yA[i] for i in te], 6)})
        print(f"  [A layer {L}] real={A[-1]['real']} ctrl={A[-1]['control']} "
              f"sel={A[-1]['selectivity']}", flush=True)
    out["A_primitive_by_layer"] = A
    best = max(A, key=lambda r: r["selectivity"])
    out["A_best_layer"] = best

    # B: direction, per layer + raw baseline
    yB = [1 if states[i]["answer_up"] else 0 for i in range(len(states))]
    B = []
    for L in range(n_layers):
        X = [SV[i][L] for i in range(len(states))]
        B.append({"layer": L, **probe_with_control([X[i] for i in tr], [yB[i] for i in tr],
                                                   [X[i] for i in te], [yB[i] for i in te], 2)})
    out["B_direction_by_layer"] = B
    bestB = max(B, key=lambda r: r["selectivity"])
    out["B_best_layer"] = bestB

    Xraw = [raw_features(s) for s in states]
    out["B_raw_input_baseline"] = probe_with_control(
        [Xraw[i] for i in tr], [yB[i] for i in tr],
        [Xraw[i] for i in te], [yB[i] for i in te], 2)

    # spoken, filler condition
    fil = [r for r in spoken if r["cond"] == "filler"]
    if fil:
        parsed = [r for r in fil if r["parsed"]]
        out["B_spoken"] = {
            "n": len(fil), "refusals": len(fil) - len(parsed),
            "accuracy": round(sum(1 for r in parsed
                                  if (r["direction"] == "UP") == r["answer_up"])
                              / max(1, len(parsed)), 4),
            "up_rate": round(sum(1 for r in parsed if r["direction"] == "UP")
                             / max(1, len(parsed)), 4),
            "true_up_rate": round(sum(1 for r in fil if r["answer_up"]) / len(fil), 4)}

        # on the tasks it got WRONG, is the probe right?
        L = bestB["layer"]
        Xall = {states[i]["task_id"]: SV[i][L] for i in range(len(states))}
        yall = {states[i]["task_id"]: yB[i] for i in range(len(states))}
        pm = fit_logistic([SV[i][L] for i in tr], [yB[i] for i in tr], 2)
        wrong = [r for r in parsed if (r["direction"] == "UP") != r["answer_up"]
                 and r["task_id"] in Xall]
        if wrong:
            pr = predict(pm, [Xall[r["task_id"]] for r in wrong])
            out["B_probe_on_spoken_errors"] = {
                "n_wrong": len(wrong), "layer": L,
                "probe_correct": round(sum(int(p == yall[r["task_id"]])
                                           for p, r in zip(pr, wrong)) / len(wrong), 4),
                "chance": 0.5}

    # C: the four conditions
    C = {}
    L = bestB["layer"]
    pm = fit_logistic([SV[i][L] for i in tr], [yB[i] for i in tr], 2)
    for cond in ("filler", "true", "all_up", "all_down"):
        rs = [r for r in spoken if r["cond"] == cond]
        if not rs:
            continue
        ps = [r for r in rs if r["parsed"]]
        entry = {"n": len(rs), "refusals": len(rs) - len(ps),
                 "spoken_up_rate": round(sum(1 for r in ps if r["direction"] == "UP")
                                         / max(1, len(ps)), 4),
                 "spoken_accuracy": round(sum(1 for r in ps
                                              if (r["direction"] == "UP") == r["answer_up"])
                                          / max(1, len(ps)), 4)}
        withv = [r for r in rs if r.get("vec_offset") is not None]
        if withv:
            pr = predict(pm, [_read_vecs(r["vec_offset"])[L] for r in withv])
            entry["probe_up_rate"] = round(sum(pr) / len(pr), 4)
            entry["probe_accuracy"] = round(
                sum(int(p == (1 if r["answer_up"] else 0))
                    for p, r in zip(pr, withv)) / len(withv), 4)
            entry["probe_n"] = len(withv)
        C[cond] = entry
    out["C_conditions"] = C
    out["C_probe_layer"] = L
    return out


# ── selftest ─────────────────────────────────────────────────────────────────

def _selftest() -> int:
    print("tools/brain_probe.py --selftest")
    fails = []

    def check(name, cond):
        print(f"  {'OK  ' if cond else 'FAIL'}   {name}")
        if not cond:
            fails.append(name)

    import transfer_tasks as TT
    t = build_tasks(60)
    check("tasks are balanced across the six primitives",
          len({x["primitive"] for x in t}) == 6
          and all(sum(1 for x in t if x["primitive"] == p) == 10 for p in TT.PRIMITIVES))
    check("the probe seed is NOT the T1 master seed", PROBE_SEED != TT.MASTER_SEED)
    check("probe tasks differ from T1's for the same index",
          t[0]["series"] != TT.make_task(0, "probe", (t[0]["primitive"],))["series"])

    # THE MUTATION: random vectors must land at chance.
    rng = random.Random(7)
    n, d = 300, 64
    Xr = [[rng.gauss(0, 1) for _ in range(d)] for _ in range(n)]
    yr = [rng.randrange(6) for _ in range(n)]
    got = probe_with_control(Xr[:200], yr[:200], Xr[200:], yr[200:], 6)
    check(f"MUTATION: a probe fed RANDOM vectors scores at chance "
          f"(real {got['real']}, chance {got['chance']})",
          abs(got["real"] - got["chance"]) < 0.12)
    check(f"...and its selectivity is ~0 ({got['selectivity']})",
          abs(got["selectivity"]) < 0.12)

    # A LEARNABLE signal must be found, or the probe is simply broken.
    #
    # THE SIGNAL IS DENSE, and the first version of this check was not — which made it
    # the wrong instrument test. It put one informative dimension among 63 noise ones
    # and demanded the probe recover it; measured, that scored 0.29 while the same
    # feature ALONE scored 1.0. That is not a bug: ridge logistic regression spreads
    # weight and does not do sparse recovery, and ||W[0]|| came out about equal to
    # ||W[1:]|| — per dimension the signal dominated, and 63 noise dimensions outvoted
    # it collectively. A hidden state is a DISTRIBUTED representation, so the regime
    # that matters is a signal spread across dimensions, which is what this now builds.
    cent = [[rng.gauss(0, 1) for _ in range(d)] for _ in range(6)]
    Xs, ys = [], []
    for i in range(n):
        c = i % 6
        Xs.append([cent[c][j] * 1.2 + rng.gauss(0, 1) for j in range(d)])
        ys.append(c)
    good = probe_with_control(Xs[:200], ys[:200], Xs[200:], ys[200:], 6)
    check(f"a probe on a SEPARABLE signal scores well above chance ({good['real']})",
          good["real"] > 0.8)
    check(f"...and its shuffled control stays at chance ({good['control']})",
          good["control"] < 0.4)
    check("selectivity separates the two cases",
          good["selectivity"] > 0.5 > abs(got["selectivity"]))

    # memory blocks: same series, different labels, equal length
    eps = t[:3]
    tr_b = memory_block("true", t[5], eps)
    up_b = memory_block("all_up", t[5], eps)
    dn_b = memory_block("all_down", t[5], eps)
    fl_b = memory_block("filler", t[5], eps)
    ser = lambda b: [l.split("->")[0] for l in b.split("\n")]          # noqa: E731
    check("all_up and all_down carry the IDENTICAL series", ser(up_b) == ser(dn_b))
    check("...and the identical series as the true-label block", ser(tr_b) == ser(up_b))
    check("all_up is all UP", up_b.count("UP") == 3 and "DOWN" not in up_b)
    check("all_down is all DOWN", dn_b.count("DOWN") == 3 and "UP" not in dn_b)
    check("the four blocks have the same number of lines",
          len({len(b.split(chr(10))) for b in (tr_b, up_b, dn_b, fl_b)}) == 1)
    check("filler carries no past case", "past case" not in fl_b)

    check("raw features are 8 values + 7 differences", len(raw_features(t[0])) == 15)

    import transfer_test as TT_T
    check("the prompt skeleton is T1's, not a new one",
          build_prompt(t[0], "X") == TT_T.build_prompt(t[0], "X"))
    check("a refusal is a refusal — T1's parser is reused",
          not TT_T.parse_reply("I think up")["parsed"])

    # STRUCTURAL, NOT A GREP. The first version searched the file for the string and
    # failed on its own docstring, which names the function in order to forbid it.
    # A test that cannot tell a prohibition from a violation is not a test.
    import ast
    tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    banned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name == "prepare_model_for_kbit_training":
                banned.add(name)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                if al.name == "prepare_model_for_kbit_training":
                    banned.add(al.name)
    check("prepare_model_for_kbit_training is never CALLED or IMPORTED "
          "(checked on the AST, not on the text)", not banned)

    print("")
    if fails:
        print(str(len(fails)) + " FAILED: " + str(fails))
    else:
        print("ALL 18 checks passed")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--analyse", action="store_true")
    ap.add_argument("--a", type=int, default=N_A)
    ap.add_argument("--c", type=int, default=N_C)
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.analyse:
        res = analyse()
    elif a.run:
        res = run(n_a=a.a, n_c=a.c)
    else:
        ap.error("--run, --analyse or --selftest")
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items()
                      if k not in ("A_primitive_by_layer", "B_direction_by_layer")},
                     ensure_ascii=False, indent=2))
    print(f"-> {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
