# -*- coding: utf-8 -*-
"""core/brain_needs.py — the brain says what it needs to know (C-NEED-1 Part 2).

Emil, R29: "build the mechanism so the brain can say what it needs and the
finder knows that need." This is COGNITION; core/maintenance.py is the separate
rotation that keeps every cell current.

1. briefing()  — built from code, no model: the five sub-goals and the top rows of
   the grounded ranking; contradictions among measurement atoms (same key, place
   and period, different values, both sources named); the open forward rows; what
   CHANGED since the previous briefing; the brain's previous needs and what
   happened to each. Plain text plus the same facts as MeTTa lines, stored with
   its sha256.
2. ask()       — cortex-l1b-3b through core.brain.think (the one door, with
   provenance). The reply is parsed HERE, so an unparseable reply keeps its raw
   text: it is recorded as SILENCE, never replaced by a default need.
3. check_form() — FORM only: a non-empty question that is not a copy of the
   briefing, a why_subgoal that is one of the five, not identical to a need
   already SATISFIED. Code never judges whether a need is valuable. A refused
   need goes to memory/brain_needs_refused.jsonl with its reason.
4. engine_needs() — no model: each contradiction becomes VERIFY, each open
   forward row FIND.
5. emit()      — memory/brain_needs.json: brain needs first, then engine needs;
   each with id, origin, briefing_sha256, created_utc, status. A need leaves the
   queue only by the brain's verdict SATISFIED or WRONG_QUESTION (Part 3), never
   by time.

    venv\\Scripts\\python.exe -m core.brain_needs            # one briefing + ask
    venv\\Scripts\\python.exe -m core.brain_needs --briefing # print the briefing only
    venv\\Scripts\\python.exe -m core.brain_needs --selftest
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
MEM = REPO / "memory"
PATHS = {
    "needs": MEM / "brain_needs.json",
    "refused": MEM / "brain_needs_refused.jsonl",
    "log": MEM / "brain_needs_log.jsonl",
    "ledger": MEM / "vertical_ledger.jsonl",
    "briefings": MEM / "brain_briefings.jsonl",
    "grounded": MEM / "orchestration_grounded_latest.json",
    "forward_glob": str(REPO / "experiments" / "institution" / "forward" / "F-[0-9]*.json"),
    "obs_log": MEM / "observation_log.jsonl",
    "atoms_root": None,
}
MODEL = "cortex-l1b-3b:latest"
KINDS = ("FIND", "VERIFY", "EXPLAIN")
OPEN, SATISFIED, STILL_OPEN, WRONG_QUESTION, SILENCE = "OPEN", "SATISFIED", "STILL_OPEN", "WRONG_QUESTION", "SILENCE"
MAX_NEEDS = 5
TOP_GROUNDED = 5


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class PathMissing(KeyError):
    """A caller that passes its own paths must pass ALL of them."""


def _p(paths: Optional[dict], k: str):
    """Live path when no paths are given; otherwise the caller's, and a missing key
    RAISES — never a silent fall back to memory/ (1 Oct 2026: a test fixture
    without "ledger" wrote 29 rows into the live vertical ledger this way)."""
    if paths is None:
        return PATHS[k]
    if k not in paths:
        raise PathMissing(f"paths given without {k!r}")
    return paths[k]


def _read(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _jsonl(p) -> list:
    try:
        return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


def _append(p, row: dict) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with Path(p).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _m(s) -> str:
    """A MeTTa string literal."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


# ── the facts ───────────────────────────────────────────────────────────────
def subgoals() -> list:
    from core import taxonomy as tx
    return sorted(tx.subgoal_names())


def grounded_top(paths=None, n: int = TOP_GROUNDED) -> list:
    doc = _read(_p(paths, "grounded"), {})
    rows = doc.get("ranking") or []
    return [{k: r.get(k) for k in ("axis", "key", "value", "unit", "score", "need", "measured")} for r in rows[:n]]


def forward_rows(paths=None) -> list:
    out = []
    for f in sorted(glob.glob(_p(paths, "forward_glob"))):
        if not re.fullmatch(r"F-\d+\.json", Path(f).name):
            continue                                   # F-001.seal.json etc. are not rows
        d = _read(f, {})
        if not d.get("id") or d.get("outcome") or d.get("resolved"):
            continue
        c = d.get("condition") or {}
        prov = (d.get("resolution") or {}).get("provisional") or {}
        out.append({"row": d["id"], "actor": c.get("dyad_name"), "place": c.get("adm_1"),
                    "condition": f"{c.get('metric')} {c.get('kept_if')} from {c.get('date_start_from')} "
                                 f"to {c.get('date_start_to')} ({c.get('source')})",
                    "resolve_by": f"{prov.get('resolve_by')} (expected {prov.get('expected')})"})
    return out


