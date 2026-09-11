# -*- coding: utf-8 -*-
"""
test/test_alarm_indicators.py — THE FIRST THREE SIGNED RED LINES (10 Sep 2026).

Emil signed three indicator bands on 10 Sep 2026 (config/alarm_indicators.json).
What this guards, failure paths first:

  * a number an agent SAID but the gate refused must never ring       (negative control)
  * a relative band with no history must record, never alarm           (no baseline, no bell)
  * a fixed crossing rings and the message carries the signed line
  * a relative crossing rings and the message carries the median it beat
  * the live file names who signed and when, on every band
  * the live sweep runs against this repo's verified_observations and says so

    venv\\Scripts\\python.exe -m pytest test/test_alarm_indicators.py -v
"""
from __future__ import annotations

import json
import pathlib

from core import alarm_bands as ab

REPO = pathlib.Path(__file__).resolve().parents[1]


def _bands(tmp_path, **indicators):
    p = tmp_path / "bands.json"
    p.write_text(json.dumps({"indicators": indicators}), encoding="utf-8")
    return p


def _verified(tmp_path, rows):
    p = tmp_path / "verified.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def _obs(key, value, date, verdict="ACCEPTED"):
    return {"verdict": verdict, "judged_utc": f"{date}T12:00:00+00:00",
            "record": {"key": key, "value": value, "observed_date": date}}


FIXED = {"axis": "DEEP_TIME_RISKS_REVIEW", "rule": "fixed", "threshold": 50, "direction": "lower_better",
         "unit": "events", "signed_by": "Emil Borissov", "signed_on": "2026-09-10"}
RELATIVE = {"axis": "ECOSYSTEMS_BIODIVERSITY_REVIEW", "rule": "relative_median", "multiplier": 2.0,
            "window_days": 56, "min_history_days": 56, "direction": "lower_better", "unit": "events",
            "signed_by": "Emil Borissov", "signed_on": "2026-09-10"}


# ---------------------------------------------------------------------------
# (a) NEGATIVE CONTROL — only what the world confirmed can ring
# ---------------------------------------------------------------------------

def test_a_refused_number_never_rings_however_large(tmp_path):
    v = _verified(tmp_path, [_obs("usgs", 9999, "2026-09-10", verdict="QUOTE_NOT_ON_PAGE"),
                             _obs("usgs", 9999, "2026-09-10", verdict="VALUE_MISMATCH"),
                             _obs("usgs", None, "2026-09-10", verdict="NULL_WITH_REASON")])
    r = ab.sweep_indicators(_bands(tmp_path, usgs=FIXED), v)
    assert r["alarms"] == []
    assert r["rows"][0]["verdict"] == ab.NO_VALUE


def test_mutation_the_verdict_filter_is_load_bearing(tmp_path, monkeypatch):
    """If indicator_values stopped filtering on ACCEPTED, the refused 9999 would ring."""
    v = _verified(tmp_path, [_obs("usgs", 9999, "2026-09-10", verdict="QUOTE_NOT_ON_PAGE")])
    src = pathlib.Path(ab.__file__).read_text(encoding="utf-8")
    assert 'o.get("verdict") != "ACCEPTED"' in src
    # and the same file with the filter neutered does ring — so the test sees the filter, not luck
    import types
    mod = types.ModuleType("ab_mut")
    mod.__file__ = ab.__file__
    exec(compile(src.replace('o.get("verdict") != "ACCEPTED"', "False"), "ab_mut", "exec"), mod.__dict__)
    assert mod.sweep_indicators(_bands(tmp_path, usgs=FIXED), v)["alarms"]


# ---------------------------------------------------------------------------
# (b) A relative band without history records and does not judge
# ---------------------------------------------------------------------------

def test_relative_band_is_record_only_until_the_window_exists(tmp_path):
    v = _verified(tmp_path, [_obs("wf", 3, "2026-09-03"), _obs("wf", 40, "2026-09-10")])
    r = ab.sweep_indicators(_bands(tmp_path, wf=RELATIVE), v)
    row = r["rows"][0]
    assert row["verdict"] == ab.RECORD_ONLY and r["alarms"] == []
    assert row["baseline"]["history_days"] == 7 and row["baseline"]["min_history_days"] == 56
    assert row["value"] == 40


