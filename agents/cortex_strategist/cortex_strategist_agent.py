#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/cortex_strategist/cortex_strategist_agent.py

CortexStrategist -- Scans the ENTIRE CORTEX++ project:
  - all Python files (agents, memory, core)
  - all snapshots
  - goals.py / semantic_memory / predictions / patches

After scanning: LLM synthesizes concrete solutions
for achieving the goal -- sustainable human civilization.
"""

from __future__ import annotations
import json, pathlib, sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
MODEL = "qwen3:1.7b"

PROMPT_CHAR_CAP = 60000


def _groq(prompt: str) -> dict:
    """Fallback chain: Groq -> OpenRouter -> Gemini -> local_3b.

    ── WHAT THE 10 SEP LOG ACTUALLY SAYS (STEP 6b), AND IT IS NOT WHAT IT SAID ──
    The night of 10 Sep printed, in this order:

        [LLM] Groq failed (413 Client Error: Payload Too Large) -- next...
        [STRATEGIST] JSON parse failed: Expecting value: line 1 column 1 (char 0)
        [STRATEGIST] raw LLM output: "We need to analyze the system and output
                                      JSON with required fields."
        [STRATEGIST] LLM error: All LLM backends failed

    The last line was FALSE and it sent the diagnosis down the wrong road. The
    413 was handled correctly — the chain moved on, and memory/llm_provenance
    .jsonl records OpenRouter (nvidia/nemotron-3-super-120b) answering `ok` 36
    seconds later. A backend ANSWERED. What failed was this function's own
    parser: nemotron is a reasoning model, it thought out loud before the JSON,
    and the hand-rolled fence-split here saw prose at char 0 and gave up. Then
    `None` was reported as "All LLM backends failed" — a parsing defect wearing
    an infrastructure defect's name.

    Two fixes, neither of them new code:

    1. core/llm_json.py already exists and already handles this exact family —
       reasoning preambles ("We need to produce JSON ..."), <think> blocks,
       fences, decoy braces in the prose, truncation. It was written to replace
       four hand-rolled parsers; this was the fifth and it was not migrated.
    2. The two outcomes are now told apart. "No backend answered" and "a backend
       answered and its reply did not parse" are different facts and must never
       again share one sentence.
    """
    import sys
    sys.path.insert(0, str(BASE))
    from core.llm_json import call_llm_json, LLMJSONError
    from core.groq_backend import AllBackendsFailedError
    try:
        return call_llm_json(prompt, max_tokens=1500, expect=dict,
                             label="STRATEGIST")
    except AllBackendsFailedError as e:
        print(f"[STRATEGIST] no backend answered: {e}")
        return {"error": f"no backend answered: {e}"}
    except LLMJSONError as e:
        # A model DID answer. Say so, and say what came back.
        print(f"[STRATEGIST] a backend answered but the reply did not parse: {e}")
        return {"error": f"reply did not parse as JSON: {e}"}
    except Exception as e:
        print(f"[STRATEGIST] LLM chain raised {type(e).__name__}: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def _cap(prompt: str, cap: int = PROMPT_CHAR_CAP) -> str:
    """Cap the prompt with a NAMED marker, never silently.

    Groq answered 413 five times between 2 and 10 Sep, on three different
    callers (the 25-axis planet analyser, HYPERCLAW_ORCHESTRATOR and this
    agent), and the size that triggered it is UNRECOVERABLE: llm_provenance
    rows carry prompt_sha1 and prompt_head, never a length. Measured here on
    10 Sep this prompt is 22,354 chars / 25,129 bytes / ~6.4k tokens, which
    would not 413 — so something larger went out on those nights and the log
    cannot say what. The cap is therefore a ceiling with a visible marker, not
    a fix for a diagnosed size: if it ever fires, the line says so and names
    how much was dropped, so a truncated brief can never be read as a complete
    one.
    """
    if len(prompt) <= cap:
        return prompt
    dropped = len(prompt) - cap
    print(f"[STRATEGIST] prompt {len(prompt)} chars exceeds the {cap} cap — "
          f"dropping {dropped} chars from the evidence block")
    return (prompt[:cap] +
            f"\n\n[[TRUNCATED BY cortex_strategist_agent._cap: {dropped} chars "
            f"of evidence removed to stay under {cap}. This brief is INCOMPLETE "
            f"— say so in strategist_self_assessment.]]\n")
EXCLUDE_DIRS = {"venv", "__pycache__", ".git", "OLD", "LEGACY", ".npm-global"}

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def scan_project():
    ctx = {
        "goals": "",
        "agents": [],
        "memory_modules": [],
        "snapshots_summary": {},
        "predictions": [],
        "self_modifier_patches": [],
        "missing_integrations": [],
        "cycle_structure": "",
        "goal_score": {},
    }

    # Goals
    gf = BASE / "core" / "goals.py"
    if gf.exists():
        ctx["goals"] = gf.read_text(encoding="utf-8", errors="ignore")[:2000]

    # All Python files
    for py in sorted(BASE.rglob("*.py")):
        if any(ex in py.parts for ex in EXCLUDE_DIRS):
            continue
        rel = str(py.relative_to(BASE))
        try:
            lines = py.read_text(encoding="utf-8", errors="ignore").splitlines()
            ctx["agents"].append({
                "file": rel,
                "lines": len(lines),
                "preview": "\n".join(lines[:20])[:400],
            })
        except Exception:
            pass

    # Memory modules
    md = BASE / "memory"
    if md.exists():
        ctx["memory_modules"] = [f.name for f in sorted(md.glob("*.py"))]

    # Snapshots
    sd = BASE / "snapshots"
    if sd.exists():
        for jf in sorted(sd.rglob("*_snapshot_latest.json")):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                axis = data.get("axis", jf.stem)
                ctx["snapshots_summary"][axis] = {
                    "current_level": data.get("current_level", "?"),
                    "progress_pct": data.get("progress_pct") or data.get("overall_progress_pct", "?"),
                    "xrisk_score": data.get("xrisk_score", "?"),
                    "bottlenecks": data.get("main_bottlenecks", [])[:3],
                    "next_actions": data.get("next_actions", [])[:2],
                }
            except Exception:
                pass

    # Predictions
    pf = BASE / "memory" / "predictions.json"
    if pf.exists():
        try:
            p = json.loads(pf.read_text(encoding="utf-8"))
            ctx["predictions"] = p[-10:] if isinstance(p, list) else []
        except Exception:
            pass

    # Patches
    pd = BASE / "patches"
    if pd.exists():
        ctx["self_modifier_patches"] = [f.name for f in pd.glob("*.py")]

    # Goal score
    gs = BASE / "snapshots" / "master" / "goal_score_latest.json"
    if gs.exists():
        try:
            ctx["goal_score"] = json.loads(gs.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Cycle structure
    rf = BASE / "fast_cycle_runner.py"
    if rf.exists():
        ctx["cycle_structure"] = rf.read_text(encoding="utf-8", errors="ignore")[:1500]

    # Missing integrations
    for a in ctx["agents"]:
        name = pathlib.Path(a["file"]).stem
        if "agent" in name.lower() and name not in ctx["cycle_structure"]:
            ctx["missing_integrations"].append(a["file"])

    return ctx

def synthesize(ctx):
    agents_list = "\n".join(f"  - {a['file']} ({a['lines']} lines)" for a in ctx["agents"][:50])
    snap_str = json.dumps(ctx["snapshots_summary"], ensure_ascii=False, indent=2)[:2000]
    missing_str = "\n".join(f"  - {m}" for m in ctx["missing_integrations"][:20]) or "(none)"
    goal_score_str = json.dumps(ctx.get("goal_score", {}), ensure_ascii=False, indent=2)[:500] or "(not available)"

    vision_file = BASE / "core" / "civilization_vision.txt"
    vision_text = vision_file.read_text(encoding="utf-8", errors="ignore") if vision_file.exists() else "(vision not found)"

    # Load homeostatic self-awareness block
    homeo_block = ""
    try:
        from core.homeostasis import as_prompt_block as _homeo_block
        homeo_block = _homeo_block()
    except Exception:
        pass

    # Load Attentional Meta Protocol output (cortex_orchestrator runs at Step 12.7)
    attention_block = ""
    orch_path = BASE / "memory" / "orchestration_latest.json"
    if orch_path.exists():
        try:
            orch = json.loads(orch_path.read_text(encoding="utf-8"))
            att = orch.get("attention", {})
            plan = orch.get("strategic_plan", {})
            attention_block = (
                "-- ATTENTIONAL META PROTOCOL (this cycle) --\n"
                f"Priority axes: {att.get('priority_axes', [])}\n"
                f"Main threat:   {att.get('main_threat', '?')}\n"
                f"Opportunity:   {att.get('main_opportunity', '?')}\n"
                f"Action now:    {att.get('immediate_action', '?')}\n"
                f"Key insight:   {plan.get('key_insight', '?')}\n"
                "---------------------------------------------"
            )
        except Exception:
            pass

    # Load system hypergraph summary -- isolated nodes only for missing_agents_to_build
    hg_block = ""
    hg_path = BASE / "data" / "cortex_hypergraph.json"
    if hg_path.exists():
        try:
            hg = json.loads(hg_path.read_text(encoding="utf-8"))
            agents_in_cycle = [a["agent"] for a in hg.get("agents_order", [])]
            isolated = hg.get("isolated_nodes", [])
            degree = hg.get("node_degree", {})
            seq = " -> ".join(agents_in_cycle[:10]) + ("..." if len(agents_in_cycle) > 10 else "")
            hg_block = (
                "-- SYSTEM HYPERGRAPH --\n"
                f"Agents in execution chain ({len(agents_in_cycle)}): {seq}\n"
                f"Node degree (follows connections): {json.dumps(degree, ensure_ascii=False)}\n"
                f"Isolated nodes (zero connectivity, not in chain): {isolated or ['none']}\n"
                "RULE: Suggest missing_agents_to_build ONLY for nodes in the isolated list above.\n"
                "Do NOT suggest building agents that already appear in the execution chain.\n"
                "---------------------------------------------"
            )
        except Exception:
            pass

    # Load real global indicators if available this cycle
    gi_block = ""
    gi_path = BASE / "snapshots" / "master" / "global_indicators_latest.json"
    if gi_path.exists():
        try:
            from core.global_indicators import as_prompt_block
            gi_data = json.loads(gi_path.read_text(encoding="utf-8"))
            gi_block = as_prompt_block(gi_data)
        except Exception:
            gi_block = "(global indicators file exists but could not be loaded)"

    # THE GATE CONTRACT (6 Sep 2026) - see agents/body/growth_planner.py for why.
    # strategist_to_proposals walks immediate_actions and critical_gaps to
    # proposal_intake; this prompt never named the contract they are judged by.
    try:
        from core.gate_contract import contract_block as _contract
        _gate = _contract()
    except Exception as _e:                                      # noqa: BLE001
        print(f"[STRATEGIST] REFUSED to build a prompt without the gate contract: {_e}")
        raise

    prompt = f"""You are CortexStrategist -- strategic intelligence of CORTEX++ AGI.

