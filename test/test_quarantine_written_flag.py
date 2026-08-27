"""The quarantine file's own "written" field could never be true.

memory/language_quarantine.json on 27 Aug 2026:

    "verdict": "BELOW_FLOOR", "alarmed": true, "written": false

The record had written perfectly — its mtime proved it — and said it had not.
check_purity() copies `payload` from `result` and only sets result["written"]
once the file has landed, which is after the copy. So the persisted snapshot
said false every single time, and a reader checking that field would conclude
the record had failed to save while holding the saved record in their hand.
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import language_gate as gate          # noqa: E402


def _journal(tmp_path, clean, dirty):
    """A journal with `clean` English rows and `dirty` Cyrillic ones."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for i in range(clean):
        rows.append({"ts": now, "kind": "phase_debrief",
                     "summary": f"The axis moved by {i} points this cycle."})
    for i in range(dirty):
        rows.append({"ts": now, "kind": "skip_decision",
                     "summary": "Показателят не се е променил от 48 дни."})
    p = tmp_path / "brain_journal.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                 encoding="utf-8")
    return p


def test_the_persisted_record_says_it_was_written(tmp_path):
    """THE HEADLINE. The file on disk must not deny its own existence."""
    q = tmp_path / "language_quarantine.json"
    result = gate.check_purity(hours=24, journal=_journal(tmp_path, 30, 20),
                               quarantine=q, sender=lambda *a, **k: True)
    assert result["verdict"] == "BELOW_FLOOR"
    assert q.exists()

    on_disk = json.loads(q.read_text(encoding="utf-8"))
    assert on_disk["written"] is True, (
        "the saved quarantine record still claims it was not saved")
    assert result["written"] is True


def test_a_failed_write_leaves_no_file_and_so_no_false_claim(tmp_path):
    """Claiming it before the write is safe precisely because a failed write
    leaves nothing behind to read the claim from."""
    blocked = tmp_path / "blocked"
    blocked.write_text("i am a file, not a directory", encoding="utf-8")
    q = blocked / "language_quarantine.json"

    result = gate.check_purity(hours=24, journal=_journal(tmp_path, 30, 20),
                               quarantine=q, sender=lambda *a, **k: True)
    assert result["written"] is False
    assert "write failed" in result["why"]
    assert not q.exists(), "no file, so no false claim on disk"


def test_the_other_fields_still_describe_the_measurement(tmp_path):
    """The snapshot must stay a faithful copy apart from the one fix."""
    q = tmp_path / "language_quarantine.json"
    gate.check_purity(hours=24, journal=_journal(tmp_path, 30, 20),
                      quarantine=q, sender=lambda *a, **k: True)
    on_disk = json.loads(q.read_text(encoding="utf-8"))
    assert on_disk["verdict"] == "BELOW_FLOOR"
    assert on_disk["alarmed"] is True
    assert on_disk["n_total"] == 50
    assert abs(on_disk["ratio"] - 0.6) < 1e-9
    assert on_disk["floor"] == gate.PURITY_FLOOR
    assert "skip_decision" in on_disk["by_kind"]
