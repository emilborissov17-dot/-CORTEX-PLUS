#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
predictor.py — CORTEX++_QWEN
Мисия: Анализира реалното състояние на планетата от snapshots,
идентифицира критични оси и генерира proposals за подобряване
на агентите — не за prediction accuracy.

Цикъл:
  1. Зарежда всички 28 snapshots
  2. Scoring на всяка ос (0-100)
  3. Идентифицира критични оси (score < 40)
  4. Генерира proposals за подобряване на агентите
  5. Записва в improvement_proposals.json
  6. Записва scores в output/cortex_scores_latest.json
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

SNAPSHOTS_DIR   = BASE / "snapshots"
OUTPUT_DIR      = BASE / "output"
PROPOSALS_FILE  = BASE / "memory" / "improvement_proposals.json"
SCORES_FILE     = OUTPUT_DIR / "cortex_scores_latest.json"
MEMORY_FILE     = BASE / "memory" / "predictor_memory.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

from core.groq_backend import call_groq


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: pathlib.Path) -> dict | list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 1. Зареждане на snapshots ─────────────────────────────────────────────────

def load_all_snapshots() -> dict:
    """Зарежда всички *_snapshot_latest.json файлове."""
    snapshots = {}
    for f in sorted(SNAPSHOTS_DIR.rglob("*_snapshot_latest.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            axis = data.get("axis") or f.stem.replace("_snapshot_latest", "").upper()
            snapshots[axis] = data
        except Exception:
            pass
    return snapshots


# ── 2. Scoring ────────────────────────────────────────────────────────────────

def score_snapshot(axis: str, snapshot: dict) -> float:
    """
    Извлича score от snapshot.
    Приоритет: score поле → normalize_score → LLM estimate.
    Връща 0-100.
    """
    # Директен score
    for key in ("score", "normalized_score", "composite_score", "axis_score"):
        val = snapshot.get(key)
        if val is not None:
            s = float(val)
            return round(s * 100 if s <= 1.0 else s, 1)

    # Score в metrics
    metrics = snapshot.get("metrics", {})
    if isinstance(metrics, dict):
        scores = []
        for v in metrics.values():
            if isinstance(v, (int, float)) and 0 <= v <= 100:
                scores.append(float(v))
            elif isinstance(v, (int, float)) and 0 <= v <= 1:
                scores.append(float(v) * 100)
        if scores:
            return round(sum(scores) / len(scores), 1)

    # Level → score
    level = snapshot.get("level", snapshot.get("status", ""))
    level_map = {"HIGH": 75.0, "GOOD": 75.0, "MEDIUM": 50.0, "LOW": 25.0, "CRITICAL": 10.0}
    if level.upper() in level_map:
        return level_map[level.upper()]

    return 50.0  # default


def score_all(snapshots: dict) -> dict:
    """Връща {axis: {"score": float, "level": str, "timestamp": str}}"""
    scores = {}
    for axis, snap in snapshots.items():
        s = score_snapshot(axis, snap)
        if s >= 67:
            level = "HIGH"
        elif s >= 34:
            level = "MEDIUM"
        else:
            level = "LOW"
        scores[axis] = {
            "score": round(s / 100, 3),  # 0.0-1.0 за съвместимост
            "score_100": s,              # 0-100 за четимост
            "level": level,
            "timestamp": _utc_now(),
        }
    return scores


# ── 3. Идентификация на критични оси ─────────────────────────────────────────

def find_critical_axes(scores: dict, threshold: float = 40.0) -> list[dict]:
    """Връща списък с критични оси (score_100 < threshold), сортирани по score."""
    critical = []
    for axis, data in scores.items():
        s = data["score_100"]
        if s < threshold:
            critical.append({"axis": axis, "score": s, "level": data["level"]})
    return sorted(critical, key=lambda x: x["score"])


# ── 4. Генериране на proposals за агентите ────────────────────────────────────

def generate_agent_proposal(axis: str, score: float, snapshot: dict) -> dict | None:
    """
    Генерира proposal за подобряване на агента/data provider-а за тази ос.
    Целта: по-добър анализ, не по-точно предсказание.
    """
    # Извличаме контекст от snapshot
    summary = snapshot.get("summary", snapshot.get("analysis", ""))[:300]
    data_sources = snapshot.get("data_sources", snapshot.get("sources", []))
    missing = snapshot.get("missing_data", snapshot.get("gaps", []))

    prompt = f"""Ти си CORTEX++ — AGI система за мониторинг на планетата.

ОС: {axis}
SCORE: {score}/100 — КРИТИЧНО НИСКО
ТЕКУЩ АНАЛИЗ: {summary}
ДАННИ: {data_sources}
ЛИПСВАЩИ ДАННИ: {missing}

ЗАДАЧА: Генерирай конкретно предложение за подобряване на агента/data provider-а
за тази ос, така че анализът да стане по-точен и полезен за човечеството.

НЕ предлагай prediction improvements. Предлагай:
- Нови реални data sources (API-та, бази данни)
- По-добри метрики за измерване
- По-добри агентни стратегии
- Конкретен Python код за подобрение

Отговори САМО с валиден JSON без markdown:
{{
  "component": "{axis.lower()}",
  "problem": "конкретен проблем с текущия анализ (1 изречение)",
  "solution": "конкретно решение за подобряване на агента (1 изречение)",
  "new_data_sources": ["url или API"],
  "priority": "HIGH",
  "target_file": "data_providers/planet/{axis.lower()}_provider.py",
  "python_code": "#!/usr/bin/env python3\\n# Patch за {axis}\\nprint('Patch applied')"
}}"""

    try:
        raw = call_groq(prompt, max_tokens=600)
        # Изчисти markdown
        for fence in ("```json", "```"):
            if fence in raw:
                raw = raw.split(fence)[1].split("```")[0]
        proposal = json.loads(raw.strip())
        proposal["approved"] = True
        proposal["rejected"] = False
        proposal["generated_by"] = "PREDICTOR_MISSION_ALIGNED"
        proposal["axis_score"] = score
        proposal["timestamp"] = _utc_now()
        return proposal
    except Exception as e:
        print(f"  [PREDICTOR] Грешка при генериране за {axis}: {e}")
        return None


# ── 5. Запис на proposals ─────────────────────────────────────────────────────

def save_proposals(new_proposals: list) -> int:
    """Добавя нови proposals, пропуска дублирани."""
    try:
        data = _load_json(PROPOSALS_FILE)
        existing = data.get("proposals", []) if isinstance(data, dict) else []
    except Exception:
        existing = []

    existing_problems = {p.get("problem", "") for p in existing}
    added = 0
    for p in new_proposals:
        if p and p.get("problem") not in existing_problems:
            existing.append(p)
            existing_problems.add(p["problem"])
            added += 1

    _save_json(PROPOSALS_FILE, {
        "proposals": existing,
        "last_updated": _utc_now(),
        "total": len(existing),
    })
    return added


# ── 6. Civilization summary ───────────────────────────────────────────────────

def generate_civilization_summary(scores: dict, critical: list) -> str:
    """Генерира кратко резюме на състоянието на цивилизацията."""
    high   = [a for a, d in scores.items() if d["level"] == "HIGH"]
    medium = [a for a, d in scores.items() if d["level"] == "MEDIUM"]
    low    = [a for a, d in scores.items() if d["level"] == "LOW"]

    avg = round(sum(d["score_100"] for d in scores.values()) / len(scores), 1) if scores else 0

    prompt = f"""CORTEX++ — Глобален статус на планетата.

СРЕДНА ОЦЕНКА: {avg}/100
ДОБРИ оси ({len(high)}): {high[:5]}
СРЕДНИ оси ({len(medium)}): {medium[:5]}
КРИТИЧНИ оси ({len(low)}): {[c['axis'] for c in critical]}

Напиши 3-4 изречения резюме на текущото състояние на планетата и цивилизацията.
Бъди конкретен, честен и ориентиран към действие. На български."""

    try:
        return call_groq(prompt, max_tokens=300)
    except Exception:
        return f"Средна оценка: {avg}/100. Критични оси: {len(low)}."


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> dict:
    print("\n[PREDICTOR] ═══════════════════════════════════════")
    print("[PREDICTOR] CORTEX++ — АНАЛИЗ НА РЕАЛНОТО СЪСТОЯНИЕ")
    print("[PREDICTOR] ═══════════════════════════════════════\n")

    # 1. Зареждане
    print("[PREDICTOR] Зареждам snapshots...")
    snapshots = load_all_snapshots()
    print(f"[PREDICTOR] {len(snapshots)} snapshots заредени\n")

    if not snapshots:
        print("[PREDICTOR] ⚠️  Няма snapshots — пусни hypercortex_runner.py първо!")
        return {}

    # 2. Scoring
    print("[PREDICTOR] Изчислявам scores...")
    scores = score_all(snapshots)
    _save_json(SCORES_FILE, scores)
    print(f"[PREDICTOR] Scores записани -> {SCORES_FILE}\n")

    # 3. Критични оси
    critical = find_critical_axes(scores, threshold=40.0)
    print(f"[PREDICTOR] Критични оси (score < 40): {len(critical)}")
    for c in critical:
        print(f"  ❌ {c['axis']}: {c['score']}/100")

    medium = [a for a, d in scores.items() if d["level"] == "MEDIUM"]
    high   = [a for a, d in scores.items() if d["level"] == "HIGH"]
    print(f"[PREDICTOR] Средни: {len(medium)} | Добри: {len(high)}\n")

    # 4. Proposals за критични оси
    new_proposals = []
    if critical:
        print("[PREDICTOR] Генерирам proposals за критични оси...")
        for c in critical[:3]:  # max 3 за да не hit-ваме rate limit
            axis = c["axis"]
            snap = snapshots.get(axis, {})
            print(f"  -> {axis} ({c['score']}/100)...")
            proposal = generate_agent_proposal(axis, c["score"], snap)
            if proposal:
                new_proposals.append(proposal)
                print(f"     ✅ Proposal: {proposal.get('problem','')[:70]}")
            else:
                print(f"     ⚠️  Пропуснат")
        print()

    # 5. Запис
    added = save_proposals(new_proposals)
    print(f"[PREDICTOR] {added} нови proposals записани\n")

    # 6. Summary
    print("[PREDICTOR] Генерирам цивилизационно резюме...")
    summary = generate_civilization_summary(scores, critical)
    print("\n" + "=" * 55)
    print("ГЛОБАЛЕН СТАТУС:")
    print("=" * 55)
    print(summary)
    print("=" * 55)

    # Запис в memory
    avg_score = round(sum(d["score_100"] for d in scores.values()) / len(scores), 1)
    memory = {
        "last_run": _utc_now(),
        "axes_count": len(scores),
        "avg_score": avg_score,
        "critical_count": len(critical),
        "critical_axes": [c["axis"] for c in critical],
        "proposals_added": added,
        "summary": summary[:500],
    }
    _save_json(MEMORY_FILE, memory)

    print(f"\n[PREDICTOR] Средна оценка на планетата: {avg_score}/100")
    print(f"[PREDICTOR] done at {_utc_now()}")
    print("[PREDICTOR] ═══════════════════════════════════════\n")

    return scores


if __name__ == "__main__":
    run()