# -*- coding: utf-8 -*-
"""core/needs.py — what the search should look for next, ranked, with NO model
(C-OC-3 Part 3). Rebuilds memory/needs.json on every call.

ORDER
  1. DECLARED needs first: the gaps the composers declared themselves in
     memory/composer_needs.json, selected by the same kinds core/data_scout.py
     drains (slot_unfilled, source_dead, human_sense_request) — a human's
     demand first among them.
     The command (C-OC-3) names "brain_needs" as this tier. No file, producer
     or reader of that name exists in this repo (searched 2026-10-01); the
     composers' declared hunger is the declared tier that does exist.
  2. Then every WORLD subcategory (domain E never), fewest statements +
     measurements first; ties by Maslow level, lowest first (physiological
     before self_actualization); a category with no Maslow level after those.

"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
NEEDS = REPO / "memory" / "needs.json"
COMPOSER_NEEDS = REPO / "memory" / "composer_needs.json"
DECLARED_KINDS = ("human_sense_request", "slot_unfilled", "source_dead")
MASLOW = ("physiological", "safety", "belonging", "esteem", "self_actualization")
SLOT_QUERY = {"anchor_annual": "official annual statistics", "measurement_daily": "daily measurement data",
              "event_daily": "daily event counts", "indirect_proxy": "indicator data"}
_UNITS = re.compile(r"\b(pct|per|usd|ppm|km2|kt|t|n|total|idx|index)\b")


def _words(key: str) -> str:
    return _UNITS.sub("", key.replace("_", " ")).strip()


def declared(path: Optional[Path] = None) -> list:
    try:
        doc = json.loads(Path(path or COMPOSER_NEEDS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for axis, entry in (doc or {}).items():
        for it in (entry or {}).get("items", []):
            if it.get("kind") not in DECLARED_KINDS:
                continue
            axis_words = axis.replace("_REVIEW", "").replace("_", " ").lower()
            out.append({"need_id": f"declared:{axis}:{it.get('slot')}:{it.get('kind')}", "tier": "declared",
                        "axis": axis, "slot": it.get("slot"), "kind": it.get("kind"),
                        "detail": (it.get("detail") or "")[:200],
                        "query": f"{axis_words} {SLOT_QUERY.get(it.get('slot'), 'data')}".strip(),
                        "source_ids": re.findall(r"\b([a-z][a-z0-9_]+:[A-Za-z0-9_.:-]+)", it.get("detail") or "")})
    out.sort(key=lambda n: (DECLARED_KINDS.index(n["kind"]), n["axis"], str(n["slot"])))
    return out


def _maslow_by_category(tree: dict) -> dict:
    out = {}
    for d in tree["domains"]:
        for c in d.get("categories") or []:
            if c.get("maslow_level") in MASLOW:
                out[c["id"]] = MASLOW.index(c["maslow_level"])
    return out


def counts_by_subcategory(labels_path=None, atoms_root=None) -> dict:
    """{sub_id: {"statements": n, "measurements": n}} from core.knowledge.subcategory_counts,
    the one counter coverage uses too. Absent statement labels count as 0 HERE
    (ranking only); the board shows them as MISSING."""
    from core import knowledge as kn
    raw, _present = kn.subcategory_counts(labels_path, atoms_root)
    return {s: {"statements": v["statements"] or 0, "measurements": len(v["measurements"])} for s, v in raw.items()}


def world(counts: dict, tree: Optional[dict] = None) -> list:
    from core import taxonomy as tx
    tree = tree or tx.load()
    mas = _maslow_by_category(tree)
    rows = []
    for s in tx.world_subcategories(tree):
        c = counts.get(s["id"], {"statements": 0, "measurements": 0})
        keys = " ".join(_words(k) for k in s["wanted_keys"][:2])
        rows.append({"need_id": f"world:{s['id']}", "tier": "world", "subcategory": s["id"],
                     "name": s["name_en"], "statements": c["statements"], "measurements": c["measurements"],
                     "maslow": MASLOW[mas[s["category"]]] if s["category"] in mas else None,
                     "query": f"{s['name_en']} {keys} latest data".strip(),
                     "_rank": (c["statements"] + c["measurements"], mas.get(s["category"], len(MASLOW)))})
    rows.sort(key=lambda r: r["_rank"])
    for r in rows:
        r.pop("_rank")
    return rows


def rebuild(out: Optional[Path] = None, composer_path=None, labels_path=None, atoms_root=None,
            tree: Optional[dict] = None) -> dict:
    counts = counts_by_subcategory(labels_path, atoms_root)
    needs = declared(composer_path) + world(counts, tree)
    for i, n in enumerate(needs, 1):
        n["rank"] = i
    doc = {"computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "rule": "declared (composer_needs.json) first; then world subcategories by fewest "
                   "statements+measurements, ties by Maslow level lowest first",
           "statement_labels_present": bool(counts) and any(v["statements"] for v in counts.values()),
           "needs": needs}
    out = Path(out or NEEDS)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return doc


def selftest() -> dict:
    from core import knowledge as kn
    res = {"integrations": {
        "memory/composer_needs.json (declared tier)": "LIVE" if COMPOSER_NEEDS.exists() else "INERT (absent)",
        "brain_needs (named by C-OC-3)": "INERT (no such file, producer or reader in this repo)",
        "statement labels (core.knowledge)": "LIVE" if kn.LABELS.exists() else "INERT (label_all has not run)",
        "memory/needs.json": "LIVE" if NEEDS.exists() else "INERT (never rebuilt)",
    }}
    finder = REPO / "scripts" / "openclaw_finder.py"
    res["integrations"]["finder reads needs"] = (
        "LIVE" if finder.exists() and "needs.rebuild(" in finder.read_text(encoding="utf-8") else "INERT")
    res["ok"] = True
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
        sys.exit(0)
    d = rebuild()
    print(json.dumps({"needs": len(d["needs"]), "top": [n["need_id"] for n in d["needs"][:10]]}, indent=1))
