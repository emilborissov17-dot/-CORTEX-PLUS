#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cycle_vector.py — THE CYCLE END WRITES ITS OWN STATE.

24 Aug 2026.

`cockpit/vector.append()` has existed since COMMAND 21 with no caller.
`memory/state_vectors.jsonl` has never existed. `warming()` has reported
`0/20 cycles` since the day it was written, so the lexicon cannot warm, no glyph
can be fitted, and a STATUS line — which the grammar says needs exactly one
glyph — has been structurally impossible for weeks. Every plan that depended on
the lexicon has been blocked behind one missing wire.

This is the wire. One call, once, at the end of a cycle that reached its end.

WHAT IS WRITTEN
-----------------
25 dimensions from `cockpit.somatic.VECTOR_FIELDS` plus the 4 `CYCLE_FIELDS`,
29 in all. A dimension that could not be measured stays `None` and never 0.0 —
a sensor that could not be read must not look like a sensor that read zero, and
k-means cannot tell those apart once they are both numbers.

WHAT IS NOT WRITTEN
---------------------
A cycle the survival gate REFUSED writes nothing. It did no work, it has no
duration, and its body readings describe a machine that was too starved to
start — feeding that to the lexicon would teach it that "refused" is a state the
system can be in while working, which is the opposite of true.

FAIL-OPEN, LOUDLY
-------------------
A cycle must never die because it failed to describe itself. Every path here is
wrapped and the failure is printed with its exception type; the cycle then seals
normally. Silence on failure would be worse than the missing line, because the
lexicon would simply appear to warm more slowly than it should and nobody would
know why.

The write goes through `core.durable` — flush and fsync. A vector lost in the
page cache to a kill is, as far as the lexicon is concerned, a cycle that never
happened.

    venv/Scripts/python.exe core/cycle_vector.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# The path is passed explicitly at every call site. cockpit/vector.append()
# requires it and has no default, deliberately — see the writer rule in
# test/test_cockpit.py — and this module does not invent one either.
STORE = BASE / "memory" / "state_vectors.jsonl"

REFUSED_EVENT = "CYCLE_REFUSED_SURVIVAL_GATE"


LOCK_PATH = BASE / "memory" / "cycle.lock"


def _duration_from_lock(lock_path=None):
    """Seconds since this cycle took its lock, or None.

    The ledger holds duration_sec, but it is written by CYCLE_FINISHED and the
    vector is assembled BEFORE the seal — so at this moment the ledger does not
    yet know. The lock does: it carries started_utc, and this is the same
    arithmetic _seal_cycle_record() does a few lines later.
    """
    from datetime import datetime, timezone
    try:
        raw = json.loads(pathlib.Path(lock_path or LOCK_PATH)
                         .read_text(encoding="utf-8"))
        started = raw.get("started_utc")
        if not started:
            return None
        t0 = datetime.fromisoformat(started)
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - t0).total_seconds(), 1)
    except Exception:
        return None


def cycle_metrics(cycle_id=None, duration_sec=None,
                  steps_completed=None, degraded_ratio=None,
                  flow_score=None, lock_path=None, contract=None) -> dict:
    """The 4 CYCLE_FIELDS, read from the repo where they are not supplied.

    ALL FOUR WERE None ON EVERY ROW (found 27 Aug 2026, all 7 vectors in
    memory/state_vectors.jsonl). The 25 sensor dims were fine; the block that
    says what the CYCLE did was empty, so a lexicon trained on these points
    could describe the machine's body and nothing about its work.

    Two separate causes, and neither announced itself:

      * nothing was ever passed in. fast_cycle_runner calls write() with a
        cycle_id and a store path, and every metric defaulted.
      * the one fallback that existed probed for `core.flow_score.latest()`,
        which DOES NOT EXIST. hasattr() said False, the branch was skipped, and
        a missing function is indistinguishable from a missing measurement.
        core.flow_score has compute()/history(); nothing in the repo calls
        either, and memory/flow_score.jsonl has never been written — so
        history() would have been empty too. compute() is the live answer.

    Explicit arguments still win: this only fills what the caller left None.
    """
    out = {"cycle_id": cycle_id, "duration_sec": duration_sec,
           "steps_completed": steps_completed,
           "integrity_ratio": None, "degraded_ratio": None,
           "failed_ratio": None, "cloud_success_ratio": None,
           "pace_median_s": None}

    if out["duration_sec"] is None:
        out["duration_sec"] = _duration_from_lock(lock_path)

    # NO COMPOSITE ENTERS THE VECTOR. flow_score was written here — a
    # completeness ratio multiplied by a speed — so the learning trace could not
    # tell "did less work" from "took longer" and a lexicon fitted on it would
    # cluster the two together permanently. The five arrive separately and stay
    # separate; `pace_median_s` is the speed, as its own dimension, never folded
    # into a quality.
    try:
        from core import cycle_integrity as ci
        m = ci.scalars(contract_path=contract)
        out["integrity_ratio"] = m["integrity_ratio"]
        out["degraded_ratio"] = m["degraded_ratio"]
        out["failed_ratio"] = m["failed_ratio"]
        out["cloud_success_ratio"] = m["cloud_success_ratio"]
        out["pace_median_s"] = m["median_step_seconds"]
        if out["steps_completed"] is None:
            # steps_FULL under the stricter definition: completed, not degraded,
            # not timed out, answered by the expected source.
            out["steps_completed"] = m.get("steps_full")
    except Exception:
        pass

    if degraded_ratio is not None:
        out["degraded_ratio"] = degraded_ratio
    if flow_score is not None:
        # An explicit fs from an old caller is REFUSED rather than silently
        # dropped: writing it would put a composite back into the trace.
        raise ValueError(
            "flow_score is no longer a vector field. It was a completeness "
            "ratio multiplied by a speed; use core.cycle_integrity.scalars() "
            "and pass the scalars you mean.")
    return out


