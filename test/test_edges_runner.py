"""
test/test_edges_runner.py — the spine is silent; the edges speak afterwards.

Task #8 step B.A, 25 Sep 2026. beat() called brain.attend before every step (150
model calls on the 24 Sep 19:45 cycle) and every phase close asked the brain for a
debrief, let the cockpit speak and sent a Telegram message. The spine now writes the
phase report and nothing else; edges_runner.phase_jobs() does the three afterwards.

Failure shapes: a spine beat or phase close that still calls a model; an edge job
that skips a phase, runs them out of order, or lets one failed job stop the rest.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import edges_runner  # noqa: E402


def _imports(rel):
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8-sig"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
        elif isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
    return out


def test_beat_calls_no_brain():
    assert "core.brain" not in _imports("memory/heartbeat.py")


def test_a_phase_close_writes_the_report_and_nothing_else():
    mods = _imports("core/phase_tracker.py")
    for gone in ("core.phase_debrief", "cockpit.phase_voice", "core.interoception", "supervisor"):
        assert gone not in mods, f"core/phase_tracker still imports {gone}"


def test_phase_jobs_debrief_voice_and_send_every_report_in_order(tmp_path, monkeypatch):
    from core.phase_report import safe_cycle_dir
    cid = "2026-09-25T08:54:03+03:00"
    d = tmp_path / "memory" / "phase_reports" / safe_cycle_dir(cid)
    d.mkdir(parents=True)
    for ph in ("C_SNAPSHOT", "A_ORIENT", "B_SENSE"):
        (d / f"{ph}.json").write_text(json.dumps({"phase": ph, "verdict": "DONE", "reason": "r"}), encoding="utf-8")
    from core import phase_tracker as pt
    monkeypatch.setattr(pt, "_evidence", lambda ph: {})
    monkeypatch.setattr(pt, "_own_numbers", lambda ph: set())
    monkeypatch.setattr(pt, "_trigger", lambda: None)
    seen, sent = [], []

    def debrief(ph, c, ev, own_numbers=None, must_cite=None):
        seen.append(ph)
        if ph == "B_SENSE":
            raise RuntimeError("boom")
        return {"accepted": True, "telegram": f"t {ph}"}

    out = edges_runner.phase_jobs(cid, base=tmp_path, debrief=debrief,
                                  voice=lambda ph, c, r, dd: {"emitted": True, "text": ph},
                                  send=lambda ph, c, text, trigger=None: sent.append(ph))
    assert seen == ["A_ORIENT", "B_SENSE", "C_SNAPSHOT"], "phases out of order"
    assert [r["phase"] for r in out] == seen and sent == seen, "a failed debrief stopped the rest"
    assert out[1]["debrief"] is None and out[0]["debrief"] == "accepted"
