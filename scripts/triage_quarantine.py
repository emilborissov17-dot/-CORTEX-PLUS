#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/triage_quarantine.py
Reads every quarantined self-modifier patch and asks the question nobody was asking:
WAS THIS WORTH ANYTHING?

WHY THIS EXISTS
---------------
The self-improvement pipeline was generate -> guard -> execute -> fail -> roll back ->
quarantine -> sit forever. On 2026-08-04 seventeen patches were sitting there and
nothing had ever read one of them again. scripts/review_quarantine.py is the human's
window, and its own docstring says it is not part of any automated path — so a rejected
patch was indistinguishable from a deleted one, and the intent behind it was lost along
with the broken code that carried it.

A patch can be rejected for two very different reasons:
  * the IDEA was worthless — correctly binned, nothing to recover;
  * the idea was sound and the CODE was wrong — a KeyError, a missing guard, a wrong
    dict shape. That is a draft, not garbage.

Nothing distinguished those two, so both were treated as garbage. This ranks them, and
the ranking feeds the human CLI that already exists. This tool DOES NOT APPLY ANYTHING.

WHAT IS FACT AND WHAT IS OPINION
--------------------------------
Deterministic, computed here, never asked of a model:
  - whether the patch targets a protected/constitution path (safety.protected_paths)
  - whether the source even parses (ast.parse)
  - the recorded failure stage and diagnosis from the guardian's sidecar
The usefulness judgement is a MODEL OPINION and is labelled `opinion` in the output.
It ranks a queue for a human; it does not decide anything.

THE OVERSIGHT BOUNDARY (see BOUNDARIES.md, safety/protected_paths.py)
---------------------------------------------------------------------
Any patch whose target is protected is forced to verdict HUMAN_ONLY before a model is
consulted, and the model's opinion cannot override it. The system may rank its own
rejected drafts; it may not promote them, and it may not rank its way around the canon.

    venv/Scripts/python.exe scripts/triage_quarantine.py --selftest
    venv/Scripts/python.exe scripts/triage_quarantine.py            # triage all
    venv/Scripts/python.exe scripts/triage_quarantine.py --limit 5
    venv/Scripts/python.exe scripts/triage_quarantine.py --offline  # no LLM, facts only
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("CORTEX_BASE", str(BASE_DIR))

QUARANTINE_DIR = BASE_DIR / "patches" / "quarantine"
OUT_PATH = BASE_DIR / "memory" / "quarantine_triage.json"

MAX_SOURCE_CHARS = 6000        # what the judge is shown of a patch
MAX_DIAGNOSIS_CHARS = 800


# ── integrations, checked rather than assumed ────────────────────────────────

def _integrations() -> dict:
    """Which of this module's dependencies are LIVE in the repo it finds itself in."""
    status = {}
    try:
        from safety.protected_paths import protection_reason  # noqa: F401
        status["safety.protected_paths"] = "LIVE"
    except Exception as e:
        status["safety.protected_paths"] = f"INERT ({type(e).__name__})"
    try:
        from core.llm_json import call_llm_json  # noqa: F401
        status["core.llm_json"] = "LIVE"
    except Exception as e:
        status["core.llm_json"] = f"INERT ({type(e).__name__})"
    status["patches/quarantine"] = (
        f"LIVE ({len(list(QUARANTINE_DIR.glob('*.py')))} patches)"
        if QUARANTINE_DIR.is_dir() else "INERT (directory missing)")
    status["scripts/review_quarantine.py"] = (
        "LIVE" if (BASE_DIR / "scripts" / "review_quarantine.py").is_file()
        else "INERT (the human CLI this feeds is missing)")
    return status


# ── the deterministic half ───────────────────────────────────────────────────

def _protection(target: str | None) -> str | None:
    if not target:
        return None
    try:
        from safety.protected_paths import protection_reason
    except Exception:
        return None
    try:
        return protection_reason(target)
    except Exception:
        return None


def _parses(source: str) -> tuple[bool, str | None]:
    """Static check only. A quarantined patch is untrusted code and is NEVER executed."""
    try:
        ast.parse(source)
        return True, None
    except SyntaxError as e:
        return False, f"SyntaxError line {e.lineno}: {e.msg}"


def _defined_names(source: str) -> set:
    out = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
    return out


_ARTIFACT_SUFFIXES = (".json", ".jsonl", ".txt", ".csv", ".md")


