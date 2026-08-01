#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/cortex_query.py — the human's unmediated query interface.

WHY THIS EXISTS
---------------
Sensing shapes action. What the system marks salient is what the human sees; what it
marks anomalous is what the human is asked to approve; what it never surfaces is what
the human never considers. A human who only ever sees what the system chose to surface
is a rubber stamp on a flight plan written by the autopilot.

This CLI is the human's way around that. It reads the SAME files the system reads, but
through a code path the system does not own:

  * It imports NOTHING from the project — no pulse, no supervisor, no composer, no
    signing, no scoring. Standard library only. There is therefore no salience filter,
    no confidence discount and no summarizer between Emil and the bytes on disk. This
    is enforced by test/test_cortex_query.py, which walks this module's AST and fails
    if a single non-stdlib import appears.
  * It runs no LLM. Ever. What is printed is what is stored.

READ-ONLY, with exactly two exceptions — both of them files the HUMAN owns and the
system merely consumes:
  --axis <AXIS> --force     appends a human_sense_request to memory/composer_needs.json
  --priority <AXIS> <N>     writes memory/human_priority_override.json

Neither of those RUNS anything. They queue a demand; the existing cycle drains it.

USAGE
  cortex_query.py --penumbra <id|hash>     raw quarantined leaf + its payload, verbatim
  cortex_query.py --raw <source_id>        a composer source's latest value + data date
  cortex_query.py --axis <AXIS> --force    demand this axis be sensed (bypasses salience)
  cortex_query.py --priority <AXIS> <N>    rank this axis for the needs report
  cortex_query.py --ledger                 prophecy ledger status
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

COMPOSER_STATE  = REPO / "memory" / "composer_state"
COMPOSED_OUT    = REPO / "memory" / "composed_indicators.json"
COMPOSER_NEEDS  = REPO / "memory" / "composer_needs.json"
PRIORITY_FILE   = REPO / "memory" / "human_priority_override.json"
PENUMBRA_DIR    = REPO / "memory" / "penumbra"
PENUMBRA_LEAVES = PENUMBRA_DIR / "_penumbra_leaves.jsonl"
LEDGER          = REPO / "experiments" / "prophecy" / "prophecy_ledger.jsonl"

