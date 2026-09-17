#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/browser_scout/shadow_test_semantic.py — MEASURE THE EYE BEFORE MOUNTING IT.

Kimi, 15 August 2026, condition 1 of 3 for wiring semantic_scout into the cycle:
  "Shadow test преди закачане. Пусни 3 оси ръчно през semantic_scout с brain.think.
   Измери success rate на guard 1. Ако е под 60%, не закачай нищо — първо оправи
   verbatim цитирането (prompt или chunking)."
And the warning that made this script necessary:
  "Ако ги пропуснеш, рискуваш да построиш най-елегантната фасада, която сме виждали
   днес — семантична колона, пълна с rejected_assessment, която изглежда като «мерим
   смисъл», а всъщност мери способността на LLM-а да премине guard."

WHAT THIS DOES — and, more importantly, what it does NOT do.

It runs the real thing: a real web search, real page fetches, a real model call, and
the real guard from semantic_scout (`_grounded`: a claim's quote must appear VERBATIM
in the fetched text). It then counts what survived.

It does NOT modify semantic_scout, does NOT touch the cycle, does NOT write into any
file the cycle reads, and does NOT enter the composite. Its only output is a scratch
report. The whole point is to learn whether the eye can see BEFORE anyone depends on
it — the opposite of what happened to semantic_scout and goal_prophecy, which were
built, believed, and never once measured.

Two transports are compared on the SAME fetched corpus, because the question is not
"does a model answer" but "which one can be held to the evidence":
  * local   — the Ollama path semantic_scout uses today (qwen2.5:3b by default)
  * brain   — core.brain.think(), the same brain the rest of the cycle uses

Reading the result:
  grounded_rate  = grounded claims / claims the model returned.
                   This is guard 1's success rate. Kimi's gate: >= 0.60.
  usable         = the assessment survived BOTH guards (>=1 grounded claim AND a
                   substantive counterview). An axis that fails here produces nothing.
  A high claim count with a low grounded_rate is the dangerous case: the model is
  fluent and unanchored. A low claim count with a high rate is fine — few, but honest.

  venv\\Scripts\\python.exe experiments\\browser_scout\\shadow_test_semantic.py
  venv\\Scripts\\python.exe experiments\\browser_scout\\shadow_test_semantic.py --only brain
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

OUT = REPO / "memory" / "semantic_shadow_test.json"

# Three blind axes, chosen by weight and by closeness to what the VISION is about:
# existential risk, technology/AI, and culture — the last one is the nearest thing
# the current config has to "dignity". Concepts are phrased as CONTESTED questions,
# because an uncontested concept needs no counterview and would flatter the guard.
CASES = [
    {"axis": "LONG_TERM_FUTURE_REVIEW", "weight": 7,
     "concept": "existential risk to humanity from nuclear weapons and AI in 2026"},
    {"axis": "TECHNOLOGY_AI_REVIEW", "weight": 6,
     "concept": "whether AI development in 2026 concentrates power or distributes it"},
    {"axis": "CULTURE_MEDIA_REVIEW", "weight": 5,
     "concept": "press freedom and media independence worldwide in 2026"},
]

GATE = 0.60          # Kimi's threshold for guard 1. Below this, wire nothing.
N_SOURCES = 3


def _now():
    return datetime.now(timezone.utc).isoformat()


