#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/pulse/pulse_continuum.py — the continuous mind/spirit/body continuum (#50).

Every 5 minutes the system takes its own pulse. Almost every tick is SILENT: it appends
one self-state line and stops. That silence is the point — the stream IS the continuum,
and a system that acts on every tick is not alive, it is twitching.

Discipline:
  MORAL CORE FIRST     the canon loads or the tick runs [degraded]. There is no tick
                       without a goal frame to be a self against.
  DETERMINISTIC CORE   necessity is arithmetic over named thresholds in config/pulse.json
                       (human-owned). Every contribution is NAMED in reasons[], so a wake
                       is explainable after the fact and a non-wake is auditable.
  WAKING, NOT WRITING  over threshold the pulse may WAKE things. It never writes a score,
                       a spec, or a hypothesis. LLM touches only the reflection and the
                       articulation of ideas, both explicitly labelled subjective.

  venv/Scripts/python.exe experiments/pulse/pulse_continuum.py          # one tick
  venv/Scripts/python.exe experiments/pulse/pulse_continuum.py --dry    # no side effects
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (REPO, REPO / "experiments" / "sensorium", REPO / "experiments" / "needs",
           REPO / "experiments" / "symbolic_duel", REPO / "experiments" / "browser_scout"):
    sys.path.insert(0, str(_p))

CONFIG      = REPO / "config" / "pulse.json"
STREAM      = REPO / "memory" / "pulse_stream.jsonl"
IDEAS       = REPO / "memory" / "idea_stream.jsonl"
PRIORITY    = REPO / "memory" / "self_directed_priority.json"
COMPOSER_ST = REPO / "memory" / "composer_state"
NEEDS_FILE  = REPO / "memory" / "composer_needs.json"
PENDING     = REPO / "memory" / "pending_approvals.json"
SCORES      = REPO / "output" / "cortex_scores_latest.json"

_FALLBACK_CORE = ("CORTEX goal — a sustainable, dignified civilization: peace, dignity, "
                  "ecological sustainability, freedom, truth, shared abundance.")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def cfg():
    return _load(CONFIG, {"threshold": 4, "weights": {}})


def _tail(path, k):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for l in lines[-k:]:
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return out


# ── 1. MORAL CORE ────────────────────────────────────────────────────────────

def moral_core() -> tuple:
    """(frame, degraded). The tick cannot run without a goal frame; it falls open to the
    grounded fallback rather than proceeding with no centre at all."""
    try:
        from core.canon import as_frame
        f = as_frame()
        if f and f.strip():
            return f, False
    except Exception:
        pass
    return _FALLBACK_CORE, True


# ── 2. CONTEXT (cheap reads only) ────────────────────────────────────────────

