#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/institution/publish_table.py — the public table, and the gate in front of it.

INSTITUTION #0 (WITNESS STAGE) publishes counts about named armed actors. That is
a thing to be careful with, so what reaches cortex-civilization-watch is filtered
twice and neither filter is a matter of taste:

  1. ONLY register entries whose `status` begins "confirmed_by_" appear — the
     shape a HUMAN ruling leaves. On 18 Sep 2026 (evening) Emil confirmed all
     four, so this gate now OPENS. Before that they read
     "proposed_by_claude_2026-09-18", meaning a model had drafted them from
     commitment texts it had not opened. Publishing
     an unconfirmed attribution about the Sudanese Armed Forces, the RSF, the
     Government of Rwanda, the Government of Israel or Hamas — under this
     project's name, on a public repository — is not something a machine decides.
     Emil confirms an entry and only then can it be published.

  2. NOTHING is published without UCDP's citation line. The dataset's terms
     require the dataset and its VERSION to be cited, and the version is not
     decoration here: UCDP backfills, so a count without `as_of` is a number
     whose vintage nobody knows.

SO ON 18 SEPTEMBER 2026 THIS FUNCTION RETURNS None AND PUBLISHES NOTHING, and
that is the correct output rather than a failure. `render()` says how many
entries it filtered and why, so an empty result is legible instead of looking
like a broken step.

THE CITATION IS NOT YET VERBATIM. UCDP's exact wording sits behind the same
account flow as its API, which answered 401 today, and I did not scrape around
it. CITATION_UNVERIFIED is True until someone reads the terms page and fixes the
text; while it is True, `render()` refuses even a confirmed entry. A citation we
invented would be worse than no publication.

  venv\\Scripts\\python.exe experiments/institution/publish_table.py            # dry run
  venv\\Scripts\\python.exe experiments/institution/publish_table.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]

REGISTER = REPO / "config" / "commitments.json"
LEDGER = REPO / "experiments" / "institution" / "ledger.jsonl"

# A status is publishable when a HUMAN set it. The shape is
# "confirmed_by_<person>_<date>", so the prefix is what is matched and the rest is
# kept as a record of who ruled and when. A bare "confirmed" would let a model write
# the one field it must not write.
PUBLISHABLE_PREFIX = "confirmed_by_"

# Placeholder wording, drafted from the citation convention in UCDP's codebooks
# and NOT read off their terms page, which is account-gated. While the flag below
# is True nothing publishes, so this string cannot reach the public repo by
# accident — it is here so the shape is ready and the gap is visible.
CITATION_UNVERIFIED = True
CITATION = (
    "Source: UCDP Georeferenced Event Dataset (GED), {as_of}. "
    "Uppsala Conflict Data Program, Department of Peace and Conflict Research, "
    "Uppsala University — https://ucdp.uu.se/ . "
    "Counts are of one-sided violence against civilians (type_of_violence = 3). "
    "The attribution of an event to an actor is UCDP's, not this project's."
)


def confirmed_entries(register: Optional[dict] = None) -> list[dict]:
    reg = register if register is not None else json.loads(
        REGISTER.read_text(encoding="utf-8"))
    return [c for c in reg.get("commitments", [])
            if str(c.get("status", "")).startswith(PUBLISHABLE_PREFIX)]


def latest_lines(ledger: Path = LEDGER) -> list[dict]:
    if not ledger.exists():
        return []
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        return []
    newest = max(r["ts"] for r in rows)
    return [r for r in rows if r["ts"] == newest]


def render(register: Optional[dict] = None,
           lines: Optional[list[dict]] = None) -> tuple[Optional[str], dict]:
    """(markdown or None, why). None means nothing is publishable, with a reason."""
    reg = register if register is not None else json.loads(
        REGISTER.read_text(encoding="utf-8"))
    allc = reg.get("commitments", [])
    ok = confirmed_entries(reg)
    why = {"register_entries": len(allc), "confirmed": len(ok),
           "withheld": len(allc) - len(ok),
           "statuses": sorted({c.get("status") for c in allc}),
           "citation_unverified": CITATION_UNVERIFIED}

    if CITATION_UNVERIFIED:
        why["reason"] = ("UCDP's citation line has not been read off their terms page "
                         "(account-gated; the API answered 401 on 18 Sep 2026). Nothing "
                         "publishes until it is verbatim.")
        return None, why
    if not ok:
        why["reason"] = ("no register entry has a status beginning %r — every entry is a "
                         "proposal a human has not confirmed" % PUBLISHABLE_PREFIX)
        return None, why

    rows = lines if lines is not None else latest_lines()
    by_id = {r.get("commitment_id"): r for r in rows if r.get("kind") == "commitment"}
    as_of = next((r.get("as_of") for r in rows if r.get("as_of")), "unknown")

    out = ["# Commitments and civilian targeting", "",
           "One row per party to a confirmed, publicly dated commitment: events "
           "recorded in the last complete month, against that actor's own 36-month "
           "distribution of the same statistic.", "",
           "**This is not a causal claim.** A rise after a commitment is not the "
           "commitment failing and a fall is not it working. These are counts.", "",
           "| commitment | date | actor (UCDP `side_a`) | last month | prior 3 mean | "
           "ratio | its own p90 | verdict |",
           "|---|---|---|---:|---:|---:|---:|---|"]
    for c in ok:
        line = by_id.get(c["id"])
        if line is None:
            continue
        for a in line.get("actors", []):
            if a.get("link") != "verified":
                continue          # an unverified actor link never goes public
            out.append("| %s | %s | `%s` | %s | %s | %s | %s | %s |"
                       % (c["title"], c["date"], a["side_a"],
                          a["ucdp_events_osv_last_month"], a["mean_prior_3"],
                          a["ratio"], a["null_p90"], a["verdict"]))
    out += ["", CITATION.format(as_of=as_of), ""]
    why["reason"] = "published"
    return "\n".join(out), why


def selftest() -> dict:
    out = {"register": str(REGISTER)}
    md, why = render()
    out["renders"] = md is not None
    out["why"] = why
    # The gate, exercised rather than described: a confirmed entry still does not
    # publish while the citation is unverified.
    fake = {"commitments": [{"id": "x", "title": "T", "date": "2025-01-01",
                             "status": "confirmed_by_emil_2026-09-18"}]}
    md2, why2 = render(fake, [])
    out["confirmed_entry_with_unverified_citation_publishes"] = md2 is not None
    out["expected"] = False
    out["ok"] = (md is None) and (md2 is None)
    return out


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        print(json.dumps(selftest(), ensure_ascii=False, indent=2))
        return 0
    md, why = render()
    print(json.dumps(why, ensure_ascii=False, indent=2))
    if md is None:
        print("\nNOTHING PUBLISHED — see reason above. This is the correct output today.")
    else:
        print("\n" + md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
