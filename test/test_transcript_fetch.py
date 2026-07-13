"""Permanent test suite for transcript fetching (item 4).

Covers the three behaviours and the two sanity checks that were specified:

  (a) sticky IP-block fallback — the FIRST block in a cycle switches the rest
      of the cycle straight to Playwright, and resets on the next cycle.
      SANITY: after a simulated block, NO further API attempts are made.

  (b) 2-3 parallel Playwright contexts per axis, bounded by the BODY scan RAM
      directive (read exactly the way fast_cycle_runner reads workers=).

  (c) cross-cycle transcript cache keyed by video ID, consulted before ANY
      fetch attempt.
      SANITY: a cached video costs ZERO network calls.

Every test isolates the cache into tmp_path — none of them touch the real
memory/transcript_cache/ tree, and none of them make a real network call.
"""
import json
import sys
import types

import pytest

import agents.internet.internet_agent as ia


@pytest.fixture(autouse=True)
def isolated_cycle(tmp_path, monkeypatch):
    """Fresh cycle state + a throwaway cache dir for every test.

    Also stubs out the Playwright transcript step. Without this, any test that
    lets get_transcript() fall past the api/yt-dlp stages launches a REAL
    Chromium against youtube-transcript.ai — which is what made two of these
    tests take 5s each on first write. No test may touch the network.
    """
    monkeypatch.setattr(ia, "TRANSCRIPT_CACHE_DIR", tmp_path / "transcript_cache")

    stub = types.ModuleType("youtube_intel")
    stub._get_transcript_playwright = lambda vid: None
    monkeypatch.setitem(sys.modules, "youtube_intel", stub)

    ia.reset_cycle_state()
    yield
    ia.reset_cycle_state()


# ---------------------------------------------------------------------------
# Tripwires — any of these firing means we hit the network when we should not
# ---------------------------------------------------------------------------


class _Tripwire:
    """Counts calls; explodes if called when it must not be."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        return None


def _fake_yt_api_module(exc_factory=None, transcript="hello world"):
    """A stand-in for the youtube_transcript_api package.

    Counts every fetch() so we can assert "no further API attempts".
    """
    counter = {"fetches": 0}

    class _Snippet:
        def __init__(self, text):
            self.text = text

    class YouTubeTranscriptApi:
        def fetch(self, video_id, languages=None):
            counter["fetches"] += 1
            if exc_factory:
                raise exc_factory()
            return [_Snippet(transcript)]

    mod = types.ModuleType("youtube_transcript_api")
    mod.YouTubeTranscriptApi = YouTubeTranscriptApi
    mod._counter = counter
    return mod, counter


class RequestBlocked(Exception):
    """Mirrors youtube_transcript_api's real exception class name."""


# ---------------------------------------------------------------------------
# (c) Cross-cycle cache — SANITY: cached video = zero network calls
# ---------------------------------------------------------------------------


def test_cached_video_makes_zero_network_calls(monkeypatch):
    """THE sanity check: a cache hit must not touch api, yt-dlp, Playwright,
    or Whisper. Every fetch path is a tripwire."""
    ia.TRANSCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (ia.TRANSCRIPT_CACHE_DIR / "vid00000001.json").write_text(
        json.dumps({
            "video_id": "vid00000001",
            "transcript": "previously fetched transcript",
            "transcript_chars": 29,
            "transcript_method": "youtube_transcript_api",
            "cached_at": "2026-07-12T00:00:00+00:00",
        }),
        encoding="utf-8",
    )

    api, ytdlp, whisper = _Tripwire(), _Tripwire(), _Tripwire()
    monkeypatch.setattr(ia, "_get_transcript_api", api)
    monkeypatch.setattr(ia, "_get_transcript_ytdlp", ytdlp)
    monkeypatch.setattr(ia, "_get_transcript_whisper", whisper)

    got = ia.get_transcript("vid00000001", title="T")

    assert got["transcript"] == "previously fetched transcript"
    assert got["transcript_method"] == "youtube_transcript_api"
    assert got["has_transcript"] is True
    assert (api.calls, ytdlp.calls, whisper.calls) == (0, 0, 0), \
        "cache hit must make ZERO fetch attempts"


