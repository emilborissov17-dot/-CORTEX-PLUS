#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
initiative_tracker.py
Reads improvement_proposals.json, keeps only civilizational/external proposals
(not code-patch-generating ones), and creates/updates data/initiatives/{id}.json
with status=PROPOSED, milestone, target_date, and action_plan (Groq-generated).
"""
from __future__ import annotations
import json, hashlib, pathlib, re, sys, time
from datetime import datetime, timezone, timedelta

# Allow imports from core/ when run from root
_BASE_FOR_IMPORT = pathlib.Path(__file__).resolve().parent
if str(_BASE_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_BASE_FOR_IMPORT))

try:
    from core.groq_backend import call_groq as _call_groq
except Exception:
    _call_groq = None

BASE              = pathlib.Path(__file__).resolve().parent
PROPOSALS_PATH    = BASE / "memory" / "improvement_proposals.json"
INITIATIVES_DIR   = BASE / "data" / "initiatives"
_INDICATORS_PATH  = BASE / "snapshots" / "master" / "global_indicators_latest.json"

# Sources whose proposals are code-patch generators — skip entirely
_CODE_GENERATOR_SOURCES = {"OPENCLAW", "HYPERCLAW"}

# Text patterns that mark a proposal as a code action (generates *_patch.py)
_CODE_TEXT_PATTERN = re.compile(
    r"(_patch\.py|self_modifier\.py|execute_patches\.py"
    r"|fast_cycle_runner\.py"
    r"|(?<!\w)\.py\b)",   # bare .py extension but not e.g. "copy"
    re.IGNORECASE,
)

# Time expressions → months offset (Bulgarian + English)
_TIME_RULES: list[tuple[re.Pattern, object]] = [
    (re.compile(r"(\d+)\s*год(?:ин)?",  re.IGNORECASE), lambda m: int(m.group(1)) * 12),
    (re.compile(r"(\d+)\s*year",        re.IGNORECASE), lambda m: int(m.group(1)) * 12),
    (re.compile(r"(\d+)\s*месец",       re.IGNORECASE), lambda m: int(m.group(1))),
    (re.compile(r"(\d+)\s*month",       re.IGNORECASE), lambda m: int(m.group(1))),
    (re.compile(r"(\d+)\s*седмиц",      re.IGNORECASE), lambda m: max(1, round(int(m.group(1)) / 4.3))),
    (re.compile(r"(\d+)\s*week",        re.IGNORECASE), lambda m: max(1, round(int(m.group(1)) / 4.3))),
]
_DEFAULT_MONTHS = 6
_PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

# Valid manual transitions (from → set of allowed to)
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "PROPOSED":    {"IN_PROGRESS", "CANCELLED"},
    "OVERDUE":     {"IN_PROGRESS", "CANCELLED", "DONE"},
    "IN_PROGRESS": {"DONE", "CANCELLED", "PROPOSED"},
}

# Keyword → (dot_path_in_global_indicators, direction, label)
# direction: "lower" = we want to decrease it, "higher" = we want to increase it
# Ordered by specificity — first match wins.
_METRIC_MAP: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"неравенство|gini|inequality",             re.I), "world_bank.gini_mean",                  "lower",  "Gini coefficient"),
    (re.compile(r"бедност|poverty|беден",                   re.I), "world_bank.poverty_190_pct",            "lower",  "Poverty rate (%)"),
    (re.compile(r"CO2|въглероден|парников|emission",        re.I), "co2.co2_ppm",                           "lower",  "CO2 (ppm)"),
    (re.compile(r"температур|global.warm|климатична криза", re.I), "temperature.temp_anomaly_c",            "lower",  "Temp anomaly (°C)"),
    (re.compile(r"биоразнообразие|biodiversity|вид(?:ов)?", re.I), "biodiversity.species_observations_30d", "higher", "Species observations (30d)"),
    (re.compile(r"глад|undernourishment|недохранване",      re.I), "food.undernourishment_pct",             "lower",  "Undernourishment (%)"),
    (re.compile(r"безработиц|unemployment",                 re.I), "economy.unemployment_pct",              "lower",  "Unemployment (%)"),
    (re.compile(r"интернет|broadband|дигитал",              re.I), "cities.internet_users_pct",             "higher", "Internet users (%)"),
    (re.compile(r"електр|electricity|\bток\b",              re.I), "cities.electricity_access_pct",         "higher", "Electricity access (%)"),
    (re.compile(r"\bвода\b|water|водоснабд",                re.I), "world_bank.safe_water_access_pct",      "higher", "Safe water access (%)"),
    (re.compile(r"грамотност|literacy|образован",           re.I), "world_bank.literacy_rate_adult_pct",    "higher", "Literacy rate (%)"),
    (re.compile(r"ядрен|nuclear|warhead",                   re.I), "nuclear.nuclear_warheads_total",        "lower",  "Nuclear warheads"),
    (re.compile(r"бежанц|refugee|разселен|displaced",       re.I), "displaced.refugees_millions",           "lower",  "Refugees (millions)"),
    (re.compile(r"ВЕИ|renewable|слънч|вятърн|чиста.енерг", re.I), "world_bank.renewable_elec_pct",         "higher", "Renewable electricity (%)"),
    (re.compile(r"горск|forest|залесяване|обезлесяване",   re.I), "world_bank.forest_area_pct",            "higher", "Forest area (%)"),
    (re.compile(r"застрашен.*вид|threatened|изчезващ",     re.I), "world_bank.threatened_mammals_no",      "lower",  "Threatened mammals"),
    # Real infrastructure indicator: WDI IS.ROD.PAVE.ZS (global mean; ProACT and OCP
    # Open Contracting have no suitable public global API without authentication)
    (re.compile(r"пътищ|road|инфраструктур|transport",     re.I), "cities.roads_paved_pct",                "higher", "Roads, paved (% of total roads)"),
    # Real governance indicators: WGI GE.EST Government Effectiveness (-2.5 to +2.5)
    (re.compile(r"управлени|governance|демокрац|прозрачн",  re.I), "governance.ge_est",                    "higher", "Government Effectiveness (WGI GE.EST)"),
    (re.compile(r"продоволстви|хранителн|food.secur",       re.I), "food.food_production_index",            "higher", "Food production index"),
    (re.compile(r"\bBDP\b|GDP|икономически растеж",         re.I), "economy.gdp_growth_annual_pct",         "higher", "GDP growth (%)"),
]


def _is_code_action(proposal: dict) -> bool:
    """Return True if proposal generates *_patch.py code — not a civilizational initiative."""
    if proposal.get("generated_by", "") in _CODE_GENERATOR_SOURCES:
        return True
    if proposal.get("source", "") in _CODE_GENERATOR_SOURCES:
        return True
    text = " ".join([
        proposal.get("solution", ""),
        proposal.get("measurable_goal", ""),
        proposal.get("problem", ""),
        proposal.get("root_cause", ""),
    ])
    return bool(_CODE_TEXT_PATTERN.search(text))


def _extract_months(text: str) -> int:
    for pattern, converter in _TIME_RULES:
        m = pattern.search(text)
        if m:
            return max(1, int(converter(m)))
    return _DEFAULT_MONTHS


def _proposal_id(proposal: dict) -> str:
    """Stable ID derived from solution content + timestamp."""
    key = (proposal.get("solution", "") + proposal.get("timestamp", ""))[:128]
    return "init_" + hashlib.md5(key.encode("utf-8")).hexdigest()[:10]


def _generate_action_plan(problem: str, solution: str, target_date: str) -> list[dict]:
    """Call Groq to generate 3-5 concrete, measurable steps for this initiative."""
    if _call_groq is None:
        print("[INITIATIVE_TRACKER] call_groq недостъпен — action_plan пропуснат")
        return []
    prompt = (
        "Ти си стратегически планировчик за AGI система с глобална мисия.\n\n"
        f"ПРОБЛЕМ: {problem}\n"
        f"РЕШЕНИЕ: {solution}\n"
        f"КРАЕН СРОК: {target_date}\n\n"
        "Генерирай ACTION PLAN с 3-5 конкретни, измерими стъпки за постигане на решението.\n"
        "Всяка стъпка трябва да има:\n"
        "  - step: номер (1-5)\n"
        "  - description: конкретно действие (не абстрактно)\n"
        "  - deadline: дата YYYY-MM-DD между днес и крайния срок\n"
        "  - metric: как ще измерим успеха на тази стъпка\n\n"
        "Стъпките трябва да са наредени хронологично и всяка да надгражда предишната.\n"
        "Отговори САМО с валиден JSON масив — без markdown, без обяснения:\n"
        '[{"step":1,"description":"...","deadline":"YYYY-MM-DD","metric":"..."}]'
    )
    for attempt in range(2):
        try:
            raw = _call_groq(prompt, max_tokens=600)
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            if "```" in raw:
                parts = raw.split("```")
                for part in parts:
                    part = part.strip()
                    if part.startswith("json"):
                        part = part[4:].strip()
                    if part.startswith("["):
                        raw = part
                        break
            if "[" in raw:
                raw = raw[raw.index("["):raw.rindex("]") + 1]
            steps = json.loads(raw)
            if isinstance(steps, list) and steps:
                return steps[:5]
        except Exception as e:
            print(f"[INITIATIVE_TRACKER] action_plan attempt {attempt+1} грешка: {e}")
            if attempt == 0:
                time.sleep(5)
    return []


# ── PROGRESS MEASUREMENT ──────────────────────────────────────────────────────

def _get_indicator_value(dot_path: str, indicators: dict) -> float | None:
    """Extract a nested value by dot-path, e.g. 'world_bank.gini_mean'."""
    node: object = indicators
    for part in dot_path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    if node is None or not isinstance(node, (int, float)):
        return None
    return float(node)


def _match_metric(text: str) -> tuple[str, str, str] | None:
    """Return (dot_path, direction, label) for the first matching pattern, or None."""
    for pattern, dot_path, direction, label in _METRIC_MAP:
        if pattern.search(text):
            return dot_path, direction, label
    return None


def _extract_target_pct(text: str) -> float | None:
    """Pull the first percentage from text: '25% намаление' → 25.0."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
    return float(m.group(1).replace(",", ".")) if m else None


