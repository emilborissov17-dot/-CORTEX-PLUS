"""Tests for experiments/pulse/analyze.py — the measurement loop.

Written BEFORE the 24 h of data arrives, on purpose. A criterion that cannot be
mechanically checked is a story told afterwards; if the analyser is only written
once the numbers are in, it is impossible to prove the goalposts did not move.

The three cases that matter, and why:

  GAP        a real 45 s stall must FAIL C1 — that is the criterion.
  SLEEP GAP  a laptop that slept 6 h must NOT fail C1. Conflating the two would
             either condemn a healthy run, or — far worse — let a real stall hide
             inside a "sleep" bucket.
  INTERLEAVE two daemons wrote to the same file for ~80 s on 2026-07-13 during
             verification. Out-of-order timestamps are NOT corruption: the JSON is
             intact and the samples are real. An analyser that cried "corrupt!" at
             its own operator's footprints would be useless on the day it mattered.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "pulse"))

import analyze  # noqa: E402


T0 = datetime(2026, 7, 14, 3, 0, 0, tzinfo=timezone.utc)


def _sample(dt, pid=111, cpu=5.0, ram=56.0, churn=0, step=None,
            daemon_cpu=0.2, daemon_rss=42.0):
    return {
        "ts": dt.isoformat(),
        "pid": pid,
        "cpu_pct": cpu,
        "ram_pct": ram,
        "ram_available_gb": 6.0,
        "disk_free_gb": 500.0,
        "net": {"reachable": True, "latency_ms": 20.0, "down_kbps": 1.0},
        "cycle": {"running": bool(step), "step": step},
        "ledger": {"last_event": "CYCLE_STARTED"},
        "memory_files_changed": churn,
        "daemon_cpu_pct": daemon_cpu,
        "daemon_rss_mb": daemon_rss,
    }


def _write(tmp_path, samples, name="2026-07-14.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(s) for s in samples) + "\n", encoding="utf-8")
    return p


def _clean(tmp_path, n=30, step=10):
    return [_sample(T0 + timedelta(seconds=i * step)) for i in range(n)]


# ---------------------------------------------------------------------------
# C1 — gaps
# ---------------------------------------------------------------------------

def test_clean_stream_passes_c1(tmp_path):
    rows, _ = analyze.load(_write(tmp_path, _clean(tmp_path)))
    g = analyze.analyse_gaps(rows)

    assert g["verdict"] == "PASS"
    assert g["unexplained_gaps"] == []
    assert g["gap_median_sec"] == 10.0


def test_a_real_gap_fails_c1(tmp_path):
    """A 45 s stall is exactly what C1 exists to catch."""
    s = _clean(tmp_path, n=10)
    s += [_sample(T0 + timedelta(seconds=90 + 45 + i * 10)) for i in range(10)]

    rows, _ = analyze.load(_write(tmp_path, s))
    g = analyze.analyse_gaps(rows)

    assert g["verdict"] == "FAIL"
    assert len(g["unexplained_gaps"]) == 1
    assert g["unexplained_gaps"][0]["seconds"] == pytest.approx(45, abs=1)


def test_machine_sleep_does_not_fail_c1(tmp_path):
    """6 hours of sleep is not a daemon failure. This must never be a FAIL."""
    s = _clean(tmp_path, n=10)
    wake = T0 + timedelta(hours=6)
    s += [_sample(wake + timedelta(seconds=i * 10)) for i in range(10)]

    rows, _ = analyze.load(_write(tmp_path, s))
    g = analyze.analyse_gaps(rows)

    assert g["verdict"] == "PASS", "machine sleep was miscounted as a failure"
    assert len(g["probable_sleep_gaps"]) == 1
    # last sample of the first burst is at t+90s, so the gap to a 6h wake is
    # 360min - 1.5min = 358.5min
    assert g["probable_sleep_gaps"][0]["minutes"] == pytest.approx(358.5, abs=0.5)
    assert g["unexplained_gaps"] == []


def test_sleep_gap_is_excluded_from_awake_hours(tmp_path):
    """Span is 6h, but the daemon was only awake for ~3 minutes of it."""
    s = _clean(tmp_path, n=10)
    s += [_sample(T0 + timedelta(hours=6) + timedelta(seconds=i * 10)) for i in range(10)]

    rows, _ = analyze.load(_write(tmp_path, s))
    g = analyze.analyse_gaps(rows)

    assert g["span_hours"] == pytest.approx(6.03, abs=0.05)
    assert g["awake_hours"] < 0.1, "sleep time must not be counted as awake"


def test_a_stall_hiding_next_to_a_sleep_gap_is_still_caught(tmp_path):
    """THE dangerous case: a real 45 s stall must not be swallowed by the sleep
    bucket just because a sleep gap exists elsewhere in the stream."""
    s = _clean(tmp_path, n=5)                                  # 0-40s
    s += [_sample(T0 + timedelta(seconds=85 + i * 10)) for i in range(5)]   # 45s stall
    wake = T0 + timedelta(hours=6)
    s += [_sample(wake + timedelta(seconds=i * 10)) for i in range(5)]      # then sleep

    rows, _ = analyze.load(_write(tmp_path, s))
    g = analyze.analyse_gaps(rows)

    assert g["verdict"] == "FAIL"
    assert len(g["unexplained_gaps"]) == 1
    assert len(g["probable_sleep_gaps"]) == 1


def test_a_dead_daemon_does_not_hide_inside_the_sleep_exemption(tmp_path):
    """THE hole this closes. A daemon that crashed and was restarted 10 minutes
    later produces a gap long enough to look like sleep — and would have been
    waved through as 'not a failure'. That is the exact failure C1 exists to
    catch, hiding inside C1's own exemption.

    Across machine sleep the process SURVIVES (same pid). Across a death+restart
    the pid CHANGES. That is how we tell them apart.
    """
    s = [_sample(T0 + timedelta(seconds=i * 10), pid=111) for i in range(5)]
    # 10-minute gap, and the daemon comes back as a DIFFERENT process.
    back = T0 + timedelta(minutes=10)
    s += [_sample(back + timedelta(seconds=i * 10), pid=999) for i in range(5)]

    rows, _ = analyze.load(_write(tmp_path, s))
    g = analyze.analyse_gaps(rows)

    assert g["verdict"] == "FAIL", "a dead daemon was waved through as sleep"
    assert len(g["daemon_death_gaps"]) == 1
    assert g["daemon_death_gaps"][0]["pid_before"] == 111
    assert g["daemon_death_gaps"][0]["pid_after"] == 999
    assert g["probable_sleep_gaps"] == []


def test_real_machine_sleep_keeps_the_same_pid_and_passes(tmp_path):
    """The other side of the same coin: the daemon SURVIVED the sleep, so the pid
    is unchanged, and this must remain a PASS."""
    s = [_sample(T0 + timedelta(seconds=i * 10), pid=111) for i in range(5)]
    wake = T0 + timedelta(hours=6)
    s += [_sample(wake + timedelta(seconds=i * 10), pid=111) for i in range(5)]

    rows, _ = analyze.load(_write(tmp_path, s))
    g = analyze.analyse_gaps(rows)

    assert g["verdict"] == "PASS"
    assert len(g["probable_sleep_gaps"]) == 1
    assert "survived" in g["probable_sleep_gaps"][0]["classification"]
    assert g["daemon_death_gaps"] == []


def test_long_gap_without_pids_is_flagged_as_unknown(tmp_path):
    """Samples predating pid recording cannot be classified. Say so — do not
    silently assume the innocent explanation."""
    s = [_sample(T0 + timedelta(seconds=i * 10)) for i in range(5)]
    s += [_sample(T0 + timedelta(minutes=10) + timedelta(seconds=i * 10)) for i in range(5)]
    for x in s:
        del x["pid"]

    rows, _ = analyze.load(_write(tmp_path, s))
    g = analyze.analyse_gaps(rows)

    assert len(g["probable_sleep_gaps"]) == 1
    assert "cannot tell sleep from a daemon death" in g["probable_sleep_gaps"][0]["classification"]


def test_gap_exactly_at_the_limit_passes(tmp_path):
    s = [_sample(T0), _sample(T0 + timedelta(seconds=30))]
    rows, _ = analyze.load(_write(tmp_path, s))
    assert analyze.analyse_gaps(rows)["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Interleaved writers — an observation, not corruption
# ---------------------------------------------------------------------------

def test_interleaved_writers_are_not_corruption(tmp_path):
    """Two daemons, alternating, appended out of order. Real samples."""
    s = []
    for i in range(10):
        s.append(_sample(T0 + timedelta(seconds=i * 10), pid=111))
        s.append(_sample(T0 + timedelta(seconds=i * 10 + 5), pid=222))

    rows, torn = analyze.load(_write(tmp_path, s))
    w = analyze.analyse_writers(rows)

    assert torn == 0, "interleaving is not torn JSON"
    assert w["writers"] == 2
    assert w["interleaved"] is True
    assert w["samples_per_pid"] == {111: 10, 222: 10}


def test_interleaving_does_not_invent_gaps(tmp_path):
    """Out-of-order file order would produce negative and doubled gaps if we did
    not sort by timestamp first."""
    s = []
    for i in range(10):
        s.append(_sample(T0 + timedelta(seconds=i * 10), pid=111))
        s.append(_sample(T0 + timedelta(seconds=i * 10 + 5), pid=222))
    # Shuffle deterministically into a hostile order.
    s = s[::-1]

    rows, _ = analyze.load(_write(tmp_path, s))
    g = analyze.analyse_gaps(rows)

    assert g["verdict"] == "PASS"
    assert all(x["seconds"] > 0 for x in g["unexplained_gaps"])
    assert g["gap_median_sec"] == 5.0


def test_sequential_writers_are_not_flagged_as_interleaved(tmp_path):
    """Restarting the daemon appends under a new pid. That is normal — it is only
    OVERLAPPING time ranges that count as interleaving."""
    s = [_sample(T0 + timedelta(seconds=i * 10), pid=111) for i in range(5)]
    s += [_sample(T0 + timedelta(seconds=100 + i * 10), pid=222) for i in range(5)]

    rows, _ = analyze.load(_write(tmp_path, s))
    w = analyze.analyse_writers(rows)

    assert w["writers"] == 2
    assert w["interleaved"] is False


def test_torn_final_line_is_skipped_not_fatal(tmp_path):
    p = _write(tmp_path, _clean(tmp_path, n=5))
    with p.open("a", encoding="utf-8") as fh:
        fh.write('{"ts": "2026-07-14T03:01:0')      # power loss mid-append

    rows, torn = analyze.load(p)

    assert len(rows) == 5
    assert torn == 1


# ---------------------------------------------------------------------------
# C4 — cost
# ---------------------------------------------------------------------------

def test_cheap_daemon_passes_c4(tmp_path):
    rows, _ = analyze.load(_write(tmp_path, _clean(tmp_path)))
    c = analyze.analyse_cost(rows)

    assert c["verdict"] == "PASS"
    assert c["daemon_cpu_mean_pct"] == pytest.approx(0.2)
    assert c["ram_caution_breaches"] == 0


def test_expensive_daemon_fails_c4(tmp_path):
    s = [_sample(T0 + timedelta(seconds=i * 10), daemon_cpu=3.5) for i in range(10)]
    rows, _ = analyze.load(_write(tmp_path, s))

    assert analyze.analyse_cost(rows)["verdict"] == "FAIL"


def test_pre_existing_ram_pressure_is_not_blamed_on_the_experiment(tmp_path):
    """OBSERVED 2026-07-13: system RAM sat at 71-72% (a browser) while the daemon
    held 25 MB / 0.02% CPU. An analyser that failed C4 on that would blame the
    experiment for the machine's pre-existing state — and the 24 h run would
    'fail' before the model was even installed."""
    s = [_sample(T0 + timedelta(seconds=i * 10), ram=72.0, daemon_cpu=0.02,
                 daemon_rss=25.0) for i in range(10)]
    rows, _ = analyze.load(_write(tmp_path, s))
    c = analyze.analyse_cost(rows)

    assert c["verdict"] == "PASS", "the daemon was blamed for someone else's RAM"
    assert c["daemon_verdict"] == "PASS"
    assert c["ram_baseline_already_high"] is True
    assert c["ram_caution_breaches"] == 10      # still REPORTED, just not blamed
    assert "not the experiment's" in c["ram_note"]


def test_ram_breaches_are_still_reported_as_context(tmp_path):
    """Not blaming is not the same as not reporting. The number must be visible —
    model inference has to be judged against this baseline, not against zero."""
    s = [_sample(T0 + timedelta(seconds=i * 10), ram=65.0) for i in range(5)]
    s += [_sample(T0 + timedelta(seconds=50 + i * 10), ram=75.0) for i in range(5)]
    rows, _ = analyze.load(_write(tmp_path, s))
    c = analyze.analyse_cost(rows)

    assert c["ram_caution_breaches"] == 5
    assert c["ram_baseline_already_high"] is False   # it DID start below the line
    assert c["system_ram_max_pct"] == 75.0


def test_expensive_daemon_still_fails_c4_regardless_of_ram(tmp_path):
    """The attribution fix must not defang the criterion that IS the daemon's."""
    s = [_sample(T0 + timedelta(seconds=i * 10), ram=40.0, daemon_cpu=3.5)
         for i in range(10)]
    rows, _ = analyze.load(_write(tmp_path, s))

    assert analyze.analyse_cost(rows)["verdict"] == "FAIL"


