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


_MEASURED_RE = re.compile(r"^MEASURED:\s*(.+)$", re.MULTILINE)

def _extract_measured(stdout: str):
    """The patch's own self-report: a 'MEASURED: {...}' line (required by the
    self_modifier prompt since 13 Aug 2026). This is what makes a patch's claim
    checkable — a patch that measures nothing cannot claim to have helped."""
    m = _MEASURED_RE.search(stdout or "")
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except Exception:
        return raw[:200]  # non-JSON but present — keep the text


_READ_CALL_RE = re.compile(r"(_read_json\s*\(|read_text\s*\(|json\.load\s*\()")
_QUOTED_JSON_RE = re.compile(r'["\']([\w./\\-]+\.jsonl?)["\']')

def _measurement_quality(measured, source: str):
    """15 Aug 2026 — THE LETTER-VS-SPIRIT FIX.

    Yesterday's rule ("every patch must print MEASURED") worked mechanically and
    failed substantively: today's four patches all printed MEASURED and all of
    them reported 0 / 0.0 / a hardcoded constant, having read nothing. A number
    that came from no file is not a measurement, it is a decoration.

    Returns (quality, why):
      MEASURED   — a real value derived from a file the system actually has
      ZERO       — printed a measurement of 0/None/empty (nothing was measured)
      FABRICATED — never read any existing data file; the number is invented
      UNMEASURED — no MEASURED line at all
    """
    if measured is None:
        return "UNMEASURED", "no MEASURED line"
    val = measured.get("value") if isinstance(measured, dict) else measured
    reads = bool(_READ_CALL_RE.search(source or ""))
    named = [f for f in _QUOTED_JSON_RE.findall(source or "")
             if (BASE / f).exists() or (BASE / "memory" / pathlib.Path(f).name).exists()]
    if not (reads and named):
        return "FABRICATED", ("no read of an existing data file"
                              if not named else "no read call")
    if val is None or (isinstance(val, (int, float)) and float(val) == 0.0) or val == "":
        return "ZERO", f"measured {val!r} from {named[0]} — nothing actually measured"
    return "MEASURED", f"{val!r} derived from {named[0]}"


def _record(name, ok, out, err, score_before, score_after, levels_before, levels_after,
            source: str = ""):
    delta   = round(score_after - score_before, 2) if score_before is not None and score_after is not None else None
    measured = _extract_measured(out)
    verdict = "NEUTRAL"
    if delta is not None:
        if delta > 1.0:   verdict = "BENEFICIAL"
        elif delta < -1.0: verdict = "HARMFUL"
    # Axis levels almost never move in the seconds after one patch, so nearly every
    # patch used to land as NEUTRAL — indistinguishable from "did nothing". A patch
    # that ran fine but reported NO measurement is now named for what it is: the
    # quarantine lesson (measurable_goal rule) applied at the execution end too.
    quality, quality_why = _measurement_quality(measured, source)
    if ok and verdict == "NEUTRAL" and quality != "MEASURED":
        verdict = quality          # UNMEASURED / ZERO / FABRICATED — never silent NEUTRAL
        print(f"  [MEASUREMENT] {quality}: {quality_why}")

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
            "measured":     measured,
            "measurement_quality": quality,
            "measurement_why":     quality_why,
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
            "measured":     measured,
            "measurement_quality": quality,
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


def _guardian_supervised_run(patch: pathlib.Path, env: dict) -> tuple[bool, str, str]:
    """
    Прекарва patch-а изцяло през AST gate + PatchGuardian.apply_patch():
      AST capability gate (втори слой — self_modifier вече провери преди
      write, тук е независим re-check) → backup → syntax → write →
      import-check (инертен — генерираният код е обграден в
      if __name__ == "__main__" от self_modifier) → реално изпълнение
      (subprocess, cwd=BASE, 30s timeout) → auto-rollback (quarantine на
      новия patch файл, НЕ delete) при неуспех.

    guardian.apply_patch() е единственият път, по който patch-ът реално се
    изпълнява — вече няма отделен "суров" subprocess.run на скрипта.

    Returns (success: bool, stdout: str, stderr: str).
    Пада обратно към директен subprocess.run само ако patch_guardian не
    може да се импортне.
    """
    import asyncio as _asyncio
    from safety.ast_gate import check_code
    from safety.quarantine import quarantine

    relpath = patch.relative_to(BASE).as_posix()
    source  = patch.read_text(encoding="utf-8", errors="ignore")

    # ── AST capability gate (независим re-check преди guardian) ────────────
    gate_allowed, gate_reason = check_code(source)
    if not gate_allowed:
        print(f"  [AST_GATE] ✗ {gate_reason} → quarantine")
        quarantine(
            base_dir=BASE,
            filename=relpath,
            reason=gate_reason,
            verdict={"gate": "ast_gate", "stage": "execute_patches_recheck", "reason": gate_reason},
            source_path=patch,
        )
        return False, "", f"AST_GATE: {gate_reason}"
    print(f"  [AST_GATE] ✔ {relpath} разрешен")

    try:
        from patch_guardian import PatchGuardian, PatchResult
    except ImportError as e:
        print(f"  [GUARDIAN] import error: {e} — direct run")
        try:
            r = subprocess.run([sys.executable, str(patch)], cwd=str(BASE),
                               capture_output=True, text=True, timeout=30, env=env,
                               encoding="utf-8", errors="replace")
            return r.returncode == 0, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return False, "", "timeout"
        except Exception as ex:
            return False, "", str(ex)

    guardian = PatchGuardian()

    _prev_cwd = os.getcwd()
    os.chdir(str(BASE))  # guardian резолвва Path(filename) спрямо CWD
    try:
        try:
            res = _asyncio.run(guardian.apply_patch(relpath, source))
        except Exception as ge:
            res = PatchResult(relpath, False, "exception", str(ge))
    finally:
        os.chdir(_prev_cwd)

    guardian._save_result(res)
    if not res.success:
        print(f"  [GUARDIAN] ✗ apply_patch FAIL [{res.stage}]: {res.error}")
        return False, res.stdout or "", f"guardian:{res.stage}:{res.error}"

    print(f"  [GUARDIAN] ✔ apply_patch OK [stage={res.stage}]")
    return True, res.stdout or "", ""


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

        # ── PatchGuardian supervised run: syntax+backup+compile+execute+apply_patch
        try:
            _src = patch.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            _src = ""
        ok, stdout, stderr = _guardian_supervised_run(patch, env)

        if ok:
            time.sleep(1)
            levels_after = _compute_levels()
            score_after  = _avg_score(levels_after)

            verdict, delta, changed = _record(
                patch.name, True, stdout, "",
                score_before, score_after, levels_before, levels_after, source=_src
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
            print(f"  ⛔ GUARDIAN FAIL: {stderr[:200]}")
            # A failed patch was rolled back, so the levels should be EXACTLY what they
            # were. Passing {} here claimed the opposite: _changed_axes read a missing
            # axis as None and printed "all 20 axes -> None" after every single failure,
            # which is both false and the precise shape of the alarm that would matter
            # if a rollback ever left damage behind. Recompute instead — silence now
            # means the rollback was clean, and a line means it was not.
            levels_after = _compute_levels()
            _record(patch.name, False, stdout, stderr,
                    score_before, None, levels_before, levels_after, source=_src)

    print(f"\n[PATCH_EXECUTOR] final score = {_avg_score(levels_before)}")
    print(f"[PATCH_EXECUTOR] done at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    run()