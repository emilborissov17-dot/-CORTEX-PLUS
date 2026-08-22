#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cycle_profile.py — WHAT A CYCLE MAY SPEND, DEPENDING ON THE HOUR.

    day    06:00-22:00   full cycle, 8b window allowed, cloud primary for batch
    night  22:00-06:00   lean: qwen3:8b FORBIDDEN, its work deferred to the day

The prohibition is the point, and it is measured rather than felt: qwen2.5:3b
and qwen3:8b never coexist in 4GB of VRAM, and 8b does not fit even alone —
3.32GB of 5.75GB resident, the remaining 42% running from system RAM. A night
run that loads it pays a full reload in and another out, charged to a step's
ceiling, with nobody awake to notice the degradation. The day has a human nearby.

WORK IS DEFERRED, NOT DROPPED
------------------------------
A night task that needs the big model is appended to memory/deferred_batch.json
and drained by the FIRST day cycle. Dropping it would make the night look
successful while quietly doing less each time — the kind of slow shrinkage that
only shows up months later as "why does it not notice things any more".

THE INTERACTION THIS MODULE CANNOT RESOLVE BY ITSELF
------------------------------------------------------
The nightly cycle runs at 03:00, which is inside the NIGHT window. So if this is
ever wired, `big_model_allowed = false` will forbid the 8b window that
config/model_window.json opens at `brain_reconsider`, on the one cycle that
actually runs unattended. 8b would then execute only in manual day cycles.

That may well be right — it is what "8b FORBIDDEN at night" means, and 8b's
place in the night is exactly what has been costing reloads. But it is a
consequence, not a detail, and it belongs in front of a human before either
setting is changed. Written here rather than discovered at 03:00.

NOT WIRED. Nothing consults this.

    venv\\Scripts\\python.exe core/cycle_profile.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
CONFIG = BASE / "config" / "cycle_profiles.json"
STEP_PRIORITY = BASE / "config" / "step_priority.json"

DAY, NIGHT = "day", "night"

# The fail-safe profile, used when the config cannot be read. NIGHT, deliberately:
# the cautious answer costs the expensive model, the incautious one costs a
# reload storm on an unattended run.
FALLBACK = {
    "name": NIGHT,
    "allowed_priorities": ["CRITICAL", "NORMAL"],
    "big_model_allowed": False,
    "cloud_primary_for_batch": True,
    "why": "config/cycle_profiles.json unreadable — falling back to the cautious profile",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Optional[pathlib.Path] = None) -> dict:
    try:
        return json.loads((pathlib.Path(path) if path else CONFIG)
                          .read_text(encoding="utf-8"))
    except Exception:
        return {}


@dataclass
class Profile:
    name: str
    hour: int
    allowed_priorities: list
    big_model_allowed: bool
    cloud_primary_for_batch: bool
    why: str = ""
    run: list = field(default_factory=list)
    skip: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def in_window(hour: int, start: int, end: int) -> bool:
    """[start, end), handling a window that wraps midnight.

    22->6 is not a range in the ordinary sense; it is the complement of 6->22.
    Writing it as two comparisons and an `or` is the whole trick, and getting it
    wrong silently gives every hour the day profile.
    """
    hour = int(hour) % 24
    start, end = int(start) % 24, int(end) % 24
    if start == end:
        return True                     # a full-day window
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def profile_name_for(when: Optional[datetime] = None,
                     config: Optional[dict] = None) -> str:
    cfg = config if config is not None else _load()
    profiles = (cfg.get("profiles") or {})
    hour = (when or datetime.now().astimezone()).hour
    for name, spec in profiles.items():
        if in_window(hour, spec.get("starts_hour", 0), spec.get("ends_hour", 0)):
            return name
    return FALLBACK["name"]


def load_priorities(path: Optional[pathlib.Path] = None) -> dict:
    """{step: CRITICAL} from config/step_priority.json. Absent means NORMAL.

    DELEGATES to core.survival_mode, which has read this file since it was
    written. The file is NOT a flat {step: priority} map — it is
    {"CRITICAL": [names...]} — and a second reader here got 0 entries where the
    first got 16, silently, until the selftest printed both. One reader.
    """
    try:
        from core.survival_mode import load_priorities as _lp
        return _lp(pathlib.Path(path).parents[1] if path else None)
    except Exception:
        return {}


def resolve(when: Optional[datetime] = None,
            steps: Optional[list] = None,
            config: Optional[dict] = None,
            priorities: Optional[dict] = None) -> Profile:
    """Which profile applies, and which steps it would run.

    Pure with respect to its inputs — every one can be injected — so a test can
    ask about 03:00 without waiting for 03:00.
    """
    cfg = config if config is not None else _load()
    when = when or datetime.now().astimezone()
    name = profile_name_for(when, cfg)
    spec = (cfg.get("profiles") or {}).get(name) or FALLBACK

    if not cfg.get("enabled", True):
        spec = dict(spec)
        spec["big_model_allowed"] = True
        spec["why"] = "profiles disabled in config; nothing is restricted"

    allowed = list(spec.get("allowed_priorities")
                   or FALLBACK["allowed_priorities"])
    table = priorities if priorities is not None else load_priorities()

    if steps is None:
        try:
            from core.cycle_map import STEPS
            steps = list(dict.fromkeys(s[0] for s in STEPS))
        except Exception:
            steps = []

    run, skip = [], []
    for s in steps:
        (run if table.get(s, "NORMAL") in allowed else skip).append(s)

    notes = []
    if not skip and steps:
        # Said every time, because a filter that excludes nothing looks in a log
        # exactly like a filter that is working.
        notes.append(
            "the priority filter {} excludes none of the {} steps: "
            "config/step_priority.json defines only CRITICAL and NORMAL, and both "
            "are allowed. This profile's leanness is entirely the model policy."
            .format(allowed, len(steps)))
    if not table:
        notes.append("config/step_priority.json is missing or empty; every step "
                     "read as NORMAL")

    return Profile(
        name=name, hour=when.hour, allowed_priorities=allowed,
        big_model_allowed=bool(spec.get("big_model_allowed", False)),
        cloud_primary_for_batch=bool(spec.get("cloud_primary_for_batch", True)),
        why=str(spec.get("why", "")), run=run, skip=skip, notes=notes)


