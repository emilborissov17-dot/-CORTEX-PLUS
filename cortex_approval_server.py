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
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_file

BASE_DIR = pathlib.Path(__file__).resolve().parent
PROPOSALS_FILE = BASE_DIR / "memory" / "improvement_proposals.json"
APPROVAL_QUEUE = BASE_DIR / "memory" / "approval_queue.json"
DASHBOARD_FILE = BASE_DIR / "output" / "cortex_dashboard_live.html"

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


@app.route("/")
def index():
    """Serve dashboard с approval бутони."""
    if DASHBOARD_FILE.exists():
        content = DASHBOARD_FILE.read_text(encoding="utf-8")
        # Инжектирай approval панел преди </body>
        approval_panel = _build_approval_panel()
        content = content.replace("</body>", f"{approval_panel}</body>")
        return content
    return "<h2>Dashboard не е генериран още. Пусни hypercortex_runner.py първо.</h2>"


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

async function loadProposals() {
  const res = await fetch('/api/proposals');
  const proposals = await res.json();
  const list = document.getElementById('proposals-list');
  if (!proposals.length) {
    list.innerHTML = '<div class="no-proposals">Няма pending proposals.</div>';
    return;
  }
  list.innerHTML = proposals.map(p => `
    <div class="proposal-item" id="prop-${p.index}">
      <div class="proposal-text">
        <div class="proposal-component">${p.component || 'unknown'} · ${p.priority || 'MEDIUM'}</div>
        <div>${p.problem || ''}</div>
        ${p.solution ? `<div style="color:#666;margin-top:3px;">${p.solution}</div>` : ''}
        ${p.python_code ? '<div style="color:#378ADD;margin-top:3px;">📝 Съдържа python код</div>' : ''}
      </div>
      <button class="btn-approve" onclick="approve(${p.index})">✓ Approve</button>
      <button class="btn-reject" onclick="reject(${p.index})">✗ Reject</button>
    </div>`).join('');
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
    print("[APPROVAL SERVER] Стартира на http://localhost:5000")
    print("[APPROVAL SERVER] Спри с Ctrl+C")
    app.run(host="0.0.0.0", port=5000, debug=False)