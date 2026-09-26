"""
test/test_publisher_drops_missing_review.py — a review file that is gone when the
publisher reaches it is DROPPED, and the run goes on (C3b, 26 Sep 2026).

Five review producers left the cycle that day. The refusal-free failure this pins:
one missing page raising out of publish_cycle and taking the Daily index (the
night's proof) down with it, or being counted as a publishing error, which would
make a deletion read like a fault. Mutation: remove the FileNotFoundError branch
and the dropped count is 0 and errors is 1, so the test fails.
"""
from __future__ import annotations

import json

import github_publisher as gp


def test_a_review_file_gone_before_it_is_read_is_dropped_not_failed(tmp_path, monkeypatch):
    folder = tmp_path / "2026-09-26"
    folder.mkdir()
    (folder / "a_review_web_intel.json").write_text(json.dumps({"axis": "A_REVIEW"}), encoding="utf-8")
    gone = folder / "b_review_web_intel.json"
    gone.write_text(json.dumps({"axis": "B_REVIEW"}), encoding="utf-8")

    pushed = []

    def push(path, content, message):
        pushed.append(path)
        if gone.exists():            # the file vanishes after the listing, before its read
            gone.unlink()
    monkeypatch.setattr(gp, "_push_file", push)
    monkeypatch.setattr(gp, "cycle_date", lambda now_utc=None: "2026-09-26")

    got = gp.publish_cycle(folder)

    assert got == {"published": 1, "errors": 0, "dropped": 1}
    assert pushed == ["reports/2026-09-26/a_review.md", "reports/2026-09-26/index.md"], \
        "the Daily index must still be published without the missing page"