def _load_indicators() -> dict:
    try:
        return json.loads(_INDICATORS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[INITIATIVE_TRACKER] global_indicators load failed: {e}")
        return {}


def _measure_progress(initiative: dict, indicators: dict) -> dict:
    """
    Match the initiative's milestone text to a global_indicator field.
    On first call: captures baseline_value = current reading.
    On subsequent calls: computes progress % toward the milestone target.
    Returns a dict with measurable/progress fields to be merged back into the record.
    """
    init_id = initiative.get("id", "?")
    search_text = " ".join([
        initiative.get("problem", ""),
        initiative.get("solution", ""),
        initiative.get("milestone", ""),
    ])

    match = _match_metric(search_text)
    if not match:
        return {"measurable": False, "progress_reason": "no matching indicator in global_indicators"}

    dot_path, direction, label = match
    current_value = _get_indicator_value(dot_path, indicators)
    if current_value is None:
        return {
            "measurable":      False,
            "progress_reason": f"indicator '{dot_path}' has no data in global_indicators",
            "indicator_path":  dot_path,
            "indicator_label": label,
        }

    # First measurement → snapshot baseline; subsequent → reuse saved baseline
    saved_baseline = initiative.get("baseline_value")
    is_first       = saved_baseline is None
    baseline_value = current_value if is_first else float(saved_baseline)

    target_pct  = _extract_target_pct(initiative.get("milestone", ""))
    target_value: float | None = None
    progress_pct: float | None = None

    if target_pct is not None and baseline_value != 0:
        if direction == "lower":
            target_value = baseline_value * (1.0 - target_pct / 100.0)
            denom        = baseline_value - target_value
        else:
            target_value = baseline_value * (1.0 + target_pct / 100.0)
            denom        = target_value - baseline_value

        if denom != 0:
            if direction == "lower":
                raw = (baseline_value - current_value) / denom * 100.0
            else:
                raw = (current_value - baseline_value) / denom * 100.0
            progress_pct = round(max(0.0, min(100.0, raw)), 1)

    now_iso = datetime.now(timezone.utc).isoformat()
    result: dict = {
        "measurable":          True,
        "indicator_path":      dot_path,
        "indicator_label":     label,
        "indicator_direction": direction,
        "baseline_value":      round(baseline_value, 4),
        "current_value":       round(current_value, 4),
        "delta":               round(current_value - baseline_value, 4),
        "target_pct":          target_pct,
        "target_value":        round(target_value, 4) if target_value is not None else None,
        "current_progress":    progress_pct,
        "measured_at":         now_iso,
    }
    if is_first:
        result["baseline_snapshot_at"] = now_iso

    tag = f"{progress_pct}%" if progress_pct is not None else "no target %"
    print(f"  [PROGRESS] {init_id}: {label}  {baseline_value} -> {current_value}  ({tag})")

    # Generate causal explanation only when: first time, or delta changed meaningfully
    existing_explanation = initiative.get("progress_explanation")
    existing_delta       = initiative.get("delta", 0.0)
    delta_changed = abs((current_value - baseline_value) - existing_delta) > 1e-4
    needs_explanation = (existing_explanation is None) or delta_changed

    if needs_explanation:
        try:
            sys.path.insert(0, str(BASE))
            from hypothesis_generator import generate_causal_hypothesis
            causal = generate_causal_hypothesis(
                metric_label=label,
                indicator_path=dot_path,
                baseline_value=baseline_value,
                current_value=current_value,
                direction=direction,
                problem_context=initiative.get("problem", ""),
                target_pct=target_pct,
            )
            if causal.get("verification_status") != "REJECTED":
                result["progress_explanation"] = {
                    "hypothesis":      causal.get("hypothesis_text", ""),
                    "root_cause":      causal.get("root_cause", ""),
                    "suggested_action": causal.get("suggested_action", ""),
                    "expected_improvement": causal.get("expected_improvement", ""),
                    "evidence_strength": causal.get("evidence_strength", "unknown"),
                    "hypothesis_id":   causal.get("id", ""),
                    "generated_at":    causal.get("created_at", ""),
                    "verification_status": causal.get("verification_status", ""),
                }
        except Exception as e:
            print(f"  [PROGRESS] causal hypothesis failed: {e}")

    return result


def _update_progress_for_active(indicators: dict) -> None:
    """Measure and persist progress for every PROPOSED / IN_PROGRESS / OVERDUE initiative."""
    if not indicators or not INITIATIVES_DIR.exists():
        return
    for f in INITIATIVES_DIR.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if rec.get("status") not in ("PROPOSED", "IN_PROGRESS", "OVERDUE"):
            continue

        prog = _measure_progress(rec, indicators)

        if prog.get("measurable"):
            # Persist baseline only on first measurement
            if rec.get("baseline_value") is None:
                rec["baseline_value"]       = prog["baseline_value"]
                rec["baseline_snapshot_at"] = prog.get("baseline_snapshot_at", prog["measured_at"])
            rec["current_value"]      = prog["current_value"]
            rec["delta"]              = prog["delta"]
            rec["indicator_label"]    = prog["indicator_label"]
            rec["indicator_path"]     = prog["indicator_path"]
            rec["indicator_direction"]= prog["indicator_direction"]
            rec["target_pct"]         = prog["target_pct"]
            rec["target_value"]       = prog["target_value"]
            rec["current_progress"]   = prog["current_progress"]
            rec["measured_at"]        = prog["measured_at"]
            rec["updated_at"]         = prog["measured_at"]
            if "progress_explanation" in prog:
                rec["progress_explanation"] = prog["progress_explanation"]
        else:
            rec.setdefault("measurable",      False)
            rec.setdefault("progress_reason", prog.get("progress_reason", ""))

        f.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply_overdue_transitions() -> int:
    """
    Scan all PROPOSED initiatives whose target_date has passed and mark them OVERDUE.
    Returns the number of initiatives transitioned.
    """
    if not INITIATIVES_DIR.exists():
        return 0
    today = datetime.now(timezone.utc).date()
    transitioned = 0
    for f in INITIATIVES_DIR.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if rec.get("status") != "PROPOSED":
            continue
        td = rec.get("target_date", "")
        if not td:
            continue
        try:
            if datetime.strptime(td, "%Y-%m-%d").date() < today:
                rec["status"]       = "OVERDUE"
                rec["overdue_since"] = today.isoformat()
                rec["updated_at"]   = datetime.now(timezone.utc).isoformat()
                f.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
                transitioned += 1
                print(f"[INITIATIVE_TRACKER] ⚠ OVERDUE: {rec['id']}  ({td})")
        except ValueError:
            continue
    return transitioned


def advance_status(init_id: str, new_status: str) -> bool:
    """
    Manually advance an initiative to new_status.
    Enforces _ALLOWED_TRANSITIONS; returns True on success.
    """
    init_path = INITIATIVES_DIR / f"{init_id}.json"
    if not init_path.exists():
        print(f"[INITIATIVE_TRACKER] Не намерена инициатива: {init_id}")
        return False
    try:
        rec = json.loads(init_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[INITIATIVE_TRACKER] Грешка при четене: {e}")
        return False

    current = rec.get("status", "")
    new_status = new_status.upper()
    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        print(
            f"[INITIATIVE_TRACKER] Невалиден преход: {current} → {new_status}\n"
            f"  Позволени от {current}: {', '.join(sorted(allowed)) or 'няма'}"
        )
        return False

    rec["status"]     = new_status
    rec["updated_at"] = datetime.now(timezone.utc).isoformat()
    if new_status == "IN_PROGRESS" and not rec.get("started_at"):
        rec["started_at"] = rec["updated_at"]
    elif new_status == "DONE":
        rec["completed_at"] = rec["updated_at"]
    elif new_status == "CANCELLED":
        rec["cancelled_at"] = rec["updated_at"]

    init_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INITIATIVE_TRACKER] ✓ {init_id}: {current} → {new_status}")
    return True


def run() -> list[dict]:
    """
    Process improvement_proposals.json:
      - skip code-patch proposals
      - create data/initiatives/{id}.json with status=PROPOSED (or preserve IN_PROGRESS/DONE)
    Returns the current list of PROPOSED + IN_PROGRESS initiatives.
    """
    INITIATIVES_DIR.mkdir(parents=True, exist_ok=True)

    overdue_count = _apply_overdue_transitions()
    if overdue_count:
        print(f"[INITIATIVE_TRACKER] {overdue_count} инициатив(и) маркирани като OVERDUE")

    try:
        raw       = json.loads(PROPOSALS_PATH.read_text(encoding="utf-8"))
        proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
    except Exception as e:
        print(f"[INITIATIVE_TRACKER] proposals load failed: {e}")
        return []

    now     = datetime.now(timezone.utc)
    created = updated = skipped = 0

    for proposal in proposals:
        if _is_code_action(proposal):
            skipped += 1
            continue

        init_id   = _proposal_id(proposal)
        init_path = INITIATIVES_DIR / f"{init_id}.json"

        existing_created_at = now.isoformat()

        is_new = not init_path.exists()
        if not is_new:
            try:
                existing = json.loads(init_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
            existing_created_at = existing.get("created_at", now.isoformat())
            existing_action_plan = existing.get("action_plan", [])
            if existing.get("status") not in ("PROPOSED",):
                # Preserve IN_PROGRESS / DONE / CANCELLED — don't overwrite
                continue
            updated += 1
        else:
            existing_action_plan = []
            created += 1

        goal_text   = f"{proposal.get('measurable_goal', '')} {proposal.get('solution', '')}"
        months      = _extract_months(goal_text)
        target_date = (now + timedelta(days=months * 30.44)).strftime("%Y-%m-%d")
        milestone   = (proposal.get("measurable_goal") or proposal.get("solution", ""))[:120]

        # Generate action_plan only for brand-new initiatives (avoid re-generating on each update)
        if is_new:
            print(f"[INITIATIVE_TRACKER] Генерирам action_plan за {init_id}…")
            action_plan = _generate_action_plan(
                problem=proposal.get("problem", ""),
                solution=proposal.get("solution", ""),
                target_date=target_date,
            )
            if action_plan:
                print(f"[INITIATIVE_TRACKER]   → {len(action_plan)} стъпки генерирани ✓")
            else:
                print(f"[INITIATIVE_TRACKER]   → action_plan празен (LLM грешка или недостъпен)")
        else:
            action_plan = existing_action_plan

        record: dict = {
            "id":                 init_id,
            "status":             "PROPOSED",
            "priority":           proposal.get("priority", "MEDIUM"),
            "component":          proposal.get("component", "unknown"),
            "agi_characteristic": proposal.get("agi_characteristic", ""),
            "problem":            proposal.get("problem", ""),
            "solution":           proposal.get("solution", ""),
            "milestone":          milestone,
            "target_date":        target_date,
            "action_plan":        action_plan,
            "source":             proposal.get("source") or proposal.get("generated_by", "unknown"),
            "created_at":         existing_created_at if not is_new else now.isoformat(),
            "updated_at":         now.isoformat(),
            "proposal_timestamp": proposal.get("timestamp", ""),
        }

        init_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[INITIATIVE_TRACKER] created={created} updated={updated} skipped_code={skipped}")

    # Measure progress for all active initiatives against global_indicators
    indicators = _load_indicators()
    if indicators:
        _update_progress_for_active(indicators)
    else:
        print("[INITIATIVE_TRACKER] global_indicators недостъпни — progress пропуснат")

    return load_active()


def load_active() -> list[dict]:
    """Return PROPOSED, OVERDUE, and IN_PROGRESS initiatives sorted by priority then target_date."""
    if not INITIATIVES_DIR.exists():
        return []
    active: list[dict] = []
    for f in INITIATIVES_DIR.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            if rec.get("status") in ("PROPOSED", "IN_PROGRESS", "OVERDUE"):
                active.append(rec)
        except Exception:
            pass
    return sorted(
        active,
        key=lambda r: (_PRIORITY_ORDER.get(r.get("priority", "LOW"), 9), r.get("target_date", "")),
    )


def load_all() -> list[dict]:
    """Return every initiative regardless of status."""
    if not INITIATIVES_DIR.exists():
        return []
    recs: list[dict] = []
    for f in INITIATIVES_DIR.glob("*.json"):
        try:
            recs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return sorted(recs, key=lambda r: r.get("updated_at", ""), reverse=True)


def _print_table(initiatives: list[dict]) -> None:
    _STATUS_COLOR = {
        "PROPOSED":    "",
        "IN_PROGRESS": "",
        "OVERDUE":     "(!)",
        "DONE":        "(✓)",
        "CANCELLED":   "(x)",
    }
    for rec in initiatives:
        status  = rec.get("status", "?")
        marker  = _STATUS_COLOR.get(status, "")
        line = (
            f"  {marker}[{status:11s}] [{rec.get('priority','?'):6s}]"
            f"  {rec['id']}  {rec.get('milestone','')[:60]:<60}"
            f"  -> {rec.get('target_date','?')}"
        )
        print(line)


if __name__ == "__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="initiative_tracker.py",
        description="CORTEX++ Initiative Tracker",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="Процесирай proposals и провери OVERDUE (default)")
    sub.add_parser("list", help="Покажи активни инициативи (PROPOSED / IN_PROGRESS / OVERDUE)")
    sub.add_parser("list-all", help="Покажи всички инициативи включително DONE / CANCELLED")

    adv = sub.add_parser("advance", help="Ръчно смени статус: advance <id> <NEW_STATUS>")
    adv.add_argument("id",     help="Initiative ID (напр. init_bd91e92297)")
    adv.add_argument("status", help=f"Нов статус. Позволени преходи: {_ALLOWED_TRANSITIONS}")

    args = parser.parse_args()

    if args.cmd == "advance":
        INITIATIVES_DIR.mkdir(parents=True, exist_ok=True)
        advance_status(args.id, args.status)

    elif args.cmd == "list":
        items = load_active()
        print(f"\nАктивни инициативи ({len(items)}):")
        _print_table(items)

    elif args.cmd == "list-all":
        items = load_all()
        print(f"\nВсички инициативи ({len(items)}):")
        _print_table(items)

    else:
        # default: run
        initiatives = run()
        print(f"\nАктивни: {len(initiatives)}")
        _print_table(initiatives)
