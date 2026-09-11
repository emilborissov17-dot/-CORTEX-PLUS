#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/signed_schedule.py — A RANDOMISED EXPERIMENT ON A KNOB THE MACHINE MAY NOT TOUCH.
(10 Sep 2026. Emil: "потърси и намери решение" for the empty self-improvement loop.)

THE PROBLEM, EXACTLY
--------------------
exp-001 asks whether step_ceiling 900 or 1500 gives fewer watchdog kills on
daily_analysis. The knob lives in config/scheduler.json, a protected path: the
machine cannot write it, and it must not — a system that can raise its own
ceiling has no ceiling. So the arm is whatever the human last set, which is
one arm for weeks: 30 nights, a=1, b=12 counted. STEP 6a (Claude Code, today)
made the loop honest about that — `randomised: False`, an observational
verdict — and honest is not the same as informative. The sandbox bench says
why: from observation alone, direction is not recoverable (T8 FAIL); it is
recovered by INTERVENTION (T12, T6A PASS). The self loop needs interventions.

THE SOLUTION: THE HUMAN SIGNS THE RANDOMISATION, ONCE. THE PEN STAYS HUMAN.
----------------------------------------------------------------------------
config/self_experiment_schedule.json carries a seed, an arm count and a
signature. The sequence of arms is a pure function of (seed, n_per_arm) — a
balanced shuffle — so it can be re-derived and checked at every step: the
machine cannot slip a different sequence under a valid signature. `--apply`
writes tonight's arm into the guarded file ON BEHALF OF THE SIGNATURE, not on
the brain's judgement: it runs from a Windows scheduled task the human
creates, before the 03:04 cycle; the brain never calls it, has no say in the
arm, and reads the arm back from the file as it does today (STEP 6a). Every
application is logged with the UTC time, so core/self_experiment.py can
establish the value in force for a cycle from the log rather than from the
file's mtime (which the nightly edit would otherwise poison).

Refusals, loud:
  * unsigned (signed_by null)                -> nothing written, exit 2
  * sequence on file != derived from seed    -> TAMPERED, nothing written, exit 3
  * sequence exhausted                       -> restore_value written once, DONE
  * arm value outside the knob's band        -> refused (the band is in code)

Usage:
  venv\\Scripts\\python.exe tools\\signed_schedule.py --draw        # print the sequence for the seed, for the human to read before signing
  venv\\Scripts\\python.exe tools\\signed_schedule.py --status
  venv\\Scripts\\python.exe tools\\signed_schedule.py --apply       # tonight's arm into the guarded file (scheduled task, 02:50 local)
  venv\\Scripts\\python.exe tools\\signed_schedule.py --selftest
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCHEDULE = REPO / "config" / "self_experiment_schedule.json"
LOG = REPO / "memory" / "self_experiment_schedule_log.jsonl"

# ── ЕДИН ИЗТОЧНИК НА ОБХВАТА, НЕ ОГЛЕДАЛО (11 септември 2026) ───────────────
# Тук стоеше `BANDS = {"step_ceiling": (300, 1800)}` с коментар „mirrors
# core/self_experiment.ALLOWED_KNOBS". Огледало на договор е точно дефектът, който
# СТЪПКА 3 поправи при merkle_to_training: два четеца на едно правило се разминават
# мълчаливо, а тук разминаването е в посока НАВЪН — ако някой разшири огледалото,
# подписът би могъл да запише стойност извън обявения в кода обхват, и пазачът на
# тавана пада без никой да го е махал.
#
# Затова обхватът се ЧЕТЕ от ALLOWED_KNOBS, което е авторитетът. Литералът остава
# само като резерва, ако инструментът се пусне без пакета (сам файл, друга машина),
# и test_the_band_is_not_a_copy пада, ако резервата се разминае с източника.
_BAND_FALLBACK = {"step_ceiling": (300, 1800)}


def _bands() -> dict:
    """{knob: (lo, hi)} от core.self_experiment.ALLOWED_KNOBS; резервата само ако
    модулът не е достъпен. Обхватът е в КОДА — никога в подписания файл, иначе
    подписът щеше да си определя и границите."""
    try:
        sys.path.insert(0, str(REPO))
        from core.self_experiment import ALLOWED_KNOBS  # noqa: PLC0415
        out = {}
        for name, decl in ALLOWED_KNOBS.items():
            band = decl.get("band")
            if isinstance(band, (list, tuple)) and len(band) == 2:
                out[name] = (band[0], band[1])
        return out or dict(_BAND_FALLBACK)
    except Exception:
        return dict(_BAND_FALLBACK)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def draw(seed: int, n_per_arm: int) -> list[str]:
    """Balanced random sequence: n_per_arm of 'a' and of 'b', order by the seed. Pure."""
    seq = ["a"] * n_per_arm + ["b"] * n_per_arm
    random.Random(int(seed)).shuffle(seq)
    return seq