def _referenced_artifacts_and_modules(source: str) -> tuple[list, list]:
    """String literals in the patch that name a FILE it writes or a MODULE it points at."""
    artifacts, modules = [], []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return artifacts, modules
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        s = node.value.strip()
        if not s or len(s) > 120 or " " in s:
            continue
        if s.endswith(_ARTIFACT_SUFFIXES):
            # A glob pattern ("*.json") or a bare extension (".json") is not a file. Both
            # slipped through and, being common substrings, always found a "reader" —
            # which made wires_into_nothing false for patches whose every REAL artifact
            # was an orphan. general_patch.1784940113 survived as REWRITE on exactly that
            # accounting error: its "*.json" counted as wired, its _mitigation.json and
            # existential_risk_log.json did not, and the ratio said "partly wired".
            name = Path(s).name
            if any(ch in s for ch in "*?[]") or name.startswith("."):
                continue
            artifacts.append(s)
        elif "/" not in s and "\\" not in s and "." in s and s.count(".") >= 2 \
                and all(part.isidentifier() for part in s.split(".")):
            modules.append(s)
    return sorted(set(artifacts)), sorted(set(modules))


def _wiring(source: str, self_name: str) -> dict:
    """Is anything in this repo actually going to LOAD what the patch produces?

    CLAUDE.md, in this repo, states the rule the triage kept breaking: "grep for the
    loader — if nothing imports or reads it, you are about to create dead weight." The
    model judge could not apply it, because it was shown the patch and nothing else. It
    scored general_patch.1785353275 at 4/5 for "add a WATER_REVIEW agent to the
    registry"; that patch writes agents/registry.json, which NO file in this repo reads,
    and registers agents.water.water_review_agent, which does not exist. Written
    perfectly, it would still be dead weight.

    So the wiring is checked here, in code, against the actual tree — and the judge is
    told the answer instead of being asked to guess it."""
    artifacts, modules = _referenced_artifacts_and_modules(source)
    # `"venv" not in p.parts` missed venv312_metta, so site-packages counted as a
    # "reader" and registry.json looked wired when nothing in this repo touches it.
    # Any directory whose name STARTS with venv is a vendored tree, not our code.
    # Two kinds of file MENTION an artifact without ever loading it, and both fooled
    # this scan:
    #   - this module, whose comment naming "agents/registry.json" as the example of an
    #     orphan made the scanner find a "reader" for it — the tool answering its own
    #     question with its own prose;
    #   - the tests, which name an artifact precisely in order to assert something about
    #     it. A test is a check, not a loader; if the only file referring to an artifact
    #     is a test, nothing in the live system reads it, which is exactly the finding.
    _self = Path(__file__).resolve()

    def _ours(p: Path) -> bool:
        if p.resolve() == _self:
            return False
        return not any(part.startswith("venv") or part in
                       {"quarantine", "OLD", "LEGACY", "__pycache__", ".git",
                        "node_modules", "test", "tests"}
                       for part in p.parts)

    py_files = [p for p in BASE_DIR.rglob("*.py") if _ours(p)]

    orphan_artifacts = []
    for art in artifacts:
        base = Path(art).name
        readers = 0
        for p in py_files:
            if p.name == self_name:
                continue
            try:
                if base in p.read_text(encoding="utf-8", errors="replace"):
                    readers += 1
                    break
            except OSError:
                continue
        if readers == 0:
            orphan_artifacts.append(art)

    missing_modules = []
    for mod in modules:
        rel = Path(*mod.split("."))
        if not (BASE_DIR / rel).with_suffix(".py").is_file() \
                and not (BASE_DIR / rel).is_dir():
            missing_modules.append(mod)

    return {
        "artifacts": artifacts,
        "orphan_artifacts": orphan_artifacts,
        "modules": modules,
        "missing_modules": missing_modules,
        "wires_into_nothing": bool(artifacts) and len(orphan_artifacts) == len(artifacts),
    }


