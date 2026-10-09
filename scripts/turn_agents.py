# -*- coding: utf-8 -*-
"""scripts/turn_agents.py — the agents' turn (C-TURN-1 Part 4f; Emil R31, R32).

Run through tools/cycle_witness.ps1 by scripts/turns_loop.py, while the baton is
AGENTS. OpenClaw is the only searcher (scripts/openclaw_search.py); each need or
cell is served under the profile of its category (core/agent_profiles.py).

A turn is a PORTION; the rest waits in rotation (C-BRAIN-1 Part 5). Order:
  1. every open BRAIN need that is searchable (children and direct needs; a parent
     is never searched) — the query is the brain's own question (+ place, actor, period);
  2. every open ENGINE need that is not VERIFY or LABEL (FIND);
  3. at most verify_per_turn engine VERIFY needs, longest-waiting first (last
     served, else created); the rest are logged WAITED and come first next turn;
  4. LABEL needs (an atom with neither place nor period), served from the store, no browser;
  5. maintenance_cells_per_turn subcategory cells;
  6. both browser profiles stopped, then the declared data feeds and the judge.
The two numbers live in config/turn_portion.json with the measurement behind them.
No query carries "none". The browser is checked before each need: dead -> started
once; dead again -> the turn ends with cause SEARCHER_DEAD (exit 2, the baton passes).
The core model is put back resident before the turn ends (R18).

    venv\\Scripts\\python.exe scripts\\turn_agents.py [--maintenance N]
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
RESULT = REPO / "memory" / "turn_result.json"
RECORDS = REPO / "memory" / "turns"
LEDGER = REPO / "memory" / "vertical_ledger.jsonl"
FAIL_STREAK = 3


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


_NONE_PHRASE = re.compile(r"(?:,\s*)?\b(?:for|in|at|period)\s+(?:none|null)(?![\w-])", re.IGNORECASE)
_NONE = re.compile(r"(?<![\w-])(?:none|null)(?![\w-])", re.IGNORECASE)


def clean_query(q: str) -> str:
    """No "none" in a query (C-BRAIN-1 5e): a missing place or period is left out,
    never searched for as the word."""
    s = _NONE.sub("", _NONE_PHRASE.sub("", q))
    return re.sub(r"\s+", " ", re.sub(r"\s+([,.;:?!])", r"\1", s)).strip(" ,;:")


def query_for(need: dict) -> str:
    """The brain's question IS the query, plus place, actor and period it gave."""
    about = need.get("about") or {}
    extra = [str(about[k]) for k in ("place", "actor", "period") if about.get(k)
             and str(about[k]).lower() not in need["question"].lower()]
    return clean_query(" ".join([need["question"]] + extra))


def _atom_subcategories() -> dict:
    from core import atoms as at
    from core import space as sp
    return {sp.atom_id(a): a.get("subcategory") for a in at.read()}


class SearcherDead(RuntimeError):
    """OpenClaw's browser is not running after one start: the turn ends (5f iii)."""


class GatewayDead(SearcherDead):
    """OpenClaw's gateway does not answer after its one restart this turn (C-GW-1 1a)."""


class ProfileDead(SearcherDead):
    """One browser profile does not answer while the gateway's health does (C-FIX-1 4B-a);
    still so after the turn's one gateway restart."""

    def __init__(self, profile: str, why: str):
        super().__init__(f"profile {profile}: {why}")
        self.profile = profile


MAX_GATEWAY_RESTARTS = 1


def _cause(exc: SearcherDead) -> str:
    if isinstance(exc, ProfileDead):
        return f"PROFILE_DEAD:{exc.profile}"
    return f"{'GATEWAY_DEAD' if isinstance(exc, GatewayDead) else 'SEARCHER_DEAD'}: {exc}"


def _waited_since(n: dict) -> str:
    return str(n.get("last_served_utc") or n.get("created_utc") or "")