{_gate}

MISSION:
{vision_text}

You scanned the ENTIRE CORTEX++ project. Full context:

-- GOALS --
{ctx['goals'][:800]}

-- PROJECT FILES ({len(ctx['agents'])} files) --
{agents_list}

-- MEMORY MODULES --
{', '.join(ctx['memory_modules'])}

-- SNAPSHOTS STATE --
{snap_str}

-- GOAL SCORE (composite from real data) --
{goal_score_str}

{homeo_block}

{attention_block}

{gi_block}

{hg_block}

-- AGENTS NOT IN fast_cycle_runner (missing integrations) --
{missing_str}

-- CYCLE STRUCTURE --
{ctx['cycle_structure'][:800]}

-- PATCHES --
{', '.join(ctx['self_modifier_patches']) or '(none)'}

TASK: Analyze EVERYTHING. What is missing? What is broken? What must be built?
How does this system get closer to the MISSION?

CRITICAL RULE for missing_agents_to_build: ONLY suggest agents whose names appear in
the "Isolated nodes" list from the SYSTEM HYPERGRAPH above. If isolated list is empty
or says "none", return an empty array for missing_agents_to_build.
Do NOT invent agents that already exist in the execution chain.

Return ONLY this JSON:
{{
  "system_health": "POOR|FAIR|GOOD|EXCELLENT",
  "mission_alignment_pct": <0-100>,
  "critical_gaps": [
    {{"gap": "<what is missing>", "impact": "HIGH|MEDIUM|LOW", "fix": "<concrete action>",
     "INDICATOR": "<exact name from GRADEABLE INDICATORS above>",
     "EXPECTED_DELTA": <signed bare number>, "DEADLINE": "<YYYY-MM-DD>"}}
  ],
  "immediate_actions": [
    {{"action": "<what to do>", "file": "<which file>", "why": "<reason>",
     "INDICATOR": "<exact name from GRADEABLE INDICATORS above>",
     "EXPECTED_DELTA": <signed bare number>, "DEADLINE": "<YYYY-MM-DD>"}}
  ],
  "missing_agents_to_build": [
    {{"name": "<AgentName>", "role": "<what it does>", "priority": "HIGH|MEDIUM"}}
  ],
  "fast_cycle_improvements": ["<improvement>"],
  "next_milestone": "<what brings system to next level>",
  "strategist_self_assessment": "<what CortexStrategist should do next>"
}}

