#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cortex_approval_server.py
Локален Flask сървър за одобрение на proposals.
Стартирай: python3 cortex_approval_server.py
После отвори: http://localhost:5000
"""
import json
import pathlib
from datetime import datetime, timedelta, timezone
from html import escape

from flask import Flask, jsonify

BASE_DIR = pathlib.Path(__file__).resolve().parent
PROPOSALS_FILE = BASE_DIR / "memory" / "improvement_proposals.json"
APPROVAL_QUEUE = BASE_DIR / "memory" / "approval_queue.json"
DASHBOARD_FILE = BASE_DIR / "output" / "cortex_dashboard_live.html"
SCORES_FILE = BASE_DIR / "output" / "cortex_scores_latest.json"

app = Flask(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: pathlib.Path) -> dict | list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# THE FRESHNESS GATE
# ---------------------------------------------------------------------------
# The dashboard served at "/" is a FILE ON DISK, not a live render. Nothing in the
# cycle writes it: `grep -rn "dashboard_generator" --include=*.py .` returns only that
# module's own docstring, and hypercortex_runner.py / fast_cycle_runner.py / run_daily.py
# never mention a dashboard at all. It is produced by hand, by running
# cortex_dashboard_generator.py as __main__.
#
# So the page drifts away from the data behind it. Measured 20 Aug 2026:
#
#     output/cortex_dashboard_live.html   Apr 13 17:29
#     output/cortex_scores_latest.json    Aug 20 04:33
#
# Four months apart, under a filename containing the word "live". This route was
# serving that April page — with the approval panel injected into it — as the surface
# an operator reads while deciding whether to approve a self-modification. The page
# carries its own timestamp, generated whenever it was last run by hand, so it looks
# current while showing scores from another season.
#
# This gate does not fix the generator and does not make the page fresh. The generator
# has no caller and its arithmetic is knowingly broken (its lines 148/150/151 fabricate
# 0.5 for an unmeasured domain, average domain means without the target_config weights,
# and default a score-less axis to 0.5 so a blind axis can never read as critical) —
# that is a separate decision and is deliberately untouched here.
#
# What this gate does is make staleness LOUD instead of silent. If the dashboard is
# older than the scores it purports to show, the dashboard is not served at all.
# ---------------------------------------------------------------------------

_PLAIN_CSS = """<style>
body { background:#0d0d0d; color:#ddd; margin:0; padding:2.5rem 2rem 45vh;
       font:14px/1.55 -apple-system, "Segoe UI", sans-serif; }
