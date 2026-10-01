# -*- coding: utf-8 -*-
"""core/space.py — what the brain may use, written as expressions; rules derive
from it (C-TURN-1 Part 1; Emil R23/R28: "Why is the symbolic idea still not built?").

build()   writes memory/space/base.metta from code, NO MODEL, rebuilt whole each
          brain turn. Every expression is preceded by a provenance comment
          (; from <file> <row>):
            (subgoal <id> "<text>") (domain <id>) (category <id> <domain>)
            (subcategory <id> <category>) (serves <category> <subgoal>)
            (axis-serves <axis> <subgoal>)                       config/target_config.json
            (obs <atom> <sub> <key> <place> <period> <value> <unit> <source>)   core.atoms.read
            (source-class <source> <class>) (independent-src <source>)
            (seen <atom> <times> <last_seen_day>)
            (period-age <atom> "day"|"month" <days>) (period-year <atom> <year>) (this-year <y>)
            (changed <key> <place> <from> <to> <day>) (unchanged <key> <place> <since_day>)
                                                                memory/observation_log.jsonl
            (gap <axis> <need> <score>)              memory/orchestration_grounded_latest.json
            (commitment <row> <actor> <from> <to> <metric> <kept_if>) (commitment-place <row> <place>)
            (commitment-witness <row> <verdict>)     experiments/institution/forward + memory/metta_forward_*
            (need <id> <origin> <kind> <subgoal> <status>)           memory/brain_needs.json
            (statement <id> <subcategory> <host>)    labelled statements only; the text stays in the store
derive()  runs base.metta + config/space_rules.metta through the repo's hyperon
          (venv312_metta). Derivations go to memory/space/derived.metta. If hyperon
          does not run, SpaceEngineFailed is RAISED: there is no Python fallback
          that agrees with itself.
needs_from()  the engine's needs, from the derived (need-derived ...) expressions.

    venv\\Scripts\\python.exe -m core.space            # build + derive, print the counts
    venv\\Scripts\\python.exe -m core.space --selftest
"""
from __future__ import annotations

import glob
import json
import math
import re
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
MEM = REPO / "memory"
PATHS = {
    "dir": MEM / "space",
    "rules": REPO / "config" / "space_rules.metta",
    "atoms_root": None,
    "obs_log": MEM / "observation_log.jsonl",
    "grounded": MEM / "orchestration_grounded_latest.json",
    "forward_glob": str(REPO / "experiments" / "institution" / "forward" / "F-*.json"),
    "witness_glob": str(MEM / "metta_forward_F-*.json"),
    "needs": MEM / "brain_needs.json",
    "labels": MEM / "knowledge" / "labels.json",
    "store": MEM / "statements.jsonl",
    "target_config": REPO / "config" / "target_config.json",
    "proposed": MEM / "space" / "proposed.metta",
}
SIDECAR_PY = REPO / "venv312_metta" / "Scripts" / "python.exe"
DERIVED_HEADS = ("contradiction", "unverified", "stale", "uncovered", "lacks-evidence", "need-derived")


class SpaceEngineFailed(RuntimeError):
    """hyperon did not run; the turn stops and says so."""


class PathMissing(KeyError):
    pass


def _p(paths, k):
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


def lit(v) -> str:
    """A MeTTa literal: numbers as numbers, everything else a string."""
    if isinstance(v, bool) or v is None:
        return '"none"' if v is None else ('"true"' if v else '"false"')
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return '"non-finite"'
        return repr(float(v)) if isinstance(v, float) else str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def atom_id(a: dict) -> str:
    return "a-" + str(a.get("card_key") or "")[:12]


