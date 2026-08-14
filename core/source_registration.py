#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/source_registration.py — the REGISTRATION SCHEMA WALL.

WHAT WENT WRONG (live, 31 Jul - 3 Aug 2026)
-------------------------------------------
data_scout fetched a candidate URL, parsed its JSON to prove it contained numbers,
threw the parsed structure away, and registered a record holding only
{url, format, metric, org, slot_hint}. That record has no PARSING RULE, so it cannot
be fetched by any composer kind. It nonetheless became an approval item, reached
Emil's phone, and was tapped OK — three times for id 96b9, once for a027. Each tap
hit a deterministic refusal ("kind 'http_json_path' needs an 'extract' path"), and the
approval path then BLACKLISTED the source for it. Two good providers — Our World in
Data and the World Bank — were permanently barred over a field the system had failed
to compute for them, from a payload it had held in memory seconds earlier.

THE RULE THIS MODULE ENFORCES
-----------------------------
A candidate may not be REGISTERED unless it carries every field its kind needs to be
fetched. The rule is DERIVED at discovery time from the payload that was already
fetched to validate the URL — one fetch, no extra traffic. If no unambiguous rule can
be derived, the candidate is DROPPED with a named reason: it never enters
memory/discovered_data_sources.json and never reaches Telegram. No human approval is
ever spent on something already known to be unfetchable.

INCOMPLETE IS NOT BAD
---------------------
A candidate we could not derive a rule for is DISCARDED (logged, visible, re-proposable
by hand via scripts/cortex_ingest.py). It is never blacklisted. Blacklisting —
status "rejected" — is reserved for a source that FAILED A REAL FETCH: a dead URL, an
unparseable payload, or data whose own date is too old. See approve_reader._apply_promote.

NO AXIS-FIT FILTER. EVER.
-------------------------
Do not add a relevance / vocabulary / axis-fit test to this module or to data_scout.
It will look like an obvious improvement — "why register a health feed under a
governance axis?" — and it is exactly wrong. Cross-domain evidence is the point of this
system: child mortality is legitimate evidence about governance capacity, grid frequency
is evidence about infrastructure and about economy, refugee counts are evidence about
climate. A filter keyed on axis vocabulary would mechanically destroy precisely the
cross-domain feeds this system exists to combine, and would do it silently, in the name
of tidiness. The only gates here are MECHANICAL: can this be fetched, and can it be
parsed. What a number MEANS for an axis is a human's judgement at promotion time, and
the composer's afterwards. Not a keyword match.

  venv\\Scripts\\python.exe -m core.source_registration --unblacklist
  venv\\Scripts\\python.exe -m core.source_registration --unblacklist --offline
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

BASE       = Path(__file__).resolve().parents[1]
DISCOVERED = BASE / "memory" / "discovered_data_sources.json"
DISCARDED  = BASE / "memory" / "discarded_candidates.jsonl"

# What each composer kind needs in order to be FETCHED at all. `location` mirrors
# composer.KIND_LOCATION (where it reads from); `rule` is the parsing rule without which
# fetch() raises on every call. Both must be present before a candidate is registered.
KIND_RULES = {
    "file":             {"location": "path", "rule": "extract"},
    "http_json_path":   {"location": "url",  "rule": "extract"},
    "http_json_count":  {"location": "url",  "rule": "extract"},
    "http_json_series": {"location": "url",  "rule": "extract"},
    "http_csv":         {"location": "url",  "rule": "col"},
    "http_gdelt_tone":  {"location": "url",  "rule": None},   # fixed payload shape
}

_MAX_DEPTH = 6