def test_successful_fetch_is_written_to_cache(monkeypatch):
    monkeypatch.setattr(ia, "_get_transcript_api", lambda vid: "fresh transcript")

    ia.get_transcript("vid00000002", title="T")

    cached = json.loads((ia.TRANSCRIPT_CACHE_DIR / "vid00000002.json").read_text(encoding="utf-8"))
    assert cached["transcript"] == "fresh transcript"
    assert cached["transcript_method"] == "youtube_transcript_api"


def test_second_fetch_of_same_video_hits_cache(monkeypatch):
    """Cross-cycle behaviour: fetch once, then a later call costs nothing."""
    calls = _Tripwire()

    def once(vid):
        calls.calls += 1
        return "only fetched once"

    monkeypatch.setattr(ia, "_get_transcript_api", once)

    ia.get_transcript("vid00000003")
    ia.reset_cycle_state()          # simulate a brand-new cycle
    got = ia.get_transcript("vid00000003")

    assert got["transcript"] == "only fetched once"
    assert calls.calls == 1, "second cycle must be served from cache"


def test_description_fallback_is_not_cached(monkeypatch):
    """Caching a description-fallback would permanently poison the video:
    we'd never try for a real transcript again."""
    monkeypatch.setattr(ia, "_get_transcript_api", lambda vid: None)
    monkeypatch.setattr(ia, "_get_transcript_ytdlp", lambda vid: None)
    monkeypatch.setattr(ia, "_get_transcript_whisper", lambda vid: None)

    got = ia.get_transcript("vid00000004", description="just a description")

    assert got["transcript_method"] == "description"
    assert not (ia.TRANSCRIPT_CACHE_DIR / "vid00000004.json").exists()


def test_failed_fetch_is_not_cached(monkeypatch):
    monkeypatch.setattr(ia, "_get_transcript_api", lambda vid: None)
    monkeypatch.setattr(ia, "_get_transcript_ytdlp", lambda vid: None)
    monkeypatch.setattr(ia, "_get_transcript_whisper", lambda vid: None)

    got = ia.get_transcript("vid00000005")

    assert got["transcript_method"] == "none"
    assert not (ia.TRANSCRIPT_CACHE_DIR / "vid00000005.json").exists()


def test_corrupt_cache_file_is_treated_as_miss(monkeypatch):
    ia.TRANSCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (ia.TRANSCRIPT_CACHE_DIR / "vid00000006.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(ia, "_get_transcript_api", lambda vid: "refetched")

    got = ia.get_transcript("vid00000006")

    assert got["transcript"] == "refetched"


# ---------------------------------------------------------------------------
# (a) Sticky IP-block — SANITY: no further API attempts after the first block
# ---------------------------------------------------------------------------


def test_first_ip_block_makes_no_further_api_attempts(monkeypatch):
    """THE sanity check: once blocked, the rest of the cycle must not call
    youtube-transcript-api again — not even once."""
    fake_mod, counter = _fake_yt_api_module(exc_factory=RequestBlocked)
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_mod)

    assert not ia._is_ip_blocked()

    # Video 1: hits the block.
    assert ia._get_transcript_api("vid1") is None
    assert ia._is_ip_blocked(), "an IP block must set the sticky flag"
    fetches_after_block = counter["fetches"]
    assert fetches_after_block >= 1

    # Videos 2..5: must short-circuit with ZERO further fetch attempts.
    for vid in ("vid2", "vid3", "vid4", "vid5"):
        assert ia._get_transcript_api(vid) is None

    assert counter["fetches"] == fetches_after_block, \
        "no further API attempts allowed after the first IP block"


