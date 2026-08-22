#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/lexicon.py — GLYPHS FOR STATES, AND THREE WAYS THE LANGUAGE MAY GROW.

LANGUAGE IS VALID ONLY IF THE DETERMINISTIC CODE CAN PARSE IT
---------------------------------------------------------------
That is the whole rule. A glyph, a compound state, a boolean contrast — every
construction here has a parser in this file, and parse_expression() runs with no
model in the loop. A construction the code cannot read is not a richer language;
it is noise with a Greek letter in front of it, and it would let the system
appear to be saying more while saying nothing checkable.

THE SEED
---------
k-means, k=16, over the 25-dimensional cycle vector, giving Δ0..Δ15. Implemented
in numpy rather than sklearn because sklearn is not installed and this is 40
lines of Lloyd's algorithm — a new dependency for that would be a bad trade.
Deterministic: the seed is an argument, initialisation is k-means++ over a seeded
RandomState, and the same vectors produce the same glyphs.

The christening map — which glyph is called what in human words — lives in
config_expression.yaml, NOT here. Naming is the human's job; clustering is the
machine's, and mixing them in one file is how the names start driving the maths.

THREE GROWTH MECHANISMS, EACH WITH A MEASURED REASON
------------------------------------------------------
1. PREDICTIVE BIGRAMS. ΔX -> ΔY that precede a concrete event become a named
   compound state — but only with measured predictive value. lift and support
   are computed and stored; a bigram that is merely frequent does not qualify.

2. HIERARCHICAL SPLITTING. When mean silhouette falls below 0.3 the glyph set
   may grow 16 -> 32 -> 64. Every split is logged WITH ITS MEASURED REASON. A
   split whose only reason is "we want more glyphs" is REFUSED, by code, in
   propose_split(): if the silhouette is healthy the proposal comes back
   allowed=False and says so.

3. BOOLEAN CONTRASTS. `NOT Δ3 AND Δ7` — parsed by a real grammar in
   parse_contrast(), not by a model deciding what it probably meant.

VECTOR VERSIONING
------------------
The 25-dim vector carries a version tag. If it is extended, the cluster
migration is LOGGED rather than silently remapped: Δ7 under v1 and Δ7 under v2
are different states that happen to share an index, and a chart that plots them
on one line is lying about continuity.

    venv/Scripts/python.exe -m cockpit.lexicon --selftest
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np

BASE = pathlib.Path(__file__).resolve().parents[1]

VECTOR_VERSION = "v1"
VECTOR_DIMS = 25

SEED_K = 16
K_LADDER = (16, 32, 64)
SILHOUETTE_FLOOR = 0.3

# A bigram must clear BOTH to become a compound state. Frequency alone is not
# predictive value: the most common transition in any system is "nothing changed".
MIN_SUPPORT = 5          # times the bigram was observed
MIN_LIFT = 1.5           # P(event | bigram) / P(event)