def was_refused(cycle_id, ledger_rows=None) -> bool:
    """Did the survival gate refuse this cycle? Then it has nothing to describe."""
    try:
        if ledger_rows is None:
            from memory import existence_ledger as ledger
            ledger_rows = ledger.read_all()
    except Exception:
        return False
    for row in reversed(list(ledger_rows or [])):
        ev = str(row.get("event", "")).upper()
        if ev == REFUSED_EVENT and (cycle_id is None
                                    or row.get("cycle_id") == cycle_id):
            return True
        if ev in ("CYCLE_FINISHED", "CYCLE_STARTED") and \
                row.get("cycle_id") == cycle_id:
            return False
    return False


def write(cycle_id=None, store_path=None, probe=None, metrics=None,
          ledger_rows=None) -> dict:
    """Assemble one cycle-end vector and append it. NEVER RAISES.

    Returns a record describing what happened, which the caller prints.
    """
    out = {"written": False, "path": None, "why": "", "dims": None,
           "measured": None, "cycle_id": cycle_id}
    try:
        p = pathlib.Path(store_path or STORE)
        out["path"] = str(p)

        if was_refused(cycle_id, ledger_rows):
            out["why"] = ("the survival gate refused this cycle — it did no "
                          "work and has no state to describe")
            return out

        from cockpit import vector as vec
        m = metrics if metrics is not None else cycle_metrics(cycle_id=cycle_id)
        v = vec.assemble(probe=probe, cycle_metrics=m)

        # A dimension that could not be measured stays None. Asserted here
        # rather than trusted, because a 0.0 in this file is permanent: the
        # lexicon fits on it and cannot tell it from a real reading.
        # `vector` is a LIST aligned with `fields`, not a dict — pairing them
        # here rather than assuming, because an off-by-one between the two
        # would mislabel every dimension in the store permanently.
        fields = list(v.get("fields") or [])
        values = list(v.get("vector") or [])
        if len(fields) != len(values):
            out["why"] = "fields/vector length mismatch: {} vs {}".format(
                len(fields), len(values))
            return out
        unresolved = set(v.get("unresolved_fields") or [])
        zeroed = [f for f, val in zip(fields, values)
                  if val == 0.0 and f in unresolved]
        if zeroed:
            out["why"] = "unresolved fields arrived as 0.0: {}".format(zeroed)
            return out

        line = json.dumps(v, ensure_ascii=False)
        from core.durable import append_durable
        ok = append_durable(p, line)
        if not ok:
            out["why"] = "core.durable refused the write"
            return out

        out.update(written=True, dims=v.get("dims"),
                   measured=v.get("measured"),
                   unresolved=v.get("unresolved_fields"),
                   why="appended")
        return out
    except Exception as exc:
        out["why"] = "{}: {}".format(type(exc).__name__, exc)
        return out


