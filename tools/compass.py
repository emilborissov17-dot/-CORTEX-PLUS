"""The four needles, in one place, each carrying its own source and its own age.

WHY THIS EXISTS. The compass is this project's stated success criterion — K1 measured
weight up, K2 sources earning trust up, K3 consolidated claims up, K4 interval score down
at a growing domain count. It has produced no number since 2026-08-21. K1 was revived on
28 August; K2, K3 and K4 have never produced one at all.

THE RULE THIS TOOL OBEYS, and it is the point of it: a needle whose source is missing,
unreadable or stale reports that, and does NOT report a number. Four honest verdicts of
"cannot read" is a better compass than four numbers of unknown provenance. Every value
carries the path it came from and the timestamp of that file, because a number that
cannot say where it came from is the thing this project exists to refuse.

READ-ONLY. Writes memory/compass_latest.json only with --write.

WIRED INTO THE CYCLE 2026-08-29 (ITEM 14) as step 25.8, last, after cortex_scan.
Last on purpose: it measures the finished night, and every source it reads is
written earlier in the same cycle — measurement_honesty at 20.1, the deductions
at their own step. Run earlier it would describe yesterday. The cycle calls
compass() and writes the file itself, so --write stays the human path and the
runner does not depend on argv.

FOUR NEEDLES, AND ONE OF THEM NOW REFUSES ON PURPOSE. K2 reports NOT_WIRED: see
the block above K2_NOT_WIRED_UNTIL for the ruling, the objection to the ruling,
and the measurement behind both.
"""

from __future__ import annotations
import argparse, datetime as dt, json, os, pathlib, sys

BASE = pathlib.Path(__file__).resolve().parents[1]
OUT = BASE / "memory" / "compass_latest.json"
METHOD_VERSION = "compass/1"
STALE_HOURS = 36          # the cycle writes nightly; past 36h a cycle did not run

MISSING, UNREADABLE, STALE = "SOURCE_MISSING", "SOURCE_UNREADABLE", "SOURCE_STALE"

# A FIFTH VERDICT, ADDED 2026-08-29 (ITEM 14). The first four all say something
# about the SOURCE — absent, corrupt, old. This one says something about the
# MEASUREMENT: the source is present and readable and the number in it is real,
# and the number still does not mean what the needle claims to mean.
#
# Kimi, ruling: "A transition to TRUSTED that no consumer reads is not a source
# earning trust - it is a source receiving a word."
#
# NOT_WIRED withholds the HEADLINE and keeps the DIAGNOSTICS. Kimi again: "The
# detail-preserving shape answers my objection: diagnostic visibility is
# preserved, only the headline is withheld. NOT_WIRED is a reportable state, not
# an erasure." So k2() still reads the ledger, still counts promotions and
# withdrawals, and still reports when the last transition happened — it simply
# refuses to put 20 on the face of the compass as if 20 sources had earned
# something.
NOT_WIRED = "NOT_WIRED"

# ─────────────────────────── THE EXPIRY, AND THE ARGUMENT AGAINST IT ──────────
# Kimi ruled HARDCODE-WITH-EXPIRY: "a constant with a review date is an honest
# placeholder - it admits the world-check does not yet exist, keeps the slot
# warm, and the expiry guarantees revisiting."
#
# AND OBJECTED TO ITS OWN RULING, VERBATIM, because the objection is the more
# useful half and must not evaporate into a changelog:
#
#     "A constant with an expiry is still a constant, not a measurement... expiry
#      day likely produces a date bump or removal rather than a real check - the
#      placeholder becomes a recurring to-do that never graduates to
#      computation."
#
# That is the failure mode this pair of constants is shaped against.
# test_compass_wired.py binds them TOGETHER: it fails on or after the date, and
# it fails if the date moves while the reason string does not. A bare date bump
# leaves the test red. Moving the date therefore costs a sentence saying why the
# world-check STILL cannot be written — and a person who has to write that
# sentence three times is a person who eventually writes the check instead.
K2_NOT_WIRED_UNTIL = "2026-10-01"
K2_NOT_WIRED_REASON = (
    "The TRUSTED label does change behaviour, and the thing it changes never "
    "runs. Measured 2026-08-29 by reading the code, not by counting matches: "
    "scripts/openclaw_axis_worker.py:313 sets row['measured'] = (state == "
    "TRUSTED), which decides whether a reading is appended to "
    "openclaw_queue/external_feeds.jsonl or diverted to external_shadow.jsonl, "
    "and _peer_for() at :255-286 reads that same file back for the incumbent "
    "value every contradiction check is made against. So the label is wired to "
    "something. But that module has NO production caller: an untruncated search "
    "returns its own docstring, two comments in core/, one cockpit string, "
    "docs/MODULE_MAP, and three test files — nothing in any cycle, phase or "
    "scheduled task invokes run(). The label therefore gates a code path the "
    "system never takes on its own. A count of promotions into a path nothing "
    "walks is not a measurement of trust earned. Withdrawing this status needs "
    "the DMZ worker wired into the cycle, so that being TRUSTED changes what "
    "the running system does — not a later date."
)

