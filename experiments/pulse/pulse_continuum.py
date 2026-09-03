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
    # composite_moved is GONE from here on purpose. That comparison existed to justify an
    # escalation, so it now lives in the watchdog, against thresholds in
    # config/watchdog.json. The pulse reports the composite on the stream line and in the
    # signal; it no longer forms an opinion about whether the movement is big enough.
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

# Written by experiments/watchdog/trigger_watchdog.py, NOT by the pulse. Read here only
# to report a rate on the stream line — reading is not deciding.
CYCLE_PROPOSALS = REPO / "memory" / "pulse_cycle_requests.json"

# THE PULSE EMITS THIS AND STOPS. It is the raw signal, with no judgement attached: no
# thresholds, no qualification, no proposal. Whether any of it warrants a cycle is decided
# by a different process, because the process that computes an escalation must not be the
# process that benefits from it.
PULSE_SIGNAL = REPO / "memory" / "pulse_signal.json"

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


def build_signal(ctx: dict) -> dict:
    """The RAW signal: what is true, with no opinion about what it deserves.

    These same fields become the evidence a human is shown and the signature covers, so
    what Emil reads and what the supervisor honours cannot drift apart. The pulse's job
    ends here — it states the numbers and does not argue from them."""
    prev = ctx.get("prev")[-1] if ctx.get("prev") else {}
    pre = (prev.get("spirit") or {}).get("composite")
    post = ctx.get("composite")
    ev = {"pre_composite": pre, "post_composite": post,
          "delta": (round(post - pre, 6)
                    if isinstance(pre, (int, float)) and isinstance(post, (int, float))
                    else None),
          "anomaly_leaf_hash": None, "source_url": None, "rule_violated": None}
    try:
        import sensorium
        lf = sensorium.newest_anomaly(exclude_origins=_SELF_ORIGINS)
        if lf:
            ev["anomaly_leaf_hash"] = lf.get("leaf")
            ev["anomaly_drop_id"] = lf.get("id")
            rec = _load(REPO / lf["path"], {})
            pay = rec.get("payload") or {}
            ev["source_url"] = (pay.get("url") or pay.get("source_url")
                                or (pay.get("grounded_on") or [None])[0])
            proof = ((pay.get("mentor") or {}).get("proof") or [])
            ev["rule_violated"] = (pay.get("rule_violated")
                                   or (proof[0] if proof else None))
    except Exception:
        pass
    return ev


