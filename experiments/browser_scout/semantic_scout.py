#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/browser_scout/semantic_scout.py — measure CONCEPTS, not just numbers.

The twin of autonomous_scout. For a conceptual axis (dignity, justice, democratic
health, authoritarian drift) there is no honest scalar, so the system reads several
sources and produces a STRUCTURED, EVIDENCE-GROUNDED, MULTI-PERSPECTIVE assessment,
tracked over time. It ASSESSES; it does not deliver a verdict on good/evil — the human
and the moral core supervise. (See claude/SEMANTIC_MEASUREMENT_DESIGN_30JUL.md.)

Two HARD guards, enforced in code (not left to the model's goodwill):
  1. GROUNDING: every evidence quote must appear VERBATIM in one of the fetched source
     texts. A claim whose quote can't be located is dropped, loudly. An assessment with
     zero grounded claims is rejected.
  2. MULTI-PERSPECTIVE: the strongest counterview is MANDATORY. No counterview -> rejected.

Sovereign + free: DuckDuckGo HTML + local Ollama (qwen3:8b preferred for nuance).

  python experiments/browser_scout/semantic_scout.py --axis GOVERNANCE_INSTITUTIONS_REVIEW \
      --concept "democratic health vs authoritarian drift"
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT_DIR = REPO / "memory" / "browse_sources"
LEDGER = REPO / "memory" / "semantic_trajectory.jsonl"

sys.path.insert(0, str(HERE))
from autonomous_scout import (  # reuse sovereign tools
    _local, _json_from, search_ddg, search_robust, _loosen, _page_text)

import os
_MODEL = os.environ.get("CORTEX_LOCAL_MODEL", "qwen2.5:3b")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _grounded(quote: str, corpus: str) -> bool:
    """A quote counts as grounded only if a substantial verbatim run of it appears in
    the fetched text. Guards against the model inventing a citation."""
    q = _norm(quote)
    if len(q) < 12:
        return False
    c = _norm(corpus)
    if q in c:
        return True
    # allow a long contiguous fragment (>=40 chars) to match, to tolerate light trimming
    for size in (60, 40):
        if len(q) >= size and q[:size] in c:
            return True
    return False


def assess(concept: str, sources: list) -> dict:
    """sources: list of (url, text). Returns the verified assessment or raises."""
    corpus = "\n\n".join(t for _, t in sources)
    snippets = "\n\n".join(f"[SOURCE {i+1}] {u}\n{t[:2500]}" for i, (u, t) in enumerate(sources))
    prompt = (
        f"You are assessing the CONCEPT: '{concept}'. This is contested and value-laden. "
        f"Do NOT deliver a verdict on good/evil; ASSESS with evidence and foreground the "
        f"disagreement. Read the sources and reply ONLY with JSON:\n"
        f'{{"assessment": "<a few sentences, grounded>", '
        f'"direction": "improving|stable|deteriorating", '
        f'"key_evidence": [{{"claim": "...", "source_url": "...", "quote": "<VERBATIM phrase '
        f'copied exactly from a source>"}}], '
        f'"strongest_counterview": "<the best opposing interpretation — required>", '
        f'"what_would_change_it": "...", "confidence": "low|medium|high", "contested": true}}\n\n'
        f"SOURCES:\n{snippets}")
    obj = _json_from(_local(prompt, num_predict=600))

    # GUARD 1: keep only evidence whose quote is verbatim-grounded in the fetched text
    kept = [e for e in (obj.get("key_evidence") or [])
            if isinstance(e, dict) and _grounded(e.get("quote", ""), corpus)]
    dropped = len(obj.get("key_evidence") or []) - len(kept)
    if not kept:
        raise ValueError("no evidence quote could be grounded in the sources — rejected")
    # GUARD 2: a real counterview is mandatory
    cv = (obj.get("strongest_counterview") or "").strip()
    if len(cv) < 20:
        raise ValueError("no substantive counterview — rejected (contested concepts need it)")

    return {
        "concept": concept,
        "assessment": obj.get("assessment", ""),
        "direction": obj.get("direction"),
        "key_evidence": kept,
        "evidence_dropped_ungrounded": dropped,
        "strongest_counterview": cv,
        "what_would_change_it": obj.get("what_would_change_it"),
        "confidence": obj.get("confidence"),
        "contested": bool(obj.get("contested", True)),
        "note": "assessment, not verdict; human + moral-core supervised",
        "assessed_at": _now_iso(),
        "assessed_by": f"semantic_scout ({_MODEL})",
    }


def research(axis: str, concept: str, n_sources: int = 3) -> dict:
    def _replan():
        p = (f"To assess the concept '{concept}', give ONE web search query — plain "
             f"keywords, NO quotes — likely to find recent reporting/analysis with "
             f"concrete facts. Reply with ONLY the query text.")
        return _loosen(_local(p, num_predict=40).splitlines()[0])

    results, _used = search_robust(concept, n=n_sources + 2, replan_fn=_replan)
    sources, seen = [], []
    for url, _t in results:
        try:
            sources.append((url, _page_text(url)))
            seen.append(url)
        except Exception:
            continue
        if len(sources) >= n_sources:
            break
    if not sources:
        return {"axis": axis, "concept": concept, "error": "no readable sources"}
    rec = assess(concept, sources)
    rec["axis"] = axis
    rec["sources_read"] = seen
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^a-z0-9]+", "_", axis.lower())[:40]
    (OUT_DIR / f"semantic_{key}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    # trajectory: append the compact reading so the concept can be tracked over time
    try:
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": rec["assessed_at"], "axis": axis, "concept": concept,
                                "direction": rec["direction"], "confidence": rec["confidence"],
                                "n_evidence": len(rec["key_evidence"])}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


if __name__ == "__main__":
    a = {}
    for i, tok in enumerate(sys.argv):
        if tok == "--axis": a["axis"] = sys.argv[i + 1]
        if tok == "--concept": a["concept"] = sys.argv[i + 1]
    print(json.dumps(research(a.get("axis", "GOVERNANCE_INSTITUTIONS_REVIEW"),
                              a.get("concept", "democratic health vs authoritarian drift")),
                     ensure_ascii=False, indent=2))
