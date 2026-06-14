#!/usr/bin/env python3
"""
execute_patches.py
Изпълнява генерираните patches от self_modifier.
Мери реален ефект чрез auto_level.py ПРЕДИ и СЛЕД всеки patch.
"""
import subprocess, sys, pathlib, json, os, time
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