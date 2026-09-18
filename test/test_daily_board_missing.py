# -*- coding: utf-8 -*-
"""test/test_daily_board_missing.py — the board's REFUSAL path, first.

tools/daily_board.py prints one number per running experiment every morning. The
number it must never print is a number it did not measure today. Two ways that
happens, and both are tested here before anything about the happy path:

  1. a DEFAULT where a measurement should be — 0, 0.0, "n/a", a dash;
  2. YESTERDAY'S NUMBER carried into today's column, which makes a dead
     experiment look alive for exactly as long as nobody checks the mtime.

The correct behaviour for a source that is absent, empty, torn or the wrong
shape is the word MISSING and the path it looked at — a refusal, not an error,
and not a reason to drop the other five rows.

The repo under test is SYNTHETIC and built in tmp_path: the smallest file of
each kind that the six rows accept. Pointing this at the live memory/ files
would make the outcome vary with the world rather than with the code, which is
what the `live_state` marker in pytest.ini exists to keep out of the gate. The
first test guards the fixture itself — if the synthetic repo ever stops
producing six live rows, every MISSING assertion below would pass vacuously.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location("daily_board", REPO / "tools" / "daily_board.py")
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)

NOW = datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc)
TODAY = NOW.date().isoformat()
YDAY = (NOW - timedelta(days=1)).date().isoformat()

# Which file each row dies without. Every path here is also in db.SOURCES, and
# test_the_source_table_and_this_table_agree holds the two together.
ROW_SOURCES = [
    ("t1", "memory/t1_result_full.json"),
    ("probe", "claude/reports/BRAIN_PROBE_2026-09-17.json"),
    ("selfmodel", "experiments/prophecy/prophecy_ledger.jsonl"),
    ("selfmodel", "memory/existence_ledger.jsonl"),
    ("world", "experiments/prophecy/prophecy_ledger.jsonl"),
    ("fresh", "memory/measurement_honesty_latest.json"),
    ("fresh", "memory/daily_tier.jsonl"),
    ("local", "memory/llm_provenance.jsonl"),
]


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _lines(rows: list[dict]) -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The smallest repo in which all six rows produce a number."""
    _write(tmp_path / "memory/t1_result_full.json", json.dumps({
        "ts": "2026-09-17T14:12:45+00:00", "model": "qwen3:8b", "verdict": "FAIL",
        "success_rate": {"on": 0.78, "off": 0.79, "shuffled": 0.71},
        "brier": {"on": 0.31, "off": 0.30, "shuffled": 0.33},
        "decomposition": {
            "total_on_minus_off": {"diff": -0.0156, "lo": -0.125, "hi": 0.0938, "n": 64},
            "retrieval_on_minus_shuffled": {"diff": 0.0625, "lo": -0.05, "hi": 0.17, "n": 64},
            "format_shuffled_minus_off": {"diff": -0.0781, "lo": -0.17, "hi": 0.015, "n": 64}},
        "conditions": {"a": False, "b": False, "c": False},
        "parse_failures": {"on": 0, "off": 0, "shuffled": 0},
        "transport_errors": {"on": 0, "off": 0, "shuffled": 0},
        "brier_comparison_void": False}))

    _write(tmp_path / "claude/reports/BRAIN_PROBE_2026-09-17.json", json.dumps({
        "ts": "2026-09-17T19:28:29+00:00", "model": "Qwen2.5-3B", "C_probe_layer": 35,
        "A_best_layer": {"layer": 34, "real": 1.0, "control": 0.14, "selectivity": 0.86, "chance": 0.1667},
        "B_best_layer": {"layer": 35, "real": 0.99, "control": 0.41, "selectivity": 0.58, "chance": 0.5},
        "B_spoken": {"n": 200, "refusals": 0, "accuracy": 0.995},
        "C_conditions": {
            "filler": {"n": 200, "refusals": 0, "spoken_accuracy": 0.995, "spoken_up_rate": 0.53},
            "true": {"n": 200, "refusals": 0, "spoken_accuracy": 0.735, "spoken_up_rate": 0.27,
                     "probe_accuracy": 0.60},
            "all_up": {"n": 200, "refusals": 0, "spoken_accuracy": 0.53, "spoken_up_rate": 0.995,
                       "probe_accuracy": 0.61},
            "all_down": {"n": 200, "refusals": 0, "spoken_accuracy": 0.61, "spoken_up_rate": 0.135,
                         "probe_accuracy": 0.59}}}))

    _write(tmp_path / "memory/existence_ledger.jsonl", _lines([
        {"seq": 1, "ts": "2026-09-17T02:07:56+00:00", "event": "CYCLE_FINISHED",
         "cycle_id": "c1", "duration_sec": 7430.7, "steps_completed": 41, "degraded_steps": 3},
        {"seq": 2, "ts": "2026-09-18T01:46:56+00:00", "event": "CYCLE_FINISHED",
         "cycle_id": "c2", "duration_sec": 6171.5, "steps_completed": 42, "degraded_steps": 2},
    ]))

    anchor = "next_cycle_after::2026-09-17T02:07:56+00:00"
    _write(tmp_path / "experiments/prophecy/prophecy_ledger.jsonl", _lines([
        {"seq": 1, "ts": "2026-09-17T09:00:00+00:00", "event": "PREDICTION_SEALED",
         "target_kind": "self_duration", "target_id": anchor, "learner": 6826.0,
         "baseline": 7430.7, "hash": "h1"},
        {"seq": 2, "ts": "2026-09-17T09:00:01+00:00", "event": "PREDICTION_SEALED",
         "target_kind": "self_degraded", "target_id": anchor, "learner": 0.78,
         "baseline": 0.33, "hash": "h2"},
        {"seq": 3, "ts": TODAY + "T09:00:02+00:00", "event": "OUTCOME_SCORED", "ref_hash": "h2",
         "target_kind": "self_degraded", "actual": 1, "learner_err": 0.0484,
         "baseline_err": 0.4489, "learner_wins": True, "rule": "brier"},
        {"seq": 4, "ts": YDAY + "T01:00:00+00:00", "event": "PREDICTION_SEALED",
         "target_kind": "world_next", "target_id": "W::a", "indicator": "quakes.m45",
         "learner": 12.3, "baseline": 12.0, "hash": "w1"},
        {"seq": 5, "ts": TODAY + "T01:00:00+00:00", "event": "OUTCOME_SCORED", "ref_hash": "w1",
         "target_kind": "world_next", "actual": 12.0, "learner_err": 0.3,
         "baseline_err": 0.0, "learner_wins": False},
        {"seq": 6, "ts": TODAY + "T01:33:00+00:00", "event": "PREDICTION_SEALED",
         "target_kind": "world_next", "target_id": "W::b", "indicator": "co2.ppm",
         "learner": 426.080003, "baseline": 426.08, "hash": "w2"},
    ]))

    _write(tmp_path / "memory/measurement_honesty_latest.json", json.dumps({
        "ts": "2026-09-18T01:13:10+00:00", "k1": 0.6826, "k1_fresh": 0.0599,
        "fresh_window_days": 30, "fresh_weight": 10.0, "measured_weight": 114.0,
        "undated_weight": 18.0, "max_observation_age_days": 2087.0, "oldest_axis": "ENERGY_REVIEW",
        "honest_composite": {"total_weight": 167.0}}))

    _write(tmp_path / "memory/daily_tier.jsonl", _lines([
        {"date": YDAY, "indicator": "a", "value": 1.0},
        {"date": TODAY, "indicator": "a", "value": 2.0},
        {"date": YDAY, "indicator": "b", "value": 5.0},
        {"date": TODAY, "indicator": "b", "value": 5.0},
    ]))

    _write(tmp_path / "memory/llm_provenance.jsonl", _lines([
        {"ts": TODAY + "T00:10:00+00:00", "backend": "local:qwen3:8b"},
        {"ts": TODAY + "T00:20:00+00:00", "backend": "Groq"},
        {"ts": YDAY + "T23:00:00+00:00", "backend": "local:qwen3:8b"},
    ]))
    return tmp_path