# ---------------------------------------------------------------------------
# Deferral
# ---------------------------------------------------------------------------

def deferred_path(config: Optional[dict] = None) -> pathlib.Path:
    cfg = config if config is not None else _load()
    return BASE / (cfg.get("deferred_batch_path") or "memory/deferred_batch.json")


def defer(task: dict, path: Optional[pathlib.Path] = None,
          config: Optional[dict] = None) -> dict:
    """Put an 8b-needing task aside for the first day cycle.

    Deduplicated on `key` if one is given: a nightly task deferred every night
    for a week should be one entry with a count, not seven entries. Otherwise the
    day cycle wakes up to a backlog that grows with the number of nights rather
    than with the amount of work.
    """
    p = pathlib.Path(path) if path else deferred_path(config)
    blob = _read_deferred(p)
    key = task.get("key")
    if key:
        for existing in blob["tasks"]:
            if existing.get("key") == key:
                existing["deferred_count"] = int(existing.get("deferred_count", 1)) + 1
                existing["last_deferred"] = _now()
                _write_deferred(p, blob)
                return existing
    rec = dict(task)
    rec.setdefault("key", None)
    rec["deferred_at"] = _now()
    rec["last_deferred"] = rec["deferred_at"]
    rec["deferred_count"] = 1
    blob["tasks"].append(rec)
    _write_deferred(p, blob)
    return rec


def deferred(path: Optional[pathlib.Path] = None,
             config: Optional[dict] = None) -> list:
    return _read_deferred(pathlib.Path(path) if path else deferred_path(config))["tasks"]


def take_deferred(path: Optional[pathlib.Path] = None,
                  config: Optional[dict] = None) -> list:
    """Drain the backlog. The FIRST day cycle calls this; the rest find it empty.

    Returns the tasks and empties the file in one step, so two cycles racing
    cannot both run the same deferred work.
    """
    p = pathlib.Path(path) if path else deferred_path(config)
    blob = _read_deferred(p)
    tasks = blob["tasks"]
    _write_deferred(p, {"tasks": [], "drained_at": _now()})
    return tasks


def _read_deferred(p: pathlib.Path) -> dict:
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(blob, dict) and isinstance(blob.get("tasks"), list):
            return blob
    except Exception:
        pass
    return {"tasks": []}


def _write_deferred(p: pathlib.Path, blob: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/cycle_profile.py --selftest")
    print("  repo base            {}".format(BASE))
    ok = True

    cfg = _load()
    if cfg:
        print("  config               LIVE ({} profiles, enabled={})".format(
            len(cfg.get("profiles") or {}), cfg.get("enabled")))
    else:
        print("  config               INERT — falling back to the cautious profile")
        ok = False

    table = load_priorities()
    print("  step_priority.json   {} ({} entries, values={})".format(
        "LIVE" if table else "INERT", len(table),
        sorted(set(table.values())) or "-"))
    if not table:
        ok = False

    now = datetime.now().astimezone()
    for label, hour in (("now", now.hour), ("03:00 (the nightly cycle)", 3),
                        ("12:00", 12), ("22:00", 22), ("06:00", 6),
                        ("21:59", 21), ("05:59", 5)):
        when = now.replace(hour=hour, minute=0)
        p = resolve(when)
        print("    {:<26} -> {:<5}  8b_allowed={:<5}  runs {}/{} steps".format(
            label, p.name, str(p.big_model_allowed), len(p.run),
            len(p.run) + len(p.skip)))

    p = resolve(now.replace(hour=3))
    for n in p.notes:
        print("    NOTE: {}".format(n))

    print("")
    print("  THE INTERACTION TO DECIDE BEFORE WIRING:")
    print("    the nightly cycle runs at 03:00, which is NIGHT, so big_model_allowed")
    print("    is False. Wired as written, that forbids the 8b window")
    print("    config/model_window.json opens at brain_reconsider -- on the one")
    print("    cycle that runs unattended. 8b would then run only in manual day")
    print("    cycles. That may be correct; it is a human's call, not a detail.")

    dp = deferred_path()
    print("")
    print("  deferred batch       {} exists={} ({} task(s) waiting)".format(
        dp.name, dp.exists(), len(deferred())))

    try:
        runner = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8",
                                                           errors="replace")
        wired = "cycle_profile" in runner
    except OSError:
        wired = False
    print("  fast_cycle_runner    {}".format(
        "WIRED" if wired else
        "NOT WIRED — no cycle consults a profile; the 03:00 run behaves exactly "
        "as it did last night"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
