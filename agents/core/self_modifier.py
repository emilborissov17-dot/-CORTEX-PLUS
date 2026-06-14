#!/usr/bin/env python3
"""
agents/core/self_modifier.py
REDESIGN: Генерира patches за решаване на РЕАЛНИ ПРОБЛЕМИ.
НЕ chase-ва score — решава конкретни проблеми с measurable_goal.
"""
import json, pathlib, subprocess, sys, tempfile, os
from datetime import datetime, timezone
from core.groq_backend import call_groq
from alignment.civilization_guard import evaluate_proposal_alignment

try:
    from memory.runtime_telemetry import record_experience as _rec
except Exception:
    _rec = lambda *a, **k: None

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]

AVAILABLE_MODULES = """
Налични модули в системата:
- memory.body_scan: full_scan(), find_in_self()
- memory.existence_model: am_i_alive()
- memory.semantic_memory: remember(), query()
- core.groq_backend: call_groq()
- json, pathlib, datetime, os, sys — стандартни

НЕ използвай: SemanticMemory клас, pandas, sklearn, requests, urllib
BASE_DIR: pathlib.Path(os.environ["CORTEX_BASE"])
Пиши standalone patch — само стандартни библиотеки + горните модули.
"""

# Patterns забранени в генерирания patch код
FORBIDDEN_PATTERNS = [
    "requests.get",
    "requests.post",
    "urllib.request",
    "urllib.urlopen",
    "http://",
    "https://",
    "fetch_data(",
    "SemanticMemory(",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "open_government",
    "world_bank",
    "noaa",
    "curl",
]

# Keyword → component mapping за auto-detection
COMPONENT_KEYWORDS = [
    ("climate",     "climate"),
    ("governance",  "governance"),
    ("institution", "governance"),
    ("government",  "governance"),
    ("energy",      "energy"),
    ("social",      "social"),
    ("economy",     "economy"),
    ("economic",    "economy"),
    ("inequality",  "inequality"),
    ("poverty",     "inequality"),
    ("technology",  "technology"),
    ("health",      "health"),
    ("education",   "education"),
    ("environment", "environment"),
    ("security",    "security"),
]

_BASE_INJECT = '''\
import os, pathlib, sys
BASE_DIR = pathlib.Path(os.environ.get("CORTEX_BASE", ".")).resolve()
sys.path.insert(0, str(BASE_DIR))
'''

_SAFE_FILE_TEMPLATE = '''\
def _safe_load(path, default):
    """Зарежда JSON файл, създава го с default ако не съществува."""
    p = pathlib.Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(default, ensure_ascii=False), encoding="utf-8")
    return json.loads(p.read_text(encoding="utf-8"))

def _safe_save(path, data):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
'''


# -- Helpers ------------------------------------------------------------------

def _detect_component(component: str, problem: str) -> str:
    """Ако component е 'unknown', извлича го от текста на проблема."""
    if component and component != "unknown":
        return component
    problem_lower = problem.lower()
    for keyword, comp in COMPONENT_KEYWORDS:
        if keyword in problem_lower:
            return comp
    return "general"


def _read_avg_score() -> float | None:
    """Само за tracking — не е цел."""
    try:
        levels    = json.loads((BASE_DIR / "memory" / "auto_levels.json").read_text(encoding="utf-8"))
        level_map = {"HIGH": 85.0, "MEDIUM": 55.0, "LOW": 25.0}
        scores    = [level_map[v.get("level")] for v in levels.values()
                     if isinstance(v, dict) and v.get("level") in level_map]
        return round(sum(scores) / len(scores), 2) if scores else None
    except Exception:
        return None


def _problem_already_attempted(problem: str, journal_path: pathlib.Path) -> bool:
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        mods    = journal.get(today, {}).get("auto_modifications", [])
        failed_today = [m["problem"][:80] for m in mods if m.get("action") == "FAILED"]
        return problem[:80] in failed_today
    except Exception:
        return False


def _check_forbidden_patterns(code: str) -> tuple[bool, str]:
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in code:
            return False, f"Забранен pattern: '{pattern}'"
    return True, "OK"


# -- Main --------------------------------------------------------------------

