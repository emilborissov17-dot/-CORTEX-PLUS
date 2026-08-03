#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/cortex_ingest.py — Emil proposes a source the system never found.

WHY THIS IS A SEPARATE FILE FROM cortex_query.py
------------------------------------------------
cortex_query's guarantee is structural: it imports nothing from the project, so no salience
filter, confidence discount or summarizer can ever sit between the human and the bytes, and
an AST test enforces it. Ingest cannot live under that guarantee — it must run the system's
REAL registration and smoke-fetch path, or it would prove nothing. Reaching for subprocess
to smuggle it in would open exactly the vector the gate exists to close, for every command
in that file including the reads. So: a read that must not be mediated and a write that
must be executed are different operations, and they live in different files.

WHY IT EXISTS AT ALL
--------------------
Every source in the portfolio arrived the same way: an LLM suggested it, the system probed
it, the system registered it, the system offered it. If the only thing a human can approve
is what that pipeline surfaced, then the human is ratifying the system's search bubble and
calling it oversight. This is the door in the other direction. What comes through it gets
the SAME treatment as anything the system found — the same rule derivation, the same schema
wall, the same smoke fetch through the same loader — and the same refusal to be promoted
without an explicit human act. No special pleading in either direction.

  # propose a source, derive its rule from a real fetch, smoke-test it, register it:
  venv\\Scripts\\python.exe scripts/cortex_ingest.py --ingest <URL> --axis WATER_REVIEW \\
      --slot anchor_annual

  # override any part of the derivation (the human knows the payload better than the walker):
  ... --ingest <URL> --kind http_csv --column-name value --row-key World --unit pct

  # and, as a separate explicit act, put it in the spec:
  ... --promote
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "composers"))

from core import source_registration as SR   # noqa: E402  the real wall
import composer as C                          # noqa: E402  the real loader
import provenance as P                        # noqa: E402  origin + reporter class

DISCOVERED = REPO / "memory" / "discovered_data_sources.json"

PASSTHROUGH = ("extract", "col", "column_name", "row_key", "row_key_column",
               # addresses for the official-statistics readers. Leaving these out meant a
               # jsonstat `cell` was silently dropped, the walker then derived a json_path
               # rule for a jsonstat kind, and the entry died at the schema wall reporting
               # a missing address it had actually been given.
               "cell", "series_key", "where", "timeout",
               "data_date_col", "data_date_column", "data_date_extract",
               "data_max_age_days", "path", "unit", "origin",
               "reporter_class", "reporter_class_confirmed_by")