# Function words only. It is tempting to also strip "count", "value", "total", "rate",
# "index" as too generic — do not: those are exactly the words a payload names its
# measurement with, and stripping them threw away the one real match in a USGS feed
# ("count of earthquakes" vs metadata.count) and fell back to a structural guess.
_STOPWORDS = {"the", "and", "for", "from", "with", "per", "that", "this", "these",
              "those", "its", "their", "into", "over", "under", "about", "are", "was",
              "has", "have", "not", "but", "all", "any", "one", "two", "out"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(cell):
    try:
        return float(str(cell).strip())
    except (TypeError, ValueError):
        return None


_DATEISH = re.compile(r"^\d{4}-\d{2}(-\d{2})?")


# ── payload scan: every addressable path, the way composer._dotted addresses it ───

def _scan(node, path: str = "", depth: int = 0, acc: dict | None = None) -> dict:
    """Collect the paths composer._dotted() can actually walk.

    scalars    [(path, value)]   numeric leaves            -> http_json_path
    num_lists  [(path, n)]       lists of numbers          -> http_json_series
    dict_lists [(path, n)]       lists of objects          -> http_json_count
    str_lists  [(path, n)]       lists of date-ish strings -> data_date_extract
    """
    if acc is None:
        acc = {"scalars": [], "num_lists": [], "dict_lists": [], "str_lists": []}
    if depth > _MAX_DEPTH:
        return acc
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            if _is_num(v):
                acc["scalars"].append((p, v))
            elif isinstance(v, list):
                _scan_list(v, p, depth, acc)
            elif isinstance(v, dict):
                _scan(v, p, depth + 1, acc)
    elif isinstance(node, list):
        _scan_list(node, path, depth, acc)
    return acc


def _scan_list(v: list, p: str, depth: int, acc: dict) -> None:
    nums = [x for x in v if _is_num(x)]
    if v and p:
        if nums and len(nums) * 2 >= len(v):          # mostly numeric -> a series
            acc["num_lists"].append((p, len(nums)))
        elif all(isinstance(x, dict) for x in v):     # objects -> countable events
            acc["dict_lists"].append((p, len(v)))
        elif all(isinstance(x, str) for x in v) and any(_DATEISH.match(x or "") for x in v):
            acc["str_lists"].append((p, len(v)))
    if depth < _MAX_DEPTH:
        # First three elements only. A heterogeneous root list (the World Bank answers
        # [meta, [rows...]]) is unreachable otherwise, and walking every element of a
        # 200-row payload buys nothing but time.
        for i, el in enumerate(v[:3]):
            if isinstance(el, (dict, list)):
                _scan(el, f"{p}.{i}" if p else str(i), depth + 1, acc)


def _tokens(text: str) -> set:
    # >= 3 so co2 / gdp / ppp survive as the identifying tokens they are
    return {w for w in re.split(r"[^a-z0-9]+", str(text or "").lower())
            if len(w) >= 3 and w not in _STOPWORDS}


def _best(cands: list, toks: set):
    """The single best token-matching path, or None if nothing matches or the top is TIED.

    A tie is refused rather than broken by iteration order: picking one of two equally
    good numbers is exactly the coin-flip that would later be reported as a measurement.
    """
    scored = []
    for path, _extra in cands:
        ptoks = _tokens(path.replace(".", " "))
        hits = len(toks & ptoks)
        if hits:
            scored.append((hits, -path.count("."), -len(path), path))
    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][:3] == scored[1][:3]:
        return None
    return scored[0][3]


