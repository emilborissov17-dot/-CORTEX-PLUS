#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/cycle_step_audit.py — one row per cycle step: what it writes, and who reads it.

THE QUESTION (Emil, 19 September 2026): of the 75 steps the cycle runs for 1h45m
every night, which ones produce something that anything downstream actually
reads? LOAD-BEARING if a reader is provably named. RITUAL if nothing reads it.
UNKNOWN if the honest answer is that nobody has confirmed either way. NONE and
UNKNOWN are answers, and the count of them is the point.

WHY THE VERDICT IS NOT A GREP. test/test_produces_has_a_reader.py already carries
the scar tissue: four static classifiers were written on 6 September and all four
were wrong in different directions — literal basenames gave 176 false "never
read", a parent-directory walk gave 0, a read/write window classifier gave 17 of
which the whole snapshot family was false (they are read through
rglob("*_snapshot_latest.json")), and a glob-aware version gave 0 again because
"*.json" matches everything. Reads in this repo happen through module constants,
through globs, and through helpers far from the path.

So the verdict is DECLARED first and grepped only as a fallback, and a grep hit
never promotes a path to LOAD-BEARING on its own — it can only lift RITUAL to
UNKNOWN, because "a module mentions this string" is not "a module reads this
file".

SOURCES, all read-only:
  core/cycle_map.py                    75 steps: name, index, purpose, produces
  config/cycle_phases.json             phase -> requires / produces / steps
  config/produces_readers.json         path -> declared readers + status
  memory/step_callmap.json             static AST map: modules each step reaches
  memory/step_contract_baseline.json   empirical footprints (files touched/run)
  memory/blackbox.jsonl                this run's begin/end spans
  memory/steps/<cid>_steps.jsonl       this run's verdicts and seconds

A KNOWN LIMIT, stated rather than papered over: nothing in this repo declares
what an individual step READS. cycle_map declares produces per step; requires
exists only per PHASE. So the READS column is the phase's requires plus the
modules the step reaches from the AST map, and it is coarser than the WRITES
column. Do not read it as a file-level input contract.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Files every step touches because the runner touches them. Counting these as a
# step's own output would make all 75 look busy.
NOISE = re.compile(
    r"^memory/(blackbox\.jsonl|cycle_logs/|cycle_trace/|steps/|heartbeat\.json"
    r"|step_contract_(latest|baseline)\.json|phase_state\.json)")

LOAD_BEARING, RITUAL, UNKNOWN = "LOAD-BEARING", "RITUAL", "UNKNOWN"