RULE = "─" * 78


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(path: Path) -> str:
    """Repo-relative for readability, absolute when it lies outside the repo. Never
    raises — a path we cannot shorten is still a path the human is entitled to see."""
    try:
        return str(Path(path).relative_to(REPO))
    except ValueError:
        return str(path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_jsonl(path: Path) -> list:
    """Every parseable line. A torn line is skipped, not guessed at."""
    out = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ── --penumbra ───────────────────────────────────────────────────────────────

def cmd_penumbra(needle: str) -> int:
    """The raw quarantined leaf and its payload. VERBATIM — no summarization, no
    filtering, no 'relevant excerpt'. The whole point of the penumbra is that the
    system considers this material untrustworthy; the human reads it anyway."""
    leaves = _read_jsonl(PENUMBRA_LEAVES)
    if not leaves:
        print(f"penumbra is empty — no leaves at {_rel(PENUMBRA_LEAVES)}")
        print("(nothing has been quarantined yet, or the sensorium has never run)")
        return 0

    hits = [lf for lf in leaves
            if needle in (str(lf.get("id", "")), str(lf.get("leaf", "")))
            or str(lf.get("id", "")).endswith(needle)
            or str(lf.get("leaf", "")).startswith(needle)]

    if not hits:
        print(f"no penumbra leaf matches {needle!r}. Present ids:")
        for lf in leaves:
            print(f"  {lf.get('id')}   leaf={str(lf.get('leaf'))[:16]}  "
                  f"reason={(lf.get('quarantine') or {}).get('reason', '?')}")
        return 1

    for lf in hits:
        print(RULE)
        print("PENUMBRA LEAF (verbatim record)")
        print(RULE)
        print(json.dumps(lf, ensure_ascii=False, indent=2))

        rel = lf.get("path")
        if not rel:
            print("\n(no payload path on this leaf)")
            continue
        payload = REPO / str(rel).replace("\\", "/")
        print()
        print(RULE)
        print(f"PAYLOAD (verbatim bytes of {rel})")
        print(RULE)
        try:
            print(payload.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[unreadable: {type(e).__name__}: {e}]")
    return 0


# ── --raw ────────────────────────────────────────────────────────────────────

def _find_source(source_id: str):
    """(axis, state) for a source id across every composer state file."""
    for f in sorted(COMPOSER_STATE.glob("*.json")):
        state = _read_json(f, {}) or {}
        srcs = state.get("sources") or {}
        if source_id in srcs:
            return f.stem, srcs[source_id]
    return None, None


def cmd_raw(source_id: str) -> int:
    axis, st = _find_source(source_id)
    if st is None:
        print(f"no composer source {source_id!r} in {_rel(COMPOSER_STATE)}/")
        known = []
        for f in sorted(COMPOSER_STATE.glob("*.json")):
            known += list((_read_json(f, {}) or {}).get("sources", {}))
        print(f"({len(known)} known source ids: {', '.join(sorted(set(known))[:12])} ...)")
        return 1

    print(RULE)
    print(f"SOURCE {source_id}   axis={axis}")
    print(RULE)
    print(f"last_value        {st.get('last_value')}")
    print(f"last_ok_ts        {st.get('last_ok_ts')}   (when WE fetched it)")
    print(f"last_attempt_ts   {st.get('last_attempt_ts')}")
    print(f"status            {st.get('status')}   consecutive_fails={st.get('consecutive_fails')}")
    if st.get("throttled"):
        print("throttled         yes")
    if st.get("last_error"):
        print(f"last_error        {st.get('last_error')}")

    # data_date — the date the DATA refers to, not the date we fetched it. The composer
    # extracts it at fetch time and uses it to refuse stale values, but persists it only
    # on the refusal path (inside last_error). On success it is discarded. Say so plainly
    # rather than passing off last_ok_ts as if it were the data's own date; they answer
    # different questions and conflating them is how a 2024 number reads as today's.
    print()
    err = str(st.get("last_error") or "")
    if "data_date" in err:
        print(f"data_date         (from the refusal above) {err}")
    else:
        print("data_date         NOT PERSISTED — composer.py records the source's own data")
        print("                  date only when it REFUSES the value as too old; on success")
        print("                  it is discarded. last_ok_ts above is OUR fetch time.")

    # unit lives in the composed report, not in state
    composed = _read_json(COMPOSED_OUT, {}) or {}
    for slot in (composed.get(axis, {}).get("slots") or {}).values():
        for live in slot.get("live") or []:
            if live.get("id") == source_id:
                print(f"unit              {live.get('unit')}   org={live.get('org')}"
                      f"   age_days={live.get('age_days')}")
                break

    hist = st.get("history") or []
    print()
    print(f"history           {len(hist)} point(s), {len({v for _, v in hist})} distinct value(s)")
    for ts, val in hist:
        print(f"  {ts}   {val}")
    return 0


# ── --axis ... --force ───────────────────────────────────────────────────────

def cmd_axis_force(axis: str) -> int:
    """Queue the human's demand that an axis be sensed, bypassing pulse salience.

    This does NOT run a collector. It appends one item to the file the collectors
    already read, and the next cycle drains it like any other declared hunger.
    """
    needs = _read_json(COMPOSER_NEEDS, {}) or {}
    entry = needs.get(axis) or {"ts": _now(), "items": []}
    entry.setdefault("items", [])
    item = {
        "slot": "*",
        "kind": "human_sense_request",
        "detail": f"HUMAN DEMAND: sense {axis} — queued by cortex_query, bypassing pulse salience",
        "requested_by": "human",
        "requested_ts": _now(),
    }
    entry["items"].append(item)
    needs[axis] = entry
    _write_json(COMPOSER_NEEDS, needs)

    print(f"queued human_sense_request for {axis}")
    print(json.dumps(item, ensure_ascii=False, indent=2))
    print()
    print(f"-> written to {_rel(COMPOSER_NEEDS)}")
    print("-> core/data_scout.py drains it at cycle beat 22.5 (kind human_sense_request)")
    print("-> composer.py preserves it across its own rewrites until it is drained")
    return 0


# ── --priority ───────────────────────────────────────────────────────────────

def cmd_priority(axis: str, rank: str) -> int:
    """The human's ranking of what matters. The needs report orders by this when
    present — human ranking beats the system's severity ordering."""
    try:
        n = int(rank)
    except ValueError:
        print(f"priority must be an integer, got {rank!r}")
        return 2

    doc = _read_json(PRIORITY_FILE, {}) or {}
    ranks = doc.get("priority") or {}
    ranks[axis] = n
    doc = {"ts": _now(), "set_by": "human", "priority": ranks,
           "note": "lower number = higher priority; read by experiments/needs/needs_report.py"}
    _write_json(PRIORITY_FILE, doc)

    print(f"human priority set: {axis} = {n}   (lower = more important)")
    print()
    print("current ranking:")
    for a, r in sorted(ranks.items(), key=lambda kv: kv[1]):
        print(f"  {r:>4}  {a}")
    print()
    print(f"-> written to {_rel(PRIORITY_FILE)}")
    return 0


# ── --ledger ─────────────────────────────────────────────────────────────────

def cmd_ledger() -> int:
    recs = _read_jsonl(LEDGER)
    if not recs:
        print(f"no prophecy ledger at {_rel(LEDGER)}")
        return 1

    sealed  = [r for r in recs if r.get("event") == "PREDICTION_SEALED"]
    scored  = [r for r in recs if r.get("event") == "OUTCOME_SCORED"]
    pending = [r for r in recs if r.get("event") == "PREDICTION_PENDING"]
    done    = {r.get("ref_hash") for r in scored}
    unscored = [r for r in sealed if r.get("hash") not in done]

    print(RULE)
    print("PROPHECY LEDGER")
    print(RULE)
    print(f"records            {len(recs)}")
    print(f"predictions sealed {len(sealed)}")
    print(f"outcomes scored    {len(scored)}")
    print(f"unscored           {len(unscored)}")
    print(f"pending (TODO)     {len(pending)}")

    kinds = {}
    for r in sealed:
        kinds[r.get("target_kind")] = kinds.get(r.get("target_kind"), 0) + 1
    print("\nby target_kind:")
    for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4}  {k}")

    horizons = {}
    for r in sealed:
        horizons[str(r.get("horizon_utc"))] = horizons.get(str(r.get("horizon_utc")), 0) + 1
    print("\nhorizons:")
    for h, n in sorted(horizons.items(), key=lambda kv: -kv[1]):
        # A calendar horizon is falsifiable on a date a human can hold you to. A symbolic
        # one ('next cycle') is only falsifiable relative to the system's own schedule.
        mark = "calendar" if h[:4].isdigit() else "symbolic"
        print(f"  {n:>4}  {h}   [{mark}]")

    if pending:
        print("\npending predictions (calendar-triggered TODOs):")
        for r in pending[-5:]:
            print(f"  {r.get('ts', '')[:19]}Z  {r.get('target_id')}")
            print(f"        {r.get('reason')}")

    if unscored:
        print("\nunscored (most recent 5):")
        for r in unscored[-5:]:
            print(f"  seq={r.get('seq'):<5} {r.get('target_id')}   horizon={r.get('horizon_utc')}")
            print(f"        learner={r.get('learner')}  baseline={r.get('baseline')}"
                  f"  hash={str(r.get('hash'))[:12]}")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="cortex_query",
        description="The human's unmediated read of what CORTEX stored. No LLM, no summarizer.")
    p.add_argument("--penumbra", metavar="ID|HASH", help="print a raw quarantined leaf + payload")
    p.add_argument("--raw", metavar="SOURCE_ID", help="a composer source's latest value + data date")
    p.add_argument("--axis", metavar="AXIS", help="demand this axis be sensed (requires --force)")
    p.add_argument("--force", action="store_true", help="confirm the --axis demand")
    p.add_argument("--priority", nargs=2, metavar=("AXIS", "N"), help="rank an axis for the needs report")
    p.add_argument("--ledger", action="store_true", help="prophecy ledger status")
    a = p.parse_args(argv)

    if a.penumbra:
        return cmd_penumbra(a.penumbra)
    if a.raw:
        return cmd_raw(a.raw)
    if a.axis:
        if not a.force:
            print("--axis queues a demand that bypasses the system's own salience ranking.")
            print("Say so explicitly: --axis <AXIS> --force")
            return 2
        return cmd_axis_force(a.axis)
    if a.priority:
        return cmd_priority(a.priority[0], a.priority[1])
    if a.ledger:
        return cmd_ledger()

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