def changed_since(ts: Optional[str], paths=None) -> list:
    return [r for r in _jsonl(_p(paths, "obs_log"))
            if r.get("verdict") == "CHANGED" and (ts is None or str(r.get("ts")) > ts)]


def load_needs(paths=None) -> dict:
    return _read(_p(paths, "needs"), {"needs": [], "briefing_sha256": None, "briefing_utc": None})


# ── 1. the briefing ─────────────────────────────────────────────────────────
PER_RULE_IN_TEXT = 8      # think() keeps the last 5000 characters of evidence; the MeTTa lines keep all


def briefing(paths=None, derived: Optional[list] = None) -> dict:
    """`derived` is what core.space derived this turn (parsed expressions)."""
    from core import space as sp
    derived = derived or []
    prev = load_needs(paths)
    sg, top, fwd = subgoals(), grounded_top(paths), forward_rows(paths)
    con = [x for x in derived if x[0] == "contradiction"]
    ch = changed_since(prev.get("briefing_utc"), paths)
    mine = [n for n in prev.get("needs", []) if n.get("origin") == "brain"]
    T, M = [], []
    T.append("SUB-GOALS (the five): " + ", ".join(sg))
    M += [f"(subgoal {_m(s)})" for s in sg]
    T.append("\nWHERE THE SYSTEM IS FURTHEST FROM ITS TARGETS (need = weight x (1 - score)):")
    for r in top:
        T.append(f"- {r['axis']} {r['key'] or '(no key)'}: value {r['value']} {r['unit'] or ''}, "
                 f"score {r['score']}, need {r['need']}{'' if r['measured'] else ' (NOT MEASURED)'}")
        M.append(f"(grounded {_m(r['axis'])} {_m(r['key'])} {_m(r['value'])} {_m(r['score'])} {_m(r['need'])})")
    T.append("\nWHAT THE SPACE DERIVED (rules in config/space_rules.metta; premises are atom ids):"
             + ("" if derived else " nothing"))
    for head in ("contradiction", "unverified", "stale", "uncovered", "lacks-evidence"):
        xs = [x for x in derived if x[0] == head]
        if not xs:
            continue
        T.append(f"- {head}: {len(xs)}")
        for x in xs[:PER_RULE_IN_TEXT]:
            T.append(f"    {sp.render(x)}")
        if len(xs) > PER_RULE_IN_TEXT:
            T.append(f"    ... and {len(xs) - PER_RULE_IN_TEXT} more")
    M += [sp.render(x) for x in derived if x[0] != "need-derived"]
    T.append("\nOPEN FORWARD ROWS (commitments being watched):" + ("" if fwd else " none"))
    for f in fwd:
        T.append(f"- {f['row']}: {f['actor']} in {f['place']}; kept if {f['condition']}; resolves {f['resolve_by']}")
        M.append(f"(forward {_m(f['row'])} {_m(f['actor'])} {_m(f['place'])} {_m(f['condition'])} {_m(f['resolve_by'])})")
    T.append("\nCHANGED SINCE THE LAST BRIEFING:" + ("" if ch else " nothing registered"))
    for r in ch[-10:]:
        cf = r.get("changed_from") or {}
        ident = r.get("identity") or []
        T.append(f"- {ident[1:4]}: was {cf.get('value')} ({cf.get('period')}), now {ident[4] if len(ident) > 4 else '?'}")
        M.append(f"(changed {_m(ident[1] if len(ident) > 1 else '')} {_m(cf.get('value'))} "
                 f"{_m(ident[4] if len(ident) > 4 else '')})")
    T, line_ids = number_lines(T)
    facts_text = "\n".join(T)      # the copy check compares against the FACTS, not the brain's own past needs
    T.append("\nYOUR PREVIOUS NEEDS AND WHAT HAPPENED:" + ("" if mine else " none yet"))
    for n in mine[-10:]:
        T.append(f"- [{n['id']}] [{n['status']}] {n['question']} (searched {n.get('searched', 0)} time(s), "
                 f"gained {n.get('gained_statements', 0)} statement(s))")
        M.append(f"(prior-need {_m(n['id'])} {_m(n['question'])} {_m(n['status'])})")
    text = "\n".join(T)
    metta = "\n".join(M)
    sha = hashlib.sha256((text + "\n" + metta).encode("utf-8")).hexdigest()
    b = {"utc": _now(), "sha256": sha, "text": text, "facts_text": facts_text, "metta": metta, "line_ids": line_ids,
         "facts": {"subgoals": sg, "grounded": top, "contradictions": con, "forward": fwd,
                   "changed": len(ch), "prior_needs": len(mine)}}
    _append(_p(paths, "briefings"), b)
    return b