def run():
    proposals_path = BASE_DIR / "memory" / "improvement_proposals.json"
    journal_path   = BASE_DIR / "memory" / "development_journal.json"
    levels_path    = BASE_DIR / "memory" / "auto_levels.json"
    sa_path        = BASE_DIR / "memory" / "self_awareness.json"

    try:
        raw       = json.loads(proposals_path.read_text(encoding="utf-8"))
        proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
    except Exception:
        proposals = []

    try:
        sa = json.loads(sa_path.read_text(encoding="utf-8"))
    except Exception:
        sa = {}

    try:
        levels = json.loads(levels_path.read_text(encoding="utf-8"))
    except Exception:
        levels = {}

    print("[SELF_MODIFIER] ═══════════════════════════════")
    print("[SELF_MODIFIER] РЕШАВАНЕ НА РЕАЛНИ ПРОБЛЕМИ")
    print("[SELF_MODIFIER] ═══════════════════════════════")

    high = [p for p in proposals if isinstance(p, dict) and p.get("priority") == "HIGH"]
    high.sort(key=lambda p: (not p.get("real_world_signal", False), p.get("problem", "")))
    print(f"  HIGH proposals: {len(high)} (real_world: {sum(1 for p in high if p.get('real_world_signal'))})")
    print()

    executed, failed = [], []

    for proposal in high[:5]:
        component  = proposal.get("component", "unknown")
        problem    = proposal.get("problem", "")
        solution   = proposal.get("solution", "")
        measurable = proposal.get("measurable_goal", "")
        root_cause = proposal.get("root_cause", "")
        real_world = proposal.get("real_world_signal", False)

        component = _detect_component(component, problem)

        print(f"[SELF_MODIFIER] Проблем: {problem[:70]}")
        print(f"  Component: {component}")
        if measurable:
            print(f"  Measurable goal: {measurable[:60]}")

        if _problem_already_attempted(problem, journal_path):
            print(f"  [SKIP] Вече опитан днес — пропускам")
            continue

        guard = evaluate_proposal_alignment(proposal)
        if not guard["allowed"]:
            print(f"  [GUARD] ❌ Блокиран: {guard['notes']}")
            failed.append({"problem": problem[:100], "reason": f"GUARD: {guard['notes']}"})
            continue
        print(f"  [GUARD] ✅ Одобрен (risk={guard['risk_score']})")

        score_before = _read_avg_score()

        ready_code = proposal.get("python_code", "")
        if ready_code and len(ready_code) > 50:
            target = f"agents/core/{component.lower()}_patch.py"
            print(f"  Използвам python_code от proposal -> {target}")
            result = _write_python(target, ready_code)
        else:
            context = _build_context(sa, levels, component, problem)
            result  = _generate_solution(problem, solution, root_cause, measurable, component, context)

        score_after = _read_avg_score()

        if result["success"]:
            executed.append({
                "problem":         problem[:100],
                "action":          result["action"],
                "measurable_goal": measurable[:100],
                "real_world":      real_world,
                "code_written":    result.get("code_written", False),
                "score_before":    score_before,
                "score_after":     score_after,
            })
            _rec("SUCCESS", {"message": result["action"], "problem": problem[:60]})
            delta_str = f" | Δscore: {score_before}→{score_after}" if score_before else ""
            print(f"  SUCCESS: {result['action']}{delta_str}")

            try:
                from memory.context_injector import record_causal
                record_causal(
                    action       = f"self_modifier:{result['action'][:100]}",
                    effect       = f"patch написан за: {problem[:100]}",
                    why          = f"{root_cause[:150]} | Решение: {solution[:150]}",
                    axis         = component.upper(),
                    score_before = score_before,
                    score_after  = score_after,
                )
            except Exception as e:
                print(f"  [CAUSAL] грешка: {e}")
        else:
            failed.append({"problem": problem[:100], "reason": result.get("reason", "?")})
            _rec("ERROR", {"message": result.get("reason", "?"), "problem": problem[:60]})
            print(f"  FAILED: {result.get('reason', '?')}")
        print()

    _log_journal(journal_path, executed, failed)
    print(f"[SELF_MODIFIER] Изпълнени: {len(executed)} | Неуспешни: {len(failed)}")
    for e in executed:
        print(f"  → {e['action']} | goal: {e.get('measurable_goal', '')[:50]}")


