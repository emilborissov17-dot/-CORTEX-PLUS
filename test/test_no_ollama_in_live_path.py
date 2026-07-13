"""Permanent guard: no Ollama calls in the live cycle path (item 7).

Ollama was removed from the LLM fallback chain on 2026-07-04 (see
core/groq_backend.py): there is not a single model pulled locally, so it was a
dead safety net that only masked AllBackendsFailedError. Per CLAUDE.md
convention, any remaining subprocess/HTTP Ollama call in the live cycle path is
a bug.

web_intelligence_agent still ran _warmup_ollama() at the top of every cycle. It
hit http://localhost:11434/api/tags, nothing was listening, and every cycle
opened with "Ollama warmup пропуснат: <connection refused>" — noise that masked
real startup errors. Removed.

This test stops it (and anything like it) coming back.

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

# Modules that run as part of a normal cycle.
LIVE_PATH_MODULES = [
    "web_intelligence_agent.py",
    "fast_cycle_runner.py",
    "core/groq_backend.py",
    "core/data_scout.py",
    "core/global_indicators.py",
    "agents/internet/internet_agent.py",
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


def test_web_intelligence_agent_has_no_warmup_function():
    """The specific regression: a warmup that failed on every single cycle."""
    import web_intelligence_agent as wia

    assert not hasattr(wia, "_warmup_ollama"), \
        "_warmup_ollama is back; it errors every cycle because nothing listens on 11434"


def test_groq_backend_chain_excludes_ollama():
    """Ollama must not be in the fallback chain either."""
    import inspect

    from core import groq_backend

    src = inspect.getsource(groq_backend.call_groq_meta)
    assert "_call_ollama" not in src, "Ollama is back in the LLM fallback chain"