def test_relative_band_rings_over_twice_its_own_median_and_says_so(tmp_path):
    rows = [_obs("wf", 5 + (i % 3), f"2026-07-{1 + i:02d}") for i in range(30)]      # July: 5..7
    rows += [_obs("wf", 5, "2026-08-20"), _obs("wf", 6, "2026-08-27"), _obs("wf", 14, "2026-09-10")]
    r = ab.sweep_indicators(_bands(tmp_path, wf=RELATIVE), _verified(tmp_path, rows))
    row = r["rows"][0]
    assert row["verdict"] == ab.ALARM
    assert row["baseline"]["kind"] == "relative_median" and row["baseline"]["multiplier"] == 2.0
    assert "median" in row["why"] and str(row["baseline"]["median"]) in row["why"]
    assert row["threshold"] == 2.0 * row["baseline"]["median"]


def test_relative_band_is_quiet_inside_twice_its_median(tmp_path):
    rows = [_obs("wf", 6, f"2026-07-{1 + i:02d}") for i in range(30)] + [_obs("wf", 11, "2026-09-10")]
    r = ab.sweep_indicators(_bands(tmp_path, wf=RELATIVE), _verified(tmp_path, rows))
    assert r["rows"][0]["verdict"] == ab.OK


# ---------------------------------------------------------------------------
# (c) A fixed crossing rings, immediately, with the signed line in the text
# ---------------------------------------------------------------------------

def test_fixed_crossing_rings_and_the_message_carries_the_signature(tmp_path):
    v = _verified(tmp_path, [_obs("usgs", 38, "2026-09-03"), _obs("usgs", 63, "2026-09-10")])
    r = ab.sweep_indicators(_bands(tmp_path, usgs=FIXED), v)
    assert len(r["alarms"]) == 1
    row = r["alarms"][0]
    assert row["value"] == 63 and row["baseline"] == {"kind": "fixed", "threshold": 50, "direction": "lower_better"}
    assert "Emil Borissov 2026-09-10" in row["why"]
    sent = []
    assert ab.send(r, sender=lambda name, text: sent.append((name, text))) == 1
    assert sent[0][0] == "DEEP_TIME_RISKS_REVIEW · usgs" and "ЧЕРВЕНА ЛИНИЯ" in sent[0][1]
    assert "50" in sent[0][1]


def test_fixed_band_uses_the_latest_accepted_value_not_the_largest(tmp_path):
    v = _verified(tmp_path, [_obs("usgs", 70, "2026-09-03"), _obs("usgs", 38, "2026-09-10")])
    r = ab.sweep_indicators(_bands(tmp_path, usgs=FIXED), v)
    assert r["rows"][0]["verdict"] == ab.OK and r["rows"][0]["value"] == 38


def test_a_band_with_an_unusable_rule_or_direction_is_a_config_error(tmp_path):
    v = _verified(tmp_path, [_obs("x", 1, "2026-09-10")])
    r = ab.sweep_indicators(_bands(tmp_path, x=dict(FIXED, rule="p95_someday"),
                                   y=dict(FIXED, direction="up")), v)
    assert {row["verdict"] for row in r["rows"]} == {ab.CONFIG_ERROR}
    assert len(r["config_errors"]) == 2


# ---------------------------------------------------------------------------
# (d) THE LIVE FILE — three bands, each signed, none invented by the system
# ---------------------------------------------------------------------------

def test_the_live_bands_are_three_and_each_is_signed():
    bands = ab.indicator_bands()
    assert set(bands) == {"co2_annual_increase_ppm", "usgs_m5plus_7d_count", "gdacs_wildfire_orange_red_7d_count"}
    for key, b in bands.items():
        assert b["signed_by"] == "Emil Borissov" and b["signed_on"] == "2026-09-10", key
        assert b["rule"] in ab.RULES and b["direction"] in ab.DIRECTIONS, key
        assert b["axis"] in ab.axes(), key
    assert bands["co2_annual_increase_ppm"]["threshold"] == 3.0
    assert bands["usgs_m5plus_7d_count"]["threshold"] == 50
    assert bands["gdacs_wildfire_orange_red_7d_count"]["multiplier"] == 2.0
    assert bands["gdacs_wildfire_orange_red_7d_count"]["min_history_days"] == 56


