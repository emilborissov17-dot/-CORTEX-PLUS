#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/server.py — READ-ONLY OVER memory/, ON 127.0.0.1, AND NOTHING ELSE.

WHY A SEPARATE APP AND NOT A BLUEPRINT ON cortex_approval_server.py
---------------------------------------------------------------------
The obvious move is a blueprint on the Flask app that already exists. It was
considered and rejected for three reasons, in order of weight:

  1. THAT APP APPROVES SELF-MODIFICATIONS. cortex_approval_server.py serves
     /api/approve/<i> and /api/reject/<i>, which apply and refuse patches. The
     cockpit's contract is "read-only plus exactly three named writes". Mounted
     together, that contract is only as strong as the neighbouring routes, and a
     reader checking it would have to audit both. Separate processes make the
     claim checkable by reading one file.
  2. THE COCKPIT NEEDS A WEBSOCKET AND A PTY. Bolting a terminal bridge onto the
     process that can approve a self-modification widens that process's surface
     for a feature that has nothing to do with approvals.
  3. LIFECYCLE. The approval server has a freshness gate around a hand-generated
     dashboard and is started when a human wants to approve something. The
     cockpit is a long-running read-only window. One crashing should not take the
     other down.

So: its own app, its own port, 127.0.0.1 only.

EXACTLY FOUR WRITEFUL ENDPOINTS EXIST IN THE WHOLE COCKPIT
------------------------------------------------------------
    POST /api/expression/seen     append-only mark-as-seen
    POST /api/ask                 append to human_input_queue (append-only sqlite)
    POST /api/toggle              mic_enabled / camera_enabled, and NOTHING else
    WS   /terminal                the terminal bridge (cockpit/terminal.py)

The fourth was added 22 Aug 2026. Fixing the count at three had made the mic and
camera switches unbuildable — the rule was protecting a number rather than the
property the number stood for. /api/toggle may write exactly two booleans in
config_expression.yaml; it rewrites those two lines in place and leaves every
other line of the file byte-identical, which a test asserts.

Everything else is GET and opens no file for writing. WRITE_ENDPOINTS below is
the list, and a test asserts that no other route accepts POST.

NO LLM CALLS. NO PUSH NOTIFICATIONS. NO OUTBOUND NETWORK except the single
manual forks refresh, which is fail-soft and disk-cached.

PATHS ARE PASSED EXPLICITLY, ALWAYS
-------------------------------------
Every writer in cockpit/ takes its path as a required argument. This module is
the only place the LIVE paths are named, and it names them at the call site. A
test therefore cannot accidentally write to memory/ by omitting an argument —
it would fail with a TypeError instead.

    venv/Scripts/python.exe -m cockpit.server --port 5055
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cockpit import datasources as ds          # noqa: E402
from cockpit import expression as ex           # noqa: E402
from cockpit import somatic as som             # noqa: E402
from cockpit import norms as nm                # noqa: E402
from cockpit import timeline as tl             # noqa: E402
from cockpit import pulse as pls               # noqa: E402

# ── THE LIVE PATHS. Named ONCE, here, and passed explicitly everywhere. ──────
STREAM_PATH = BASE / "memory" / "expression_stream.jsonl"
PENDING_PATH = BASE / "memory" / "pending_expression.json"
QUEUE_DB = BASE / "memory" / "human_input_queue.db"
QUARANTINE_ROOT = BASE / "memory" / "expression_quarantine"
VECTOR_STORE = BASE / "memory" / "state_vectors.jsonl"
HISTORY_PATH = BASE / "memory" / "somatic_history.jsonl"

# ── THE PULSE PRODUCER, WIRED (22 Aug 2026) ─────────────────────────────────
# It was committed in 2fb57be with tests and NO CALLER, so the stream stayed
# empty through two full cycles. One producer per server process, because the
# emission rule compares against the LAST EMITTED reading and a fresh producer
# per request would treat every reading as the first one and emit everything.
_PULSE = pls.PulseProducer()

# The last (cycle_id, step) a spine line was emitted for.
_SPINE_SEEN = {"cycle_id": None, "step": None}

# The previous probe's numeric readings, for the FIXED rule's fallback — it needs
# a "previous value" and a sensor with too little history has no norm to use
# instead. Kept in memory rather than re-read: this is the same process that
# took the previous probe.
_LAST_READING = {}
FORKS_CACHE = BASE / "memory" / "cockpit_forks_cache.json"
TERMINAL_LOG = BASE / "memory" / "cockpit_terminal.log"

FORKS_URL = "https://api.github.com/repos/emilborissov17-dot/-CORTEX-PLUS/forks"

DEFAULT_PORT = 5055
HOST = "127.0.0.1"          # never 0.0.0.0. A test asserts it.

WRITE_ENDPOINTS = ("/api/expression/seen", "/api/ask", "/api/toggle",
                   "/terminal")
CONFIG_EXPRESSION = BASE / "config_expression.yaml"