def load(path: Path = SCHEDULE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _log_rows(log: Path) -> list[dict]:
    if not log.exists():
        return []
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def status(sched: dict, log: Path | None = None) -> dict:
    """Where the schedule stands. Never writes."""
    log = log or LOG
    expected = draw(sched["seed"], sched["n_per_arm"])
    on_file = sched.get("sequence")
    signed = bool(sched.get("signed_by")) and bool(sched.get("signed_on"))
    tampered = on_file is not None and list(on_file) != expected
    applied = [r for r in _log_rows(log) if r.get("schedule_id") == sched.get("id")]
    return {"id": sched.get("id"), "signed": signed, "signed_by": sched.get("signed_by"),
            "tampered": tampered, "length": len(expected), "applied": len(applied),
            "next_position": len(applied), "expected": expected,
            "done": len(applied) >= len(expected)}


def apply(sched: dict, target: Path, log: Path | None = None, now: str | None = None,
          write=None) -> dict:
    """Write tonight's arm into the guarded file on behalf of the signature.
    `write(path, blob)` injectable so the tests never touch config/."""
    log = log or LOG
    st = status(sched, log)
    if not st["signed"]:
        return {"verdict": "UNSIGNED", "written": False,
                "why": "signed_by/signed_on are null — a schedule nobody signed applies nothing"}
    if st["tampered"]:
        return {"verdict": "TAMPERED", "written": False,
                "why": "the sequence on file is not the one the signed seed derives — refused"}
    knob = sched["knob"]
    lo, hi = _bands().get(knob, (None, None))
    blob = json.loads(target.read_text(encoding="utf-8"))
    section, key = sched["key"].split(".", 1)
    before = (blob.get(section) or {}).get(key)
    if st["done"]:
        value, arm, position = sched["restore_value"], None, None
        already = any(r.get("restored") for r in _log_rows(log) if r.get("schedule_id") == sched.get("id"))
        if already:
            return {"verdict": "DONE", "written": False, "why": "sequence exhausted and restore already applied"}
    else:
        position = st["next_position"]
        arm = st["expected"][position]
        value = sched["arms"][arm]
    if lo is not None and not (lo <= int(value) <= hi):
        return {"verdict": "OUT_OF_BAND", "written": False, "why": f"{value} outside {knob} band {lo}..{hi}"}
    blob.setdefault(section, {})[key] = value
    (write or (lambda p, b: p.write_text(json.dumps(b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")))(target, blob)
    row = {"applied_utc": now or _now(), "schedule_id": sched.get("id"), "experiment": sched.get("experiment"),
           "knob": knob, "step": sched.get("step"), "key": sched["key"], "position": position, "arm": arm,
           "value": value, "before": before, "signed_by": sched.get("signed_by"), "restored": st["done"]}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"verdict": "RESTORED" if st["done"] else "APPLIED", "written": True, **row}


def value_in_force_from_log(step: str, cycle_start: str, cycle_end: str, log: Path | None = None):
    """(value, basis) or (None, None). The signed log is evidence of what the file held
    during [cycle_start, cycle_end]: the last application at or before cycle_start,
    provided nothing was applied inside the window."""
    log = log or LOG          # read at call time, so a test (or a hook) can repoint it
    rows = [r for r in _log_rows(log) if r.get("step") == step and r.get("applied_utc")]
    if not rows:
        return None, None
    before = [r for r in rows if r["applied_utc"] <= cycle_start]
    inside = [r for r in rows if cycle_start < r["applied_utc"] <= cycle_end]
    if inside:
        return None, f"the signed schedule changed the value at {inside[0]['applied_utc'][:19]}, inside this cycle"
    if not before:
        return None, None
    last = before[-1]
    return last["value"], (f"applied by the signed schedule (position {last.get('position')}, arm "
                           f"{last.get('arm')}) at {last['applied_utc'][:19]}, signed {last.get('signed_by')}")


def _selftest() -> int:
    print("tools/signed_schedule.py --selftest")
    checks = [("draw is deterministic", draw(7, 6) == draw(7, 6)),
              ("draw is balanced", sorted(draw(7, 6)) == ["a"] * 6 + ["b"] * 6),
              ("different seeds differ", draw(7, 6) != draw(8, 6))]
    live = None
    try:
        live = status(load())
        checks.append((f"live schedule loads (signed={live['signed']}, tampered={live['tampered']}, "
                       f"applied={live['applied']}/{live['length']})", not live["tampered"]))
    except Exception as exc:  # noqa: BLE001
        checks.append((f"live schedule loads ({exc})", False))
    ok = True
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    if live is not None:
        print("  INTEGRATION:", "LIVE — signed, applies from the scheduled task" if live["signed"]
              else "INERT — unsigned; nothing is applied until a human signs config/self_experiment_schedule.json")
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sched = load()
    if "--draw" in sys.argv:
        print(json.dumps({"seed": sched["seed"], "n_per_arm": sched["n_per_arm"],
                          "sequence": draw(sched["seed"], sched["n_per_arm"])}, ensure_ascii=False))
        sys.exit(0)
    if "--apply" in sys.argv:
        out = apply(sched, REPO / sched["file"])
        print(json.dumps(out, ensure_ascii=False))
        sys.exit({"APPLIED": 0, "RESTORED": 0, "DONE": 0, "UNSIGNED": 2, "TAMPERED": 3}.get(out["verdict"], 1))
    print(json.dumps(status(sched), ensure_ascii=False, indent=2))
