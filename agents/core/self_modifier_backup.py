#!/usr/bin/env python3
import json, pathlib, subprocess, sys, tempfile
from datetime import datetime, timezone
from core.groq_backend import call_groq
try:
    from memory.runtime_telemetry import record_experience as _rec
except:
    _rec = lambda *a, **k: None

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]

def run():
    proposals_path = BASE_DIR / "memory" / "improvement_proposals.json"
    sa_path        = BASE_DIR / "memory" / "self_awareness.json"
    journal_path   = BASE_DIR / "memory" / "development_journal.json"
    levels_path    = BASE_DIR / "memory" / "auto_levels.json"
    s2_path        = BASE_DIR / "memory" / "system2_latest.json"

    try:
        raw = json.loads(proposals_path.read_text(encoding="utf-8"))
        proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
    except:
        proposals = []

    try:
        s2 = json.loads(s2_path.read_text(encoding="utf-8"))
        for p in s2.get("step4_self_reflection", {}).get("improvement_proposals", []):
            if p not in proposals:
                proposals.append(p)
    except:
        pass

    try:
        sa = json.loads(sa_path.read_text(encoding="utf-8"))
    except:
        sa = {}

    try:
        levels = json.loads(levels_path.read_text(encoding="utf-8"))
    except:
        levels = {}

    print("[SELF_MODIFIER] ═══════════════════════════════")
    print("[SELF_MODIFIER] АВТОНОМНА САМОРЕФЛЕКСИЯ")
    print("[SELF_MODIFIER] ═══════════════════════════════")

    high = [p for p in proposals if isinstance(p, dict) and p.get("priority") == "HIGH"]
    print(f"  HIGH предложения: {len(high)}")
    print()

    executed, failed = [], []

    for proposal in high[:2]:
        component = proposal.get("component", "")
        problem   = proposal.get("problem", "")
        solution  = proposal.get("solution", "")
        print(f"[SELF_MODIFIER] Проблем: {problem[:70]}")

        context = _build_context(sa, levels, component)
        result  = _autonomous_solve(problem, solution, component, context)

        if result["success"]:
            executed.append({"problem": problem[:100], "action": result["action"], "code_written": result.get("code_written", False)})
            _rec("SUCCESS", {"message": result["action"], "problem": problem[:60]})
            print(f"  SUCCESS: {result['action']}")
        else:
            failed.append({"problem": problem[:100], "reason": result.get("reason", "?")})
            _rec("ERROR", {"message": result.get("reason","?"), "problem": problem[:60]})
            print(f"  FAILED: {result.get('reason','?')}")
        print()

    _log_journal(journal_path, executed, failed)
    print(f"[SELF_MODIFIER] Изпълнени: {len(executed)} | Неуспешни: {len(failed)}")
    for e in executed:
        print(f"  -> {e['action']}")


def _build_context(sa, levels, component):
    critical  = [a for a, d in levels.items() if d.get("level") == "LOW"]
    missing   = sa.get("software_mind", {}).get("missing_data", [])
    key_files = sa.get("code_map", {}).get("key_files", {})
    return (
        f"Критични оси: {critical}\n"
        f"Липсващи данни: {missing[:3]}\n"
        f"Ключови файлове: {json.dumps(key_files, ensure_ascii=False)}\n"
        f"BASE_DIR: {BASE_DIR}"
    )


def _autonomous_solve(problem, solution, component, context):
    prompt = (
        f"Ти си CORTEX++ self-modifier.\n\n"
        f"КОД НА СИСТЕМАТА:\n{context[:2000]}\n\n"
        f"ПРОБЛЕМ: {problem}\nРЕШЕНИЕ: {solution}\n\n"
        f"Напиши САМО валиден Python код. Без обяснения. Без markdown. Само код.\n"
        f"Първият ред: #!/usr/bin/env python3\n"
        f"НЕ пиши нищо преди или след кода. Само чист Python."
    )
    try:
        raw = call_groq(prompt, max_tokens=800)
        if "```python" in raw: raw = raw.split("```python")[1].split("```")[0]
        elif "```" in raw: raw = raw.split("```")[1].split("```")[0]
        raw = raw.strip()
        target = f"agents/core/{component.lower()}_patch.py"
        print(f"  Groq: WRITE_PYTHON -> {target}")
        return _write_python(target, raw)
    except Exception as e:
        return {"success": False, "reason": str(e)[:120]}


def _log_semantic(content, component):
    try:
        sys.path.insert(0, str(BASE_DIR))
        from memory.semantic_memory import remember
        remember(text=content[:500], axis=component.upper(), source="self_modifier")
        return {"success": True, "action": f"Инсайт: {content[:60]}"}
    except Exception as e:
        return {"success": False, "reason": str(e)[:100]}


def _update_json(target_file, content):
    try:
        if not target_file.startswith("memory/"):
            return {"success": False, "reason": "Само memory/ е позволено"}
        path = BASE_DIR / target_file
        if not path.exists():
            return {"success": False, "reason": f"Не съществува: {target_file}"}
        existing = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(content, str):
            try:
                update = json.loads(content)
            except:
                update = {"note": content}
        else:
            update = content
        if isinstance(existing, dict):
            existing["auto_update"] = {"timestamp": datetime.now(timezone.utc).isoformat(), "by": "self_modifier", "data": update}
            new_content = json.dumps(existing, ensure_ascii=False, indent=2)
            if len(new_content) < 10:
                return {"success": False, "reason": "Празно съдържание — отказано"}
            path.write_text(new_content, encoding="utf-8")
            return {"success": True, "action": f"JSON обновен: {target_file}"}
        return {"success": False, "reason": "Несъвместима структура"}
    except Exception as e:
        return {"success": False, "reason": str(e)[:100]}


def _write_python(target_file, content):
    try:
        allowed = ["memory/", "agents/core/", "data_providers/"]
        if not any(target_file.startswith(a) for a in allowed):
            return {"success": False, "reason": f"Не е позволено: {target_file}"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        check = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open(r'{tmp_path}').read()); print('OK')"],
            capture_output=True, text=True, timeout=10
        )
        pathlib.Path(tmp_path).unlink(missing_ok=True)
        if "OK" not in check.stdout:
            return {"success": False, "reason": f"Синтаксис: {check.stderr[:80]}"}
        target = BASE_DIR / target_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"success": True, "action": f"Код написан: {target_file}", "code_written": True}
    except Exception as e:
        return {"success": False, "reason": str(e)[:100]}


def _log_journal(journal_path, executed, failed):
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except:
        journal = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today not in journal:
        journal[today] = {}
    if "auto_modifications" not in journal[today]:
        journal[today]["auto_modifications"] = []
    for e in executed:
        journal[today]["auto_modifications"].append({"timestamp": datetime.now(timezone.utc).isoformat(), "action": e["action"], "problem_solved": e["problem"], "code_written": e.get("code_written", False), "executed_by": "SELF_MODIFIER_AUTONOMOUS"})
    for f in failed:
        journal[today]["auto_modifications"].append({"timestamp": datetime.now(timezone.utc).isoformat(), "action": "FAILED", "problem": f["problem"], "reason": f["reason"], "executed_by": "SELF_MODIFIER_AUTONOMOUS"})
    journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    run()