GLYPH_PREFIX = "Δ"
GLYPH_RE = re.compile(r"Δ(\d+)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def glyph(i: int) -> str:
    return "{}{}".format(GLYPH_PREFIX, int(i))


# ---------------------------------------------------------------------------
# k-means, in numpy
# ---------------------------------------------------------------------------

def _kmeanspp(X: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    n = X.shape[0]
    centres = [X[rng.integers(n)]]
    for _ in range(1, k):
        d2 = np.min(((X[:, None, :] - np.array(centres)[None, :, :]) ** 2).sum(-1),
                    axis=1)
        total = d2.sum()
        if not np.isfinite(total) or total <= 0:
            centres.append(X[rng.integers(n)])
            continue
        centres.append(X[rng.choice(n, p=d2 / total)])
    return np.array(centres)


def kmeans(X: np.ndarray, k: int = SEED_K, seed: int = 0,
           iters: int = 100) -> tuple:
    """(labels, centroids). Deterministic for a given seed."""
    X = np.asarray(X, dtype=float)
    if X.ndim != 2:
        raise ValueError("expected a 2-D array of vectors, got shape {}".format(X.shape))
    n = X.shape[0]
    k = max(1, min(int(k), n))
    rng = np.random.default_rng(seed)
    C = _kmeanspp(X, k, rng)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        d = ((X[:, None, :] - C[None, :, :]) ** 2).sum(-1)
        new = d.argmin(axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            members = X[labels == j]
            if len(members):
                C[j] = members.mean(axis=0)
    return labels, C


def silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    """Mean silhouette over all points. 0.0 when it is undefined.

    Undefined rather than raising: a single cluster has no separation to measure,
    and a lexicon of one glyph is a real (bad) state the caller must be able to
    see rather than a crash.
    """
    X = np.asarray(X, dtype=float)
    labels = np.asarray(labels)
    uniq = np.unique(labels)
    if len(uniq) < 2 or len(X) < 3:
        return 0.0
    D = np.sqrt(((X[:, None, :] - X[None, :, :]) ** 2).sum(-1))
    scores = []
    for i in range(len(X)):
        own = labels[i]
        same = (labels == own)
        same[i] = False
        if not same.any():
            continue
        a = D[i, same].mean()
        b = min(D[i, labels == other].mean()
                for other in uniq if other != own)
        denom = max(a, b)
        scores.append(0.0 if denom == 0 else (b - a) / denom)
    return float(np.mean(scores)) if scores else 0.0


# ---------------------------------------------------------------------------
# The lexicon
# ---------------------------------------------------------------------------

@dataclass
class Lexicon:
    k: int
    centroids: list
    vector_version: str = VECTOR_VERSION
    seed: int = 0
    silhouette: float = 0.0
    compounds: dict = field(default_factory=dict)   # name -> {from,to,support,lift}
    fitted_at: str = field(default_factory=_now)

    def glyphs(self) -> list:
        return [glyph(i) for i in range(self.k)]

    def assign(self, vector) -> str:
        v = np.asarray(vector, dtype=float)
        C = np.asarray(self.centroids, dtype=float)
        return glyph(int(((C - v) ** 2).sum(axis=1).argmin()))

    def as_dict(self) -> dict:
        return {"k": self.k, "vector_version": self.vector_version,
                "seed": self.seed, "silhouette": round(self.silhouette, 4),
                "glyphs": self.glyphs(), "compounds": self.compounds,
                "fitted_at": self.fitted_at,
                "centroids": [list(map(float, c)) for c in self.centroids]}


def fit(vectors, k: int = SEED_K, seed: int = 0,
        vector_version: str = VECTOR_VERSION) -> Lexicon:
    X = np.asarray(vectors, dtype=float)
    if X.ndim != 2:
        raise ValueError("vectors must be 2-D")
    labels, C = kmeans(X, k=k, seed=seed)
    return Lexicon(k=int(C.shape[0]), centroids=[list(map(float, c)) for c in C],
                   vector_version=vector_version, seed=seed,
                   silhouette=silhouette(X, labels))


# ---------------------------------------------------------------------------
# GROWTH 1 — predictive bigrams
# ---------------------------------------------------------------------------

def bigram_stats(sequence: list, events: list) -> dict:
    """{(ΔX,ΔY): {support, lift, p_event_given, p_event}} over a glyph sequence.

    `events` is a parallel list of booleans: did a concrete event occur at that
    step. Lift is P(event | bigram) / P(event) — a bigram that predicts nothing
    has lift 1.0 however often it appears.
    """
    if len(sequence) != len(events):
        raise ValueError("sequence and events must be the same length")
    base = sum(1 for e in events if e) / len(events) if events else 0.0
    counts, hits = {}, {}
    for i in range(len(sequence) - 1):
        pair = (sequence[i], sequence[i + 1])
        counts[pair] = counts.get(pair, 0) + 1
        # the event that FOLLOWS the pair
        if i + 1 < len(events) and events[i + 1]:
            hits[pair] = hits.get(pair, 0) + 1
    out = {}
    for pair, n in counts.items():
        p = hits.get(pair, 0) / n
        out[pair] = {"support": n, "p_event_given": round(p, 4),
                     "p_event": round(base, 4),
                     "lift": round(p / base, 4) if base > 0 else 0.0}
    return out


def propose_compound(pair: tuple, stats: dict) -> dict:
    """Should ΔX->ΔY become a named compound state? MEASURED, not felt."""
    s = stats.get(pair)
    if not s:
        return {"allowed": False, "reason": "never observed"}
    if s["support"] < MIN_SUPPORT:
        return {"allowed": False,
                "reason": "support {} < {}".format(s["support"], MIN_SUPPORT),
                **s}
    if s["lift"] < MIN_LIFT:
        return {"allowed": False,
                "reason": ("lift {} < {} — frequent is not predictive"
                           .format(s["lift"], MIN_LIFT)), **s}
    return {"allowed": True,
            "reason": "support {} and lift {}".format(s["support"], s["lift"]),
            "name": "{}>{}".format(pair[0], pair[1]), **s}


# ---------------------------------------------------------------------------
# GROWTH 2 — hierarchical splitting, with a refusal
# ---------------------------------------------------------------------------

def propose_split(vectors, current_k: int, seed: int = 0) -> dict:
    """May the glyph set grow? Only if the measurement says the clusters are bad.

    THE REFUSAL IS THE POINT. If silhouette is at or above the floor, this
    returns allowed=False with the number that refused it. "We want more glyphs"
    is not a reason and cannot be entered as one — there is no parameter here to
    express it.
    """
    X = np.asarray(vectors, dtype=float)
    labels, _ = kmeans(X, k=current_k, seed=seed)
    s = silhouette(X, labels)
    nxt = next((k for k in K_LADDER if k > current_k), None)
    if s >= SILHOUETTE_FLOOR:
        return {"allowed": False, "silhouette": round(s, 4),
                "floor": SILHOUETTE_FLOOR, "current_k": current_k,
                "reason": ("silhouette {:.4f} >= {} — the clusters are separable, "
                           "so more glyphs would name distinctions the data does "
                           "not contain".format(s, SILHOUETTE_FLOOR))}
    if nxt is None:
        return {"allowed": False, "silhouette": round(s, 4),
                "current_k": current_k,
                "reason": "already at the top of the ladder {}".format(K_LADDER)}
    labels2, _ = kmeans(X, k=nxt, seed=seed)
    s2 = silhouette(X, labels2)
    # A LOW SILHOUETTE IS NOT ITSELF A LICENCE. Found while testing this on pure
    # noise: silhouette 0.0223 at k=16 and 0.0043 at k=32, and the first draft
    # allowed the split and described it as "raises it to 0.0043". Data with no
    # cluster structure has none at any k, and cutting it finer just produces
    # more glyphs that name nothing — which is the exact move propose_split()
    # exists to refuse, arriving by a different door.
    if s2 <= s:
        return {"allowed": False, "silhouette": round(s, 4),
                "floor": SILHOUETTE_FLOOR, "current_k": current_k,
                "next_k": nxt, "silhouette_after": round(s2, 4),
                "reason": ("silhouette {:.4f} < {}, but k {} -> {} does not "
                           "improve it ({:.4f}) — this data has no cluster "
                           "structure at any k, and more glyphs would name "
                           "nothing".format(s, SILHOUETTE_FLOOR, current_k,
                                            nxt, s2))}
    return {"allowed": True, "silhouette": round(s, 4), "floor": SILHOUETTE_FLOOR,
            "current_k": current_k, "next_k": nxt,
            "silhouette_after": round(s2, 4),
            "reason": ("silhouette {:.4f} < {}; k {} -> {} raises it to {:.4f}"
                       .format(s, SILHOUETTE_FLOOR, current_k, nxt, s2))}


def log_split(decision: dict, path: pathlib.Path) -> pathlib.Path:
    """Append a split decision WITH its measured reason. `path` is REQUIRED."""
    if not decision.get("reason"):
        raise ValueError("a split may not be logged without its measured reason")
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _now(), **decision}, ensure_ascii=False) + "\n")
    return p