# ── build ───────────────────────────────────────────────────────────────────
def build(paths=None, today: Optional[date] = None, tree: Optional[dict] = None) -> dict:
    from core import atoms as at
    from core import taxonomy as tx
    today = today or datetime.now(timezone.utc).date()
    t0 = time.time()
    L: list = []

    def add(expr: str, src: str):
        L.append(f"; from {src}")
        L.append(expr)

    tree = tree or tx.load()
    tc = _read(_p(paths, "target_config"), {})
    for sg, axes in sorted((k, v) for k, v in tc.items() if not k.startswith("_") and isinstance(v, dict)):
        add(f"(subgoal {lit(sg)} {lit(sg.replace('_', ' ').lower())})", "config/target_config.json " + sg)
        for ax in sorted(a for a in axes if not a.startswith("_")):
            add(f"(axis-serves {lit(ax)} {lit(sg)})", f"config/target_config.json {sg}.{ax}")
    for d in tree["domains"]:
        add(f"(domain {lit(d['id'])})", "config/taxonomy.json " + d["id"])
        for c in d.get("categories") or []:
            add(f"(category {lit(c['id'])} {lit(d['id'])})", "config/taxonomy.json " + c["id"])
            if c.get("subgoal"):
                add(f"(serves {lit(c['id'])} {lit(c['subgoal'])})", "config/taxonomy.json " + c["id"])
            for s in c.get("subcategories") or []:
                add(f"(subcategory {lit(s['id'])} {lit(c['id'])})", "config/taxonomy.json " + s["id"])
    add(f"(this-year {today.year})", "the clock")

    classes = {}
    for a in at.read(root=_p(paths, "atoms_root")):
        aid, src = atom_id(a), a.get("source_id") or "none"
        add(f"(obs {lit(aid)} {lit(a.get('subcategory') or 'unplaced')} {lit(a.get('key'))} {lit(a.get('place'))} "
            f"{lit(a.get('period'))} {lit(a.get('value'))} {lit(a.get('unit'))} {lit(src)})",
            f"atoms/ card_key {a.get('card_key')}")
        classes.setdefault(src, a.get("source_class") or "unknown")
        add(f"(seen {lit(aid)} {int(a.get('times_seen') or 1)} {lit(str(a.get('last_seen_utc') or '')[:10])})",
            f"atoms/ card_key {a.get('card_key')}")
        g = at.period_granularity(a.get("period"))
        p = str(a.get("period") or "")
        try:
            if g == "day":
                add(f"(period-age {lit(aid)} \"day\" {(today - date.fromisoformat(p[:10])).days})", "period of " + aid)
            elif g == "month":
                import calendar
                y, m = int(p[:4]), int(p[5:7])
                end = date(y, m, calendar.monthrange(y, m)[1])
                add(f"(period-age {lit(aid)} \"month\" {(today - end).days})", "period of " + aid)
            elif g == "year":
                add(f"(period-year {lit(aid)} {int(p)})", "period of " + aid)
        except ValueError:
            pass
    for src, cls in sorted(classes.items()):
        add(f"(source-class {lit(src)} {lit(cls)})", "atoms/ source_class")
        if cls in ("independent", "adversarial"):
            add(f"(independent-src {lit(src)})", "atoms/ source_class")

    for i, r in enumerate(_jsonl(_p(paths, "obs_log"))):
        ident = r.get("identity") or []
        if len(ident) < 5:
            continue
        if r.get("verdict") == "CHANGED":
            cf = r.get("changed_from") or {}
            add(f"(changed {lit(ident[1])} {lit(ident[2])} {lit(cf.get('value'))} {lit(ident[4])} "
                f"{lit(str(r.get('ts'))[:10])})", f"memory/observation_log.jsonl row {i}")
        elif r.get("verdict") == "UNCHANGED":
            add(f"(unchanged {lit(ident[1])} {lit(ident[2])} {lit(str(r.get('since'))[:10])})",
                f"memory/observation_log.jsonl row {i}")

    for i, r in enumerate((_read(_p(paths, "grounded"), {}) or {}).get("ranking") or []):
        if isinstance(r.get("need"), (int, float)):
            add(f"(gap {lit(r.get('axis'))} {lit(float(r['need']))} {lit(r.get('score'))})",
                f"memory/orchestration_grounded_latest.json ranking[{i}]")

    for f in sorted(glob.glob(_p(paths, "forward_glob"))):
        if not re.fullmatch(r"F-\d+\.json", Path(f).name):
            continue
        d = _read(f, {})
        if not d.get("id") or d.get("outcome") or d.get("resolved"):
            continue
        c = d.get("condition") or {}
        rel = Path(f).relative_to(REPO).as_posix() if Path(f).is_absolute() and REPO in Path(f).parents else Path(f).name
        add(f"(commitment {lit(d['id'])} {lit(c.get('dyad_name'))} {lit(c.get('date_start_from'))} "
            f"{lit(c.get('date_start_to'))} {lit(c.get('metric'))} {lit(c.get('kept_if'))})", rel)
        places = c.get("adm_1") if isinstance(c.get("adm_1"), list) else [c.get("adm_1") or "ALL"]
        for pl in places:
            add(f"(commitment-place {lit(d['id'])} {lit(pl)})", rel)
    for f in sorted(glob.glob(_p(paths, "witness_glob"))):
        w = _read(f, {})
        if w.get("row_id"):
            add(f"(commitment-witness {lit(w['row_id'])} {lit(w.get('verdict'))})", Path(f).name)

    for n in (_read(_p(paths, "needs"), {}) or {}).get("needs", []):
        add(f"(need {lit(n['id'])} {lit(n.get('origin'))} {lit(n.get('kind'))} {lit(n.get('why_subgoal'))} "
            f"{lit(n.get('status'))})", "memory/brain_needs.json " + n["id"])

    labels = ((_read(_p(paths, "labels"), {}) or {}).get("labels") or {})
    placed = {i: l for i, l in labels.items() if l.get("subcategory") not in (None, "unplaced", "pending_vector")}
    if placed:
        hosts = {}
        for r in _jsonl(_p(paths, "store")):
            if r.get("id") in placed:
                hosts[r["id"]] = r.get("host") or ""
        for i, l in sorted(placed.items()):
            add(f"(statement {lit(i)} {lit(l['subcategory'])} {lit(hosts.get(i, ''))})", "memory/knowledge/labels.json " + i)

    text = "\n".join(L) + "\n"
    d = Path(_p(paths, "dir"))
    d.mkdir(parents=True, exist_ok=True)
    (d / "base.metta").write_text(text, encoding="utf-8")
    n = sum(1 for l in L if not l.startswith(";"))
    return {"expressions": n, "seconds": round(time.time() - t0, 2), "path": str(d / "base.metta")}