def _prompt(concept: str, snippets: str) -> str:
    """The prompt semantic_scout already uses, kept verbatim so the test measures the
    REAL module and not a friendlier variant of it."""
    return (
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


def _fetch(concept: str) -> list:
    """Real search + real pages. No replan_fn: the replanner needs a model, and this
    stage must be identical for both transports, otherwise the comparison is rigged."""
    from autonomous_scout import search_robust, _page_text      # noqa: PLC0415
    results, _used = search_robust(concept, n=N_SOURCES + 2, replan_fn=None)
    sources = []
    for url, _t in results:
        try:
            txt = _page_text(url)
        except Exception:
            continue
        if txt and len(txt) > 400:
            sources.append((url, txt))
        if len(sources) >= N_SOURCES:
            break
    return sources


def _ask_local(concept: str, snippets: str) -> tuple:
    from autonomous_scout import _local, _json_from             # noqa: PLC0415
    raw = _local(_prompt(concept, snippets), num_predict=600)
    return _json_from(raw), "local"


def _ask_brain(concept: str, snippets: str) -> tuple:
    from core import brain                                      # noqa: PLC0415
    # NOTE, and do not "tidy" this: the sources go into `question`, not `evidence`.
    # brain.think truncates evidence with str(evidence)[-5000:], and three pages at
    # 2500 chars each is 7500 — the first source would be silently cut off and the
    # comparison would be rigged against this transport without anyone noticing.
    # A test that quietly handicaps one side is worse than no test.
    d = brain.think(
        role="assessor of a contested concept",
        question=_prompt(concept, snippets),
        evidence="",                     # sources are already inside the prompt
        schema={
            "assessment": "a few sentences, grounded in the sources",
            "direction": "improving | stable | deteriorating",
            "key_evidence": "list of {claim, source_url, quote}; quote copied EXACTLY "
                            "from one of the sources, word for word",
            "strongest_counterview": "the best opposing interpretation — required",
            "what_would_change_it": "what observation would change this reading",
            "confidence": "low | medium | high",
            "contested": "true/false",
        },
        kind="semantic_shadow", remember_it=False, temperature=0.1)
    if not d:
        raise RuntimeError("brain returned nothing (no provider answered, or the "
                           "reply was not valid JSON)")
    return {k: v for k, v in d.items() if not str(k).startswith("_")}, str(d.get("_model", "?"))


def _measure(obj: dict, corpus: str) -> dict:
    """Apply semantic_scout's OWN guards. Imported, not reimplemented — a copy would
    drift from the module and the test would stop measuring the real thing."""
    from semantic_scout import _grounded                        # noqa: PLC0415
    claims = obj.get("key_evidence") or []
    if not isinstance(claims, list):
        claims = []
    kept, dropped_examples = 0, []
    for e in claims:
        if isinstance(e, dict) and _grounded(e.get("quote", ""), corpus):
            kept += 1
        elif isinstance(e, dict):
            if len(dropped_examples) < 2:
                dropped_examples.append(str(e.get("quote", ""))[:120])
    cv = str(obj.get("strongest_counterview") or "").strip()
    n = len(claims)
    return {
        "claims_returned": n,
        "claims_grounded": kept,
        "grounded_rate": (round(kept / n, 3) if n else None),
        "counterview_ok": len(cv) >= 20,
        "counterview_len": len(cv),
        "direction": obj.get("direction"),
        "confidence": obj.get("confidence"),
        # BOTH guards, exactly as semantic_scout.assess() applies them
        "usable": bool(kept) and len(cv) >= 20,
        "ungrounded_examples": dropped_examples,
    }


def run(which: tuple = ("local", "brain")) -> dict:
    report = {"ts": _now(), "gate": GATE, "n_sources": N_SOURCES, "cases": []}
    for case in CASES:
        row = {**case, "sources": [], "by_transport": {}}
        print(f"\n=== {case['axis']} (weight {case['weight']}) ===")
        print(f"    concept: {case['concept']}")
        try:
            sources = _fetch(case["concept"])
        except Exception as e:
            row["fetch_error"] = f"{type(e).__name__}: {e}"
            print(f"    FETCH FAILED: {row['fetch_error']}")
            report["cases"].append(row)
            continue
        if not sources:
            row["fetch_error"] = "no readable sources"
            print("    FETCH FAILED: no readable sources — the eye is blind for a "
                  "reason that has nothing to do with the model")
            report["cases"].append(row)
            continue

        row["sources"] = [u for u, _ in sources]
        corpus = "\n\n".join(t for _, t in sources)
        snippets = "\n\n".join(f"[SOURCE {i+1}] {u}\n{t[:2500]}"
                               for i, (u, t) in enumerate(sources))
        print(f"    fetched {len(sources)} page(s), {len(corpus)} chars")

        for name, fn in (("local", _ask_local), ("brain", _ask_brain)):
            if name not in which:
                continue
            try:
                obj, model = fn(case["concept"], snippets)
                m = _measure(obj, corpus)
                m["model"] = model
                row["by_transport"][name] = m
                rate = m["grounded_rate"]
                print(f"    {name:6s} [{model}] claims={m['claims_returned']} "
                      f"grounded={m['claims_grounded']} "
                      f"rate={'n/a' if rate is None else f'{rate:.0%}'} "
                      f"counterview={'yes' if m['counterview_ok'] else 'NO'} "
                      f"-> {'USABLE' if m['usable'] else 'REJECTED'}")
                for q in m["ungrounded_examples"]:
                    print(f"           ungrounded quote: {q!r}")
            except Exception as e:
                row["by_transport"][name] = {"error": f"{type(e).__name__}: {e}",
                                             "trace": traceback.format_exc()[-400:]}
                print(f"    {name:6s} FAILED: {type(e).__name__}: {e}")
        report["cases"].append(row)

    # ── the verdict, stated the way Kimi framed the gate ─────────────────────
    summary = {}
    for name in which:
        rows = [c["by_transport"].get(name) or {} for c in report["cases"]]
        ok = [r for r in rows if "error" not in r and r.get("grounded_rate") is not None]
        total_claims = sum(r["claims_returned"] for r in ok)
        total_kept = sum(r["claims_grounded"] for r in ok)
        summary[name] = {
            "axes_attempted": len(rows),
            "axes_answered": len(ok),
            "axes_usable": sum(1 for r in ok if r.get("usable")),
            "claims_returned": total_claims,
            "claims_grounded": total_kept,
            "grounded_rate": (round(total_kept / total_claims, 3) if total_claims else None),
        }
    report["summary"] = summary

    print("\n" + "=" * 74)
    for name, s in summary.items():
        rate = s["grounded_rate"]
        verdict = ("NO DATA" if rate is None else
                   "PASS — wiring is allowed" if rate >= GATE else
                   f"FAIL — below the {GATE:.0%} gate; fix the citing before wiring")
        print(f"{name:6s} answered {s['axes_answered']}/{s['axes_attempted']} axes | "
              f"usable {s['axes_usable']} | claims {s['claims_grounded']}/{s['claims_returned']} "
              f"grounded ({'n/a' if rate is None else f'{rate:.0%}'}) -> {verdict}")
    print("=" * 74)
    print("Read it this way: many claims with a low rate is the dangerous case — the "
          "model is fluent and unanchored. Few claims with a high rate is fine.")
    print("If it FAILS, the cure is not a better prompt but mechanical quoting: split "
          "the page into sentences, send the model only chunks, let it CHOOSE one. "
          "Then the quote cannot be invented, because the model never writes it.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport -> {OUT}")
    return report


if __name__ == "__main__":
    which = ("local", "brain")
    if "--only" in sys.argv:
        which = (sys.argv[sys.argv.index("--only") + 1],)
    run(which)