def _load_sidecar(py_path: Path) -> dict:
    side = py_path.with_suffix(py_path.suffix + ".json")
    if not side.is_file():
        return {}
    try:
        return json.loads(side.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _facts(py_path: Path) -> dict:
    source = py_path.read_text(encoding="utf-8", errors="replace")
    side = _load_sidecar(py_path)
    verdict = side.get("verdict") or {}
    target = side.get("original_filename") or verdict.get("file")
    parses, syntax_error = _parses(source)
    diagnosis = (side.get("deny_reason") or verdict.get("error") or "").strip()
    return {
        "patch": py_path.name,
        "target": target,
        "quarantined_at": side.get("timestamp"),
        "stage": verdict.get("stage"),
        "diagnosis": diagnosis[:MAX_DIAGNOSIS_CHARS],
        "diagnosis_truncated_by_old_guardian": (
            bool(diagnosis) and len(diagnosis) >= 295 and "[...]" not in diagnosis),
        "parses": parses,
        "syntax_error": syntax_error,
        "defines": sorted(_defined_names(source))[:20],
        "lines": source.count("\n") + 1,
        "protected": _protection(target),
        "wiring": _wiring(source, py_path.name),
        "source": source,
    }


# ── the opinion half ─────────────────────────────────────────────────────────

JUDGE_PROMPT = """You are reviewing a REJECTED self-modification patch from an AGI \
research system called CORTEX++. The patch was generated by a model, failed when the \
guardian ran it, and was rolled back and quarantined.

Your job is NOT to decide whether the code is correct — it demonstrably is not. Your job \
is to decide whether the INTENT behind it was worth anything, and whether a correct \
implementation would be useful to the system.

The system's purpose: a transparent, human-controlled AGI whose current mission is \
detecting the gap between official claims and observed reality across 25 "axes" of \
civilisation (climate, food, governance, energy, ...). It scores axes from real data \
series and flags where a claim and the measurement disagree.

TARGET FILE: {target}
RECORDED FAILURE ({stage}): {diagnosis}

WIRING, checked against the real repository (these are FACTS, not guesses — trust them
over what the code appears to promise):
{wiring}
A patch whose output files are read by NOTHING is dead weight even when written
perfectly. Score it accordingly: intent alone is not usefulness.

SOURCE (truncated):
```python
{source}
```

Reply ONLY with JSON:
{{"intent": "<one sentence: what was this patch trying to achieve>",
  "useful_if_correct": <0-5 integer: how much would a CORRECT version help the system's \
mission? 0=worthless or duplicates existing work, 5=clearly valuable>,
  "defect_class": "<one of: logic_bug, wrong_data_shape, missing_guard, fabricated_data, \
placeholder_stub, wrong_target, unclear>",
  "trivially_fixable": <true|false: would a competent engineer fix this in under 20 lines>,
  "fabricates_data": <true|false: does it invent numbers/facts rather than read real \
sources? this system treats invented data as a serious fault>,
  "recommendation": "<one of: rewrite, discard, needs_human>",
  "rationale": "<two sentences max>"}}"""


def _wiring_brief(w: dict) -> str:
    bits = []
    if w.get("orphan_artifacts"):
        bits.append(f"  - writes {w['orphan_artifacts']} — NO file in this repo reads them")
    elif w.get("artifacts"):
        bits.append(f"  - writes {w['artifacts']} — at least one reader exists")
    if w.get("missing_modules"):
        bits.append(f"  - references modules that DO NOT EXIST: {w['missing_modules']}")
    if w.get("wires_into_nothing"):
        bits.append("  - VERDICT OF FACT: every artifact it produces is orphaned")
    return "\n".join(bits) or "  - no file artifacts or module references detected"


def _judge(facts: dict) -> dict:
    from core.llm_json import call_llm_json
    prompt = JUDGE_PROMPT.format(
        target=facts.get("target") or "(unknown)",
        stage=facts.get("stage") or "(unknown)",
        diagnosis=facts.get("diagnosis") or "(nothing recorded — the pre-2026-08-04 "
                                           "guardian truncated the cause away)",
        wiring=_wiring_brief(facts.get("wiring") or {}),
        source=facts["source"][:MAX_SOURCE_CHARS],
    )
    return call_llm_json(prompt, max_tokens=700, expect=dict, label="quarantine_triage")


# ── orchestration ────────────────────────────────────────────────────────────

def _apply_policy(opinion: dict, wiring: dict | None = None) -> tuple[str, str, dict]:
    """House rules that outrank the judge's opinion.

    THE FIRST RUN CAME BACK 17 REWRITE OUT OF 17, scores clustered at 3-4, not one
    discard. A reviewer that approves everything has ranked nothing — the same rubber
    stamp the moral gate's 3B judge was caught giving. Worse, the top-scored patch was
    flagged `fabricates_data: true` and still got 4/5 and REWRITE.

    That one is not a matter of taste. This system exists to expose the gap between what
    is claimed and what is measured; a patch that invents its numbers instead of reading
    a source IS that gap, committed by the system against itself. It cannot be graded as
    a promising draft. So it is capped and routed to a human here, in code, where the
    rule is visible and testable — not left to a model that may be feeling generous.

    The raw opinion is preserved untouched alongside, so a policy override is always
    auditable against what the judge actually said."""
    verdict = str(opinion.get("recommendation", "unclear")).upper()
    reason = str(opinion.get("rationale", ""))[:300]
    applied = dict(opinion)

    score = opinion.get("useful_if_correct")
    score = score if isinstance(score, (int, float)) else 0

    wiring = wiring or {}
    if wiring.get("wires_into_nothing") or wiring.get("missing_modules"):
        applied["useful_if_correct"] = min(score, 1)
        detail = []
        if wiring.get("orphan_artifacts"):
            detail.append(f"orphan artifacts {wiring['orphan_artifacts']}")
        if wiring.get("missing_modules"):
            detail.append(f"missing modules {wiring['missing_modules']}")
        applied["policy_override"] = (
            "wired into nothing (" + "; ".join(detail) + ") — CLAUDE.md: code no loader "
            "reads is dead weight however well written")
        return "DEAD_WEIGHT", applied["policy_override"], applied

    if opinion.get("fabricates_data") is True:
        applied["useful_if_correct"] = min(score, 1)
        applied["policy_override"] = (
            "fabricates_data=true — inventing numbers instead of reading a source is the "
            "exact failure this system exists to detect; capped and sent to a human")
        return "NEEDS_HUMAN", applied["policy_override"], applied

    if opinion.get("defect_class") == "placeholder_stub" and score >= 4:
        applied["useful_if_correct"] = 3
        applied["policy_override"] = "placeholder_stub cannot score above 3 — a stub is intent, not work"
        return verdict, reason, applied

    return verdict, reason, applied


def _discrimination(rows: list) -> dict:
    """Is the JUDGE discriminating, or rubber-stamping?

    Measured on the judge's RAW opinion, never on the final verdict. Those are different
    questions and conflating them reads backwards: once the wiring policy landed, 14 of
    17 came out DEAD_WEIGHT and the flag fired "the judge is not discriminating" — but
    that concentration was a deterministic finding about the patches (they write files
    nothing reads), not a model failing to think. A house rule agreeing with itself
    across many patches is a conclusion; a judge agreeing with itself is a warning."""
    judged = [r for r in rows if r.get("opinion")]
    if not judged:
        return {"judged": 0, "judge_spread": {}, "verdict_spread": {}, "rubber_stamp": None}

    def _spread(key):
        counts = {}
        for r in judged:
            if key == "verdict":
                v = r["verdict"]
            else:
                v = str((r.get("opinion_raw") or r.get("opinion") or {})
                        .get("recommendation", "unclear")).upper()
            counts[v] = counts.get(v, 0) + 1
        return counts

    judge_counts = _spread("judge")
    top = max(judge_counts.values())
    raw_scores = sorted({(r.get("opinion_raw") or r.get("opinion") or {})
                         .get("useful_if_correct") for r in judged} - {None})
    stamp = top / len(judged) >= 0.8
    return {
        "judged": len(judged),
        "judge_spread": judge_counts,
        "judge_distinct_scores": raw_scores,
        "verdict_spread": _spread("verdict"),
        "policy_overrides": sum(1 for r in judged
                                if (r.get("opinion") or {}).get("policy_override")),
        "rubber_stamp": stamp,
        "note": ("the JUDGE gave one recommendation to >=80% of patches — its ranking is "
                 "weak evidence on its own; the deterministic checks are carrying this "
                 "report") if stamp else
                "the judge's own recommendations are spread; its ranking carries signal",
    }


def triage(limit: int | None = None, offline: bool = False) -> dict:
    patches = sorted(p for p in QUARANTINE_DIR.glob("*.py") if p.is_file())
    if limit:
        patches = patches[:limit]

    rows = []
    for py in patches:
        facts = _facts(py)
        row = {k: v for k, v in facts.items() if k != "source"}

        if facts["protected"]:
            # The canon lane. No model is consulted and no ranking can move this.
            row["verdict"] = "HUMAN_ONLY"
            row["reason"] = f"protected path: {facts['protected']}"
            row["opinion"] = None
            rows.append(row)
            print(f"  HUMAN_ONLY  {py.name} — {facts['protected']}")
            continue

        if offline:
            row["verdict"] = "UNJUDGED"
            row["reason"] = "--offline: facts only, no model consulted"
            row["opinion"] = None
            rows.append(row)
            print(f"  UNJUDGED    {py.name}")
            continue

        try:
            raw = _judge(facts)
            verdict, reason, applied = _apply_policy(raw, facts.get("wiring"))
            row["opinion"] = applied
            row["opinion_raw"] = raw          # what the judge said before house rules
            row["verdict"] = verdict
            row["reason"] = reason
            print(f"  {verdict:<11} {py.name}  useful={applied.get('useful_if_correct')}"
                  f"{' (POLICY)' if applied.get('policy_override') else ''}  "
                  f"{str(raw.get('intent',''))[:60]}")
        except Exception as e:
            row["verdict"] = "JUDGE_FAILED"
            row["reason"] = f"{type(e).__name__}: {e}"
            row["opinion"] = None
            print(f"  JUDGE_FAILED {py.name} — {type(e).__name__}")
        rows.append(row)

    def rank(r):
        op = r.get("opinion") or {}
        useful = op.get("useful_if_correct")
        useful = useful if isinstance(useful, (int, float)) else -1
        return (-useful, not op.get("trivially_fixable", False), r["patch"])

    rows.sort(key=rank)
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "quarantine_dir": str(QUARANTINE_DIR.relative_to(BASE_DIR)),
        "n_patches": len(rows),
        "note": "usefulness is a MODEL OPINION for ranking a human queue; "
                "protection and parse status are computed facts. Nothing here is applied.",
        "discrimination": _discrimination(rows),
        "next_step": "venv/Scripts/python.exe scripts/review_quarantine.py --show <name>",
        "patches": rows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _print_summary(report: dict) -> None:
    rows = report["patches"]
    print(f"\n{'='*78}")
    print(f"TRIAGE: {len(rows)} quarantined patch(es) -> "
          f"{OUT_PATH.relative_to(BASE_DIR)}")
    print(f"{'='*78}")
    by_verdict = {}
    for r in rows:
        by_verdict.setdefault(r["verdict"], []).append(r)
    for v in sorted(by_verdict):
        print(f"  {v:<13} {len(by_verdict[v])}")
    disc = report.get("discrimination") or {}
    if disc.get("policy_overrides"):
        print(f"\n  {disc['policy_overrides']} verdict(s) set by house rule, "
              f"overriding the judge (raw opinion kept in the report)")
    if disc.get("rubber_stamp"):
        print(f"  ⚠️  {disc.get('note')}")
        print(f"      judge said: {disc.get('judge_spread')} "
              f"scores {disc.get('judge_distinct_scores')}")
    worth = [r for r in rows
             if (r.get("opinion") or {}).get("useful_if_correct", 0) >= 3
             and r["verdict"] == "REWRITE"]
    if worth:
        print(f"\nWORTH REWRITING ({len(worth)}):")
        for r in worth:
            op = r["opinion"]
            print(f"  [{op['useful_if_correct']}/5] {r['patch']}")
            print(f"        target : {r.get('target')}")
            print(f"        intent : {op.get('intent')}")
            print(f"        defect : {op.get('defect_class')} "
                  f"(trivially fixable: {op.get('trivially_fixable')})")
    else:
        print("\nNothing scored >=3/5 with a rewrite recommendation.")
    print("\nNOTHING WAS APPLIED. Next step is yours:")
    print(f"  venv/Scripts/python.exe scripts/review_quarantine.py --show <name>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true",
                    help="report which integrations are LIVE/INERT in this repo")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--offline", action="store_true",
                    help="compute the facts, consult no model")
    args = ap.parse_args()

    if args.selftest:
        print("triage_quarantine --selftest")
        ok = True
        for name, state in _integrations().items():
            print(f"  {state:<28} {name}")
            if state.startswith("INERT"):
                ok = False
        print("\nRESULT:", "all integrations LIVE" if ok else "DEGRADED — see INERT above")
        return 0 if ok else 1

    if not QUARANTINE_DIR.is_dir():
        print(f"[TRIAGE] no quarantine directory at {QUARANTINE_DIR}")
        return 1
    report = triage(limit=args.limit, offline=args.offline)
    _print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