def _by_id(rows: list[dict]) -> dict:
    return {r["id"]: r for r in rows}


# --------------------------------------------------------------------------- the fixture guard
def test_the_synthetic_repo_produces_six_live_rows(repo: Path):
    """Without this, every MISSING assertion below could pass vacuously."""
    rows = db.build_rows(repo, NOW)
    assert [r["id"] for r in rows] == [b[0] for b in db.BUILDERS]
    for r in rows:
        assert r.get("status") != "MISSING", (r["id"], r["headline"])
        assert "MISSING" not in r["headline"], r["headline"]


def test_the_source_table_and_this_table_agree(repo: Path):
    """ROW_SOURCES is what the tests delete; db.SOURCES is what the board reads.

    If a row gains a source and only one of the two tables is updated, the new
    source is never tested for its MISSING path. This keeps them married.
    """
    declared = {(rid, pat) for rid, pats in db.SOURCES.items() for pat in pats}
    tested = set()
    for rid, path in ROW_SOURCES:
        hit = [p for p in db.SOURCES[rid]
               if p == path or ("*" in p and Path(path).match(p.replace("claude/reports/", "")))]
        assert hit, "{} is not in db.SOURCES[{!r}]".format(path, rid)
        tested.add((rid, hit[0]))
    assert tested == declared, "untested sources: {}".format(sorted(declared - tested))


