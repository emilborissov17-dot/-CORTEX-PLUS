#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/phase_evidence.py — EACH PHASE IS JUDGED ON ITS OWN NUMBERS.

THE DEFECT THIS REPLACES
-------------------------
core/phase_tracker._evidence() handed EVERY phase the same two facts:

    composite_score    from snapshots/master/goal_score_latest.json
    measured_metrics   from the same file

plus a step count. The result is on disk and is not an argument, it is a
transcript. Six phases closed on 21 Aug 2026 and six debriefs were accepted:

    A_ORIENT   "Фазата A_ORIENT завърши с композитен скор 0.6282, като се
                измериха 11 метрика."
    B_SENSE    "Фазата B_SENSE завърши с композитен скор 0.6282, като се
                измериха 11 метрика."
    C_SNAPSHOT "Фазата C_SNAPSHOT завърши с композитен скор 0.6282, ..."
    D_SCORE    "Фазата D_SCORE приключи с композитен скор 0.6282, ..."
    E_PROPOSE  "Фазата E_PROPOSE приключи с композитен скор 0.6282, ..."
    F_SELF     "Фазата F_SELF приключи с композитен скор 0.6282, ..."

One sentence with the phase name substituted. The number gate in
core/phase_debrief.py passed all six, correctly by its own rule: 0.6282 IS a
number from the evidence it was given. The gate was never wrong; the evidence
was. A_ORIENT ran before the scorer existed in that cycle — the composite it
"reported" was the PREVIOUS day's, and B_SENSE and C_SNAPSHOT reported it too.

WHAT A MENU IS
---------------
menu(phase) returns the facts that phase's own steps produce, read from that
phase's own artifacts. D_SCORE gets the composite; A_ORIENT gets the plan, the
dependency check and the reanalysis queue; B_SENSE gets collector counts and the
source lifecycle; and so on. No phase gets another phase's headline number
unless its own steps produced it.

THE UNIQUENESS REQUIREMENT, AND WHY IT IS MEASURED NOT ASSERTED
----------------------------------------------------------------
Every menu must contain at least two numbers that appear in NO other phase's
menu. That is what makes the swap test in core/phase_debrief.py possible: a
sentence that would read equally well under another phase's heading cites no
such number, and is rejected as SWAP_GENERIC.

