"""A truncated LLM answer must not be published as "nothing urgent".

WHAT WENT WRONG (measured, cycle 2026-08-28T08:05:00)
------------------------------------------------------
Gemini returned finish_reason=length on 14 of 19 answers in the
internet_intelligence step. The chain of consequences was:

  1. agents/internet/internet_agent._llm_synthesize called
     core.groq_backend.call_groq, which DISCARDS the meta dict and with it
     finish_reason. The parser therefore never learned the provider had cut
     the answer; it saw a broken string and guessed "garbage".
  2. The except-clause returned urgency='LOW', sentiment='NEUTRAL' and
     summary=ctx[:200] — the raw SOURCE TEXT that had been fed IN, republished
     as the analysis that came OUT.
  3. fetch_axis rebuilt the result dict from a fixed key list that did not
     copy 'error', so news/news_latest.json carried no marker of any kind.
  4. Three readers gate on urgency in ("HIGH","CRITICAL") — cortex_core_agent,
     cortex_orchestrator, semantic_memory — and skipped all fourteen.

The observable result on disk that day: 18 of 24 axes LOW, 14 of them these.
Not a false alarm. A false ALL-CLEAR, which is the more expensive direction.

WHAT THIS SUITE HOLDS
---------------------
That a truncation produces urgency=UNKNOWN with truncated=True, a non-empty
error, and a summary that is NOT the input; that the marker survives the
rebuild in fetch_axis; that the aggregate counts UNKNOWN apart from LOW; and
that the three readers surface it rather than folding it into LOW or promoting
it to HIGH.

LIVE STATE IS NOT TOUCHED. The last test asserts news/news_latest.json is
byte-identical after the whole module has run.
"""
import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agents.internet import internet_agent as ia          # noqa: E402
from core.llm_json import TruncatedJSONError              # noqa: E402

NEWS_LATEST = REPO / "news" / "news_latest.json"


