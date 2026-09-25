"""
core/llm_pacing.py — the pause between cloud calls, set by the cycle's body scan.

25 Sep 2026 (task #8 B.C). body_scan used to import core.groq_backend just to set
_SLEEP_SECS, and that import made the step reach the LLM stack. The directive now
lands here, in a module that imports nothing; the ladder's legs read it.
"""
from __future__ import annotations

SLEEP_SECS: float | None = None      # None -> the ladder's own default


def set_sleep(seconds: float) -> None:
    global SLEEP_SECS
    SLEEP_SECS = float(seconds)
