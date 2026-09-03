# -*- coding: utf-8 -*-
"""
core/media_tools.py — ffmpeg/deno resolution and the subtitle-429 parking rule (3 Sep 2026).

No network, no subprocess: yt-dlp is never run. The command is built and captured.
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import core.media_tools as M  # noqa: E402
import youtube_intel as Y     # noqa: E402


# ── SubtitleRateLimit ─────────────────────────────────────────────────────────

_429 = "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"


def _fresh(tmp_path, n=3):
    return M.YouTubeBreaker(trip_after=n, state_file=tmp_path / "yt_backoff.json")


def test_parks_after_n_consecutive_429_and_announces_once(tmp_path):
    L = _fresh(tmp_path, 3)
    assert L.record(_429) is False
    assert L.record(_429) is False
    assert L.record(_429) is True
    assert L.parked and L.streak == 3 and L.total_429 == 3
    line = L.park_line()
    assert "[YT-BREAKER]" in line and "3 times in a row" in line
    assert L.park_line() == ""          # once per cycle


def test_non_429_failure_breaks_the_streak(tmp_path):
    L = _fresh(tmp_path, 3)
    L.record(_429); L.record(_429)
    L.record("ERROR: [youtube] abc: Private video")
    assert L.streak == 0 and not L.parked
    L.record(_429); L.record(_429)
    assert not L.parked                  # 2 after the reset, not 4


def test_success_resets_streak_but_reset_keeps_the_wall_clock_park(tmp_path):
    L = _fresh(tmp_path, 2)
    L.record(_429)
    L.record("", success=True)
    assert L.streak == 0
    L.record(_429); L.record(_429)
    assert L.parked
    L.reset()                       # per-process counters only (Kimi Q2)
    assert L.parked and L.streak == 0 and L.total_429 == 0 and not L.announced
    L.clear_park()
    assert not L.parked


def test_park_is_wall_clock_persisted_and_escalates(tmp_path, monkeypatch):
    import time as _t
    now = [1_000_000.0]
    monkeypatch.setattr(_t, "time", lambda: now[0])
    L = _fresh(tmp_path, 2)
    L.record(_429); L.record(_429)
    assert L.parked and L.seconds_left() == 5 * 60 and L.level == 1
    # a NEW process (the nightly cycle) sees the same park from disk
    L2 = _fresh(tmp_path, 2)
    assert L2.parked and L2.seconds_left() == 5 * 60
    now[0] += 5 * 60 + 1
    assert not L2.parked
    L2.record(_429); L2.record(_429)
    assert L2.seconds_left() == 10 * 60 and L2.level == 2      # escalated
    now[0] += 10 * 60 + 1
    L2.record(_429); L2.record(_429)
    assert L2.seconds_left() == 20 * 60                          # cap
    now[0] += 20 * 60 + 1
    L2.record("", success=True)                                  # clean success closes the ladder
    assert L2.level == 0


def test_default_threshold_is_the_documented_constant():
    assert M.SUBS_LIMIT.trip_after == M.YT_429_TRIP_AFTER == M.YT_SUBS_429_PARK_AFTER == 5


# ── flags reach the yt-dlp argv ───────────────────────────────────────────────

def _isolate_live_breaker(monkeypatch, tmp_path):
    """The module-level breaker must never write memory/yt_backoff.json from a test
    (conftest's _no_live_writes). Point it at tmp, then clear."""
    monkeypatch.setattr(Y._SUBS_LIMIT, "state_file", tmp_path / "yt_backoff.json")
    Y._SUBS_LIMIT.clear_park(); Y._SUBS_LIMIT.reset()


def _capture(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return types.SimpleNamespace(returncode=1, stdout="", stderr=_429)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def test_subtitle_call_carries_resolved_ffmpeg_and_deno(monkeypatch, tmp_path):
    ff = tmp_path / "ffmpeg.exe"; ff.write_bytes(b"")
    dn = tmp_path / "deno.exe"; dn.write_bytes(b"")
    monkeypatch.setattr(M, "find_ffmpeg", lambda: str(ff))
    monkeypatch.setattr(M, "find_deno", lambda: str(dn))
    monkeypatch.setattr(M, "_runs", lambda p: True)
    _isolate_live_breaker(monkeypatch, tmp_path)
    seen = _capture(monkeypatch)
    Y._get_transcript_yt_dlp("dQw4w9WgXcQ")
    cmd = seen["cmd"]
    assert cmd[0] == sys.executable and cmd[1:3] == ["-m", "yt_dlp"]
    assert cmd[cmd.index("--ffmpeg-location") + 1] == str(tmp_path)
    assert cmd[cmd.index("--js-runtimes") + 1] == f"deno:{dn}"
    # the URL is still the last argument
    assert cmd[-1].endswith("dQw4w9WgXcQ")


def test_nothing_found_means_no_flags_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "find_ffmpeg", lambda: None)
    monkeypatch.setattr(M, "find_deno", lambda: None)
    assert M.yt_dlp_extra_args() == []
    _isolate_live_breaker(monkeypatch, tmp_path)
    seen = _capture(monkeypatch)
    Y._get_transcript_yt_dlp("dQw4w9WgXcQ")
    assert "--ffmpeg-location" not in seen["cmd"] and "--js-runtimes" not in seen["cmd"]


def test_after_parking_no_process_is_spawned(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(M, "find_ffmpeg", lambda: None)
    monkeypatch.setattr(M, "find_deno", lambda: None)
    _isolate_live_breaker(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return types.SimpleNamespace(returncode=1, stdout="", stderr=_429)

    monkeypatch.setattr(subprocess, "run", fake_run)
    for i in range(M.YT_SUBS_429_PARK_AFTER + 4):
        Y._get_transcript_yt_dlp(f"vid{i:08d}")
    assert calls["n"] == M.YT_SUBS_429_PARK_AFTER     # the rest never spawned
    out = capsys.readouterr().out
    assert out.count("[YT-BREAKER]") == 1
    Y._SUBS_LIMIT.clear_park(); Y._SUBS_LIMIT.reset()   # still on tmp via the fixture


def test_version_flag_per_binary():
    assert M._version_flag("C:/x/ffmpeg.exe") == "-version"
    assert M._version_flag("/usr/bin/deno") == "--version"


def test_a_found_binary_that_does_not_run_is_not_passed(monkeypatch, tmp_path):
    """Kimi Q4: a dead runtime handed to yt-dlp is worse than no flag."""
    dn = tmp_path / "deno.exe"; dn.write_bytes(b"")
    monkeypatch.setattr(M, "find_ffmpeg", lambda: None)
    monkeypatch.setattr(M, "find_deno", lambda: str(dn))
    M._RUNS.clear()
    assert M.yt_dlp_extra_args() == []            # an empty file cannot answer --version
    assert "FAIL    deno" in M.dep_check_lines()[1]


def test_dep_check_lines_speak_the_runner_vocabulary(monkeypatch):
    monkeypatch.setattr(M, "find_ffmpeg", lambda: None)
    monkeypatch.setattr(M, "find_deno", lambda: "C:/x/deno.exe")
    monkeypatch.setattr(M, "_runs", lambda p: True)
    monkeypatch.setattr(M, "binary_version", lambda p: "deno 2.x")
    lines = M.dep_check_lines()
    assert lines[0].startswith("[DEP_CHECK] MISSING ffmpeg") and "install_media_deps" in lines[0]
    assert lines[1].startswith("[DEP_CHECK] OK      deno")