# An address the human (or a provider record) supplied. Present -> we do NOT guess.
DECLARED_ADDRESS = ("extract", "col", "column_name", "cell", "series_key")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def ingest(url, axis=None, slot=None, fmt=None, kind=None, org=None, metric=None,
           deterministic=False, overrides=None, register=True, promote=False) -> dict:
    """Fetch once, derive the rule, smoke-test through the real loader, register.

    Returns a verbatim trail. Every step reports what actually happened, including the
    raw exception — a human who proposed a source is owed the failure, not a summary of it.
    """
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    trail = {"ts": _now(), "url": url, "axis": axis, "slot": slot,
             "proposed_by": "human (scripts/cortex_ingest.py)", "steps": []}

    def step(name, ok, **kw):
        trail["steps"].append({"step": name, "ok": bool(ok), **kw})
        return ok

    # 1. FETCH ONCE. Same probe the registration path uses.
    fmt = (fmt or ("csv" if str(url).lower().split("?")[0].endswith(".csv") else "json"))
    payload, err = SR.probe(url, fmt)
    if err:
        step("probe", False, format=fmt, error=err)
        trail["result"] = "REFUSED: the URL could not be read"
        return trail
    step("probe", True, format=fmt,
         payload_type=type(payload).__name__,
         size=len(payload) if isinstance(payload, str) else len(json.dumps(payload)))

    # 2. DERIVE THE RULE from what came back — unless the human declared it, in which case
    #    the human wins. They can see the payload; the walker only guesses at it.
    if any(overrides.get(k) is not None for k in DECLARED_ADDRESS):
        rule = {k: overrides[k] for k in DECLARED_ADDRESS
                if overrides.get(k) is not None}
        kind = kind or ("http_csv" if fmt == "csv" else "http_json_path")
        step("derive", True, source="declared by the human", kind=kind, rule=rule)
    else:
        dkind, drule, why = SR.derive_rule(fmt, payload, metric or "")
        if not dkind:
            step("derive", False, reason=why)
            trail["result"] = ("REFUSED: no unambiguous parsing rule. Re-run naming it, "
                               "e.g. --extract a.b.c or --column-name <header>")
            return trail
        kind, rule = (kind or dkind), drule
        step("derive", True, source="derived from the fetched payload", kind=kind,
             rule=rule, why=why)

    entry = {"id": f"ingested_{abs(hash(url)) % 100000}", "kind": kind, "url": url,
             "org": org or "?", **rule}
    for k in PASSTHROUGH:
        if overrides.get(k) is not None:
            entry[k] = overrides[k]
    if deterministic:
        entry["deterministic"] = True

    # 3. THE SCHEMA WALL, both halves, exactly as a self-discovered candidate meets them.
    try:
        C.validate_entry(entry)
        C.validate_rule(entry)
        step("schema_wall", True, checked=["location", "parsing rule"])
    except C.PromotionRejected as e:
        step("schema_wall", False, error=str(e))
        trail["result"] = "REFUSED: incomplete record — not registered, not blacklisted"
        return trail

    # 4. THE SMOKE FETCH, through composer.fetch, the loader the composer itself uses.
    try:
        value, data_date = C.smoke_fetch(entry)
        step("smoke_fetch", True, value=value, data_date=data_date,
             schema=entry.get("schema"))
    except Exception as e:
        fclass, code = C.classify_failure(e)
        step("smoke_fetch", False, failure_class=fclass, reason_code=code,
             exception=f"{type(e).__name__}: {e}")
        trail["result"] = f"REFUSED: it does not fetch ({code})"
        return trail

    cls, why = P.reporter_class(entry)
    trail["origin"] = P.origin(entry)
    trail["reporter_class"] = {"class": cls, "why": why}
    trail["entry"] = entry

    # 5. REGISTER as a candidate. Not promoted — that stays a separate, explicit act.
    if register and axis:
        doc = _load(DISCOVERED, {})
        ax = doc.setdefault(axis, {"sources": []})
        rec = {"url": url, "format": fmt, "metric": metric or "", "org": org or "?",
               "kind": kind, **rule, "status": "active",
               "discovered_at": _now(), "rule_derived_at": _now(),
               "rule_derivation": "proposed by the human via cortex_ingest, rule "
                                  "derived or declared, smoke-fetched before registering",
               "proposed_by": "human", "smoke_value": value, "smoke_data_date": data_date}
        for k in PASSTHROUGH:
            if overrides.get(k) is not None:
                rec[k] = overrides[k]
        if slot:
            rec["slot_hint"] = slot
        if deterministic:
            rec["deterministic"] = True
            rec["schema"] = entry.get("schema")
        existing = [s for s in ax["sources"] if s.get("url") == url]
        if existing:
            existing[0].update(rec)
            step("register", True, note="already known — record updated in place")
        else:
            ax["sources"].append(rec)
            step("register", True, note=f"registered as a candidate under {axis}")
        DISCOVERED.parent.mkdir(parents=True, exist_ok=True)
        DISCOVERED.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    elif register:
        step("register", False, note="no --axis given, so nothing was registered; the "
                                     "smoke test above still stands")

    # 6. PROMOTION, only when asked for in words. Running this command is the human act.
    if promote:
        if not (axis and slot):
            step("promote", False, error="--promote needs --axis and --slot")
            trail["result"] = "SMOKE-TESTED and registered; promotion needs --axis + --slot"
            return trail
        res = C.promote(axis, url, slot, kind, org or "?",
                        **{k: entry[k] for k in PASSTHROUGH + ("deterministic", "schema")
                           if k in entry})
        step("promote", "error" not in res, result=res)
        trail["result"] = ("PROMOTED into the spec — review the git diff"
                           if "error" not in res else f"REFUSED at promote: {res.get('error')}")
        return trail

    trail["result"] = (f"VERIFIED and registered. It read {value} through the real loader. "
                       f"NOT promoted — that is Emil's call: "
                       f"composer.py --promote {axis} --slot {slot} ...")
    return trail


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="cortex_ingest",
        description="Propose a source the system never found. It gets the same walls.")
    p.add_argument("--ingest", metavar="URL", required=True)
    p.add_argument("--axis"); p.add_argument("--slot")
    p.add_argument("--format", choices=("json", "csv"))
    p.add_argument("--kind"); p.add_argument("--org"); p.add_argument("--metric")
    p.add_argument("--extract"); p.add_argument("--col", type=int)
    p.add_argument("--column-name", dest="column_name")
    p.add_argument("--row-key", dest="row_key")
    p.add_argument("--row-key-column", dest="row_key_column")
    p.add_argument("--data-date-column", dest="data_date_column")
    p.add_argument("--data-date-col", dest="data_date_col", type=int)
    p.add_argument("--data-max-age-days", dest="data_max_age_days", type=float)
    p.add_argument("--unit"); p.add_argument("--origin")
    p.add_argument("--reporter-class", dest="reporter_class")
    p.add_argument("--confirmed-by", dest="reporter_class_confirmed_by")
    p.add_argument("--deterministic", action="store_true")
    p.add_argument("--promote", action="store_true",
                   help="also write it into the spec (a separate, explicit act)")
    p.add_argument("--json", action="store_true", help="machine-readable trail")
    a = p.parse_args(argv)

    overrides = {k: getattr(a, k, None) for k in PASSTHROUGH}
    trail = ingest(a.ingest, axis=a.axis, slot=a.slot, fmt=a.format, kind=a.kind,
                   org=a.org, metric=a.metric, deterministic=a.deterministic,
                   overrides=overrides, promote=a.promote)

    if a.json:
        print(json.dumps(trail, ensure_ascii=False, indent=2))
    else:
        print("─" * 78)
        print(f"INGEST  {a.ingest}")
        print("─" * 78)
        for s in trail["steps"]:
            mark = "ok  " if s["ok"] else "FAIL"
            detail = {k: v for k, v in s.items() if k not in ("step", "ok")}
            print(f"  [{mark}] {s['step']:<12} {json.dumps(detail, ensure_ascii=False)[:200]}")
        if trail.get("reporter_class"):
            print(f"\n  origin          {trail['origin']}")
            print(f"  reporter class  {trail['reporter_class']['class']}")
            print(f"                  {trail['reporter_class']['why'][:150]}")
        print(f"\n  {trail['result']}")
    return 0 if not any(not s["ok"] for s in trail["steps"]) else 1


if __name__ == "__main__":
    sys.exit(main())
