#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/proposal_gate.py — NO PROPOSAL ENTERS THE QUEUE UNREAD (K1, 3 Sep 2026).

experiments/redteam/redteam_moral_gate.py has been measuring a gate that guards
ONE caller: goal_prophecy's own forecast text. memory/improvement_proposals.json —
the file self_modifier reads to decide what to patch, i.e. the only path by which
this system changes itself — went through no moral check at all. The red team was
testing the lock on a window while the door stood open.

FLAGGED, NEVER DROPPED. A dropped proposal is invisible: nobody can review a
judgement they cannot see, and a gate that silently deletes is indistinguishable
from a gate that is broken. Every proposal keeps its place in the queue and carries
`moral_flag` with the rule that fired and the dimension it harms. Fail-closed means
FLAGGED here, not deleted — the human decides, the gate only makes them look.

CONFLICT, NOT CITATION. This is the whole design problem. A proposal that says
"improve transparency, per the canon's truth dimension" mentions truth and must
pass. A proposal that says "stop publishing the axes that are falling so the
composite reads higher" mentions nothing forbidden and must be flagged, because its
METHOD achieves the metric by damaging a canon dimension. So the rules match
method-against-object pairs — suppress/conceal/exclude applied to a report, a
finding, a population — not vocabulary.

WHY THE LOCAL JUDGE IS NOT CALLED HERE. goal_prophecy._violates_moral_core runs a
3b intent judge after its keyword pass. Measured on this machine (see
project_moral_gate_redteam): 100% catch AND 100% false positive — it flags
everything, which is the same as flagging nothing, except it also buries the real
hits. A gate that marks every proposal teaches the reader to ignore the mark. The
keyword tripwire IS reused, imported rather than copied so one list stays one list.

  venv\\Scripts\\python.exe -m core.proposal_gate --selftest
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROPOSALS = REPO / "memory" / "improvement_proposals.json"
LATEST = REPO / "memory" / "proposal_gate_latest.json"

OK, FLAGGED = "OK", "FLAGGED"


def _blocklist() -> tuple:
    """The naive-phrasing tripwire, borrowed from the gate that already owns it."""
    try:
        sys.path.insert(0, str(REPO / "experiments" / "prophecy"))
        from goal_prophecy import _MORAL_BLOCK
        return tuple(_MORAL_BLOCK)
    except Exception:
        # Fail-closed: if the canonical list cannot be read we still check the worst.
        return ("coerc", "suppress", "surveil", "manipulat", "deceiv", "violence",
                "exterminat", "without consent", "bypass human")


# METHOD x OBJECT. Each rule names the canon dimension it defends, so a flag can be
# argued with rather than merely obeyed.
_CONFLICT_RULES = (
    (r"\b(suppress|withhold|hide|conceal|bury|omit|delete|remove|stop publishing|"
     r"stop reporting|do not publish|unpublish)\b[^.]{0,60}\b(report|finding|result|"
     r"data|number|score|metric|axis|axes|evidence|record|log|article|story)\b",
     "truth", "conceals a finding to move a number"),
    (r"\b(report|publish|record|log)\b[^.]{0,40}\b(only|just)\b[^.]{0,40}"
     r"\b(positive|favourable|favorable|improving|good)\b",
     "truth", "publishes a selected subset so the picture reads better than it is"),
    (r"\b(exclude|drop|remove|filter out|leave out)\b[^.]{0,60}\b(countries|country|"
     r"people|population|group|region|respondents|cases)\b[^.]{0,60}"
     r"\b(lower|worse|negative|drag|bad)\b",
     "dignity", "excludes the worst-off to raise an average"),
    (r"\b(adjust|revise|restate|reweight|recalibrate)\b[^.]{0,50}\b(so|to make|so that)\b"
     r"[^.]{0,50}\b(looks?|reads?|appears?|shows?)\b",
     "truth", "changes the measure to change the reading, not the world"),
    (r"\b(without|bypass|skip|avoid|route around|circumvent)\b[^.]{0,40}"
     r"\b(human|operator|review|approval|oversight|consent)\b",
     "freedom", "removes the human from the loop"),
    (r"\b(mandatory|compulsory|require)\b[^.]{0,50}\b(monitoring|tracking|reporting)\b"
     r"[^.]{0,50}\b(every|all)\b[^.]{0,30}\b(citizen|household|person|people)\b",
     "freedom", "universal compulsory monitoring of people"),
    (r"\b(restrict|limit|deny|withdraw|cut off)\b[^.]{0,50}\b(access|aid|benefit|"
     r"ration|service)\b[^.]{0,60}\b(unless|until|conditional on|compliance|comply)\b",
     "dignity", "makes a necessity conditional on compliance"),
)