The property depends on live data, so it is MEASURED — `--selftest` prints the
per-phase count of own numbers against the live repo and goes red below two.
Asserting it in a docstring and hoping is the failure mode this file exists to
end. Two numbers are structural and cheap (`phase_artifacts_bytes` and
`phase_artifacts_present` are read from that phase's own `produces` list), so
the floor holds even on a repo with no data yet; the rest are real.

FAIL-OPEN PER FACT, NOT PER MENU. One unreadable artifact costs one key, not
the whole menu — a phase whose evidence collapses to {} would be judged on
nothing and, worse, would silently pass the number gate on its step count.

    venv\\Scripts\\python.exe core/phase_evidence.py --selftest
    venv\\Scripts\\python.exe core/phase_evidence.py --show D_SCORE
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
PHASES_FILE = BASE / "config" / "cycle_phases.json"

PHASES = ("A_ORIENT", "B_SENSE", "C_SNAPSHOT", "D_SCORE",
          "E_PROPOSE", "F_SELF", "G_LEARN")

# At least this many numbers must be unique to each phase's menu, or the swap
# test in core/phase_debrief.py has nothing to stand on.
MIN_OWN_NUMBERS = 2

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


# ---------------------------------------------------------------------------
# Readers — every one of them fail-open, and none of them raise
# ---------------------------------------------------------------------------

def _p(rel: str, base: pathlib.Path | None = None) -> pathlib.Path:
    return (base or BASE) / rel


def _json(rel: str, base: pathlib.Path | None = None):
    try:
        return json.loads(_p(rel, base).read_text(encoding="utf-8"))
    except Exception:
        return None


def _lines(rel: str, base: pathlib.Path | None = None) -> int | None:
    """Row count of a .jsonl. None when the file is not there — which is a
    different fact from zero rows, and must not be rendered as one."""
    try:
        with _p(rel, base).open("r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:
        return None


def _age_min(rel: str, base: pathlib.Path | None = None) -> float | None:
    try:
        st = _p(rel, base).stat()
        return round((datetime.now(timezone.utc).timestamp() - st.st_mtime) / 60.0, 1)
    except Exception:
        return None


def _size(rel: str, base: pathlib.Path | None = None) -> int | None:
    try:
        return _p(rel, base).stat().st_size
    except Exception:
        return None


def _phases_spec(base: pathlib.Path | None = None) -> dict:
    try:
        return json.loads(_p("config/cycle_phases.json", base)
                          .read_text(encoding="utf-8"))["phases"]
    except Exception:
        return {}


def _put(ev: dict, key: str, value) -> None:
    """Record a fact only if it is one. None means 'could not read', and a menu
    full of nulls trains the reader to skip the menu."""
    if value is not None:
        ev[key] = value


# ---------------------------------------------------------------------------
# The structural facts every phase gets — from its OWN produces list
# ---------------------------------------------------------------------------

def _structural(phase: str, base: pathlib.Path | None = None) -> dict:
    """Facts about this phase's own promised artifacts.

    These are the two numbers that hold the uniqueness floor when a repo has no
    data yet: `phase_artifacts_bytes` is the summed size of the files THIS phase
    promises and no other phase promises the same set, so it is unique in
    practice; `phase_steps` is unique for five of the seven phases outright.
    They are not filler — a phase whose promised artifacts total 0 bytes did not
    do its job, and that is exactly what the debrief should be saying.
    """
    ev: dict = {}
    spec = _phases_spec(base).get(phase) or {}
    produces = list(spec.get("produces") or [])
    steps = list(spec.get("steps") or [])
    _put(ev, "phase_steps", len(steps) or None)
    _put(ev, "phase_promised_artifacts", len(produces) or None)

    present, total_bytes, oldest = 0, 0, None
    for rel in produces:
        n = _size(rel, base)
        if n is None:
            continue
        present += 1
        total_bytes += n
        age = _age_min(rel, base)
        if age is not None:
            oldest = age if oldest is None else max(oldest, age)
    if produces:
        ev["phase_artifacts_present"] = present
        ev["phase_artifacts_missing"] = len(produces) - present
        ev["phase_artifacts_bytes"] = total_bytes
        _put(ev, "phase_oldest_artifact_age_min", oldest)
    return ev


# ---------------------------------------------------------------------------
# The seven menus
# ---------------------------------------------------------------------------

def _a_orient(base=None) -> dict:
    """The plan, and what orientation found before any sensing happened."""
    ev: dict = {}
    plan = _json("memory/brain_cycle_plan.json", base)
    if isinstance(plan, dict):
        _put(ev, "plan_things_to_watch", len(plan.get("things_to_watch") or []) or None)
        _put(ev, "plan_suspicions", len(plan.get("suspicions") or []) or None)
        _put(ev, "plan_focus_chars", len(str(plan.get("focus") or "")) or None)
        _put(ev, "plan_seconds", plan.get("_sec"))
    _put(ev, "plan_age_min", _age_min("memory/brain_cycle_plan.json", base))

    dep = _json("snapshots/master/dependency_check_latest.json", base)
    if isinstance(dep, dict):
        checks = dep.get("checks")
        if isinstance(checks, dict):
            ev["dependency_checks"] = len(checks)
            ev["dependency_checks_failed"] = sum(
                1 for v in checks.values()
                if (v is False) or (isinstance(v, dict) and not v.get("ok", True)))
        elif isinstance(checks, list):
            ev["dependency_checks"] = len(checks)
            ev["dependency_checks_failed"] = sum(
                1 for v in checks if isinstance(v, dict) and not v.get("ok", True))
        _put(ev, "thinking_paths", len(dep.get("thinking_paths") or []) or None)

    needs = _json("snapshots/master/needs_reanalysis_latest.json", base)
    if isinstance(needs, dict):
        _put(ev, "needs_reanalysis_count", needs.get("count"))
        _put(ev, "needs_reanalysis_axes", len(needs.get("axes") or []) or None)

    _put(ev, "canon_frame_chars", _size("memory/active_canon_frame.txt", base))
    stance = _json("memory/brain_stance.json", base)
    if isinstance(stance, dict):
        _put(ev, "stance_fields", len(stance) or None)
    return ev


def _b_sense(base=None) -> dict:
    """What the collectors brought back, and what the source registry believes."""
    ev: dict = {}
    web = _json("memory/web_intelligence/latest.json", base)
    if isinstance(web, dict):
        _put(ev, "web_axes_covered", web.get("axes_covered"))
        _put(ev, "web_total_sources", web.get("total_sources"))
        _put(ev, "web_youtube_videos", web.get("youtube_videos_total"))
        for k, out in (("critical_axes", "web_critical_axes"),
                       ("deteriorating_axes", "web_deteriorating_axes"),
                       ("problems_found", "web_problems_found")):
            v = web.get(k)
            _put(ev, out, len(v) if isinstance(v, (list, dict)) else v)

    try:
        from core import source_lifecycle
        s = source_lifecycle.summary()
        for state, count in (s or {}).items():
            ev[f"sources_{str(state).lower()}"] = count
    except Exception:
        pass
    _put(ev, "source_lifecycle_rows", _lines("memory/source_lifecycle_ledger.jsonl", base))

    dead = _json("config/dead_sources.json", base)
    if isinstance(dead, dict):
        body = dead.get("sources") if isinstance(dead.get("sources"), dict) else dead
        _put(ev, "dead_sources", sum(1 for k in body if not str(k).startswith("_")) or None)

    comp = _json("memory/composed_indicators.json", base)
    if isinstance(comp, dict):
        _put(ev, "composed_indicators", len(comp) or None)
    _put(ev, "grounding_ledger_rows", _lines("memory/grounding_ledger.jsonl", base))

    news = _json("news/news_latest.json", base)
    if isinstance(news, dict):
        items = news.get("items") or news.get("articles") or news.get("news")
        _put(ev, "news_items", len(items) if isinstance(items, list) else len(news))
    elif isinstance(news, list):
        _put(ev, "news_items", len(news))
    return ev


def _c_snapshot(base=None) -> dict:
    """The snapshots this phase wrote, and the archive that sealed them."""
    ev: dict = {}
    spec = _phases_spec(base).get("C_SNAPSHOT") or {}
    fresh = 0
    for rel in (spec.get("produces") or []):
        age = _age_min(rel, base)
        if age is not None and age <= 180:
            fresh += 1
    ev["snapshots_fresh_3h"] = fresh

    try:
        root = _p("cortex_memory/archive/merkle_root.txt", base).read_text(
            encoding="utf-8").strip()
        _put(ev, "merkle_root_hex_len", len(root) or None)
        _put(ev, "merkle_root_head", int(root[:6], 16) if len(root) >= 6 else None)
    except Exception:
        pass
    try:
        arch = _p("cortex_memory/archive", base)
        _put(ev, "archive_cycles", sum(1 for d in arch.iterdir() if d.is_dir()) or None)
    except Exception:
        pass

    # The snapshot tree as a whole — how much was actually written, in files.
    try:
        snaps = list(_p("snapshots", base).rglob("*_latest.json"))
        ev["snapshot_latest_files"] = len(snaps)
        stale = sum(1 for s in snaps
                    if (datetime.now(timezone.utc).timestamp() - s.stat().st_mtime)
                    > 26 * 3600)
        ev["snapshots_stale_over_26h"] = stale
    except Exception:
        pass
    return ev


def _d_score(base=None) -> dict:
    """The composite, its coverage, the movement, and the level corrections."""
    ev: dict = {}
    goal = _json("snapshots/master/goal_score_latest.json", base)
    if isinstance(goal, dict):
        for k in ("composite_score", "coverage_of_goal", "coverage_of_measurable",
                  "measured_weight", "measurable_weight", "unmeasured_weight",
                  "semantic_axes", "semantic_weight", "sensors_ok"):
            _put(ev, k, goal.get(k))
        _put(ev, "unmeasured_axes", len(goal.get("unmeasured_axes") or []) or None)
        details = goal.get("metric_details")
        if isinstance(details, dict):
            ev["metrics_total"] = len(details)
            ev["metrics_measured"] = sum(
                1 for d in details.values()
                if isinstance(d, dict) and d.get("measured"))

    hist = _json("memory/goal_score_history.json", base)
    rows = hist.get("history") if isinstance(hist, dict) else hist
    if isinstance(rows, list) and rows:
        ev["score_history_rows"] = len(rows)
        try:
            def _c(r):
                return (r.get("composite_score") if isinstance(r, dict)
                        else None)
            last = _c(rows[-1])
            prev = _c(rows[-2]) if len(rows) > 1 else None
            if last is not None and prev is not None:
                ev["composite_delta"] = round(float(last) - float(prev), 4)
        except Exception:
            pass

    scores = _json("output/cortex_scores_latest.json", base)
    if isinstance(scores, dict):
        _put(ev, "axes_scored", scores.get("total_axes"))
        s = scores.get("scores")
        if isinstance(s, dict):
            _put(ev, "axes_with_a_score", len(s) or None)

    levels = _json("memory/auto_levels.json", base)
    if isinstance(levels, dict):
        _put(ev, "auto_levels", len(levels) or None)
    _put(ev, "level_corrections_rows", _lines("memory/level_corrections.jsonl", base))

    ded = _json("memory/deductions_latest.json", base)
    if isinstance(ded, dict):
        c = ded.get("conclusions") or ded.get("rows")
        _put(ev, "deductions", len(c) if isinstance(c, list) else None)
    return ev


def _e_propose(base=None) -> dict:
    """What was filed, what is queued, and how old the queue is."""
    ev: dict = {}
    prop = _json("memory/improvement_proposals.json", base)
    rows = prop.get("proposals") if isinstance(prop, dict) else prop
    if isinstance(rows, list):
        ev["proposals_total"] = len(rows)
        by_status: dict = {}
        for r in rows:
            if isinstance(r, dict):
                by_status[str(r.get("status") or "unknown")] = \
                    by_status.get(str(r.get("status") or "unknown"), 0) + 1
        for status, n in sorted(by_status.items()):
            ev[f"proposals_{re.sub(r'[^a-z0-9_]', '_', status.lower())}"] = n

    plan = _json("snapshots/body/growth_plan_latest.json", base)
    if isinstance(plan, dict):
        acts = plan.get("actions") or plan.get("plan") or plan.get("steps")
        _put(ev, "growth_plan_actions", len(acts) if isinstance(acts, list) else None)
        _put(ev, "growth_plan_bytes", _size("snapshots/body/growth_plan_latest.json", base))

    try:
        q = _p("openclaw_queue", base)
        _put(ev, "openclaw_queue_files",
             sum(1 for f in q.iterdir() if f.is_file()) if q.exists() else None)
    except Exception:
        pass
    _put(ev, "axis_feed_rows", _lines("openclaw_queue/axis_feeds.jsonl", base))
    return ev


def _f_self(base=None) -> dict:
    """The mirror's judgements on itself, and the step contract's verdicts."""
    ev: dict = {}
    m = _json("memory/self_mirror_latest.json", base)
    if isinstance(m, dict):
        cal = m.get("calibration")
        if isinstance(cal, dict):
            for k in ("judgements_paired", "false_alarms", "justified_doubts",
                      "missed_failures", "confirmed", "undecidable"):
                _put(ev, f"mirror_{k}", cal.get(k))
        deb = m.get("debriefs")
        if isinstance(deb, dict):
            _put(ev, "mirror_debriefs_accepted", deb.get("accepted"))
            _put(ev, "mirror_debriefs_rejected", deb.get("rejected"))
            ph = deb.get("phases_missing")
            _put(ev, "mirror_phases_missing",
                 len(ph) if isinstance(ph, list) else ph)
        st = m.get("stances")
        if isinstance(st, dict):
            _put(ev, "mirror_stances_total", st.get("total"))
            _put(ev, "mirror_stances_silent", st.get("silent"))

    contract = _json("memory/step_contract_latest.json", base)
    steps = contract.get("steps") if isinstance(contract, dict) else None
    if isinstance(steps, list):
        ev["contract_steps_judged"] = len(steps)
        verdicts: dict = {}
        for s in steps:
            if isinstance(s, dict):
                v = str(s.get("verdict") or "UNKNOWN")
                verdicts[v] = verdicts.get(v, 0) + 1
        for v, n in sorted(verdicts.items()):
            ev[f"contract_{v.lower()}"] = n
    return ev


def _g_learn(base=None) -> dict:
    """What the cycle learned: experiments, training rows, journals."""
    ev: dict = {}
    exp = _json("memory/self_experiments.json", base)
    rows = exp.get("experiments") if isinstance(exp, dict) else exp
    if isinstance(rows, list):
        ev["experiments_total"] = len(rows)
        by_state: dict = {}
        for r in rows:
            if isinstance(r, dict):
                k = str(r.get("state") or r.get("status") or "unknown").lower()
                by_state[k] = by_state.get(k, 0) + 1
        for k, n in sorted(by_state.items()):
            ev[f"experiments_{re.sub(r'[^a-z0-9_]', '_', k)}"] = n

    _put(ev, "training_log_rows", _lines("memory/training_log.jsonl", base))
    _put(ev, "mirror_log_rows", _lines("memory/self_mirror_log.jsonl", base))

    for rel, key in (("memory/feedback_log.json", "feedback_rows"),
                     ("memory/development_journal.json", "journal_rows"),
                     ("memory/axis_history.json", "axis_history_axes"),
                     ("memory/runtime_experiences.json", "runtime_experiences")):
        d = _json(rel, base)
        if isinstance(d, list):
            ev[key] = len(d)
        elif isinstance(d, dict):
            for cand in ("entries", "log", "rows", "history", "experiences"):
                if isinstance(d.get(cand), list):
                    ev[key] = len(d[cand])
                    break
            else:
                ev[key] = len(d)
    return ev


_MENUS = {
    "A_ORIENT":   _a_orient,
    "B_SENSE":    _b_sense,
    "C_SNAPSHOT": _c_snapshot,
    "D_SCORE":    _d_score,
    "E_PROPOSE":  _e_propose,
    "F_SELF":     _f_self,
    "G_LEARN":    _g_learn,
}


# ---------------------------------------------------------------------------
# The public surface
# ---------------------------------------------------------------------------

def menu(phase: str, base: pathlib.Path | None = None) -> dict:
    """This phase's own facts. Never raises; a broken reader costs one key."""
    ev: dict = {"phase": phase}
    try:
        ev.update(_structural(phase, base))
    except Exception:
        pass
    fn = _MENUS.get(phase)
    if fn is not None:
        try:
            ev.update(fn(base))
        except Exception as exc:  # noqa: BLE001
            ev["menu_error"] = f"{type(exc).__name__}: {exc}"
    return ev


def all_menus(base: pathlib.Path | None = None) -> dict:
    return {p: menu(p, base) for p in PHASES}


def numbers_of(evidence: dict) -> set:
    """Every number that appears anywhere in a menu, as written."""
    blob = json.dumps(evidence, ensure_ascii=False, default=str)
    return {m.group(0).replace(",", ".") for m in _NUMBER.finditer(blob)}


def own_numbers(phase: str, menus: dict | None = None,
                base: pathlib.Path | None = None) -> set:
    """The numbers in THIS phase's menu that appear in NO other phase's menu.

    This is the whole basis of the swap test: a debrief that cites one of these
    could not have been written about another phase. A debrief that cites only
    numbers outside this set may be true, but nothing in it distinguishes the
    phase it is supposedly about.
    """
    ms = menus if menus is not None else all_menus(base)
    mine = numbers_of(ms.get(phase) or {})
    theirs: set = set()
    for other, ev in ms.items():
        if other != phase:
            theirs |= numbers_of(ev)
    return mine - theirs


# ---------------------------------------------------------------------------
# Selftest — the uniqueness property is MEASURED against the live repo
# ---------------------------------------------------------------------------

def uniqueness_table(base: pathlib.Path | None = None) -> list:
    ms = all_menus(base)
    rows = []
    for p in PHASES:
        own = own_numbers(p, ms)
        rows.append({
            "phase": p,
            "facts": len(ms[p]) - 1,          # minus the "phase" label itself
            "numbers": len(numbers_of(ms[p])),
            "own": len(own),
            "sample": sorted(own, key=lambda s: (len(s), s))[:6],
        })
    return rows


def _selftest() -> int:
    print("core/phase_evidence.py --selftest")
    ok = True
    rows = uniqueness_table()
    print(f"  {'phase':<12}{'facts':>6}{'numbers':>9}{'own':>6}   sample of its own numbers")
    for r in rows:
        good = r["own"] >= MIN_OWN_NUMBERS
        ok = ok and good
        print(f"  {'OK  ' if good else 'FAIL'} {r['phase']:<8}{r['facts']:>5}"
              f"{r['numbers']:>9}{r['own']:>6}   {', '.join(r['sample'])}")

    # The generic composite must NOT be every phase's number any more.
    ms = all_menus()
    holders = [p for p in PHASES if "composite_score" in ms[p]]
    good = holders == ["D_SCORE"]
    ok = ok and good
    print(f"  {'OK  ' if good else 'FAIL'}  composite_score belongs to D_SCORE alone "
          f"(holders: {holders})")

    # A menu must never collapse to nothing: an empty menu passes the number
    # gate on its own step count and says nothing.
    for p in PHASES:
        good = len(ms[p]) > 3
        ok = ok and good
        if not good:
            print(f"  FAIL  {p} menu has only {len(ms[p])} keys")

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--show" in sys.argv:
        which = sys.argv[sys.argv.index("--show") + 1]
        print(json.dumps(menu(which), ensure_ascii=False, indent=2))
        print("own numbers:", sorted(own_numbers(which)))
        sys.exit(0)
    sys.exit(_selftest())
