#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The YouTube breaker must count 403 as a refusal, not as a reset.

THE DEFECT THESE TESTS DESCRIBE (measured 12 Sep 2026). core/media_tools.py
counts a consecutive streak of HTTP 429 and parks every yt-dlp call after
YT_429_TRIP_AFTER of them. is_429() requires the literal "429", so a
403 Forbidden — the same host refusing the same caller for the same reason —
falls into the `else` branch and sets self.streak = 0. An alternating
429/403/429/403 sequence therefore never reaches five in a row and the breaker
never trips. The evidence: one web_intelligence run printed 319 refusal lines
and memory/yt_backoff.json does not exist.

WHAT A PASS LOOKS LIKE, AND WHAT MUST NOT COUNT AS ONE. The breaker parking
because the trip threshold was lowered is NOT a pass. Neither is a breaker that
parks on any failure at all — that would park on a dropped Wi-Fi connection and
blind the cycle for twenty minutes for a reason YouTube had nothing to do with.
The deliberate reset on an unrelated failure is correct behaviour and
test_unrelated_failure_still_resets_the_streak exists to stop the fix from
eating it. Every test below fails if the guard it names is removed.

Everything is driven through the public surface (record / parked / reset /
clear_park) and writes only to tmp_path: a test that parks the live breaker
would blind tonight's cycle.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.media_tools import YouTubeBreaker, YT_429_TRIP_AFTER  # noqa: E402

R429 = "ERROR: unable to download video subtitles: HTTP Error 429: Too Many Requests"
R403 = "ERROR: unable to download video data: HTTP Error 403: Forbidden"
NETWORK = "ERROR: [Errno 11001] getaddrinfo failed"
DISK = "OSError: [Errno 28] No space left on device"


def _breaker(tmp_path, **kw) -> YouTubeBreaker:
    return YouTubeBreaker(state_file=tmp_path / "yt_backoff.json", **kw)


def test_the_threshold_is_five_and_the_test_does_not_move_it():
    """Guards the guard: a fix that trips sooner is not the fix asked for."""
    assert YT_429_TRIP_AFTER == 5


def test_three_429_and_two_403_trip_the_breaker(tmp_path):
    """The case the live run hit 319 times and the breaker slept through.

    Five refusals from one host, in a row, mixed. Under the current code the two
    403s reset the streak to zero and this assertion fails — which is the point
    of the file.
    """
    b = _breaker(tmp_path)
    for stderr in (R429, R429, R429, R403, R403):
        b.record(stderr)
    assert b.parked, (
        f"five consecutive refusals from YouTube (3x429 + 2x403) did not park the "
        f"breaker; streak={b.streak}, total_429={b.total_429}. A 403 is the same "
        f"host refusing the same caller — it must count, not reset.")
    assert b.seconds_left() > 0


def test_five_403_alone_trip_the_breaker(tmp_path):
    """403 is not a lesser refusal. On its own it must be enough."""
    b = _breaker(tmp_path)
    for _ in range(YT_429_TRIP_AFTER):
        b.record(R403)
    assert b.parked, (
        f"{YT_429_TRIP_AFTER} consecutive 403s left the breaker open; "
        f"streak={b.streak}")


def test_four_refusals_do_not_trip_it(tmp_path):
    """One below the threshold stays open — the fix must not park on anything."""
    b = _breaker(tmp_path)
    for stderr in (R429, R403, R429, R403):
        b.record(stderr)
    assert not b.parked, "parked after four refusals; the threshold is five"


def test_success_resets_the_streak(tmp_path):
    """A working call means the host is answering us again."""
    b = _breaker(tmp_path)
    for stderr in (R429, R429, R403, R403):
        b.record(stderr)
    b.record("", success=True)
    assert b.streak == 0, f"a success left streak={b.streak}"
    b.record(R429)
    assert not b.parked, ("the streak carried across a success: one more refusal "
                          "after a working call parked the breaker")


def test_unrelated_failure_still_resets_the_streak(tmp_path):
    """DELIBERATE, and the fix must not eat it.

    A DNS failure or a full disk is not evidence that YouTube is rate-limiting
    us. Counting it would park every yt-dlp call for twenty minutes because the
    Wi-Fi blinked, and the cycle would go blind for a reason the host had no part
    in. The existing comment in media_tools says exactly this; these lines make
    it a test instead of a promise.
    """
    b = _breaker(tmp_path)
    b.record(R429)
    b.record(R429)
    b.record(NETWORK)
    assert b.streak == 0, f"a network error was counted as a refusal (streak={b.streak})"
    b.record(R429)
    b.record(DISK)
    assert b.streak == 0, f"a disk error was counted as a refusal (streak={b.streak})"
    for _ in range(YT_429_TRIP_AFTER - 1):
        b.record(R403)
    assert not b.parked, ("unrelated failures were counted towards the trip: "
                          "four refusals plus two non-refusals parked it")


def test_a_park_survives_the_process(tmp_path):
    """The nightly cycle is a fresh process; a park it cannot see is no park.

    Two objects over one state file stand in for two processes: the second reads
    what the first wrote, which is the whole mechanism.
    """
    state = tmp_path / "yt_backoff.json"
    first = YouTubeBreaker(state_file=state)
    for _ in range(YT_429_TRIP_AFTER):
        first.record(R429)
    assert first.parked, "setup failed: the first breaker did not park"
    assert state.is_file(), "the park was never written to disk"

    second = YouTubeBreaker(state_file=state)
    assert second.parked, (
        "a fresh breaker over the same state file is not parked — the park does "
        "not survive the process, and the nightly cycle IS a fresh process")
    assert second.seconds_left() > 0

    second.clear_park()
    third = YouTubeBreaker(state_file=state)
    assert not third.parked, "clear_park() did not survive to the next process"


def test_the_park_line_is_printed_once(tmp_path):
    """The announcement is for a human; 319 copies of it is not an announcement."""
    b = _breaker(tmp_path)
    for _ in range(YT_429_TRIP_AFTER):
        b.record(R429)
    first = b.park_line()
    assert first, "the breaker parked without announcing it"
    assert b.park_line() == "", "the park line was printed twice"


def test_no_live_state_is_written(tmp_path):
    """This file must not park the breaker the cycle will use tonight."""
    live = REPO / "memory" / "yt_backoff.json"
    before = live.is_file()
    b = _breaker(tmp_path)
    for _ in range(YT_429_TRIP_AFTER + 2):
        b.record(R429)
    assert live.is_file() == before, (
        f"the test touched {live} — a test that parks the live breaker blinds "
        f"tonight's cycle for twenty minutes")
