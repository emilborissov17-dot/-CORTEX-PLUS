#!/usr/bin/env python3
"""
agents/core/action_layer.py
Изпълнява improvement proposals от System 2.
Първо действие: генерира седмичен доклад като markdown.
"""
import json, pathlib
from datetime import datetime, timezone
from core.groq_backend import call_groq

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]

def execute_proposals():
    """Чете improvement_proposals и изпълнява HIGH приоритет."""

    proposals_path = BASE_DIR / "memory" / "improvement_proposals.json"
    levels_path    = BASE_DIR / "memory" / "auto_levels.json"
    system2_path   = BASE_DIR / "memory" / "system2_latest.json"
    sa_path        = BASE_DIR / "memory" / "self_awareness.json"

    try:
        proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
    except:
        proposals = []

    try:
        levels = json.loads(levels_path.read_text(encoding="utf-8"))
    except:
        levels = {}

    try:
        s2 = json.loads(system2_path.read_text(encoding="utf-8"))
    except:
        s2 = {}

    try:
        sa = json.loads(sa_path.read_text(encoding="utf-8"))
    except:
        sa = {}

    print("[ACTION] Изпълнявам действия от System 2...")
    print()

    # Действие 1: Генерирай седмичен цивилизационен доклад
    _generate_weekly_report(levels, s2, sa)

    # Действие 2: Запиши в development_journal
    _update_journal(levels, s2)

def _generate_weekly_report(levels, s2, sa):
    """Генерира markdown доклад за цивилизационното състояние."""

    print("[ACTION] Генерирам цивилизационен доклад...")

    critical = [a for a, d in levels.items() if d.get("level") == "LOW"]
    warning  = [a for a, d in levels.items() if d.get("level") == "MEDIUM"]
    good     = [a for a, d in levels.items() if d.get("level") == "HIGH"]

    causal  = s2.get("step3_causality", {}).get("causal_chain", "")
    summary = s2.get("step5_action", {}).get("summary_bulgarian", "")

    # Инжектирай миналото знание в prompt
    try:
        from memory.continuous_learner import before_llm_call
        memory_block = before_llm_call("CIVILIZATION_REPORT", "цивилизационен доклад критични оси")
    except Exception:
        memory_block = ""

    prompt = f"""{memory_block}Ти си CORTEX++ AGI. Генерирай кратък цивилизационен доклад на български.

РЕАЛНИ ДАННИ:
Критични оси (LOW): {critical}
Внимание (MEDIUM): {warning}
Добре (HIGH): {good}

Каузална верига: {causal}

Обобщение: {summary}

Напиши доклад в markdown формат:
# Цивилизационен Доклад — [дата]
## Критично
## Внимание
## Положително
## Препоръки

Максимум 400 думи. Само реални факти."""

    try:
        report = call_groq(prompt, max_tokens=600)

        reports_dir = BASE_DIR / "reports"
        reports_dir.mkdir(exist_ok=True)

        now = datetime.now(timezone.utc)
        filename = f"civilization_report_{now.strftime('%Y-%m-%d')}.md"
        report_path = reports_dir / filename
        report_path.write_text(report, encoding="utf-8")
        (reports_dir / "latest_report.md").write_text(report, encoding="utf-8")

        print(f"[ACTION] ✅ Доклад записан: {filename}")
        print()
        print("=== ДОКЛАД ===")
        print(report[:800])
        print("...")

        # Запиши в continuous learner
        try:
            from memory.continuous_learner import after_llm_call
            after_llm_call(
                axis="CIVILIZATION_REPORT",
                llm_output=report[:300],
                source="action_layer"
            )
        except Exception:
            pass

    except Exception as e:
        print(f"[ACTION] ❌ Грешка: {e}")

def _update_journal(levels, s2):
    """Обновява development journal с днешните данни."""
    journal_path = BASE_DIR / "memory" / "development_journal.json"
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except:
        journal = {}

    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    critical = [a for a, d in levels.items() if d.get("level") == "LOW"]
    causal   = s2.get("step3_causality", {}).get("causal_chain", "")
    summary  = s2.get("step5_action", {}).get("summary_bulgarian", "")

    journal[today] = {
        "axes_measured": len(levels),
        "critical": critical,
        "causal_chain": causal[:200],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ACTION] ✅ Journal обновен за {today}")

    # Запиши каузалната верига в causal_log
    try:
        from memory.context_injector import record_causal
        if causal:
            record_causal(
                action=f"system2_cycle_{today}",
                effect=summary[:200] if summary else f"Critical axes: {critical}",
                why=causal[:300],
                axis="CIVILIZATION"
            )
            print(f"[ACTION] ✅ Каузален запис добавен в causal_log")
    except Exception as e:
        print(f"[ACTION] ⚠️ record_causal грешка: {e}")

    # Запиши в continuous learner
    try:
        from memory.continuous_learner import after_llm_call
        insight = f"Критични оси: {critical} | Каузална верига: {causal[:150]}"
        after_llm_call(
            axis="CIVILIZATION",
            llm_output=insight,
            score=float(max(0, 100 - len(critical) * 15)),
            source="action_layer"
        )
    except Exception:
        pass

if __name__ == "__main__":
    execute_proposals()