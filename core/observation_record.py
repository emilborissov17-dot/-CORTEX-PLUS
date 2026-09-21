#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/observation_record.py — a panel yields N records, one per (entity, period), or none.

WHAT WENT WRONG (20 September 2026)
------------------------------------
The OpenClaw wire produced this, and the gate accepted it:

    axis  COGNITION_LEARNING_REVIEW
    key   "Youth literacy rate (ages 15-24) %"
    value 83.3899993896484
    unit  "unknown"
    quote a raw JSON slice
    data_date null

Measured against the real body on 21 Sep, that number is **AFE / 2024** —
"Africa Eastern and Southern", one aggregate region, one year, out of a page of
60 rows and a panel of 17,490. It was written onto a global axis as a bare
number with no country and no year.

The worker was obeying its spec. The spec asked for "a quote and two dates", so
a panel collapsed into one nameless cell, and `unit: "unknown"` passed every
check that only tests presence. A placeholder is worse than absence: absence is
visible.

THE THREE TIMESTAMPS, AND WHY NONE SUBSTITUTES FOR ANOTHER
-----------------------------------------------------------
  period        a property of the DATUM   — what the value refers to
  published_at  a property of the SOURCE  — when it says it last updated
  retrieved_at  a property of US          — when we fetched

Today we can read a value that refers to 1990. The fetch date says nothing about
the reading, and the old card carried only the fetch date.

WHAT THE SOURCE MUST DECLARE, and what is refused without it
-------------------------------------------------------------
No path is ever guessed. A declaration that cannot name where the entity and the
period live produces ZERO records and one REFUSED entry naming the source and
the reason. Zero is a correct answer; one nameless number is not.

AGGREGATES ARE ALLOWED ONLY WHERE THE SOURCE DECLARES THEM, and the World Bank
does: /v2/country marks every aggregate with region.id == "NA" — 78 of its 295
entries, AFE among them, BGR not. That list is fetched and declared, never
inferred from the shape of a code. Without it, a code that cannot be confirmed
as either is emitted UNVERIFIED with the reason, not promoted to a country.

    venv/Scripts/python.exe -m core.observation_record --selftest
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

# THE ONLY SPELLINGS WRITTEN. Registered in config/field_names.json so
# tools/ask.py can answer for them; test_the_record_names_are_registered fails
# if the two lists drift apart.
RECORD_FIELDS = ("entity", "period", "period_granularity", "value", "unit",
                 "span", "url", "selector_path", "published_at", "retrieved_at")

# published_at is the one field a source may honestly not have.
REQUIRED_FIELDS = tuple(f for f in RECORD_FIELDS if f != "published_at")

GRANULARITIES = ("year", "month", "day", "instant")

# What a declaration must name before a single record may be emitted.
DECLARATION_REQUIRED = ("rows_path", "entity_path", "period_path",
                        "period_granularity", "value_path")


class Undeclared(ValueError):
    """The source cannot say where entity or period live. Zero records."""


def _walk(node, path: str):
    """Dotted path over dicts and list indices. Returns None if it does not
    resolve — a path that misses is a missing field, never an exception that
    takes the whole page down."""
    if path in ("", None):
        return node
    for seg in str(path).split("."):
        if isinstance(node, dict):
            if seg not in node:
                return None
            node = node[seg]
        elif isinstance(node, (list, tuple)):
            if not seg.lstrip("-").isdigit():
                return None
            i = int(seg)
            if not -len(node) <= i < len(node):
                return None
            node = node[i]
        else:
            return None
    return node


def _balanced_object(raw: str, at: int) -> tuple:
    """(start, end) of the smallest {...} in `raw` that contains offset `at`.

    A VERBATIM SLICE, cut from the bytes the server sent. It is never rebuilt
    from the parsed object: a span assembled from what we already parsed would
    match the page every time and the gate would be checking that a string is a
    string.
    """
    start = raw.rfind("{", 0, at + 1)
    while start != -1:
        depth, i, in_str, esc = 0, start, False, False
        while i < len(raw):
            c = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    if start <= at <= i:
                        return start, i + 1
                    break
            i += 1
        start = raw.rfind("{", 0, start)
    return -1, -1


def _value_spellings(value) -> list:
    """How the body may have written this number, longest first. Used only to
    LOCATE the span; the span itself is cut from the raw text."""
    out = []
    try:
        f = float(value)
    except (TypeError, ValueError):
        return [str(value)]
    if f.is_integer():
        out.append(str(int(f)))
    out.append(repr(f))
    out.append(str(value))
    seen, uniq = set(), []
    for c in sorted(out, key=len, reverse=True):
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def span_for(raw: str, value, entity: str, period: str) -> str | None:
    """The verbatim object in `raw` that carries this value AND names this
    entity and period. None when no such object exists.

    THE TIE IS MADE HERE, not asserted later: a span that does not contain the
    entity and the period alongside the value is not evidence for THIS cell, and
    the gate refuses it.
    """
    if not raw:
        return None
    for cand in _value_spellings(value):
        i = raw.find(cand)
        while i != -1:
            start, end = _balanced_object(raw, i)
            if start != -1:
                obj = raw[start:end]
                if str(entity) in obj and str(period) in obj:
                    return obj
            i = raw.find(cand, i + 1)
    return None


def aggregates_from_country_list(body_text: str) -> set:
    """The codes the World Bank ITSELF marks as aggregates: region.id == "NA".

    Declared, not inferred. Handed to extract() by the caller; without it no
    code can be confirmed and every record says so.
    """
    try:
        doc = json.loads(body_text)
    except Exception:                                             # noqa: BLE001
        return set()
    rows = doc[1] if isinstance(doc, list) and len(doc) > 1 else doc
    out = set()
    for c in rows or []:
        if isinstance(c, dict) and (c.get("region") or {}).get("id") == "NA":
            code = str(c.get("id") or "").strip()
            if code:
                out.add(code)
    return out