def test_ip_block_stops_the_per_language_loop_immediately(monkeypatch):
    """A block is per-IP, not per-language: don't grind through 5 languages."""
    fake_mod, counter = _fake_yt_api_module(exc_factory=RequestBlocked)
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_mod)

    ia._get_transcript_api("vid1")

    assert counter["fetches"] == 1, (
        "must bail on the first blocked language, not grind through all "
        f"{len(ia.TRANSCRIPT_LANGUAGES)}"
    )


def test_ip_block_also_skips_ytdlp(monkeypatch):
    """yt-dlp hits YouTube from the SAME IP, so the block applies to it too."""
    tripwire = _Tripwire()
    monkeypatch.setattr(ia.subprocess, "run", tripwire)

    ia._mark_ip_blocked("test")
    assert ia._get_transcript_ytdlp("vid1") is None
    assert tripwire.calls == 0, "yt-dlp must not be spawned while IP-blocked"


def test_ip_block_routes_search_straight_to_playwright(monkeypatch):
    api_tripwire = _Tripwire()
    monkeypatch.setattr(ia, "_yt_search_api", api_tripwire)
    monkeypatch.setattr(ia, "_yt_search_playwright",
                        lambda q, n=5: [{"video_id": "pw", "url": "u"}])
    monkeypatch.setattr(ia, "YOUTUBE_API_KEY", "fake-key")

    ia._mark_ip_blocked("test")
    got = ia._search_youtube("query")

    assert got == [{"video_id": "pw", "url": "u"}]
    assert api_tripwire.calls == 0, "must go straight to Playwright when blocked"


def test_search_uses_api_when_not_blocked(monkeypatch):
    """The flip side: without a block we must still prefer the cheap API."""
    monkeypatch.setattr(ia, "_yt_search_api",
                        lambda q, n=3: [{"video_id": "api", "url": "u"}])
    pw_tripwire = _Tripwire()
    monkeypatch.setattr(ia, "_yt_search_playwright", pw_tripwire)
    monkeypatch.setattr(ia, "YOUTUBE_API_KEY", "fake-key")
    monkeypatch.setattr(ia, "_YT_QUOTA_EXHAUSTED", False)

    got = ia._search_youtube("query")

    assert got == [{"video_id": "api", "url": "u"}]
    assert pw_tripwire.calls == 0


def test_sticky_flag_resets_on_next_cycle():
    """A block must not outlive its cycle — the next run() gets a clean slate,
    otherwise one bad morning pins us to Playwright all day."""
    ia._mark_ip_blocked("test")
    assert ia._is_ip_blocked()

    ia.reset_cycle_state()

    assert not ia._is_ip_blocked()


def test_non_block_errors_do_not_trip_the_flag(monkeypatch):
    """A missing-transcript error is NOT an IP block. Over-tripping the flag
    would needlessly push the whole cycle onto the slow Playwright path."""
    fake_mod, _ = _fake_yt_api_module(exc_factory=lambda: ValueError("no transcript"))
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_mod)

    ia._get_transcript_api("vid1")

    assert not ia._is_ip_blocked()


@pytest.mark.parametrize("err,expected", [
    (RequestBlocked("blocked"), True),
    (Exception("YouTube is blocking requests from your IP"), True),
    (Exception("Too Many Requests"), True),
    (Exception("Subtitles are disabled for this video"), False),
    (Exception("video unavailable"), False),
])
def test_ip_block_error_classifier(err, expected):
    assert ia._is_ip_block_error(err) is expected


# ---------------------------------------------------------------------------
# (b) Parallel Playwright contexts, bounded by the BODY scan RAM directive
# ---------------------------------------------------------------------------


def _write_directives(tmp_path, monkeypatch, workers):
    mem = tmp_path / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "adaptive_directives.json").write_text(
        json.dumps({"max_parallel_workers": workers}), encoding="utf-8"
    )
    monkeypatch.setattr(ia, "BASE_DIR", tmp_path)