def emit_signal(ctx: dict) -> str:
    """Write the raw signal and stop. This replaces propose_extraordinary_cycle().

    The pulse used to decide whether a movement qualified as cycle-worthy and then write
    its own proposal. It no longer does either: it states the numbers, and
    experiments/watchdog/trigger_watchdog.py — a separate process, on its own schedule,
    with thresholds it reads and never computes — decides what they deserve."""
    sig = {"ts": _now(), **build_signal(ctx)}
    try:
        PULSE_SIGNAL.parent.mkdir(parents=True, exist_ok=True)
        PULSE_SIGNAL.write_text(json.dumps(sig, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        return "signal_written"
    except Exception as e:
        return f"signal_failed:{type(e).__name__}"


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
    # NOTE: no extraordinary-cycle branch here any more. The pulse cannot propose one; it
    # emits the signal every tick (see tick()) and the watchdog decides. Waking actions
    # remain the pulse's own business — they touch nothing the supervisor honours.
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


MIN_DISTINCT_VALUES = 3      # a trend has to MOVE, and move more than once


def seeds_trend(min_points=5, min_distinct=MIN_DISTINCT_VALUES) -> list:
    """Series that actually moved. A constant resampled is not a trend.

    THE BUG, measured 2026-08-04: 27 of the 40 trend seeds were series whose last five
    values were IDENTICAL — gi_temp_anomaly [1.19]*5, gi_confirmed_exoplanets [6333.0]*5,
    gi_unemployment [4.7913]*5 — every one of them announced as "moved monotonically up
    over 5 points". `all(b >= a)` is vacuously true for a flat run, so a constant passed
    as a rising trend.

    These are ANNUAL indicators (World Bank, NASA counts) that the composer re-samples
    every cycle. The value cannot change between cycles; the "history" is one yearly
    figure photographed five times. The ideas generated on 2026-08-04 stood on exactly
    this — including a hypothesis about confirmed exoplanets "moving up" from a number
    that had not moved at all.

    That is the system manufacturing a claim its own data does not support: precisely
    the gap between stated and measured that CORTEX exists to detect, turned inward. A
    flat series is not a trend to explain, it is a STALLED one — which the pulse already
    has a concept for (series_stalled in necessity()) and was contradicting here.

    So a direction now requires real movement: monotonic AND ends away from where it
    started AND changes value at least `min_distinct` times. Conservative on purpose —
    a single step ([0,0,1,1,1]) is an event, not a trend, and gets no seed."""
    out = []
    for f in sorted(COMPOSER_ST.glob("*.json")) if COMPOSER_ST.exists() else []:
        for sid, s in (_load(f, {}).get("sources") or {}).items():
            hist = [v for _t, v in (s.get("history") or [])
                    if isinstance(v, (int, float))]
            if len(hist) < min_points:
                continue
            tail = hist[-min_points:]
            if len(set(tail)) < min_distinct:
                continue                      # a constant, or a single step: not a trend
            up = all(b >= a for a, b in zip(tail, tail[1:])) and tail[-1] > tail[0]
            down = all(b <= a for a, b in zip(tail, tail[1:])) and tail[-1] < tail[0]
            if up or down:
                out.append({"kind": "hypothesis", "seed": "trend", "axis": f.stem,
                            "source": sid, "series_tail": tail,
                            "distinct_values": len(set(tail)),
                            "detail": f"{sid} moved monotonically "
                                      f"{'up' if up else 'down'} over {min_points} points "
                                      f"({tail[0]} -> {tail[-1]})"})
    return out


def _catalog(seed: dict) -> list:
    """The files that ACTUALLY stand behind this seed — repo-relative, verified present.

    THE GUARD WAS RIGHT AND THE PROMPT WAS WRONG. `articulate` asked the model for
    "repo-relative file paths that already exist" while never showing it a single path
    from this repo, so it did the only thing it could: it invented plausible ones
    ("climate_change_analysis/data/CO2_levels.csv"). Every idea then died on
    _refs_exist, and the creative phase produced nothing for a day and a half. A model
    cannot cite a repo it has never been shown. This builds the citation list from the
    files the seed was literally read out of, and articulate() hands it over verbatim."""
    cands = []
    axis = str(seed.get("axis") or "")
    if seed.get("seed") == "trend" and axis:
        cands.append(COMPOSER_ST / f"{axis}.json")   # the series this trend was read from
    cands += [CONFIG,
              REPO / "config" / "axis_source_map.json",
              REPO / "output" / "cortex_scores_latest.json",
              REPO / "memory" / "auto_levels.json"]
    out = []
    for p in cands:
        try:
            if p.is_file():
                rel = p.relative_to(REPO).as_posix()
                if rel not in out:
                    out.append(rel)
        except (ValueError, OSError):
            continue
    return out


def grounding_bypassed() -> bool:
    """TEMPORARY, OPERATOR-CONTROLLED. `CORTEX_PULSE_GROUNDING_OFF=1` lets ideas through
    without a verified citation. It exists so a starved creative phase can be unblocked
    by hand, and it never lies about what it did: a bypassed idea is stamped
    grounding="BYPASSED" and can never be marked well_sourced. Default is OFF — the
    guard is on."""
    return os.environ.get("CORTEX_PULSE_GROUNDING_OFF", "").strip().lower() in ("1", "true", "yes")


def _refs_exist(refs, catalog=None) -> bool:
    """grounded_on must point at things that EXIST. An idea grounded on an invented file
    is a hallucination with a citation.

    THE GUARD WAS OPEN FOR REFS THAT ARE NOTHING BUT AN ANCHOR. `split("#", 1)[0]` was
    meant to drop a fragment from "docs/FILE.md#section". Given "#GLOBAL-TARGET.md" it
    returns the EMPTY STRING, and `REPO / ""` is the repo root, which of course exists —
    so the check passed. The single idea the creative phase had produced by 2026-08-03
    cited "#GLOBAL-TARGET.md" and "#PODCELLS.md", neither of which is a file in this
    repo, and it was kept and surfaced with well_sourced=true. A guard that accepts an
    invented citation is worse than no guard: it puts a stamp on the hallucination.

    Four things are now required of every ref, and the empty case is the one that bit:
    a non-empty path, inside the repo, that resolves to an actual FILE — a directory
    always exists and grounding an idea on one grounds it on nothing."""
    if not refs:
        return False
    for r in refs:
        raw = str(r or "").split("#", 1)[0].strip().lstrip("/\\")
        if not raw:
            return False                      # an anchor with no file behind it
        p = REPO / raw
        try:
            p.resolve().relative_to(REPO.resolve())
        except (ValueError, OSError):
            return False                      # no escaping the repo with ../
        if not p.is_file():
            return False                      # a directory is not a citation
        if catalog is not None and raw not in catalog:
            return False                      # a real file it was never shown is a guess
    return True


def articulate(seed: dict, frame: str, catalog=None) -> dict:
    from autonomous_scout import _local, _json_from
    horizon = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    allowed = "\n".join(f"  {c}" for c in (catalog or []))
    cite = (f"These files exist in the repo and are the ONLY citations you may use. "
            f"Copy them verbatim into grounded_on — do not invent, shorten or guess a "
            f"path:\n{allowed}\n\n" if catalog else "")
    out = _local(
        f"{frame}\n\nA deterministic check produced this seed:\n{json.dumps(seed)[:900]}\n\n"
        f"{cite}"
        f"Turn it into ONE testable idea. Reply ONLY JSON:\n"
        f'{{"idea": "<one sentence>", "grounded_on": ["<one or more paths copied '
        f'exactly from the list above>"], "dimension": "<one word>", '
        f'"falsifiable_test": "<a concrete check>", "horizon": "{horizon}"}}',
        timeout=180, num_predict=350)
    return _json_from(out)


def _spread(seeds: list, per_axis: int, total: int) -> list:
    """Round-robin across axes, so one axis cannot eat the whole ideation budget.

    THE BUG: ideate() took `seeds[:6]`. seeds_trend() walks
    `sorted(COMPOSER_ST.glob("*.json"))`, so the seeds arrive grouped by axis in
    ALPHABETICAL order — and CLIMATE_GLOBAL_RISK_REVIEW sorts near the front with five
    qualifying series. It took five of the six slots every single time; COSMIC took the
    sixth. On 2026-08-04 there were 40 seeds spanning 16 axes and exactly 2 axes could
    ever produce an idea. The output looked like a system obsessed with climate. It was
    a slice, not a worldview.

    One seed per axis per round, so every axis with real data is reached before any axis
    gets a second idea."""
    by_axis = {}
    for s in seeds:
        by_axis.setdefault(s.get("axis") or "?", []).append(s)
    out = []
    for rnd in range(max(per_axis, 0)):
        progressed = False
        for ax in by_axis:
            bucket = by_axis[ax]
            if rnd < len(bucket) and len(out) < total:
                out.append(bucket[rnd])
                progressed = True
        if not progressed or len(out) >= total:
            break
    return out


def ideate(frame: str, dry: bool, c: dict | None = None) -> dict:
    c = c or {}
    per_axis = int(c.get("creative_ideas_per_axis", 2))
    budget = int(c.get("creative_max_ideas", 40))
    seeds = seeds_rule_violation() + seeds_trend()
    picked = _spread(seeds, per_axis, budget)
    result = {"seeds": len(seeds), "attempted": len(picked),
              "axes_seen": len({s.get("axis") for s in seeds}),
              "axes_attempted": len({s.get("axis") for s in picked}),
              "kept": [], "rejected": [], "penumbra": []}
    bypass = grounding_bypassed()
    if bypass:
        result["grounding"] = "BYPASSED"
    for s in picked:
        catalog = _catalog(s)
        try:
            got = articulate(s, frame, catalog)
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
        grounded = _refs_exist(refs, catalog)
        if not grounded and not bypass:
            result["rejected"].append({"idea": idea[:90], "why": "ungrounded — grounded_on "
                                                                "refs do not exist"})
            continue
        if not test or not horizon:
            result["rejected"].append({"idea": idea[:90],
                                       "why": "no falsifiable_test with a horizon"})
            continue
        rec = {"ts": _now(), "idea": idea, "grounded_on": refs, "dimension":
               got.get("dimension"), "falsifiable_test": test, "kind": s.get("kind"),
               "seed": s.get("seed"), "test_horizon": horizon, "outcome": None,
               "grounding": "verified" if grounded else "BYPASSED"}
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
                # a bypassed citation is never "well sourced" — the stamp is the whole
                # point of the guard, and it does not get handed out for free
                "well_sourced": bool(rec.get("grounded_on"))
                                and rec.get("grounding") == "verified"
                                and seed.get("seed") == "trend"}
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


def consolidation_due(ctx: dict, c: dict) -> bool:
    """Once per day, in the quiet hour. Same gate as creative_due, own record.

    Separate from creative_due deliberately: ideation asks a 3b model for an idea
    and can be starved by a dead Ollama, which is what has kept `creative` out of
    the stream since 2026-09-02T23:09. Consolidation is arithmetic over the sealed
    archive and has no such dependency, so tying the two together would let the
    model's absence silence the one job that does not need it.
    """
    now = datetime.now(timezone.utc)
    if now.hour < c.get("quiet_hour", 21):
        return False
    return not any(str(p.get("ts", ""))[:10] == now.date().isoformat()
                   and p.get("consolidation") for p in ctx["prev"])


def consolidate(dry: bool) -> dict:
    """Read the last 30 days of sealed cycles and write falsifiable drift claims.

    FAIL-SOFT and REPORTED: the pulse must not die because consolidation did, but a
    failure must not read as a quiet night either — the error goes into the stream.
    """
    try:
        from core.consolidation import run as _run
        rec = _run(write=not dry)
        return {"cycles_read": rec["cycles_read"],
                "series": rec["series_considered"],
                "emitted": rec["emitted"],
                "rejected": rec["rejected"],
                "dry": dry}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


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

    # EMIT THE SIGNAL EVERY TICK, unconditionally and regardless of necessity. The pulse
    # does not decide what is worth escalating, so it does not decide what is worth
    # reporting either — a filter here would be the same judgement wearing a smaller hat.
    line["signal"] = emit_signal(ctx) if not dry else "dry:signal_not_written"

    if nec["score"] >= int(c.get("threshold", 4)):
        line["actions"] = wake(nec, ctx, dry)
    else:
        line["actions"] = []

    if creative_due(ctx, c):
        line["creative"] = ideate(frame, dry, c)

    # The quiet hour's other job, and the one that does not need a model.
    if consolidation_due(ctx, c):
        line["consolidation"] = consolidate(dry)

    _append(STREAM, line, dry)
    return line


if __name__ == "__main__":
    out = tick(dry="--dry" in sys.argv)
    print(json.dumps(out, ensure_ascii=False, indent=2))