app = Flask(__name__, static_folder=str(pathlib.Path(__file__).parent / "static"),
            static_url_path="/static")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: pathlib.Path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_jsonl(path: pathlib.Path, limit: int = 500) -> list:
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _summarise(blob, cap: int = 400):
    """Top-level keys with long values truncated. Never invents, only shortens.

    The cockpit refreshes every 15 seconds. A panel that ships a 380 KB ledger
    each time is not more honest than one that ships its shape — it is the same
    information, delivered so slowly the reader stops opening it.
    """
    if blob is None:
        return None
    if isinstance(blob, dict):
        out = {}
        for k, v in blob.items():
            if isinstance(v, (dict, list)):
                out[k] = "<{} with {} entries>".format(type(v).__name__, len(v))
            else:
                out[k] = (str(v)[:cap] if isinstance(v, str) and len(str(v)) > cap
                          else v)
        return out
    if isinstance(blob, list):
        return "<list with {} entries>".format(len(blob))
    return blob


def last_sealed_cycle(ledger_path: pathlib.Path) -> Optional[dict]:
    """The last CYCLE_FINISHED seal. `ledger_path` is REQUIRED.

    Exists because the checklist used to render "(no cycle) 0/55" whenever no
    cycle was live, which is the least informative true statement available: it
    looks like a system that has never run. The last SEALED cycle is what a
    reader actually wants between runs.
    """
    rows = _read_jsonl(ledger_path, limit=4000)
    seals = [r for r in rows if r.get("event") == "CYCLE_FINISHED"]
    if not seals:
        return None
    last = seals[-1]
    return {"cycle_id": last.get("cycle_id"),
            "sealed_at": last.get("ts"),
            "duration_sec": last.get("duration_sec"),
            "pid": last.get("pid"),
            "outcome": "finished"}


def _warming() -> dict:
    """How far the lexicon is from existing. Never implies a glyph."""
    try:
        from cockpit import vector as vec
        return vec.warming(VECTOR_STORE)
    except Exception as e:                                   # noqa: BLE001
        return {"warm": False, "cycles": 0, "needed": 20,
                "label": "lexicon state unreadable",
                "why": "{}: {}".format(type(e).__name__, e)}


def no_data(panel: str) -> dict:
    """The honest-empty card. Names the missing paths; never fakes a shape.

    `missing` lists EVERY absent source, required or optional — not just the
    required ones. Panel.missing() counts only required files because that is
    what decides whether a panel is live; but a card that says "no data yet" and
    then names nothing is useless to the person trying to work out why, and the
    forks panel's only source is optional.
    """
    p = ds.PANELS_BY_KEY.get(panel)
    if not p:
        return {"no_data": True, "panel": panel, "missing": [], "note": "",
                "why": "unknown panel"}
    absent = [s.rel for s in p.sources if not s.exists()]
    return {"no_data": True, "panel": panel,
            "missing": absent, "required_missing": [s.rel for s in p.missing()],
            "note": p.note,
            "why": "the file(s) named above do not exist yet; nothing is invented "
                   "to fill the panel"}


# ---------------------------------------------------------------------------
# READ-ONLY ENDPOINTS
# ---------------------------------------------------------------------------

@app.get("/api/panels")
def api_panels():
    """The item-0 table, live. Which panels have data and which do not."""
    return jsonify({"ts": _now(), "panels": ds.table()})


