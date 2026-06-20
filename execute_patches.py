#!/usr/bin/env python3
"""
execute_patches.py
Изпълнява генерираните patches от self_modifier.
Мери реален ефект чрез auto_level.py ПРЕДИ и СЛЕД всеки patch.
"""
import subprocess, sys, pathlib, json, os, time, re
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parent
PATCH_DIR    = BASE / "agents" / "core"
JOURNAL_PATH = BASE / "memory" / "development_journal.json"

sys.path.insert(0, str(BASE))
os.environ.setdefault("CORTEX_BASE", str(BASE))


def _compute_levels() -> dict:
    """Вика auto_level.py и връща новите levels."""
    try:
        from memory.auto_level import run as auto_level_run
        levels, _, _ = auto_level_run()
        return levels
    except Exception as e:
        print(f"  [AUTO_LEVEL] грешка: {e}")
        return {}


def _avg_score(levels: dict) -> float | None:
    level_map = {"HIGH": 100.0, "MEDIUM": 55.0, "LOW": 10.0}
    scores = []
    for v in levels.values():
        lvl = v.get("level", "") if isinstance(v, dict) else str(v)
        if lvl in level_map:
            scores.append(level_map[lvl])
    return round(sum(scores) / len(scores), 2) if scores else None


def _changed_axes(before: dict, after: dict) -> list:
    changed = []
    for axis in set(list(before.keys()) + list(after.keys())):
        b = before.get(axis, {})
        a = after.get(axis, {})
        bl = b.get("level") if isinstance(b, dict) else b
        al = a.get("level") if isinstance(a, dict) else a
        if bl != al:
            changed.append(f"{axis}: {bl} → {al}")
    return changed


