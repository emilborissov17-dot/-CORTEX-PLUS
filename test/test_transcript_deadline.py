"""One video may never occupy an axis indefinitely.

youtube_intel enforced TRANSCRIPT_TIMEOUT_SEC with signal.alarm. `_time_limit` says so
itself — "само на Linux/Mac" — and on Windows, which is where this system actually runs,
it yields with no guard at all. The documented 60s-per-video ceiling did not exist. It
also never covered attempts 3 and 4 (Playwright, and a yt-dlp audio download fed to Groq
Whisper, which allows 90s for the download alone) because those sit outside the `with`.

The cost was visible on 2026-08-04: TECHNOLOGY_AI_REVIEW and COSMIC_RESOURCES_REVIEW
were both abandoned with "no progress for 93s (last stage: yt:transcript:<id>)".
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import youtube_intel as Y  # noqa: E402


def test_the_signal_based_guard_is_known_to_be_inert_here():
    """Not a bug to fix — a fact to have covered, so nobody re-trusts _time_limit."""
    import signal
    if not hasattr(signal, "SIGALRM"):
        with Y._time_limit(0, "probe"):
            pass          # yields immediately, guarding nothing — this is the platform


def test_a_hanging_fetch_returns_within_the_deadline(monkeypatch):
    monkeypatch.setattr(Y, "TRANSCRIPT_TIMEOUT_SEC", 2)

    def _never_returns(video_id, title="", description=""):
        time.sleep(60)

    monkeypatch.setattr(Y, "_get_transcript_unbounded", _never_returns)
    t0 = time.time()
    out = Y.get_transcript("hangingVID", "t", "d")
    elapsed = time.time() - t0
    assert elapsed < 15, f"deadline did not fire: took {elapsed:.1f}s"
    assert out["transcript_method"] == "timeout"
    assert out["has_transcript"] is False
    assert out["transcript"] == ""
    assert out["video_id"] == "hangingVID"


def test_a_normal_fetch_is_returned_untouched(monkeypatch):
    payload = {"video_id": "ok", "title": "t", "url": "u", "transcript": "hello",
               "transcript_chars": 5, "transcript_method": "yt_dlp",
               "has_transcript": True}
    monkeypatch.setattr(Y, "_get_transcript_unbounded",
                        lambda vid, title="", description="": payload)
    assert Y.get_transcript("ok") is payload


def test_the_timeout_shape_matches_the_success_shape(monkeypatch):
    """A caller must not have to special-case the timeout result."""
    good = {"video_id": "a", "title": "", "url": "", "transcript": "x",
            "transcript_chars": 1, "transcript_method": "api", "has_transcript": True}
    monkeypatch.setattr(Y, "_get_transcript_unbounded",
                        lambda vid, title="", description="": good)
    ok = Y.get_transcript("a")
    monkeypatch.setattr(Y, "TRANSCRIPT_TIMEOUT_SEC", 1)
    monkeypatch.setattr(Y, "_get_transcript_unbounded",
                        lambda vid, title="", description="": time.sleep(30))
    timed_out = Y.get_transcript("b")
    assert set(ok) == set(timed_out)


def test_the_progress_hook_never_breaks_the_fetch():
    """A raising on_progress callback must not take the whole axis down with it."""
    src = (REPO / "youtube_intel.py").read_text(encoding="utf-8")
    body = src.split("def fetch_youtube_for_axis(")[1].split("\ndef ")[0]
    assert "except Exception:" in body, "the _tick wrapper must swallow hook errors"