@app.get("/api/cycles")
def api_cycles():
    """Cycles as checklists, with the EVIDENCE for each square distinguishable.

    THREE FAULTS FIXED HERE, all found by reading the live files rather than the
    code (22 Aug 2026, cycle 14:51 running):

    1. `ticks recorded 0` for the last sealed cycle. `ticks` was len(done), and
       `done` is the CURRENT cycle's checkpoint set — which is empty while a
       different cycle is running. The sealed cycle's own set is what it needed.

    2. EVERY STEP OF THE RUNNING CYCLE RENDERED "todo", which was true and
       useless. Checkpoints are written by _run() AFTER a step completes, and
       most steps are not wrapped in _run(): the earliest name that has ever
       been checkpointed is `cortexstrategist` at map position 16. A cycle at
       position 17 has legitimately produced zero checkpoints. So position is
       now used as a SECOND, WEAKER kind of evidence — `passed` — and it is
       rendered differently from `done` and labelled as inferred. A green square
       that means "we assume so" must not look like one that means "it is on
       record".

    3. TEN OF TWENTY-NINE CHECKPOINTS COULD NEVER LIGHT A SQUARE. alarm_bands,
       brain_relay, level_reconcile, needs_auth, proposal_sla, read_the_mirror,
       session_updater, metta_column, cortex_orchestrator and
       orchestrator_grounded are recorded as completed steps and appear in
       neither core.cycle_map.STEPS nor its ALIASES. They were being silently
       dropped, which is what made "ticks 29 / checklist 20" look like a
       rounding difference. They are now returned as `unmapped`, counted, and
       named, because a checkpoint nothing can display is a step nobody can see.
    """
    from core.cycle_map import STEPS
    try:
        from core.cycle_map import SUBSTEP, UNKNOWN, resolve
    except ImportError:                      # older map, no resolver
        from core.cycle_map import ALIASES
        SUBSTEP, UNKNOWN = "substep", "unknown"

        def resolve(name):
            canon = ALIASES.get(name, name)
            return canon, ("step" if canon != name else UNKNOWN)

    all_steps = [{"step": s[0], "index": s[1], "what": s[2]} for s in STEPS]
    names = [s["step"] for s in all_steps]
    pos = {n: i for i, n in enumerate(names)}

    resume = _read_jsonl(ds.BASE / "memory" / "cycle_resume.jsonl", limit=4000)
    heartbeat = _read_json(ds.BASE / "memory" / "heartbeat.json", {}) or {}
    survival = _read_json(ds.BASE / "memory" / "survival_state.json", {}) or {}
    contract = _read_json(ds.BASE / "memory" / "step_contract_latest.json", {}) or {}

    # ── ONE RESOLVER, NOT A LOCAL GUESS (23 Aug 2026) ─────────────────────
    # This used to apply ALIASES in both directions and call whatever was left
    # `unmapped`. core.cycle_map.resolve() now knows all three tables — steps,
    # aliases and SUBSTEPS — so cortex_orchestrator and orchestrator_grounded,
    # which are two _run()s inside cognitive_orchestrator's one beat, light that
    # step's square instead of being reported as names nothing can display.
    # A name that resolves to nothing is STILL reported: unmapped is now the
    # genuinely unknown, which is the only thing it was ever supposed to mean.
    by_cycle, unmapped_by_cycle, substeps_by_cycle = {}, {}, {}
    for row in resume:
        cid, step = row.get("cycle_id"), row.get("last_completed_step")
        if not cid or not step:
            continue
        canon, kind = resolve(step)
        if kind == SUBSTEP:
            substeps_by_cycle.setdefault(cid, set()).add(step)
        if canon in pos:
            # IDENTITY IS (NAME, INDEX). body_scan runs twice — index 0 before
            # everything and index 13 after the heavy steps — so a set of names
            # lit BOTH squares off one checkpoint and the checklist claimed one
            # more finished step than the log holds. The checkpoint has carried
            # its step_index all along; it just was not being read.
            by_cycle.setdefault(cid, set()).add(
                (canon, str(row.get("step_index") or "")))
        else:
            unmapped_by_cycle.setdefault(cid, set()).add(step)

    sealed = last_sealed_cycle(ds.BASE / "memory" / "existence_ledger.jsonl")
    live = som.cycle_is_live()

    current_cycle = heartbeat.get("cycle_id")
    current_step = heartbeat.get("step") if live else None
    if not live and sealed:
        current_cycle = sealed["cycle_id"]

    done = by_cycle.get(current_cycle, set())
    # An older checkpoint may carry no index; then the name alone is all the
    # evidence there is, and it lights whichever square matches by name.
    done_names = {name for name, idx in done if not idx}

    unmapped = sorted(unmapped_by_cycle.get(current_cycle, set()))

    # The heartbeat's step name resolved to a MAP POSITION. Its own step_index is
    # the runner's label ("4"), which is not the map's ordering.
    cur_name = resolve(current_step)[0] if current_step else None
    cur_pos = pos.get(cur_name) if cur_name else None

    checklist = []
    for i, s in enumerate(all_steps):
        if (s["step"], str(s["index"])) in done or s["step"] in done_names:
            state, evidence = "done", "checkpoint in cycle_resume.jsonl"
        elif s["step"] == cur_name:
            state, evidence = "current", "heartbeat"
        elif cur_pos is not None and i < cur_pos:
            state, evidence = "passed", "inferred: the heartbeat is past this step"
        else:
            state, evidence = "todo", ""
        checklist.append({**s, "state": state, "evidence": evidence})

    steps_blob = contract.get("steps") if isinstance(contract, dict) else None
    degraded = 0
    if isinstance(steps_blob, list):
        degraded = sum(1 for x in steps_blob
                       if isinstance(x, dict) and x.get("verdict") == "DEGRADED")

    sealed_done = by_cycle.get(sealed["cycle_id"], set()) if sealed else set()
    sealed_unmapped = sorted(unmapped_by_cycle.get(sealed["cycle_id"], set())) if sealed else []

    counts = {k: sum(1 for c in checklist if c["state"] == k)
              for k in ("done", "passed", "current", "todo")}

    return jsonify({
        "ts": _now(),
        "current_cycle": current_cycle,
        "current_step": current_step,
        "current_position": cur_pos,
        "heartbeat": heartbeat,
        "checklist": checklist,
        "total_steps": len(all_steps),
        "counts": counts,
        # done_count keeps its old meaning — CHECKPOINTED only. `covered` is the
        # number a human reads as "how far along is it".
        "done_count": counts["done"],
        "covered": counts["done"] + counts["passed"] + counts["current"],
        "substep_checkpoints": sorted(substeps_by_cycle.get(current_cycle, set())),
        "substep_note": ("recorded under a SUBSTEP name — a _run() inside "
                         "another step's beat() — and resolved to the step it "
                         "belongs to, not counted as a step of its own"),
        "unmapped_checkpoints": unmapped,
        "unmapped_note": ("recorded as completed but present in neither "
                          "cycle_map.STEPS nor ALIASES, so they can light no "
                          "square" if unmapped else ""),
        "cycles_seen": sorted(by_cycle, reverse=True)[:20],
        "live": live,
        "label": ("running now" if live else
                  "last completed cycle" if sealed else "no cycle has ever sealed"),
        "last_sealed": ({**sealed,
                         "ticks": len(sealed_done),
                         "unmapped": sealed_unmapped,
                         "outcome": "finished"}
                        if sealed else None),
        "badges": {
            "survival_latched": bool(survival.get("active")),
            "survival_reason": survival.get("reason"),
            "degraded_steps": degraded,
        },
    })


