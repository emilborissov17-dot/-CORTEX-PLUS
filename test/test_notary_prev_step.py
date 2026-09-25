"""
test/test_notary_prev_step.py — the notary learns the previous step from the beats, not the brain.

25 Sep 2026. On the 03:04 cycle brain.attend did not answer (warm core absent), so the
prev_step memory/heartbeat.beat() handed core.notary.attest was None: the "promise"
dimension fell to 0, web_intelligence was stamped level_0, and github_publish refused
to publish, inheriting it. Every earlier night showed prev=needs_reanalysis_scan,
promise=3 - because the brain echoed it back.

Failure shape: attest called with prev_step None on any beat after the first, or with
the brain's answer instead of the beat sequence.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from memory import heartbeat as hb  # noqa: E402


def test_the_notary_gets_the_previous_step_from_the_beat_sequence(tmp_path, monkeypatch):
    logs = tmp_path / "cycle_logs"
    logs.mkdir()
    log = logs / "cycle_2026-09-25_030402.log"
    log.write_text("[STEP] needs_reanalysis_scan\n", encoding="utf-8")
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")
    monkeypatch.setattr(hb, "CYCLE_LOG_DIR", logs)
    seen = []
    import core.notary as notary
    monkeypatch.setattr(notary, "attest", lambda step, prev=None: seen.append((step, prev)) or {})
    hb.beat("web_intelligence", 1, cycle_id="c")
    assert seen == [("web_intelligence", "needs_reanalysis_scan")], seen
