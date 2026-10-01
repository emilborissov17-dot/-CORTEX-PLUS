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


def contradictions(paths=None) -> list:
    """Measurement atoms with the same key, place and period and different
    values, both sources named."""
    from core import atoms as at
    groups: dict = {}
    for a in at.read(root=_p(paths, "atoms_root")):
        if a.get("period") is None:
            continue
        groups.setdefault((a.get("key"), a.get("place"), a.get("period")), []).append(a)
    out = []
    for (key, place, period), g in sorted(groups.items(), key=lambda kv: str(kv[0])):
        # two SOURCES disagreeing; one source moving inside the period is an
        # update (the observation log's CHANGED), not a contradiction
        pair = next(((a, b) for i, a in enumerate(g) for b in g[i + 1:]
                     if a.get("value") != b.get("value") and a.get("source_id") != b.get("source_id")), None)
        if pair is None:
            continue
        (a1, a2) = pair
        v1, v2 = a1.get("value"), a2.get("value")
        out.append({"key": key, "place": place, "period": period, "value_1": v1, "source_1": a1.get("source_id"),
                    "value_2": v2, "source_2": a2.get("source_id")})
    return out


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
def briefing(paths=None) -> dict:
    prev = load_needs(paths)
    sg, top, con, fwd = subgoals(), grounded_top(paths), contradictions(paths), forward_rows(paths)
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
    T.append("\nCONTRADICTIONS (same key, place, period; different values):" + ("" if con else " none"))
    for c in con:
        T.append(f"- {c['key']} {c['place']} {c['period']}: {c['value_1']} ({c['source_1']}) vs "
                 f"{c['value_2']} ({c['source_2']})")
        M.append(f"(contradiction {_m(c['key'])} {_m(c['place'])} {_m(c['period'])} {_m(c['value_1'])} "
                 f"{_m(c['source_1'])} {_m(c['value_2'])} {_m(c['source_2'])})")
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
    facts_text = "\n".join(T)      # the copy check compares against the FACTS, not the brain's own past needs
    T.append("\nYOUR PREVIOUS NEEDS AND WHAT HAPPENED:" + ("" if mine else " none yet"))
    for n in mine[-10:]:
        T.append(f"- [{n['status']}] {n['question']} (searched {n.get('searched', 0)} time(s), "
                 f"gained {n.get('gained_statements', 0)} statement(s))")
        M.append(f"(prior-need {_m(n['id'])} {_m(n['question'])} {_m(n['status'])})")
    text = "\n".join(T)
    metta = "\n".join(M)
    sha = hashlib.sha256((text + "\n" + metta).encode("utf-8")).hexdigest()
    b = {"utc": _now(), "sha256": sha, "text": text, "facts_text": facts_text, "metta": metta,
         "facts": {"subgoals": sg, "grounded": top, "contradictions": con, "forward": fwd,
                   "changed": len(ch), "prior_needs": len(mine)}}
    _append(_p(paths, "briefings"), b)
    return b


# ── 2. ask ──────────────────────────────────────────────────────────────────
QUESTION = (
    "Read the briefing. What do YOU need to know next, and why? State up to 5 needs in "
    "your own words. Answer ONLY with JSON of this shape:\n"
    '{"needs": [{"question": "<what you need to know, in your own words>", '
    '"why_subgoal": "<exactly one of the five sub-goal names>", '
    '"about": {"place": <string or null>, "actor": <string or null>, "period": <string or null>}, '
    '"kind": "FIND | VERIFY | EXPLAIN", '
    '"would_change": "<what you would do differently if it were answered>"}]}')


def _think(question: str, evidence: str) -> dict:
    from core import brain
    return brain.think("what I need to know", question, evidence=evidence, schema=None,
                       model_override=MODEL, kind="brain_needs", lean=False)


def ask(b: dict, think: Optional[Callable] = None) -> dict:
    """-> {"raw": text or None, "parsed": list or None, "model", "sec"}."""
    t0 = time.time()
    try:
        r = (think or _think)(QUESTION, b["text"])
    except Exception as exc:                                         # noqa: BLE001
        return {"raw": None, "parsed": None, "error": f"{type(exc).__name__}: {exc}", "sec": round(time.time() - t0, 1)}
    raw = (r or {}).get("text")
    out = {"raw": raw, "parsed": None, "model": (r or {}).get("model"), "sec": (r or {}).get("sec", round(time.time() - t0, 1))}
    if raw:
        out["parsed"] = parse_reply(raw)
    return out


def parse_reply(raw: str):
    """The needs list from a reply, or None. Never invents an entry."""
    s = raw.strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = s.find(opener), s.rfind(closer)
        if i < 0 or j <= i:
            continue
        try:
            d = json.loads(s[i:j + 1])
        except ValueError:
            continue
        lst = d.get("needs") if isinstance(d, dict) else d
        if isinstance(lst, list):
            return lst
    return None


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


