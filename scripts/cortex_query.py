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
  cortex_query.py --clock                  what the portfolio stands on: origin
                                           concentration, who measured it, collector counters
  cortex_query.py --candidates             the FULL candidate pool (random sample if large)
  cortex_query.py --rejected [--since D]   everything considered and dropped, with reasons
  cortex_query.py --pairs                  direct-vs-aggregate pairs, both sides verbatim

The write half of human sovereignty over intake — proposing a source the system never
found — is deliberately NOT here: see scripts/cortex_ingest.py. That command must run the
system's real registration path, which means importing project code, and this file's whole
guarantee is that it imports none. A read that cannot be mediated and a write that must be
executed are different operations and they live in different files.
"""
from __future__ import annotations

import argparse
import json
import random
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
DISCOVERED      = REPO / "memory" / "discovered_data_sources.json"
DISCARDED       = REPO / "memory" / "discarded_candidates.jsonl"
SPEC_FILE       = REPO / "config" / "composer_specs.json"
REPORTER_FILE   = REPO / "config" / "reporter_independence.json"
INSTRUMENT      = REPO / "memory" / "collector_instrumentation.json"
PAIRS_FILE      = REPO / "memory" / "provenance_pairs.json"

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


# ── --clock ──────────────────────────────────────────────────────────────────
#
# DELIBERATE DUPLICATION. origin() and the reporter lookup exist in
# experiments/composers/provenance.py and are re-implemented here in nine lines of string
# work. Importing that module would put a project code path between Emil and the bytes,
# which is the one thing this file may never do. The price is two implementations; the
# guard against drift is test_origin_honesty.py, which runs BOTH over the live spec and
# fails if they ever disagree about a single source.

def _host(url):
    s = str(url or "").strip().split("://", 1)[-1].split("/", 1)[0]
    return s.split("@")[-1].split(":")[0].lower()


def _origin(src):
    explicit = str(src.get("origin") or "").strip()
    if explicit:
        return explicit
    if src.get("kind") == "file":
        return str(src.get("path") or "?")
    return _host(src.get("url")) or "?"


def _reporter(src, confirmed):
    on_rec = str(src.get("reporter_class") or "").strip()
    if on_rec and str(src.get("reporter_class_confirmed_by") or "").strip():
        return on_rec
    for key in (f"host:{_host(src.get('url'))}" if src.get("url") else None,
                f"org:{src.get('org')}" if src.get("org") else None,
                f"path:{src.get('path')}" if src.get("path") else None):
        if key and key in confirmed:
            return confirmed[key].get("class", "unknown")
    return "unknown"


def cmd_clock(threshold: float = 0.5) -> int:
    """The counters, unranked and unsummarised: what the portfolio actually stands on,
    who measured it, and whether the collecting loop has been anywhere lately."""
    specs = _read_json(SPEC_FILE, {}) or {}
    confirmed = (_read_json(REPORTER_FILE, {}) or {}).get("confirmed") or {}
    composed = _read_json(COMPOSED_OUT, {}) or {}

    print(RULE)
    print("PORTFOLIO CLOCK — origin concentration and who measured it")
    print(RULE)
    print("origin = what a source RESOLVES to: the file it is read from, or the host it is")
    print("fetched from. NOT the `org` label, which is free text written at discovery.")
    print()

    all_srcs, flagged, nominal = [], [], []
    print(f"{'axis':<38} {'src':>4} {'orig':>5} {'top share':>10}  top origin")
    for axis, body in sorted(specs.items()):
        if axis.startswith("_"):
            continue
        srcs = [s for sl in (body.get("portfolio") or {}).values()
                for s in sl.get("sources", [])]
        all_srcs += srcs
        if not srcs:
            print(f"{axis:<38} {0:>4} {'-':>5} {'-':>10}  (no sources declared)")
            continue
        counts = {}
        for s in srcs:
            o = _origin(s)
            counts[o] = counts.get(o, 0) + 1
        top, n = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        share = n / len(srcs)
        mark = "  <== origin_concentrated" if share > threshold else ""
        if share > threshold:
            flagged.append(axis)
        print(f"{axis:<38} {len(srcs):>4} {len(counts):>5} {share:>9.0%}  {top[:44]}{mark}")

        for slot, rep in ((composed.get(axis) or {}).get("slots") or {}).items():
            if rep.get("nominally_filled"):
                nominal.append(f"{axis}/{slot}")

    print()
    print(RULE)
    print("REPORTER INDEPENDENCE — who produced the statistic")
    print(RULE)
    print("Layers 1 and 2 are closed: we did not invent it, and we read it correctly.")
    print("Layer 3 is OPEN. A self-reported number is the measured entity's account of")
    print("itself. This is shown, never scored — discounting it would be a truth claim.")
    print()
    tally, unmapped = {}, set()
    for s in all_srcs:
        c = _reporter(s, confirmed)
        tally[c] = tally.get(c, 0) + 1
        if c == "unknown":
            if s.get("org"):
                unmapped.add(f"org:{s['org']}")
            if s.get("url"):
                unmapped.add(f"host:{_host(s['url'])}")
    total = sum(tally.values()) or 1
    for c in ("self_reported", "independent", "adversarial", "unknown"):
        print(f"  {c:<16} {tally.get(c, 0):>4}  {tally.get(c, 0) / total:>5.0%}")
    print(f"  {'TOTAL':<16} {total:>4}")

    self_only = []
    for axis, body in sorted(specs.items()):
        if axis.startswith("_"):
            continue
        srcs = [s for sl in (body.get("portfolio") or {}).values()
                for s in sl.get("sources", [])]
        if srcs and all(_reporter(s, confirmed) == "self_reported" for s in srcs):
            self_only.append(axis)

    print()
    print(f"origin_concentrated  {len(flagged)} axis/axes: {', '.join(flagged) or 'none'}")
    print(f"nominally_filled     {len(nominal)} slot(s): {', '.join(nominal) or 'none'}")
    print(f"self_reported_only   {len(self_only)} axis/axes: {', '.join(self_only) or 'none'}")
    if unmapped:
        print(f"\nawaiting your ruling ({len(unmapped)} org/host with no confirmed class —")
        print(f"unknown is never read as independent). Add to config/reporter_independence.json:")
        for k in sorted(unmapped):
            print(f"  {k}")

    inst = _read_json(INSTRUMENT, {}) or {}
    if inst:
        print()
        print(RULE)
        print(f"COLLECTOR, LAST {inst.get('window_days', '?')} DAYS")
        print(RULE)
        print("A decline rate on its own cannot tell an honest guard from a stuck loop —")
        print("both report ~90%. Read it only with the three counters beneath it.")
        print()
        print(f"  runs                 {inst.get('runs')}")
        print(f"  decline_rate         {inst.get('decline_rate')}")
        print(f"  distinct_urls_tried  {inst.get('distinct_urls_tried')}")
        print(f"  distinct_queries     {inst.get('distinct_queries')}")
        print(f"  axes_touched         {inst.get('n_axes_touched')}  "
              f"{inst.get('axes_touched')}")
        print(f"  seen_skipped         {inst.get('seen_skipped')}")
    else:
        print(f"\n(no collector instrumentation yet at {_rel(INSTRUMENT)})")
    return 0


# ── --candidates ─────────────────────────────────────────────────────────────

CANDIDATE_PRINT_LIMIT = 40


def _all_candidates():
    doc = _read_json(DISCOVERED, {}) or {}
    out = []
    for axis, entry in doc.items():
        if not isinstance(entry, dict):
            continue
        for s in entry.get("sources", []):
            out.append((axis, s))
    return out


def cmd_candidates(limit: int = CANDIDATE_PRINT_LIMIT, seed=None) -> int:
    """The WHOLE pool, or a RANDOM sample of it.

    Never a relevance-ranked subset. Ranking is where the agenda lives: whatever the
    system considers most relevant is exactly the axis along which it could quietly steer
    what a human ever looks at, and it would do so while appearing helpful. A random
    sample is dumber and cannot be steered — and the seed is printed, so any sample can
    be reproduced and argued with.
    """
    cands = _all_candidates()
    if not cands:
        print(f"no candidates in {_rel(DISCOVERED)}")
        return 0

    print(RULE)
    print(f"CANDIDATE POOL — {len(cands)} record(s) across "
          f"{len({a for a, _ in cands})} axes")
    print(RULE)
    by_status = {}
    for _a, s in cands:
        st = s.get("status", "?")
        by_status[st] = by_status.get(st, 0) + 1
    print("by status: " + ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())))

    shown, note = cands, "all of them"
    if len(cands) > limit:
        seed = random.randrange(1 << 30) if seed is None else int(seed)
        rng = random.Random(seed)
        shown = rng.sample(cands, limit)
        note = (f"a RANDOM sample of {limit} (seed {seed}; rerun with --seed {seed} to get "
                f"this exact sample). NOT the 'most relevant' — that ranking is the system's "
                f"opinion and it is not offered here")
    print(f"showing: {note}")
    print()

    for axis, s in shown:
        rule = {k: s[k] for k in ("extract", "col", "column_name", "row_key", "path")
                if s.get(k) is not None}
        print(f"[{s.get('status', '?')}] {axis}")
        print(f"    org     {s.get('org') or '?'}")
        print(f"    metric  {s.get('metric') or '?'}")
        print(f"    url     {s.get('url') or '?'}")
        print(f"    kind    {s.get('kind') or '(none derived)'}   slot_hint "
              f"{s.get('slot_hint') or '-'}")
        print(f"    rule    {rule or '(none — this one cannot be fetched as it stands)'}")
        if s.get("rule_derivation"):
            print(f"    derived {s['rule_derivation']}")
        for k in ("rejected_why", "incomplete_why", "unblacklist_reason"):
            if s.get(k):
                print(f"    {k:<7} {str(s[k])[:150]}")
    return 0


# ── --rejected ───────────────────────────────────────────────────────────────

def _after(ts, since):
    if not since:
        return True
    try:
        return str(ts or "") >= str(since)
    except Exception:
        return True


def cmd_rejected(since=None) -> int:
    """Everything considered and dropped, with the reason, and whether it was ever
    actually contacted. Two different things live here and conflating them is what cost
    OWID and the World Bank their place in the portfolio:

      rejected    a real fetch was made and it failed. Evidence about the source.
      incomplete  our record was missing a field. Evidence about US.
      discarded   never registered at all — no rule could be derived from its payload.
    """
    rows = []
    for axis, s in _all_candidates():
        st = s.get("status")
        if st in ("rejected", "incomplete"):
            ts = s.get("rejected_at") or s.get("incomplete_at") or ""
            if _after(ts, since):
                rows.append((ts, st, axis, s.get("org"), s.get("url"),
                             s.get("rejected_why") or s.get("incomplete_why"),
                             s.get("rejected_class")))
    for d in _read_jsonl(DISCARDED):
        if _after(d.get("ts"), since):
            rows.append((d.get("ts", ""), "discarded", d.get("axis"), None,
                         d.get("url"), d.get("reason"), d.get("stage")))
    rows.sort()

    print(RULE)
    print("EVERYTHING CONSIDERED AND DROPPED" + (f" SINCE {since}" if since else ""))
    print(RULE)
    print("rejected   = a real fetch failed. Evidence about the source.")
    print("incomplete = our record lacked a field. Evidence about US, not about them.")
    print("discarded  = never registered: no parsing rule derivable from its payload.")
    print("Only 'rejected' is a verdict on a provider. It requires having asked.")
    print()
    if not rows:
        print("nothing dropped in this window.")
        return 0
    for ts, st, axis, org, url, why, extra in rows:
        print(f"{str(ts)[:19]:<19} [{st}] {axis or '?'}")
        print(f"    {org or ''} {str(url)[:96]}")
        print(f"    reason: {str(why)[:220]}")
        if extra:
            print(f"    {'class' if st == 'rejected' else 'stage'}: {extra}")
    print()
    counts = {}
    for _t, st, *_r in rows:
        counts[st] = counts.get(st, 0) + 1
    print("totals: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


# ── --pairs ──────────────────────────────────────────────────────────────────

def cmd_pairs() -> int:
    """Both sides of every direct-vs-aggregate pair, as read. NOTHING IS COMPUTED here
    either — this prints what core/provenance_pairs.py stored, and that module derives no
    difference, ratio or agreement score by design. A delta published before anyone has
    established that two series measure the same quantity for the same entity is a number
    that will be read as evidence and is not one."""
    doc = _read_json(PAIRS_FILE, {}) or {}
    pairs = doc.get("pairs") or {}
    print(RULE)
    print("DIRECT vs AGGREGATE PAIRS — the same quantity from two provenances")
    print(RULE)
    if not pairs:
        print(f"no pairs recorded at {_rel(PAIRS_FILE)}")
        return 0
    axes_both = set()
    for pid, p in pairs.items():
        print(f"\n{pid}   [{p.get('axis')}]   entity={p.get('entity')}")
        print(f"  {p.get('indicator')}")
        print(f"  same quantity because: {str(p.get('why_same_quantity'))[:200]}")
        print(f"  confirmed by {p.get('confirmed_by')} on "
              f"{str(p.get('confirmed_at'))[:10]}")
        last = (p.get("observations") or [{}])[-1]
        for side in ("primary", "aggregate"):
            s = p.get(side) or {}
            r = last.get(side) or {}
            got = (f"{r['value']}  ({r.get('data_date')})" if "value" in r
                   else f"NO VALUE — {str(r.get('error'))[:90]}")
            print(f"  {side:<10} {s.get('reporter_class'):<14} {s.get('origin')}")
            print(f"  {'':<10} {s.get('label')}")
            print(f"  {'':<10} -> {got}")
        if "value" in (last.get("primary") or {}) and "value" in (last.get("aggregate") or {}):
            axes_both.add(p.get("axis"))
    print()
    print(RULE)
    print(f"pairs confirmed          {len(pairs)}")
    print(f"axes with a pair         {len({p.get('axis') for p in pairs.values()})}")
    print(f"axes with BOTH sides     {len(axes_both)}   <- only this one means Stage 3 "
          f"has anything to look at")
    print("Stage 3 (divergence) was gated on 3 axes of paired series of DIFFERENT "
          "provenance.")
    print("A confirmed pair whose aggregate side never yields is not paired data.")
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
    p.add_argument("--clock", action="store_true",
                   help="origin concentration, reporter independence, collector counters")
    p.add_argument("--candidates", action="store_true",
                   help="the FULL candidate pool, or a random sample — never ranked")
    p.add_argument("--seed", help="reproduce an earlier --candidates sample")
    p.add_argument("--rejected", action="store_true",
                   help="every candidate considered and dropped, with the reason")
    p.add_argument("--since", metavar="ISO", help="limit --rejected to this date onward")
    p.add_argument("--pairs", action="store_true",
                   help="direct-vs-aggregate pairs, both sides as read (nothing computed)")
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
    if a.clock:
        return cmd_clock()
    if a.candidates:
        return cmd_candidates(seed=a.seed)
    if a.rejected:
        return cmd_rejected(since=a.since)
    if a.pairs:
        return cmd_pairs()

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