def _strict_longest(cands: list):
    """The uniquely longest list, or None when two are tied for longest."""
    if not cands:
        return None
    ranked = sorted(cands, key=lambda pn: -pn[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def _sibling_dates(path: str, str_lists: list):
    """A date array beside the value array (open-meteo: daily.time next to daily.x) —
    it is what lets the composer refuse a stale reading later."""
    parent = path.rsplit(".", 1)[0] if "." in path else ""
    for p, _n in str_lists:
        if (p.rsplit(".", 1)[0] if "." in p else "") == parent and p != path:
            return p
    return None


# ── the derivation ───────────────────────────────────────────────────────────

# Final path segments that name an ERROR ENVELOPE, not a measurement. This is a
# MECHANICAL parse-validity gate, NOT an axis-fit filter (see module doctrine above):
# it asks "is this field a message about the request?", never "does this number
# belong to this axis?". Added 13 Aug 2026 after a World Bank HTTP-200 error payload
# ([{"message":[{...}]}]) was derived into extract="0.message" and reached the
# approval queue as a countable "measurement" of its own error text.
_ERRORISH_KEYS = {"message", "messages", "error", "errors", "fault", "faults",
                  "exception", "detail", "details", "warning", "warnings",
                  "status_message", "statusmessage"}


def _drop_errorish(cands: list) -> tuple:
    """Split candidate (path, extra) pairs into (kept, dropped_paths) by final key."""
    kept, dropped = [], []
    for path, extra in cands:
        final = path.rsplit(".", 1)[-1].lower()
        if final in _ERRORISH_KEYS:
            dropped.append(path)
        else:
            kept.append((path, extra))
    return kept, dropped


def derive_rule(fmt: str, payload, metric_hint: str = "") -> tuple:
    """(kind, rule_dict, reason). kind is None when no unambiguous rule exists.

    Deterministic and offline: it reads the payload data_scout ALREADY fetched. The
    preference order is stated rather than tuned — a named field beats a structural
    guess, and a tie is a refusal.
    """
    fmt = (fmt or "").lower()

    if fmt == "csv":
        text = payload if isinstance(payload, str) else ""
        rows = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        if not rows:
            return None, None, "csv: no data rows in the payload"
        cells = rows[-1].replace("\t", ",").replace(";", ",").split(",")
        numeric = [i for i, c in enumerate(cells) if _num(c) is not None]
        if not numeric:
            return None, None, (f"csv: last row has no numeric column "
                                f"({len(cells)} cell(s)) — no col rule derivable")
        rule = {"col": numeric[-1]}
        # the composer's own default is col=-1 and CSV series conventionally end with the
        # value; taking the LAST numeric column reproduces that convention explicitly
        # instead of leaving it implicit in a default.
        for i, c in enumerate(cells):
            if i not in numeric and _DATEISH.match(str(c).strip()):
                rule["data_date_col"] = i
                break
        return "http_csv", rule, f"csv: last numeric column is {numeric[-1]} of {len(cells)}"

    if not isinstance(payload, (dict, list)):
        return None, None, f"json: payload is {type(payload).__name__}, not an object or array"

    acc = _scan(payload)

    # error-envelope gate: fields whose NAME says "message/error" are not measurements.
    dropped_all = []
    for bucket in ("scalars", "num_lists", "dict_lists"):
        acc[bucket], dropped = _drop_errorish(acc[bucket])
        dropped_all.extend(dropped)
    if dropped_all and not (acc["scalars"] or acc["num_lists"] or acc["dict_lists"]):
        return None, None, (
            f"json: payload is an error envelope — every addressable field is error-ish "
            f"({', '.join(dropped_all[:4])}); an HTTP 200 with only a message is a refusal, "
            f"not a measurement")

    toks = _tokens(metric_hint)

    hit = _best(acc["scalars"], toks)
    if hit:
        return "http_json_path", {"extract": hit}, f"json: field name matches the metric ({hit})"

    hit = _best(acc["num_lists"], toks)
    if hit:
        rule = {"extract": hit}
        dates = _sibling_dates(hit, acc["str_lists"])
        if dates:
            rule["data_date_extract"] = dates
        return "http_json_series", rule, f"json: series name matches the metric ({hit})"

    hit = _best(acc["dict_lists"], toks)
    if hit:
        return "http_json_count", {"extract": hit}, f"json: event array matches the metric ({hit})"

    if len(acc["scalars"]) == 1:
        p = acc["scalars"][0][0]
        return "http_json_path", {"extract": p}, f"json: the payload's only numeric field ({p})"

    hit = _strict_longest(acc["num_lists"])
    if hit:
        rule = {"extract": hit}
        dates = _sibling_dates(hit, acc["str_lists"])
        if dates:
            rule["data_date_extract"] = dates
        return "http_json_series", rule, f"json: the payload's longest numeric series ({hit})"

    hit = _strict_longest(acc["dict_lists"])
    if hit:
        return "http_json_count", {"extract": hit}, f"json: the payload's longest event array ({hit})"

    return None, None, (
        f"json: no unambiguous parsing rule — {len(acc['scalars'])} numeric field(s), "
        f"{len(acc['num_lists'])} series, {len(acc['dict_lists'])} event array(s), and the "
        f"metric text {metric_hint[:60]!r} matched none of them uniquely")


def missing_fields(entry: dict) -> list:
    """Which fields this entry's kind needs and does not have."""
    spec = KIND_RULES.get(entry.get("kind"))
    if spec is None:
        return [f"<unknown kind {entry.get('kind')!r}>"]
    out = []
    for field in (spec["location"], spec["rule"]):
        if field and not str(entry.get(field) or "").strip():
            if field == "col" and _is_num(entry.get("col")):
                continue                      # col 0 is a real column
            out.append(field)
    return out


# ── the wall ─────────────────────────────────────────────────────────────────

def build_candidate(url: str, fmt: str, payload, metric: str = "", org: str = "",
                    slot_hint: str = "", axis: str = "") -> tuple:
    """(record, reason). record is None when the candidate may NOT be registered.

    This is the wall. Everything past it is fetchable by construction.
    """
    kind, rule, reason = derive_rule(fmt, payload, metric)
    if not kind:
        return None, reason
    rec = {
        "url": url, "format": fmt, "metric": metric, "org": org,
        "kind": kind, **rule,
        "discovered_at": _now(),
        "status": "active",
        "rule_derived_at": _now(),
        "rule_derivation": reason,
    }
    if slot_hint:
        rec["slot_hint"] = slot_hint
    gaps = missing_fields(rec)
    if gaps:                                  # belt and braces: the wall checks itself
        return None, f"derived rule is still incomplete, missing {gaps}"
    return rec, reason


def discard(axis: str, url: str, reason: str, stage: str = "registration",
            fmt: str = "", slot_hint: str = "") -> None:
    """Record a candidate that was DROPPED, not blacklisted. Fail-open: bookkeeping
    must never break discovery. Read back by cortex_query --rejected."""
    try:
        DISCARDED.parent.mkdir(parents=True, exist_ok=True)
        with open(DISCARDED, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": _now(), "axis": axis, "url": url, "format": fmt,
                "slot_hint": slot_hint, "stage": stage, "reason": str(reason)[:300],
                "blacklisted": False,
                "note": "dropped for want of a parsing rule — never fetched, never barred; "
                        "propose it by hand with scripts/cortex_ingest.py",
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── probe (the one fetch) ────────────────────────────────────────────────────

def probe(url: str, fmt: str = "json", timeout: int = 15) -> tuple:
    """(payload, error). JSON is parsed, CSV is returned as text. Used by the
    un-blacklist migration and by scripts/cortex_ingest.py; data_scout already holds
    the payload from its own validation fetch and passes it straight in."""
    try:
        import requests
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "CORTEX-registration/1.0"})
        r.raise_for_status()
        if (fmt or "json").lower() == "csv":
            return r.text, None
        return r.json(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:200]


# ── A4: the un-blacklist migration ───────────────────────────────────────────

# The signature of the refusal that blacklisted sources it had never fetched.
_NO_RULE_MARKERS = ("no parsing rule", "registered without one")


def _was_barred_for_want_of_a_rule(src: dict) -> bool:
    why = str(src.get("rejected_why") or "").lower()
    return src.get("status") == "rejected" and any(m in why for m in _NO_RULE_MARKERS)


def unblacklist_incomplete(store_path: Path = None, complete: bool = True) -> dict:
    """Clear the blacklist from every candidate barred under the no-parsing-rule error.

    They were never fetched, so they were never tested. Idempotent: a second run finds
    nothing to restore, because the marker fields are gone.

    complete=True then does what registration should have done in the first place —
    one fetch, derive the rule, write it on. A candidate whose rule still cannot be
    derived becomes status 'incomplete' (visible, re-proposable) and NOT 'rejected'.
    """
    path = Path(store_path or DISCOVERED)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"cannot read {path}: {type(e).__name__}: {e}", "restored": []}

    restored, completed, still_incomplete = [], [], []
    for axis, entry in doc.items():
        if not isinstance(entry, dict):
            continue
        for src in entry.get("sources", []):
            if not _was_barred_for_want_of_a_rule(src):
                continue
            src["status"] = "active"
            src["unblacklisted_at"] = _now()
            src["unblacklist_reason"] = (
                "barred under the no-parsing-rule refusal, which never fetched it — "
                "the missing field was ours, not the source's")
            src.pop("rejected_why", None)
            src.pop("rejected_at", None)
            src.pop("rejected_class", None)
            restored.append({"axis": axis, "org": src.get("org"), "url": src.get("url")})

            if not complete:
                continue
            payload, err = probe(src.get("url", ""), src.get("format", "json"))
            if err:
                # a failed probe here is OUR network, not a verdict on the source
                src["rule_derivation"] = f"probe deferred ({err})"
                continue
            kind, rule, reason = derive_rule(src.get("format", "json"), payload,
                                             src.get("metric", ""))
            if kind:
                src["kind"] = kind
                src.update(rule)
                src["rule_derived_at"] = _now()
                src["rule_derivation"] = reason
                completed.append({"axis": axis, "url": src.get("url"),
                                  "kind": kind, "rule": rule})
            else:
                src["status"] = "incomplete"
                src["incomplete_why"] = reason
                still_incomplete.append({"axis": axis, "url": src.get("url"),
                                         "reason": reason})
                discard(axis, src.get("url", ""), reason, stage="unblacklist_completion",
                        fmt=src.get("format", ""), slot_hint=src.get("slot_hint", ""))

    if restored:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"restored": restored, "completed": completed,
            "still_incomplete": still_incomplete, "store": str(path)}


if __name__ == "__main__":
    import sys
    if "--unblacklist" in sys.argv:
        res = unblacklist_incomplete(complete="--offline" not in sys.argv)
        print(f"un-blacklist: {len(res.get('restored', []))} candidate(s) restored")
        for r in res.get("restored", []):
            print(f"  RESTORED  {r['axis']:<36} {r.get('org') or '?':<26} {str(r['url'])[:70]}")
        for c in res.get("completed", []):
            print(f"  COMPLETED {c['axis']:<36} kind={c['kind']} rule={c['rule']}")
        for i in res.get("still_incomplete", []):
            print(f"  INCOMPLETE (dropped, NOT blacklisted) {str(i['url'])[:70]}")
            print(f"             {i['reason']}")
        if not res.get("restored"):
            print("  nothing to restore — no candidate carries the no-parsing-rule marker")
        if res.get("error"):
            print(f"  ERROR {res['error']}")
    else:
        print(__doc__)