@app.get("/api/flow")
def api_flow():
    """Flow Score needle. Red zone below 2.0."""
    hist_path = ds.BASE / "memory" / "flow_score.jsonl"
    history = _read_jsonl(hist_path, limit=100)
    computed_now = None
    if not history:
        try:
            from core import flow_score as fs
            score = fs.compute()
            computed_now = score.as_dict() if hasattr(score, "as_dict") else dict(score)
        except Exception as e:
            computed_now = {"error": "{}: {}".format(type(e).__name__, e)}
    return jsonify({
        "ts": _now(),
        "history": history,
        "computed_now": computed_now,
        "computed_not_recalled": bool(computed_now),
        "red_below": 2.0,
        "note": ("memory/flow_score.jsonl has never been written; the number "
                 "shown is computed from memory/step_contract_latest.json right "
                 "now, and is labelled so."),
    })


@app.get("/api/forks")
def api_forks():
    """Disk-cached. Manual refresh only (?refresh=1). Fail-soft offline."""
    cached = _read_json(FORKS_CACHE, None)
    if not request.args.get("refresh"):
        if cached is None:
            return jsonify({**no_data("forks"),
                            "hint": "GET /api/forks?refresh=1 to fetch once"})
        return jsonify({**cached, "from_cache": True})
    try:
        import requests
        r = requests.get(FORKS_URL, timeout=10,
                         headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        rows = [{"full_name": f.get("full_name"), "html_url": f.get("html_url"),
                 "owner": (f.get("owner") or {}).get("login"),
                 "created_at": f.get("created_at"),
                 "stargazers_count": f.get("stargazers_count")}
                for f in r.json()]
        blob = {"ts": _now(), "count": len(rows), "forks": rows, "url": FORKS_URL}
        FORKS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        FORKS_CACHE.write_text(json.dumps(blob, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        return jsonify({**blob, "from_cache": False})
    except Exception as e:
        # FAIL SOFT: offline is a normal state, not an error page.
        return jsonify({"ts": _now(), "offline": True,
                        "error": "{}: {}".format(type(e).__name__, e),
                        "stale": cached,
                        "note": "the last cache is shown if there is one"})


def _age_days(ts) -> Optional[float]:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - t).total_seconds() / 86400.0, 1)
    except Exception:
        return None


def _triage_verdicts() -> dict:
    """filename -> JUNK|REVIEW, read from the triage document.

    The verdicts live in docs/QUARANTINE_TRIAGE_2026-08-22.md, which is the
    record a human already produced. Re-deriving them here would be a second
    opinion nobody asked for and would drift from the one in the repo.
    """
    doc = ds.BASE / "docs" / "QUARANTINE_TRIAGE_2026-08-22.md"
    out = {}
    try:
        for line in doc.read_text(encoding="utf-8").splitlines():
            if line.startswith("| ") and "_patch." in line and "**" in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                name = next((c.strip("`") for c in cells if "_patch." in c), None)
                verdict = next((c.strip("*") for c in cells if "**" in c), None)
                if name and verdict:
                    out[name] = verdict
    except OSError:
        pass
    return out


@app.get("/api/pending")
def api_pending():
    """Everything waiting on a human — AS ITEMS, not as counts.

    A count tells the operator that something is waiting and nothing about what.
    Four numbers on a panel is four reasons to open a terminal; four LISTS is a
    panel somebody can read. Each row carries what it needs to be judged (id,
    title, author, age; axis and value; filename and triage verdict) and its own
    prefill command, so reading and acting stay in the same place.
    """
    imp = _read_json(ds.BASE / "memory" / "improvement_proposals.json", {}) or {}
    raw = imp.get("proposals") if isinstance(imp, dict) else imp
    decided = ("approved", "rejected", "executed", "applied", "dismissed")
    proposals = []
    for i, r in enumerate(raw or []):
        if not isinstance(r, dict) or any(r.get(f) for f in decided):
            continue
        proposals.append({
            "id": "imp:{}".format(i),
            "title": str(r.get("problem") or r.get("component") or "?")[:120],
            "component": r.get("component"),
            "author": str(r.get("generated_by") or "(unattributed)"),
            "age_days": _age_days(r.get("timestamp")),
            "priority": r.get("priority"),
            "prefill": "venv\\Scripts\\python.exe cortex_approval_server.py",
        })
    proposals.sort(key=lambda x: -(x["age_days"] or 0))

    thr = _read_json(ds.BASE / "memory" / "threshold_proposals.json", {}) or {}
    thresholds = [{
        "id": "thr:{}".format(t.get("axis")),
        "axis": t.get("axis"),
        "suggested": t.get("suggested"),
        "target": t.get("target"),
        "basis": t.get("basis"),
        "direction": t.get("direction"),
        "prefill": "venv\\Scripts\\python.exe -c \"import json;print(json.load("
                   "open('memory/threshold_proposals.json',encoding='utf-8'))"
                   "['proposals'])\"",
    } for t in (thr.get("proposals") or []) if t.get("suggested") is not None]

    qdir = ds.BASE / "patches" / "quarantine"
    verdicts = _triage_verdicts()
    quarantine = []
    if qdir.is_dir():
        for p in sorted(qdir.glob("*_patch.*.py")):
            quarantine.append({
                "id": "qua:{}".format(p.name),
                "file": p.name,
                "bytes": p.stat().st_size,
                "verdict": verdicts.get(p.name, "(not in the 22 Aug triage)"),
                "prefill": "venv\\Scripts\\python.exe scripts/review_quarantine.py "
                           "--show {}".format(p.name),
            })

    appr = _read_json(ds.BASE / "memory" / "pending_approvals.json", {}) or {}
    telegram = []
    for key, row in (appr.get("approvals") or {}).items():
        row = row if isinstance(row, dict) else {}
        telegram.append({
            "id": key,
            "label": str(row.get("label") or row.get("type") or "?")[:80],
            "axis": row.get("axis"),
            "type": row.get("type"),
            "need": str(row.get("need") or "")[:140],
            "prefill": "venv\\Scripts\\python.exe experiments/needs/approve_reader.py",
            "reply": "OK {}".format(key),
        })

    return jsonify({
        "ts": _now(),
        "queues": {
            "proposals": {"count": len(proposals), "rows": proposals[:50]},
            "thresholds": {"count": len(thresholds), "rows": thresholds[:50]},
            "quarantine": {"count": len(quarantine), "rows": quarantine[:50]},
            "telegram": {"count": len(telegram), "rows": telegram[:50]},
        },
        "prefill_note": ("every button TYPES its command into the terminal. "
                         "Nothing here approves anything — you read it and press "
                         "Enter."),
        # kept so older callers and the OVERVIEW tab keep working
        "improvement_proposals": {"open": len(proposals), "rows": proposals[:50]},
        "threshold_proposals": {"unsigned": len(thresholds), "rows": thresholds[:50]},
        "quarantined_patches": {"count": len(quarantine),
                                "rows": [q["file"] for q in quarantine[:50]]},
        "sla_queue": _read_json(ds.BASE / "memory" / "proposal_sla_queue.json", None)
                     or no_data("pending"),
        "deferred_batch": _read_json(ds.BASE / "memory" / "deferred_batch.json", None),
        "openclaw_level_3": _read_json(
            ds.BASE / "memory" / "openclaw_pending_l3.json", None),
    })


@app.get("/api/thoughts")
def api_thoughts():
    """Per-phase debriefs INCLUDING rejected attempts, stance, ideas, dream."""
    debrief_dir = ds.BASE / "memory" / "phase_debriefs"
    cycles = sorted((p for p in debrief_dir.glob("*") if p.is_dir()),
                    key=lambda p: p.name, reverse=True)[:3]
    debriefs = []
    for cdir in cycles:
        for f in sorted(cdir.glob("*.json")):
            blob = _read_json(f, {}) or {}
            attempts = blob.get("attempt_log") or []
            debriefs.append({
                "cycle": cdir.name,
                "phase": blob.get("phase") or f.stem,
                "model": blob.get("model"),
                "accepted": blob.get("accepted"),
                "attempts": blob.get("attempts"),
                "seconds": blob.get("seconds"),
                # REJECTED ATTEMPTS ARE SHOWN. A debrief that only displays the
                # accepted answer hides how many tries it took to get one.
                # The text is TRUNCATED, not dropped: the full attempt log across
                # three cycles is 580 KB, which at a 15-second refresh is a
                # sluggish page rather than a useful one. The count and the
                # verdict are what the panel is for; the file is one click away.
                "attempt_log": [{"prompt": a.get("prompt"),
                                 "accepted": a.get("accepted"),
                                 "said": json.dumps(a.get("said"),
                                                    ensure_ascii=False)[:600]}
                                for a in attempts],
                "rejected_count": sum(1 for a in attempts
                                      if a.get("accepted") is False),
            })

    dreams_dir = ds.BASE / "experiments" / "dreams"
    dream_notes = sorted(p.name for p in dreams_dir.glob("*.md")
                         if p.name != "README.md") if dreams_dir.is_dir() else []
    latest_dream = None
    if dream_notes:
        latest_dream = {"file": dream_notes[-1],
                        "text": (dreams_dir / dream_notes[-1]).read_text(
                            encoding="utf-8", errors="replace")[:4000]}

    return jsonify({
        "ts": _now(),
        "stance": _read_json(ds.BASE / "memory" / "brain_stance.json", {}),
        "debriefs": debriefs,
        "ideas": _read_jsonl(ds.BASE / "memory" / "idea_stream.jsonl", limit=40),
        "dream": latest_dream or {**no_data("thoughts"),
                                  "missing": ["experiments/dreams/YYYY-MM-DD.md"],
                                  "why": "no dream note has been written yet"},
        # SUMMARISED, not dumped. The grounding ledger's last 40 rows are 380 KB
        # and the mirror another 142 KB; at a 15-second refresh that is a page
        # that stutters while showing the reader nothing they asked for. The
        # panel needs the shape and the count, and the file is one click away.
        "mirror": _summarise(_read_json(
            ds.BASE / "memory" / "self_mirror_latest.json", None)),
        "hypotheses": [_summarise(h) for h in
                       _read_jsonl(ds.BASE / "memory" / "hypotheses.jsonl", limit=20)],
        "grounding": [_summarise(g) for g in
                      _read_jsonl(ds.BASE / "memory" / "grounding_ledger.jsonl",
                                  limit=20)],
    })


@app.get("/api/proposals")
def api_proposals():
    """Grouped by AUTHOR MODEL. The field is `generated_by`, not `authored_by`."""
    imp = _read_json(ds.BASE / "memory" / "improvement_proposals.json", {}) or {}
    rows = imp.get("proposals") if isinstance(imp, dict) else imp
    groups = {}
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        # 18 of 40 rows carry no author at all. They get their own visible group
        # rather than being dropped or silently attributed to anyone.
        author = str(r.get("generated_by") or "(unattributed)")
        groups.setdefault(author, []).append({
            "component": r.get("component"), "problem": r.get("problem"),
            "timestamp": r.get("timestamp"), "priority": r.get("priority"),
            "approved": bool(r.get("approved")), "rejected": bool(r.get("rejected")),
        })
    return jsonify({
        "ts": _now(),
        "field_used": "generated_by",
        "groups": {k: {"count": len(v), "rows": v[:40]}
                   for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))},
        "total": sum(len(v) for v in groups.values()),
    })


