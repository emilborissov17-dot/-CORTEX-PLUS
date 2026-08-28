#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/brain_scan.py — dump the interval head's learned weights, and nothing else.

    venv/Scripts/python.exe tools/brain_scan.py --dump

Writes out/brain_scan.json. READ-ONLY with respect to everything except out/:
it opens memory/interval_head_weights.npz, memory/interval_head_curve.json and
memory/training_log.jsonl for reading and writes one file, in out/.

WHAT IT IS FOR
--------------
core/interval_head.py has trained five times and kept the CURVE and the RUNS,
which say how well it did, and never the WEIGHTS, which say what it learned. A
loss number tells you the head beat a flat baseline; it does not tell you which
input dimension it leaned on, whether a unit is dead, or what moved between two
runs. This dumps the second thing so a human can look at it.

NOTHING IS EVER SYNTHESISED. Not a weight, not an activation, not an interval.
Where a value cannot be read it is null and the reason is stated. If the weights
file does not exist the output is exactly {"meta": {"weights_persisted": false}}
and the run stops — the renderer handles that case and says so plainly, which is
better than a page of plausible zeros.

The key names below are fixed by out/brain_map.html, which reads them. They are
not negotiable from this side.
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys
from datetime import datetime, timezone

import numpy as np

BASE = pathlib.Path(__file__).resolve().parents[1]
WEIGHTS = BASE / "memory" / "interval_head_weights.npz"
WEIGHTS_PREV = BASE / "memory" / "interval_head_weights_prev.npz"
CURVE = BASE / "memory" / "interval_head_curve.json"
OUT_DIR = BASE / "out"
OUT = OUT_DIR / "brain_scan.json"

