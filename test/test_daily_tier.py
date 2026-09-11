# -*- coding: utf-8 -*-
"""test/test_daily_tier.py — the world that moves is kept (AGI-5, 10 Sep 2026). Failure paths first."""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import daily_tier as dt  # noqa: E402

SNAP = {"timestamp": "2026-09-10T00:21:52+00:00",
        "sources": {"co2": "NOAA"},
        "co2": {"co2_ppm": 427.15, "co2_date": "2026-08-30"},
        "quakes": {"quake_m45_count": 12, "last_date": "2026-09-09", "min_magnitude": 4.5},
        "markets": {"spy_adjclose": 765.96, "last_date": "2026-09-08"},
        "food": {"undernourishment_pct": 8.5, "food_production_index": 100.0,
                 "_carried": {"food_production_index": {"value": 100.0, "since": "2026-08-01"}}},
        "media": {"news_tone_latest": -1.31, "news_tone_datapoints": 1, "news_tone_scale": "text"},
        "_health": {"fresh_this_cycle": 6, "carried_from_a_previous_cycle": 1}}


def _write(tmp_path, snap):
    p = tmp_path / "gi.json"
    p.write_text(json.dumps(snap), encoding="utf-8")
    return p, tmp_path / "tier.jsonl"


def test_a_carried_value_never_becomes_a_new_observation(tmp_path):
    sp, tp = _write(tmp_path, SNAP)
    c = dt.record(sp, tp)
    rows = [json.loads(l) for l in tp.read_text().splitlines()]
    assert "food.food_production_index" not in {r["indicator"] for r in rows}
    assert c["carried_skipped"] == 1 and c["written"] == 5


def test_parameters_and_health_are_not_observations(tmp_path):
    sp, tp = _write(tmp_path, SNAP)
    dt.record(sp, tp)
    names = {json.loads(l)["indicator"] for l in tp.read_text().splitlines()}
    assert not any(n.startswith("_health") for n in names)
    assert "quakes.min_magnitude" not in names and "media.news_tone_datapoints" not in names
    assert "media.news_tone_scale" not in names


def test_dates_come_from_the_source_when_it_says_and_say_so_when_not(tmp_path):
    sp, tp = _write(tmp_path, SNAP)
    dt.record(sp, tp)
    by = {json.loads(l)["indicator"]: json.loads(l) for l in tp.read_text().splitlines()}
    assert by["co2.co2_ppm"]["date"] == "2026-08-30" and by["co2.co2_ppm"]["date_basis"] == "source"
    assert by["quakes.quake_m45_count"]["date"] == "2026-09-09"
    assert by["markets.spy_adjclose"]["date"] == "2026-09-08"
    assert by["food.undernourishment_pct"]["date"] == "2026-09-10" and by["food.undernourishment_pct"]["date_basis"] == "fetch"


def test_recording_twice_writes_nothing_twice(tmp_path):
    sp, tp = _write(tmp_path, SNAP)
    dt.record(sp, tp)
    c2 = dt.record(sp, tp)
    assert c2["written"] == 0 and c2["already_on_file"] == 5
    assert len(tp.read_text().splitlines()) == 5


def test_a_new_night_adds_only_the_new_dates(tmp_path):
    sp, tp = _write(tmp_path, SNAP)
    dt.record(sp, tp)
    snap2 = json.loads(json.dumps(SNAP))
    snap2["timestamp"] = "2026-09-11T00:20:00+00:00"
    snap2["quakes"] = {"quake_m45_count": 19, "last_date": "2026-09-10", "min_magnitude": 4.5}
    sp2 = tmp_path / "gi2.json"; sp2.write_text(json.dumps(snap2), encoding="utf-8")
    c = dt.record(sp2, tp)
    s = dt.series(tp)
    assert s["quakes.quake_m45_count"] == [("2026-09-09", 12.0), ("2026-09-10", 19.0)]
    assert s["co2.co2_ppm"] == [("2026-08-30", 427.15)]          # co2_date unchanged -> no new row
    assert c["written"] == 3                                     # quakes + the two fetch-dated leaves (food, media)


def test_dry_run_writes_nothing(tmp_path):
    sp, tp = _write(tmp_path, SNAP)
    c = dt.record(sp, tp, dry=True)
    assert c["written"] == 5 and not tp.exists()


def test_unreadable_snapshot_is_a_named_error_not_a_crash(tmp_path):
    c = dt.record(tmp_path / "missing.json", tmp_path / "tier.jsonl")
    assert "error" in c and c["written"] == 0