@app.get("/api/goal")
def api_goal():
    """Goal composite, the 5 subgoals, the 25 axes, and the 7 continents."""
    history = _read_json(ds.BASE / "memory" / "goal_score_history.json", []) or []
    scores = _read_json(ds.BASE / "output" / "cortex_scores_latest.json", {}) or {}
    target = _read_json(ds.BASE / "config" / "target_config.json", {}) or {}

    tree = {}
    for subgoal, block in target.items():
        if subgoal == "_meta" or not isinstance(block, dict):
            continue
        tree[subgoal] = [{"axis": a,
                          "weight": (block[a] or {}).get("weight"),
                          "target": (block[a] or {}).get("target_value")}
                         for a in block]

    try:
        from core import continents as C
        regions = C.load()
        computed_at = C.computed_at()
    except Exception as e:
        regions, computed_at = [], "unavailable: {}".format(type(e).__name__)

    return jsonify({
        "ts": _now(),
        "composite_history": history[-60:],
        "latest_scores": scores,
        "tree": tree,
        "subgoal_count": len(tree),
        "axis_count": sum(len(v) for v in tree.values()),
        "continents": regions,
        "continents_computed_at": computed_at,
    })


@app.get("/api/columns")
def api_columns():
    """The FIVE columns. Empty by construction until something writes them."""
    from core import three_columns as tc
    records = tc.load_records()
    return jsonify({
        "ts": _now(),
        "column_order": list(tc.DISPLAY_COLUMNS),
        "column_spec": {k: {"title": v.title, "refines": v.refines,
                            "pipeline": v.pipeline, "pipeline_kind": v.pipeline_kind,
                            "why": v.why}
                        for k, v in tc.COLUMN_SPEC.items()},
        "independence_violations": tc.assert_columns_independent(),
        "lifecycle_ladder": tc.LIFECYCLE_LADDER,
        "ladder_note": ("this panel shows the SOURCE_LIFECYCLE state. There is no "
                        "SHADOW in that ladder; SHADOW is a row status in "
                        "scripts/openclaw_axis_worker.py and is a different thing."),
        "records": records,
        "record_count": len(records),
        "empty_because": (None if records else
                          "core/three_columns.py is not wired: nothing writes "
                          "memory/columns/ yet"),
    })