.wrap { max-width:780px; margin:0 auto; }
h1 { font-size:17px; font-weight:600; color:#E24B4A; margin:0 0 0.9rem; }
p.lede { color:#999; margin:0 0 1.3rem; }
table { border-collapse:collapse; width:100%; margin:0 0 1.3rem; }
td { border:0.5px solid #333; padding:7px 12px; vertical-align:top; }
td.k { color:#777; white-space:nowrap; width:1%; }
td.v { color:#EF9F27; font-family:ui-monospace, Consolas, monospace; font-size:13px;
       word-break:break-all; }
.note { color:#6f6f6f; font-size:12.5px; border-left:2px solid #333; padding-left:12px; }
code { color:#378ADD; font-family:ui-monospace, Consolas, monospace; }
</style>"""


def _mtime_utc(path: pathlib.Path) -> datetime:
    """Last-modified time of `path` as an aware UTC datetime."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _fmt(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _human_gap(gap: timedelta) -> str:
    seconds = int(gap.total_seconds())
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = [f"{days}d", f"{hours}h", f"{minutes}m"] if days else (
        [f"{hours}h", f"{minutes}m"] if hours else [f"{minutes}m", f"{secs}s"])
    return " ".join(parts)


def _plain_page(headline: str, rows: list[tuple[str, str]], note: str) -> str:
    """A dashboard-less page: the reason, the evidence, then the approval panel.

    The panel is still rendered — the operator can still read and judge proposals.
    What is withheld is the stale dashboard, so that no approval is ever made while
    looking at scores older than the data on disk.
    """
    rows_html = "".join(
        f"<tr><td class='k'>{escape(key)}</td><td class='v'>{escape(value)}</td></tr>"
        for key, value in rows
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>CORTEX++ approval — dashboard withheld</title>
{_PLAIN_CSS}</head>
<body><div class="wrap">
<h1>{escape(headline)}</h1>
<p class="lede">No dashboard was served on this page. Nothing you see above the
approval panel came from a rendered dashboard — do not read it as scores.</p>
<table>{rows_html}</table>
<div class="note">{note}</div>
</div>
{_build_approval_panel()}
</body></html>"""


_REGENERATE = ("Generate it by hand: "
               r"<code>venv\Scripts\python.exe cortex_dashboard_generator.py</code> "
               "(nothing in the cycle does this for you).")


@app.route("/")
def index():
    """Serve the dashboard with approval buttons — but never if it is stale."""
    if not DASHBOARD_FILE.exists():
        return _plain_page(
            "No dashboard has been generated.",
            [("expected at", str(DASHBOARD_FILE))],
            _REGENERATE + " The message here used to name hypercortex_runner.py, "
            "which does not generate the dashboard and never did.",
        )

    if not SCORES_FILE.exists():
        return _plain_page(
            "Dashboard freshness cannot be verified — withheld.",
            [
                ("dashboard written", _fmt(_mtime_utc(DASHBOARD_FILE))),
                ("scores file", f"{SCORES_FILE} — MISSING"),
            ],
            "The dashboard is withheld rather than vouched for: with no scores file "
            "there is nothing to compare its age against, and an unverifiable page is "
            "exactly the one an operator should not approve against.",
        )

    dashboard_at = _mtime_utc(DASHBOARD_FILE)
    scores_at = _mtime_utc(SCORES_FILE)

    if dashboard_at < scores_at:
        return _plain_page(
            "STALE DASHBOARD — withheld. The scores are newer than the page.",
            [
                ("dashboard written", _fmt(dashboard_at)),
                ("scores written", _fmt(scores_at)),
                ("dashboard is behind by", _human_gap(scores_at - dashboard_at)),
                ("dashboard file", str(DASHBOARD_FILE)),
                ("scores file", str(SCORES_FILE)),
            ],
            "The page would have shown scores older than the ones on disk, while "
            "carrying its own generation timestamp and a filename saying "
            "<code>live</code>. " + _REGENERATE,
        )

    content = DASHBOARD_FILE.read_text(encoding="utf-8")
    return content.replace("</body>", f"{_build_approval_panel()}</body>")


@app.route("/api/proposals")
def get_proposals():
    """Връща pending proposals."""
    data = _load_json(PROPOSALS_FILE)
    proposals = data.get("proposals", []) if isinstance(data, dict) else []
    pending = [
        {"index": i, **p}
        for i, p in enumerate(proposals)
        if not p.get("executed") and not p.get("approved") and not p.get("rejected")
    ]
    return jsonify(pending)


@app.route("/api/approve/<int:index>", methods=["POST"])
def approve(index: int):
    """Одобрява proposal по индекс."""
    data = _load_json(PROPOSALS_FILE)
    proposals = data.get("proposals", [])
    if index >= len(proposals):
        return jsonify({"error": "invalid index"}), 400

    proposals[index]["approved"] = True
    proposals[index]["approved_at"] = _utc_now()
    data["proposals"] = proposals
    _save_json(PROPOSALS_FILE, data)

    # Добави в approval_queue
    queue = _load_json(APPROVAL_QUEUE)
    if not isinstance(queue, list):
        queue = []
    queue.append({**proposals[index], "queued_at": _utc_now()})
    _save_json(APPROVAL_QUEUE, queue)

    return jsonify({"status": "approved", "index": index})


@app.route("/api/reject/<int:index>", methods=["POST"])
def reject(index: int):
    """Отхвърля proposal по индекс."""
    data = _load_json(PROPOSALS_FILE)
    proposals = data.get("proposals", [])
    if index >= len(proposals):
        return jsonify({"error": "invalid index"}), 400

    proposals[index]["rejected"] = True
    proposals[index]["rejected_at"] = _utc_now()
    data["proposals"] = proposals
    _save_json(PROPOSALS_FILE, data)

    return jsonify({"status": "rejected", "index": index})


def _build_approval_panel() -> str:
    """Генерира HTML панел за approval."""
    return """
<style>
#approval-panel {
  position: fixed; bottom: 0; left: 0; right: 0;
  background: #1a1a1a; border-top: 1px solid #333;
  padding: 1rem 1.5rem; z-index: 1000;
  max-height: 40vh; overflow-y: auto;
}
#approval-panel h3 { color: #fff; font-size: 13px; margin-bottom: 10px; font-weight: 500; }
.proposal-item {
  background: #222; border: 0.5px solid #333; border-radius: 8px;
  padding: 10px 14px; margin-bottom: 8px;
  display: flex; align-items: center; gap: 12px;
}
.proposal-text { flex: 1; font-size: 12px; color: #aaa; }
.proposal-component { font-size: 11px; color: #EF9F27; margin-bottom: 3px; }
.btn-approve {
  background: #1a3a1a; border: 0.5px solid #639922; color: #639922;
  padding: 5px 14px; border-radius: 6px; cursor: pointer; font-size: 12px;
}
.btn-approve:hover { background: #2a4a2a; }
.btn-reject {
  background: #3a1a1a; border: 0.5px solid #E24B4A; color: #E24B4A;
  padding: 5px 14px; border-radius: 6px; cursor: pointer; font-size: 12px;
}
.btn-reject:hover { background: #4a2a2a; }
.no-proposals { font-size: 12px; color: #555; }
#approval-toggle {
  position: fixed; bottom: 0; right: 1.5rem;
  background: #7F77DD; color: #fff; border: none;
  padding: 6px 16px; border-radius: 8px 8px 0 0;
  cursor: pointer; font-size: 12px; z-index: 1001;
}
</style>

<button id="approval-toggle" onclick="togglePanel()">⚙ Proposals</button>

<div id="approval-panel" style="display:none;">
  <h3>Pending proposals — одобри или отхвърли</h3>
  <div id="proposals-list"><div class="no-proposals">Зарежда...</div></div>
</div>

<script>
function togglePanel() {
  const p = document.getElementById('approval-panel');
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
  if (p.style.display === 'block') loadProposals();
}

// Every proposal field below is written by an LLM (goal_planner, self_observer) into
// memory/improvement_proposals.json and was being interpolated straight into innerHTML.
// A proposal whose text contained markup therefore executed in the approval page — the
// one page whose whole purpose is to let a human judge that proposal before it runs.
// The generated code was already shown as a flag, never as text, so nothing legitimate
// here needs HTML: escape all of it.
function esc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

async function loadProposals() {
  const res = await fetch('/api/proposals');
  const proposals = await res.json();
  const list = document.getElementById('proposals-list');
  if (!proposals.length) {
    list.innerHTML = '<div class="no-proposals">Няма pending proposals.</div>';
    return;
  }
  list.innerHTML = proposals.map(p => {
    const i = Number(p.index);          // an int from enumerate(); never a string
    return `
    <div class="proposal-item" id="prop-${i}">
      <div class="proposal-text">
        <div class="proposal-component">${esc(p.component || 'unknown')} · ${esc(p.priority || 'MEDIUM')}</div>
        <div>${esc(p.problem || '')}</div>
        ${p.solution ? `<div style="color:#666;margin-top:3px;">${esc(p.solution)}</div>` : ''}
        ${p.python_code ? '<div style="color:#378ADD;margin-top:3px;">📝 Съдържа python код</div>' : ''}
      </div>
      <button class="btn-approve" onclick="approve(${i})">✓ Approve</button>
      <button class="btn-reject" onclick="reject(${i})">✗ Reject</button>
    </div>`;
  }).join('');
}

async function approve(index) {
  await fetch('/api/approve/' + index, {method: 'POST'});
  document.getElementById('prop-' + index).style.opacity = '0.3';
  document.getElementById('prop-' + index).innerHTML += '<span style="color:#639922;margin-left:10px;">✓ Approved</span>';
}

async function reject(index) {
  await fetch('/api/reject/' + index, {method: 'POST'});
  document.getElementById('prop-' + index).style.opacity = '0.3';
  document.getElementById('prop-' + index).innerHTML += '<span style="color:#E24B4A;margin-left:10px;">✗ Rejected</span>';
}
</script>
"""


if __name__ == "__main__":
    # LOOPBACK ONLY. This server has NO authentication of any kind: anyone who can
    # reach port 5000 can approve or reject a self-modification proposal. Bound to
    # 0.0.0.0 it handed that power to every device on the LAN.
    #
    # Verified before narrowing it (17 Aug 2026), because closing a port the human
    # actually uses is its own kind of failure: nothing off-machine calls this. No
    # uvicorn, ngrok, cloudflared or tailscale anywhere in the repo; no code fetches
    # :5000; no scheduled task starts it; memory/approval_queue.json — the only thing
    # it writes — is read by nobody and last changed 13 Apr 2026. The human approval
    # gate that IS live runs over Telegram (memory/pending_approvals.json ->
    # experiments/needs/approve_reader.py), not over this port.
    #
    # If it turns out you do open this from a phone on the LAN, the opt-in is one
    # line — host = os.getenv("CORTEX_APPROVAL_HOST", "127.0.0.1") — but it must stay
    # closed by default and never go back to a bare 0.0.0.0.
    print("[APPROVAL SERVER] Стартира на http://127.0.0.1:5000 (само локално)")
    print("[APPROVAL SERVER] Спри с Ctrl+C")
    app.run(host="127.0.0.1", port=5000, debug=False)