# --------------------------------------------------------------------------- the refusal
@pytest.mark.parametrize("row_id,source", ROW_SOURCES)
def test_a_row_whose_source_is_removed_says_missing_and_names_the_path(
        repo: Path, row_id: str, source: str):
    (repo / source).unlink()
    rows = _by_id(db.build_rows(repo, NOW))
    r = rows[row_id]
    assert r["status"] == "MISSING"
    assert "MISSING" in r["headline"]
    # A row that globs names the PATTERN it looked for, not a file that is not there.
    wanted = [Path(p).name for p in db.SOURCES[row_id]]
    assert any(w in r["headline"] for w in wanted), (r["headline"], wanted)
    assert ("not on disk" in r["why"]) or ("no file matches" in r["why"]), r["why"]


@pytest.mark.parametrize("row_id,source", ROW_SOURCES)
def test_removing_one_source_does_not_take_the_other_rows_down(
        repo: Path, row_id: str, source: str):
    """A refusal in one row is a refusal in one row. The board still prints."""
    (repo / source).unlink()
    rows = db.build_rows(repo, NOW)
    assert len(rows) == len(db.BUILDERS)
    others = [r for r in rows if r.get("status") == "MISSING" and r["id"] != row_id]
    # only rows that share the deleted file may also go MISSING
    for r in others:
        assert source in db.SOURCES[r["id"]], (r["id"], source)


@pytest.mark.parametrize("source", sorted({s for _, s in ROW_SOURCES}))
def test_an_empty_source_is_missing_not_a_zero(repo: Path, source: str):
    """A file that exists and holds nothing is the quietest way to get a fake zero."""
    (repo / source).write_text("", encoding="utf-8")
    rows = db.build_rows(repo, NOW)
    hit = [r for r in rows if r.get("status") == "MISSING"]
    assert hit, "an empty {} produced no MISSING row at all".format(source)
    for r in hit:
        assert "0" != r["headline"].strip()
        assert "MISSING" in r["headline"]


def test_a_torn_jsonl_with_no_readable_record_is_missing(repo: Path):
    (repo / "memory/llm_provenance.jsonl").write_text("{not json\n{also not\n", encoding="utf-8")
    r = _by_id(db.build_rows(repo, NOW))["local"]
    assert r["status"] == "MISSING"
    assert "torn line" in r["why"], r["why"]


def test_the_right_shape_but_the_wrong_content_is_missing_too(repo: Path):
    """Readable JSON without the field the row needs is not a zero either."""
    (repo / "memory/measurement_honesty_latest.json").write_text("{}", encoding="utf-8")
    r = _by_id(db.build_rows(repo, NOW))["fresh"]
    assert r["status"] == "MISSING"
    assert "k1_fresh" in r["why"]


