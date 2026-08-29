"""Resolve the dreams.

The daily creative tick (experiments/pulse/pulse_continuum.py, SPEC part B.7) has
written 429 falsifiable hypotheses into memory/idea_stream.jsonl since 3 Aug 2026.
Every one carries a test_horizon. NONE has an outcome, because nothing has ever gone
back to look. The first horizon falls on 2026-09-02 and 226 fall due by 2026-09-10.

This closes that. It NEVER edits memory/idea_stream.jsonl — a ledger line is annotated,
not rewritten. Every verdict is appended to memory/idea_resolutions.jsonl, keyed by the
idea's ts, and that file is the evidence K3 and K4 have been missing.

WHAT IT CAN AND CANNOT DECIDE, stated rather than blurred:

  seed=trend           (420 of 429) — decided from data. The idea was born because an
                       axis series moved monotonically. The claim is that it continues.
                       Direction at birth vs direction at horizon; HELD, BROKE or FLAT.
  seed=rule_violation  (9 of 429) — NOT decided here. It needs the MeTTa oracle to say
                       whether the violated rule still fires. Emitted as NEEDS_ORACLE.
                       A guess dressed as a verdict is the defect this repo is built
                       against.

  dimension unmapped   — many ideas carry a loose dimension ('climate', 'AI') that is
                       not an axis key. Those are UNMAPPED, listed by name, and left for
                       a human to alias. They are not silently dropped and not guessed.

Series source: memory/axis_history.json, field "score" (0..100), the only per-axis dated
series on disk. Recorded in every row as series_source so a later reader can disagree
with the choice without having to re-derive it.

Usage:
    python tools/resolve_ideas.py                # dry run, prints the table
    python tools/resolve_ideas.py --write        # appends to memory/idea_resolutions.jsonl
    python tools/resolve_ideas.py --selftest     # fixtures, touches nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import tempfile

BASE = pathlib.Path(__file__).resolve().parents[1]
IDEAS = BASE / "memory" / "idea_stream.jsonl"
HISTORY = BASE / "memory" / "axis_history.json"
OUT = BASE / "memory" / "idea_resolutions.jsonl"

METHOD_VERSION = "resolve_ideas/1"
SERIES_SOURCE = "memory/axis_history.json:score"

# A move smaller than this is not a direction. 0.5 on a 0..100 axis score.
FLAT_EPS = 0.5
# How many points before birth define the direction the idea was born from.
BIRTH_WINDOW = 5
# How far past the horizon we will accept an observation.
HORIZON_SLACK_DAYS = 7

# Loose dimensions the generator emits that are not axis keys. Only aliases that are
# unambiguous appear here; anything doubtful stays UNMAPPED on purpose.
ALIAS_FILE = BASE / "config" / "idea_dimension_aliases.json"
TARGET = BASE / "config" / "target_config.json"

# A branch verdict needs enough of its axes to have spoken. Below this the branch
# score is a different quantity from one day to the next and cannot be compared.
BRANCH_MIN_MEMBERS = 2


class AliasFileError(RuntimeError):
    """The alias map could not be read. Never downgraded to a default."""


def _aliases() -> dict:
    """to_axis / to_branch / refused, from a human-written file.

    IT USED TO FAIL SOFT AND THAT WAS THE DEFECT (ITEM 23a, 29 Aug 2026). A
    missing or malformed file returned {"to_axis": {}, ...}, which does not
    crash — every idea simply comes back UNMAPPED. "We could not map this
    dimension" and "the mapping file is gone" then look identical in the output,
    and the second one is a broken deployment reported as a finding about the
    world. That is the exact substitution this queue exists to remove, and it
    was living inside the tool that grades the queue's own hypotheses.

    An EMPTY BUT VALID map is still accepted: a human who deliberately aliases
    nothing is not a missing file, and refusing that would trade one silent
    failure for a loud refusal to do the right thing.
    """
    try:
        raw = ALIAS_FILE.read_text(encoding="utf-8")
    except OSError as e:
        raise AliasFileError(
            f"cannot read the alias map at {ALIAS_FILE}: {type(e).__name__}: {e}. "
            f"Without it every dimension resolves to UNMAPPED, which would be "
            f"reported as a fact about the ideas rather than about this file."
        ) from e
    try:
        al = json.loads(raw)
    except ValueError as e:
        raise AliasFileError(
            f"the alias map at {ALIAS_FILE} is not valid JSON: {e}") from e
    if not isinstance(al, dict):
        raise AliasFileError(
            f"the alias map at {ALIAS_FILE} is a {type(al).__name__}, not an "
            f"object with to_axis / to_branch / refused")
    for k in ("to_axis", "to_branch", "refused"):
        v = al.setdefault(k, {})
        if not isinstance(v, dict):
            raise AliasFileError(
                f"the alias map at {ALIAS_FILE} has {k} as a "
                f"{type(v).__name__}, not an object")
    return al


def _series_state(path: pathlib.Path | None = None) -> dict:
    """The series these verdicts were computed from, so a number cannot travel
    without it (ITEM 23b).

    A verdict about a series is meaningless without the series. Measured on
    2026-08-29: the same 437 ideas scored 7.1% one day and 44.8% the next, and
    the only thing that had changed was one more day of axis_history. A hit rate
    quoted without this block is not a statement about the system's accuracy,
    and the tool should make that impossible to forget. K1 carries basis_ts for
    the same reason.
    """
    pth = path or HISTORY
    try:
        raw = pth.read_bytes()
    except OSError as e:
        return {"series_source": SERIES_SOURCE, "points_total": None,
                "axes_total": None, "series_latest_date": None,
                "series_sha256": None,
                "series_why": f"unreadable: {type(e).__name__}: {e}"}
    try:
        hist = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        return {"series_source": SERIES_SOURCE, "points_total": None,
                "axes_total": None, "series_latest_date": None,
                "series_sha256": hashlib.sha256(raw).hexdigest(),
                "series_why": f"not valid JSON: {e}"}
    points = 0
    latest = None
    for rows in hist.values():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict) or r.get("score") is None:
                continue
            points += 1
            d = str(r.get("date") or "")[:10]
            if d and (latest is None or d > latest):
                latest = d
    return {"series_source": SERIES_SOURCE,
            "points_total": points,
            "axes_total": len(hist) if isinstance(hist, dict) else None,
            "series_latest_date": latest,
            "series_sha256": hashlib.sha256(raw).hexdigest()}


def _drop_last_point(history: dict) -> dict:
    """The same history with the chronologically last scored point of every
    axis removed. Used only to ask whether a verdict depends on it."""
    out = {}
    for k, rows in history.items():
        if not isinstance(rows, list):
            out[k] = rows
            continue
        scored = [(i, r) for i, r in enumerate(rows)
                  if isinstance(r, dict) and r.get("date") is not None
                  and r.get("score") is not None]
        if len(scored) < 2:
            out[k] = rows
            continue
        last_i = max(scored, key=lambda pair: str(pair[1].get("date"))[:10])[0]
        out[k] = [r for i, r in enumerate(rows) if i != last_i]
    return out


def _branches() -> dict:
    """{branch: {axis: weight}} from config/target_config.json."""
    try:
        tc = json.loads(TARGET.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for bname, bval in tc.items():
        if bname.startswith("_") or not isinstance(bval, dict):
            continue
        members = {k: (v.get("weight") if isinstance(v, dict) else None)
                   for k, v in bval.items() if k.endswith("_REVIEW")}
        members = {k: (w if isinstance(w, (int, float)) else 1.0)
                   for k, w in members.items()}
        if members:
            out[bname] = members
    return out


# --------------------------------------------------------------------------- io
def _read_ideas(path: pathlib.Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _series(history: dict, key: str) -> list[tuple[dt.date, float]]:
    """(date, score) pairs, ascending, only rows that carry a numeric score."""
    rows = history.get(key) or []
    pts = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d, s = r.get("date"), r.get("score")
        if d is None or s is None:
            continue
        try:
            pts.append((dt.date.fromisoformat(str(d)[:10]), float(s)))
        except (ValueError, TypeError):
            continue
    pts.sort()
    return pts


def _map_dimension(dim: str, history: dict, al: dict,
                   branches: dict) -> tuple[str, str] | None:
    """('axis', key) or ('branch', name), or None when nothing honest fits."""
    if not dim:
        return None
    if dim in (al.get("refused") or {}):
        return None                     # named as refused by a human, on purpose
    ta, tb = al.get("to_axis") or {}, al.get("to_branch") or {}
    if dim in ta and ta[dim] in history:
        return ("axis", ta[dim])
    if dim in tb and tb[dim] in branches:
        return ("branch", tb[dim])
    if dim in history:
        return ("axis", dim)
    up = dim.upper()
    if up in history:
        return ("axis", up)
    if up in branches:
        return ("branch", up)
    cand = up if up.endswith("_REVIEW") else up + "_REVIEW"
    return ("axis", cand) if cand in history else None


def _branch_series(history: dict, members: dict
                   ) -> list[tuple[dt.date, float, int]]:
    """(date, weight-weighted mean score, members that spoke) for a branch.

    A branch has no series of its own. This builds one, and carries the member
    count on every point so a day assembled from two axes is never silently
    compared with a day assembled from five.
    """
    per = {a: dict((d, v) for d, v in _series(history, a)) for a in members}
    dates = sorted({d for m in per.values() for d in m})
    out = []
    for d in dates:
        num = den = 0.0
        n = 0
        for a, w in members.items():
            v = per.get(a, {}).get(d)
            if v is None:
                continue
            num += v * w
            den += w
            n += 1
        if n >= BRANCH_MIN_MEMBERS and den:
            out.append((d, num / den, n))
    return out


# ---------------------------------------------------------------------- verdict
def _direction(vals: list[float]) -> tuple[str, float]:
    """Direction across a list of values, and the size of the move."""
    if len(vals) < 2:
        return "NONE", 0.0
    delta = vals[-1] - vals[0]
    if abs(delta) < FLAT_EPS:
        return "FLAT", delta
    return ("UP" if delta > 0 else "DOWN"), delta


def resolve_one(idea: dict, history: dict, today: dt.date,
                _loo: bool = True) -> dict | None:
    """One verdict, or None when the horizon has not arrived.

    `_loo` is internal. When true, the verdict is computed a SECOND time against
    the same series with each axis's last point removed, and the row carries
    survives_leave_one_out. Measured on 2026-08-29 across 437 ideas: 82.8% of
    decided verdicts flip under that operation and NOT ONE HELD survives, so a
    verdict here is usually a statement about the most recent point rather than
    about a trend. The rule is deliberately NOT retuned to hide that — the flag
    makes a fragile verdict visibly fragile and the number is the finding.
    """
    hz_raw = idea.get("test_horizon")
    if not hz_raw:
        return None
    try:
        horizon = dt.date.fromisoformat(str(hz_raw)[:10])
    except ValueError:
        return None
    if horizon > today:
        return None

    base = {
        "ts_resolved": dt.datetime.now(dt.timezone.utc).isoformat(),
        "idea_ts": idea.get("ts"),
        "seed": idea.get("seed"),
        "dimension": idea.get("dimension"),
        "horizon": horizon.isoformat(),
        "method_version": METHOD_VERSION,
        # THE SERIES TRAVELS WITH THE VERDICT (ITEM 23b). Not decoration: the
        # same 437 ideas scored 7.1% and 44.8% one day apart, and only the
        # series had changed.
        **_series_state(),
        # None for verdicts that never read the series (UNMAPPED, NEEDS_ORACLE):
        # "not applicable" is not the same as "fragile" or "robust".
        "survives_leave_one_out": None,
        "verdict_without_last_point": None,
    }

    if idea.get("seed") != "trend":
        return {**base, "verdict": "NEEDS_ORACLE", "axis_key": None,
                "why": "seed is not 'trend'; deciding it requires the MeTTa oracle, "
                       "and a guess presented as a verdict is worse than an open item"}

    al, branches = _aliases(), _branches()
    hit = _map_dimension(str(idea.get("dimension") or ""), history, al, branches)
    if hit is None:
        refused = (al.get("refused") or {}).get(str(idea.get("dimension")))
        return {**base, "verdict": "UNMAPPED", "axis_key": None,
                "resolution_level": None,
                "why": (f"dimension {idea.get('dimension')!r}: {refused}"
                        if refused else
                        f"dimension {idea.get('dimension')!r} is neither an axis nor a "
                        f"branch of the goal tree; a human must alias it in "
                        f"config/idea_dimension_aliases.json or the generator must "
                        f"stop emitting it")}

    level, key = hit
    base = {**base, "resolution_level": level}
    if level == "branch":
        raw = _branch_series(history, branches[key])
        pts = [(d, v) for (d, v, _n) in raw]
        base = {**base, "branch_members": sorted(branches[key]),
                "branch_min_members": BRANCH_MIN_MEMBERS}
    else:
        pts = _series(history, key)
    if not pts:
        return {**base, "verdict": "NO_DATA", "axis_key": key,
                "why": (f"branch {key} has no day where at least "
                        f"{BRANCH_MIN_MEMBERS} member axes carried a score"
                        if level == "branch" else
                        f"{key} carries no dated numeric score")}

    try:
        birth = dt.date.fromisoformat(str(idea.get("ts"))[:10])
    except (ValueError, TypeError):
        return {**base, "verdict": "NO_DATA", "axis_key": key,
                "why": "the idea carries no readable ts"}

    before = [v for (d, v) in pts if d <= birth][-BIRTH_WINDOW:]
    after = [(d, v) for (d, v) in pts if birth < d <= horizon + dt.timedelta(
        days=HORIZON_SLACK_DAYS)]

    if len(before) < 2:
        return {**base, "verdict": "NO_DATA", "axis_key": key,
                "why": f"only {len(before)} point(s) on or before {birth} — the "
                       f"direction the idea was born from cannot be recovered"}
    if not after:
        return {**base, "verdict": "NO_DATA", "axis_key": key,
                "why": f"no observation between {birth} and {horizon} "
                       f"(+{HORIZON_SLACK_DAYS}d slack)"}

    born_dir, born_delta = _direction(before)
    v_birth = before[-1]
    obs_date, v_horizon = after[-1]
    now_dir, now_delta = _direction([v_birth, v_horizon])

    if born_dir in ("NONE", "FLAT"):
        verdict = "NO_CLAIM"
        why = (f"the series was not moving at birth (delta {born_delta:+.3f} over "
               f"{len(before)} points, below the {FLAT_EPS} floor) — there was no "
               f"trend to continue, so the idea was never falsifiable")
    elif now_dir == "FLAT":
        verdict = "FLAT"
        why = (f"born {born_dir} ({born_delta:+.3f}); by {obs_date} the move was "
               f"{now_delta:+.3f}, below the {FLAT_EPS} floor — the trend stopped "
               f"without reversing")
    elif now_dir == born_dir:
        verdict = "HELD"
        why = (f"born {born_dir} ({born_delta:+.3f}); {v_birth:.3f} -> {v_horizon:.3f} "
               f"by {obs_date} ({now_delta:+.3f}) — same direction")
    else:
        verdict = "BROKE"
        why = (f"born {born_dir} ({born_delta:+.3f}); {v_birth:.3f} -> {v_horizon:.3f} "
               f"by {obs_date} ({now_delta:+.3f}) — reversed")

    row = {**base, "verdict": verdict, "axis_key": key,
           "direction_at_birth": born_dir, "delta_at_birth": round(born_delta, 6),
           "points_at_birth": len(before),
           "value_at_birth": round(v_birth, 6),
           "value_at_horizon": round(v_horizon, 6),
           "observed_on": obs_date.isoformat(),
           "delta": round(now_delta, 6),
           "flat_eps": FLAT_EPS,
           "why": why}
    if _loo:
        shadow = resolve_one(idea, _drop_last_point(history), today, _loo=False)
        row["survives_leave_one_out"] = bool(
            shadow is not None and shadow.get("verdict") == verdict)
        row["verdict_without_last_point"] = (shadow or {}).get("verdict")
    return row


# ------------------------------------------------------------------------ main
def run(today: dt.date, write: bool) -> dict:
    ideas = _read_ideas(IDEAS)
    history = json.loads(HISTORY.read_text(encoding="utf-8"))

    already = set()
    if OUT.exists():
        for r in _read_ideas(OUT):
            if r.get("idea_ts"):
                already.add(r["idea_ts"])

    rows, counts, unmapped = [], {}, {}
    due = 0
    for idea in ideas:
        if idea.get("outcome") is not None:
            continue
        if idea.get("ts") in already:
            continue
        r = resolve_one(idea, history, today)
        if r is None:
            continue
        due += 1
        rows.append(r)
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        if r["verdict"] == "UNMAPPED":
            d = str(idea.get("dimension"))
            unmapped[d] = unmapped.get(d, 0) + 1

    decided = counts.get("HELD", 0) + counts.get("BROKE", 0)
    hit_rate = (counts.get("HELD", 0) / decided) if decided else None

    # (ITEM 23c) How much of this depends on the newest point in each series.
    fragile = sum(1 for r in rows if r.get("survives_leave_one_out") is False)
    judged = sum(1 for r in rows if r.get("survives_leave_one_out") is not None)
    frag_dec = sum(1 for r in rows
                   if r.get("verdict") in ("HELD", "BROKE")
                   and r.get("survives_leave_one_out") is False)

    summary = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "as_of": today.isoformat(),
        "ideas_total": len(ideas),
        "already_resolved": len(already),
        "due_now": due,
        "verdicts": counts,
        "decided": decided,
        "hit_rate": hit_rate,
        # A hit rate without the series it was computed from is not a number
        # about the system's accuracy (ITEM 23b).
        **_series_state(),
        # ITEM 23c: how many verdicts change if each series loses its last
        # point. fragile_of_decided is the one that matters — measured 82.8% on
        # 2026-08-29, with no HELD surviving at all.
        "fragile": fragile,
        "judged_for_fragility": judged,
        "fragile_of_decided": (frag_dec / decided) if decided else None,
        "unmapped_dimensions": unmapped,
        "wrote": False,
    }

    if write and rows:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary["wrote"] = True
        summary["appended"] = len(rows)

    return {"summary": summary, "rows": rows}


def _print(res: dict) -> None:
    s = res["summary"]
    print(f"as of {s['as_of']}  ideas {s['ideas_total']}  "
          f"already resolved {s['already_resolved']}  due now {s['due_now']}")
    print(f"series: {s.get('points_total')} points over {s.get('axes_total')} axes, "
          f"latest {s.get('series_latest_date')}, "
          f"sha256 {str(s.get('series_sha256'))[:12]}"
          + (f"  [{s['series_why']}]" if s.get("series_why") else ""))
    if s.get("fragile_of_decided") is not None:
        print(f"FRAGILITY: {s['fragile_of_decided']:.1%} of the {s['decided']} "
              f"decided verdicts change if each series loses its LAST POINT "
              f"({s['fragile']} of {s['judged_for_fragility']} judged overall). "
              f"A high number here means these are verdicts about today, not "
              f"about a trend.")
    if not s["due_now"]:
        print("nothing has reached its horizon yet — this is a fact, not an error.")
        return
    for k in ("HELD", "BROKE", "FLAT", "NO_CLAIM", "NO_DATA",
              "UNMAPPED", "NEEDS_ORACLE"):
        if k in s["verdicts"]:
            print(f"  {k:<12} {s['verdicts'][k]}")
    if s["hit_rate"] is not None:
        print(f"  hit rate on the {s['decided']} that could be decided: "
              f"{s['hit_rate']*100:.1f}%")
    else:
        print("  hit rate: undefined — nothing could be decided from data")
    if s["unmapped_dimensions"]:
        print("  unmapped dimensions (a human must alias or the generator must stop):")
        for d, n in sorted(s["unmapped_dimensions"].items(), key=lambda x: -x[1]):
            print(f"    {d}  x{n}")
    print("  (dry run — nothing written)" if not s["wrote"]
          else f"  appended {s['appended']} row(s) to {OUT}")


def _selftest() -> int:
    print("tools/resolve_ideas.py --selftest")
    ok = True
    checks = []
    hist = {"WATER_REVIEW": [
        {"date": "2026-08-01", "score": 50.0},
        {"date": "2026-08-02", "score": 52.0},
        {"date": "2026-08-03", "score": 54.0},
        {"date": "2026-09-05", "score": 60.0},
    ]}
    up = {"ts": "2026-08-03T00:00:00+00:00", "seed": "trend",
          "dimension": "WATER_REVIEW", "test_horizon": "2026-09-04", "outcome": None}
    r = resolve_one(up, hist, dt.date(2026, 9, 6))
    checks.append(("a continuing rise is HELD", r and r["verdict"] == "HELD"))

    hist2 = json.loads(json.dumps(hist))
    hist2["WATER_REVIEW"][-1]["score"] = 40.0
    r2 = resolve_one(up, hist2, dt.date(2026, 9, 6))
    checks.append(("a reversal is BROKE", r2 and r2["verdict"] == "BROKE"))

    hist3 = json.loads(json.dumps(hist))
    hist3["WATER_REVIEW"][-1]["score"] = 54.2
    r3 = resolve_one(up, hist3, dt.date(2026, 9, 6))
    checks.append((f"a move under the {FLAT_EPS} floor is FLAT",
                   r3 and r3["verdict"] == "FLAT"))

    flat = {"WATER_REVIEW": [{"date": "2026-08-01", "score": 50.0},
                             {"date": "2026-08-02", "score": 50.1},
                             {"date": "2026-08-03", "score": 50.2},
                             {"date": "2026-09-05", "score": 70.0}]}
    r4 = resolve_one(up, flat, dt.date(2026, 9, 6))
    checks.append(("a trend that never existed is NO_CLAIM",
                   r4 and r4["verdict"] == "NO_CLAIM"))

    r5 = resolve_one({**up, "seed": "rule_violation"}, hist, dt.date(2026, 9, 6))
    checks.append(("a rule_violation is NEEDS_ORACLE, never guessed",
                   r5 and r5["verdict"] == "NEEDS_ORACLE"))

    r6 = resolve_one({**up, "dimension": "vibes"}, hist, dt.date(2026, 9, 6))
    checks.append(("an unknown dimension is UNMAPPED, never coerced",
                   r6 and r6["verdict"] == "UNMAPPED"))

    r7 = resolve_one(up, hist, dt.date(2026, 8, 10))
    checks.append(("a future horizon returns nothing", r7 is None))

    r8 = resolve_one(up, {"WATER_REVIEW": [{"date": "2026-08-03", "score": 54.0}]},
                     dt.date(2026, 9, 6))
    checks.append(("one point cannot give a direction — NO_DATA",
                   r8 and r8["verdict"] == "NO_DATA"))

    # negative control: the resolver must not invent a verdict from an empty series
    r9 = resolve_one(up, {"WATER_REVIEW": []}, dt.date(2026, 9, 6))
    checks.append(("an empty series is NO_DATA, not HELD",
                   r9 and r9["verdict"] == "NO_DATA"))

    for name, good in checks:
        print(("  OK   " if good else "  FAIL ") + name)
        ok = ok and bool(good)
    print("every check passed" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="append verdicts to memory/idea_resolutions.jsonl")
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD, default today (UTC)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    today = (dt.date.fromisoformat(a.as_of) if a.as_of
             else dt.datetime.now(dt.timezone.utc).date())
    res = run(today, a.write)
    _print(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