def write_at_cycle_end(cycle_id=None, store_path=None, **kw) -> dict:
    """What fast_cycle_runner calls. Prints its own outcome; never raises."""
    rec = write(cycle_id=cycle_id, store_path=store_path, **kw)
    p = pathlib.Path(store_path or STORE)
    if rec["written"]:
        try:
            from cockpit import vector as vec
            w = vec.warming(p)
            print("[FAST_CYCLE] state vector appended: {}/{} dims measured — {}"
                  .format(rec["measured"], rec["dims"], w["label"]))
        except Exception:
            print("[FAST_CYCLE] state vector appended: {}/{} dims measured"
                  .format(rec["measured"], rec["dims"]))
    else:
        # LOUD. A cycle that failed to describe itself still seals, but the
        # lexicon would otherwise just look slow to warm and nobody would know.
        print("[FAST_CYCLE] STATE VECTOR NOT WRITTEN: {} — the cycle seals "
              "normally".format(rec["why"]))
    return rec


def _selftest() -> int:
    import tempfile
    print("core/cycle_vector.py --selftest\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    d = pathlib.Path(tempfile.mkdtemp())
    store = d / "state_vectors.jsonl"

    rec = write(cycle_id="selftest", store_path=store, ledger_rows=[])
    check("it writes a vector ({})".format(rec["why"]), rec["written"] is True)
    check("the file exists", store.exists())

    rows = [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines()]
    check("one line", len(rows) == 1)
    v = rows[0]
    check("25 dims", v.get("dims") == 25)
    # Derived from CYCLE_FIELDS rather than restated, so the next change to the
    # schema cannot leave this assertion describing the previous one. It used to
    # name the four fields literally, and flow_score was one of them.
    from cockpit import vector as _vf
    check("the {} cycle fields travel with it".format(len(_vf.CYCLE_FIELDS)),
          set(v.get("cycle", {})) == set(_vf.CYCLE_FIELDS))
    check("{} measurable keys in all".format(25 + len(_vf.CYCLE_FIELDS)),
          len(v.get("vector", [])) + len(v.get("cycle", {}))
          == 25 + len(_vf.CYCLE_FIELDS))
    check("fields and vector line up",
          len(v.get("fields", [])) == len(v.get("vector", [])) == 25)
    nones = [f for f, x in zip(v["fields"], v["vector"]) if x is None]
    check("unmeasured dims are None, not 0.0 ({} of them)".format(len(nones)),
          all(x is not None or x is None for x in v["vector"])
          and 0.0 not in [v["vector"][v["fields"].index(f)] for f in
                          (v.get("unresolved_fields") or [])])

    from cockpit import vector as vec
    check("warming() moved to 1/20", vec.warming(store)["cycles"] == 1)

    refused = write(cycle_id="c-refused", store_path=store, ledger_rows=[
        {"event": REFUSED_EVENT, "cycle_id": "c-refused"}])
    check("a refused cycle writes nothing", refused["written"] is False)
    check("and says why", "refused" in refused["why"])
    check("the file did not grow",
          len(store.read_text(encoding="utf-8").splitlines()) == 1)

    broken = write(cycle_id="x", store_path=d / "nope" / "deep" / "x.jsonl",
                   ledger_rows=[])
    check("an unwritable path is reported, not raised",
          isinstance(broken, dict))

    print("\n  {}".format("every check passed" if ok else "SOMETHING FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())

    # DRY RUN BY DEFAULT, --write TO APPEND (27 Aug 2026).
    #
    # Running this module bare used to APPEND A ROW TO THE LIVE LEARNING TRACE.
    # It did exactly that during this command's own development: a row with
    # cycle_id=None, from no cycle, landed in memory/state_vectors.jsonl simply
    # because somebody ran the file to see what it did. The row was removed, but
    # the foot-gun is the bug — a module whose default action mutates the
    # evidence is one keystroke from corrupting it, and the lexicon fits on
    # exactly these rows.
    #
    # Looking is now free; writing is a decision.
    if "--write" in sys.argv:
        print(json.dumps(write(store_path=STORE), indent=2, default=str))
    else:
        from cockpit import vector as _v
        preview = _v.assemble(cycle_metrics=cycle_metrics())
        print("DRY RUN — nothing was written. Pass --write to append.\n")
        print(json.dumps({"would_append_to": str(STORE),
                          "dims": preview.get("dims"),
                          "measured": preview.get("measured"),
                          "cycle": preview.get("cycle"),
                          "unresolved_fields": preview.get("unresolved_fields")},
                         indent=2, default=str))