@app.get("/api/expression")
def api_expression():
    """The one stream, filtered by preset. Plus the rejected quarantine."""
    preset = request.args.get("filter", "ALL")
    lines = ex.read_stream(STREAM_PATH, limit=500)
    filtered = ex.apply_filter(lines, preset)
    return jsonify({
        "ts": _now(),
        "filter": preset.upper(),
        "presets": sorted(ex.FILTER_PRESETS),
        "lines": filtered,
        "line_count": len(filtered),
        "total_in_stream": len(lines),
        "unread": ex.pending_unread(STREAM_PATH, PENDING_PATH),
        "populated_cells": sorted("{}+{}".format(s, d)
                                  for s, d in ex.POPULATED_CELLS),
        "rejected": ex.read_rejected(QUARANTINE_ROOT),
        "grammar": {"forms": list(ex.FORMS), "max_tokens": ex.MAX_TOKENS,
                    "banned_groups": sorted(ex.BANNED_GROUPS)},
        "lexicon": _warming(),
        "empty_because": (None if lines else
                          "no expression line has been generated yet"),
    })


@app.get("/api/timeline")
def api_timeline():
    """THE WINDOW RENDERS WHAT THE SYSTEM ALREADY SAYS — it does not produce it.

    The expression window used to show one thin channel of its own while the
    plan, the stances, the phase debriefs, the autopsy, the reconsider decision
    and the report all went to Telegram and to a file and to no window. This
    merges every one of those into ONE timeline, ordered by the timestamp its
    own writer stamped, with the pulse between them. The model's lines are in
    it unchanged, as one source among several.

    ?cycle=<cycle_id> scopes it; the default is the last cycle that sealed.
    """
    cycle = request.args.get("cycle") or None
    try:
        limit = max(1, min(2000, int(request.args.get("limit", 600))))
    except ValueError:
        limit = 600
    blob = tl.collect(cycle, limit=limit,
                      include_pulse=request.args.get("pulse", "1") != "0")
    return jsonify({**blob, "cycles_available": _timeline_cycles()})


def _timeline_cycles(limit: int = 20) -> list:
    """The cycle ids a timeline can be asked for, newest first."""
    rows = _read_jsonl(ds.BASE / "memory" / "existence_ledger.jsonl", limit=4000)
    seen = []
    for row in reversed(rows):
        cid = row.get("cycle_id")
        if cid and cid not in seen:
            seen.append(cid)
        if len(seen) >= limit:
            break
    return seen