# --------------------------------------------------------------------------- the forbidden fallback
def test_a_missing_row_never_inherits_yesterdays_number(repo: Path):
    """The whole point. Yesterday's number stays in yesterday's column."""
    prev = {"date": YDAY, "rows": {"t1": "verdict PASS - on-off = +0.4242"},
            "status": {"t1": "OK"}}
    (repo / "memory/t1_result_full.json").unlink()
    rows = db.build_rows(repo, NOW)
    text = db.render(rows, NOW, YDAY, prev)
    line = [l for l in text.splitlines() if l.startswith("| T1 transfer test |")]
    assert len(line) == 1, text
    today_cell, yday_cell = line[0].split("|")[3], line[0].split("|")[4]
    assert "MISSING" in today_cell and "t1_result_full.json" in today_cell
    assert "0.4242" not in today_cell, "yesterday's number leaked into today's column"
    assert "0.4242" in yday_cell, "yesterday's number should still be shown beside it"


def test_the_machine_block_records_missing_so_tomorrow_shows_missing_too(repo: Path):
    (repo / "memory/t1_result_full.json").unlink()
    text = db.render(db.build_rows(repo, NOW), NOW, None, {})
    block = db.read_machine_block(text)
    assert block["status"]["t1"] == "MISSING"
    assert "MISSING" in block["rows"]["t1"]


def test_build_rows_cannot_be_handed_a_previous_board(repo: Path):
    """The structural net. A fallback needs this signature to change first."""
    assert list(inspect.signature(db.build_rows).parameters) == ["repo", "now"]


def test_the_rows_are_identical_whether_or_not_a_previous_board_exists(repo: Path):
    """Behavioural twin of the signature test: prove it, do not just declare it.

    Fails if today's numbers are ever computed with one eye on the archive.
    """
    before = db.build_rows(repo, NOW)
    _write(repo / db.ARCHIVE / (YDAY + ".md"),
           db.render(before, NOW, None, {}).replace("MISSING", "SOMETHING ELSE"))
    (repo / "memory/t1_result_full.json").unlink()
    after_with_archive = db.build_rows(repo, NOW)
    (repo / db.ARCHIVE / (YDAY + ".md")).unlink()
    after_without = db.build_rows(repo, NOW)
    assert after_with_archive == after_without


def test_previous_board_never_reads_todays_own_file(repo: Path):
    """Reading today's file back would make yesterday a copy of today forever."""
    _write(repo / db.ARCHIVE / (TODAY + ".md"), db.render(db.build_rows(repo, NOW), NOW, None, {}))
    assert db.previous_board(repo, TODAY) == (None, {})
    _write(repo / db.ARCHIVE / (YDAY + ".md"), db.render(db.build_rows(repo, NOW), NOW, None, {}))
    date, block = db.previous_board(repo, TODAY)
    assert date == YDAY and block["rows"]["t1"]


# --------------------------------------------------------------------------- labels
def test_every_printed_number_row_names_its_statistic(repo: Path):
    """The label audit found five values printed with no statistic named. Not a sixth."""
    rows = _by_id(db.build_rows(repo, NOW))
    assert "success-rate difference" in rows["t1"]["headline"]
    assert "probe accuracy" in rows["probe"]["headline"] and "selectivity" in rows["probe"]["headline"]
    assert "MAE (mean absolute error)" in rows["world"]["headline"]
    assert "Brier NOT DEFINED" in rows["world"]["headline"]
    assert "k1_fresh" in rows["fresh"]["headline"]
    assert "local:*" in rows["local"]["headline"]


def test_a_world_forecast_equal_to_its_baseline_to_three_decimals_is_counted(repo: Path):
    r = _by_id(db.build_rows(repo, NOW))["world"]
    joined = "\n".join(r["detail"])
    assert "1 equal the baseline to 3 decimals" in joined, joined
    assert "co2.ppm learner 426.080003 vs baseline 426.08" in joined


def test_no_local_answer_today_says_local_brain_silent(repo: Path):
    (repo / "memory/llm_provenance.jsonl").write_text(
        _lines([{"ts": TODAY + "T00:20:00+00:00", "backend": "Groq"}]), encoding="utf-8")
    r = _by_id(db.build_rows(repo, NOW))["local"]
    assert r["headline"].startswith("LOCAL BRAIN SILENT")
    assert r["correction"] == "yes"