def _record(name, ok, out, err, score_before, score_after, levels_before, levels_after):
    delta   = round(score_after - score_before, 2) if score_before is not None and score_after is not None else None
    verdict = "NEUTRAL"
    if delta is not None:
        if delta > 1.0:   verdict = "BENEFICIAL"
        elif delta < -1.0: verdict = "HARMFUL"

    changed = _changed_axes(levels_before, levels_after)
    if changed:
        print(f"  [AXES CHANGED] {', '.join(changed)}")

    try:
        try:
            j = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
        except Exception:
            j = {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        j.setdefault(today, {}).setdefault("patch_executions", []).append({
            "timestamp":    datetime.now(timezone.utc).isoformat(),
            "patch":        name,
            "success":      ok,
            "stdout":       out[:300],
            "stderr":       err[:300],
            "score_before": score_before,
            "score_after":  score_after,
            "delta":        delta,
            "verdict":      verdict,
            "changed_axes": changed,
        })
        JOURNAL_PATH.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  [JOURNAL] {e}")

    try:
        from memory.context_injector import record_causal
        effect = f"verdict={verdict} delta={delta}"
        if changed:
            effect += f" | {'; '.join(changed[:3])}"
        record_causal(
            action       = f"execute_patch:{name}",
            effect       = effect,
            why          = "Self-modifier patch изпълнен",
            axis         = "SELF_IMPROVEMENT",
            score_before = score_before,
            score_after  = score_after,
        )
    except Exception as e:
        print(f"  [CAUSAL] {e}")

    try:
        from memory.continuous_learner import learn_from_cycle
        learn_from_cycle({
            "source":       "execute_patches",
            "patch":        name,
            "success":      ok,
            "verdict":      verdict,
            "score_before": score_before,
            "score_after":  score_after,
            "delta":        delta,
            "changed_axes": changed,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    return verdict, delta, changed


# Patterns that require human approval before a patch is executed.
# Checked line-by-line; comment lines are skipped.
_APPROVAL_RULES: list[tuple[str, str]] = [
    # Self-modification of critical orchestration files
    (r"execute_patches",          "пипа execute_patches.py"),
    (r"self_modifier",            "пипа self_modifier.py"),
    # Git operations
    (r"""["']git[\s"']""",        "git операция"),
    (r'subprocess[^\n]*"git',     "git subprocess"),
    # File deletion outside patches/
    # (detected separately below to inspect path context)
    # Network credentials being written
    (r"(?i)(password|secret)\s*=\s*[\"'][^\"']{4,}", "записва credentials"),
    (r"open\s*\([^)]*\.env",      "пише в .env"),
]


def _needs_approval(patch: pathlib.Path) -> tuple[bool, str]:
    """Inspect patch source. Return (True, reason) if approval is required."""
    try:
        content = patch.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return True, "не може да се прочете"

    for line in content.splitlines():
        if line.strip().startswith("#"):
            continue
        for pattern, reason in _APPROVAL_RULES:
            if re.search(pattern, line):
                return True, reason
        # File deletion: flag only when the path is not inside patches/
        if re.search(r"(os\.remove|\.unlink\b|shutil\.rmtree|shutil\.rmdir)", line):
            if "patch" not in line.lower():
                return True, f"изтрива файл извън patches/: {line.strip()[:80]}"

    return False, ""


def _request_approval(patch: pathlib.Path, reason: str) -> bool:
    """Show patch content and reason, then ask for y/N. Returns True if approved."""
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  PATCH:  {patch.name}")
    print(f"  ПРИЧИНА ЗА ПРОВЕРКА: {reason}")
    print(sep)
    try:
        print(patch.read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False
    print(sep)
    try:
        answer = input("  Одобри? [y/N]: ").strip().lower()
        return answer == "y"
    except (EOFError, KeyboardInterrupt):
        print("\n  Прекъснато — patch пропуснат.")
        return False


def _guardian_preflight(patch: pathlib.Path, env: dict) -> tuple[bool, str]:
    """
    Run PatchGuardian checks BEFORE subprocess.run:
      1. Syntax  — AST parse via PatchGuardian._check_syntax()
      2. Backup  — PatchGuardian._make_backup() creates .bak before any execution
      3. Compile — py_compile in subprocess catches import-level errors without executing

    Returns (True, "") if all pass, (False, reason) to skip the patch.
    If patch_guardian cannot be imported, preflight is skipped with a warning (non-blocking).
    """
    try:
        from patch_guardian import PatchGuardian, PatchResult
    except ImportError as e:
        print(f"  [GUARDIAN] не може да се импортира: {e} — preflight пропуснат")
        return True, ""

    guardian = PatchGuardian()
    source   = patch.read_text(encoding="utf-8", errors="ignore")

    # ── 1. Syntax ─────────────────────────────────────────────────────────────
    syntax_ok, syntax_err = guardian._check_syntax(source)
    if not syntax_ok:
        guardian._save_result(PatchResult(patch.name, False, "syntax", syntax_err))
        return False, f"СИНТАКСИС ГРЕШКА: {syntax_err}"
    print(f"  [GUARDIAN] ✔ Синтаксис OK")

    # ── 2. Backup ─────────────────────────────────────────────────────────────
    backup_path = guardian._make_backup(patch)
    if not backup_path:
        return False, "BACKUP НЕУСПЕШЕН — patch пропуснат за безопасност"
    print(f"  [GUARDIAN] ✔ Backup: {backup_path.name}")

    # ── 3. Compile (py_compile) — no execution, catches bad imports/names ──────
    try:
        cp = subprocess.run(
            [sys.executable, "-m", "py_compile", str(patch)],
            capture_output=True, text=True, timeout=10,
            cwd=str(BASE), env=env,
        )
        if cp.returncode != 0:
            err = (cp.stderr or cp.stdout).strip()[:200]
            guardian._save_result(PatchResult(patch.name, False, "import", err))
            return False, f"COMPILE ГРЕШКА: {err}"
        print(f"  [GUARDIAN] ✔ Compile OK")
    except subprocess.TimeoutExpired:
        return False, "COMPILE TIMEOUT (>10s)"
    except Exception as e:
        return False, f"COMPILE ГРЕШКА: {e}"

    return True, ""


def run():
    patches = sorted(PATCH_DIR.glob("*_patch.py"))
    print(f"[PATCH_EXECUTOR] Намерени {len(patches)} patches")

    if not patches:
        print("[PATCH_EXECUTOR] Няма patches.")
        return

    env = {**os.environ, "PYTHONPATH": str(BASE), "CORTEX_BASE": str(BASE)}

    print("[PATCH_EXECUTOR] Изчислявам baseline score от реални метрики...")
    levels_before = _compute_levels()
    score_before  = _avg_score(levels_before)
    print(f"[PATCH_EXECUTOR] baseline = {score_before} ({len(levels_before)} оси)")

    for patch in patches:
        print(f"\n[PATCH_EXECUTOR] → {patch.name}")

        needs_ok, reason = _needs_approval(patch)
        if needs_ok:
            if not sys.stdin.isatty():
                print(f"  ⛔ ПРОПУСНАТ (изисква одобрение, но няма TTY): {reason}")
                print(f"     Пусни ръчно: python execute_patches.py")
                continue
            if not _request_approval(patch, reason):
                print("  ⏭  Пропуснат от потребителя.")
                continue
        else:
            print(f"  ✔  Auto-approved (не пипа чувствителни зони)")

        # ── PatchGuardian preflight: syntax + backup + compile ────────────────
        preflight_ok, preflight_reason = _guardian_preflight(patch, env)
        if not preflight_ok:
            print(f"  ⛔ GUARDIAN FAIL — patch пропуснат: {preflight_reason}")
            _record(patch.name, False, "", preflight_reason,
                    score_before, None, levels_before, {})
            continue

        try:
            result = subprocess.run(
                [sys.executable, str(patch)],
                cwd=str(BASE),
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )

            if result.returncode == 0:
                time.sleep(1)
                levels_after = _compute_levels()
                score_after  = _avg_score(levels_after)

                verdict, delta, changed = _record(
                    patch.name, True, result.stdout, "",
                    score_before, score_after, levels_before, levels_after
                )

                if verdict == "HARMFUL":
                    print(f"  ⚠️  HARMFUL (delta={delta}) — запазен за debugging")
                else:
                    patch.unlink(missing_ok=True)
                    ds = f"{delta:+.2f}" if delta is not None else "n/a"
                    print(f"  ✅ {verdict} | {score_before} → {score_after} (Δ{ds})")

                levels_before = levels_after
                score_before  = score_after

            else:
                print(f"  ❌ FAILED: {result.stderr[:150]}")
                _record(patch.name, False, result.stdout, result.stderr,
                        score_before, None, levels_before, {})

        except subprocess.TimeoutExpired:
            print(f"  ⏱ TIMEOUT")
            _record(patch.name, False, "", "timeout", score_before, None, levels_before, {})
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            _record(patch.name, False, "", str(e), score_before, None, levels_before, {})

    print(f"\n[PATCH_EXECUTOR] final score = {_avg_score(levels_before)}")
    print(f"[PATCH_EXECUTOR] done at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    run()