def countries_from_country_list(body_text: str) -> set:
    """Every code the same list declares, aggregate or not."""
    try:
        doc = json.loads(body_text)
    except Exception:                                             # noqa: BLE001
        return set()
    rows = doc[1] if isinstance(doc, list) and len(doc) > 1 else doc
    return {str(c.get("id") or "").strip() for c in (rows or [])
            if isinstance(c, dict) and str(c.get("id") or "").strip()}


def extract(declaration: dict, body_text: str, retrieved_at: str | None = None,
            declared_codes: set | None = None,
            aggregates: set | None = None) -> tuple:
    """(records, refusals) — THE ONE DOOR.

    No other code path may construct a record. Every field comes from the
    declaration applied to the body; nothing is defaulted and nothing is
    inferred. A record that cannot fill a required field is emitted with
    verified=False and a reason NAMING that field, never with a placeholder.
    """
    sid = str(declaration.get("id") or "<unnamed>")
    retrieved_at = retrieved_at or datetime.now(timezone.utc).isoformat()

    missing = [k for k in DECLARATION_REQUIRED if not declaration.get(k)]
    if missing:
        return [], [{"source_id": sid, "status": "REFUSED",
                     "reason": "the source declares no {}; a value with no "
                               "entity or period is a nameless number"
                               .format(", ".join(missing)),
                     "url": declaration.get("url")}]
    gran = str(declaration.get("period_granularity"))
    if gran not in GRANULARITIES:
        return [], [{"source_id": sid, "status": "REFUSED",
                     "reason": f"period_granularity {gran!r} is not one of "
                               f"{GRANULARITIES}",
                     "url": declaration.get("url")}]
    try:
        body = json.loads(body_text)
    except Exception as exc:                                      # noqa: BLE001
        return [], [{"source_id": sid, "status": "REFUSED",
                     "reason": f"body is not JSON: {type(exc).__name__}",
                     "url": declaration.get("url")}]

    rows = _walk(body, declaration["rows_path"])
    if not isinstance(rows, list):
        return [], [{"source_id": sid, "status": "REFUSED",
                     "reason": "rows_path {!r} did not resolve to a list"
                               .format(declaration["rows_path"]),
                     "url": declaration.get("url")}]

    published_at = None
    if declaration.get("published_at_path"):
        got = _walk(body, declaration["published_at_path"])
        published_at = str(got) if isinstance(got, str) and got.strip() else None

    unit_pattern = declaration.get("unit_pattern")
    records = []
    for i, row in enumerate(rows):
        value = _walk(row, declaration["value_path"])
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue                      # an empty cell is not an observation
        entity = _walk(row, declaration["entity_path"])
        period = _walk(row, declaration["period_path"])
        unit = _walk(row, declaration["unit_path"]) if declaration.get("unit_path") else None
        if unit_pattern and isinstance(unit, str):
            m = re.search(unit_pattern, unit)
            unit = m.group(1) if m else None
        selector = "{}.{}.{}".format(declaration["rows_path"], i,
                                     declaration["value_path"])
        span = span_for(body_text, value, entity, period)

        rec = {"entity": str(entity).strip() if isinstance(entity, str) and entity.strip() else None,
               "period": str(period).strip() if period not in (None, "") else None,
               "period_granularity": gran,
               "value": float(value),
               "unit": unit.strip() if isinstance(unit, str) and unit.strip() else None,
               "span": span,
               "url": declaration.get("url"),
               "selector_path": selector,
               "retrieved_at": retrieved_at}
        if published_at:
            rec["published_at"] = published_at

        why = [f for f in REQUIRED_FIELDS if rec.get(f) in (None, "")]
        if rec["entity"] and declared_codes is not None:
            if rec["entity"] not in declared_codes:
                why.append("entity:not-in-the-source's-own-code-list")
            elif aggregates is not None and rec["entity"] in aggregates:
                # ALLOWED, because the source itself declares it an aggregate —
                # which is exactly the condition the record shape puts on it.
                rec["entity_is_aggregate"] = True
        elif rec["entity"]:
            why.append("entity:the source declares no way to tell a country "
                       "from an aggregate")
        rec["verified"] = not why
        if why:
            rec["unverified_reason"] = "; ".join(why)
        records.append(rec)

    return records, []


# ── SELFTEST ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    import pathlib
    base = pathlib.Path(__file__).resolve().parents[1]
    rep = {"record_fields": list(RECORD_FIELDS), "integrations": {}}
    reg = base / "config" / "field_names.json"
    try:
        doc = json.loads(reg.read_text(encoding="utf-8"))
        known = {e["spelling"] for e in
                 doc.get("concepts", {}).get("OBSERVATION_RECORD", {})
                 .get("spellings", [])}
        missing = [f for f in RECORD_FIELDS if f not in known]
        rep["integrations"]["config/field_names.json"] = (
            "LIVE - every field registered" if not missing else
            f"INERT - unregistered: {missing}")
    except Exception as exc:                                      # noqa: BLE001
        rep["integrations"]["config/field_names.json"] = f"INERT - {exc}"
    try:
        gate = (base / "core" / "quote_gate.py").read_text(encoding="utf-8")
        rep["integrations"]["core.quote_gate"] = (
            "LIVE - judge_record exists" if "def judge_record" in gate else
            "INERT - the gate cannot judge a record")
    except Exception as exc:                                      # noqa: BLE001
        rep["integrations"]["core.quote_gate"] = f"INERT - {exc}"
    return rep


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), ensure_ascii=False, indent=2))
