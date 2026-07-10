#!/usr/bin/env python3
"""
safety/quarantine.py
Quarantine за rejected/rolled-back self-modifier patches.

Философия: системата НИКОГА не трие patch код — само човек изпразва
quarantine (виж scripts/review_quarantine.py). Всеки quarantine-нат
patch получава JSON sidecar със timestamp, deny reason, пълния verdict
(AST gate или PatchGuardian) и source proposal-а, ако е наличен.

Два режима:
  - source_path: файлът вече съществува на диска (напр. execute_patches.py
    или PatchGuardian откриват проблем СЛЕД като self_modifier го е
    записал) — премества се.
  - content: patch-ът никога не е бил записван на живо място (self_modifier
    AST gate спира ПРЕДИ write) — записва се директно в quarantine.
"""

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path


def quarantine(
    *,
    base_dir: Path,
    filename: str,
    reason: str,
    verdict: dict,
    content: str | None = None,
    source_path: Path | None = None,
    source_proposal: dict | None = None,
) -> Path | None:
    """
    Премества/записва rejected patch в <base_dir>/patches/quarantine/ и пише
    JSON sidecar до него. Връща новия .py path, или None ако няма какво да
    се quarantine-не (нито source_path съществува, нито е подадено content).
    """
    quarantine_dir = Path(base_dir) / "patches" / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".py"

    ts = int(time.time())
    dest = quarantine_dir / f"{stem}.{ts}{suffix}"
    n = 0
    while dest.exists():
        n += 1
        dest = quarantine_dir / f"{stem}.{ts}.{n}{suffix}"

    if source_path is not None and Path(source_path).exists():
        shutil.move(str(source_path), str(dest))
    elif content is not None:
        dest.write_text(content, encoding="utf-8")
    else:
        return None

    sidecar = dest.parent / f"{dest.name}.json"
    sidecar.write_text(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "original_filename": filename,
                "quarantined_path": str(dest.relative_to(Path(base_dir))).replace("\\", "/"),
                "deny_reason": reason,
                "verdict": verdict,
                "source_proposal": source_proposal,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    _log_quarantine_event(base_dir, dest, filename, reason, verdict, source_proposal)

    return dest


def _log_quarantine_event(
    base_dir: Path,
    dest: Path,
    filename: str,
    reason: str,
    verdict: dict,
    source_proposal: dict | None,
) -> None:
    """
    Добавя quarantine събитие в memory/development_journal.json[today]
    ["quarantine_events"] — огледално на как execute_patches.py логва
    patch_executions в същия journal. fast_cycle_runner.py (стъпка 24)
    чете и двете и ги подава заедно на MerkleMemory().commit(), така че
    quarantine събитията влизат в архивираната Merkle памет на цикъла,
    не само в patches/quarantine/.

    Best-effort — грешка тук никога не пречи на самото quarantine-ване.
    """
    journal_path = Path(base_dir) / "memory" / "development_journal.json"
    try:
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except Exception:
            journal = {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        journal.setdefault(today, {}).setdefault("quarantine_events", []).append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "quarantine",
            "original_filename": filename,
            "quarantined_path": str(dest.relative_to(Path(base_dir))).replace("\\", "/"),
            "deny_reason": reason,
            "verdict_gate": verdict.get("gate"),
            "verdict_stage": verdict.get("stage"),
            "source_proposal_component": (source_proposal or {}).get("component"),
        })
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