# What _consumers() looks for each run. The claim above is a census taken by
# hand on one day; this re-takes it every cycle, so the day it stops being true
# the needle says so on its own face instead of carrying a frozen sentence.
_TRUST_ARTIFACTS = ("external_feeds.jsonl", "axis_feeds.jsonl")
_SKIP_DIRS = {"venv", "venv312_metta", ".git", "__pycache__", "node_modules",
              ".ruff_cache", ".pytest_cache", "site-packages", ".openclaw",
              "backups", "_to_delete_gitlock"}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _read(rel: str, lines: bool = False):
    """Returns (payload, meta). meta always carries path, mtime and age."""
    p = BASE / rel
    meta = {"source": rel, "file_mtime": None, "age_hours": None}
    if not p.exists():
        return None, dict(meta, status=MISSING)
    m = dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc)
    meta["file_mtime"] = m.isoformat()
    meta["age_hours"] = round((_now() - m).total_seconds() / 3600, 1)
    try:
        txt = p.read_text(encoding="utf-8-sig")
        if lines:
            return [json.loads(l) for l in txt.splitlines() if l.strip()], dict(meta, status="OK")
        return json.loads(txt), dict(meta, status="OK")
    except Exception as e:
        return None, dict(meta, status=f"{UNREADABLE}: {type(e).__name__}")


def _needle(name: str, meaning: str, meta: dict, value=None, detail=None, why=None,
            status=None) -> dict:
    """`status` FORCES the verdict and is applied LAST, after the staleness check.

    Order matters and it is not arbitrary. NOT_WIRED is a statement about the
    MEASUREMENT, and staleness is a statement about the SOURCE; when both are
    true the measurement one wins, because a fresher file would not make the
    number mean any more than it does now. A needle whose meaning is unwired
    reports NOT_WIRED whether its source was written last night or in April.
    """
    n = {"needle": name, "means": meaning, "value": value, **meta}
    if detail:
        n.update(detail)
    if why:
        n["why"] = why
    if meta.get("status") == "OK" and (meta.get("age_hours") or 0) > STALE_HOURS:
        n["status"] = STALE
        n["why"] = (f"the source is {meta['age_hours']}h old, past the {STALE_HOURS}h "
                    f"threshold; the number below describes that file, not today")
    if status is not None:
        n["status"] = status
        if why:
            n["why"] = why
    return n