def test_the_co2_line_is_on_the_rate_not_the_level():
    """427 ppm against a line of 3.0 would ring every day; the band must not be on the level key."""
    b = ab.indicator_bands()["co2_annual_increase_ppm"]
    assert "co2_ppm_mauna_loa" not in ab.indicator_bands()
    assert "year" in b["unit"]


def test_the_live_sweep_runs_and_has_no_config_errors():
    r = ab.sweep_indicators()
    assert r["bands"] == 3 and r["config_errors"] == []
    for row in r["rows"]:
        assert row["verdict"] in (ab.OK, ab.ALARM, ab.RECORD_ONLY, ab.NO_VALUE)
        if row["verdict"] in (ab.OK, ab.ALARM):
            assert row["baseline"]                       # every judged row shows what it was judged against


def test_the_axis_bands_stay_null_and_the_counter_reports_both():
    """Signing indicator lines does not quietly fill in the 24 axis lines."""
    c = ab.for_cycle_report()
    assert c["awaiting_human_values"] == 24 and c["indicator_bands"] == 3
    assert "indicator_alarms" in c


# ── an unreadable history is not an empty one (found by --selftest, 10 Sep 2026) ──
#
# All 39 tests here were green while `core/alarm_bands.py --selftest` died with a
# traceback and exit 1. Its "no history" fixture was pathlib.Path("/nonexistent"),
# which on Windows resolves to C:\nonexistent — a real DIRECTORY on this machine.
# So exists() said True, read_text raised PermissionError, and it escaped through
# sweep_indicators, whose docstring promises "Never raises". That function is a
# cycle step (test_the_sweep_runs_right_after_scoring), so the raise takes down
# the step that watches the red lines.
#
# The forbidden fallback is to swallow it: a signed line that could not be checked
# must never be indistinguishable from a signed line that is quiet.

def test_an_absent_history_is_no_value_not_an_error(tmp_path):
    """The normal early state. Nothing has been observed yet, so bands report
    NO_VALUE — no alarm, and no config error either."""
    bands = _bands(tmp_path, k1={"axis": "A", "rule": "fixed", "threshold": 10,
                                 "direction": "lower_better", "signed_by": "e",
                                 "signed_on": "2026-09-10"})
    ind = ab.sweep_indicators(bands_path=bands, verified_path=tmp_path / "not_there.jsonl")
    assert ind["alarms"] == []
    assert ind["config_errors"] == []
    assert [r["verdict"] for r in ind["rows"]] == [ab.NO_VALUE]


def test_a_directory_where_the_history_should_be_is_a_config_error(tmp_path):
    """THE SELFTEST CRASH, as a test. A path that exists and is not a readable
    file must be reported on every band, and sweep_indicators must still
    RETURN — the 'Never raises' contract is what makes it a cycle step."""
    bands = _bands(tmp_path,
                   k1={"axis": "A", "rule": "fixed", "threshold": 10,
                       "direction": "lower_better", "signed_by": "e", "signed_on": "2026-09-10"},
                   k2={"axis": "B", "rule": "fixed", "threshold": 20,
                       "direction": "lower_better", "signed_by": "e", "signed_on": "2026-09-10"})
    a_directory = tmp_path / "history_dir"
    a_directory.mkdir()
    ind = ab.sweep_indicators(bands_path=bands, verified_path=a_directory)   # must not raise
    assert ind["alarms"] == [], "an unreadable history must never ring a bell"
    assert len(ind["config_errors"]) == 2 == ind["bands"], (
        "every band must be reported as unchecked, not just the first")
    for r in ind["config_errors"]:
        assert "cannot be read" in r["why"]
        assert r["verdict"] == ab.CONFIG_ERROR
        assert r["value"] is None


def test_an_unreadable_file_is_reported_not_treated_as_empty(tmp_path, monkeypatch):
    """The other way a present file becomes unreadable: a lock or lost
    permissions. It must land in config_errors, NOT look like no history."""
    bands = _bands(tmp_path, k1={"axis": "A", "rule": "fixed", "threshold": 10,
                                 "direction": "lower_better", "signed_by": "e",
                                 "signed_on": "2026-09-10"})
    hist = _verified(tmp_path, [_obs("k1", 5.0, "2026-09-09")])

    real = pathlib.Path.read_text

    def deny(self, *a, **k):
        # ONLY the history file — denying every read would also block the bands
        # file and the test would pass for the wrong reason (no bands, no errors)
        if self == hist:
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "read_text", deny)
    ind = ab.sweep_indicators(bands_path=bands, verified_path=hist)
    assert ind["alarms"] == []
    assert len(ind["config_errors"]) == 1
    assert "could not be read" in ind["config_errors"][0]["why"]
    assert [r["verdict"] for r in ind["rows"]] != [ab.NO_VALUE], (
        "an unreadable file was reported as 'no observation yet' — the two facts "
        "must not collapse into one")


