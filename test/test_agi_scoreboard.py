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
    assert row["verdict"] == AS.NONE and "0.3" in row["number"]      # a losing static bench and no moving bench: no number earned


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


def test_point_13_reads_the_probe_summary(tmp_path, monkeypatch):
    _gone(tmp_path, monkeypatch)
    m = tmp_path / "memory"; m.mkdir()
    (m / "counterfactual_probe_latest.json").write_text(json.dumps(
        {"ts": "2026-09-12T09:00:00+00:00", "n": 3, "answered": 3, "tracks_rate": 0.667,
         "counts": {"TRACKS": 2, "INSENSITIVE": 1, "NOISE_DRIVEN": 0, "WRONG": 0, "SILENT": 0}}), encoding="utf-8")
    row = AS.rows(AS.gather())[12]
    assert row["verdict"] == AS.SEED and "INSENSITIVE 1" in row["number"]
    (m / "counterfactual_probe_latest.json").write_text(json.dumps(
        {"ts": "2026-09-20T09:00:00+00:00", "n": 19, "answered": 19, "tracks_rate": 0.9,
         "counts": {"TRACKS": 17, "INSENSITIVE": 2, "NOISE_DRIVEN": 0, "WRONG": 0, "SILENT": 0}}), encoding="utf-8")
    assert AS.rows(AS.gather())[12]["verdict"] == AS.PARTIAL


def test_point_9_says_whether_the_learner_improved(tmp_path, monkeypatch):
    _gone(tmp_path, monkeypatch)
    p = tmp_path / "memory" / "learner_progress.jsonl"; p.parent.mkdir()
    g = AS.gather()
    g["ledger"] = {"by_kind": {"world_next": {"scored": 20, "compared": 20, "learner_wins": 9,
                                              "learner_mean_err": 1.2, "baseline_mean_err": 1.0}}}
    AS.snapshot_learner(g, path=p, now="2026-09-04T09:00:00Z")
    g["ledger"]["by_kind"]["world_next"].update(scored=40, compared=40, learner_wins=24,
                                                learner_mean_err=0.9, baseline_mean_err=1.0)
    AS.snapshot_learner(g, path=p, now="2026-09-11T09:00:00Z")
    lp = AS.learner_progress(path=p)
    assert lp["status"] == "IMPROVED" and lp["margin_then"] == 0.2 and lp["margin_now"] == -0.1
    g["learner_progress"] = lp
    row = AS.rows(g)[8]
    assert row["verdict"] == AS.PARTIAL and "IMPROVED" in row["number"]
    # a snapshot only 3 days apart is not a weekly comparison
    AS.snapshot_learner(g, path=tmp_path / "short.jsonl", now="2026-09-11T09:00:00Z")
    AS.snapshot_learner(g, path=tmp_path / "short.jsonl", now="2026-09-14T09:00:00Z")
    assert AS.learner_progress(path=tmp_path / "short.jsonl")["status"] == "no comparison yet"


def test_points_1_and_3_read_the_cross_series_bench(tmp_path, monkeypatch):
    _gone(tmp_path, monkeypatch)
    d = tmp_path / "claude" / "reports"; d.mkdir(parents=True)
    (d / "CROSS_SERIES_BENCH.json").write_text(json.dumps({"verdict": {
        "targets": 4, "ridge_all_beats_persistence": 2, "ridge_all_beats_ridge_own": 3, "ewma_beats_persistence": 1,
        "transfer_pairs": 12, "transfer_beats_persistence": 8,
        "few_examples": {"10": 1, "20": 3, "40": 3, "80": 4}}}), encoding="utf-8")
    r = AS.rows(AS.gather())
    assert r[0]["verdict"] == AS.PARTIAL and "8/12 pairs" in r[0]["number"]
    assert r[2]["verdict"] == AS.PARTIAL and "k=20: 3/4" in r[2]["number"]
