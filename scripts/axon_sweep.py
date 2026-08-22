#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/axon_sweep.py — ONE PILOT SWEEP, MEASURED, UNDER A HARD WALL.

WHAT IT DOES
-------------
Builds the axon registry from config/axon_roles/, walks the agents ONE AT A TIME
in THREAT -> WATCH -> NORMAL order over a single shared aiohttp session, and
prints what each one cost:

    items seen / new / candidates written / bytes fetched / RSS delta

RSS DELTA IS THE POINT OF THE REPORT
--------------------------------------
The whole architecture rests on agents being cheap objects rather than
processes, and that claim is only worth as much as its measurement. So the
sweep samples the process's resident set before and after each agent and prints
the difference, per agent, next to the budget.

Read the per-agent number honestly: it is the delta of ONE shared process, so
it includes whatever the interpreter happened to allocate during that agent's
turn and whatever the allocator declined to return afterwards. It is an upper
bound on the agent's own cost, not an isolated measurement, and it can be
negative when a previous agent's buffers are released during this one's turn.
That is a property of measuring a shared heap, not an error. Sequential
execution is what makes even this attribution possible.

    THE GROWTH RULE, PRINTED ON EVERY REPORT
    3 -> 5 -> 10 agents is allowed ONLY while the measured footprint stays
    under 20 MB per agent. If a sweep prints a bigger number, the next agent
    does not get added; the cause gets found first.

THE WALL
---------
--sweep runs under a hard 10-minute cap, checked BETWEEN agents. An agent that
starts is allowed to finish — cancelling one mid-flight leaves a half-written
intake and a last_sweep_ts claiming it looked when it did not. What the cap
stops is the next agent starting. With per-request timeouts at 15 s and 3
sockets, the worst overrun is one agent's feeds.

GET ONLY, AND NOTHING IS SCHEDULED
-----------------------------------
This script issues no verb but GET, writes only the CANDIDATE intake, and
registers nothing with schtasks. --schtasks PRINTS the command a human may run;
it does not run it. Same rule as scripts/intel_daemon.py.

    venv/Scripts/python.exe scripts/axon_sweep.py --plan       # no network
    venv/Scripts/python.exe scripts/axon_sweep.py --selftest   # no network
    venv/Scripts/python.exe scripts/axon_sweep.py --sweep      # GOES TO THE NETWORK
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core import axon_agents as ax

BASE = pathlib.Path(__file__).resolve().parents[1]

TASK_NAME = "CORTEX_Axon"
RUN_EVERY_HOURS = 6


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def rss_mb() -> float | None:
    """Resident set of THIS process in MB, or None if it cannot be measured.

    None rather than 0.0 on failure: a report that prints 0.0 MB for an
    unmeasurable footprint is claiming the agent was free.
    """
    try:
        import psutil                                        # noqa: PLC0415
        return psutil.Process(os.getpid()).memory_info().rss / (1024.0 * 1024.0)
    except Exception:
        return None