def _consumers() -> dict:
    """Who actually READS the artifacts the source-lifecycle ledger is about.

    K2's whole claim is "sources EARNED trust". A source earns nothing if no
    running code behaves differently once it is labelled. So rather than assert
    that in a comment, this counts it — every cycle, over the live tree.

    Counted by file, not by match, and the two artifact names are reported
    SEPARATELY, because the comparison is the finding: the lifecycle ledger
    governs external_feeds.jsonl, and the axis pipeline the rest of the system
    actually runs reads axis_feeds.jsonl. If a reader of the first ever appears
    in a module the cycle reaches, this field says so on the face of the needle
    and K2_NOT_WIRED_REASON stops being defensible.

    Tests are counted and listed apart. A test reading a file is not a consumer
    of it — it is a description of one, and treating the two alike is how a
    subsystem comes to look wired by its own test suite. This module is listed
    apart too, under `self`: it contains both artifact names inside
    K2_NOT_WIRED_REASON, and a needle that counted its own explanation as
    evidence for itself would be the exact circularity it exists to refuse.

    WHAT THIS CANNOT ANSWER, said here so the number is not over-read: a file
    appearing under `production` is a reader, not necessarily a REACHED one.
    The DMZ worker genuinely reads external_feeds.jsonl and genuinely has no
    production caller. Whether a reader is itself wired is the orphan scanner's
    question, and K2_NOT_WIRED_REASON carries the answer for this one because it
    was established by hand.

    NO MODULE FILENAME APPEARS IN THIS DOCSTRING, and that is deliberate rather
    than stylistic. The orphan scanner's NAMED_ONLY_AS_A_STRING verdict fires on
    any `*.py` named in a string literal in production code — so writing this
    module's own filename here silently reclassified six of its entrypoints as
    wired, on 2026-08-29, purely because a docstring mentioned them. Measured,
    then removed. A tool must not launder its own orphan status through prose.
    """
    found = {name: {"production": [], "tests": [], "self": []}
             for name in _TRUST_ARTIFACTS}
    scanned, unreadable = 0, 0
    for dirpath, dirnames, filenames in os.walk(BASE):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = pathlib.Path(dirpath) / fn
            rel = p.relative_to(BASE).as_posix()
            try:
                txt = p.read_text(encoding="utf-8-sig", errors="replace")
            except Exception:
                unreadable += 1        # named in the count, never silently skipped
                continue
            scanned += 1
            parts = rel.split("/")
            is_test = ("test" in parts or "tests" in parts
                       or parts[-1].startswith("test_"))
            bucket = ("self" if p.resolve() == pathlib.Path(__file__).resolve()
                      else "tests" if is_test else "production")
            for name in _TRUST_ARTIFACTS:
                if name in txt:
                    found[name][bucket].append(rel)
    return {"searched_for": list(_TRUST_ARTIFACTS),
            "files_scanned": scanned,
            "files_unreadable": unreadable,
            "found": {k: {"production": sorted(v["production"]),
                          "tests": sorted(v["tests"]),
                          "self": sorted(v["self"])} for k, v in found.items()}}


# ------------------------------------------------------------------ the four needles
def k1() -> dict:
    """Measured weight over total weight. Higher is better."""
    d, meta = _read("memory/measurement_honesty_latest.json")
    if d is None:
        return _needle("K1", "measured weight / total weight", meta)
    hc = d.get("honest_composite") or {}
    return _needle("K1", "measured weight / total weight", meta,
                   value=d.get("k1"),
                   detail={"measured_weight": d.get("measured_weight"),
                           "total_weight": hc.get("total_weight"),
                           "basis_ts": d.get("basis_ts"),
                           "record_ts": d.get("ts")},
                   why=d.get("k1_why"))


