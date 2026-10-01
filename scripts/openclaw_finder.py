# -*- coding: utf-8 -*-
"""scripts/openclaw_finder.py — search for what the system needs, fetch what the
search returns, put the pages in the store the brain reads (C-OC-3 Part 3).

NO MODEL ANYWHERE IN THIS PATH. The needs are ranked by core/needs.py (counts and
a config order), the query is built from the need's own words, the search is the
repo's own (web_intelligence_agent._ddg_search — ddgs — with its GDELT fallback),
and every fetch goes through core/fetch_standard.

Chain: openclaw_axis_worker -> openclaw_finder -> card_intake.

Every step leaves a row in memory/vertical_ledger.jsonl:
  EMITTED (needs rebuilt) · TAKEN (need picked this pass) · SEARCHED(query, n) or
  NO_RESULTS · FETCHED(n) · UNREACHABLE (one per url, with the reason) · GAINED
  (statements this need added).
A source named by a declared need is unparked (core.fetch_standard.unpark), so
the next worker pass tries it again.

  venv\\Scripts\\python.exe scripts\\openclaw_finder.py [--n 5] [--per-need 4]
  venv\\Scripts\\python.exe scripts\\openclaw_finder.py --selftest
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

LEDGER = REPO / "memory" / "vertical_ledger.jsonl"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _row(ledger, **kw):
    ledger = pathlib.Path(ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"ts": _now(), **kw}, ensure_ascii=False) + "\n")


def repo_search(query: str, n: int = 5) -> list:
    """The repo's own search: ddgs first, GDELT when ddgs returns nothing."""
    import web_intelligence_agent as wia
    hits = wia._ddg_search(query, n) or wia._gdelt_search(query, n)
    return [{"url": h.get("link"), "title": h.get("title")} for h in hits if h.get("link")]


def _fetch(url: str, getter=None) -> dict:
    """-> {ok, raw, payload, content_type, err}."""
    if getter is not None:
        status, payload, err, raw = getter(url, 30)
        return {"ok": status == 200 and not err, "raw": raw, "payload": payload, "content_type": "",
                "err": err or (None if status == 200 else f"HTTP {status}")}
    from core import fetch_standard as fs
    try:
        g = fs.get(url)
    except fs.FetchRefused as exc:
        return {"ok": False, "err": f"REFUSED_BY_FETCH_STANDARD: {exc}"}
    except Exception as exc:                                         # noqa: BLE001
        return {"ok": False, "err": f"{type(exc).__name__}: {str(exc)[:160]}"}
    payload = None
    try:
        payload = json.loads(g["raw"])
    except ValueError:
        pass
    return {"ok": g["status"] == 200, "raw": g["raw"], "payload": payload, "content_type": g["content_type"],
            "err": None if g["status"] == 200 else f"HTTP {g['status']}"}


def run(n: int = 5, per_need: int = 4, search=None, getter=None, ledger=None, store=None, seen_path=None,
        needs_out=None, composer_path=None, labels_path=None, atoms_root=None, parking=None, tree=None) -> dict:
    from core import fetch_standard as fs
    from core import knowledge as kn
    from core import needs
    search = search or repo_search
    ledger = ledger or LEDGER
    doc = needs.rebuild(out=needs_out, composer_path=composer_path, labels_path=labels_path,
                        atoms_root=atoms_root, tree=tree)
    _row(ledger, event="EMITTED", needs=len(doc["needs"]),
         declared=sum(1 for x in doc["needs"] if x["tier"] == "declared"))
    taken = doc["needs"][:n]
    out = {"emitted": len(doc["needs"]), "taken": [], "statements_added": 0, "fetched": 0, "unreachable": 0}
    for need in taken:
        nid = need["need_id"]
        _row(ledger, event="TAKEN", need_id=nid, rank=need["rank"], query=need["query"])
        for sid in (need.get("source_ids") or []) if parking is not None else []:
            fs.unpark(sid, f"named by need {nid}", parking)
        try:
            hits = search(need["query"], per_need)
        except Exception as exc:                                     # noqa: BLE001
            hits = []
            _row(ledger, event="NO_RESULTS", need_id=nid, query=need["query"], why=f"{type(exc).__name__}: {exc}")
        else:
            _row(ledger, event="SEARCHED" if hits else "NO_RESULTS", need_id=nid, query=need["query"], n=len(hits))
        got, gained = 0, 0
        for h in hits[:per_need]:
            url = h["url"]
            page = _fetch(url, getter)
            if not page["ok"]:
                out["unreachable"] += 1
                _row(ledger, event="UNREACHABLE", need_id=nid, url=url, why=page["err"])
                continue
            got += 1
            try:
                text, form = kn.body_to_text(page["raw"], page["payload"], page["content_type"])
            except kn.FlattenLostValue as exc:
                text, form = page["raw"] or "", f"raw_text ({exc})"
            if form == "pdf_unreadable":
                _row(ledger, event="UNREACHABLE", need_id=nid, url=url, why="a PDF reader (none installed)")
                continue
            r = kn.ingest(f"url:{url}", text, url=url, origin="finder", store=store, seen_path=seen_path)
            gained += r["added"]
        _row(ledger, event="FETCHED", need_id=nid, n=got)
        _row(ledger, event="GAINED", need_id=nid, statements=gained)
        out["fetched"] += got
        out["statements_added"] += gained
        out["taken"].append({"need_id": nid, "query": need["query"], "hits": len(hits), "fetched": got,
                             "gained": gained})
    return out


def chain_steps(path=None) -> list:
    """The scripts tools/openclaw_chain.bat EXECUTES, in order (the %PY% lines,
    never its comments)."""
    p = pathlib.Path(path or REPO / "tools" / "openclaw_chain.bat")
    return [l.strip().split()[1].replace("\\", "/").rsplit("/", 1)[-1]
            for l in p.read_text(encoding="utf-8").splitlines() if l.strip().startswith("%PY% ")]


def selftest() -> dict:
    res = {"integrations": {}}
    try:
        import web_intelligence_agent as wia
        res["integrations"]["search: web_intelligence_agent._ddg_search (ddgs)"] = (
            "LIVE" if wia.HAS_DDG else "INERT (ddgs not importable; GDELT fallback only)")
    except Exception as exc:                                         # noqa: BLE001
        res["integrations"]["search: web_intelligence_agent"] = f"INERT ({type(exc).__name__})"
    res["integrations"]["chain runs the finder between worker and judge"] = (
        "LIVE" if chain_steps() == ["openclaw_axis_worker.py", "openclaw_finder.py", "card_intake.py"] else
        f"INERT (chain runs {chain_steps()})")
    res["integrations"]["memory/vertical_ledger.jsonl"] = "LIVE" if LEDGER.exists() else "INERT (never ran)"
    res["ok"] = True
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="search for the top needs; no model")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--per-need", type=int, default=4)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        print(json.dumps(selftest(), indent=2))
        return 0
    from core import fetch_standard as fs
    r = run(n=a.n, per_need=a.per_need, parking=fs.PARKING)
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