Be specific. Reference actual filenames. Return ONLY valid JSON."""

    result = _groq(_cap(prompt))
    if result and "error" not in result:
        print("[STRATEGIST] LLM: OK")
        return result
    # The reason travels. Replacing it with a generic sentence here is what put
    # "All LLM backends failed" in the 10 Sep log over a parse error (STEP 6b).
    return result if isinstance(result, dict) and result.get("error") else {
        "error": "no result and no reason — _groq returned "
                 f"{result!r}, which is itself the defect"}

def save(result):
    out_dir = BASE / "snapshots" / "cortex_strategist"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "cortex_strategist_snapshot_latest.json"
    result["snapshot_timestamp"] = _utc_now()
    result["axis"] = "STRATEGIST_SOLUTIONS"
    result["source_type"] = "STRATEGIST_FULL_SCAN"
    result["metrics"] = {
        "mission_alignment_pct": result.get("mission_alignment_pct"),
        "system_health": result.get("system_health"),
        "critical_gaps_count": len(result.get("critical_gaps", [])),
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[STRATEGIST] snapshot -> {out_path}")
    try:
        sys.path.insert(0, str(BASE))
        from memory.semantic_memory import remember
        summary = (f"CortexStrategist FullScan [{_utc_now()}]: "
                   f"Health={result.get('system_health','?')} | "
                   f"Mission={result.get('mission_alignment_pct','?')}% | "
                   f"Gaps={len(result.get('critical_gaps',[]))} | "
                   f"Next: {result.get('next_milestone','?')}")
        remember(summary[:600], axis="STRATEGIST_FULL_SCAN", source="cortex_strategist_agent")
        print("[STRATEGIST] memory saved.")
    except Exception as e:
        print(f"[STRATEGIST] memory save failed: {e}")

def run():
    print(f"[STRATEGIST] FullScan started at {_utc_now()}")
    ctx = scan_project()
    print(f"[STRATEGIST] {len(ctx['agents'])} files | {len(ctx['snapshots_summary'])} snapshots | {len(ctx['missing_integrations'])} missing integrations")
    print("[STRATEGIST] synthesizing strategic plan...")
    result = synthesize(ctx)
    if "error" in result:
        print(f"[STRATEGIST] LLM error: {result['error']}")
        result["needs_reanalysis"] = True
        save(result)
        return result
    print(f"[STRATEGIST] health={result.get('system_health')} | mission={result.get('mission_alignment_pct')}% | gaps={len(result.get('critical_gaps',[]))}")
    save(result)
    print(f"[STRATEGIST] done at {_utc_now()}")
    return result

if __name__ == "__main__":
    result = run()
    print("\n== CORTEX STRATEGIST PLAN ==")
    print(json.dumps(result, ensure_ascii=False, indent=2))
