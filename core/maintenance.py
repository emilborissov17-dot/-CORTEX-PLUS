# -*- coding: utf-8 -*-
"""core/maintenance.py — every cell of the map is worked in turn (C-NEED-1 Part 1).

Emil, R29: "The puzzle of empty cells has to be filled anyway: every cell is
worked and the information there is kept current — registered with or without
change, as reality shows; some things really do not change."

THIS IS MAINTENANCE, NOT COGNITION. No priority: the queue is every world
subcategory and every known source, ordered ONLY by how long since each was last
worked (never-worked first, then oldest), and a pass takes the next N. Nothing
here decides what matters; core/brain_needs.py is where needs come from.

A SUBCATEGORY cell is searched with its name and ONE wanted key, the key rotating
pass by pass; a query already tried is not tried again until every key of the
cell has had its turn. Pages found are ingested whole (core.knowledge). The
observation log gets one row per cell: CHANGED (new sentences entered),
UNCHANGED (every sentence was already held), or NOTHING_FOUND (with the queries
tried). config/taxonomy.json's source_hints_unverified are not used.

A SOURCE cell is re-fetched through the DMZ worker, one source; its card is
judged by core/card_intake, and core.atoms.write registers that re-observation
as UNCHANGED or CHANGED. A source that cannot be reached is NOTHING_FOUND here.

    venv\\Scripts\\python.exe -m core.maintenance [--n 10]
    venv\\Scripts\\python.exe -m core.maintenance --selftest
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
STATE = REPO / "memory" / "maintenance_state.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load(p: Path) -> dict:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict, p: Path) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def cells(tree: Optional[dict] = None, sources: Optional[list] = None) -> list:
    """Every world subcategory and every known source, as cell dicts."""
    from core import taxonomy as tx
    out = [{"cell": f"sub:{s['id']}", "kind": "subcategory", "sub": s} for s in tx.world_subcategories(tree)]
    if sources is None:
        from scripts.openclaw_axis_worker import all_sources
        sources, _ = all_sources()
    seen = set()
    for s in sources:
        if s.get("id") and s["id"] not in seen:          # a source listed twice is one cell
            seen.add(s["id"])
            out.append({"cell": f"src:{s['id']}", "kind": "source", "source": s})
    return out


STALE = REPO / "memory" / "space" / "stale_for_maintenance.json"


def queue(all_cells: list, state: dict, due: Optional[set] = None) -> list:
    """Oldest-worked first; never-worked before any worked; ties by cell id. A
    source the space derived as STALE (core/space.py) is due: it sorts as if never
    worked, because its reading is known to be out of date. Nothing else enters."""
    due = due or set()
    return sorted(all_cells, key=lambda c: ("" if c["cell"] in due else
                                            (state.get(c["cell"]) or {}).get("last_worked_utc") or "", c["cell"]))


def query_for(sub: dict, st: dict) -> Optional[str]:
    """The cell's next query: its name and ONE wanted key. A query already tried
    is skipped until every key has had its turn, then the rotation restarts."""
    keys = list(sub.get("wanted_keys") or []) or [""]
    tried = set(st.get("tried") or [])
    if len(tried & {_q(sub, k) for k in keys}) >= len(keys):
        tried = set()
        st["tried"] = []
        st["rotations"] = st.get("rotations", 0) + 1
    i = st.get("key_idx", 0)
    for step in range(len(keys)):
        k = keys[(i + step) % len(keys)]
        q = _q(sub, k)
        if q not in tried:
            st["key_idx"] = (i + step + 1) % len(keys)
            return q
    return None


def _q(sub: dict, key: str) -> str:
    return f"{sub['name_en']} {key.replace('_', ' ')}".strip()


NO_SEARCHER = "no searcher: the Python finder was removed on Emil's order; OpenClaw search not built yet"


def _work_subcategory(cell, st, search) -> dict:
    """A subcategory cell is SEARCHED by the searcher it is given. Until OpenClaw
    search exists (C-TURN-1 Part 4) there is none: the cell is logged NO_SEARCHER
    with the query it would have used, and nothing else stands in."""
    q = query_for(cell["sub"], st)
    if search is None:
        return {"verdict": "NO_SEARCHER", "queries": [q], "why": NO_SEARCHER}
    st.setdefault("tried", []).append(q)
    try:
        res = search(cell, q)
    except Exception as exc:                                         # noqa: BLE001
        return {"verdict": "NOTHING_FOUND", "queries": [q], "why": f"{type(exc).__name__}: {exc}"}
    if not res.get("pages"):
        return {"verdict": "NOTHING_FOUND", "queries": [q], **res}
    return {"verdict": "CHANGED" if res.get("statements_added") else "UNCHANGED", "queries": [q], **res}


def _work_source(cell, worker_run) -> dict:
    r = worker_run(cell["source"])
    if r.get("unreachable"):
        return {"verdict": "NOTHING_FOUND", "why": r["unreachable"][0].get("reason")}
    if r.get("refusals") and not r.get("cards"):
        return {"verdict": "LABEL_REFUSED", "why": r["refusals"][0].get("reason")}
    return {"verdict": "FETCHED", "cards": len(r.get("cards") or []),
            "note": "UNCHANGED/CHANGED is registered by core.atoms.write when card_intake judges the card"}


def _live_worker_run(source: dict) -> dict:
    import tempfile
    from core import fetch_standard as fs
    from core import knowledge as kn
    from scripts import openclaw_axis_worker as w
    with tempfile.TemporaryDirectory() as d:
        seed = Path(d) / "one.json"
        seed.write_text(json.dumps({"sources": [source], "timeout_sec": 30}), encoding="utf-8")
        return w.run(seed, discovered_path=Path(d) / "none.json", ingest=kn.ingest, parking=fs.PARKING)


def run(n: int = 10, search: Optional[Callable] = None, worker_run: Optional[Callable] = None,
        state_path=None, log_path=None, tree=None, sources=None, stale_path=None) -> dict:
    """`search(cell, query) -> {pages, statements_added, ...}` is the searcher; None
    means there is none (and the subcategory cells say so)."""
    from core import atoms as at
    worker_run = worker_run or _live_worker_run
    sp = Path(state_path or STATE)
    lp = Path(log_path or at.OBS_LOG)
    state = _load(sp)
    due = {f"src:{s}" for s in (_load(stale_path or STALE).get("sources") or [])}
    q = queue(cells(tree, sources), state, due)
    taken, out = q[:n], []
    for c in taken:
        st = state.setdefault(c["cell"], {})
        res = (_work_subcategory(c, st, search) if c["kind"] == "subcategory"
               else _work_source(c, worker_run))
        st["last_worked_utc"] = _now()
        st["last_verdict"] = res["verdict"]
        row = {"ts": st["last_worked_utc"], "origin": "maintenance", "cell": c["cell"], **res}
        lp.parent.mkdir(parents=True, exist_ok=True)
        with lp.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.append(row)
        _save(state, sp)                                  # a killed pass keeps what it worked
    return {"cells_total": len(q), "worked": len(out), "rows": out}


def selftest() -> dict:
    res = {"integrations": {
        "memory/maintenance_state.json": f"LIVE ({len(_load(STATE))} cells worked)" if STATE.exists()
        else "INERT (never ran)"}}
    chain = REPO / "tools" / "openclaw_chain.bat"
    from core.turn import bat_steps
    res["integrations"]["chain runs core.maintenance"] = (
        "LIVE" if "maintenance.py" in bat_steps(chain) else "INERT (not in tools/openclaw_chain.bat)")
    res["integrations"]["searcher for subcategory cells"] = "INERT (" + NO_SEARCHER + ")"
    res["ok"] = True
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
        sys.exit(0)
    nn = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 10
    r = run(n=nn)
    print(json.dumps({k: v for k, v in r.items() if k != "rows"} | {"verdicts": [x["verdict"] for x in r["rows"]]},
                     indent=1))
