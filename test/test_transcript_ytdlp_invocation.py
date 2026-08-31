r"""The transcript fallback that was never once started.

MEASURED, 2026-08-31. Across every cycle log this repo has ever written there
are ZERO `chars, yt-dlp` transcript successes. Not "few" — zero. The reason was
not YouTube, not the network and not a quota:

    cmd = ["yt-dlp", ...]          # a bare name, resolved against PATH

The scheduled cycle is launched as `venv\Scripts\python.exe fast_cycle_runner.py`
WITHOUT activating the venv, so `venv/Scripts` is not on PATH, `yt-dlp` did not
resolve, and the resulting FileNotFoundError was caught by a handler that
returned None and printed nothing. A dead fallback that cannot say it is dead.

It stayed invisible because attempt 3 (Playwright) was carrying the feature. When
Playwright broke after the 2026-08-28 12:15 cycle, the whole chain went to
"fallback to description" — 325 of them on 29 Aug alone — and attempt 2, which
would have worked, had never been running.

Two call sites in TWO files had the bug, and in one of them the SAME FILE
already had it right eleven lines further down:
    youtube_intel._get_transcript_yt_dlp             bare  -> fixed
    internet_agent._get_transcript_ytdlp     (:681)  bare  -> fixed
    internet_agent._get_transcript_whisper   (:724)  correct all along
    media_intel_worker.download_audio        (:255)  correct all along

These tests build the command and never run it. No network, no subprocess.
"""
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import youtube_intel as Y  # noqa: E402


class _Recorder:
    """Stands in for subprocess.run: records argv, runs nothing."""

    def __init__(self):
        self.cmd = None

    def __call__(self, cmd, *a, **kw):
        self.cmd = list(cmd)
        raise subprocess.TimeoutExpired(cmd, 1)   # exit before any file work


def _capture(monkeypatch, module, fn_name):
    rec = _Recorder()
    monkeypatch.setattr(module.subprocess, "run", rec)
    getattr(module, fn_name)("dQw4w9WgXcQ")
    assert rec.cmd is not None, f"{fn_name} never built a command"
    return rec.cmd


# --------------------------------------------------------------------------- #
# The invariant: this interpreter, as a module. Never a bare name.
# --------------------------------------------------------------------------- #

def test_youtube_intel_invokes_yt_dlp_through_this_interpreter(monkeypatch):
    cmd = _capture(monkeypatch, Y, "_get_transcript_yt_dlp")

    assert cmd[0] == str(Path(sys.executable)), (
        f"argv[0] is {cmd[0]!r}, not the running interpreter. A bare name "
        f"resolves against PATH, and the scheduled cycle has no venv/Scripts "
        f"on PATH — which is why this fallback never ran once.")
    assert cmd[1:3] == ["-m", "yt_dlp"], (
        f"expected '-m yt_dlp' after the interpreter, got {cmd[1:3]!r}")


def test_internet_agent_invokes_yt_dlp_through_this_interpreter(monkeypatch):
    """The sibling copy of the same chain — it had the same defect."""
    ia = pytest.importorskip("agents.internet.internet_agent")
    monkeypatch.setattr(ia, "_is_ip_blocked", lambda: False, raising=False)
    cmd = _capture(monkeypatch, ia, "_get_transcript_ytdlp")

    assert cmd[0] == sys.executable, f"argv[0] is {cmd[0]!r}, not the interpreter"
    assert cmd[1:3] == ["-m", "yt_dlp"], f"got {cmd[1:3]!r}"


@pytest.mark.parametrize("rel,fn", [
    ("youtube_intel.py", "_get_transcript_yt_dlp"),
    ("agents/internet/internet_agent.py", "_get_transcript_ytdlp"),
])
def test_no_bare_yt_dlp_string_survives_in_the_call_path(rel, fn):
    """Guards the shape, not just today's behaviour: a future edit that types
    "yt-dlp" back into the argv list fails here even if nothing calls it yet."""
    src = (REPO / rel).read_text(encoding="utf-8")
    body = src.split(f"def {fn}(", 1)[1].split("\ndef ", 1)[0]
    for line in body.splitlines():
        code = line.split("#", 1)[0]
        assert '"yt-dlp"' not in code and "'yt-dlp'" not in code, (
            f"{rel}::{fn} passes a bare 'yt-dlp' argv entry again: {line.strip()}")


# --------------------------------------------------------------------------- #
# A fallback must be able to say why it failed
# --------------------------------------------------------------------------- #

def test_a_missing_yt_dlp_names_itself_instead_of_returning_silence(monkeypatch, capsys):
    """THE DEFECT THAT HID THE DEFECT. `except FileNotFoundError: return None`
    with no print is why three nights of empty transcripts named no cause."""
    def _boom(cmd, *a, **kw):
        raise FileNotFoundError(2, "The system cannot find the file specified")
    monkeypatch.setattr(Y.subprocess, "run", _boom)

    assert Y._get_transcript_yt_dlp("dQw4w9WgXcQ") is None
    out = capsys.readouterr().out
    assert "[TRANSCRIPT-YTDLP]" in out, "the failure printed nothing at all"
    assert "not runnable" in out, f"the reason is not named: {out!r}"


def test_an_ip_block_reaches_the_detector_instead_of_being_swallowed(monkeypatch, capsys):
    """The per-language loop caught IpBlocked one level BELOW the _YT_IP_BLOCKED
    detector, making the detector unreachable and its warning unprintable.

    A STUB MODULE, NOT THE REAL PACKAGE. The first version of this test did
    `import youtube_transcript_api` here and passed alone but failed in the full
    suite: an earlier test replaces `requests`, so importing the real package
    fresh dies with ImportError: cannot import name 'Session'. Nothing here
    needs the real client — _get_transcript_api imports the name INSIDE the
    function, so a stub in sys.modules is both sufficient and order-independent.
    """
    class IpBlocked(Exception):
        pass

    class _Api:
        def fetch(self, *a, **kw):
            raise IpBlocked("YouTube is blocking requests from your IP.")

    stub = types.ModuleType("youtube_transcript_api")
    stub.YouTubeTranscriptApi = _Api
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", stub)
    monkeypatch.setattr(Y, "_YT_IP_BLOCKED", False)

    assert Y._get_transcript_api("dQw4w9WgXcQ") is None
    assert Y._YT_IP_BLOCKED is True, (
        "the IP-block flag never latched — the detector is still unreachable "
        "and every remaining video will pay the same doomed round trip")
    assert "IP block detected" in capsys.readouterr().out

    monkeypatch.setattr(Y, "_YT_IP_BLOCKED", False)   # do not leak module state


def test_the_ip_block_helper_matches_by_type_not_only_by_message():
    """str(exc) can be empty — the 28 Aug logs printed '[TRANSCRIPT-API] <id>:'
    with nothing after the colon. Type is the reliable signal."""
    class IpBlocked(Exception):
        pass
    assert Y._is_ip_block_error(IpBlocked(""))
    assert Y._is_ip_block_error(RuntimeError("YouTube is blocking requests"))
    assert not Y._is_ip_block_error(ValueError("no transcript for language 'bg'"))