def _id(origin: str, text: str) -> str:
    return ("BN-" if origin == "brain" else "EN-") + hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()[:10]


# ── 4. engine needs ─────────────────────────────────────────────────────────
def engine_needs(b: dict) -> list:
    out = []
    for c in b["facts"]["contradictions"]:
        q = (f"Verify {c['key']} for {c['place']}, period {c['period']}: {c['value_1']} ({c['source_1']}) vs "
             f"{c['value_2']} ({c['source_2']}), from a source independent of both")
        out.append({"question": q, "kind": "VERIFY", "why_subgoal": None,
                    "source_ids": [s for s in (c["source_1"], c["source_2"]) if s],
                    "about": {"place": c["place"], "actor": None, "period": c["period"]}, "would_change": None})
    for f in b["facts"]["forward"]:
        place = ", ".join(f["place"]) if isinstance(f["place"], list) else f["place"]
        q = f"Find current reports on {f['actor']} in {place} for the period {time.strftime('%B %Y')}"
        out.append({"question": q, "kind": "FIND", "why_subgoal": None, "row": f["row"],
                    "about": {"place": place, "actor": f["actor"], "period": time.strftime("%Y-%m")},
                    "would_change": None})
    return out


# ── 5. emit ─────────────────────────────────────────────────────────────────
def emit(b: dict, reply: dict, paths=None) -> dict:
    doc = load_needs(paths)
    needs = doc.get("needs", [])
    by_id = {n["id"]: n for n in needs}
    five = b["facts"]["subgoals"]
    satisfied = {_norm(n["question"]) for n in needs if n.get("status") == SATISFIED}
    accepted, refused, silence, reopened = [], [], None, []
    if reply.get("parsed") is None or (isinstance(reply.get("parsed"), list) and not reply["parsed"]):
        silence = {"utc": _now(), "briefing_sha256": b["sha256"], "raw": reply.get("raw"),
                   "error": reply.get("error"), "why": "empty reply" if not reply.get("raw") else
                   ("no needs in the reply" if reply.get("parsed") == [] else "reply is not parseable JSON")}
        _append(_p(paths, "log"), {"event": SILENCE, **silence})
    else:
        for i, n in enumerate(reply["parsed"]):
            why = "over the limit of 5 needs" if i >= MAX_NEEDS else check_form(n, b["facts_text"], satisfied, five)
            if why:
                row = {"utc": _now(), "briefing_sha256": b["sha256"], "reason": why, "need": n}
                refused.append(row)
                _append(_p(paths, "refused"), row)
                continue
            nid = _id("brain", n["question"])
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
                   "status": OPEN, **{k: n.get(k) for k in ("question", "why_subgoal", "about", "kind", "would_change")}}
            by_id[nid] = rec
            accepted.append(rec)
    for n in engine_needs(b):
        nid = _id("engine", n["question"])
        if nid in by_id:
            continue
        rec = {"id": nid, "origin": "engine", "briefing_sha256": b["sha256"], "created_utc": _now(),
               "status": OPEN, **n}
        by_id[nid] = rec
        accepted.append(rec)
    ordered = ([n for n in by_id.values() if n["origin"] == "brain"] +
               [n for n in by_id.values() if n["origin"] == "engine"])
    out = {"briefing_sha256": b["sha256"], "briefing_utc": b["utc"], "silence": silence, "needs": ordered}
    _save_needs(out, paths)
    for r in accepted:
        _append(_p(paths, "ledger"), {"event": "EMITTED", "ts": _now(), "need_id": r["id"], "origin": r["origin"],
                                      "question": r["question"]})
    for r in reopened:
        _append(_p(paths, "ledger"), {"event": "REOPENED", "ts": _now(), "need_id": r["id"], "was": r["reopened"][-1]["was"]})
    return {"accepted": accepted, "refused": refused, "reopened": reopened, "silence": silence, "open": sum(
        1 for n in ordered if n["status"] in (OPEN, STILL_OPEN))}


def _save_needs(doc: dict, paths=None) -> None:
    Path(_p(paths, "needs")).parent.mkdir(parents=True, exist_ok=True)
    Path(_p(paths, "needs")).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")


def mark_served(need_id: str, query: str, hits: int, fetched: int, gained: int, paths=None) -> None:
    """The finder's account on the need itself; the status is NOT touched."""
    doc = load_needs(paths)
    for n in doc.get("needs", []):
        if n["id"] == need_id:
            n["searched"] = n.get("searched", 0) + 1
            n["last_query"] = query
            n["last_hits"], n["last_fetched"] = hits, fetched
            n["gained_statements"] = n.get("gained_statements", 0) + gained
    _save_needs(doc, paths)


