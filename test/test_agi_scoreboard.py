# -*- coding: utf-8 -*-
"""test/test_agi_scoreboard.py — the 14 points as numbers (11 Sep 2026).

Pins: always 14 rows in order; a missing file is "—" (never a guess, never a crash);
COUNTRY_BENCH is read from the table, not from the first digit after a word;
verdicts are mechanical.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import agi_scoreboard as AS  # noqa: E402


def _gone(tmp_path, monkeypatch):
    monkeypatch.setattr(AS, "REPO", tmp_path)
    monkeypatch.setattr(AS, "REPORT", tmp_path / "claude" / "reports" / "AGI_14_SCOREBOARD.md")
    monkeypatch.setattr(AS, "REPORT_JSON", tmp_path / "claude" / "reports" / "AGI_14_SCOREBOARD.json")
    monkeypatch.setattr(AS, "_ledger", lambda: {"chain_valid": None, "by_kind": {}})   # the real ledger lives outside tmp_path


def test_fourteen_rows_in_order_on_an_empty_repo(tmp_path, monkeypatch):
    _gone(tmp_path, monkeypatch)
    r = AS.rows(AS.gather())
    assert [x["point"] for x in r] == list(range(1, 15))
    assert all(x["name"] == AS.POINTS[x["point"]] for x in r)


def test_missing_files_give_no_number_not_a_guess(tmp_path, monkeypatch):
    _gone(tmp_path, monkeypatch)
    r = {x["point"]: x for x in AS.rows(AS.gather())}
    for n in (1, 2, 3, 4, 9, 13, 14):
        assert r[n]["number"] == AS.NONE and r[n]["verdict"] == AS.NONE


def test_country_bench_is_read_from_the_table(tmp_path):
    p = tmp_path / "COUNTRY_BENCH.md"
    p.write_text("# bench\nMAE on a 0–1 index; kNN k=5\n\n"
                 "| target | baseline (mean) | kNN k=5 | ridge | n |\n|---|---:|---:|---:|---:|\n"
                 "| v2x_rule | 0.2797 | 0.1392 (61 closer) | 0.171 (59 closer) | 79 |\n"
                 "| v2x_corr_inv | 0.2739 | 0.1339 (60 closer) | 0.1453 (64 closer) | 79 |\n", encoding="utf-8")
    cb = AS.country_bench(p)
    assert cb["v2x_rule"] == {"baseline": 0.2797, "knn": 0.1392, "knn_closer": 61, "n": 79}
    assert len(cb) == 2
    assert AS.country_bench(tmp_path / "absent.md") == {}


def test_point_1_seed_only_when_knn_beats_mean_for_most_countries(tmp_path, monkeypatch):
    _gone(tmp_path, monkeypatch)
    d = tmp_path / "claude" / "reports"; d.mkdir(parents=True)
    (d / "COUNTRY_BENCH.md").write_text("| v2x_rule | 0.28 | 0.14 (61 closer) | x | 79 |\n", encoding="utf-8")
    assert AS.rows(AS.gather())[0]["verdict"] == AS.SEED
    (d / "COUNTRY_BENCH.md").write_text("| v2x_rule | 0.28 | 0.30 (30 closer) | x | 79 |\n", encoding="utf-8")
    row = AS.rows(AS.gather())[0]
    assert row["verdict"] == AS.PARTIAL and "0.3" in row["number"]


def test_point_2_live_needs_thirty_compared_and_a_win(tmp_path, monkeypatch):
    _gone(tmp_path, monkeypatch)
    g = AS.gather()
    g["ledger"] = {"by_kind": {"world_next": {"scored": 40, "compared": 40, "learner_beats_control": True,
                                              "learner_mean_err": 0.1, "baseline_mean_err": 0.2}}}
    assert AS.rows(g)[1]["verdict"] == AS.LIVE
    g["ledger"]["by_kind"]["world_next"]["compared"] = 5
    assert AS.rows(g)[1]["verdict"] == AS.PARTIAL


def test_failed_streak_counts_from_the_end(tmp_path, monkeypatch):
    _gone(tmp_path, monkeypatch)
    m = tmp_path / "memory"; m.mkdir()
    rows = [{"success": True}, {"success": False}, {"success": "false"}]
    (m / "brain_cycle_reviews.jsonl").write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
    row = AS.rows(AS.gather())[5]
    assert "reviews on file 3, failed streak 2" in row["number"] and row["verdict"] == AS.PARTIAL


def test_write_produces_md_and_json_with_counts(tmp_path, monkeypatch):
    _gone(tmp_path, monkeypatch)
    g = AS.gather(); r = AS.rows(g); md = AS.markdown(r, g)
    assert md.count("\n| ") == 15                       # header + 14 rows
    assert "LIVE 0 · PARTIAL" in md
    AS.REPORT.parent.mkdir(parents=True)
    AS.REPORT.write_text(md, encoding="utf-8")
    assert AS.REPORT.read_text(encoding="utf-8").startswith("# AGI")
