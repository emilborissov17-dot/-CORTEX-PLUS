#!/usr/bin/env python3
"""
tools/morning_digest.py — one Telegram message a morning about last night (C2c, 26 Sep 2026).

Content, all read from records, none from a model:
  last night's collectors / spine / edges: exit code and wall time (memory/witness.jsonl)
  the daily proof: newest commit on cortex-civilization-watch, its sha and date label
  core resident yes/no (Ollama /api/ps); UCDP API requests today
  forward rows: id, status, next expected date
  GITHUB_TOKEN days to expiry (GitHub's own response header), a warning under 30
  DIRTY tracked code at the spine's start (the witness start row), if any
  "clean nights in a row: N/7"

A CLEAN night: collectors, spine and edges all exit 0, AND the proof was published
with that night's local date label, AND the spine start row lists no dirty code. A
start row without the dirty_code field (written before 26 Sep 2026) is UNKNOWN, and
unknown is not clean. The counter (memory/clean_nights.json) moves once per night;
a miss resets it and records every reason.

Sent through supervisor.alarm_human(cls="morning_digest") - the one class allowed in
quiet hours. Task CORTEX_MorningDigest runs it at 07:00 and 09:05; a run sends only
if nothing was delivered for today, so 09:05 is the retry. Every attempt is logged
to memory/morning_digest_log.jsonl (delivered / deferred / suppressed / failed).

    venv\\Scripts\\python.exe tools/morning_digest.py            # send if not yet delivered today
    venv\\Scripts\\python.exe tools/morning_digest.py --dry-run  # print, send nothing, count nothing
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

WITNESS = REPO / "memory" / "witness.jsonl"
CLEAN = REPO / "memory" / "clean_nights.json"
LOG = REPO / "memory" / "morning_digest_log.jsonl"
WATCH_REPO = "emilborissov17-dot/cortex-civilization-watch"
TOKEN_WARN_DAYS = 30
STREAK_GOAL = 7


def _rows(path: Path = WITNESS) -> list:
    try:
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except FileNotFoundError:
        return []


def last_night(rows: list) -> dict:
    """The newest spine start row, its collectors (the newest #collectors start
    before it) and its edges (<cid>#edges). {role: {start, exit}}."""
    spines = [r for r in rows if r.get("event") == "start" and r.get("role") == "spine"]
    if not spines:
        return {}
    sp = spines[-1]
    cid = sp["cycle_id"]
    cols = [r for r in rows if r.get("event") == "start" and str(r.get("cycle_id", "")).endswith("#collectors")
            and str(r.get("ts", "")) <= str(sp.get("ts", ""))]
    ids = {"spine": cid, "edges": f"{cid}#edges", "collectors": cols[-1]["cycle_id"] if cols else None}
    out = {"night": str(cid)[:10]}
    for role, rid in ids.items():
        start = next((r for r in reversed(rows) if r.get("event") == "start" and r.get("cycle_id") == rid), None)
        ex = next((r for r in reversed(rows) if r.get("event") == "exit" and r.get("cycle_id") == rid), None)
        out[role] = {"cycle_id": rid, "start": start, "exit": ex}
    return out


def proof(watch: str = WATCH_REPO) -> dict:
    import requests
    import github_publisher as gp
    r = requests.get(f"https://api.github.com/repos/{watch}/commits?per_page=50", headers=gp._headers(), timeout=20)
    exp = r.headers.get("github-authentication-token-expiration")
    out = {"http": r.status_code, "token_expiration": exp}
    c = daily_index_commit(r.json() if r.ok else [])
    if c:
        msg = c["commit"]["message"].splitlines()[0]
        out.update(sha=c["sha"], date_utc=c["commit"]["author"]["date"], message=msg,
                   label=re.match(r"\[(\d{4}-\d{2}-\d{2})\]", msg).group(1))
    return out


def daily_index_commit(commits: list) -> dict | None:
    """The newest '[YYYY-MM-DD] Daily index' commit - the daily proof. Other commits on
    the watch repo (institution0 pages, forward rows) are not the proof."""
    for c in commits or []:
        if re.match(r"\[\d{4}-\d{2}-\d{2}\] Daily index", c["commit"]["message"].splitlines()[0]):
            return c
    return None


def token_days(exp: str | None, now: datetime | None = None) -> int | None:
    if not exp:
        return None
    t = datetime.strptime(exp.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (t - (now or datetime.now(timezone.utc))).days


def verdict(night: dict, prf: dict) -> tuple[bool, list]:
    """(clean, reasons it is not)."""
    reasons = []
    if not night:
        return False, ["no spine start row in the witness log"]
    for role in ("collectors", "spine", "edges"):
        ex = (night.get(role) or {}).get("exit")
        if not ex:
            reasons.append(f"{role}: no exit row")
        elif ex.get("exit_code") != 0:
            reasons.append(f"{role}: exit {ex.get('exit_code')} ({ex.get('meaning')})")
    if prf.get("label") != night["night"]:
        reasons.append(f"proof labelled {prf.get('label')}, night is {night['night']}")
    start = (night.get("spine") or {}).get("start") or {}
    if "dirty_code" not in start:
        reasons.append("dirty state UNKNOWN (spine start row has no dirty_code)")
    elif start.get("dirty_code"):
        reasons.append(f"DIRTY: {', '.join(start['dirty_code'])}")
    return not reasons, reasons


def update_streak(night: str, clean: bool, reasons: list, path: Path = CLEAN) -> dict:
    """Moves once per night; a miss resets to 0 and records why."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        d = {"count": 0, "last_night": None, "history": []}
    if d.get("last_night") == night:
        return d
    d["count"] = d.get("count", 0) + 1 if clean else 0
    d["last_night"] = night
    d["history"] = (d.get("history") or []) + [{"night": night, "clean": clean, "reasons": reasons}]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return d


def forward_rows() -> list:
    from experiments.institution import forward_rows as fr
    out = []
    for p in sorted(fr.FORWARD_DIR.glob("F-*.json")):
        if p.name.count(".") != 1:
            continue
        row = json.loads(p.read_text(encoding="utf-8"))
        log = p.parent / f"{row['id']}.resolutions.jsonl"
        done = set()
        if log.exists():
            done = {json.loads(l).get("stage") for l in log.read_text(encoding="utf-8").splitlines() if l.strip()}
        stage = "provisional" if "PROVISIONAL" not in done else "final"
        m = re.search(r"\d{4}-\d{2}-\d{2}", row["resolution"][stage].get("expected", ""))
        out.append({"id": row["id"], "status": fr.status(row["id"], log),
                    "next": f"{stage} {m.group(0) if m else row['resolution'][stage].get('expected')}"})
    return out


def core_resident() -> bool | None:
    try:
        from core import model_window as mw
        return mw.cycle_local_model() in (mw.resident_models() or set())
    except Exception:  # noqa: BLE001
        return None


def compose(night: dict, prf: dict, streak: dict, clean: bool, reasons: list, rows: list,
            core: bool | None, ucdp: int) -> str:
    def line(role):
        x = night.get(role) or {}
        ex = x.get("exit")
        return (f"{role}: exit {ex.get('exit_code')}, {ex.get('wall_seconds')} s" if ex
                else f"{role}: NO EXIT ROW ({x.get('cycle_id')})")
    days = token_days(prf.get("token_expiration"))
    tok = ("unknown" if days is None else f"{days} days" + ("  ⚠ UNDER 30 - ROTATE" if days < TOKEN_WARN_DAYS else ""))
    start = (night.get("spine") or {}).get("start") or {}
    lines = [f"night {night.get('night')} (Europe/Sofia)",
             *(line(r) for r in ("collectors", "spine", "edges")),
             f"proof: {str(prf.get('sha'))[:10]} label [{prf.get('label')}] at {prf.get('date_utc')}",
             f"core resident: {'yes' if core else ('no' if core is False else 'unknown')}",
             f"UCDP requests today: {ucdp}",
             "forward rows: " + "; ".join(f"{r['id']} {r['status']} next {r['next']}" for r in rows),
             f"GITHUB_TOKEN expires in: {tok}"]
    if start.get("dirty_code"):
        lines.append("DIRTY: " + ", ".join(start["dirty_code"]))
    lines.append(f"clean nights in a row: {streak.get('count', 0)}/{STREAK_GOAL}"
                 + ("" if clean else " - missed: " + "; ".join(reasons)))
    return "\n".join(lines)


def delivered_today(day: str, path: Path = LOG) -> bool:
    try:
        return any(json.loads(l).get("day") == day and json.loads(l).get("status") == "delivered"
                   for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
    except FileNotFoundError:
        return False


def main(argv: list) -> int:
    dry = "--dry-run" in argv
    today = datetime.now().astimezone().date().isoformat()
    if not dry and delivered_today(today):
        print(f"[digest] already delivered for {today}; nothing to do")
        return 0
    rows = _rows()
    night = last_night(rows)
    prf = proof()
    clean, reasons = verdict(night, prf)
    streak = (update_streak(night["night"], clean, reasons) if (night and not dry)
              else json.loads(CLEAN.read_text(encoding="utf-8")) if CLEAN.exists() else {"count": 0})
    from core import ucdp_client as uc
    text = compose(night, prf, streak, clean, reasons, forward_rows(), core_resident(), uc.requests_today())
    print(text)
    if dry:
        return 0
    import supervisor
    status = supervisor.alarm_human(f"CORTEX morning digest {today}", text, dedup_key=f"digest:{today}",
                                    level=supervisor.NOTICE, cls="morning_digest")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "day": today,
                             "night": night.get("night"), "status": status, "clean": clean,
                             "streak": streak.get("count")}, ensure_ascii=False) + "\n")
    print(f"[digest] {status}")
    return 0 if status in ("delivered", "suppressed") else 6


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