@pytest.mark.parametrize("directive,expected", [
    (1, 1),   # RAM/CPU > 85% → body_scanner says single-worker → we obey
    (2, 2),   # RAM/CPU > 70% → 2 contexts
    (3, 3),   # healthy → 3 contexts
    (8, 3),   # never exceed our own ceiling, whatever the directive says
    (0, 1),   # never drop below 1, or nothing would run at all
])
def test_playwright_workers_follows_body_directive(tmp_path, monkeypatch, directive, expected):
    _write_directives(tmp_path, monkeypatch, directive)
    assert ia._playwright_workers() == expected


def test_playwright_workers_defaults_when_directive_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "BASE_DIR", tmp_path)  # no memory/ dir at all
    assert ia._playwright_workers() == 3


def test_playwright_workers_defaults_on_corrupt_directive(tmp_path, monkeypatch):
    mem = tmp_path / "memory"
    mem.mkdir(parents=True)
    (mem / "adaptive_directives.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(ia, "BASE_DIR", tmp_path)
    assert ia._playwright_workers() == 3


def test_axis_fetch_runs_transcripts_in_parallel(tmp_path, monkeypatch):
    """3 videos with a RAM-healthy directive must be fetched concurrently, and
    every video must still come back exactly once."""
    _write_directives(tmp_path, monkeypatch, 3)

    monkeypatch.setattr(ia, "_search_youtube", lambda q, max_results=5: [
        {"video_id": f"v{i}", "title": f"T{i}", "description": "", "url": f"u{i}"}
        for i in range(3)
    ])
    monkeypatch.setattr(ia, "_load_adaptive_memory", lambda: {})
    monkeypatch.setattr(ia, "_save_adaptive_memory", lambda m: None)

    import threading
    # A barrier is the honest test of concurrency: all 3 fetches must be
    # in flight AT THE SAME TIME to release it. If the code were serial, the
    # first fetch would block here forever and the barrier would time out.
    # (Asserting on thread names is not enough — a fast enough task gets
    # reused on one pooled thread and looks serial when it is not.)
    barrier = threading.Barrier(3, timeout=10)

    def fake_transcript(video_id, title="", description=""):
        barrier.wait()   # BrokenBarrierError on timeout -> test fails
        return ia._transcript_result(video_id, title, f"transcript for {video_id}", "yt_dlp")

    monkeypatch.setattr(ia, "get_transcript", fake_transcript)

    items = ia._fetch_youtube_for_axis("ENERGY")

    assert {i["video_id"] for i in items} == {"v0", "v1", "v2"}
    assert not barrier.broken, "all 3 transcript fetches must be concurrent"


def test_axis_fetch_is_serial_when_ram_directive_is_one(tmp_path, monkeypatch):
    """RAM critical → body_scanner drops workers to 1 → we must go serial,
    because each Playwright context is a whole Chromium."""
    _write_directives(tmp_path, monkeypatch, 1)

    monkeypatch.setattr(ia, "_search_youtube", lambda q, max_results=5: [
        {"video_id": f"v{i}", "title": f"T{i}", "description": "", "url": f"u{i}"}
        for i in range(3)
    ])
    monkeypatch.setattr(ia, "_load_adaptive_memory", lambda: {})
    monkeypatch.setattr(ia, "_save_adaptive_memory", lambda m: None)
    monkeypatch.setattr(ia, "time", types.SimpleNamespace(sleep=lambda s: None))

    import threading
    main = threading.current_thread().name
    seen_threads = set()

    def fake_transcript(video_id, title="", description=""):
        seen_threads.add(threading.current_thread().name)
        return ia._transcript_result(video_id, title, f"t {video_id}", "yt_dlp")

    monkeypatch.setattr(ia, "get_transcript", fake_transcript)

    items = ia._fetch_youtube_for_axis("ENERGY")

    assert len(items) == 3
    assert seen_threads == {main}, "workers=1 must stay on the calling thread"