# ── the engine ──────────────────────────────────────────────────────────────
_WORKER = (
    "import json,sys\n"
    "from hyperon import MeTTa\n"
    "prog = sys.stdin.read()\n"
    "try:\n"
    "    res = MeTTa().run(prog)\n"
    "except Exception as e:\n"
    "    print(json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'})); sys.exit(0)\n"
    "print(json.dumps({'ok': True, 'raw': [[str(a) for a in r] for r in res]}))\n")


def hyperon_engine(program: str, timeout: int = 300) -> list:
    """Every result expression, as text. RAISES SpaceEngineFailed."""
    if not SIDECAR_PY.exists():
        raise SpaceEngineFailed(f"hyperon sidecar not found at {SIDECAR_PY}")
    try:
        proc = subprocess.run([str(SIDECAR_PY), "-c", _WORKER], input=program, capture_output=True,
                              text=True, timeout=timeout, encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        raise SpaceEngineFailed(f"hyperon timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise SpaceEngineFailed(f"hyperon exit {proc.returncode}: {proc.stderr.strip()[-300:]}")
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise SpaceEngineFailed(f"hyperon printed no result: {proc.stdout[-200:]!r}") from exc
    if not out.get("ok"):
        raise SpaceEngineFailed(out.get("error") or "hyperon reported failure")
    return [x for r in out["raw"] for x in r]


_TOK = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def parse(expr: str):
    """An s-expression -> nested lists; strings unquoted, numbers as float."""
    toks = _TOK.findall(expr)
    pos = 0

    def one():
        nonlocal pos
        t = toks[pos]
        pos += 1
        if t == "(":
            out = []
            while toks[pos] != ")":
                out.append(one())
            pos += 1
            return out
        if t.startswith('"'):
            return bytes(t[1:-1], "utf-8").decode("unicode_escape") if "\\" in t else t[1:-1]
        try:
            return float(t)
        except ValueError:
            return t
    return one()


def derive(paths=None, engine: Optional[Callable] = None) -> dict:
    d = Path(_p(paths, "dir"))
    base = (d / "base.metta").read_text(encoding="utf-8")
    proposed = Path(_p(paths, "proposed"))
    prop = proposed.read_text(encoding="utf-8") if proposed.exists() else ""
    rules = Path(_p(paths, "rules")).read_text(encoding="utf-8")
    t0 = time.time()
    raw = (engine or hyperon_engine)(base + "\n" + prop + "\n" + rules)
    secs = round(time.time() - t0, 2)
    seen, derived = set(), []
    for e in raw:
        if not e.startswith("("):
            continue
        x = parse(e)
        if not isinstance(x, list) or not x or x[0] not in DERIVED_HEADS:
            continue
        key = _canon(x)
        if key in seen:
            continue
        seen.add(key)
        derived.append(x)
    lines = []
    for x in derived:
        lines.append(f"; rule {x[1] if x[0] == 'need-derived' else x[0]} premises {premises(x)}")
        lines.append(render(x))
    (d / "derived.metta").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # stale goes to MAINTENANCE, not to the brain: the sources of stale atoms are due
    src_of = {}
    for line in base.splitlines():
        if line.startswith("(obs "):
            o = parse(line)
            src_of[o[1]] = o[8]
    stale = sorted({x[1] for x in derived if x[0] == "stale"})
    (d / "stale_for_maintenance.json").write_text(json.dumps(
        {"atoms": stale, "sources": sorted({src_of[a] for a in stale if a in src_of and src_of[a] != "none"})},
        indent=1), encoding="utf-8")
    counts = {}
    for x in derived:
        counts[x[0]] = counts.get(x[0], 0) + 1
    return {"derived": len(derived), "by_rule": counts, "seconds": secs, "expressions": derived}


def _canon(x):
    """contradiction (k p per a b) and (k p per b a) are one."""
    if x[0] == "contradiction":
        return tuple(x[:4]) + tuple(sorted(map(str, x[4:])))
    if x[0] == "need-derived" and len(x) > 2 and x[2] == "contradiction":
        return tuple(x[:6]) + tuple(sorted(map(str, x[6:])))
    return tuple(map(str, x))


def premises(x) -> list:
    return [a for a in x[1:] if isinstance(a, str) and (a.startswith("a-") or re.fullmatch(r"F-\d+", a))]


def render(x) -> str:
    if isinstance(x, list):
        return "(" + " ".join(render(a) for a in x) + ")"
    if isinstance(x, float):
        return repr(x)
    if x in ("VERIFY", "FIND") or x in DERIVED_HEADS or x in ("contradiction", "unverified", "uncovered", "lacks-evidence"):
        return x
    return lit(x)


def needs_from(derived: list) -> list:
    """Engine needs from (need-derived KIND rule ...). The question text is a
    rendering of the expression; the premises travel with the need."""
    out = []
    for x in derived:
        if x[0] != "need-derived":
            continue
        kind, rule, args = x[1], x[2], x[3:]
        if rule == "contradiction":
            k, p, per = args[:3]
            q = f"Verify {k} for {p}, period {per}: two sources disagree — from a source independent of both"
            about = {"place": p, "actor": None, "period": per}
        elif rule == "unverified":
            k, p, per = args[:3]
            q = f"Verify {k} for {p}, period {per}, from an independent source (only a self-reported one holds it)"
            about = {"place": p, "actor": None, "period": per}
        elif rule == "uncovered":
            q = f"Find measurements for the sub-goal {args[0]}: no category that serves it has one"
            about = {"place": None, "actor": None, "period": None}
        elif rule == "lacks-evidence":
            q = f"Find current reports for commitment {args[0]} in {args[1]}"
            about = {"place": args[1], "actor": None, "period": None}
        else:
            q, about = f"{kind} {rule} {' '.join(map(str, args))}", {}
        out.append({"question": q, "kind": kind, "why_subgoal": args[0] if rule == "uncovered" else None,
                    "rule": rule, "premises": premises(x), "expression": render(x), "about": about,
                    "source_ids": [], "would_change": None})
    return out


def selftest() -> dict:
    res = {"integrations": {
        "hyperon sidecar venv312_metta": "LIVE" if SIDECAR_PY.exists() else "INERT (missing)",
        "config/space_rules.metta": "LIVE" if PATHS["rules"].exists() else "INERT (missing)",
        "memory/space/base.metta": "LIVE" if (PATHS["dir"] / "base.metta").exists() else "INERT (never built)",
    }}
    bn = (REPO / "core" / "brain_needs.py").read_text(encoding="utf-8")
    res["integrations"]["brain_needs takes engine needs from the space"] = "LIVE" if "space.needs_from(" in bn else "INERT"
    res["ok"] = True
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
        sys.exit(0)
    b = build()
    d = derive()
    print(json.dumps({"base_expressions": b["expressions"], "build_seconds": b["seconds"], "derived": d["derived"],
                      "by_rule": d["by_rule"], "engine_seconds": d["seconds"]}, indent=1))
