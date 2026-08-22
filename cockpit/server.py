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

# ── THE LIVE PATHS. Named ONCE, here, and passed explicitly everywhere. ──────
STREAM_PATH = BASE / "memory" / "expression_stream.jsonl"
PENDING_PATH = BASE / "memory" / "pending_expression.json"
QUEUE_DB = BASE / "memory" / "human_input_queue.db"
QUARANTINE_ROOT = BASE / "memory" / "expression_quarantine"
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
    """Cycles as checklists: green = checkpointed, current = heartbeat, grey = rest."""
    from core.cycle_map import STEPS
    all_steps = [{"step": s[0], "index": s[1], "what": s[2]} for s in STEPS]

    resume = _read_jsonl(ds.BASE / "memory" / "cycle_resume.jsonl", limit=2000)
    heartbeat = _read_json(ds.BASE / "memory" / "heartbeat.json", {}) or {}
    survival = _read_json(ds.BASE / "memory" / "survival_state.json", {}) or {}
    contract = _read_json(ds.BASE / "memory" / "step_contract_latest.json", {}) or {}

    by_cycle = {}
    for row in resume:
        cid = row.get("cycle_id")
        if not cid:
            continue
        by_cycle.setdefault(cid, set()).add(row.get("last_completed_step"))

    current_cycle = heartbeat.get("cycle_id")
    done = by_cycle.get(current_cycle, set())
    current_step = heartbeat.get("step")

    checklist = []
    for s in all_steps:
        state = ("done" if s["step"] in done else
                 "current" if s["step"] == current_step else "todo")
        checklist.append({**s, "state": state})

    steps_blob = contract.get("steps") if isinstance(contract, dict) else None
    degraded = 0
    if isinstance(steps_blob, list):
        degraded = sum(1 for x in steps_blob
                       if isinstance(x, dict) and x.get("verdict") == "DEGRADED")

    return jsonify({
        "ts": _now(),
        "current_cycle": current_cycle,
        "current_step": current_step,
        "heartbeat": heartbeat,
        "checklist": checklist,
        "total_steps": len(all_steps),
        "done_count": sum(1 for c in checklist if c["state"] == "done"),
        "cycles_seen": sorted(by_cycle, reverse=True)[:20],
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


@app.get("/api/pending")
def api_pending():
    """Everything waiting on a human."""
    imp = _read_json(ds.BASE / "memory" / "improvement_proposals.json", {}) or {}
    rows = imp.get("proposals") if isinstance(imp, dict) else imp
    decided = ("approved", "rejected", "executed", "applied", "dismissed")
    open_props = [r for r in (rows or [])
                  if isinstance(r, dict) and not any(r.get(f) for f in decided)]

    thr = _read_json(ds.BASE / "memory" / "threshold_proposals.json", {}) or {}
    unsigned = [t for t in (thr.get("proposals") or [])
                if t.get("suggested") is not None]

    qdir = ds.BASE / "patches" / "quarantine"
    quarantined = sorted(p.name for p in qdir.glob("*_patch.*.py")) if qdir.is_dir() else []

    sla = _read_json(ds.BASE / "memory" / "proposal_sla_queue.json", None)
    deferred = _read_json(ds.BASE / "memory" / "deferred_batch.json", None)
    l3 = _read_json(ds.BASE / "memory" / "openclaw_pending_l3.json", None)

    return jsonify({
        "ts": _now(),
        "improvement_proposals": {"open": len(open_props),
                                  "rows": open_props[:50]},
        "threshold_proposals": {"unsigned": len(unsigned), "rows": unsigned[:50]},
        "quarantined_patches": {"count": len(quarantined), "rows": quarantined[:50]},
        "sla_queue": sla if sla else no_data("pending"),
        "deferred_batch": deferred,
        "openclaw_level_3": l3,
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
        "empty_because": (None if lines else
                          "no expression line has been generated yet"),
    })


@app.get("/api/somatic")
def api_somatic():
    """Live sensor read. Mic and camera stay off unless explicitly toggled on."""
    mic = request.args.get("mic") == "1"
    cam = request.args.get("camera") == "1"
    r = som.probe(mic_enabled=mic, camera_enabled=cam)
    return jsonify({**r, "state_vector": som.state_vector(r)})


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

@app.get("/")
def index():
    return send_from_directory(str(pathlib.Path(__file__).parent / "templates"),
                               "cockpit.html")


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="CORTEX++ cockpit (read-only, local)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--no-terminal", action="store_true",
                   help="do not start the terminal websocket bridge")
    args = p.parse_args(argv)

    token = None
    if not args.no_terminal:
        try:
            from cockpit import terminal
            token = terminal.start_bridge(log_path=TERMINAL_LOG)
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
