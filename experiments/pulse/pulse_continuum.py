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
    prev_anom = ((prev.get("mind") or {}).get("penumbra_anomalies"))
    anom = (ctx["penumbra"].get("by_reason") or {}).get("model_anomaly", 0)
    if anom and (not isinstance(prev_anom, int) or anom > prev_anom):
        add("penumbra_model_anomaly_new", f"{anom} model_anomaly item(s) — model may be broken")
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
                 "series_stalled_axes": ctx["stalled"]},
        "spirit": {"composite": ctx["composite"], "worst_gap_axis": ctx["worst_gap_axis"],
                   "ideas_pending": ctx["ideas_pending"]},
        "necessity": nec,
    }


# ── 5. WAKING ACTIONS (may wake; never writes scoring or specs) ──────────────

def request_extraordinary_cycle() -> str:
    """SPEC GAP, flagged not improvised: supervisor.py has no flag-file intake. decide()
    is a pure function of (now, state, heartbeat, lock, cfg) and its only START paths are
    daily_hour and catch-up. Writing a request file nothing reads would be a silent no-op
    dressed as a trigger, so the pulse reports the gap instead of faking the capability."""
    return "unavailable:no_supervisor_intake"


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
    if keys & {"composite_moved", "series_stalled"}:
        acted.append(f"cycle_request={request_extraordinary_cycle()}")
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