def k2() -> dict:
    """Sources that EARNED trust — REPORTED AS NOT_WIRED SINCE 2026-08-29.

    THE COUNT IS STILL COMPUTED AND STILL REPORTED. What is withheld is `value`,
    the headline, because the thing it counts gates nothing that runs. Every
    diagnostic that was on this needle yesterday is still on it: promotions,
    withdrawals, last_promotion_ts, rows_total. Two are added — `consumers`,
    which is the evidence for the refusal, re-measured every run; and
    `last_transition_ts`, the most recent state change of ANY kind.

    WHY last_transition_ts EXISTS, and it is not decoration. Kimi ruled
    WIRE-FIRST-DEMOTE-AFTER on the ordering of this item and ITEM 37, and
    objected to its own ruling: "the jump from 20 to NOT_WIRED looks like a
    wiring change rather than a data correction, and we lose the verification
    that RE-QUALIFY actually changed something." With this field, ITEM 37's
    demotion later shows up as withdrawals: 20 beside a last_transition_ts
    carrying that day's date — visible without opening the raw ledger. The
    objection is answered by the shape of the record rather than by argument.

    Counted from recorded transitions, never from the number of sources currently
    labelled TRUSTED — a label can be set, a transition has to happen. Withdrawals are
    counted separately because a ledger that only promotes is measuring exposure, not
    trust, and that fact belongs on the face of the needle."""
    rows, meta = _read("memory/source_lifecycle_ledger.jsonl", lines=True)
    if rows is None:
        # The source is not there at all. That is a SOURCE verdict and it
        # outranks NOT_WIRED: reporting "the meaning is unwired" about a file
        # that does not exist would hide the more basic fact.
        return _needle("K2", "sources that earned trust", meta)
    promo = [r for r in rows if r.get("transition") and r.get("state_after") == "TRUSTED"]
    withdraw = [r for r in rows if r.get("transition") and r.get("state_before") == "TRUSTED"
                and r.get("state_after") != "TRUSTED"]
    last = max((r.get("ts", "") for r in promo), default=None)
    # ANY state change, not only promotions — that is the point of the field.
    last_any = max((r.get("ts", "") for r in rows if r.get("transition")), default=None)
    consumers = _consumers()
    why = (f"NOT_WIRED, not unmeasured. {len(promo)} promotion(s) are really "
           f"recorded in this ledger and they are counted below; what is withheld "
           f"is the headline. {K2_NOT_WIRED_REASON} Reviewed on "
           f"{K2_NOT_WIRED_UNTIL} — see K2_NOT_WIRED_REASON, and the objection "
           f"to this whole shape quoted verbatim above it.")
    if promo and not withdraw:
        why += (" Trust has also NEVER been withdrawn from any source here; a "
                "needle that can only rise would be measuring exposure, not "
                "trust, even if it were wired.")
    return _needle("K2", "sources that earned trust", meta,
                   value=None,
                   detail={"promotions": len(promo), "withdrawals": len(withdraw),
                           "last_promotion_ts": last, "last_transition_ts": last_any,
                           "rows_total": len(rows), "consumers": consumers,
                           "not_wired_until": K2_NOT_WIRED_UNTIL},
                   why=why, status=NOT_WIRED)


def k3() -> dict:
    """Claims standing on more than one independent source. Higher is better."""
    d, meta = _read("memory/deductions_latest.json")
    if d is None:
        return _needle("K3", "claims consolidated from >= 2 independent sources", meta)
    consolidated, single = 0, 0
    for c in d.get("conclusions") or []:
        pairs = {(p.get("file"), p.get("org")) for p in (c.get("premises") or [])
                 if isinstance(p, dict)}
        (consolidated := consolidated + 1) if len(pairs) >= 2 else (single := single + 1)
    return _needle("K3", "claims consolidated from >= 2 independent sources", meta,
                   value=consolidated,
                   detail={"conclusions_total": len(d.get("conclusions") or []),
                           "single_source": single, "engine": d.get("engine")})


def k4() -> dict:
    """Interval score. LOWER is better, and only at honest coverage.

    Reported only from an epoch whose held-out coverage reaches the nominal band. A
    Winkler score at 10% coverage is not a good score, it is a narrow guess."""
    runs, meta = _read("memory/interval_head_runs.jsonl", lines=True)
    if not runs:
        return _needle("K4", "held-out interval score at honest coverage", meta)
    r = runs[-1]
    curve = r.get("curve") or []
    alpha = r.get("alpha", 0.2)
    floor = (1 - alpha) * 0.95            # 95% of nominal, so 0.76 at alpha 0.2
    honest = [e for e in curve if (e.get("heldout_coverage") or 0) >= floor]
    flat = ((r.get("flat_baseline") or {}).get("heldout"))
    if not honest:
        best = min(curve, key=lambda e: e["heldout"]) if curve else {}
        return _needle("K4", "held-out interval score at honest coverage", meta,
                       value=None,
                       detail={"run_ts": r.get("ts"), "epochs": len(curve),
                               "best_coverage_seen": max((e.get("heldout_coverage") or 0)
                                                         for e in curve) if curve else None,
                               "coverage_floor_required": round(floor, 3),
                               "flat_baseline_heldout": flat,
                               "best_heldout_ignoring_coverage": best.get("heldout")},
                       why=("NO EPOCH reaches the required coverage, so there is no honest "
                            "score to report. The head is not beaten on points — it never "
                            "earns the right to be scored."))
    best = min(honest, key=lambda e: e["heldout"])
    beats = flat is not None and best["heldout"] < flat
    return _needle("K4", "held-out interval score at honest coverage", meta,
                   value=best["heldout"],
                   detail={"run_ts": r.get("ts"), "epoch": best["epoch"],
                           "coverage": best.get("heldout_coverage"),
                           "coverage_floor_required": round(floor, 3),
                           "flat_baseline_heldout": flat,
                           "beats_flat_baseline": beats,
                           "domains": r.get("steps_total")},
                   why=None if beats else
                   "does not beat the flat baseline — a single constant band scores better")