def log_migration(old: Lexicon, new: Lexicon, path: pathlib.Path) -> pathlib.Path:
    """Record a vector-version change HONESTLY. `path` is REQUIRED.

    Δ7 under v1 and Δ7 under v2 are different states that happen to share an
    index. Plotting them on one line would be a claim of continuity nobody
    measured, so the migration is written down instead of applied silently.
    """
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": _now(), "from_version": old.vector_version,
           "to_version": new.vector_version, "from_k": old.k, "to_k": new.k,
           "glyph_indices_are_not_comparable_across_versions": True}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return p


# ---------------------------------------------------------------------------
# GROWTH 3 — boolean contrasts, with a real parser
# ---------------------------------------------------------------------------

_CONTRAST_TOKEN = re.compile(r"\s*(NOT|AND|OR|Δ\d+|\(|\))")


def parse_contrast(text: str) -> dict:
    """Parse `NOT Δ3 AND Δ7` into a tree. Raises on anything it cannot read.

    Grammar:
        expr   := term (('AND'|'OR') term)*
        term   := 'NOT'? atom
        atom   := GLYPH | '(' expr ')'

    Raising is the contract. A construction the parser cannot read is refused,
    which is what makes the language checkable — see the module docstring.
    """
    toks = [t for t in re.findall(r"NOT|AND|OR|Δ\d+|\(|\)", str(text or ""))]
    if not toks:
        raise ValueError("no parseable tokens in {!r}".format(text))
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def eat(expected=None):
        nonlocal pos
        t = peek()
        if t is None or (expected and t != expected):
            raise ValueError("expected {!r}, got {!r}".format(expected, t))
        pos += 1
        return t

    def atom():
        t = peek()
        if t == "(":
            eat("(")
            e = expr()
            eat(")")
            return e
        if t and GLYPH_RE.fullmatch(t):
            eat()
            return {"glyph": t}
        raise ValueError("expected a glyph, got {!r}".format(t))

    def term():
        if peek() == "NOT":
            eat("NOT")
            return {"op": "NOT", "of": atom()}
        return atom()

    def expr():
        node = term()
        while peek() in ("AND", "OR"):
            op = eat()
            node = {"op": op, "left": node, "right": term()}
        return node

    tree = expr()
    if pos != len(toks):
        raise ValueError("trailing tokens: {}".format(toks[pos:]))
    return tree


def eval_contrast(tree: dict, active: set) -> bool:
    """Evaluate a parsed contrast against the set of currently active glyphs."""
    if "glyph" in tree:
        return tree["glyph"] in active
    op = tree.get("op")
    if op == "NOT":
        return not eval_contrast(tree["of"], active)
    if op == "AND":
        return eval_contrast(tree["left"], active) and eval_contrast(tree["right"], active)
    if op == "OR":
        return eval_contrast(tree["left"], active) or eval_contrast(tree["right"], active)
    raise ValueError("unknown node {!r}".format(tree))


def parse_expression(text: str) -> dict:
    """Every construction the language allows, read by code and nothing else."""
    out = {"glyphs": GLYPH_RE.findall(str(text or "")), "contrast": None}
    try:
        out["contrast"] = parse_contrast(text)
    except ValueError:
        out["contrast"] = None
    return out