def number_lines(lines: list) -> tuple:
    """Every fact line (a "- " item or an indented expression) gets an id [L<n>]
    the brain can point at; headings stay as they are. -> (lines, {id: line})."""
    out, ids, n = [], {}, 0
    for line in lines:
        st = line.lstrip()
        if st.startswith("- ") or st.startswith("("):
            n += 1
            lid = f"L{n}"
            ids[lid] = st
            out.append(line[: len(line) - len(st)] + f"[{lid}] " + st)
        else:
            out.append(line)
    return out, ids


# ── 2. ask ──────────────────────────────────────────────────────────────────
QUESTION = (
    "Read the briefing. What do YOU need to know next, and why? State up to 5 needs in "
    "your own words. Answer ONLY with JSON of this shape:\n"
    '{"needs": [{"question": "<what you need to know, in your own words>", '
    '"why_subgoal": "<exactly one of the five sub-goal names>", '
    '"about": {"place": <string or null>, "actor": <string or null>, "period": <string or null>}, '
    '"kind": "FIND | VERIFY | EXPLAIN", '
    '"would_change": "<what you would do differently if it were answered>", '
    '"from_line": "<the [L..] id of the briefing line this need arises from, or none>", '
    '"expects": "<one line: what you expect the search to bring back>"}]}')


_S = {"type": "string"}
_SN = {"type": ["string", "null"]}
SCHEMA_NEEDS = {"type": "object", "properties": {"needs": {"type": "array", "maxItems": MAX_NEEDS, "items": {
    "type": "object", "properties": {
        "question": _S, "why_subgoal": _S,
        "about": {"type": "object", "properties": {"place": _SN, "actor": _SN, "period": _SN},
                  "required": ["place", "actor", "period"]},
        "kind": {"type": "string", "enum": list(KINDS)}, "would_change": _S, "from_line": _S, "expects": _S},
    "required": ["question", "why_subgoal", "about", "kind", "would_change", "from_line", "expects"]}}},
    "required": ["needs"]}


def _think(prompt: str, evidence: str, schema: dict) -> Optional[dict]:
    """The one door, schema-bound at temperature 0 (C-BRAIN-1 2a). With no evidence
    the prompt is a written instruction text and goes out verbatim (exact)."""
    from core import brain
    role = "what I need to know" if schema is SCHEMA_NEEDS else "did it answer my question"
    return brain.think(role, prompt, evidence=evidence, json_schema=schema, exact=not evidence,
                       model_override=MODEL, kind="brain_needs", lean=False)


def _schema_problem(d, schema: dict) -> Optional[str]:
    try:
        import jsonschema
        jsonschema.validate(d, schema)
        return None
    except Exception as exc:                                         # noqa: BLE001
        return f"schema-invalid: {str(exc).splitlines()[0][:200]}"


def bound(r: Optional[dict], schema: dict) -> tuple:
    """-> (data or None, raw, why unreadable or None). The reply is validated
    AGAIN here, so a door that let a bad reply through cannot make it readable."""
    if not r:
        return None, None, "no reply"
    raw = r.get("raw")
    if r.get("unreadable"):
        return None, raw, r["unreadable"]
    if "data" not in r:
        return None, raw, "no data in the reply"
    why = _schema_problem(r["data"], schema)
    return (None, raw, why) if why else (r["data"], raw, None)


def unreadable(what: str, why: str, raw, paths=None, **extra) -> dict:
    """A schema-invalid reply is recorded UNREADABLE with its raw text; nothing is
    put in its place. The board counts these rows."""
    row = {"event": "UNREADABLE", "ts": _now(), "what": what, "why": why, "raw": raw, **extra}
    _append(_p(paths, "log"), row)
    _append(_p(paths, "ledger"), row)
    return row


