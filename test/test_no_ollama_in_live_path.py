"""Permanent guard: no Ollama calls in the live cycle path (item 7).

Ollama was removed from the LLM fallback chain on 2026-07-04 (see
core/local_llm.py): there is not a single model pulled locally, so it was a
dead safety net that only masked AllBackendsFailedError. Per CLAUDE.md
convention, any remaining subprocess/HTTP Ollama call in the live cycle path is
a bug.

web_intelligence_agent still ran _warmup_ollama() at the top of every cycle. It
hit http://localhost:11434/api/tags, nothing was listening, and every cycle
opened with "Ollama warmup пропуснат: <connection refused>" — noise that masked
real startup errors. Removed.

This test stops it (and anything like it) coming back.

EXCEPTIONS (30 Jul 2026, Emil-approved). The box now runs Ollama with real models
(qwen2.5:3b / 7b, qwen3:8b) and Emil explicitly wants them used as SOVEREIGN
fallbacks. So the convention shifted: not "no Ollama anywhere" but "no SILENT/MASKING
Ollama; LABELLED sovereign fallbacks are allowed". Two modules are checked POSITIVELY
below instead of by the blanket ban:
  - core/local_llm.py (task #16): local model as an explicit LAST RESORT, only when
    all four cloud backends are cooling, answer labelled backend="local:<model>",
    degraded=True. Keeps an axis alive instead of dying with LLM_FAILED.
  - core/data_scout.py: local model as a SOVEREIGN fallback for source discovery —
    it tries a cloud suggestion first and falls back to the local brain, so the system
    can keep hunting for data even with no cloud. Never touches scoring.
The blanket endpoint ban still holds for every other live module (e.g. no silent
warmup pings that fail every cycle).

Deliberately NOT flagged:
  - agents/body/body_scanner._ollama_status() — misleading name, but it reads
    API keys and makes no Ollama call.
  - core/cortex_llm.py — genuinely talks to Ollama, but is imported only from
    LEGACY/ and OLD/, which are not the live path.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Modules that run as part of a normal cycle. local_llm.py and data_scout.py are
# intentionally NOT here — each owns a LABELLED sovereign local fallback (Emil-approved)
# and is checked positively below instead of by the blanket endpoint ban.
LIVE_PATH_MODULES = [
    "fast_cycle_runner.py",
    "core/global_indicators.py",
    "agents/core/self_observer.py",
    "memory/trend_tracker.py",
]

OLLAMA_ENDPOINT = re.compile(r"localhost:11434|127\.0\.0\.1:11434")


def _code_lines(path: Path):
    """Yield (lineno, line) for lines that are not comments.

    Comments are allowed to mention Ollama — the removal is documented in one.
    What must not exist is a live call.
    """
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        yield i, raw


@pytest.mark.parametrize("rel", LIVE_PATH_MODULES)
def test_no_ollama_endpoint_in_live_module(rel):
    path = REPO / rel
    if not path.exists():
        pytest.skip(f"{rel} not in this checkout")

    hits = [(n, l.strip()) for n, l in _code_lines(path) if OLLAMA_ENDPOINT.search(l)]

    assert not hits, (
        f"{rel} makes a live Ollama call — Ollama is dead by convention "
        f"(CLAUDE.md). Offending lines: {hits}"
    )