def _build_context(sa, levels, component, problem):
    web_intel_axes = {}
    try:
        wi_path = BASE_DIR / "memory" / "web_intelligence" / "latest.json"
        if wi_path.exists():
            wi_data = json.loads(wi_path.read_text(encoding="utf-8"))
            web_intel_axes = wi_data.get("axes", {})
    except Exception:
        pass

    relevant_axis_data = ""
    for axis, data in web_intel_axes.items():
        if component.lower() in axis.lower() or any(
            kw in problem.lower() for kw in axis.lower().split("_")[:2]
        ):
            relevant_axis_data = json.dumps(data.get("analysis", {}), ensure_ascii=False)[:500]
            break

    real_code = ""
    possible_files = [
        BASE_DIR / "data_providers" / "civilization" / f"{component.lower()}_provider.py",
        BASE_DIR / "data_providers" / "planet" / f"{component.lower()}_provider.py",
        BASE_DIR / "agents" / "core" / f"{component.lower()}.py",
    ]
    for pf in possible_files:
        if pf.exists():
            real_code = pf.read_text(encoding="utf-8")[:1500]
            break

    return (
        f"BASE_DIR: {BASE_DIR}\n"
        f"Реални данни за проблема:\n{relevant_axis_data}\n"
        f"{AVAILABLE_MODULES}\n"
        f"Код на {component}:\n{real_code or 'Не е намерен'}"
    )


def _generate_solution(problem, solution, root_cause, measurable_goal, component, context):
    memory_block = ""
    try:
        from memory.continuous_learner import before_llm_call
        memory_block = before_llm_call(
            axis=component.upper(),
            question=problem,
        )
    except Exception as e:
        print(f"  [MEMORY] before_llm_call грешка: {e}")

    forbidden_str = ", ".join(f"'{p}'" for p in FORBIDDEN_PATTERNS)

    prompt = (
        f"{memory_block}\n\n" if memory_block else ""
    ) + (
        f"Ти си CORTEX++ self-modifier. Трябва да РЕШИШ реален проблем.\n\n"
        f"ПРОБЛЕМ: {problem}\n"
        f"ROOT CAUSE: {root_cause}\n"
        f"РЕШЕНИЕ: {solution}\n"
        f"MEASURABLE GOAL: {measurable_goal}\n\n"
        f"КОД НА СИСТЕМАТА:\n{context[:2000]}\n\n"
        f"{AVAILABLE_MODULES}\n\n"
        "Напиши Python patch който:\n"
        "1. Адресира ROOT CAUSE на проблема\n"
        "2. Имплементира РЕШЕНИЕТО\n"
        "3. Принтира нещо measurable (за да можем да проверим дали е сработило)\n\n"
        "СТРОГО ЗАБРАНЕНО — кодът ти ще бъде отхвърлен ако съдържа:\n"
        f"  {forbidden_str}\n"
        "ПОЗВОЛЕНО: json, pathlib, os, datetime, sys — само локални файлове в memory/\n"
        "НЕ правиш HTTP заявки. НЕ използваш external APIs. НЕ използваш subprocess.\n\n"
        "КРИТИЧНО — РАБОТА С ФАЙЛОВЕ:\n"
        "НИКОГА не приемай че файл съществува. ВИНАГИ проверявай:\n"
        "  if not file_path.exists():\n"
        "      file_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "      file_path.write_text(json.dumps({'data': []}, ensure_ascii=False))\n"
        "Използвай тази _safe_load helper функция в кода си:\n"
        f"{_SAFE_FILE_TEMPLATE}\n\n"
        "Само чист Python код. Без обяснение. Без markdown.\n"
        "Първи ред: #!/usr/bin/env python3\n"
        "BASE_DIR = pathlib.Path(os.environ['CORTEX_BASE'])\n"
        "НЕ използвай __file__ за пътища."
    )

    try:
        raw = call_groq(prompt, max_tokens=1000)

        if not raw or len(raw.strip()) < 10:
            return {"success": False, "reason": "Groq върна празен отговор"}

        try:
            err_check = json.loads(raw)
            if "error" in err_check:
                return {"success": False, "reason": f"Groq API грешка: {str(err_check['error'])[:100]}"}
        except (json.JSONDecodeError, TypeError):
            pass

        if "```python" in raw:
            raw = raw.split("```python")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]
        raw = raw.strip()

        if not raw.startswith(("#", "import", "from")):
            print(f"  [WARN] Отговорът не изглежда като код: {raw[:80]}")

        target = f"agents/core/{component.lower()}_patch.py"
        print(f"  Groq: WRITE_PYTHON -> {target}")
        return _write_python(target, raw)

    except Exception as e:
        return {"success": False, "reason": f"Groq грешка: {str(e)[:120]}"}