def test_backfill_writes_source_dated_days_and_names_a_failed_source(tmp_path):
    tp = tmp_path / "tier.jsonl"

    def usgs(day):
        return {_dt.date(2026, 9, 5): 17, _dt.date(2026, 9, 6): 24, _dt.date(2026, 9, 7): 12}.get(day, 15)

    def market(sym):
        if sym == "UUP":
            raise ValueError("no chart.result")
        base = 1_757_000_000  # epoch ~ 2025-09; only the date matters
        return {"chart": {"result": [{"timestamp": [base, base + 86400, base + 2 * 86400],
                                      "indicators": {"adjclose": [{"adjclose": [100.0, None, 101.5]}]}}]}}

    r = dt.backfill(3, tp, usgs_fetch=usgs, market_fetch=market)
    assert r["errors"] == {"UUP": "no chart.result"}
    s = dt.series(tp)
    assert len(s["quakes.quake_m45_count"]) == 3
    assert all(r2["date_basis"] == "source" for r2 in (json.loads(l) for l in tp.read_text().splitlines()))
    assert len(s["markets.spy_adjclose"]) == 2 and len(s["markets.gld_adjclose"]) == 2   # None bar dropped
    r2 = dt.backfill(3, tp, usgs_fetch=usgs, market_fetch=market)
    assert r2["written"] == 0


def test_the_live_snapshot_records_and_the_annual_leaves_do_not_masquerade_as_daily(tmp_path):
    """Against this repo's snapshot: every row is dated, and a fetch-dated annual figure is
    labelled fetch, never source."""
    if not dt.SNAPSHOT.exists():
        return
    tp = tmp_path / "tier.jsonl"
    c = dt.record(dt.SNAPSHOT, tp)
    assert c["written"] > 30
    rows = [json.loads(l) for l in tp.read_text().splitlines()]
    assert all(len(r["date"]) == 10 for r in rows)
    wb = [r for r in rows if r["indicator"].startswith("world_bank.")]
    assert wb and all(r["date_basis"] == "fetch" for r in wb)


# ── the step is WIRED, not merely declared (11 Sep 2026) ─────────────────────
#
# A beat named in cycle_map, cycle_phases and step_inputs but never actually
# called is the dead weight CLAUDE.md warns about: three files would agree the
# step exists and no night would run it. These check the four places together.

def _runner_src():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / "fast_cycle_runner.py"
            ).read_text(encoding="utf-8-sig")


def test_the_runner_calls_daily_tier_through_run_not_a_bare_try():
    """THROUGH _run(), and a test already insisted once. A step records its
    checkpoint only by going through _run(); the first version of this step used
    its own try/except and test_checkpoint_wiring caught the uncovered count
    going 30 -> 31."""
    import ast
    src = _runner_src()
    assert 'beat("daily_tier", "2.52")' in src, "the beat is gone"
    tree = ast.parse(src)
    called = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_run"
                and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "daily_tier"):
            called = True
    assert called, "daily_tier is announced by beat() but never run through _run()"


def test_the_step_runs_record_and_never_backfill():
    """record() reads a file already on disk. backfill() reaches USGS and Yahoo
    ~90 times and belongs to a human's `--backfill 90`. A night that silently
    made 93 network calls would not be the step that was declared."""
    src = _runner_src()
    i = src.index('beat("daily_tier", "2.52")')
    block = src[i:i + 900]
    assert "record" in block, "the step does not call record()"
    assert "backfill" not in block, (
        "the cycle step references backfill — that is ~93 network calls a night "
        "and a human's command, not the night's")


def test_the_step_is_declared_everywhere_it_has_to_be():
    """cycle_map (what it is), cycle_phases (which phase pays for its failure),
    step_inputs (what it opens). Missing any one of them is a different defect
    the suite already has tests for; this one fails fast and says which."""
    import json
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[1]

    cmap = (repo / "core" / "cycle_map.py").read_text(encoding="utf-8-sig")
    assert '"daily_tier", "2.52"' in cmap.replace("'", '"'), "not in core/cycle_map.py"

    phases = json.loads((repo / "config" / "cycle_phases.json").read_text(encoding="utf-8"))
    b = phases["phases"]["B_SENSE"]
    names = [s["name"] for s in b["steps"]]
    assert "daily_tier" in names, "not in cycle_phases B_SENSE"
    assert names.index("daily_tier") == names.index("global_indicators") + 1, (
        "daily_tier must sit immediately after global_indicators — it keeps THAT "
        "fetch per day, so any step between them could overwrite what it records")
    assert "memory/daily_tier.jsonl" in b["produces"], "the phase does not declare the tier"

    si = json.loads((repo / "config" / "step_inputs.json").read_text(encoding="utf-8"))
    d = si["steps"].get("daily_tier")
    assert d, "not in config/step_inputs.json"
    assert "snapshots/master/global_indicators_latest.json" in d["inputs"]
    assert d.get("derived_from"), "step_inputs requires derived_from, not a guess"