TOP_DIMS = 10
DEAD_EPS = 1e-6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(p: pathlib.Path) -> str:
    """Repo-relative when it can be, absolute when it cannot. A path outside
    the repo is what a test fixture looks like, and reporting it honestly beats
    raising inside a dumper."""
    try:
        return str(p.relative_to(BASE)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _load_json(p: pathlib.Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _layer_stats(name: str, W: np.ndarray, prev: np.ndarray | None) -> dict:
    """One row of the layers table. dead_fraction is over OUTPUT units: a column
    whose weights are all ~0 cannot influence anything downstream."""
    col_norms = np.linalg.norm(W, axis=0) if W.ndim == 2 else np.abs(W)
    dead = float(np.mean(col_norms < DEAD_EPS)) if col_norms.size else 0.0
    row = {
        "name": name,
        "shape": list(W.shape),
        "l2": float(np.linalg.norm(W)),
        "mean": float(np.mean(W)),
        "std": float(np.std(W)),
        "dead_fraction": dead,
        "delta_l2_vs_prev": None,
        "delta_mean_vs_prev": None,
    }
    if prev is not None and prev.shape == W.shape:
        row["delta_l2_vs_prev"] = float(np.linalg.norm(W) - np.linalg.norm(prev))
        row["delta_mean_vs_prev"] = float(np.mean(W) - np.mean(prev))
    return row


def _units(W: np.ndarray, b: np.ndarray, layer: str,
           prev_W: np.ndarray | None) -> list:
    """Per-unit view: which input dimensions each hidden unit actually reads."""
    out = []
    n_units = W.shape[1]
    for j in range(n_units):
        col = W[:, j]
        order = np.argsort(-np.abs(col))[:TOP_DIMS]
        prev_l2 = None
        if prev_W is not None and prev_W.shape == W.shape:
            prev_l2 = float(np.linalg.norm(col) - np.linalg.norm(prev_W[:, j]))
        out.append({
            "layer": layer,
            "index": int(j),
            "bias": float(b[j]) if b is not None and j < len(b) else None,
            "incoming_l2": float(np.linalg.norm(col)),
            "incoming_delta_l2": prev_l2,
            "top_dims": [[int(d), float(col[d])] for d in order],
        })
    return out


def _relu(x):
    return np.maximum(x, 0.0)


def _q8(M: np.ndarray) -> dict:
    """int8 + a stated scale. The page prints the scale so a reader can recover
    the real number: value ~= data * scale. Lossy on purpose — 2059x256 floats
    is 4MB of JSON and the renderer needs a picture, not a checkpoint — and the
    loss is DECLARED rather than hidden behind a pretty gradient."""
    M = np.asarray(M, dtype=np.float64)
    peak = float(np.max(np.abs(M))) if M.size else 0.0
    scale = peak / 127.0 if peak > 0 else 1.0
    q = np.clip(np.rint(M / scale), -127, 127).astype(np.int8)
    return {"shape": list(M.shape), "scale": scale,
            "data": base64.b64encode(q.tobytes()).decode("ascii")}


def _cosine_units(W: np.ndarray) -> np.ndarray:
    """Unit-to-unit cosine similarity by INCOMING weight vector (columns of W)."""
    C = np.asarray(W, dtype=np.float64)
    n = np.linalg.norm(C, axis=0)
    n[n < 1e-12] = 1.0
    Cn = C / n
    return np.clip(Cn.T @ Cn, -1.0, 1.0)


def _greedy_chain(S: np.ndarray) -> list:
    """Put alike units adjacent, by walking nearest-neighbour from the strongest
    pair. It REORDERS INDICES AND NOTHING ELSE — no embedding, no projection,
    no force layout. A layout algorithm that moves points would draw structure
    the weights do not have, and this file's whole rule is that nothing is
    invented. A greedy chain is honest: it can be checked by hand."""
    n = S.shape[0]
    if n == 0:
        return []
    M = S.copy()
    np.fill_diagonal(M, -np.inf)
    i, j = np.unravel_index(int(np.argmax(M)), M.shape)
    order = [int(i), int(j)]
    seen = {int(i), int(j)}
    while len(order) < n:
        last = order[-1]
        row = S[last].copy()
        row[list(seen)] = -np.inf
        nxt = int(np.argmax(row))
        order.append(nxt)
        seen.add(nxt)
    return order


def _forward(W1, b1, W2, b2, W3, b3, x):
    """One real forward pass. Returns (hidden1, hidden2, centre, halfwidth)."""
    a1 = _relu(x @ W1 + b1)
    a2 = _relu(a1 @ W2 + b2)
    z3 = a2 @ W3 + b3
    centre, log_hw = float(z3[0]), float(z3[1])
    return a1, a2, centre, float(np.exp(log_hw))


def _real_input_rows(W1, b1, W2, b2, W3, b3, mu, sd) -> list:
    """Two REAL rows, chosen for contrast. Nothing here is invented.

    A healthy cycle and the 2026-08-28T03:00 refusal. Every field is read from
    memory/training_log.jsonl and pushed through the actual weights; where a row
    cannot be found it is simply absent, never replaced by a plausible one.
    """
    if any(v is None for v in (W1, b1, W2, b2, W3, b3, mu, sd)):
        return []
    try:
        sys.path.insert(0, str(BASE))
        from core import interval_head as ih
        data = ih.dataset()
        rows, keys, y = data["rows"], data["keys"], data["y"]
        # The SAME embedding train() builds, by the same recipe (:598-605) —
        # one vector per step NAME, cached by ollama. Rebuilding it any other
        # way would put a different input through the weights and call the
        # result an activation.
        steps = sorted(set(keys))
        E, _src = ih.embed([f"CORTEX cycle step: {s}" for s in steps])
        by_step = {s: E[i] for i, s in enumerate(steps)}
        # If the saved weights are wider than the embedding, this run had row
        # features on and they are hstacked AFTER it — same order as train().
        want = int(np.asarray(mu).shape[0])
        F = None
        if want > E.shape[1]:
            F, _names, _cov = ih.row_features(rows)
    except Exception:
        return []
    if not rows:
        return []

    # Contrast: the longest and the shortest grounded row we have. The refusal
    # is the short one on 2026-08-28; if it is not in the log, the shortest real
    # row stands in and `label` says which row it actually is.
    order = sorted(range(len(rows)), key=lambda i: float(y[i]))
    picks = []
    refusal = [i for i, r in enumerate(rows)
               if str(r.get("ts", "")).startswith("2026-08-28T03")]
    if refusal:
        picks.append(("2026-08-28T03:00 refusal", refusal[0]))
    picks.append(("longest grounded step", order[-1]))
    if not refusal:
        picks.insert(0, ("shortest grounded step", order[0]))

    out = []
    for label, i in picks[:2]:
        r = rows[i]
        vec = by_step.get(keys[i])
        if vec is None:
            continue
        vec = np.asarray(vec, dtype=float)
        if F is not None and i < len(F):
            vec = np.concatenate([vec, np.asarray(F[i], dtype=float)])
        if vec.shape[0] != np.asarray(mu).shape[0]:
            # Still the wrong width: skip the row rather than pad it to fit.
            # A padded input is not this input, and the trace would be fiction.
            continue
        xn = (vec - mu) / sd
        # THE TRACE COMES FROM IntervalHead.forward, not from a second
        # implementation here. Two copies of a forward pass drift, and the one
        # that drifts is always the one nobody runs — which would be this one.
        h = _live_head(W1, b1, W2, b2, W3, b3)
        f = h.forward(xn.reshape(1, -1))
        z1, a1 = f["z1"][0], f["a1"][0]
        z2, a2 = f["z2"][0], f["a2"][0]
        z3 = f["z3"][0]
        centre, hw = float(z3[0]), float(np.exp(np.clip(float(z3[1]), -20, 20)))
        out.append({
            "label": label,
            "source_file": "memory/training_log.jsonl",
            "ts": r.get("ts"),
            "hidden": {"layer1": [float(v) for v in a1],
                       "layer2": [float(v) for v in a2]},
            "trace": {"x": [float(v) for v in xn],
                      "z1": [float(v) for v in z1],
                      "a1": [float(v) for v in a1],
                      "z2": [float(v) for v in z2],
                      "a2": [float(v) for v in a2],
                      "z3": [float(v) for v in z3]},
            "centre": centre,
            "halfwidth": hw,
            "observed": float(np.exp(y[i])),
        })
    return out


def _live_head(W1, b1, W2, b2, W3, b3):
    """An IntervalHead carrying these weights, so forward() is the real one."""
    sys.path.insert(0, str(BASE))
    from core.interval_head import IntervalHead
    h = IntervalHead.__new__(IntervalHead)
    h.W1, h.b1, h.W2, h.b2, h.W3, h.b3 = W1, b1, W2, b2, W3, b3
    return h


def _row_feature_names() -> list:
    try:
        sys.path.insert(0, str(BASE))
        from core.interval_head import ROW_FEATURE_NAMES
        return list(ROW_FEATURE_NAMES)
    except Exception:
        return []


def _sensor_note(W1: np.ndarray, sensor_dims: list) -> str:
    """One measured sentence: do the 11 sensor dims sit together in the
    similarity ordering of INPUT dimensions, or scatter among the language ones?

    Measured, not asserted. If the answer is 'scattered' that is a real finding
    about the head and it gets said, not softened."""
    if not sensor_dims or W1 is None or W1.shape[0] <= max(sensor_dims):
        return ("no row features in this run — W1 has {} input dims and none of "
                "them are sensors".format(0 if W1 is None else W1.shape[0]))
    R = np.asarray(W1, dtype=np.float64)
    n = np.linalg.norm(R, axis=1)
    n[n < 1e-12] = 1.0
    Rn = R / n[:, None]
    order = _greedy_chain(np.clip(Rn @ Rn.T, -1.0, 1.0))
    pos = {d: i for i, d in enumerate(order)}
    spots = sorted(pos[d] for d in sensor_dims if d in pos)
    if len(spots) < 2:
        return "too few sensor dims placed to say anything"
    gaps = [b - a for a, b in zip(spots, spots[1:])]
    median_gap = float(np.median(gaps))
    total = len(order)
    # If they clustered, consecutive sensor dims would sit ~1 apart; scattered,
    # they sit ~total/11 apart, which for 2059 dims is ~187.
    if median_gap <= 3:
        return (f"the {len(spots)} sensor dims CLUSTER: median gap {median_gap:.0f} "
                f"positions apart in a {total}-dim ordering")
    return (f"the {len(spots)} sensor dims SCATTER among the language dims: "
            f"median gap {median_gap:.0f} positions apart in a {total}-dim "
            f"ordering, against ~1 if they grouped")


def matrices() -> dict:
    """W1/W2/W3 as int8 with a stated scale. Fetched ONCE, not on the poll."""
    if not WEIGHTS.exists():
        return {"weights_persisted": False}
    w = np.load(WEIGHTS, allow_pickle=False)
    out = {}
    for k in ("W1", "W2", "W3"):
        if k in w.files:
            out[k] = _q8(w[k])
    return out


def build(head=None, mu=None, sd=None, training=None) -> dict:
    """The contract, from a LIVE head if given, else from the saved weights."""
    def g(store, k):
        try:
            return store[k] if store is not None and k in store.files else None
        except Exception:
            return None

    prev = np.load(WEIGHTS_PREV, allow_pickle=False) if WEIGHTS_PREV.exists() else None

    if head is not None:
        W1, b1, W2, b2 = head.W1, head.b1, head.W2, head.b2
        W3, b3 = head.W3, head.b3
        run_ts, w = None, None
        # Mid-training the "previous run" is the last SAVED file, which is what
        # the page means by SINCE LAST POLL's baseline.
        prev = np.load(WEIGHTS, allow_pickle=False) if WEIGHTS.exists() else prev
    elif WEIGHTS.exists():
        w = np.load(WEIGHTS, allow_pickle=False)
        W1, b1 = g(w, "W1"), g(w, "b1")
        W2, b2 = g(w, "W2"), g(w, "b2")
        W3, b3 = g(w, "W3"), g(w, "b3")
        mu, sd = g(w, "mu"), g(w, "sd")
        run_ts = str(g(w, "run_ts")) if g(w, "run_ts") is not None else None
    else:
        return {"meta": {"weights_persisted": False}}

    if head is not None:
        run_ts = None
    prev_run_ts = (str(g(prev, "run_ts"))
                   if prev is not None and g(prev, "run_ts") is not None else None)

    curve = _load_json(CURVE, {}) or {}
    param_count = int(sum(a.size for a in (W1, b1, W2, b2, W3, b3) if a is not None))

    meta = {
        "ts": _now(),
        "weights_path": _rel(WEIGHTS),
        "run_ts": run_ts,
        "prev_run_ts": prev_run_ts,
        "param_count": param_count,
        "embedding": curve.get("embedding"),
        "embedding_dim": curve.get("embedding_dim"),
        "architecture": curve.get("architecture"),
        "alpha": curve.get("alpha"),
        "beats_flat_baseline_heldout": curve.get("beats_flat_baseline_heldout"),
        "weights_persisted": True,
    }

    layers = []
    for name, W, P in (("W1", W1, g(prev, "W1")),
                       ("W2", W2, g(prev, "W2")),
                       ("W3", W3, g(prev, "W3"))):
        if W is not None:
            layers.append(_layer_stats(name, W, P))

    # ATTENTION = the column norms of W1: how much the first layer leans on each
    # input dimension. Not an attention mechanism — the head has none — but the
    # same question, answered by the only thing that can answer it here.
    attention, attention_delta = [], None
    if W1 is not None:
        attention = [float(v) for v in np.linalg.norm(W1, axis=1)]
        pW1 = g(prev, "W1")
        if pW1 is not None and pW1.shape == W1.shape:
            attention_delta = [float(a - b) for a, b in
                               zip(attention, np.linalg.norm(pW1, axis=1))]

    units = []
    if W1 is not None:
        units += _units(W1, b1, "layer1", g(prev, "W1"))
    if W2 is not None:
        units += _units(W2, b2, "layer2", g(prev, "W2"))

    # WHICH INPUT DIMENSIONS ARE THE SENSORS. The first embedding_dim columns of
    # W1 are language; the 11 after them are the row features, appended in this
    # order by interval_head.row_features(). Naming them is what lets a reader
    # ask whether the head leans on what it MEASURED or on what a step is CALLED.
    # The sensors are the LAST len(names) columns of W1, because row_features()
    # is hstacked AFTER the embedding. meta.embedding_dim is the TOTAL width
    # (2059 when row features are on), not the language width — reading it as
    # the offset put the sensor dims past the end of the matrix, which is the
    # bug this comment exists to stop coming back.
    names = _row_feature_names()
    has_rows = bool((_load_json(CURVE, {}) or {}).get("row_feature_coverage"))
    if W1 is not None and names and has_rows:
        first = int(W1.shape[0]) - len(names)
        sensor_dims = [first + k for k in range(len(names))]
    else:
        sensor_dims = []
    input_groups = {"sensor_names": list(names), "sensor_dims": sensor_dims}

    similarity = None
    if W1 is not None and W2 is not None:
        S1, S2 = _cosine_units(W1), _cosine_units(W2)
        o1, o2 = _greedy_chain(S1), _greedy_chain(S2)
        similarity = {
            "units_l1": _q8(S1), "order_l1": o1,
            "units_l2": _q8(S2), "order_l2": o2,
            "input_order_note": _sensor_note(W1, input_groups["sensor_dims"]),
        }

    blob = {"meta": meta, "layers": layers, "attention": attention,
            "attention_delta": attention_delta, "units": units,
            "input_groups": input_groups, "similarity": similarity,
            "inputs": _real_input_rows(W1, b1, W2, b2, W3, b3, mu, sd)}
    if training is not None:
        # Only inside a training run. Absent means idle, which is exactly what
        # the page needs to distinguish "nothing is moving" from "epoch 0".
        blob["training"] = training
    return blob


def dump() -> dict:
    return build()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", action="store_true",
                    help="write out/brain_scan.json")
    a = ap.parse_args(argv)
    if not a.dump:
        ap.print_help()
        return 0

    blob = dump()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    if not blob["meta"].get("weights_persisted"):
        print(f"no weights on disk yet ({_rel(WEIGHTS)}) — wrote "
              f"{_rel(OUT)} with weights_persisted=false")
        return 0
    m = blob["meta"]
    print(f"brain_scan -> {_rel(OUT)}")
    print(f"  run_ts {m['run_ts']}  prev {m['prev_run_ts']}  "
          f"params {m['param_count']}")
    print(f"  layers {len(blob['layers'])}  units {len(blob['units'])}  "
          f"attention dims {len(blob['attention'])}  "
          f"input rows {len(blob['inputs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