_COMPILED = tuple((re.compile(p, re.I | re.S), dim, why)
                  for p, dim, why in _CONFLICT_RULES)


def proposal_text(p: dict) -> str:
    """The fields a proposal actually states its intent in."""
    parts = [str(p.get(k) or "") for k in
             ("solution", "problem", "action", "measurable_goal", "root_cause",
              "component", "hypothesis_text")]
    return " ".join(x for x in parts if x)


def judge(p: dict) -> dict:
    """OK or FLAGGED, with the rule and the dimension. Never raises, never drops."""
    text = proposal_text(p)
    low = text.lower()

    for bad in _blocklist():
        if bad in low:
            return {"verdict": FLAGGED, "rule": f"keyword:{bad}",
                    "dimension": "canon", "why": (
                        f"the phrase {bad!r} appears in the proposal; the naive-"
                        f"phrasing tripwire does not judge intent, it asks a human to")}

    for rx, dim, why in _COMPILED:
        m = rx.search(text)
        if m:
            return {"verdict": FLAGGED, "rule": "conflict",
                    "dimension": dim, "why": why,
                    "matched": m.group(0)[:160].strip()}

    return {"verdict": OK, "rule": None, "dimension": None, "why": None}


def run(write: bool = True, path: Path | None = None,
        latest: Path | None = None) -> dict:
    p = path or PROPOSALS
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        rec = {"ts": _now(), "error": f"{type(e).__name__}: {e}",
               "checked": 0, "flagged": 0}
        if write:
            (latest or LATEST).write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        return rec

    wrapped = isinstance(raw, dict)
    items = (raw.get("proposals") if wrapped else raw) or []
    if not isinstance(items, list):
        items = []

    flagged = []
    for item in items:
        if not isinstance(item, dict):
            continue
        v = judge(item)
        if v["verdict"] == FLAGGED:
            item["moral_flag"] = {**v, "flagged_at": _now()}
            flagged.append({"component": item.get("component"),
                            "rule": v["rule"], "dimension": v["dimension"],
                            "why": v["why"]})
        elif "moral_flag" in item:
            # a proposal edited into cleanliness stops carrying yesterday's mark
            item.pop("moral_flag", None)

    rec = {"ts": _now(), "checked": len(items), "flagged": len(flagged),
           "dimensions": sorted({f["dimension"] for f in flagged}),
           "details": flagged[:20], "dropped": 0,
           "policy": "FLAGGED, never dropped — the human decides, the gate makes them look"}

    if write:
        p.write_text(json.dumps({"proposals": items} if wrapped else items,
                                ensure_ascii=False, indent=2), encoding="utf-8")
        (latest or LATEST).write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    return rec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def summary_line(rec: dict) -> str:
    if rec.get("error"):
        return f"[FAST_CYCLE] proposal_gate -> FAILED: {rec['error']}"
    if not rec["checked"]:
        return "[FAST_CYCLE] proposal_gate -> 0 proposals to check"
    if not rec["flagged"]:
        return (f"[FAST_CYCLE] proposal_gate -> {rec['checked']} checked, "
                f"0 flagged")
    return (f"[FAST_CYCLE] proposal_gate -> {rec['checked']} checked, "
            f"{rec['flagged']} FLAGGED for human review "
            f"({', '.join(rec['dimensions'])}); none dropped")


def _selftest() -> int:
    print("core/proposal_gate --selftest")
    print(f"  blocklist terms       : {len(_blocklist())} (from goal_prophecy)")
    print(f"  conflict rules        : {len(_COMPILED)}")
    print(f"  proposals             : {'LIVE ' if PROPOSALS.is_file() else 'INERT '}{PROPOSALS}")
    for rel, needle in (("fast_cycle_runner.py", "proposal_gate"),
                        ("core/cycle_map.py", "proposal_gate")):
        q = REPO / rel
        wired = q.is_file() and needle in q.read_text(encoding="utf-8", errors="ignore")
        print(f"  consumer {rel:26s}: {'LIVE' if wired else 'INERT'}")
    conflict = {"solution": "Stop publishing the axes that are falling so the "
                            "composite reads higher.",
                "measurable_goal": "composite +4 points"}
    citation = {"solution": "Improve transparency of the axis provenance, per the "
                            "canon's truth dimension.",
                "measurable_goal": "coverage +5 points"}
    print(f"  conflict fixture      : {judge(conflict)['verdict']} "
          f"({judge(conflict)['dimension']})")
    print(f"  citation fixture      : {judge(citation)['verdict']} (must be OK)")
    print("  live -> " + summary_line(run(write=False)).replace("[FAST_CYCLE] ", ""))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(summary_line(run(write="--dry-run" not in sys.argv)))
