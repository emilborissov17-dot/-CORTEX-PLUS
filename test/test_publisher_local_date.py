"""
test/test_publisher_local_date.py — the daily proof is labelled with the cycle's LOCAL
date (Europe/Sofia), not the UTC date of the data folder (26 Sep 2026).

The night of 26 Sep ran at 00:20 UTC and was published as "[2026-09-25] Daily
index". A refusal-free failure looks exactly like that: a plausible date one day
early. These tests pin the conversion on both sides of midnight and of both DST
changes, and that publish_cycle uses it for the title, the path and the index.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import github_publisher as gp


def U(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_a_0020z_run_on_the_26th_is_labelled_2026_09_26():
    assert gp.cycle_date(U(2026, 9, 26, 0, 20)) == "2026-09-26"


def test_summer_and_winter_offsets_and_both_dst_edges():
    assert gp.cycle_date(U(2026, 9, 25, 20, 59)) == "2026-09-25"   # 23:59 EEST
    assert gp.cycle_date(U(2026, 9, 25, 21, 0)) == "2026-09-26"    # 00:00 EEST
    assert gp.cycle_date(U(2026, 12, 31, 21, 59)) == "2026-12-31"  # 23:59 EET
    assert gp.cycle_date(U(2026, 12, 31, 22, 0)) == "2027-01-01"   # 00:00 EET
    # 2026: DST from 29 Mar 01:00 UTC to 25 Oct 01:00 UTC
    assert gp.cycle_date(U(2026, 3, 28, 21, 30)) == "2026-03-28"   # 23:30 EET (UTC+2)
    assert gp.cycle_date(U(2026, 10, 25, 0, 30)) == "2026-10-25"   # 03:30 EEST
    assert gp.cycle_date(U(2026, 10, 24, 21, 30)) == "2026-10-25"  # 00:30 EEST
    assert gp.cycle_date(U(2026, 10, 25, 22, 30)) == "2026-10-26"  # 00:30 EET, after the change


def test_publish_cycle_labels_title_path_and_index_with_the_local_date(tmp_path, monkeypatch):
    folder = tmp_path / "2026-09-25"                               # the UTC-named data folder
    folder.mkdir()
    (folder / "water.json").write_text(json.dumps({"axis": "WATER_REVIEW", "analysis": {}}), encoding="utf-8")
    pushed = []
    monkeypatch.setattr(gp, "_push_file", lambda path, content, message: pushed.append((path, message, content)))
    monkeypatch.setattr(gp, "cycle_date", lambda now_utc=None: "2026-09-26")
    gp.publish_cycle(folder)
    paths = [p for p, _m, _c in pushed]
    assert "reports/2026-09-26/water_review.md" in paths
    assert ("reports/2026-09-26/index.md", "[2026-09-26] Daily index") in [(p, m) for p, m, _c in pushed]
    index = next(c for p, _m, c in pushed if p.endswith("index.md"))
    assert "data folder 2026-09-25" in index
    assert not any("2026-09-25]" in m for _p, m, _c in pushed)