def ask(b: dict, think: Optional[Callable] = None, free: Optional[list] = None) -> dict:
    """-> {"raw", "parsed": list or None, "unreadable": why or None, "model", "sec"}.
    `free`: the sub-goals with no open parent — told to the brain as data."""
    t0 = time.time()
    ev = b["text"] + ("" if free is None else "\n\nSUB-GOALS WITH NO OPEN PARENT: " + ", ".join(free))
    try:
        r = (think or _think)(QUESTION, ev, SCHEMA_NEEDS)
    except Exception as exc:                                         # noqa: BLE001
        return {"raw": None, "parsed": None, "unreadable": f"{type(exc).__name__}: {exc}",
                "sec": round(time.time() - t0, 1)}
    d, raw, why = bound(r, SCHEMA_NEEDS)
    return {"raw": raw, "parsed": d["needs"] if d else None, "unreadable": why, "model": (r or {}).get("model"),
            "sec": (r or {}).get("sec", round(time.time() - t0, 1))}


# ── 3. form ─────────────────────────────────────────────────────────────────
def check_form(need, briefing_text: str, satisfied_questions: set, five: list) -> Optional[str]:
    """None if well-formed, else the reason. FORM ONLY."""
    if not isinstance(need, dict):
        return "not an object"
    q = need.get("question")
    if not isinstance(q, str) or not q.strip():
        return "question is empty"
    if len(_norm(q)) >= 20 and _norm(q) in _norm(briefing_text):
        return "question is a copy of the briefing"
    if need.get("why_subgoal") not in five:
        return f"why_subgoal {need.get('why_subgoal')!r} is not one of the five sub-goals"
    if _norm(q) in satisfied_questions:
        return "identical to a need already SATISFIED"
    return None


def _anchor(v, line_ids: dict) -> str:
    """The brain's from_line as given, normalised to "L<n>"; "none" when it gave
    none. Nothing is refused for it; the board counts anchored vs unanchored."""
    s = str(v or "").strip().strip("[]")
    return s if s in line_ids else ("none" if not s or s.lower() == "none" else f"unknown:{s}")


def _id(origin: str, text: str) -> str:
    return ("BN-" if origin == "brain" else "EN-") + hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()[:10]


# ── parents and children (C-BRAIN-1 2b) ─────────────────────────────────────
PARENT, CHILD, DIRECT = "parent", "child", "direct"


def is_general(n: dict) -> bool:
    """No place, actor or period, or from_line "none"."""
    about = n.get("about") if isinstance(n.get("about"), dict) else {}
    return not any(about.get(k) for k in ("place", "actor", "period")) or str(n.get("from_line")) == "none"


def _is_parent(n: dict) -> bool:
    """A brain need with no role yet (written before roles) is judged by the same
    rule, so a turn that runs before adopt_roles never searches a general need."""
    if n.get("origin") != "brain":
        return False
    return n.get("role") == PARENT or (not n.get("role") and is_general(n))


def searchable(ns: list) -> list:
    """The open needs a searcher may take: a parent is never searched verbatim."""
    return [n for n in ns if n.get("status") in (OPEN, STILL_OPEN) and not _is_parent(n)]


def _held_questions(doc: dict) -> set:
    out = set()
    for n in doc.get("needs", []):
        out.add(_norm(n.get("question")))
        out.update(_norm(q) for q in n.get("questions") or [])
    return out


def adopt_roles(paths=None) -> int:
    """A brain need written before roles existed gets one by the same rule."""
    doc = load_needs(paths)
    n_new = 0
    for n in doc.get("needs", []):
        if n.get("origin") == "brain" and not n.get("role"):
            n["role"] = PARENT if is_general(n) else DIRECT
            n_new += 1
            if n["role"] == PARENT:
                n.setdefault("none_why", None)
                _append(_p(paths, "ledger"), {"event": "MADE_PARENT", "ts": _now(), "need_id": n["id"],
                                              "why": "general: no place, actor or period, or from_line none"})
    if n_new:
        _save_needs(doc, paths)
    return n_new


def free_subgoals(five: list, paths=None) -> list:
    """The sub-goals with no OPEN parent (2d)."""
    held = {n.get("why_subgoal") for n in load_needs(paths).get("needs", [])
            if _is_parent(n) and n.get("status") in (OPEN, STILL_OPEN)}
    return [s for s in five if s not in held]