def _spine_if_step_changed(heartbeat: dict) -> list:
    """One spine line per cycle step, derived from the HEARTBEAT.

    The runner is the natural place to emit these and it is the live cycle's own
    file, so it is out of bounds while one is running. This watches the heartbeat
    instead and emits when the step name changes.

    HONEST LIMIT, and it is not small: this only sees a step if the cockpit is
    polled while that step is current. A step shorter than the poll interval is
    missed entirely, so the spine is a sampling of the timeline rather than the
    timeline. The line says `spine_source: heartbeat` so nobody reads it as the
    runner's own record.
    """
    cid, step = heartbeat.get("cycle_id"), heartbeat.get("step")
    if not cid or not step:
        return []
    if _SPINE_SEEN["cycle_id"] == cid and _SPINE_SEEN["step"] == step:
        return []
    _SPINE_SEEN["cycle_id"], _SPINE_SEEN["step"] = cid, step
    line = _PULSE.spine(step, heartbeat.get("step_index") or "")
    line["spine_source"] = "heartbeat"
    ex.append_line(line, path=STREAM_PATH)
    return [line]


@app.get("/api/somatic")
def api_somatic():
    """Live sensor read, AND the pulse emission rule for what it found.

    The mic/camera arguments are None unless explicitly given. They used to
    default to False, which meant every ordinary page refresh passed an explicit
    "off" and OVERRODE the operator's own toggle — the switch wrote true into
    config_expression.yaml and the panel went on reading DISABLED.
    """
    mic = True if request.args.get("mic") == "1" else None
    cam = True if request.args.get("camera") == "1" else None
    r = som.probe(mic_enabled=mic, camera_enabled=cam)

    # ── THE READINGS ARE KEPT NOW (23 Aug 2026) ───────────────────────────
    # This endpoint has been probing every 15 seconds and throwing the numbers
    # away: only readings that EARNED a pulse line were stored, and stored as
    # prose. So "rank by what is unusual for this machine" had no history to be
    # computed from — cockpit/norms.py is the norm, and this line is the half
    # of it that was missing. Never takes the panel down.
    previous = dict(_LAST_READING)
    try:
        nm.record(r, HISTORY_PATH)
        _LAST_READING.clear()
        _LAST_READING.update(nm.flatten(r))
    except Exception as e:                                   # noqa: BLE001
        print("[COCKPIT] somatic history: {}: {}".format(type(e).__name__, e))

    emitted = []
    try:
        emitted = _PULSE.emit(r)
        for line in emitted:
            ex.append_line(line, path=STREAM_PATH)
        heartbeat = _read_json(ds.BASE / "memory" / "heartbeat.json", {}) or {}
        emitted += _spine_if_step_changed(heartbeat)
    except Exception as e:                                   # noqa: BLE001
        # A failed pulse must never take the panel down: the readings are the
        # point and the stream is a by-product.
        emitted = [{"error": "{}: {}".format(type(e).__name__, e)}]

    rows = [row for rows_ in (r.get("groups") or {}).values() for row in rows_]
    return jsonify({**r, "state_vector": som.state_vector(r),
                    "pulse_emitted": len(emitted),
                    "pulse_lines": emitted,
                    # WHAT IS UNUSUAL FOR THIS MACHINE, beside what merely
                    # moved. Each row says which rule judged it.
                    "unusual": nm.unusual_now(rows, HISTORY_PATH,
                                              previous=previous)})


# ── GLASS — A WINDOW, NOT A SENSE (23 Aug 2026) ────────────────────────────
# THIS ENDPOINT TAKES NO READING. It renders the newest cycle log, the firewall
# log tail and the network counters the somatic endpoint ALREADY read — passed
# in from _LAST_READING, which /api/somatic fills on its own schedule.
#
# That is the whole point and it is the bug from two days ago stated as a rule:
# /api/somatic probed every 15 seconds and threw the numbers away, so a panel
# meant to display the body was a second, disagreeing body. A viewer is a
# visitor with the chart, not a nurse with a thermometer.
#
# test/test_glass.py counts guarded probes with the tab shut and again after
# rendering it repeatedly, and the two numbers must match.
@app.get("/api/glass")
def api_glass():
    from cockpit import glass as gl
    try:
        return jsonify(gl.render(last_reading=dict(_LAST_READING)))
    except Exception as e:                                   # noqa: BLE001
        return jsonify({"error": "{}: {}".format(type(e).__name__, e),
                        "label": gl.LABEL})


@app.get("/api/somatic/selftest")
def api_somatic_selftest():
    return jsonify(som.selftest())


# ---------------------------------------------------------------------------
# THE THREE WRITEFUL ENDPOINTS
# ---------------------------------------------------------------------------

@app.post("/api/expression/seen")
def api_expression_seen():
    """WRITEFUL 1 of 3. Append-only mark-as-seen."""
    body = request.get_json(silent=True) or {}
    ts_list = body.get("ts") or []
    if isinstance(ts_list, str):
        ts_list = [ts_list]
    result = ex.pending_mark_seen(ts_list, path=PENDING_PATH)
    return jsonify({"ok": True, **result,
                    "unread": ex.pending_unread(STREAM_PATH, PENDING_PATH)})


@app.post("/api/ask")
def api_ask():
    """WRITEFUL 2 of 3. Append one human question to the append-only queue."""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty question"}), 400
    try:
        row = ex.queue_append(text, db_path=QUEUE_DB, tag=body.get("tag"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, **row,
                    "note": "answered on the next cycle or micro-cycle; "
                            "DEEP questions return later tagged 8b-deferred"})


@app.get("/api/ask")
def api_ask_read():
    return jsonify({"ts": _now(), "queue": ex.queue_read(db_path=QUEUE_DB)})


