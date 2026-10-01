# -*- coding: utf-8 -*-
"""core/agent_profiles.py — one searcher profile per taxonomy category (C-TURN-1
Part 4e; Emil R30: "one main, agents per category, each with its own settings").

config/agents/<category>.json   generated from config/taxonomy.json: name,
                                subcategories, the OpenClaw browser profile and
                                agent it is served under, skills, plugins, model.
memory/agents/<category>.json   what that category has LEARNED: hosts and queries
                                that brought statements, hosts that showed a
                                CAPTCHA or refused. Learned, never a fixed list —
                                nothing in it stops a search; search always runs.

category_of() says whose profile serves a need or a maintenance cell.

    venv\\Scripts\\python.exe -m core.agent_profiles --generate
    venv\\Scripts\\python.exe -m core.agent_profiles --selftest
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "agents"
LEARNED = REPO / "memory" / "agents"
MAIN = "main"
SEARCHER_MODEL = ("none: direct browser calls through the OpenClaw gateway "
                  "(C-TURN-1 4b, R33: the cheapest option that finished)")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def generate(out_dir=None, tree: Optional[dict] = None) -> list:
    from core import taxonomy as tx
    tree = tree or tx.load()
    d = Path(out_dir or CONFIG)
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for dom in tree["domains"]:
        for c in dom.get("categories") or []:
            cid = c["id"]
            prof = {"category": cid, "name": c.get("name_en"), "domain": dom["id"], "subgoal": c.get("subgoal"),
                    "subcategories": [{"id": s["id"], "name": s.get("name_en")} for s in c.get("subcategories") or []],
                    "openclaw_agent": None, "browser_profile": "openclaw",
                    "searcher_model": SEARCHER_MODEL, "skills": [], "plugins": [],
                    "learned": f"memory/agents/{cid}.json",
                    "_generated": f"from config/taxonomy.json by core/agent_profiles.py; edit the agent fields only"}
            p = d / f"{cid}.json"
            if p.exists():                                       # keep the agent/browser fields set by hand
                old = json.loads(p.read_text(encoding="utf-8"))
                for k in ("openclaw_agent", "browser_profile", "skills", "plugins"):
                    prof[k] = old.get(k, prof[k])
            p.write_text(json.dumps(prof, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            written.append(cid)
    return written


def load(cat: str, cfg_dir=None) -> dict:
    p = Path(cfg_dir or CONFIG) / f"{cat}.json"
    if cat == MAIN or not p.exists():
        return {"category": MAIN, "browser_profile": "openclaw", "openclaw_agent": None, "learned": None}
    return json.loads(p.read_text(encoding="utf-8"))


def learn(cat: str, result: dict, learned_dir=None) -> dict:
    """Fold one served need's outcome into the category's learned memory."""
    p = Path(learned_dir or LEARNED) / f"{cat}.json"
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {"category": cat, "hosts_gained": {}, "queries_gained": {}, "hosts_captcha": {}, "attempts": 0}
    m["attempts"] = m.get("attempts", 0) + 1
    for h in result.get("hosts_gained") or []:
        m["hosts_gained"][h] = m["hosts_gained"].get(h, 0) + 1
    if result.get("statements_added"):
        q = result.get("query") or ""
        m["queries_gained"][q] = m["queries_gained"].get(q, 0) + result["statements_added"]
    for h in result.get("hosts_captcha") or []:
        m["hosts_captcha"][h] = m["hosts_captcha"].get(h, 0) + 1
    m["updated_utc"] = _now()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    return m


def category_of(item: dict, atom_sub: Optional[dict] = None) -> str:
    """A maintenance cell: its subcategory's category. An engine need: the
    category of its premises (a forward row -> B1, where the commitments live; an
    atom -> its subcategory's category). A brain need names no category: MAIN."""
    cell = item.get("cell") or ""
    if cell.startswith("sub:"):
        return cell[4:].split(".")[0]
    for prem in item.get("premises") or []:
        if re.fullmatch(r"F-\d+", str(prem)):
            return "B1"
        sub = (atom_sub or {}).get(prem)
        if sub and sub != "unplaced":
            return sub.split(".")[0]
    return MAIN


def selftest() -> dict:
    n = len(list(CONFIG.glob("*.json"))) if CONFIG.exists() else 0
    res = {"integrations": {"config/agents/": f"LIVE ({n} profiles)" if n else "INERT (not generated)",
                            "memory/agents/": f"LIVE ({len(list(LEARNED.glob('*.json')))} learned)" if LEARNED.exists()
                            else "INERT (nothing learned yet)"}}
    b1 = load("B1")
    res["integrations"]["B1 OpenClaw agent"] = b1.get("openclaw_agent") or "INERT (not created)"
    res["ok"] = True
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
        sys.exit(0)
    if "--generate" in sys.argv:
        print(generate())
        sys.exit(0)
    print(__doc__)