def add_child(doc: dict, parent: dict, question: str, paths=None) -> Optional[dict]:
    """A narrower question becomes a CHILD of `parent`; one already held anywhere
    (any need's question or its history) is REPEAT and not added. The parent,
    once narrowed, is a parent: it is not searched again."""
    q = question.strip()
    if _norm(q) in _held_questions(doc):
        _append(_p(paths, "ledger"), {"event": "REPEAT", "ts": _now(), "parent": parent["id"], "question": q})
        return None
    rec = {"id": _id("brain", q), "origin": "brain", "role": CHILD, "parent": parent["id"],
           "briefing_sha256": parent.get("briefing_sha256"), "created_utc": _now(), "status": OPEN,
           "question": q, "why_subgoal": parent.get("why_subgoal"), "about": None, "kind": "FIND",
           "would_change": None, "expects": None, "from_line": "none"}
    doc["needs"].append(rec)
    parent.setdefault("children", []).append(rec["id"])
    if parent.get("role") != PARENT:
        parent["role"] = PARENT
        _append(_p(paths, "ledger"), {"event": "MADE_PARENT", "ts": _now(), "need_id": parent["id"],
                                      "why": "narrowed by review"})
    _append(_p(paths, "ledger"), {"event": "CHILD", "ts": _now(), "need_id": rec["id"], "parent": parent["id"],
                                  "question": q})
    return rec


# ── 4. engine needs come from the space (core/space.py, C-TURN-1 Part 1d) ───
# The Python path that computed them here was run side by side with the space on
# one fixture (they agreed) and then removed.


# ── 5. emit ─────────────────────────────────────────────────────────────────
def emit(b: dict, reply: Optional[dict], paths=None, engine: Optional[list] = None,
         free: Optional[list] = None) -> dict:
    """`engine` = core.space.needs_from(derived): the engine's needs, with premises.
    `reply` None: the question was not asked (every sub-goal has an open parent).
    `free`: a need for a sub-goal outside it is refused (2d)."""
    doc = load_needs(paths)
    needs = doc.get("needs", [])
    by_id = {n["id"]: n for n in needs}
    five = b["facts"]["subgoals"]
    satisfied = {_norm(n["question"]) for n in needs if n.get("status") == SATISFIED}
    accepted, refused, silence, reopened, repeats = [], [], None, [], []
    if reply is None:
        pass
    elif reply.get("unreadable") and reply.get("parsed") is None:
        silence = {"utc": _now(), "briefing_sha256": b["sha256"], "raw": reply.get("raw"),
                   "why": f"UNREADABLE: {reply['unreadable']}"}
        unreadable("needs", reply["unreadable"], reply.get("raw"), paths, briefing_sha256=b["sha256"])
    elif reply.get("parsed") is None or (isinstance(reply.get("parsed"), list) and not reply["parsed"]):
        silence = {"utc": _now(), "briefing_sha256": b["sha256"], "raw": reply.get("raw"),
                   "error": reply.get("error"), "why": "empty reply" if not reply.get("raw") else
                   ("no needs in the reply" if reply.get("parsed") == [] else "reply is not parseable JSON")}
        _append(_p(paths, "log"), {"event": SILENCE, **silence})
        _append(_p(paths, "ledger"), {"event": "SILENCE", "ts": _now(), "origin": "brain", "why": silence["why"]})
    else:
        for i, n in enumerate(reply["parsed"]):
            why = "over the limit of 5 needs" if i >= MAX_NEEDS else check_form(n, b["facts_text"], satisfied, five)
            if not why and free is not None and n.get("why_subgoal") in five and n.get("why_subgoal") not in free:
                why = f"sub-goal {n.get('why_subgoal')} already has an open parent"
            if why:
                row = {"utc": _now(), "briefing_sha256": b["sha256"], "reason": why, "need": n}
                refused.append(row)
                _append(_p(paths, "refused"), row)
                continue
            nid = _id("brain", n["question"])
            if nid in by_id and _is_parent(by_id[nid]):
                # a parent is never re-emitted, whatever its status (C-BRAIN-1 2b)
                _append(_p(paths, "ledger"), {"event": "REPEAT", "ts": _now(), "need_id": nid,
                                              "why": "the question of a parent asked again"})
                repeats.append(nid)
                continue
            if nid in by_id and by_id[nid]["status"] in (OPEN, STILL_OPEN):
                continue                                          # already open: not duplicated
            if nid in by_id:
                # asked again after the brain closed it: REOPENED, with its whole
                # history kept (1 Oct 2026, Part 4: the second reply re-asked all five
                # needs it had just called WRONG_QUESTION, and the record was overwritten)
                old = by_id[nid]
                old.setdefault("reopened", []).append({"utc": _now(), "briefing_sha256": b["sha256"],
                                                       "was": old["status"]})
                old["status"] = OPEN
                reopened.append(old)
                continue
            rec = {"id": nid, "origin": "brain", "briefing_sha256": b["sha256"], "created_utc": _now(),
                   "status": OPEN, **{k: n.get(k) for k in ("question", "why_subgoal", "about", "kind", "would_change",
                                                               "expects")},
                   "from_line": _anchor(n.get("from_line"), b.get("line_ids") or {})}
            rec["role"] = PARENT if is_general(rec) else DIRECT
            if rec["role"] == PARENT:
                # none_why is TEXT A's field; TEXT A failed its trial (C-BRAIN-1 Part 1) and is not
                # asked, so a parent is narrowed only by review (TEXT C) and none_why stays null
                rec["none_why"] = None
            by_id[nid] = rec
            accepted.append(rec)
    by_expr = {e: n for n in by_id.values()
               if n.get("origin") == "engine" and n.get("status") in (OPEN, STILL_OPEN) for e in _exprs(n)}
    for n in (engine or []):
        nid = _id("engine", n["question"])
        old = by_expr.get(n.get("expression"))
        held = by_id.get(nid)
        if old is not None:
            if old["question"] == n["question"]:
                continue
            if held is not None and held is not old and held.get("status") in (OPEN, STILL_OPEN):
                # re-worded into a question another open need already asks: one need (C-GW-1 3)
                _merge_engine(held, old)
                old.update({"status": MERGED, "merged_into": held["id"], "merged_utc": _now()})
                for e in _exprs(old):
                    by_expr[e] = held
                continue
            # the same derivation rendered as a new question (C-BRAIN-1 5e): one need, re-worded
            old.setdefault("questions", [old["question"]]).append(n["question"])
            old.update({k: n[k] for k in ("question", "kind", "about") if k in n})
            continue
        if held is not None:
            if held.get("origin") == "engine" and held.get("status") in (OPEN, STILL_OPEN):
                # another atom with the same question: the need lists both (C-GW-1 3)
                _merge_engine(held, n)
                for e in _exprs(n):
                    by_expr[e] = held
            continue
        rec = {"id": nid, "origin": "engine", "briefing_sha256": b["sha256"], "created_utc": _now(),
               "status": OPEN, **n, "expressions": [n["expression"]] if n.get("expression") else []}
        by_id[nid] = rec
        by_expr.update({e: rec for e in _exprs(rec)})
        accepted.append(rec)
    resolved = resolve_engine(by_id.values(), engine, paths) if engine is not None else []
    ordered = ([n for n in by_id.values() if n["origin"] == "brain"] +
               [n for n in by_id.values() if n["origin"] == "engine"])
    out = {"briefing_sha256": b["sha256"], "briefing_utc": b["utc"], "silence": silence, "needs": ordered}
    _save_needs(out, paths)
    for r in accepted:
        _append(_p(paths, "ledger"), {"event": "EMITTED", "ts": _now(), "need_id": r["id"], "origin": r["origin"],
                                      "question": r["question"]})
    for r in reopened:
        _append(_p(paths, "ledger"), {"event": "REOPENED", "ts": _now(), "need_id": r["id"], "was": r["reopened"][-1]["was"]})
    return {"accepted": accepted, "refused": refused, "reopened": reopened, "repeats": repeats, "silence": silence,
            "resolved": resolved, "open": sum(1 for n in ordered if n["status"] in (OPEN, STILL_OPEN))}