def test_startup_spike_is_excluded_from_the_daemon_mean(tmp_path):
    """cpu_percent()'s first reading after priming includes process startup (~3%).
    Judging a 0.02% daemon on that artifact would be a false FAIL."""
    s = [_sample(T0, daemon_cpu=3.25)]
    s += [_sample(T0 + timedelta(seconds=(i + 1) * 10), daemon_cpu=0.02) for i in range(9)]
    rows, _ = analyze.load(_write(tmp_path, s))
    c = analyze.analyse_cost(rows)

    assert c["daemon_cpu_mean_pct"] == pytest.approx(0.02, abs=0.005)
    assert c["verdict"] == "PASS"


def test_old_samples_without_self_measurement_report_no_data(tmp_path):
    """A process's CPU cost cannot be recovered retroactively. Say so, rather than
    quietly reporting a PASS from an empty list."""
    s = [_sample(T0 + timedelta(seconds=i * 10)) for i in range(5)]
    for x in s:
        del x["daemon_cpu_pct"]
        del x["daemon_rss_mb"]

    rows, _ = analyze.load(_write(tmp_path, s))
    c = analyze.analyse_cost(rows)

    assert c["verdict"] == "NO_DATA"
    assert "retroactively" in c["note"]


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

def test_timeline_marks_state_transitions(tmp_path, capsys):
    """Tomorrow's first autonomous wake must read as a story: idle → cycle → idle."""
    s  = [_sample(T0 + timedelta(seconds=i * 10)) for i in range(3)]
    s += [_sample(T0 + timedelta(seconds=30 + i * 10), step="web_intelligence",
                  cpu=88.0, churn=14) for i in range(3)]
    s += [_sample(T0 + timedelta(seconds=60 + i * 10)) for i in range(3)]

    rows, _ = analyze.load(_write(tmp_path, s))
    analyze.timeline(rows, "00:00-23:59", local=False)

    out = capsys.readouterr().out
    assert "idle → cycle:web_intelligence" in out
    assert "cycle:web_intelligence → idle" in out


def test_timeline_handles_an_empty_window(tmp_path, capsys):
    rows, _ = analyze.load(_write(tmp_path, _clean(tmp_path)))
    analyze.timeline(rows, "20:00-21:00", local=False)
    assert "no samples in" in capsys.readouterr().out


def test_report_returns_nonzero_on_failure(tmp_path):
    s = _clean(tmp_path, n=5)
    s += [_sample(T0 + timedelta(seconds=90 + i * 10)) for i in range(5)]  # 45s gap
    p = _write(tmp_path, s)

    assert analyze.report(p) == 1


def test_report_returns_zero_on_pass(tmp_path):
    assert analyze.report(_write(tmp_path, _clean(tmp_path))) == 0