def _fmt_mb(v) -> str:
    return "n/a" if v is None else "{:+.2f}".format(v)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def print_report(rows: list, result: dict, budget: float,
                 baseline_mb: float | None, final_mb: float | None) -> None:
    print()
    print("=" * 78)
    print("AXON SWEEP — {} agent(s) in {:.1f}s".format(
        len(result["ran"]), result["elapsed_sec"]))
    print("=" * 78)
    print("{:<8} {:<26} {:>5} {:>5} {:>6} {:>9} {:>9}".format(
        "STATE", "AXIS", "SEEN", "NEW", "CAND", "BYTES", "RSS dMB"))
    print("-" * 78)
    for r in rows:
        s = r["stats"]
        print("{:<8} {:<26} {:>5} {:>5} {:>6} {:>9,} {:>9}".format(
            r["state"], r["axis"][:26], s["seen"], s["new"], s["candidates"],
            s["bytes"], _fmt_mb(r["rss_delta_mb"])))
    print("-" * 78)

    refusals = sum(r["stats"]["refused_url"] + r["stats"]["refused_domain"]
                   for r in rows)
    no_url = sum(r["stats"]["no_url"] for r in rows)
    if refusals or no_url:
        print("refused: {} url/domain, {} row(s) with no link (refused, not "
              "dropped)".format(refusals, no_url))
    if result["skipped"]:
        print("NOT SWEPT (wall cap): {}".format(", ".join(result["skipped"])))

    print()
    print("MEMORY")
    if baseline_mb is None or final_mb is None:
        print("  UNMEASURED — psutil unavailable. The growth rule below cannot be")
        print("  checked from this run, so treat it as unmet, not as met.")
        return
    n = max(1, len(result["ran"]))
    total = final_mb - baseline_mb
    per_agent = total / n
    print("  process RSS   {:.1f} MB before -> {:.1f} MB after ({:+.2f} MB)".format(
        baseline_mb, final_mb, total))
    print("  per agent     {:+.2f} MB over {} agent(s), budget {:.0f} MB".format(
        per_agent, n, budget))
    worst = max((r["rss_delta_mb"] for r in rows
                 if r["rss_delta_mb"] is not None), default=None)
    if worst is not None:
        print("  worst single  {:+.2f} MB ({})".format(
            worst, next(r["axis"] for r in rows if r["rss_delta_mb"] == worst)))
    print()
    print("  THE GROWTH RULE: 3 -> 5 -> 10 agents is allowed ONLY while the")
    print("  measured footprint stays under {:.0f} MB per agent.".format(budget))
    ok = per_agent < budget and (worst is None or worst < budget)
    print("  THIS SWEEP: {}".format(
        "WITHIN BUDGET — growth to the next rung is permitted"
        if ok else
        "OVER BUDGET — do not add agents; find the cause first"))
    print()
    print("  Read the per-agent delta as an UPPER BOUND: it is one shared heap,")
    print("  so an agent's column includes whatever the allocator did during its")
    print("  turn. A negative delta is a release, not an error.")


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

async def run_sweep(agents: list, wall_cap_sec: float,
                    intake_path=None, state_path=None,
                    lifecycle_state_path=None) -> tuple:
    """Sequential, measured, under one session. Returns (rows, result)."""
    rows = []
    baseline = rss_mb()
    session = ax.make_session()
    t0 = time.monotonic()
    ran = []
    rings_state = ax.load_state(state_path)
    rings = {k: list(v) for k, v in (rings_state.get("_seen_rings") or {}).items()}
    orch = ax.load_orchestration()

    try:
        for agent in agents:
            if time.monotonic() - t0 >= wall_cap_sec:
                break
            before = rss_mb()
            await ax.sweep_agent(agent, session, intake_path=intake_path,
                                 lifecycle_state_path=lifecycle_state_path,
                                 seen_rings=rings)
            after = rss_mb()
            rows.append({
                "axis": agent.axis,
                "state": ax.alert_state(agent.axis, orch),
                "stats": dict(agent.stats),
                "rss_delta_mb": (None if before is None or after is None
                                 else round(after - before, 2)),
            })
            ran.append(agent)
    finally:
        await session.close()

    elapsed = time.monotonic() - t0
    st = ax.load_state(state_path)
    for agent in ran:
        st[agent.axis] = {"last_sweep_ts": agent.last_sweep_ts,
                          "last_stats": dict(agent.stats)}
    st["_seen_rings"] = rings
    ax.save_state(st, state_path)

    line = ax.emit_heartbeat(ran, elapsed)
    result = {"ran": [a.axis for a in ran],
              "skipped": [a.axis for a in agents if a not in ran],
              "elapsed_sec": round(elapsed, 2), "line": line}
    return rows, result, baseline, rss_mb()


# ---------------------------------------------------------------------------
# Modes that touch nothing
# ---------------------------------------------------------------------------

def cmd_plan(args) -> int:
    """What a sweep WOULD do. No sockets, no writes."""
    agents = ax.build_registry(orchestration=None)
    orch = ax.load_orchestration()
    print("axon sweep plan — {} agent(s), in this order:".format(len(agents)))
    print("{:<8} {:<26} {:>6} {:<}".format("STATE", "AXIS", "ITEMS", "FEEDS"))
    for a in agents:
        print("{:<8} {:<26} {:>6} {}".format(
            ax.alert_state(a.axis, orch), a.axis[:26], a.max_items,
            ", ".join(a.feeds)))
        print("{:<8} {:<26} {:>6} last_sweep={}".format(
            "", "", "", a.last_sweep_ts or "never"))
    print()
    print("caps: {:,} bytes/response, {}s/request, {} sockets, wall {}s".format(
        ax.MAX_CONTENT_BYTES, ax.STREAM_TIMEOUT_SEC, ax.MAX_CONNECTIONS,
        int(args.wall_cap)))
    print("budget: {:.0f} MB per agent".format(ax.MEMORY_BUDGET_MB))
    print("intake: {}".format(ax.INTAKE_PATH))
    print("\nNothing was fetched and nothing was written. Use --sweep to run.")
    return 0