ENGINE_RESOLVED = "ENGINE_RESOLVED"
MERGED = "MERGED"


def _exprs(n: dict) -> list:
    return list(n.get("expressions") or ([n["expression"]] if n.get("expression") else []))


def _merge_engine(keep: dict, other: dict) -> None:
    """`other`'s atoms and derivations join `keep` (C-GW-1 3): one need, every atom listed."""
    keep["premises"] = list(dict.fromkeys((keep.get("premises") or []) + (other.get("premises") or [])))
    ex = _exprs(keep)
    keep["expressions"] = ex + [e for e in _exprs(other) if e not in ex]


def resolve_engine(needs, engine: list, paths=None) -> list:
    """C-BRAIN-1 5d: an open engine need whose derivation no longer fires (its
    expression is not among this turn's need-derived) is ENGINE_RESOLVED. For a
    VERIFY that is what an observation from an independent host does: the rule
    stops deriving it. Code does not close it by time or by having searched."""
    firing = {n.get("expression") for n in engine}
    out = []
    for n in needs:
        if (n.get("origin") == "engine" and n.get("status") in (OPEN, STILL_OPEN) and _exprs(n)
                and not any(e in firing for e in _exprs(n))):
            n["status"] = ENGINE_RESOLVED
            n["resolved_utc"] = _now()
            _append(_p(paths, "ledger"), {"event": ENGINE_RESOLVED, "ts": _now(), "need_id": n["id"],
                                          "expressions": _exprs(n)})
            out.append(n["id"])
    return out