def portion_of(needs: list, verify_n: int, origins: Optional[tuple] = None) -> tuple:
    """-> (taken in order, waiting). All brain needs (children and direct; parents
    are not searchable), all engine FIND, at most `verify_n` engine VERIFY,
    longest-waiting first; LABEL needs are served from the store."""
    from core import brain_needs as bn
    open_ = [n for n in bn.searchable(needs) if origins is None or n.get("origin") in origins]
    brain = [n for n in open_ if n.get("origin") == "brain"]
    find = [n for n in open_ if n.get("origin") == "engine" and n.get("kind") not in ("VERIFY", "LABEL")]
    verify = sorted([n for n in open_ if n.get("origin") == "engine" and n.get("kind") == "VERIFY"], key=_waited_since)
    label = [n for n in open_ if n.get("origin") == "engine" and n.get("kind") == "LABEL"]
    return brain + find + verify[:verify_n] + label, verify[verify_n:]


def _profiles(profiles_dir=None) -> list:
    from core import agent_profiles as ap
    out = {"openclaw"}
    for f in Path(profiles_dir or ap.CONFIG).glob("*.json"):
        try:
            out.add(json.loads(f.read_text(encoding="utf-8")).get("browser_profile") or "openclaw")
        except (OSError, ValueError):
            pass
    return sorted(out)


