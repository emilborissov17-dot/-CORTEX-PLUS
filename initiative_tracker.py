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

BASE            = pathlib.Path(__file__).resolve().parent
PROPOSALS_PATH  = BASE / "memory" / "improvement_proposals.json"
INITIATIVES_DIR = BASE / "data" / "initiatives"

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
