#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/hyperclaw/hyperclaw_orchestrator.py
HyperClaw — генерира глобален 24-72h план по четирите оси:
HUMAN / PLANET / CIVILIZATION / COSMOS
Чете master_snapshot_latest.json (dailyreview-*.md като fallback).
"""
from __future__ import annotations
import json, pathlib
from datetime import datetime, timezone

BASE      = pathlib.Path(__file__).resolve().parents[2]
PLAN_DIR  = BASE / "plans"
AXES_SPEC = BASE / "agi_axes_spec.txt"
PLAN_DIR.mkdir(parents=True, exist_ok=True)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _read_context() -> str:
    master = BASE / "snapshots" / "master" / "master_snapshot_latest.json"
    if master.exists():
        try:
            data = json.loads(master.read_text(encoding="utf-8"))
            summary = {
                "axes_count": data.get("axes_count", 0),
                "timestamp":  data.get("timestamp"),
            }
            for axis, d in data.get("snapshots", {}).items():
                summary[axis] = {
                    "current_level": d.get("current_level", "?"),
                    "xrisk_score":   d.get("xrisk_score", "?"),
                    "progress_pct":  d.get("progress_pct") or d.get("overall_progress_pct", "?"),
                    "bottlenecks":   d.get("main_bottlenecks", [])[:2],
                    "next_actions":  d.get("next_actions", [])[:2],
                }
            return json.dumps(summary, ensure_ascii=False, indent=2)[:4000]
        except Exception:
            pass
    # Fallback: most recent dailyreview
    daily = BASE / "daily"
    if daily.exists():
        files = sorted(daily.glob("dailyreview-*.md"), key=lambda p: p.name, reverse=True)
        if files:
            return files[0].read_text(encoding="utf-8", errors="ignore")[:4000]
    return "(no snapshot data available)"


def _load_merkle_essence() -> str:
    """Връща load_fast() есенция от MerkleMemory — сжат контекст от минали цикли."""
    import sys
    sys.path.insert(0, str(BASE))
    try:
        from merkle_memory import MerkleMemory
        essence = MerkleMemory().load_fast()
        if essence and len(essence) > 20:
            return essence[:800]
    except Exception as e:
        print(f"[HYPERCLAW] MerkleMemory.load_fast() failed: {e}")
    return ""


# ── WHAT THE SYSTEM CAN ACTUALLY DO (Kimi Round 31, 5 Sep 2026) ───────────────
# The planner used to be asked for "concrete actions" with no statement of what
# this system is able to do. It answered with mailing lists, membrane filters and
# a 10 000-user survey. None of that is an action THIS system can take, so none
# of it could ever be graded, so none of it could ever be learned from.
CAPABILITIES = (
    "CORTEX++ CAN: read public indicators (World Bank, NOAA, USGS, WHO, UNHCR, ACLED, "
    "arXiv, GitHub) once a night; write JSON snapshots and scores; register a "
    "prediction about an indicator and grade it later; publish a Markdown/JSON report "
    "to GitHub; propose a patch to its own code for a HUMAN to review.\n"
    "CORTEX++ CANNOT: send email, run surveys, fund, build, deploy, contact anyone, or "
    "change anything in the world without a human acting on its output."
)

PROPOSAL_KEYS = ("INDICATOR", "EXPECTED_DELTA", "DEADLINE")


def _gradeable_indicators() -> dict:
    """axis -> observed value, for axes MEASURED this cycle. Same gate as K1 and as
    hypothesis_intake: only these can be graded, so only these may be named."""
    import sys
    sys.path.insert(0, str(BASE))
    try:
        from core.hypothesis_intake import measured_axes
        return measured_axes()
    except Exception as e:
        print(f"[HYPERCLAW] measured_axes unavailable: {e}")
        return {}


def _indicator_block(indicators: dict) -> str:
    if not indicators:
        return ("GRADEABLE INDICATORS: none resolved this cycle - any INDICATOR you name "
                "will be refused at intake.\n")
    lines = [f"  {k}: {v}" for k, v in sorted(indicators.items())]
    return ("GRADEABLE INDICATORS (axis: current value). INDICATOR must be one of these "
            "axes, or AXIS__metric where the metric is measured under that axis:\n"
            + "\n".join(lines) + "\n")


def parse_plan(plan_text: str, plan_name: str, ts: str) -> list:
    """plan-*.md -> proposals. Moved out of fast_cycle_runner._hyperclaw_to_proposals
    (5 Sep 2026) so it can be tested without importing the whole cycle.

    Every OBJECTIVE and STEP line becomes a proposal. If it is followed by indented
    INDICATOR / EXPECTED_DELTA / DEADLINE lines, those become fields on the proposal;
    if not, the proposal is born without them and core.proposal_intake refuses it
    with the missing pieces named. The parser never fills a field it did not read."""
    import re as _re
    _bold_re      = _re.compile(r'\*{1,2}([^*]+)\*{1,2}')
    _obj_re       = _re.compile(r'^\*{0,2}OBJECTIVE\*{0,2}\s*:', _re.IGNORECASE)
    _step_num_re  = _re.compile(r'^(\d+)\.\s+(.+)')
    # MEASURED 6 Sep 2026: the model writes "- **STEP 1:** ...". The old pattern
    # required the literal STEP straight after "- ", died at the bold marker, and
    # matched NOTHING - all 8 steps of plan-2026-09-06.md vanished without a
    # trace, while their triples leaked onto the section's OBJECTIVE. A step that
    # is refused is recorded by name; a step that never matched is not recorded
    # anywhere, which is why this is the worse failure.
    _step_dash_re = _re.compile(
        r'^[-*]?\s*\*{0,2}STEP\s*(\d+)\s*\*{0,2}\s*[:.~-]?\s*\*{0,2}\s*(.+)',
        _re.IGNORECASE)
    _key_re       = _re.compile(r'^[-*\s]*\*{0,2}(INDICATOR|EXPECTED_DELTA|DEADLINE)\*{0,2}\s*:\s*(.+?)\s*$',
                                _re.IGNORECASE)

    def _clean(text: str) -> str:
        # _bold_re needs asterisks on BOTH sides. "**OBJECTIVE:** text" loses
        # "**OBJECTIVE:" to _obj_re.sub and keeps a LEADING "**" that matches
        # nothing, so every solution in the 6 Sep plan began with "** ". Strip
        # what is left after the paired substitution.
        out = _bold_re.sub(r'\1', text).strip()
        return out.strip('*').strip()

    proposals: list = []
    seen_steps: dict = {}
    current_axis = None
    current = None
    for raw in plan_text.splitlines():
        line = raw.strip()
        for marker in ("HUMAN_AXIS_FOCUS", "PLANET_AXIS_FOCUS", "CIVILIZATION_AXIS_FOCUS", "COSMOS_AXIS_FOCUS"):
            if marker in line:
                current_axis = marker.replace("_AXIS_FOCUS", "")
                current = None
        if not current_axis:
            continue
        km = _key_re.match(line)
        # A triple belongs to the STEP above it. Before 6 Sep no STEP ever
        # matched, so every triple in a section wrote into that section's
        # OBJECTIVE - step 1 setting it and step 2 overwriting it. An objective
        # is not a step and must not wear numbers it never had.
        if km and current is not None and current.get("step_index") is not None:
            key, val = km.group(1).upper(), _clean(km.group(2))
            if key == "INDICATOR":
                current["indicator"] = val
            elif key == "EXPECTED_DELTA":
                try:
                    current["expected_delta"] = float(val.replace(",", ".").rstrip("%").strip())
                except ValueError:
                    current["expected_delta"] = val  # intake names it as not a number
            elif key == "DEADLINE":
                current["deadline"] = val[:10]
            continue
        if _obj_re.match(line):
            objective = _clean(_obj_re.sub("", line, count=1))
            if objective and "<" not in objective and len(objective) > 10:
                current = {
                    "component":         current_axis,
                    "problem":           f"{current_axis} axis needs progress",
                    "solution":          objective,
                    "root_cause":        f"HyperClaw plan - {plan_name}",
                    "priority":          "MEDIUM",
                    "real_world_signal": True,
                    "generated_by":      "HYPERCLAW",
                    "timestamp":         ts,
                }
                proposals.append(current)
            continue
        m = _step_dash_re.match(line) or _step_num_re.match(line)
        if m:
            step_no, step = m.group(1), _clean(m.group(2))
            if step and "<" not in step and len(step) > 10:
                seen_steps[current_axis] = seen_steps.get(current_axis, 0) + 1
                try:
                    idx = int(step_no)
                except (TypeError, ValueError):
                    idx = seen_steps[current_axis]
                current = {
                    "component":         current_axis,
                    "problem":           f"Action required for {current_axis}",
                    "solution":          step,
                    "root_cause":        f"HyperClaw step - {plan_name}",
                    "priority":          "MEDIUM",
                    "real_world_signal": True,
                    "generated_by":      "HYPERCLAW",
                    "timestamp":         ts,
                    # PROVENANCE. Two steps of one axis are indistinguishable in
                    # the ledger without it.
                    "axis":              current_axis,
                    "step_index":        idx,
                    "plan":              plan_name,
                }
                proposals.append(current)
    return proposals


def _build_prompt(context: str, axes_spec: str, today: str, merkle_essence: str = "",
                  indicators: dict | None = None) -> str:
    merkle_section = (
        f"── MERKLE MEMORY (история от минали цикли) ──\n{merkle_essence}\n\n"
        if merkle_essence else ""
    )
    return (
        "Ти си CORTEX++ в ролята на HYPERCLAW_ORCHESTRATOR.\n"
        "Имаш достъп до текущото състояние на системата по всички оси.\n\n"
        + CAPABILITIES + "\n\n"
        + _indicator_block(indicators or {}) + "\n"
        "ЗАДАЧА: Генерирай глобален план `plan-{today}.md` с конкретни стъпки\n"
        "за следващите 24-72 часа по всяка от четирите оси.\n"
        "За всяка ос избери под-оси с нисък прогрес или висок риск.\n"
        "ВСЯКА СТЪПКА Е ДЕЙСТВИЕ, КОЕТО CORTEX++ МОЖЕ ДА ИЗВЪРШИ (виж CAN/CANNOT), и носи\n"
        "три реда под себе си: INDICATOR (от списъка горе), EXPECTED_DELTA (число със знак,\n"
        "очаквана промяна на индикатора), DEADLINE (YYYY-MM-DD, до 1 година). Стъпка без\n"
        "трите реда се ОТКАЗВА при приемане и не влиза никъде.\n\n"
        "ИЗХОД: САМО Markdown съдържание. Без meta-коментари.\n\n"
        f"# HYPERCLAW MULTI-AXIS PLAN – {today}\n\n"
        "META:\n"
        f"  DATE: {today}\n"
        "  ORCHESTRATOR: HYPERCLAW\n"
        "  SOURCE: master_snapshot_latest.json\n\n"
        "HUMAN_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES: [<под-ос с нисък прогрес>]\n"
        "  OBJECTIVE: <целево подобрение за 24-72h>\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <конкретно действие, което CORTEX++ може да извърши>\n"
        "      INDICATOR: <AXIS или AXIS__metric от списъка>\n"
        "      EXPECTED_DELTA: <число със знак>\n"
        "      DEADLINE: <YYYY-MM-DD>\n"
        "    - STEP 2: <конкретно действие>\n"
        "      INDICATOR: <...>\n"
        "      EXPECTED_DELTA: <...>\n"
        "      DEADLINE: <...>\n"
        "  CROSS_AXIS_EFFECTS: <ефект върху PLANET/CIVILIZATION/COSMOS>\n\n"
        "PLANET_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES: [<под-ос>]\n"
        "  OBJECTIVE: <цел>\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <действие>\n"
        "      INDICATOR: <...>\n"
        "      EXPECTED_DELTA: <...>\n"
        "      DEADLINE: <...>\n"
        "    - STEP 2: <действие>\n"
        "      INDICATOR: <...>\n"
        "      EXPECTED_DELTA: <...>\n"
        "      DEADLINE: <...>\n"
        "  CROSS_AXIS_EFFECTS: <ефект>\n\n"
        "CIVILIZATION_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES: [<под-ос>]\n"
        "  OBJECTIVE: <цел>\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <действие>\n"
        "      INDICATOR: <...>\n"
        "      EXPECTED_DELTA: <...>\n"
        "      DEADLINE: <...>\n"
        "    - STEP 2: <действие>\n"
        "      INDICATOR: <...>\n"
        "      EXPECTED_DELTA: <...>\n"
        "      DEADLINE: <...>\n"
        "  CROSS_AXIS_EFFECTS: <ефект>\n\n"
        "COSMOS_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES: [LONG_TERM_FUTURE_REVIEW]\n"
        "  OBJECTIVE: <намаляване на екзистенциален риск>\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <действие>\n"
        "      INDICATOR: <...>\n"
        "      EXPECTED_DELTA: <...>\n"
        "      DEADLINE: <...>\n"
        "    - STEP 2: <действие>\n"
        "      INDICATOR: <...>\n"
        "      EXPECTED_DELTA: <...>\n"
        "      DEADLINE: <...>\n"
        "  CROSS_AXIS_EFFECTS: <ефект>\n\n"
        "GLOBAL_RISKS_AND_CHECKS:\n"
        "  - <риск>: check: <метрика>\n\n"
        "NEXT_REVIEW_SIGNALS:\n"
        "  HUMAN: <индикатор>\n"
        "  PLANET: <индикатор>\n"
        "  CIVILIZATION: <индикатор>\n"
        "  COSMOS: <индикатор>\n\n"
        + merkle_section
        + f"── AGI AXES SPEC ──\n{axes_spec[:1000]}\n\n"
        f"── ТЕКУЩО СЪСТОЯНИЕ ──\n{context}\n\n"
        f"Генерирай plan-{today}.md по горния формат. Само Markdown."
    ).replace("{today}", today)


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"[HYPERCLAW] started at {_utc_now()}")

    context        = _read_context()
    # Wire-first (16 Aug 2026): the cycle comment at step 12.7 always claimed
    # HyperClaw uses the orchestrator's priority_axes — it never read them.
    # Now it does: attention.priority_axes from orchestration_latest.json.
    try:
        _orch = json.loads((BASE / "memory" / "orchestration_latest.json")
                           .read_text(encoding="utf-8"))
        _pa = (_orch.get("attention") or {}).get("priority_axes") or []
        if _pa:
            context += ("\n\nPRIORITY_AXES (cognitive_orchestrator, this cycle): "
                        + json.dumps(_pa, ensure_ascii=False)[:600]
                        + "\nFocus the sub-axis selection on these first.")
            print(f"[HYPERCLAW] priority_axes wired: {str(_pa)[:120]}")
    except Exception as _e:
        print(f"[HYPERCLAW] priority_axes unavailable: {_e}")
    axes_spec      = AXES_SPEC.read_text(encoding="utf-8", errors="ignore") if AXES_SPEC.exists() else ""
    merkle_essence = _load_merkle_essence()
    if merkle_essence:
        print(f"[HYPERCLAW] MerkleMemory essence loaded ({len(merkle_essence)} chars)")
    indicators     = _gradeable_indicators()
    print(f"[HYPERCLAW] gradeable indicators offered: {len(indicators)}")
    prompt         = _build_prompt(context, axes_spec, today, merkle_essence, indicators)

    plan_md = None
    try:
        from core.groq_backend import call_groq, AllBackendsFailedError
        plan_md = call_groq(prompt, max_tokens=4000)
    except AllBackendsFailedError as e:
        print(f"[HYPERCLAW] AllBackendsFailedError — всички backends изчерпани: {e}")
        _snap_dir = BASE / "snapshots" / "hyperclaw"
        _snap_dir.mkdir(parents=True, exist_ok=True)
        (_snap_dir / "hyperclaw_snapshot_latest.json").write_text(
            json.dumps({
                "axis": "HYPERCLAW_PLAN",
                "needs_reanalysis": True,
                "error": str(e)[:200],
                "snapshot_timestamp": _utc_now(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[HYPERCLAW] LLM error: {e}")

    if not plan_md:
        print("[HYPERCLAW] пропускам запис — няма план (всички LLM backends неуспешни)")
        return

    out_path = PLAN_DIR / f"plan-{today}.md"
    out_path.write_text(plan_md, encoding="utf-8")
    print(f"[HYPERCLAW] plan written -> {out_path}")


if __name__ == "__main__":
    main()
