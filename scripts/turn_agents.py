# -*- coding: utf-8 -*-
"""scripts/turn_agents.py — the agents' turn (C-TURN-1 Part 4f; Emil R31, R32).

Run through tools/cycle_witness.ps1 by scripts/turns_loop.py, while the baton is
AGENTS. OpenClaw is the only searcher (scripts/openclaw_search.py); each need or
cell is served under the profile of its category (core/agent_profiles.py).

Order, no cap:
  1. every open BRAIN need — the query is the brain's own question (+ place, actor, period);
  2. every open ENGINE need;
  3. the maintenance portion — subcategory cells only, N per turn;
  4. the declared data feeds (scripts/openclaw_axis_worker.py) and the judge
     (core/card_intake.py) — the work the 4-times-a-day chain used to do.
Each open need gets one attempt per turn; a need with nothing found stays OPEN.
The core model is put back resident before the turn ends (R18), and the reload
seconds are reported. memory/turn_result.json carries a summary per need.

    venv\\Scripts\\python.exe scripts\\turn_agents.py [--maintenance 10]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
RESULT = REPO / "memory" / "turn_result.json"
LEDGER = REPO / "memory" / "vertical_ledger.jsonl"
FAIL_STREAK = 3


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def query_for(need: dict) -> str:
    """The brain's question IS the query, plus place, actor and period it gave."""
    about = need.get("about") or {}
    extra = [str(about[k]) for k in ("place", "actor", "period") if about.get(k)
             and str(about[k]).lower() not in need["question"].lower()]
    return " ".join([need["question"]] + extra)


def _atom_subcategories() -> dict:
    from core import atoms as at
    from core import space as sp
    return {sp.atom_id(a): a.get("subcategory") for a in at.read()}


def run(browser_for: Optional[Callable] = None, ingest: Optional[Callable] = None, maintenance_n: int = 10,
        bn_paths=None, ledger_path=None, result_path=None, turn_path=None, profiles_dir=None, learned_dir=None,
        feeds: Optional[Callable] = None, restore: Optional[Callable] = None, atom_sub: Optional[dict] = None,
        maintenance: Optional[Callable] = None, pages_dir=None) -> dict:
    from core import agent_profiles as ap
    from core import brain_needs as bn
    from core import turn
    from scripts import openclaw_search as oc
    turn.take(turn.AGENTS, turn_path, why="the agents' turn")
    t0 = time.time()
    if ingest is None:
        from core import knowledge as kn
        ingest = kn.ingest
    browsers: dict = {}

    def browser(profile: str):
        if profile not in browsers:
            browsers[profile] = (browser_for or (lambda p: oc.OpenClawBrowser(profile=p)))(profile)
        return browsers[profile]

    lp = Path(ledger_path or LEDGER)

    def ledger(row: dict) -> None:
        lp.parent.mkdir(parents=True, exist_ok=True)
        with lp.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"ts": _now(), **row}, ensure_ascii=False) + "\n")

    atom_sub = atom_sub if atom_sub is not None else _atom_subcategories()
    doc = bn.load_needs(bn_paths)
    open_ = [n for n in doc.get("needs", []) if n.get("status") in (bn.OPEN, bn.STILL_OPEN)]
    open_.sort(key=lambda n: 0 if n.get("origin") == "brain" else 1)
    per_need, streak = [], 0
    for n in open_:
        cat = ap.category_of(n, atom_sub)
        prof = ap.load(cat, profiles_dir)
        q = query_for(n) if n.get("origin") == "brain" else n["question"]
        ledger({"event": "TAKEN", "need_id": n["id"], "origin": n.get("origin"), "query": q, "category": cat})
        r = oc.serve(n["id"], q, browser(prof.get("browser_profile") or "openclaw"), ingest, ledger, pages_dir=pages_dir, category=cat)
        bn.mark_served(n["id"], q, r["pages"] + r["captcha"] + r["unbacked"], r["pages"], r["statements_added"], bn_paths)
        if cat != ap.MAIN:
            ap.learn(cat, r, learned_dir)
        streak = streak + 1 if r["errors"] and not r["pages"] else 0
        if streak == FAIL_STREAK:
            ledger({"event": "SEARCHER_FAILING", "streak": streak,
                    "why": "the direct browser path failed three needs in a row; the next in the price order "
                           "(an agent turn on ollama/qwen2.5:7b) is not built yet"})
        per_need.append({"need_id": n["id"], "origin": n.get("origin"), "category": cat, "query": q,
                         "pages": r["pages"], "captcha": r["captcha"], "unbacked": r["unbacked"],
                         "statements_gained": r["statements_added"], "pdfs": len(r.get("pdfs") or [])})

    rows = [json.loads(l) for l in lp.read_text(encoding="utf-8").splitlines() if l.strip()] if lp.exists() else []
    pdf_done = 0
    for item in oc.pending_pdf_needs(rows):
        pdf_done += 1 if oc.serve_pdf(item["need_id"], item["url"], browser("openclaw"), ingest, ledger,
                                      pages_dir) else 0

    def search_cell(cell: dict, q: str) -> dict:
        cat = ap.category_of(cell)
        prof = ap.load(cat, profiles_dir)
        r = oc.serve(cell["cell"], q, browser(prof.get("browser_profile") or "openclaw"), ingest, ledger, pages_dir=pages_dir, category=cat)
        ap.learn(cat, r, learned_dir)
        return {"pages": r["pages"], "statements_added": r["statements_added"], "captcha": r["captcha"]}

    if maintenance is None:
        from core import maintenance as mt
        maintenance = lambda n_, s: mt.run(n=n_, search=s, sources=[])      # noqa: E731  subcategory cells only
    mres = maintenance(maintenance_n, search_cell)
    fres = (feeds or _live_feeds)()
    rst = (restore or _live_restore)()
    res = {"utc": _now(), "seconds": round(time.time() - t0, 1), "cause": None, "per_need": per_need,
           "maintenance": {"worked": mres.get("worked"),
                           "verdicts": [x.get("verdict") for x in mres.get("rows", [])]},
           "feeds": fres, "core_restore": rst, "pdf_needs_read": pdf_done,
           "summary": (f"agents turn: {len(per_need)} need(s) served "
                       f"({sum(p['pages'] for p in per_need)} page(s), {sum(p['captcha'] for p in per_need)} CAPTCHA, "
                       f"{sum(p['statements_gained'] for p in per_need)} statement(s) gained); "
                       f"maintenance {mres.get('worked')} cell(s)")}
    p = Path(result_path or RESULT)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return {**res, "exit": 0}


def _live_feeds() -> dict:
    import subprocess
    py = str(REPO / "venv" / "Scripts" / "python.exe")
    out = {}
    for name, args in (("worker", [py, str(REPO / "scripts" / "openclaw_axis_worker.py")]),
                       ("judge", [py, str(REPO / "core" / "card_intake.py")])):
        t0 = time.time()
        p = subprocess.run(args, cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        out[name] = {"rc": p.returncode, "seconds": round(time.time() - t0, 1), "tail": p.stdout.strip()[-300:]}
    return out


def _live_restore() -> dict:
    from core import model_window as mw
    return mw.ensure_core()


def main() -> int:
    n = int(sys.argv[sys.argv.index("--maintenance") + 1]) if "--maintenance" in sys.argv else 10
    r = run(maintenance_n=n)
    print(json.dumps({k: v for k, v in r.items() if k != "per_need"}, indent=1, ensure_ascii=False, default=str))
    for p in r["per_need"]:
        print(json.dumps(p, ensure_ascii=False))
    return r["exit"]


if __name__ == "__main__":
    sys.exit(main())