def run(browser_for: Optional[Callable] = None, ingest: Optional[Callable] = None, maintenance_n: Optional[int] = None,
        bn_paths=None, ledger_path=None, result_path=None, turn_path=None, profiles_dir=None, learned_dir=None,
        feeds: Optional[Callable] = None, restore: Optional[Callable] = None, atom_sub: Optional[dict] = None,
        maintenance: Optional[Callable] = None, pages_dir=None, records_dir=None, portion_path=None,
        store_read: Optional[Callable] = None, gateway=None, origins: Optional[tuple] = None,
        end_chrome: Optional[Callable] = None, turns_log=None, alarm: Optional[Callable] = None) -> dict:
    """origins=("engine",): a turn run by hand that takes engine needs only (C-GW-1 step 4).
    turns_log / alarm: the loop's log and the alarm sender for the five-turn stall (C-BRAIN-ASK-1)."""
    from core import agent_profiles as ap
    from core import brain_needs as bn
    from core import turn
    from scripts import openclaw_search as oc
    from core import narration as nr
    turn.take(turn.AGENTS, turn_path, why="the agents' turn")
    t0 = time.time()
    por = turn.portion(portion_path)
    maintenance_n = por["maintenance_cells_per_turn"] if maintenance_n is None else maintenance_n
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

    gw = gateway if gateway is not None else oc.Gateway()
    gw_restarts = [0]

    def ensure_gateway() -> None:
        """C-GW-1 1a: a gateway that does not answer is not a dead browser. One health
        check; dead -> restarted at most MAX_GATEWAY_RESTARTS per turn; still dead -> GatewayDead."""
        if gw.healthy():
            return
        if gw_restarts[0] >= MAX_GATEWAY_RESTARTS:
            raise GatewayDead("the OpenClaw gateway does not answer and was already restarted this turn")
        gw_restarts[0] += 1
        t1 = time.time()
        gw.restart()
        ok = gw.healthy()
        ledger({"event": "GATEWAY_RESTARTED", "seconds": round(time.time() - t1, 1), "healthy_after": ok})
        if not ok:
            raise GatewayDead("the OpenClaw gateway does not answer after one restart")

    def recycle(profile: str, b) -> None:
        """C-FIX-1 4B-b iii: the profile's status timed out while the gateway's health
        answers. The recovery 4B-a found is a gateway restart - one per turn, shared with
        ensure_gateway; still no answer -> ProfileDead."""
        ledger({"event": "PROFILE_DEAD", "profile": profile,
                "why": "a call for this profile timed out while the gateway's health answered"})
        if gw_restarts[0] >= MAX_GATEWAY_RESTARTS:
            raise ProfileDead(profile, "no answer, and the gateway was already restarted this turn")
        gw_restarts[0] += 1
        t1 = time.time()
        gw.restart()
        ledger({"event": "GATEWAY_RESTARTED", "seconds": round(time.time() - t1, 1), "healthy_after": gw.healthy(),
                "why": f"PROFILE_DEAD:{profile}"})

    def gateway_timed_out(profile: str, where: str) -> None:
        """C-GW-2 (8 Oct 2026): the CLI said "gateway timeout" for a browser call while
        `gateway health` answers. That IS a dead gateway for the browser (5 and 7 Oct: the
        turn ended SEARCHER_DEAD three times and the baton stood for 36 h, then 21 h). The
        recovery is the same one restart per turn, shared with ensure_gateway and recycle;
        a second timeout after it ends the turn GATEWAY_DEAD, whose health check is real."""
        ledger({"event": "GATEWAY_TIMEOUT", "profile": profile, "where": where,
                "health": "answers" if gw.healthy() else "does not answer"})
        if gw_restarts[0] >= MAX_GATEWAY_RESTARTS:
            raise GatewayDead(f"the OpenClaw gateway times out on browser {where} for profile {profile} "
                              f"and was already restarted this turn")
        gw_restarts[0] += 1
        t1 = time.time()
        gw.restart()
        ledger({"event": "GATEWAY_RESTARTED", "seconds": round(time.time() - t1, 1), "healthy_after": gw.healthy(),
                "why": f"GATEWAY_TIMEOUT:{where}:{profile}"})

    def start_once(profile: str, b) -> None:
        """One start; a gateway timeout on it is the gateway's fault, not the profile's:
        one restart (if the turn still has it), then the start is tried once more."""
        ledger({"event": "BROWSER_DEAD", "profile": profile, "action": "start once"})
        try:
            b.start()
            return
        except oc.GatewayTimeout as exc:
            ledger({"event": "BROWSER_START_FAILED", "profile": profile, "error": f"{type(exc).__name__}: {exc}"[:300]})
            gateway_timed_out(profile, "start")
        except Exception as exc:                                         # noqa: BLE001
            ledger({"event": "BROWSER_START_FAILED", "profile": profile, "error": f"{type(exc).__name__}: {exc}"[:300]})
            return
        ledger({"event": "BROWSER_DEAD", "profile": profile, "action": "start again after the gateway restart"})
        try:
            b.start()
        except oc.GatewayTimeout as exc:
            ledger({"event": "BROWSER_START_FAILED", "profile": profile, "error": f"{type(exc).__name__}: {exc}"[:300]})
            raise GatewayDead(f"the OpenClaw gateway times out on browser start for profile {profile} "
                              f"after one restart") from exc
        except Exception as exc:                                         # noqa: BLE001
            ledger({"event": "BROWSER_START_FAILED", "profile": profile, "error": f"{type(exc).__name__}: {exc}"[:300]})

    def live(profile: str):
        """5f iii: checked before each need; gateway first (C-GW-1); browser dead -> started
        once; dead again -> SearcherDead, or GatewayDead if the gateway died meanwhile.
        C-GW-2: a "gateway timeout" on status or start is a dead gateway: one restart."""
        b = browser(profile)
        if b.alive():
            return b
        if getattr(b, "timed_out", False) and gw.healthy():
            recycle(profile, b)
            if b.alive():
                return b
            if getattr(b, "timed_out", False):
                raise ProfileDead(profile, "no answer after one gateway restart")
        if getattr(b, "gateway_timed_out", False):
            gateway_timed_out(profile, "status")
            if b.alive():
                return b
            if getattr(b, "gateway_timed_out", False):
                raise GatewayDead(f"the OpenClaw gateway times out on browser status for profile {profile} "
                                  f"after one restart")
        ensure_gateway()
        if b.alive():
            return b
        start_once(profile, b)
        if b.alive():
            return b
        if getattr(b, "gateway_timed_out", False):
            gateway_timed_out(profile, "status after start")
            if b.alive():
                return b
            raise GatewayDead(f"the OpenClaw gateway times out on browser status for profile {profile} "
                              f"after its start and the turn's one restart")
        ensure_gateway()
        raise SearcherDead(f"OpenClaw browser profile {profile} is not running after one start")

    def stop_all() -> dict:
        """5f ii: both browser profiles stopped at the turn's end, whatever happened; a stop
        that times out ends that profile's Chrome by exact PID (C-FIX-1 4B-b ii)."""
        out = {}
        for prof in _profiles(profiles_dir):
            try:
                out[prof] = oc.stop_browser(browser(prof), ledger, profile=prof, end_chrome=end_chrome)
            except Exception as exc:                                     # noqa: BLE001
                out[prof] = f"{type(exc).__name__}: {exc}"[:200]
        return out

    stopped: dict = {}
    try:
        atom_sub = atom_sub if atom_sub is not None else _atom_subcategories()
        doc = bn.load_needs(bn_paths)
        taken, waiting = portion_of(doc.get("needs", []), por["verify_per_turn"], origins)
        nr.begin("needs", "fetch what the open needs ask for: the brain's needs with its own question, engine "
                          "FIND, the longest-waiting VERIFY, LABEL from the store (OpenClaw is the only searcher, R42)",
                 reads=[bn._p(bn_paths, "needs")])
        nr.note(f"portion: {len(taken)} need(s) taken, {len(waiting)} waiting for a later turn",
                taken=[x.get("id") for x in taken])
        for n in waiting:
            ledger({"event": "WAITED", "need_id": n["id"], "origin": n.get("origin"), "kind": n.get("kind"),
                    "since": _waited_since(n)})
        per_need, streak, cause = [], 0, None
        try:
            for n in taken:
                t1 = time.time()
                cat = ap.category_of(n, atom_sub)
                if n.get("kind") == "LABEL":
                    # 5e: an atom with neither place nor period — served from the store, no browser
                    items = (store_read or _store_read)(n["question"])
                    ledger({"event": "LABEL_FROM_STORE", "need_id": n["id"], "items": [i.get("id") for i in items]})
                    nr.note(f"{n['id']} LABEL from the store: {len(items)} item(s) for {n['question']!r}")
                    bn.mark_served(n["id"], "store: " + n["question"], len(items), 0, 0, bn_paths)
                    per_need.append({"need_id": n["id"], "origin": n.get("origin"), "kind": "LABEL", "category": cat,
                                     "query": None, "store_items": len(items), "pages": 0, "captcha": 0, "unbacked": 0,
                                     "statements_gained": 0, "seconds": round(time.time() - t1, 1)})
                    continue
                prof = ap.load(cat, profiles_dir)
                q = clean_query(query_for(n) if n.get("origin") == "brain" else n["question"])
                b = live(prof.get("browser_profile") or "openclaw")
                ledger({"event": "TAKEN", "need_id": n["id"], "origin": n.get("origin"), "query": q, "category": cat})
                nr.note(f"{n['id']} ({n.get('origin')} {n.get('kind') or ''}, {cat}): searching {q!r}")
                r = oc.serve(n["id"], q, b, ingest, ledger, pages_dir=pages_dir, category=cat)
                bn.mark_served(n["id"], q, r["pages"] + r["captcha"] + r["unbacked"], r["pages"], r["statements_added"],
                               bn_paths)
                if cat != ap.MAIN:
                    ap.learn(cat, r, learned_dir)
                streak = streak + 1 if r["errors"] and not r["pages"] else 0
                if streak == FAIL_STREAK:
                    ledger({"event": "SEARCHER_FAILING", "streak": streak,
                            "why": "the direct browser path failed three needs in a row; the next in the price order "
                                   "(an agent turn on ollama/qwen2.5:7b) is not built yet"})
                per_need.append({"need_id": n["id"], "origin": n.get("origin"), "kind": n.get("kind"), "category": cat,
                                 "query": q, "pages": r["pages"], "captcha": r["captcha"], "unbacked": r["unbacked"],
                                 "statements_gained": r["statements_added"], "regions": r.get("regions"),
                                 "pdfs": len(r.get("pdfs") or []), "seconds": round(time.time() - t1, 1)})
                nr.note(f"{n['id']} served in {per_need[-1]['seconds']} s: {r['pages']} page(s), {r['captcha']} "
                        f"CAPTCHA, {r['statements_added']} statement(s) gained"
                        + (f"; errors: {str(r.get('errors'))[:200]}" if r.get("errors") else ""))
        except SearcherDead as exc:
            cause = _cause(exc)
            ledger({"event": "SEARCHER_DEAD", "why": str(exc), "served": len(per_need)})

        nr.end(f"{len(per_need)} need(s) served, {sum(p['statements_gained'] for p in per_need)} statement(s) "
               f"gained", status="OK" if cause is None else "STOPPED", error=cause)
        mres, fres, pdf_done = {"worked": 0, "rows": []}, None, 0
        nr.begin("maintenance", "read the PDFs the pages pointed to, then search the oldest subcategory cells "
                                "(R29)" if cause is None else "skipped: the needs phase stopped")
        if cause is None:
            rows = [json.loads(l) for l in lp.read_text(encoding="utf-8").splitlines() if l.strip()] if lp.exists() else []
            try:
                for item in oc.pending_pdf_needs(rows):
                    pdf_done += 1 if oc.serve_pdf(item["need_id"], item["url"], live("openclaw"), ingest, ledger,
                                                  pages_dir) else 0

                def search_cell(cell: dict, q: str) -> dict:
                    cat = ap.category_of(cell)
                    prof = ap.load(cat, profiles_dir)
                    r = oc.serve(cell["cell"], clean_query(q), live(prof.get("browser_profile") or "openclaw"), ingest,
                                 ledger, pages_dir=pages_dir, category=cat)
                    ap.learn(cat, r, learned_dir)
                    return {"pages": r["pages"], "statements_added": r["statements_added"], "captcha": r["captcha"],
                            "errors": r["errors"]}

                if maintenance is None:
                    from core import maintenance as mt
                    maintenance = lambda n_, s: mt.run(n=n_, search=s, sources=[])      # noqa: E731  subcategory cells only
                mres = maintenance(maintenance_n, search_cell)
            except SearcherDead as exc:
                cause = _cause(exc)
                ledger({"event": "SEARCHER_DEAD", "why": str(exc), "served": len(per_need)})
        nr.end(f"{pdf_done} PDF need(s) read; maintenance {mres.get('worked')} cell(s)",
               status="OK" if cause is None else "STOPPED", error=cause)
    finally:
        stopped = stop_all()
    if cause is None:
        fres = (feeds or _live_feeds)()
    rst = (restore or _live_restore)()
    nr.note(f"browsers stopped: {stopped}; feeds: {fres}; core model: {rst}"[:800])
    searched = [p for p in per_need if p.get("kind") != "LABEL"]
    stall = _stall_alarm(turns_log, lp, alarm)
    res = {"utc": _now(), "seconds": round(time.time() - t0, 1), "cause": cause, "per_need": per_need,
           "stall": stall,
           "waited": len(waiting), "portion": por, "browsers_stopped": stopped,
           "seconds_per_need": round(sum(p["seconds"] for p in searched) / len(searched), 1) if searched else None,
           "maintenance": {"worked": mres.get("worked"),
                           "verdicts": [x.get("verdict") for x in mres.get("rows", [])]},
           "feeds": fres, "core_restore": rst, "pdf_needs_read": pdf_done,
           "summary": (f"agents turn: {len(per_need)} need(s) served "
                       f"({sum(p['pages'] for p in per_need)} page(s), {sum(p['captcha'] for p in per_need)} CAPTCHA, "
                       f"{sum(p['statements_gained'] for p in per_need)} statement(s) gained); "
                       f"{len(waiting)} waited; maintenance {mres.get('worked')} cell(s)"
                       + (f"; ended: {cause}" if cause else ""))}
    p = Path(result_path or RESULT)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    rd = Path(records_dir or RECORDS)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / f"agents_{res['utc'].replace(':', '')}.json").write_text(
        json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return {**res, "exit": 2 if cause else 0}


def _stall_alarm(turns_log, ledger_path, alarm: Optional[Callable]) -> Optional[dict]:
    """C-BRAIN-ASK-1 (Perplexity 81E point 4, 81F Q3 counting (i), 81I F5): after this
    turn's needs step, the last five agents' turns are read from the loop's log and the
    vertical ledger (this turn included — its GAINED rows are already written). When none
    of the five has a GAINED row with statements > 0 for a need it took, ONE alarm goes to
    the phone (cls "alarm"; the dedup key is the seq of the first empty turn of the run, kept
    in supervisor's alarm stamp file, so a stall that goes on is told once and a new stall
    is told again). No second threshold. Never raises: the turn's result does not depend on
    the phone."""
    from core import needs_gain as ng
    from core import turn
    try:
        turns = ng.last_turns(ng.STALL_LOOKBACK, turns_log or turn.LOG, ledger_path)
        st = ng.stalled(turns)
        if st is not None and st["run_length"] == len(turns):
            # the run of empty turns reaches the edge of the lookback: read every turn, so the
            # key is the run's true first seq and does not slide once the stall outlives 50 turns
            turns = ng.last_turns(ng.ALL_TURNS, turns_log or turn.LOG, ledger_path)
            st = ng.stalled(turns)
    except Exception as exc:                                             # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}
    if st is None:
        return None
    detail = (f"{st['run_length']} agents' turns in a row (the last {st['turns']}: seq {st['seqs']}, from "
              f"{st['first_start']} to {st['last_start']}) brought no statement for any need they took; causes seen: "
              f"{st['causes'] or 'none named'}. "
              f"The brain's 3B is not asked while this goes on (core.needs_gain). The loop keeps running.")
    try:
        sent = (alarm or _live_alarm)("NEEDS_STALLED_5_TURNS", detail, f"NEEDS_STALLED:{st['run_start_seq']}")
    except Exception as exc:                                             # noqa: BLE001
        sent = f"failed: {type(exc).__name__}: {exc}"[:200]
    return {**st, "sent": sent}


def _live_alarm(subject: str, detail: str, dedup_key: str) -> str:
    import supervisor
    return supervisor.alarm_human(subject, detail, dedup_key=dedup_key, cls="alarm", level=supervisor.ALARM)


def _store_read(question: str) -> list:
    from core import knowledge as kn
    return kn.read(question, k=5, with_vectors=False)


def _live_feeds() -> dict:
    import subprocess
    py = str(REPO / "venv" / "Scripts" / "python.exe")
    out = {}
    for name, args in (("worker", [py, str(REPO / "scripts" / "data_feed_reader.py")]),
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
    n = int(sys.argv[sys.argv.index("--maintenance") + 1]) if "--maintenance" in sys.argv else None
    # --engine-only: engine needs only; --turn-file F: a baton file of its own (a turn run by
    # hand, the loop stopped, the real memory/turn.json untouched) — C-GW-1 step 4
    tf = sys.argv[sys.argv.index("--turn-file") + 1] if "--turn-file" in sys.argv else None
    from core import narration as nr
    nr.open_turn("AGENTS")
    r = None
    try:
        r = run(maintenance_n=n, origins=("engine",) if "--engine-only" in sys.argv else None, turn_path=tf,
                result_path=(Path(tf).with_name("turn_result_by_hand.json") if tf else None))
    finally:
        nr.close_turn(r["exit"] if r else "none (the turn raised; its traceback is in the turn's log)",
                      (r or {}).get("summary") or "")
    print(json.dumps({k: v for k, v in r.items() if k != "per_need"}, indent=1, ensure_ascii=False, default=str))
    for p in r["per_need"]:
        print(json.dumps(p, ensure_ascii=False))
    return r["exit"]


if __name__ == "__main__":
    sys.exit(main())