def _save_needs(doc: dict, paths=None) -> None:
    Path(_p(paths, "needs")).parent.mkdir(parents=True, exist_ok=True)
    Path(_p(paths, "needs")).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")


def mark_served(need_id: str, query: str, hits: int, fetched: int, gained: int, paths=None) -> None:
    """The finder's account on the need itself; the status is NOT touched."""
    doc = load_needs(paths)
    for n in doc.get("needs", []):
        if n["id"] == need_id:
            n["searched"] = n.get("searched", 0) + 1
            n["last_served_utc"] = _now()           # the rotation: longest-waiting first (C-BRAIN-1 5a)
            n["last_query"] = query
            n["last_hits"], n["last_fetched"] = hits, fetched
            n["gained_statements"] = n.get("gained_statements", 0) + gained
    _save_needs(doc, paths)


# ── 6. the brain is told what came back, and judges its own needs ───────────
VERDICTS = (SATISFIED, STILL_OPEN, WRONG_QUESTION)


def linked_statements(store=None, regions_path=None) -> dict:
    """need_id -> statements ingested for that need (core.knowledge records carry need_id)."""
    from core import knowledge as kn
    idx = kn.region_index(regions_path)
    out: dict = {}
    for r in kn.statements(store):
        if r.get("need_id"):
            out.setdefault(r["need_id"], []).append({"type": "statement", "text": r.get("sentence"), "id": r.get("id"),
                                                     "linked": True, "region": kn.region_of(r, idx)})
    for v in out.values():                       # main before furniture (C-BRAIN-1 3b); nothing removed
        v.sort(key=lambda x: kn.REGION_ORDER.get(x.get("region"), 1))
    return out


def review(think: Optional[Callable] = None, paths=None, k: int = 5, read: Optional[Callable] = None,
           linked: Optional[dict] = None) -> dict:
    """TEXT C, ONE call per question (C-BRAIN-1 2c), for every open parent and every
    open need that has been searched. Shown: what was fetched for the need first,
    then what the store returns for its question, k items in all. Code records the
    verdict and never overrules it. STILL_OPEN with a narrower question creates a
    CHILD (or a REPEAT); an UNREADABLE reply leaves the need as it was."""
    from core import brain_texts as T
    from core import knowledge as kn
    read = read or (lambda q, kk: kn.read(q, k=kk))
    doc = load_needs(paths)
    mine = [n for n in doc.get("needs", []) if n.get("origin") == "brain" and n.get("status") in (OPEN, STILL_OPEN)
            and (_is_parent(n) or n.get("searched", 0) > 0)]
    if not mine:
        return {"shown": 0, "verdicts": [], "calls": [], "items": {}}
    linked = linked if linked is not None else linked_statements()
    calls, recorded, shown_items, t0 = [], [], {}, time.time()
    for n in mine:
        own = (linked.get(n["id"]) or [])[:k]
        items = own + [it for it in read(n["question"], k) if it.get("id") not in {o.get("id") for o in own}][:k - len(own)]
        shown_items[n["id"]] = items
        _append(_p(paths, "ledger"), {"event": "SHOWN", "ts": _now(), "need_id": n["id"], "items": len(items)})
        lines = "\n".join(f'- "{str(it.get("text"))[:300]}"' for it in items) or "(nothing came back)"
        prompt = T.TEXT_C.format(question=n["question"], items=lines)
        try:
            r = (think or _think)(prompt, "", T.SCHEMA_C)
        except Exception as exc:                                         # noqa: BLE001
            r = {"unreadable": f"{type(exc).__name__}: {exc}", "raw": None}
        d, raw, why = bound(r, T.SCHEMA_C)
        call = {"need_id": n["id"], "role": n.get("role"), "question": n["question"], "shown": lines, "raw": raw,
                "sec": (r or {}).get("sec")}
        calls.append(call)
        if d is None:
            unreadable("review", why, raw, paths, need_id=n["id"])
            call["unreadable"] = why
            recorded.append({"id": n["id"], "verdict": None, "recorded": False, "why_not": why})
            continue
        verdict = d["verdict"]
        n.setdefault("verdicts", []).append({"utc": _now(), "verdict": verdict, "why": d.get("why"),
                                             "narrower_question": d.get("narrower_question")})
        n["status"] = verdict
        _append(_p(paths, "ledger"), {"event": verdict, "ts": _now(), "need_id": n["id"], "why": d.get("why")})
        call["verdict"] = verdict
        nq = d.get("narrower_question")
        if verdict == STILL_OPEN and isinstance(nq, str) and nq.strip():
            ch = add_child(doc, n, nq, paths)
            call["child"] = ch["id"] if ch else None
            call["repeat"] = ch is None
        recorded.append({"id": n["id"], "verdict": verdict, "recorded": True})
    _save_needs(doc, paths)
    return {"shown": len(mine), "verdicts": recorded, "calls": calls, "items": shown_items,
            "sec": round(time.time() - t0, 1)}