def _j(path, default):
    try:
        return json.loads((REPO / path).read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return default


def _phase_of(step_name, phases):
    for ph, body in phases.items():
        if step_name in (body.get("steps") or []):
            return ph
    return "?"


def _empirical(baseline, raw_names):
    """Files this step has actually touched across recorded runs, minus noise."""
    hits = Counter()
    for nm in raw_names:
        for run in (baseline.get(nm) or {}).get("runs", []):
            for f in run.get("touched") or []:
                f = f.replace("\\", "/")
                if not NOISE.match(f):
                    hits[f] += 1
    return [f for f, _ in hits.most_common()]


def _stems(path_rel):
    """Search stems for a path, DATE-STRIPPED.

    memory/session_2026-09-19.json is read by core/cortex_reasoner.py through
    glob("session_*.json"). Grepping the literal basename finds nothing and the
    file looks unread — the exact false positive test_produces_has_a_reader.py
    was written about. So a dated name is also searched by its stem.
    """
    base = os.path.basename(path_rel)
    out = [base]
    stem = re.sub(r"\d{4}-\d{2}-\d{2}", "", base)
    stem = re.sub(r"\d{8}|\d{6}", "", stem)
    stem = stem.replace("__", "_").strip("_.-")
    stem = re.split(r"[._]", stem)[0] if stem else ""
    if stem and stem != base and len(stem) >= 5:
        out.append(stem + "_")          # e.g. "session_"
    return out


def _grep_readers(path_rel, exclude_files):
    """Modules that mention this path at all. NEVER proves a read — only stops
    us calling something RITUAL when a mention exists we have not understood."""
    base = os.path.basename(path_rel)
    if not base or len(base) < 6:
        return []
    out = ""
    for needle in _stems(path_rel):
        try:
            out += subprocess.run(
                ["git", "grep", "-l", "--", needle],
                cwd=str(REPO), capture_output=True, text=True, timeout=60).stdout
        except Exception:                                    # noqa: BLE001
            pass
    mods = []
    for line in out.splitlines():
        line = line.strip().replace("\\", "/")
        if not line.endswith(".py"):
            continue
        if line in exclude_files or "/cycle_map.py" in line:
            continue
        mods.append(line)
    return mods


def verdict_for(step, writes, readers_db, callmap_files):
    """Per-path verdicts, then the step's verdict as the best of them."""
    details = []
    best = RITUAL if writes else UNKNOWN

    for w in writes:
        entry = readers_db.get(w)
        if entry:
            rs = entry.get("readers") or []
            status = entry.get("status")
            if rs and status == "named":
                v = LOAD_BEARING
            elif rs and status == "glob":
                # A glob reader is a real mechanism in this repo (the snapshot
                # family is read exactly that way), but the declaration does not
                # name the module for THIS path.
                v = LOAD_BEARING
            else:
                v = UNKNOWN          # UNVERIFIED: declared, nobody confirmed
            details.append((w, v, ", ".join(rs[:3]) or "-", status or "-"))
        elif not os.path.splitext(w)[1]:
            # A DIRECTORY CAN NEVER BE RITUAL BY GREP. Ten produces entries name a
            # directory rather than a file (snapshots/human, plans, output/reports
            # ...), and this repo reads those by walking the tree -- the snapshot
            # family is read through rglob("*_snapshot_latest.json"), so the string
            # "snapshots/human" need never appear anywhere. Absence of a literal
            # mention is not evidence of absence of a reader, and calling it RITUAL
            # would repeat the 6 September classifier's exact mistake.
            mods = [m for m in _grep_readers(w, callmap_files)
                    if not m.startswith("test/")]
            v = UNKNOWN
            details.append((w, v, ", ".join(mods[:3]) or "directory: read by "
                            "tree-walk, not decidable by name", "directory"))
        else:
            mods = _grep_readers(w, callmap_files)
            real = [m for m in mods if not m.startswith("test/")]
            if real:
                v = UNKNOWN
                details.append((w, v, ", ".join(real[:3]), "undeclared"))
            else:
                v = RITUAL
                details.append((w, v, "NONE", "undeclared"))

        order = {LOAD_BEARING: 3, UNKNOWN: 2, RITUAL: 1}
        if order[v] > order[best]:
            best = v

    if not writes:
        details.append(("(declares no output)", UNKNOWN, "NONE", "-"))
    return best, details


def build(run_steps, run_spans):
    from core.cycle_map import STEPS, ALIASES
    phases = _j("config/cycle_phases.json", {}).get("phases", {})
    readers_db = _j("config/produces_readers.json", {}).get("paths", {})
    callmap = _j("memory/step_callmap.json", {})
    baseline = _j("memory/step_contract_baseline.json", {})

    reach = {}
    for s in callmap.get("steps", []):
        mods = [x.get("module") for x in (s.get("substeps") or []) if x.get("module")]
        if not mods:
            mods = [d.get("function") for d in (s.get("delegates_to") or [])]
        reach[s.get("name")] = [m for m in mods if m]
    opaque = {o.get("step") for o in callmap.get("opaque_steps", [])}

    # canonical -> every name it may be recorded under
    rawnames = {}
    for raw, canon in ALIASES.items():
        rawnames.setdefault(canon, []).append(raw)

    rows = []
    for i, (name, idx, purpose, produces, _flag) in enumerate(STEPS, 1):
        raws = [name] + rawnames.get(name, [])
        declared = [p.replace("\\", "/") for p in (produces or [])]
        emp = _empirical(baseline, raws)
        writes = list(dict.fromkeys(declared + [e for e in emp if e not in declared]))

        # THE VERDICT IS ABOUT THE PROMISE, NOT THE FOOTPRINT. cycle_map's
        # produces list is what the step says it leaves behind; the empirical
        # touched set includes incidental writes (chromadb, provenance logs) that
        # were never a contract and must not be judged as one.
        v, details = verdict_for(name, declared, readers_db, set())

        secs, status = None, "NOT INSTRUMENTED"
        for r in raws:
            if r in run_steps:
                secs = run_steps[r].get("seconds")
                ver = run_steps[r].get("verdict")
                status = "DEGRADED" if (ver not in ("OK", "UNKNOWN", None)
                                        or run_steps[r].get("degraded")) else "OK"
                break
        else:
            for r in raws:
                if r in run_spans:
                    secs = run_spans[r]
                    status = "OK"
                    break

        rows.append({
            "n": i, "step": name, "index": idx,
            "phase": _phase_of(name, phases),
            "purpose_bg": (purpose or "").replace("\n", " "),
            "reads": (phases.get(_phase_of(name, phases), {}).get("requires") or []),
            "reaches": reach.get(name, []),
            "opaque": name in opaque,
            "declared": declared, "writes": writes,
            "verdict": v, "details": details,
            "seconds": secs, "status": status,
            "contract": "yes" if any(r in run_steps for r in raws) else "no",
        })
    return rows


def this_run():
    """(step -> contract row, step -> seconds) for the newest recorded cycle."""
    # SOURCE: memory/step_contract_latest.json, NOT the newest
    # memory/steps/<cycle_id>_steps.jsonl. The per-cycle file is written with the
    # PREVIOUS run's contents at the start of a run, so "newest by mtime" is the
    # night before -- the same trap that made cycle_watch report daily_tier as
    # 1.07s when this run took 0.1s. The latest file carries a cycle_id, so the
    # run it describes is checkable rather than assumed.
    steps = {}
    src_name = None
    latest = REPO / "memory" / "step_contract_latest.json"
    try:
        d = json.loads(latest.read_text(encoding="utf-8"))
        for r in d.get("steps") or []:
            k = r.get("step") or r.get("label")
            if k:
                steps[k] = r
        src_name = "step_contract_latest.json (cycle %s)" % d.get("cycle_id")
    except Exception:                                        # noqa: BLE001
        pass

    spans, open_at = {}, {}
    bb = REPO / "memory" / "blackbox.jsonl"
    if bb.exists():
        newest_pid = None
        recs = []
        for raw in bb.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                recs.append(json.loads(raw))
            except Exception:                                # noqa: BLE001
                pass
        for r in recs:
            if r.get("step") == "cycle" and r.get("phase") == "start":
                newest_pid = r.get("pid")
        for r in recs:
            if r.get("pid") != newest_pid:
                continue
            if r.get("phase") == "begin":
                open_at[r["step"]] = r.get("elapsed_s") or 0
            elif r.get("phase") == "end" and r.get("step") in open_at:
                spans[r["step"]] = round(
                    (r.get("elapsed_s") or 0) - open_at.pop(r["step"]), 1)
    return steps, spans, src_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(
        REPO / "claude" / "reports" / "CYCLE_STEP_AUDIT_2026-09-19.md"))
    a = ap.parse_args()

    run_steps, run_spans, src = this_run()
    rows = build(run_steps, run_spans)

    counts = Counter(r["verdict"] for r in rows)
    stat = Counter(r["status"] for r in rows)
    timed = [r for r in rows if isinstance(r.get("seconds"), (int, float))]
    timed.sort(key=lambda r: -r["seconds"])

    L = []
    W = L.append
    W("# Cycle step audit — 2026-09-19")
    W("")
    W("One row per step in execution order, built from the code, with runtime from "
      "the manual run of 2026-09-19.")
    W("")
    W("Generated by `tools/cycle_step_audit.py`. Runtime source: `%s`."
      % (src or "none"))
    W("")
    W("## Counts")
    W("")
    W("| verdict | steps |")
    W("|---|---|")
    for k in (LOAD_BEARING, UNKNOWN, RITUAL):
        W("| %s | **%d** |" % (k, counts.get(k, 0)))
    W("| total | %d |" % len(rows))
    W("")
    W("| instrumentation | steps |")
    W("|---|---|")
    for k, v in stat.most_common():
        W("| %s | %d |" % (k, v))
    W("")
    W("## Slowest steps in this run")
    W("")
    W("| step | seconds |")
    W("|---|---|")
    for r in timed[:12]:
        W("| `%s` | %s |" % (r["step"], r["seconds"]))
    W("")
    W("## Steps whose output nothing reads (RITUAL)")
    W("")
    rit = [r for r in rows if r["verdict"] == RITUAL]
    if not rit:
        W("None.")
    else:
        W("| # | step | writes | reader |")
        W("|---|---|---|---|")
        for r in rit:
            for w, v, who, _st in r["details"]:
                if v == RITUAL:
                    W("| %d | `%s` | `%s` | **NONE** |" % (r["n"], r["step"], w))
    W("")
    W("## The table")
    W("")
    W("| # | step | phase | what it does | reads (phase-level) | writes | who reads that | verdict | contract | sec |")
    W("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        writes = "<br>".join("`%s`" % w for w in r["writes"][:4]) or "—"
        who = "<br>".join("%s" % (d[2],) for d in r["details"][:4]) or "NONE"
        reads = ", ".join("`%s`" % x for x in (r["reads"] or [])[:3]) or "—"
        W("| %d | `%s` | %s | %s | %s | %s | %s | **%s** | %s | %s |"
          % (r["n"], r["step"], r["phase"], ENGLISH.get(r["step"], "—"),
             reads, writes, who, r["verdict"], r["contract"],
             r["seconds"] if r["seconds"] is not None else "—"))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote %s (%d rows)" % (out, len(rows)))
    print("verdicts:", dict(counts))
    print("status  :", dict(stat))


ENGLISH = {
    "boot": "First proof of life; stamps the cycle_id from the supervisor.",
    "body_scan": "Reads CPU/RAM/VRAM/disk/models into adaptive directives; can HALT the cycle via homeostasis.",
    "canon_load": "Loads the canon and checks it against a hardcoded SHA-256 before any planning.",
    "telegram_approvals": "Applies the human's OK/NO answers before the plan is written.",
    "brain_briefing": "The brain writes the day's plan: focus, suspicion, and its own test for success.",
    "notify_patches_and_initiatives": "Announces what is waiting for approval, after the plan so the plan's own needs surface.",
    "dependency_check": "Checks there is anything to work with; the only step that stops the cycle.",
    "needs_reanalysis_scan": "Finds axes flagged for re-examination; the flag is cleared later by a newer clean record.",
    "web_intelligence": "Free web search across the axes, in a separate process with its own 300s ceiling.",
    "global_indicators": "20 sections from 14 independent hosts; every number gets provenance and an observation date.",
    "daily_tier": "The same read as global_indicators, kept PER DAY instead of overwritten; no network.",
    "sensorium_ingest": "Ingests sensor drops and checks the real chain and the shadow chain separately.",
    "browser_scout": "Visits pages for meaning rather than numbers.",
    "composers": "The daily per-axis portfolio — the moving signal.",
    "grounding_ledger": "Records an anchor against a daily proxy; only records, the verdict belongs to source_trust.",
    "llm_self_review_axes": "LLM review per axis AFTER the senses: level plus reasoning over today's data.",
    "trend_tracker": "The direction of each axis over time.",
    "cortexstrategist": "Strategic judgement BEFORE the snapshots eat the day's token budget.",
    "internet_intelligence": "Internet agent.",
    "civilization_snapshots": "The 7 Civilization axes into snapshots.",
    "planet_snapshots": "The 7 Planet axes into snapshots.",
    "human_snapshots": "The 5 Human axes into snapshots.",
    "cosmos_snapshots": "The 6 Cosmos axes into snapshots.",
    "planetary_potential": "Review of planetary potential.",
    "energy_review": "Energy review.",
    "self_awareness": "Self-awareness agent.",
    "update_master": "Merges everything into the master snapshot.",
    "system_hypergraph": "Builds the system hypergraph.",
    "scoring_engine": "Scores every snapshot along its axis.",
    "alarm_bands": "The red lines: a threshold crossed NOW rings now, not in the morning digest.",
    "facade_self_check": "Facade hunter: which scorers are dead but look alive.",
    "auto_levels": "Automatic levels from real data.",
    "level_reconcile": "Where the word and the number disagree and meaning is pinned, the number wins.",
    "axis_history": "Per-axis indicator history — the world model's time axis; feeds world_forecast.",
    "goal_score_calculator": "The composite score against the goal.",
    "deduction": "The R1-R7 deductive layer, with premises attached to every inference.",
    "constancy_and_constellation": "Constancy as measurement: each indicator's expected regime, and all of them read together.",
    "axis_feed": "The per-axis feed to the queue; an axis with no number leaves an ABSENT row and a reason.",
    "cognitive_orchestrator": "Cognitive orchestration; hands priority_axes to HyperClaw.",
    "brain_reconsider": "The return point: the brain decides whether to continue or recompute one step (max 1/cycle).",
    "hyperclaw": "HyperClaw orchestrator.",
    "hyperclaw_plan": "Its plan, turned into improvement proposals.",
    "github_publish": "Publishes the cycle's synthesis and the verified hypotheses.",
    "action_recommendations": "Reasoning into a recommendation, written to semantic memory.",
    "self_observer": "Observes its own behaviour.",
    "self_modifier": "Writes patches for itself.",
    "execute_patches": "Executes patches through the AST gate; measures before/after and the quality of the measurement.",
    "feedback_loop": "Per-axis feedback from actually measured values.",
    "resolve_hypotheses": "Judges due hypotheses against trends.json; resolution only, never generation.",
    "belief_revision": "Moves per-method weights by the surprise of the resolved hypotheses.",
    "hypothesis_intake": "Pre-registers tonight's predictions with an interval; MEASURED axes only.",
    "output_contracts": "Judges the other steps' outputs; fixes nothing and stops nothing.",
    "measurement_honesty": "K1: the measured weight, and why each axis counts as measured.",
    "resolve_ideas": "Judges the pulse's hypotheses against the observed series; application only.",
    "session_update": "Updates the session record.",
    "daily_analysis": "Daily analysis.",
    "data_scout": "Looks for new sources; last, so it does not fight for the LLM limit.",
    "continuous_learning": "Learns from the cycle.",
    "merklememory_commit": "Merkle commitment of memory — the audit chain.",
    "merkle_verify": "Verifies the just-sealed cycle against its hash — proof of inclusion.",
    "training_data_accumulation": "Accumulates training data from the archive.",
    "metta_column": "The symbolic column: 5 rules over the feeds; disagreements go into the D_SCORE report.",
    "brain_relay": "The relay: carries what the brain said out to the phone.",
    "proposal_sla": "The proposals' clock: anything overdue escalates ONCE, by name.",
    "needs_auth": "Sources waiting for a key — weekly, with the link and the variable name.",
    "learn_world": "The night's learning: tier, scoring, alpha retune, tomorrow's forecasts, cloud-mind order.",
    "self_experiment": "One observation per unfinished pre-registered experiment; the arm is checked against the live file.",
    "self_mirror": "The mirror: judge calibration, debriefs, open predictions, ageing proposals, trusted sources. Enters no number.",
    "read_the_mirror": "The brain receives the WHOLE mirror and says what it sees; quoted numbers are checked against it.",
    "brain_debrief": "The brain judges its own plan: did its test come true.",
    "cycle_report": "The report to the human, written by the system itself.",
    "cortex_scan": "The full state for the dashboard; aggregates the finished cycle.",
    "compass": "The four needles: measured weight, trust, consolidated claims, interval score.",
}


if __name__ == "__main__":
    main()