def test_indicator_values_tells_absent_and_unreadable_apart(tmp_path):
    """The distinction at its source: {} for absent, a raise for unreadable."""
    assert ab.indicator_values(tmp_path / "nope.jsonl") == {}
    d = tmp_path / "dir_not_file"
    d.mkdir()
    try:
        ab.indicator_values(d)
    except ab.UnreadableSeries as exc:
        assert "not a readable file" in str(exc)
    else:
        raise AssertionError("a directory must not read as an empty series")


def test_the_protection_is_two_layers_and_both_hold(tmp_path, monkeypatch):
    """The unreadable path is stopped TWICE on purpose: is_file() in
    indicator_values, and the try/except around the read behind it. Neutering
    either one alone must still leave the sweep reporting rather than crashing —
    that is what defence in depth means here, and it is why a single-mutation
    net would prove nothing."""
    bands = _bands(tmp_path, k1={"axis": "A", "rule": "fixed", "threshold": 10,
                                 "direction": "lower_better", "signed_by": "e",
                                 "signed_on": "2026-09-10"})
    d = tmp_path / "history_dir"
    d.mkdir()
    assert ab.sweep_indicators(bands_path=bands, verified_path=d)["config_errors"]

    # layer 1 neutered: is_file() answers like the OLD exists() check
    monkeypatch.setattr(pathlib.Path, "is_file", lambda self: self.exists())
    ind = ab.sweep_indicators(bands_path=bands, verified_path=d)
    assert ind["config_errors"] and not ind["alarms"], (
        "with the is_file guard gone, the read's own except clause must still "
        "turn the failure into a reported config error")


def test_mutation_sweep_indicators_catching_it_is_load_bearing(tmp_path, monkeypatch):
    """MUTATION NET on the contract. sweep_indicators promises 'Never raises'
    and is wired as a cycle step. Remove its except clause — simulated here by
    making indicator_values raise — and the step dies instead of reporting.
    That was the shipped behaviour: 39 green tests, exit 1 from --selftest."""
    bands = _bands(tmp_path, k1={"axis": "A", "rule": "fixed", "threshold": 10,
                                 "direction": "lower_better", "signed_by": "e",
                                 "signed_on": "2026-09-10"})

    def boom(path=None):
        raise ab.UnreadableSeries("simulated: the history cannot be read")
    monkeypatch.setattr(ab, "indicator_values", boom)
    ind = ab.sweep_indicators(bands_path=bands, verified_path=tmp_path / "x.jsonl")
    assert not ind["alarms"]
    assert len(ind["config_errors"]) == 1
    assert "cannot be read" in ind["config_errors"][0]["why"]

    # and the negative half: a plain OSError is NOT swallowed silently, because
    # only UnreadableSeries is a named, expected condition
    def other(path=None):
        raise RuntimeError("something nobody predicted")
    monkeypatch.setattr(ab, "indicator_values", other)
    try:
        ab.sweep_indicators(bands_path=bands, verified_path=tmp_path / "x.jsonl")
    except RuntimeError:
        pass            # correct: an unexpected fault is not disguised as a config error
    else:
        raise AssertionError("an unpredicted exception was swallowed — the catch "
                             "must be narrow, or real bugs hide as config errors")


def test_the_live_selftest_passes_and_exits_zero():
    """The module's own selftest is part of the contract (CLAUDE.md: every module
    ships a --selftest). It exited 1 with a traceback until this fix."""
    import subprocess
    import sys as _sys
    r = subprocess.run([_sys.executable, str(REPO / "core" / "alarm_bands.py"), "--selftest"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"--selftest exited {r.returncode}:\n{r.stdout}\n{r.stderr}"
    assert "RESULT: OK" in r.stdout
    assert "Traceback" not in r.stderr
    assert "an unreadable history is a config error, not silence" in r.stdout