def _port_alive(port=11434, host="127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except Exception:
        return False


def body_read() -> dict:
    try:
        free_gb = round(shutil.disk_usage(str(REPO)).free / 1e9, 1)
    except Exception:
        free_gb = None
    ram_pct = None
    try:
        import psutil
        ram_pct = round(psutil.virtual_memory().percent, 1)
    except Exception:
        pass
    return {"disk_gb": free_gb, "ram_pct": ram_pct, "ollama_alive": _port_alive()}


def stalled_axes(hours: float) -> list:
    """Axes whose newest series point is older than `hours` — a series that stopped
    moving is a sense that stopped sensing."""
    out = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for f in sorted(COMPOSER_ST.glob("*.json")) if COMPOSER_ST.exists() else []:
        st = _load(f, {}).get("sources", {})
        newest = None
        for s in st.values():
            for ts, _v in (s.get("history") or []):
                try:
                    d = datetime.fromisoformat(ts)
                except Exception:
                    continue
                if newest is None or d > newest:
                    newest = d
        if newest is not None and newest < cutoff:
            out.append(f.stem)
    return out


def context(c: dict) -> dict:
    prev = _tail(STREAM, c.get("context_lines", 24))
    pri = _load(PRIORITY, {})
    needs = _load(NEEDS_FILE, {})
    needs_total = sum(len((v or {}).get("items", [])) for v in needs.values())
    try:
        import sensorium
        v = sensorium.verify()
        leaf_n = v["verified"]["n"]
        pen = sensorium.penumbra_report()
        unconsumed = _unconsumed(sensorium)
    except Exception:
        leaf_n, pen, unconsumed = 0, {"n_active": 0, "by_reason": {}}, 0
    return {
        "prev": prev,
        "body": body_read(),
        "leaf_n": leaf_n,
        "new_drops": unconsumed,
        "penumbra": pen,
        "needs_total": needs_total,
        "stalled": stalled_axes(c.get("series_stall_hours", 26)),
        "composite": pri.get("composite"),
        "worst_gap_axis": pri.get("priority_axis"),
        "approvals": len((_load(PENDING, {}).get("approvals") or {})),
        "ideas_pending": sum(1 for i in _tail(IDEAS, 500) if i.get("outcome") is None),
    }


def _unconsumed(sensorium) -> int:
    leaves = sensorium._read_leaves(sensorium.LEAVES)
    done = set(_load(sensorium.CONSUMED, {"ids": []}).get("ids", []))
    return sum(1 for lf in leaves if lf["id"] not in done)


# ── 4. NECESSITY (deterministic, every contribution named) ───────────────────

def necessity(ctx: dict, c: dict) -> dict:
    w = c.get("weights", {})
    prev = ctx["prev"][-1] if ctx["prev"] else {}
    score, reasons = 0, []

    def add(key, why):
        nonlocal score
        pts = int(w.get(key, 0))
        if pts:
            score += pts
            reasons.append({"key": key, "points": pts, "why": why})

    if ctx["new_drops"] > 0:
        add("unconsumed_drops", f"{ctx['new_drops']} unconsumed drop(s) in the sensorium")
    prev_needs = ((prev.get("mind") or {}).get("needs_total"))
    if isinstance(prev_needs, int) and ctx["needs_total"] > prev_needs:
        add("needs_increased", f"needs {prev_needs} -> {ctx['needs_total']}")
    if ctx["stalled"]:
        add("series_stalled", f"series stalled >{c.get('series_stall_hours', 26)}h: "
                              f"{', '.join(ctx['stalled'][:4])}")
    prev_comp = ((prev.get("spirit") or {}).get("composite"))
    if isinstance(prev_comp, (int, float)) and isinstance(ctx["composite"], (int, float)):
        if abs(ctx["composite"] - prev_comp) > c.get("composite_move", 0.02):
            add("composite_moved", f"composite {prev_comp} -> {ctx['composite']}")
    dg = ctx["body"].get("disk_gb")
    if isinstance(dg, (int, float)) and dg < c.get("disk_free_gb_min", 10):
        add("disk_low", f"disk free {dg}GB")
    if not ctx["body"].get("ollama_alive"):
        add("ollama_dead", "ollama port 11434 not answering")
    if ctx["approvals"]:
        add("approvals_pending", f"{ctx['approvals']} approval(s) awaiting a human")
    # ORIGIN-RESTRICTED: only anomalies from OUTSIDE the system's own ideation count.
    # An idea the system had about itself must never raise its own necessity.
    prev_anom = ((prev.get("mind") or {}).get("penumbra_anomalies_external"))
    anom = external_anomalies(ctx["penumbra"])
    if anom and (not isinstance(prev_anom, int) or anom > prev_anom):
        add("penumbra_model_anomaly_new",
            f"{anom} externally-sourced model_anomaly item(s) — model may be broken")
    return {"score": score, "reasons": reasons}


# ── 3. SELF-STATE LINE ───────────────────────────────────────────────────────

def state_line(ctx: dict, nec: dict, degraded: bool) -> dict:
    return {
        "ts": _now(),
        "degraded_core": degraded,
        "body": {"disk_gb": ctx["body"].get("disk_gb"),
                 "ram_pct": ctx["body"].get("ram_pct"),
                 "ollama_alive": ctx["body"].get("ollama_alive")},
        "mind": {"needs_total": ctx["needs_total"], "new_drops": ctx["new_drops"],
                 "penumbra_active": ctx["penumbra"].get("n_active", 0),
                 "penumbra_anomalies": (ctx["penumbra"].get("by_reason") or {}).get(
                     "model_anomaly", 0),
                 # split out on purpose: the inflation monitor needs to see whether
                 # anomalies are coming from the world or from the system's own head
                 "penumbra_anomalies_external": external_anomalies(ctx["penumbra"]),
                 "penumbra_anomaly_origins": (ctx["penumbra"].get(
                     "anomalies_by_origin") or {}),
                 "series_stalled_axes": ctx["stalled"]},
        "spirit": {"composite": ctx["composite"], "worst_gap_axis": ctx["worst_gap_axis"],
                   "ideas_pending": ctx["ideas_pending"]},
        "necessity": nec,
        "rates": rates(),          # arrival rates, for the convergence monitor
    }


# ── 5. WAKING ACTIONS (may wake; never writes scoring or specs) ──────────────

CYCLE_PROPOSALS = REPO / "memory" / "pulse_cycle_requests.json"

# ONLY these warrant waking the whole daily cycle. Routine housekeeping — unconsumed
# drops, a needs bump, pending approvals — is handled by the waking actions themselves
# and must never escalate to a full cycle, or the pulse becomes a scheduler.
_CYCLE_WORTHY = ("composite_moved", "penumbra_model_anomaly_new")

# ORIGIN RESTRICTION. An anomaly born from the system's OWN ideation is a thought about
# itself; an anomaly born from a collector reading the world is evidence. Only evidence
# may ever move anything. Without this the loop closes on itself: ideate -> anomaly ->
# necessity spike -> request a cycle -> more ideation. Auto-stimulation, dressed as need.
# "unknown" is counted as self-originated ON PURPOSE: an anomaly whose provenance we
# cannot establish must not be allowed to raise the system's own necessity. Fail-closed
# against auto-stimulation, at the cost of ignoring pre-existing leaves that predate the
# collector field.
_SELF_ORIGINS = ("pulse_ideation", "unknown")


def external_anomalies(pen: dict) -> int:
    """model_anomaly items that came from OUTSIDE the system's own thinking."""
    origins = (pen or {}).get("anomalies_by_origin") or {}
    return sum(n for o, n in origins.items() if o not in _SELF_ORIGINS)


RATE_BASELINE = REPO / "memory" / "pulse_rate_baseline.json"


def ensure_baseline() -> dict:
    """Freeze what the anomaly-arrival rate looked like BEFORE this feature existed.

    Without a pre-enable baseline the monitor can only say 'anomalies exist', which is
    useless. With one it can ask the question that matters: did giving the system a way to
    ask for cycles make it start producing more of the thing that justifies asking?"""
    b = _load(RATE_BASELINE, None)
    if b:
        return b
    enabled_at = _now()
    try:
        import sensorium
        pre = sensorium.anomaly_arrivals(until_iso=enabled_at)
        first = None
        for lf in sensorium._read_leaves(sensorium.PENUMBRA_LEAVES):
            ts = str(lf.get("ts", ""))
            if ts and (first is None or ts < first):
                first = ts
        weeks = 1.0
        if first:
            try:
                span = (datetime.fromisoformat(enabled_at)
                        - datetime.fromisoformat(first)).total_seconds() / 604800.0
                weeks = max(span, 1.0)
            except Exception:
                pass
        rate = round(pre / weeks, 3)
    except Exception:
        rate = 0.0
    b = {"enabled_at": enabled_at, "baseline_anomalies_per_week": rate,
         "note": "pre-enable arrival rate; the monitor compares post-enable weeks to this"}
    try:
        RATE_BASELINE.parent.mkdir(parents=True, exist_ok=True)
        RATE_BASELINE.write_text(json.dumps(b, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception:
        pass
    return b


def rates() -> dict:
    """Arrival rates, recorded on every stream line so the trend is inspectable later."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    out = {"anomaly_arrivals_7d": 0, "anomaly_arrivals_7d_external": 0,
           "cycle_requests_7d": 0}
    try:
        import sensorium
        out["anomaly_arrivals_7d"] = sensorium.anomaly_arrivals(since_iso=week_ago)
        out["anomaly_arrivals_7d_external"] = sensorium.anomaly_arrivals(
            since_iso=week_ago, exclude_origins=_SELF_ORIGINS)
    except Exception:
        pass
    try:
        hist = (_load(CYCLE_PROPOSALS, {}).get("history") or [])
        out["cycle_requests_7d"] = sum(1 for h in hist if str(h.get("ts", "")) >= week_ago)
    except Exception:
        pass
    return out


def propose_extraordinary_cycle(reasons) -> str:
    """PROPOSE a cycle — the system does not set its own alarm clock.

    The pulse may notice that a full cycle looks warranted and register it as an approval
    item; Emil's "OK <id>" is what makes approve_reader write the supervisor's request
    file. System proposes, human disposes. This function therefore writes a PROPOSAL that
    only the needs report reads — never anything the supervisor honours."""
    worthy = [r for r in reasons if r.get("key") in _CYCLE_WORTHY]
    if not worthy:
        return "not_proposed:no_cycle_worthy_reason"
    try:
        reason = "; ".join(f"{r['key']}: {r['why']}" for r in worthy)
        CYCLE_PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
        doc = _load(CYCLE_PROPOSALS, {})
        doc["pending"] = {"ts": _now(), "proposed_by": "pulse_continuum",
                          "reason": reason,
                          "keys": [r["key"] for r in worthy]}
        doc["history"] = ([h for h in (doc.get("history") or [])][-50:]
                          + [{"ts": _now(), "keys": [r["key"] for r in worthy]}])
        CYCLE_PROPOSALS.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        return "proposed:" + ",".join(r["key"] for r in worthy)
    except Exception as e:
        return f"propose_failed:{type(e).__name__}"


def wake(nec: dict, ctx: dict, dry: bool) -> list:
    keys = {r["key"] for r in nec["reasons"]}
    acted = []
    if dry:
        return [f"dry:{k}" for k in sorted(keys)]
    if "unconsumed_drops" in keys:
        try:
            import sensorium
            acted.append(f"sensorium.ingest={sensorium.ingest().get('ingested', 0)}")
        except Exception as e:
            acted.append(f"sensorium.ingest FAILED {type(e).__name__}")
    if keys & {"needs_increased", "approvals_pending", "penumbra_model_anomaly_new"}:
        try:
            import needs_report
            acted.append(f"needs_push={needs_report._push_status(needs_report.build())}")
        except Exception as e:
            acted.append(f"needs_push FAILED {type(e).__name__}")
    if "ollama_dead" in keys:
        try:
            exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
            if exe.exists():
                import subprocess
                subprocess.Popen([str(exe), "serve"],
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                acted.append("ollama=started")
            else:
                acted.append("ollama=binary_missing")
        except Exception as e:
            acted.append(f"ollama FAILED {type(e).__name__}")
    if keys & set(_CYCLE_WORTHY):
        acted.append(f"cycle_proposal={propose_extraordinary_cycle(nec['reasons'])}")
    return acted


# ── 6. HOURLY REFLECTION (subjective, never numeric) ─────────────────────────

def reflection(ctx: dict, frame: str) -> dict:
    """One grounded sentence, on the stream and the canon only. Skipped silently when the
    model is dead — a missing reflection is not an event."""
    if not ctx["body"].get("ollama_alive"):
        return {}
    try:
        from autonomous_scout import _local
        k = len(ctx["prev"])
        lines = json.dumps(ctx["prev"][-8:], ensure_ascii=False)[:2500]
        out = _local(
            f"{frame}\n\nBelow are the system's own recent self-state lines.\n{lines}\n\n"
            f"In ONE sentence, say what you notice about this system's condition. "
            f"No numbers, no advice, no invented facts — only what the lines show.",
            timeout=120, num_predict=90)
        s = str(out).strip().split("\n")[0][:300]
        return {"reflection": s, "grounded_on": k, "subjective": True} if s else {}
    except Exception:
        return {}


# ── 7. IDEATION (deterministic seeds, LLM articulation, guarded) ─────────────

def seeds_rule_violation() -> list:
    try:
        import metta_oracle
        lv = metta_oracle.levels_from_scores()
        res = metta_oracle.ask(lv)
        if not res.get("ok"):
            return []
        return [{"kind": "hypothesis", "seed": "rule_violation", "axis": b["axis"],
                 "proof": b.get("proofs", []),
                 "detail": f"{b['axis']} scored {b['scored']} but rules imply >= {b['implied']}"}
                for b in res.get("inconsistencies", [])]
    except Exception:
        return []


def seeds_trend(min_points=5) -> list:
    out = []
    for f in sorted(COMPOSER_ST.glob("*.json")) if COMPOSER_ST.exists() else []:
        for sid, s in (_load(f, {}).get("sources") or {}).items():
            hist = [v for _t, v in (s.get("history") or [])
                    if isinstance(v, (int, float))]
            if len(hist) < min_points:
                continue
            tail = hist[-min_points:]
            up = all(b >= a for a, b in zip(tail, tail[1:]))
            down = all(b <= a for a, b in zip(tail, tail[1:]))
            if up or down:
                out.append({"kind": "hypothesis", "seed": "trend", "axis": f.stem,
                            "source": sid, "series_tail": tail,
                            "detail": f"{sid} moved monotonically "
                                      f"{'up' if up else 'down'} over {min_points} points"})
    return out


def _refs_exist(refs) -> bool:
    """grounded_on must point at things that EXIST. An idea grounded on an invented file
    is a hallucination with a citation."""
    if not refs:
        return False
    for r in refs:
        p = REPO / str(r).split("#", 1)[0].strip()
        if not p.exists():
            return False
    return True


def articulate(seed: dict, frame: str) -> dict:
    from autonomous_scout import _local, _json_from
    horizon = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    out = _local(
        f"{frame}\n\nA deterministic check produced this seed:\n{json.dumps(seed)[:900]}\n\n"
        f"Turn it into ONE testable idea. Reply ONLY JSON:\n"
        f'{{"idea": "<one sentence>", "grounded_on": ["<repo-relative file paths that '
        f'already exist and support this>"], "dimension": "<one word>", '
        f'"falsifiable_test": "<a concrete check>", "horizon": "{horizon}"}}',
        timeout=180, num_predict=350)
    return _json_from(out)


def ideate(frame: str, dry: bool) -> dict:
    seeds = seeds_rule_violation() + seeds_trend()
    result = {"seeds": len(seeds), "kept": [], "rejected": [], "penumbra": []}
    for s in seeds[:6]:
        try:
            got = articulate(s, frame)
        except Exception as e:
            result["rejected"].append({"seed": s.get("detail"), "why": f"articulate failed: {type(e).__name__}"})
            continue
        idea = str(got.get("idea", "")).strip()
        refs = got.get("grounded_on") or []
        test = str(got.get("falsifiable_test", "")).strip()
        horizon = str(got.get("horizon", "")).strip()
        if not idea:
            result["rejected"].append({"seed": s.get("detail"), "why": "empty idea"})
            continue
        if not _refs_exist(refs):
            result["rejected"].append({"idea": idea[:90], "why": "ungrounded — grounded_on "
                                                                "refs do not exist"})
            continue
        if not test or not horizon:
            result["rejected"].append({"idea": idea[:90],
                                       "why": "no falsifiable_test with a horizon"})
            continue
        rec = {"ts": _now(), "idea": idea, "grounded_on": refs, "dimension":
               got.get("dimension"), "falsifiable_test": test, "kind": s.get("kind"),
               "seed": s.get("seed"), "test_horizon": horizon, "outcome": None}
        verdict = mentor(rec, s)
        rec["mentor"] = verdict
        if verdict.get("contradicts") and verdict.get("well_sourced"):
            # THE NOVELTY DOOR: it contradicts a known rule but stands on sourced
            # observation. That is not an error to discard, it is a wound in the model.
            rec["routed"] = "penumbra:model_anomaly"
            if not dry:
                try:
                    import sensorium
                    rec["penumbra_id"] = sensorium.drop(
                        s.get("axis", "GENERAL_SELF_REVIEW"), "semantic", rec,
                        collector="pulse_ideation",
                        quarantine={"reason": "model_anomaly"})
                except Exception as e:
                    rec["penumbra_error"] = f"{type(e).__name__}: {e}"
            result["penumbra"].append(rec)
        elif verdict.get("contradicts"):
            rec["routed"] = "mentor_rejected"      # KEPT as training material, not surfaced
            result["rejected"].append({"idea": idea[:90], "why": "mentor: contradiction",
                                       "proof": verdict.get("proof")})
            _append(IDEAS, rec, dry)
        else:
            rec["routed"] = "kept"
            result["kept"].append(rec)
            _append(IDEAS, rec, dry)
    return result


def mentor(rec: dict, seed: dict) -> dict:
    """MeTTa as mentor: does this idea contradict what the rules already say? A
    contradiction is not automatically fatal — see the novelty door in ideate()."""
    try:
        import metta_oracle
        res = metta_oracle.ask(metta_oracle.levels_from_scores())
        if not res.get("ok"):
            return {"checked": False}
        bad = [b for b in res.get("inconsistencies", []) if b["axis"] == seed.get("axis")]
        return {"checked": True, "contradicts": bool(bad),
                "proof": [p for b in bad for p in b.get("proofs", [])],
                "well_sourced": bool(rec.get("grounded_on")) and seed.get("seed") == "trend"}
    except Exception:
        return {"checked": False}


def _append(path, rec, dry):
    if dry:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def creative_due(ctx: dict, c: dict) -> bool:
    now = datetime.now(timezone.utc)
    if now.hour >= c.get("quiet_hour", 21):
        if not any(str(p.get("ts", ""))[:10] == now.date().isoformat()
                   and p.get("creative") for p in ctx["prev"]):
            return True
    fired = [p for p in ctx["prev"] if (p.get("necessity") or {}).get("score", 0)
             >= c.get("threshold", 4)]
    if ctx["prev"] and not fired:
        try:
            oldest = datetime.fromisoformat(ctx["prev"][0]["ts"])
            if (now - oldest) > timedelta(hours=c.get("no_fire_hours_for_creative", 6)):
                return True
        except Exception:
            pass
    return False


# ── the tick ─────────────────────────────────────────────────────────────────

def tick(dry: bool = False) -> dict:
    c = cfg()
    ensure_baseline()               # freeze the pre-enable rate on the very first tick
    frame, degraded = moral_core()
    ctx = context(c)
    nec = necessity(ctx, c)
    line = state_line(ctx, nec, degraded)

    n_ticks = len(_tail(STREAM, 100000))
    if (n_ticks + 1) % int(c.get("reflection_every_n_ticks", 12)) == 0:
        line.update(reflection(ctx, frame))

    if nec["score"] >= int(c.get("threshold", 4)):
        line["actions"] = wake(nec, ctx, dry)
    else:
        line["actions"] = []

    if creative_due(ctx, c):
        line["creative"] = ideate(frame, dry)

    _append(STREAM, line, dry)
    return line


if __name__ == "__main__":
    out = tick(dry="--dry" in sys.argv)
    print(json.dumps(out, ensure_ascii=False, indent=2))
