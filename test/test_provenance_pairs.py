#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_provenance_pairs.py — two provenances, side by side, and NOTHING computed.

Stage 3 is divergence detection. Kimi gated it on having "at least 3 axes with paired
series of different provenance" FIRST, because a divergence layer built before the
taxonomy exists is a lie detector that only ever listens to the accused: if both series
in a pair come from the same aggregator of the same national reporting, disagreement
between them measures rounding, not truth.

So the load-bearing test in this file is the one asserting that no observation record
contains a difference, a ratio or an agreement score. "Just a delta, it's free" is the
exact temptation to resist — a delta published before anyone has established that the two
series measure the same quantity for the same entity is a number that will be read as
evidence and is not one.

  venv\\Scripts\\python.exe test\\test_provenance_pairs.py
"""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "composers"))

from core import provenance_pairs as PP   # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


TMP = Path(tempfile.mkdtemp())
PP.PAIRS_FILE = TMP / "pairs.json"

PROBE = REPO / "test" / "_pairs_probe.json"
PROBE.write_text(json.dumps({"primary": 73.7, "aggregate": 74.1, "empty": None}),
                 encoding="utf-8")
OTHER = REPO / "test" / "_pairs_other.json"
OTHER.write_text(json.dumps({"aggregate": 74.1}), encoding="utf-8")


def side(label, path, extract, entity="World", org="X"):
    return {"label": label, "entity": entity,
            "source": {"kind": "file", "path": path, "extract": extract, "org": org}}


P = side("UN direct", "test/_pairs_probe.json", "primary", org="UN SDG")
A = side("aggregate", "test/_pairs_other.json", "aggregate", org="World Bank")


# ── what makes a pair a pair ─────────────────────────────────────────────────

err = raises(PP.record_pair, "p", "AX", "ind", "World", P, A, confirmed_by="")
check("a pair with no human confirming it is refused", err is not None)
check("...because whether two series measure the same thing is not the system's call",
      "not evidence" in err)

err = raises(PP.record_pair, "p", "AX", "ind", "World",
             P, side("agg", "test/_pairs_other.json", "aggregate", entity="EU27"),
             confirmed_by="Emil")
check("sides about DIFFERENT entities are refused", err is not None)
check("...naming the mismatch, because pairing them would manufacture a divergence "
      "out of geography",
      "'EU27'" in err and "different populations" in err)

err = raises(PP.record_pair, "p", "AX", "ind", "World",
             P, side("agg", "test/_pairs_probe.json", "aggregate"),
             confirmed_by="Emil")
check("two sides on the SAME ORIGIN are not two provenances", err is not None)
check("...named as the fake diversity it is",
      "same origin" in err and "two labels" in err)

rec = PP.record_pair("water", "WATER_REVIEW", "safe water %", "World", P, A,
                     confirmed_by="Emil", why="both are JMP 6.1.1")
check("a sound pair records", rec["confirmed_by"] == "Emil")
check("...deriving each side's origin and reporter class rather than trusting a label",
      rec["primary"]["origin"] == "test/_pairs_probe.json"
      and rec["aggregate"]["origin"] == "test/_pairs_other.json")
check("...and keeping the human's reason on the record",
      rec["why_same_quantity"] == "both are JMP 6.1.1")


# ── the system may propose; nothing counts it ────────────────────────────────

PP.propose("guess", "AX", "ind", "World", P, A, why="they look similar")
check("a PROPOSED pair is stored", "guess" in (PP._load().get("proposed") or {}))
check("...and is not a pair", "guess" not in PP.list_pairs())
check("...and is excluded from readiness, but counted so it is not invisible",
      PP.readiness()["proposed_not_counted"] == 1
      and "AX" not in PP.readiness()["axes_with_a_confirmed_pair"])
check("...and says on its own record that it is inadmissible",
      "cannot make it" in PP._load()["proposed"]["guess"]["status"])

PP.record_pair("guess", "AX", "ind", "World", P, A, confirmed_by="Emil")
check("confirming a proposal promotes it out of `proposed`",
      "guess" in PP.list_pairs() and "guess" not in (PP._load().get("proposed") or {}))


# ── THE LOAD-BEARING ONE: nothing is computed ────────────────────────────────

PP.observe()
doc = PP._load()
obs = doc["pairs"]["water"]["observations"][-1]
check("an observation records both sides as read", obs["primary"]["value"] == 73.7
      and obs["aggregate"]["value"] == 74.1)
check("...with each side's own data date slot", "data_date" in obs["primary"])

# Scan the OBSERVATION RECORDS, not the whole file: the prose that PROMISES nothing is
# computed necessarily contains the words "difference", "ratio" and "agreement", and a
# grep over the raw JSON flags its own disclaimer. The claim being made is about the data.
flat = json.dumps([o for p in doc["pairs"].values()
                   for o in (p.get("observations") or [])]).lower()
for banned in ("delta", "diff", "ratio", "agreement", "divergence", "gap", "spread",
               "discrepanc", "z_score", "residual"):
    check(f"NOTHING IS COMPUTED: no {banned!r} in any observation record",
          banned not in flat)
check("...and the record says so in words, so nobody adds one later",
      "No difference, ratio, agreement score or flag is derived here"
      in doc["pairs"]["water"]["computes_nothing"])
check("...the module states the reason: a delta before layer 4 is not evidence",
      "lie detector that only ever listens to the accused"
      in " ".join(PP.__doc__.split()))
check("the observation holds exactly the two sides and a timestamp — no derived key",
      set(obs) == {"ts", "primary", "aggregate"})

# a side that will not yield is recorded AS a failure, not smoothed into a gap
check("a pair whose sides share an origin is refused even when both sides would yield",
      raises(PP.record_pair, "broken", "OTHERAX", "ind", "World", P,
             side("empty aggregate", "test/_pairs_probe.json", "empty", org="WB"),
             confirmed_by="Emil") is not None
      and "broken" not in PP.list_pairs())

PP.record_pair("broken", "OTHERAX", "ind", "World", P,
               side("empty aggregate", "test/_pairs_other.json", "nonexistent", org="WB"),
               confirmed_by="Emil")
PP.observe("broken")
o = PP._load()["pairs"]["broken"]["observations"][-1]
check("a side that will not yield records an ERROR, not a silent gap",
      "error" in o["aggregate"] and "value" not in o["aggregate"])
check("...while the working side still records its value", o["primary"]["value"] == 73.7)


# ── readiness distinguishes a pair from paired DATA ──────────────────────────

r = PP.readiness()
check("readiness counts confirmed pairs", r["pairs_confirmed"] == 3)
check("...and the axes they cover",
      set(r["axes_with_a_confirmed_pair"]) == {"WATER_REVIEW", "AX", "OTHERAX"})
check("...but counts an axis as READY only where BOTH sides yielded",
      set(r["axes_with_BOTH_sides_yielding"]) == {"WATER_REVIEW", "AX"})
check("a confirmed pair whose aggregate never yields does NOT make its axis ready",
      "OTHERAX" not in r["axes_with_BOTH_sides_yielding"])
check("...and the gate is measured on the second number, not the flattering one",
      r["stage3_ready"] is False and r["stage3_axes_required"] == 3)
check("...the report says which number means anything",
      "is not paired data" in r["note"])

PP.observe()
r = PP.readiness()
check("a third axis with both sides yielding flips the gate",
      len(r["axes_with_BOTH_sides_yielding"]) == 2 and r["stage3_ready"] is False)


# ── the live store, as it actually stands ────────────────────────────────────

LIVE = REPO / "memory" / "provenance_pairs.json"
if LIVE.exists():
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    lp = live.get("pairs") or {}
    check(f"the live store holds pairs ({len(lp)})", len(lp) >= 3)
    check("every live pair has a human confirming it",
          all(p.get("confirmed_by") for p in lp.values()))
    check("every live pair crosses two origins",
          all(p["primary"]["origin"] != p["aggregate"]["origin"] for p in lp.values()))
    check("every live pair is about one entity",
          all(p["primary"]["entity"] == p["aggregate"]["entity"] for p in lp.values()))
    flat = json.dumps([o for p in lp.values()
                       for o in (p.get("observations") or [])]).lower()
    check("and the live observations compute nothing either",
          not any(b in flat for b in ("delta", "ratio", "agreement", "divergence")))
    check("every live observation holds exactly two sides and a timestamp",
          all(set(o) == {"ts", "primary", "aggregate"}
              for p in lp.values() for o in (p.get("observations") or [])))

for f in (PROBE, OTHER):
    f.unlink(missing_ok=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