def _digest(p: pathlib.Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


# Captured before anything in this module imports or runs further.
_NEWS_BEFORE = _digest(NEWS_LATEST)


# The context a real axis fetch builds and hands to the model. If any assertion
# below finds THIS string inside a published summary, the defect is back.
CTX_MARKER = "[GitHub]\n- satellite-image-deep-learning/techniques star=10243"

SOURCES = {
    "github": [{"title": "satellite-image-deep-learning/techniques",
                "stars": 10243, "snippet": "Techniques for deep learning"}],
}


@pytest.fixture
def truncating_llm(monkeypatch):
    """call_llm_json raises TruncatedJSONError, as it does after its own retry."""
    def _boom(prompt, **kw):
        raise TruncatedJSONError(
            '{"summary": "Rapid ice-sheet break-off in Green',
            "unclosed object", backend="Gemini")
    monkeypatch.setattr(ia, "call_llm_json", _boom)
    return _boom


@pytest.fixture
def garbage_llm(monkeypatch):
    """Not truncated — the model answered, in prose. Also not an assessment."""
    from core.llm_json import LLMJSONError

    def _boom(prompt, **kw):
        raise LLMJSONError("I cannot help with that.", "no json", backend="Groq")
    monkeypatch.setattr(ia, "call_llm_json", _boom)
    return _boom


# ── the record _llm_synthesize produces ────────────────────────────────────

def test_a_truncated_answer_is_unknown_not_low(truncating_llm):
    a = ia._llm_synthesize("PLANETARY_POTENTIAL_REVIEW", SOURCES)
    assert a["urgency"] == "UNKNOWN", "LOW is a judgement; none was made"
    assert a["urgency"] != "LOW"


def test_a_truncated_answer_is_marked_truncated(truncating_llm):
    a = ia._llm_synthesize("PLANETARY_POTENTIAL_REVIEW", SOURCES)
    assert a["truncated"] is True


def test_a_truncated_answer_carries_a_non_empty_error(truncating_llm):
    a = ia._llm_synthesize("PLANETARY_POTENTIAL_REVIEW", SOURCES)
    assert a.get("error"), "a failure with no error string is unattributable"
    assert "Gemini" in a["error"], "the backend must be named"


def test_the_summary_is_not_the_input(truncating_llm):
    """The defect itself: the source text republished as the analysis."""
    a = ia._llm_synthesize("PLANETARY_POTENTIAL_REVIEW", SOURCES)
    assert a["summary"] == "", "an empty summary, not a fabricated one"
    assert CTX_MARKER not in a["summary"]
    assert a.get("summary_why"), "empty must say why it is empty"


def test_unparseable_prose_is_also_unknown_but_not_truncated(garbage_llm):
    a = ia._llm_synthesize("WATER_REVIEW", SOURCES)
    assert a["urgency"] == "UNKNOWN"
    assert a["truncated"] is False
    assert a.get("error")


# ── the marker must survive the rebuild in fetch_axis ──────────────────────

def test_the_marker_survives_the_result_rebuild(truncating_llm):
    analysis = ia._llm_synthesize("WATER_REVIEW", SOURCES)
    # The rebuild is a fixed key list; assert the keys it must now carry.
    rebuilt = {
        "urgency": analysis.get("urgency", "UNKNOWN"),
        "truncated": bool(analysis.get("truncated", False)),
        "error": analysis.get("error"),
        "summary": analysis.get("summary", ""),
    }
    assert rebuilt["urgency"] == "UNKNOWN"
    assert rebuilt["truncated"] is True
    assert rebuilt["error"]
    src = (REPO / "agents" / "internet" / "internet_agent.py").read_text(
        encoding="utf-8")
    for key in ("'truncated':", "'error':", "'summary_why':"):
        assert key in src, f"{key} must be in the fetch_axis rebuild"


def test_missing_urgency_defaults_to_unknown_not_low():
    """A model that answered but omitted urgency assessed nothing either."""
    src = (REPO / "agents" / "internet" / "internet_agent.py").read_text(
        encoding="utf-8")
    assert "analysis.get('urgency', 'UNKNOWN')" in src
    assert "analysis.get('urgency', 'LOW')" not in src


# ── the aggregate counts UNKNOWN apart from LOW ────────────────────────────

def test_run_publishes_unknown_axes_separately():
    src = (REPO / "agents" / "internet" / "internet_agent.py").read_text(
        encoding="utf-8")
    assert "'unknown_axes': unknown" in src, "the report must publish the list"
    assert "unknown.append(axis)" in src, "UNKNOWN must be counted apart"
    assert "NOT ASSESSED" in src, "and printed where a human reads the run"


# ── the three readers ──────────────────────────────────────────────────────

def test_core_agent_surfaces_unknown(tmp_path, monkeypatch):
    import agents.core.cortex_core_agent as cca
    news = {
        "date": "2026-08-28",
        "critical_axes": [], "high_urgency_axes": [],
        "unknown_axes": ["WATER_REVIEW", "PLANETARY_POTENTIAL_REVIEW"],
        "results": {
            "WATER_REVIEW": {"urgency": "UNKNOWN", "summary": "", "truncated": True},
            "PLANETARY_POTENTIAL_REVIEW": {"urgency": "UNKNOWN", "summary": ""},
            "FOOD_REVIEW": {"urgency": "LOW", "summary": "calm"},
        },
    }
    p = tmp_path / "news_latest.json"
    p.write_text(json.dumps(news), encoding="utf-8")
    monkeypatch.setattr(cca, "NEWS_PATH", p)
    out = cca._load_news_context()
    assert "NOT ASSESSED" in out
    assert "WATER_REVIEW" in out
    assert "not an all-clear" in out
    # never promoted
    assert "CRITICAL ALERTS" not in out
    assert "HIGH URGENCY" not in out


def test_semantic_memory_does_not_remember_unknown_but_names_it(tmp_path, monkeypatch, capsys):
    import memory.semantic_memory as sm
    news = {"results": {
        "WATER_REVIEW": {"urgency": "UNKNOWN", "summary": ""},
        "FOOD_REVIEW":  {"urgency": "HIGH",    "summary": "real finding"},
    }}
    p = tmp_path / "news_latest.json"
    p.write_text(json.dumps(news), encoding="utf-8")
    monkeypatch.setattr(sm, "BASE_DIR", tmp_path.parent)
    remembered = []
    monkeypatch.setattr(sm, "remember",
                        lambda text, **kw: remembered.append(text))
    (tmp_path.parent / "news").mkdir(exist_ok=True)
    (tmp_path.parent / "news" / "news_latest.json").write_text(
        json.dumps(news), encoding="utf-8")
    n = sm.remember_from_news()
    assert n == 1, "only the HIGH axis is remembered"
    assert all("WATER_REVIEW" not in t for t in remembered)
    assert "NOT ASSESSED" in capsys.readouterr().out


def test_orchestrator_prints_unknown():
    src = (REPO / "core" / "cortex_orchestrator.py").read_text(encoding="utf-8")
    assert 'internet.get("unknown_axes", [])' in src
    assert "NOT ASSESSED" in src


# ── live state ─────────────────────────────────────────────────────────────

def test_the_real_news_file_was_not_touched():
    assert _digest(NEWS_LATEST) == _NEWS_BEFORE, (
        "news/news_latest.json changed while this suite ran — a test that "
        "writes live state is not a test, it is a cycle")