def cmd_schtasks(args) -> int:
    """PRINTS the registration command. Never runs it."""
    py = BASE / "venv" / "Scripts" / "python.exe"
    script = BASE / "scripts" / "axon_sweep.py"
    print("Not registered. To register, a HUMAN runs:\n")
    print('schtasks /Create /TN "{}" /TR "\\"{}\\" \\"{}\\" --sweep" '
          "/SC HOURLY /MO {} /F".format(TASK_NAME, py, script, RUN_EVERY_HOURS))
    print("\nTo remove:\n")
    print('schtasks /Delete /TN "{}" /F'.format(TASK_NAME))
    return 0


def cmd_selftest(args) -> int:
    print("scripts/axon_sweep.py --selftest")
    ok = True
    try:
        agents = ax.build_registry()
        print("  registry             LIVE ({} agent(s))".format(len(agents)))
    except ax.RoleError as e:
        print("  registry             INERT ({})".format(e))
        return 1

    order = [a.axis for a in agents]
    print("  sweep order          {}".format(" -> ".join(order)))

    print("  caps                 {:,} bytes / {}s / {} sockets (imported)".format(
        ax.MAX_CONTENT_BYTES, ax.STREAM_TIMEOUT_SEC, ax.MAX_CONNECTIONS))
    print("  wall cap             {}s".format(int(ax.WALL_CAP_SEC)))

    base = rss_mb()
    print("  rss measurement      {}".format(
        "LIVE ({:.1f} MB now)".format(base) if base is not None
        else "INERT — psutil unavailable, the budget cannot be checked"))
    ok = ok and base is not None

    try:
        import aiohttp
        print("  aiohttp              LIVE ({})".format(aiohttp.__version__))
    except ImportError:
        print("  aiohttp              INERT — --sweep cannot run")
        ok = False

    print("  intake               {}".format(
        "exists ({} bytes)".format(ax.INTAKE_PATH.stat().st_size)
        if ax.INTAKE_PATH.exists() else "not created yet (first sweep makes it)"))
    print("  lifecycle            {}".format(
        "LIVE" if (BASE / "core" / "source_lifecycle.py").exists() else "INERT"))
    print("  RESULT: {}".format("OK" if ok else "BROKEN"))
    return 0 if ok else 1


def cmd_sweep(args) -> int:
    agents = ax.build_registry()
    print("[AXON] sweeping {} agent(s), wall cap {}s".format(
        len(agents), int(args.wall_cap)))
    rows, result, baseline, final = asyncio.run(
        run_sweep(agents, wall_cap_sec=args.wall_cap))
    print_report(rows, result, ax.MEMORY_BUDGET_MB, baseline, final)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="One axon pilot sweep. GET only; nothing is scheduled.")
    p.add_argument("--sweep", action="store_true",
                   help="run one full sweep (GOES TO THE NETWORK)")
    p.add_argument("--plan", action="store_true",
                   help="print what a sweep would do; no sockets, no writes")
    p.add_argument("--selftest", action="store_true",
                   help="report which integrations are LIVE and which INERT")
    p.add_argument("--schtasks", action="store_true",
                   help="PRINT the registration command; never runs it")
    p.add_argument("--wall-cap", dest="wall_cap", type=float,
                   default=ax.WALL_CAP_SEC,
                   help="hard wall in seconds (default {})".format(
                       int(ax.WALL_CAP_SEC)))
    args = p.parse_args(argv)

    if args.selftest:
        return cmd_selftest(args)
    if args.schtasks:
        return cmd_schtasks(args)
    if args.plan:
        return cmd_plan(args)
    if args.sweep:
        return cmd_sweep(args)
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