TOGGLE_KEYS = ("mic_enabled", "camera_enabled")


def _write_toggles(values: dict, config_path: pathlib.Path) -> dict:
    """WRITEFUL 3 of 4. Rewrites exactly two lines. `config_path` is REQUIRED.

    LINE-LEVEL, NOT yaml.safe_dump(). Round-tripping through the yaml loader
    would silently reformat the file and DELETE EVERY COMMENT — and this file is
    mostly comments, including the ones explaining what silence_mode is for and
    why naming lives apart from clustering. A writer that erases the reasoning
    around it is not a small write.

    Only keys in TOGGLE_KEYS are touched. A key that is not in the file is
    appended; nothing else is reordered, reformatted or removed.
    """
    p = pathlib.Path(config_path)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    wanted = {k: bool(v) for k, v in values.items() if k in TOGGLE_KEYS}
    seen = set()
    out = []
    for line in lines:
        stripped = line.lstrip()
        hit = None
        for k in wanted:
            if stripped.startswith(k + ":"):
                hit = k
                break
        if hit:
            out.append("{}: {}\n".format(hit, "true" if wanted[hit] else "false"))
            seen.add(hit)
        else:
            out.append(line)
    for k in wanted:
        if k not in seen:
            out.append("{}: {}\n".format(k, "true" if wanted[k] else "false"))
    p.write_text("".join(out), encoding="utf-8")
    return som.toggles(p)


@app.post("/api/toggle")
def api_toggle():
    """WRITEFUL 3 of 4. The mic and camera switches, and nothing else.

    Refuses any key that is not one of the two. The refusal is explicit rather
    than a silent filter: a caller sending `silence_mode` should be told it was
    ignored, not left believing it was applied.
    """
    body = request.get_json(silent=True) or {}
    unknown = sorted(set(body) - set(TOGGLE_KEYS))
    if unknown:
        return jsonify({"ok": False,
                        "error": "this endpoint may write only {}; refused {}".format(
                            ", ".join(TOGGLE_KEYS), ", ".join(unknown))}), 400
    if not body:
        return jsonify({"ok": True, "toggles": som.toggles(CONFIG_EXPRESSION),
                        "note": "nothing to change"})
    now = _write_toggles(body, config_path=CONFIG_EXPRESSION)
    return jsonify({"ok": True, "toggles": now,
                    "note": "the somatic probe re-reads this file on every call"})


@app.get("/api/toggle")
def api_toggle_read():
    return jsonify({"ts": _now(), "toggles": som.toggles(CONFIG_EXPRESSION),
                    "writable_keys": list(TOGGLE_KEYS)})


# ---------------------------------------------------------------------------

@app.get("/favicon.ico")
def favicon():
    """Served locally like everything else. A 404 in the console on every load
    trains the reader to ignore the console, which is where the terminal token
    and the bridge errors appear."""
    return send_from_directory(
        str(pathlib.Path(__file__).parent / "static"), "favicon.svg",
        mimetype="image/svg+xml")


@app.get("/favicon.svg")
def favicon_svg():
    return send_from_directory(
        str(pathlib.Path(__file__).parent / "static"), "favicon.svg",
        mimetype="image/svg+xml")


# The token the running bridge is using. Set by main() AFTER start_bridge();
# None when the bridge did not start, and the page then shows the field empty
# with the reason rather than a box that silently never works.
_SESSION_TOKEN: Optional[str] = None


@app.get("/")
def index():
    """The page, with the terminal token injected.

    WHY INJECTING IT IS NOT A WEAKENING. The token's job is to stop OTHER
    software on this machine from driving a shell through the bridge. The page
    is served from 127.0.0.1 to a browser the operator opened; anything that can
    fetch this HTML can already reach every other cockpit endpoint. Making the
    human copy a hex string from a console into a field protects nothing and
    guarantees the field is sometimes pasted wrong — which is exactly how the
    terminal ended up disconnected while its buttons looked live.

    What DOES the work is on the socket: the token is still required on the
    handshake, and the handshake now also verifies the Origin, so a page from
    any other origin is refused even holding a valid token.

    Still never written to memory/cockpit_terminal.log.
    """
    html = (pathlib.Path(__file__).parent / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    token = _SESSION_TOKEN or ""
    return html.replace("__COCKPIT_TOKEN__", token), 200, {
        "Content-Type": "text/html; charset=utf-8"}


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="CORTEX++ cockpit (read-only, local)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--no-terminal", action="store_true",
                   help="do not start the terminal websocket bridge")
    args = p.parse_args(argv)

    global _SESSION_TOKEN
    token = None
    if not args.no_terminal:
        try:
            from cockpit import terminal
            token = terminal.start_bridge(log_path=TERMINAL_LOG,
                                          http_port=args.port)
            _SESSION_TOKEN = token
        except Exception as e:
            print("[COCKPIT] terminal bridge NOT started: {}: {}".format(
                type(e).__name__, e))

    print("=" * 72)
    print("CORTEX++ COCKPIT — http://{}:{}".format(HOST, args.port))
    print("  read-only over memory/. Three writeful endpoints: {}".format(
        ", ".join(WRITE_ENDPOINTS)))
    if token:
        # PRINTED ONLY HERE, to this console. Never served, never logged.
        print("  terminal session token: {}".format(token))
    print("=" * 72)
    app.run(host=HOST, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