# ── 6. the brain is told what came back, and judges its own needs ───────────
VERDICTS = (SATISFIED, STILL_OPEN, WRONG_QUESTION)
REVIEW_QUESTION = (
    "Earlier you said you needed to know the things below. For each, the store now "
    "returns the items listed under it. Judge each of YOUR needs. Answer ONLY with JSON:\n"
    '{"verdicts": [{"id": "<the need id>", "verdict": "SATISFIED | STILL_OPEN | WRONG_QUESTION", '
    '"question": "<if STILL_OPEN: the question reformulated in your words, else null>", '
    '"why": "<one sentence>"}]}')


def review(think: Optional[Callable] = None, paths=None, k: int = 5, read: Optional[Callable] = None) -> dict:
    """Show the brain, for each of its open needs that has been searched, the top k
    items core.knowledge returns for its question; record its verdict per need.
    Code records the verdict and never overrules it; an unparseable reply or a
    verdict outside the three leaves the need as it was, and says so."""
    from core import knowledge as kn
    read = read or (lambda q, kk: kn.read(q, k=kk))
    doc = load_needs(paths)
    mine = [n for n in doc.get("needs", []) if n.get("origin") == "brain"
            and n.get("status") in (OPEN, STILL_OPEN) and n.get("searched", 0) > 0]
    if not mine:
        return {"shown": 0, "verdicts": [], "silence": None}
    blocks = []
    for n in mine:
        items = read(n["question"], k)
        _append(_p(paths, "ledger"), {"event": "SHOWN", "ts": _now(), "need_id": n["id"], "items": len(items)})
        lines = [f"  {i + 1}. [{it.get('type')}] {str(it.get('text'))[:300]}" for i, it in enumerate(items)]
        blocks.append(f"NEED {n['id']}: {n['question']}\n" + ("\n".join(lines) if lines else "  (nothing returned)"))
    shown = "\n\n".join(blocks)
    t0 = time.time()
    try:
        r = (think or _think)(REVIEW_QUESTION, shown)
    except Exception as exc:                                         # noqa: BLE001
        r = {"text": None, "error": f"{type(exc).__name__}: {exc}"}
    raw = (r or {}).get("text")
    parsed = None
    if raw:
        s = raw.strip()
        i, j = s.find("{"), s.rfind("}")
        try:
            d = json.loads(s[i:j + 1]) if i >= 0 and j > i else None
            parsed = d.get("verdicts") if isinstance(d, dict) else None
        except ValueError:
            parsed = None
    sec = (r or {}).get("sec", round(time.time() - t0, 1))
    if not isinstance(parsed, list):
        sil = {"utc": _now(), "raw": raw, "why": "empty reply" if not raw else "reply is not parseable JSON"}
        _append(_p(paths, "log"), {"event": "REVIEW_SILENCE", **sil})
        return {"shown": len(mine), "shown_text": shown, "raw": raw, "verdicts": [], "silence": sil, "sec": sec}
    by_id = {n["id"]: n for n in doc["needs"]}
    recorded = []
    for v in parsed:
        if not isinstance(v, dict):
            continue
        nid, verdict = v.get("id"), v.get("verdict")
        n = by_id.get(nid)
        if n is None or n not in mine or verdict not in VERDICTS:
            recorded.append({"id": nid, "verdict": verdict, "recorded": False,
                             "why_not": "unknown need id" if n is None or n not in mine else "verdict not one of three"})
            continue
        n.setdefault("verdicts", []).append({"utc": _now(), "verdict": verdict, "why": v.get("why")})
        n["status"] = verdict
        if verdict == STILL_OPEN and isinstance(v.get("question"), str) and v["question"].strip():
            n.setdefault("questions", [n["question"]]).append(v["question"].strip())
            n["question"] = v["question"].strip()
        _append(_p(paths, "ledger"), {"event": verdict, "ts": _now(), "need_id": nid, "why": v.get("why")})
        recorded.append({"id": nid, "verdict": verdict, "recorded": True})
    _save_needs(doc, paths)
    return {"shown": len(mine), "shown_text": shown, "raw": raw, "verdicts": recorded, "silence": None, "sec": sec}


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


def run(think: Optional[Callable] = None, paths=None, busy: Optional[Callable] = None,
        read: Optional[Callable] = None) -> dict:
    """One cognition step: the brain judges what came back for its searched needs
    (review), then a new briefing and its new needs."""
    why = (busy or model_busy)()
    rv = None if why else review(think, paths, read=read)
    b = briefing(paths)
    if why:
        _append(_p(paths, "log"), {"event": "MODEL_SKIPPED", "utc": _now(), "why": why, "briefing_sha256": b["sha256"]})
        res = emit(b, {"raw": None, "parsed": [], "error": f"model step skipped: {why}"}, paths)
        return {"briefing": b, "reply": None, "review": None, "skipped": why, **res}
    reply = ask(b, think)
    return {"briefing": b, "reply": reply, "review": rv, **emit(b, reply, paths)}


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
    finder = (REPO / "scripts" / "openclaw_finder.py").read_text(encoding="utf-8")
    res["integrations"]["finder serves brain needs"] = "LIVE" if "brain_needs" in finder else "INERT"
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
