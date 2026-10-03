# -*- coding: utf-8 -*-
"""core/space_witness.py — a second witness over every derivation of the space, in plain Python
(C-GUARD-1 Step 4, Kimi round 74 K1: "every derived atom re-checked in plain Python against the base").

One function per rule of config/space_rules.metta: contradiction, unverified, stale, uncovered,
lacks_evidence (commitment-evidence), need_from. Each recomputes, from base.metta + proposed.metta
WITHOUT the engine, the expressions that rule must produce. core/space.derive compares the two sets
in both directions. Decided: this module imports no hyperon and no other CORTEX module — its
tokenizer and parser are its own, so a defect in core/space's parser cannot agree with itself here.

The stale rule reads no clock: its day counts (period-age) and `this-year` are atoms that
core/space.build wrote from its own `today`; the witness reads the same atoms.
"""
from __future__ import annotations

import re

_TOK = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def _value(t: str):
    if t.startswith('"'):
        body = t[1:-1]
        return bytes(body, "utf-8").decode("unicode_escape") if "\\" in body else body
    try:
        return float(t)
    except ValueError:
        return t


def forms(text: str) -> list:
    """The top-level expressions of a MeTTa text as nested lists; `!` commands and comment lines skipped."""
    toks = _TOK.findall("\n".join(l for l in text.splitlines() if not l.lstrip().startswith(";")))
    out, stack, bang = [], [], False
    for t in toks:
        if t == "(":
            if not stack:
                cur_bang, bang = bang, False
                stack.append(([], cur_bang))
            else:
                stack.append(([], False))
        elif t == ")":
            lst, b = stack.pop()
            if stack:
                stack[-1][0].append(lst)
            elif not b:
                out.append(lst)
        elif not stack:
            bang = t == "!"
        else:
            stack[-1][0].append(_value(t))
    return out


def index(text: str) -> dict:
    ix: dict = {}
    for x in forms(text):
        if x and isinstance(x[0], str):
            ix.setdefault(x[0], []).append(x[1:])
    return ix


def _obs(ix):
    """(obs a sub key place period value unit source), 8 arguments."""
    return [o for o in ix.get("obs", []) if len(o) == 8]


def _num(v):
    return v if isinstance(v, float) else None


# ── one function per rule ───────────────────────────────────────────────────
def contradiction(ix) -> list:
    out = []
    by_kpp: dict = {}
    for o in _obs(ix):
        by_kpp.setdefault((repr(o[2]), repr(o[3]), repr(o[4])), []).append(o)
    for group in by_kpp.values():
        for a in group:
            for b in group:
                if a[5] != b[5] and a[7] != b[7]:
                    out.append(["contradiction", a[2], a[3], a[4], a[0], b[0]])
    return out


def unverified(ix) -> list:
    classes = ix.get("source-class", [])
    indep = {r[0] for r in ix.get("independent-src", []) if r}
    obs = _obs(ix)
    out = []
    for a in obs:
        for src, cls in ((r[0], r[1]) for r in classes if len(r) == 2):
            if src != a[7] or cls not in ("self_reported", "unknown"):
                continue
            backed = any(b[2] == a[2] and b[3] == a[3] and b[4] == a[4] and b[7] in indep for b in obs)
            if not backed:
                out.append(["unverified", a[0], a[2], a[3], a[4]])
    return out


def stale(ix) -> list:
    out = []
    for r in ix.get("period-age", []):
        if len(r) == 3 and _num(r[2]) is not None:
            if (r[1] == "day" and r[2] > 45) or (r[1] == "month" and r[2] > 120):
                out.append(["stale", r[0]])
    for r in ix.get("period-year", []):
        for t in ix.get("this-year", []):
            if len(r) == 2 and _num(r[1]) is not None and t and _num(t[0]) is not None and r[1] < t[0] - 3:
                out.append(["stale", r[0]])
    return out


def uncovered(ix) -> list:
    obs_subs = {o[1] for o in _obs(ix)}
    subs_of: dict = {}
    for r in ix.get("subcategory", []):
        if len(r) == 2:
            subs_of.setdefault(r[1], set()).add(r[0])
    out = []
    for ax, sg in (r for r in ix.get("axis-serves", []) if len(r) == 2):
        for g in ix.get("gap", []):
            if len(g) == 3 and g[0] == ax and _num(g[1]) is not None and g[1] > 0:
                cats = {r[0] for r in ix.get("serves", []) if len(r) == 2 and r[1] == sg}
                if not any(s in obs_subs for c in cats for s in subs_of.get(c, ())):
                    out.append(["uncovered", sg])
    return out


def lacks_evidence(ix, stale_list) -> list:
    stale_ids = {x[1] for x in stale_list}
    out = []
    for r in ix.get("commitment-place", []):
        if len(r) == 2 and not any(o[3] == r[1] and o[0] not in stale_ids for o in _obs(ix)):
            out.append(["lacks-evidence", r[0], r[1]])
    return out


def need_from(contra, unver, uncov, lacks) -> list:
    return ([["need-derived", "VERIFY", "contradiction", *x[1:]] for x in contra]
            + [["need-derived", "VERIFY", "unverified", x[2], x[3], x[4], x[1]] for x in unver]
            + [["need-derived", "FIND", "uncovered", x[1]] for x in uncov]
            + [["need-derived", "FIND", "lacks-evidence", x[1], x[2]] for x in lacks])


def witness(text: str) -> list:
    """Every expression the six rules must derive from this base (+ proposed) text."""
    ix = index(text)
    c, u, s, v = contradiction(ix), unverified(ix), stale(ix), uncovered(ix)
    le = lacks_evidence(ix, s)
    return c + u + s + v + le + need_from(c, u, v, le)