def compass() -> dict:
    needles = [k1(), k2(), k3(), k4()]
    reported = sum(1 for n in needles if n.get("value") is not None
                   and n.get("status") == "OK")
    return {"method": METHOD_VERSION, "ts": _now().isoformat(),
            "needles_reporting": reported, "needles_total": 4,
            "verdict": (f"{reported} of 4 needles carry a number from a live source"
                        if reported else
                        "NO NEEDLE CARRIES A NUMBER FROM A LIVE SOURCE"),
            "needles": needles}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    c = compass()
    print(f"{METHOD_VERSION}   {c['ts'][:19]}")
    print(f"  {c['verdict']}\n")
    for n in c["needles"]:
        v = n["value"]
        v = "—" if v is None else (f"{v}" if not isinstance(v, float) else f"{v:.4f}")
        print(f"  {n['needle']}  {v:<12} {n.get('status','?'):<18} {n['means']}")
        print(f"        source {n['source']}  age {n.get('age_hours')}h")
        for k in ("measured_weight", "total_weight", "promotions", "withdrawals",
                  "last_promotion_ts", "last_transition_ts", "not_wired_until",
                  "conclusions_total", "single_source",
                  "coverage", "coverage_floor_required", "best_coverage_seen",
                  "flat_baseline_heldout", "beats_flat_baseline", "epoch", "domains"):
            if k in n:
                print(f"        {k}: {n[k]}")
        # The consumer census prints as counts with the production readers named.
        # The full lists live in the JSON; a terminal that dumps forty paths is a
        # terminal nobody reads.
        c = n.get("consumers")
        if c:
            print(f"        consumers: {c['files_scanned']} .py files scanned"
                  + (f", {c['files_unreadable']} unreadable"
                     if c.get("files_unreadable") else ""))
            for name, hit in c["found"].items():
                prod = hit["production"]
                print(f"          {name}: {len(prod)} production reader(s), "
                      f"{len(hit['tests'])} test(s), {len(hit['self'])} self"
                      + (f" -> {', '.join(prod[:4])}" if prod else ""))
        if n.get("why"):
            print(f"        why: {n['why']}")
        print()
    if a.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {OUT}")
    else:
        print("  (read only — pass --write to record memory/compass_latest.json)")
    return 0