# ── the guard: never while the model is someone else's ──────────────────────
def model_busy() -> Optional[str]:
    """Why the model step must be skipped now, or None."""
    from core import model_window as mw
    if mw.in_cycle():
        return "this process is inside a cycle"
    try:
        from scripts.micro_cycle import big_cycle_running
        running, why = big_cycle_running()
        if running:
            return why
    except Exception as exc:                                         # noqa: BLE001
        return f"cycle liveness could not be checked ({type(exc).__name__}) — refusing"
    if _read(mw.STATE, {}).get("open"):
        return "the 8b model window is open"
    return None


def _live_space() -> list:
    from core import space as sp
    sp.build()
    return sp.derive()["expressions"]


def run(think: Optional[Callable] = None, paths=None, busy: Optional[Callable] = None,
        read: Optional[Callable] = None, space_run: Optional[Callable] = None, linked: Optional[dict] = None) -> dict:
    """One cognition step: old needs get their role; the brain judges what came back
    (review, TEXT C per question); the space is rebuilt and derived; a new briefing,
    and the needs QUESTION only for the sub-goals with no open parent (2d).
    core.space.SpaceEngineFailed propagates: the step stops and says so."""
    from core import space as sp
    why = (busy or model_busy)()
    adopt_roles(paths)
    rv = None if why else review(think, paths, read=read, linked=linked)
    derived = (space_run or _live_space)()
    engine = sp.needs_from(derived)
    b = briefing(paths, derived)
    if why:
        _append(_p(paths, "log"), {"event": "MODEL_SKIPPED", "utc": _now(), "why": why, "briefing_sha256": b["sha256"]})
        _append(_p(paths, "ledger"), {"event": "MODEL_SKIPPED", "ts": _now(), "origin": "brain", "why": why})
        res = emit(b, {"raw": None, "parsed": [], "error": f"model step skipped: {why}"}, paths, engine)
        return {"briefing": b, "reply": None, "review": None, "skipped": why, **res}
    reply, free = ask_free(b, think, paths)
    return {"briefing": b, "reply": reply, "review": rv, "derived": len(derived), "free": free,
            **emit(b, reply, paths, engine, free)}


def ask_free(b: dict, think: Optional[Callable] = None, paths=None) -> tuple:
    """-> (reply or None, free sub-goals). None and ASK_SKIPPED when every sub-goal
    has an open parent: the question is not asked at all."""
    free = free_subgoals(b["facts"]["subgoals"], paths)
    if not free:
        _append(_p(paths, "ledger"), {"event": "ASK_SKIPPED", "ts": _now(), "origin": "brain",
                                      "why": "every sub-goal has an open parent"})
        return None, free
    return ask(b, think, free), free


def selftest() -> dict:
    res = {"integrations": {}}
    for k in ("grounded",):
        res["integrations"][str(PATHS[k].relative_to(REPO))] = "LIVE" if PATHS[k].exists() else "INERT (missing)"
    res["integrations"]["forward rows"] = f"LIVE ({len(glob.glob(PATHS['forward_glob']))})"
    res["integrations"]["memory/observation_log.jsonl"] = "LIVE" if PATHS["obs_log"].exists() else "INERT (nothing registered yet)"
    res["integrations"]["memory/brain_needs.json"] = "LIVE" if PATHS["needs"].exists() else "INERT (never emitted)"
    try:
        from core import brain
        res["integrations"][f"model {MODEL}"] = "LIVE" if MODEL in brain.models() else "INERT (not installed)"
    except Exception as exc:                                         # noqa: BLE001
        res["integrations"][f"model {MODEL}"] = f"INERT ({type(exc).__name__})"
    res["integrations"]["searcher for brain and engine needs"] = (
        "LIVE (scripts/openclaw_search.py)" if (REPO / "scripts" / "openclaw_search.py").exists() else "INERT")
    res["ok"] = True
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
        sys.exit(0)
    if "--briefing" in sys.argv:
        print(briefing({**PATHS, "briefings": Path(__import__("tempfile").gettempdir()) / "briefing_preview.jsonl"})["text"])
        sys.exit(0)
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != "briefing"}, indent=1, ensure_ascii=False, default=str))
