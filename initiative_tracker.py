#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
initiative_tracker.py
Reads improvement_proposals.json, keeps only civilizational/external proposals
(not code-patch-generating ones), and creates/updates data/initiatives/{id}.json
with status=PROPOSED, milestone, and target_date.
"""
from __future__ import annotations
import json, hashlib, pathlib, re
from datetime import datetime, timezone, timedelta

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


def run() -> list[dict]:
    """
    Process improvement_proposals.json:
      - skip code-patch proposals
      - create data/initiatives/{id}.json with status=PROPOSED (or preserve IN_PROGRESS/DONE)
    Returns the current list of PROPOSED + IN_PROGRESS initiatives.
    """
    INITIATIVES_DIR.mkdir(parents=True, exist_ok=True)

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

        if init_path.exists():
            try:
                existing = json.loads(init_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
            existing_created_at = existing.get("created_at", now.isoformat())
            if existing.get("status") not in ("PROPOSED",):
                # Preserve IN_PROGRESS / DONE / CANCELLED — don't overwrite
                continue
            updated += 1
        else:
            created += 1

        goal_text   = f"{proposal.get('measurable_goal', '')} {proposal.get('solution', '')}"
        months      = _extract_months(goal_text)
        target_date = (now + timedelta(days=months * 30.44)).strftime("%Y-%m-%d")
        milestone   = (proposal.get("measurable_goal") or proposal.get("solution", ""))[:120]

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
            "source":             proposal.get("source") or proposal.get("generated_by", "unknown"),
            "created_at":         existing_created_at,
            "updated_at":         now.isoformat(),
            "proposal_timestamp": proposal.get("timestamp", ""),
        }

        init_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[INITIATIVE_TRACKER] created={created} updated={updated} skipped_code={skipped}")
    return load_active()


def load_active() -> list[dict]:
    """Return all PROPOSED and IN_PROGRESS initiatives sorted by priority then target_date."""
    if not INITIATIVES_DIR.exists():
        return []
    active: list[dict] = []
    for f in INITIATIVES_DIR.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            if rec.get("status") in ("PROPOSED", "IN_PROGRESS"):
                active.append(rec)
        except Exception:
            pass
    return sorted(
        active,
        key=lambda r: (_PRIORITY_ORDER.get(r.get("priority", "LOW"), 9), r.get("target_date", "")),
    )


if __name__ == "__main__":
    initiatives = run()
    print(f"\nActive initiatives: {len(initiatives)}")
    for init in initiatives:
        line = (
            f"  [{init['status']:11s}] [{init['priority']:6s}]"
            f"  {init['milestone'][:70]:<70}  -> {init['target_date']}"
        )
        print(line.encode("ascii", errors="replace").decode("ascii"))