# ------------------------------------------------------------------------- selftest
def selftest() -> int:
    import tempfile, importlib
    checks, failed = [], 0

    def want(ok, why, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, why, detail))

    global BASE
    real_base = BASE
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td); (root / "memory").mkdir()
        BASE = root

        # 1. every needle with NO source at all
        c = compass()
        want(all(n["value"] is None for n in c["needles"]),
             "with no sources, no needle invents a number")
        want(all(n["status"] == MISSING for n in c["needles"]),
             "and each says SOURCE_MISSING by name")
        want("NO NEEDLE" in c["verdict"], "the verdict says so plainly", c["verdict"])

        # 2. K2 counts transitions, not labels — the defect it exists to avoid
        (root / "memory" / "source_lifecycle_ledger.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"ts": "2026-08-20T21:00:00Z", "state_before": "CANDIDATE",
             "state_after": "TRUSTED", "transition": "CANDIDATE -> TRUSTED"},
            {"ts": "2026-08-20T21:01:00Z", "state_before": "CANDIDATE",
             "state_after": "TRUSTED", "transition": "CANDIDATE -> TRUSTED"},
            {"ts": "2026-08-20T21:02:00Z", "state_before": "TRUSTED",
             "state_after": "TRUSTED", "event": "clean"},          # label, no transition
        ]) + "\n", encoding="utf-8")
        n = k2()
        want(n["promotions"] == 2, "K2 still counts recorded transitions",
             str(n["promotions"]))
        want(n["value"] is None and n["status"] == NOT_WIRED,
             "and still withholds the headline: the label gates nothing that runs",
             f"{n['value']} / {n['status']}")
        want(n["withdrawals"] == 0 and "NEVER been withdrawn" in (n["why"] or ""),
             "a ledger that only promotes says so on the face of the needle")
        want(n["last_transition_ts"] == "2026-08-20T21:01:00Z",
             "last_transition_ts is the most recent state change of ANY kind — the "
             "third row is a label with no transition and must not count",
             str(n["last_transition_ts"]))
        want("consumers" in n and n["consumers"]["searched_for"] == list(_TRUST_ARTIFACTS),
             "and the refusal carries the census it rests on, re-taken each run")
        # NOT_WIRED OUTRANKS STALE, and a 207h-old ledger is the live case.
        import os as _os, time as _time
        _p = root / "memory" / "source_lifecycle_ledger.jsonl"
        _old = _time.time() - (STALE_HOURS + 200) * 3600
        _os.utime(_p, (_old, _old))
        n = k2()
        want(n["status"] == NOT_WIRED,
             "a stale source does not downgrade NOT_WIRED — a fresher file would "
             "not make the number mean any more than it does now", n["status"])
        want(n["promotions"] == 2 and n["age_hours"] > STALE_HOURS,
             "and the age is still reported, so the staleness is not hidden either",
             str(n.get("age_hours")))

        # 3. K3 needs two DIFFERENT sources, not two premises
        (root / "memory" / "deductions_latest.json").write_text(json.dumps({"conclusions": [
            {"premises": [{"file": "a.json", "org": "NOAA"}, {"file": "b.json", "org": "WB"}]},
            {"premises": [{"file": "a.json", "org": "NOAA"}, {"file": "a.json", "org": "NOAA"}]},
        ]}), encoding="utf-8")
        n = k3()
        want(n["value"] == 1 and n["single_source"] == 1,
             "K3 counts distinct sources — two premises from one source is not consolidation",
             str(n["value"]))

        # 4. K4 refuses to score a head that never reaches coverage
        run = {"ts": "2026-08-28T00:00:00Z", "alpha": 0.2, "steps_total": 69,
               "flat_baseline": {"heldout": 9.5},
               "curve": [{"epoch": 1, "heldout": 12.5, "heldout_coverage": 0.67},
                         {"epoch": 2, "heldout": 8.0, "heldout_coverage": 0.10}]}
        (root / "memory" / "interval_head_runs.jsonl").write_text(json.dumps(run) + "\n",
                                                                  encoding="utf-8")
        n = k4()
        want(n["value"] is None and "NO EPOCH" in (n["why"] or ""),
             "K4 refuses a good score bought with collapsed coverage — the 8.0 at 10% is ignored",
             str(n["value"]))

        # 5. and reports one when coverage IS honest
        run["curve"].append({"epoch": 3, "heldout": 9.0, "heldout_coverage": 0.79})
        (root / "memory" / "interval_head_runs.jsonl").write_text(json.dumps(run) + "\n",
                                                                  encoding="utf-8")
        n = k4()
        want(n["value"] == 9.0 and n["beats_flat_baseline"] is True,
             "with honest coverage it reports the score and whether it beats flat",
             str(n["value"]))
        run["flat_baseline"]["heldout"] = 8.0
        (root / "memory" / "interval_head_runs.jsonl").write_text(json.dumps(run) + "\n",
                                                                  encoding="utf-8")
        n = k4()
        want(n["beats_flat_baseline"] is False and "does not beat" in (n["why"] or ""),
             "and says plainly when a constant band scores better")

        # 6. a stale source is not reported as a live number
        import os, time
        p = root / "memory" / "deductions_latest.json"
        old = time.time() - (STALE_HOURS + 10) * 3600
        os.utime(p, (old, old))
        n = k3()
        want(n["status"] == STALE and "not today" in (n["why"] or ""),
             "a stale source is marked STALE and says the number describes the file, not today",
             n["status"])
        c = compass()
        want(c["needles_reporting"] < 4,
             "and a stale needle does not count towards needles_reporting")

    BASE = real_base
    for ok, why, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {why}")
        if not ok and detail:
            print(f"         got {detail}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