def _inject_base(content: str) -> str:
    lines     = content.splitlines(keepends=True)
    insert_at = 1 if (lines and lines[0].startswith("#!")) else 0
    return "".join(lines[:insert_at]) + _BASE_INJECT + "".join(lines[insert_at:])


def _write_python(target_file, content):
    try:
        allowed = ["memory/", "agents/core/", "data_providers/", "alignment/", "core/"]
        if not any(target_file.startswith(a) for a in allowed):
            return {"success": False, "reason": f"Не е позволено: {target_file}"}

        is_safe, reason = _check_forbidden_patterns(content)
        if not is_safe:
            print(f"  [PATTERN_GUARD] ❌ {reason}")
            return {"success": False, "reason": f"Pattern guard: {reason}"}
        print(f"  [PATTERN_GUARD] ✅ Код е чист")

        content_injected = _inject_base(content)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(content_injected)
            tmp_path = tmp.name

        env = {**os.environ, "PYTHONPATH": str(BASE_DIR), "CORTEX_BASE": str(BASE_DIR)}

        check = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open(r'{tmp_path}').read()); print('OK')"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        if "OK" not in check.stdout:
            pathlib.Path(tmp_path).unlink(missing_ok=True)
            return {"success": False, "reason": f"Синтаксис: {check.stderr[:80]}"}

        run_check = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=15, env=env,
        )
        pathlib.Path(tmp_path).unlink(missing_ok=True)

        if run_check.returncode != 0:
            # Debug: покажи първите редове на кода и грешката
            code_preview = "\n".join(content.splitlines()[:15])
            print(f"  [DEBUG] Код (първи 15 реда):\n{code_preview}")
            return {"success": False, "reason": f"Runtime грешка: {(run_check.stderr or '')[:300]}"}

        target = BASE_DIR / target_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"success": True, "action": f"Код написан: {target_file}", "code_written": True}

    except Exception as e:
        return {"success": False, "reason": str(e)[:100]}


def _log_journal(journal_path, executed, failed):
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except Exception:
        journal = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    journal.setdefault(today, {}).setdefault("auto_modifications", [])

    for e in executed:
        delta = None
        if e.get("score_before") is not None and e.get("score_after") is not None:
            delta = round(e["score_after"] - e["score_before"], 2)
        journal[today]["auto_modifications"].append({
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "action":         e["action"],
            "problem_solved": e["problem"],
            "measurable_goal": e.get("measurable_goal", ""),
            "real_world":     e.get("real_world", False),
            "code_written":   e.get("code_written", False),
            "score_before":   e.get("score_before"),
            "score_after":    e.get("score_after"),
            "delta":          delta,
            "executed_by":    "SELF_MODIFIER_AUTONOMOUS",
        })
    for f in failed:
        journal[today]["auto_modifications"].append({
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "action":      "FAILED",
            "problem":     f["problem"],
            "reason":      f["reason"],
            "executed_by": "SELF_MODIFIER_AUTONOMOUS",
        })

    journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        from memory.continuous_learner import learn_from_cycle
        learn_from_cycle({
            "source":    "self_modifier",
            "executed":  executed,
            "failed":    failed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        print("  [LEARNER] ✅")
    except Exception as e:
        print(f"  [LEARNER] пропуснат: {e}")


if __name__ == "__main__":
    run()