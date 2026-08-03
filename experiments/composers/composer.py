#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/composers/composer.py — per-axis indicator composer.

WHAT THIS IS (plain, no inflation): a small engine that stitches one axis
indicator from a PORTFOLIO of sources — a slow official anchor plus daily-moving
proxies — and reports: composed values, agreement (do proxies confirm or
contradict the anchor's direction), confidence, and NEEDS (what the portfolio
is missing). It is plumbing between raw data and analysis. It is not a mind.

DIVERSIFICATION BY RULE, NOT BY LIST
------------------------------------
config/composer_specs.json declares SLOTS by source CLASS
(anchor_annual / measurement_daily / event_daily / indirect_proxy) with minimum
counts. Sources fill slots. Self-discovered sources (data_scout) appear as
candidates; a human promotes one with --promote, which EDITS THE SPEC (a
reviewable git diff), supplying the parsing rule. An unfilled slot is never
silent: it lowers confidence and emits a NEED record the human sees.
Diversity is counted as distinct organisations across filled slots.

FALLBACK RULES (graded degradation, never silent staleness)
-----------------------------------------------------------
- reserves inside a slot: priority order; first live-and-fresh source is used
- cache TTL: a source fetched OK within TTL_H is not re-fetched (rate-limit discipline)
- backoff: a source that just failed is not hammered again within BACKOFF_H
- last-known-good with LOUD ageing: every value carries its age; past
  freshness_days it is EXCLUDED and a stale NEED is emitted
- data-date check: a source may declare where its own measurement date lives
  (data_date_extract); data older than data_max_age_days is refused even if
  the file itself was read a second ago — a reserve may not serve old data as fresh
- death: DEATH_AT consecutive failures -> source dead + NEED for a replacement
- fail-loud: an empty slot produces NO fabricated number — only lower confidence
  and a NEED record

Outputs (runtime files, not committed):
  memory/composer_state/<AXIS>.json   per-source state incl. value history
  memory/composer_needs.json          the NEED queue (what the organism lacks)
  memory/composed_indicators.json     last composed report per axis

Usage:
  python experiments/composers/composer.py --run CLIMATE_GLOBAL_RISK_REVIEW [--force]
  python experiments/composers/composer.py --needs
  python experiments/composers/composer.py --promote AXIS --url U --slot S \
      --kind http_csv --col 3 --org ORG      # human-gated: writes the spec
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

SPEC_FILE  = REPO / "config" / "composer_specs.json"
STATE_DIR  = REPO / "memory" / "composer_state"
NEEDS_FILE = REPO / "memory" / "composer_needs.json"
OUT_FILE   = REPO / "memory" / "composed_indicators.json"
DISCOVERED = REPO / "memory" / "discovered_data_sources.json"

TTL_H       = 20   # fetched-OK within this window -> reuse, no re-fetch
BACKOFF_H   = 1    # failed within this window -> do not hammer again
DEATH_AT    = 3    # consecutive HARD failures -> dead + NEED
THROTTLE_H  = 0.25 # rate-limited within this window -> wait; NEVER counts toward death


class RateLimited(RuntimeError):
    """A 429 / provider throttle. Transient, NOT a dead source — the source is fine,
    we just asked too often. Must back off WITHOUT counting toward DEATH_AT, or a
    daily feed like GDELT (limit: 1 req / 5s) gets wrongly killed and the moving
    signal on the DYNAMIC axes disappears. (Diagnosed live 30 Jul 2026: GDELT returns
    either HTTP 429 or a 200 body 'Please limit requests to one every 5 seconds'.)"""


def _now():
    return datetime.now(timezone.utc)


def _iso(dt=None):
    return (dt or _now()).isoformat()


def _age_h(iso_str):
    try:
        return (_now() - datetime.fromisoformat(iso_str)).total_seconds() / 3600.0
    except Exception:
        return None


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _dotted(d, path):
    """Walk a dotted path. An integer part indexes a LIST ('daily.time.-1'), so the
    array-shaped APIs that most open feeds return (open-meteo, EONET, USGS) are reachable
    without a bespoke parser per provider. Dict-only paths behave exactly as before."""
    cur = d
    for part in str(path).split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _http(url, timeout=15):
    """Fetch text. Prefers `requests` — the library the nightly cycle already uses
    SUCCESSFULLY against these same domains (NOAA/GDELT/WB). On this Windows box
    urllib hits a proxy tunnel 403 for some domains while requests gets through
    (diagnosed 30 Jul 2026 from composer_state last_error). urllib is the fallback."""
    try:
        import requests
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "CORTEX-composer/1.0"})
        if r.status_code == 429:
            raise RateLimited("HTTP 429")
        r.raise_for_status()
        # some providers (GDELT) answer 200 with a plaintext throttle notice instead
        low = r.text[:200].lower()
        if "please limit requests" in low or "rate limit" in low:
            raise RateLimited("provider throttle notice")
        return r.text
    except ImportError:
        req = urllib.request.Request(url, headers={"User-Agent": "CORTEX-composer/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")


# ── fetch kinds ───────────────────────────────────────────────────────────────

def fetch(src) -> tuple:
    """Returns (value: float, data_date: str|None). Raises on any failure."""
    kind = src.get("kind")
    data_date = None
    if kind == "file":
        data = json.loads((REPO / src["path"]).read_text(encoding="utf-8"))
        v = _dotted(data, src["extract"])
        if src.get("data_date_extract"):
            data_date = _dotted(data, src["data_date_extract"])
        return float(v), data_date
    if kind == "http_json_path":
        data = json.loads(_http(src["url"]))
        return float(_dotted(data, src["extract"])), None
    if kind == "http_csv":
        text = _http(src["url"])
        rows = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        # TAB is a first-class delimiter: USGS NWIS serves its daily-values feed as RDB
        # (tab-separated), and without this every USGS row parses as a single cell.
        cells = rows[-1].replace("\t", ",").replace(";", ",").split(",")
        if src.get("data_date_col") is not None:
            data_date = cells[int(src["data_date_col"])].strip()
        return float(cells[int(src.get("col", -1))]), data_date
    if kind == "http_json_count":
        # The measurement IS the number of dated events (EONET categories, USGS feeds).
        data = json.loads(_http(src["url"]))
        arr = _dotted(data, src["extract"])
        if not isinstance(arr, list):
            raise ValueError(f"json_count: '{src['extract']}' is not a list")
        return float(len(arr)), None
    if kind == "http_json_series":
        # Daily series APIs answer with parallel arrays {"daily":{"time":[...],"x":[...]}}.
        # Take the last NON-NULL value — forecast arrays carry trailing nulls for variables
        # the model does not supply, and a null tail must not read as a missing source.
        data = json.loads(_http(src["url"]))
        arr = _dotted(data, src["extract"])
        if not isinstance(arr, list):
            raise ValueError(f"json_series: '{src['extract']}' is not a list")
        idx = next((i for i in range(len(arr) - 1, -1, -1) if arr[i] is not None), None)
        if idx is None:
            raise ValueError("json_series: every value in the series is null")
        if src.get("data_date_extract"):
            dates = _dotted(data, src["data_date_extract"])
            if isinstance(dates, list) and idx < len(dates):
                data_date = dates[idx]   # the date OF the value used, not of the request
        return float(arr[idx]), data_date
    if kind == "http_gdelt_tone":
        data = json.loads(_http(src["url"]))
        series = (data.get("timeline") or [{}])[0].get("data") or []
        vals = [float(p["value"]) for p in series[-7:] if "value" in p]
        if not vals:
            raise ValueError("gdelt: empty tone series")
        return round(sum(vals) / len(vals), 4), None
    raise ValueError(f"unknown source kind: {kind}")


def _data_too_old(data_date: str, max_days: float):
    """True if the source's OWN measurement date is older than max_days."""
    if not data_date:
        return False, None
    try:
        d = datetime.fromisoformat(str(data_date)[:10]).replace(tzinfo=timezone.utc)
        age_d = (_now() - d).total_seconds() / 86400.0
        return age_d > max_days, round(age_d, 1)
    except Exception:
        return False, None


# ── compose one axis ──────────────────────────────────────────────────────────

def compose(axis: str, force: bool = False) -> dict:
    spec = _load(SPEC_FILE, {}).get(axis)
    if not spec:
        return {"error": f"no composer spec for {axis}"}

    state_file = STATE_DIR / f"{axis}.json"
    state = _load(state_file, {"sources": {}})
    S = state["sources"]
    needs, slots_report = [], {}
    filled_orgs = set()
    freshness_factors = []

    for slot_name, slot in spec["portfolio"].items():
        fresh_days = float(slot.get("freshness_days", 30))
        live = []
        for src in slot["sources"]:
            sid = src["id"]
            st = S.setdefault(sid, {"consecutive_fails": 0, "status": "active", "history": []})
            if st.get("status") == "dead":
                continue
            ok_age = _age_h(st["last_ok_ts"]) if st.get("last_ok_ts") else None
            att_age = _age_h(st["last_attempt_ts"]) if st.get("last_attempt_ts") else None
            use_cache = (not force) and ok_age is not None and ok_age < TTL_H
            in_backoff = (not force) and att_age is not None and att_age < BACKOFF_H \
                and st["consecutive_fails"] > 0
            in_throttle = (not force) and att_age is not None and att_age < THROTTLE_H \
                and st.get("throttled")
            attempted = False
            if not use_cache and not in_backoff and not in_throttle:
                attempted = True
                st["last_attempt_ts"] = _iso()
                try:
                    v, data_date = fetch(src)
                    too_old, dd_age = _data_too_old(data_date, float(src.get("data_max_age_days", 3650)))
                    if too_old:
                        # the source ANSWERED but its own data is outdated —
                        # refuse it as fresh; do not poison last-known-good
                        st["consecutive_fails"] = 0
                        st["last_error"] = f"data_date {data_date} is {dd_age}d old — refused as current"
                        needs.append({"slot": slot_name, "kind": "stale_value",
                                      "detail": f"{sid}: own data date {data_date} ({dd_age}d old) — refused"})
                        continue
                    st["last_value"] = v
                    st["last_ok_ts"] = _iso()
                    st["consecutive_fails"] = 0
                    st.pop("throttled", None)
                    st.pop("last_error", None)
                    st["history"] = (st.get("history") or [])[-29:] + [[_iso(), v]]
                except RateLimited as e:
                    # transient throttle: wait, keep the source ALIVE, never kill it
                    st["throttled"] = True
                    st["last_error"] = f"rate-limited ({e}) — backing off {THROTTLE_H}h"
                except Exception as e:
                    st["throttled"] = False
                    st["consecutive_fails"] += 1
                    st["last_error"] = f"{type(e).__name__}: {e}"[:140]
                    if st["consecutive_fails"] >= DEATH_AT:
                        st["status"] = "dead"
                        needs.append({"slot": slot_name, "kind": "source_dead",
                                      "detail": f"{sid} dead after {DEATH_AT} consecutive failures "
                                                f"({st['last_error']}) — slot needs a replacement"})
            # usability from last-known-good, with loud ageing
            if st.get("last_ok_ts") and st.get("status") != "dead":
                age_d = (_age_h(st["last_ok_ts"]) or 0.0) / 24.0
                if age_d <= fresh_days:
                    live.append({"id": sid, "org": src.get("org", "?"),
                                 "value": st.get("last_value"), "unit": src.get("unit"),
                                 "age_days": round(age_d, 3), "cached": not attempted})
                else:
                    needs.append({"slot": slot_name, "kind": "stale_value",
                                  "detail": f"{sid} last good value is {age_d:.1f}d old "
                                            f"(> {fresh_days}d) — excluded"})
        ok = len(live) >= int(slot.get("min", 1))
        if ok:
            for l in live:
                filled_orgs.add(l["org"])
            freshness_factors.append(max(0.0, 1.0 - live[0]["age_days"] / fresh_days))
        else:
            needs.append({"slot": slot_name, "kind": "slot_unfilled",
                          "detail": f"needs >= {slot.get('min', 1)} live source(s) of class "
                                    f"'{slot_name}', has {len(live)}"})
        slots_report[slot_name] = {"filled": ok, "live": live}

    n_slots = len(spec["portfolio"])
    n_filled = sum(1 for s in slots_report.values() if s["filled"])
    coverage = n_filled / n_slots if n_slots else 0.0
    diversity = min(1.0, len(filled_orgs) / n_slots) if n_slots else 0.0
    freshness = (sum(freshness_factors) / len(freshness_factors)) if freshness_factors else 0.0
    confidence = round(0.4 * coverage + 0.3 * diversity + 0.3 * freshness, 3)

    # ── composed values (no invented blended unit — anchor unit is kept) ──────
    def _slot_primary(name):
        rep = slots_report.get(name, {})
        return (rep.get("live") or [None])[0]

    anchor = _slot_primary(spec.get("anchor_slot", "anchor_annual"))
    daily = _slot_primary(spec.get("measure_slot", "measurement_daily"))
    # divergence is anchor-vs-daily on the SAME quantity. Subtracting a river's discharge
    # from a percentage, or a bond yield from GDP growth, produces a number that means
    # nothing and then flows into the hash-chained grounding ledger as if it did. So the
    # two sources must declare the same `unit` tag; anything else yields None plus a named
    # reason. FAIL-CLOSED: an undeclared unit is treated as not comparable, never assumed.
    divergence, divergence_note = None, None
    if anchor and daily and isinstance(anchor.get("value"), (int, float)) \
            and isinstance(daily.get("value"), (int, float)):
        au, du = anchor.get("unit"), daily.get("unit")
        if au and du and au == du:
            divergence = round(daily["value"] - anchor["value"], 4)
        else:
            divergence_note = (f"not comparable: anchor unit {au or 'undeclared'} vs daily unit "
                               f"{du or 'undeclared'} — subtraction would be a category error")

    # ── agreement: does each proxy's short-term direction match the anchor's? ──
    anchor_dir = None
    ac = spec.get("anchor_change")
    if ac:
        try:
            v, _ = fetch(ac)
            anchor_dir = "rising" if v > 0 else ("falling" if v < 0 else "flat")
        except Exception:
            anchor_dir = None
    agreement = {"anchor_direction": anchor_dir, "proxies": {}}
    for slot_name, rep in slots_report.items():
        if slot_name == spec.get("anchor_slot"):
            continue
        for l in rep["live"]:
            hist = (S.get(l["id"], {}).get("history") or [])
            if len(hist) >= 2:
                delta = hist[-1][1] - hist[-2][1]
                d = "rising" if delta > 1e-9 else ("falling" if delta < -1e-9 else "flat")
                agreement["proxies"][l["id"]] = {
                    "direction": d, "delta": round(delta, 4),
                    "matches_anchor": (d == anchor_dir) if anchor_dir and d != "flat" else None}
            else:
                agreement["proxies"][l["id"]] = {"direction": "unknown", "note": "needs >=2 observations"}

    # ── candidates the system found itself, awaiting human promotion ──────────
    disc = _load(DISCOVERED, {}).get(axis, {})
    spec_urls = {s.get("url") for sl in spec["portfolio"].values() for s in sl["sources"]}
    candidates = [s for s in disc.get("sources", [])
                  if s.get("status") == "active" and s.get("url") not in spec_urls]
    for c in candidates:
        needs.append({"slot": "?", "kind": "candidate_awaiting_promotion",
                      "detail": f"self-discovered: {c.get('org', '?')} | {c.get('metric', '?')[:50]} | "
                                f"promote with --promote {axis} --url {c.get('url', '')[:60]}..."})

    report = {
        "ts": _iso(), "axis": axis,
        "composed": {"anchor": anchor, "daily": daily, "divergence": divergence,
                     "divergence_note": divergence_note},
        "slots": slots_report, "agreement": agreement,
        "confidence": confidence,
        "confidence_parts": {"coverage": round(coverage, 3), "diversity": round(diversity, 3),
                             "freshness": round(freshness, 3)},
        "needs": needs, "n_candidates": len(candidates),
    }

    _save(state_file, state)
    all_needs = _load(NEEDS_FILE, {})
    # The human's own demands (scripts/cortex_query.py --axis X --force) live in this
    # same file, and this assignment used to REPLACE the axis entry wholesale — so a
    # request queued by Emil was silently deleted here at beat 2.6, long before
    # data_scout read the file at beat 22.5. A queue nobody can write to durably is not
    # a queue. Human items survive the composer's rewrite of its OWN findings; they
    # leave only when the consumer marks them drained.
    kept_human = [i for i in (all_needs.get(axis) or {}).get("items", [])
                  if i.get("kind") == "human_sense_request" and not i.get("consumed")]
    all_needs[axis] = {"ts": _iso(), "items": kept_human + needs}
    _save(NEEDS_FILE, all_needs)
    all_out = _load(OUT_FILE, {})
    all_out[axis] = report
    _save(OUT_FILE, all_out)
    return report


# ── human-gated promotion: a candidate becomes a spec source (git-visible) ────

PROMOTE_FIELDS = ("extract", "col", "data_date_col", "data_date_extract",
                  "data_max_age_days", "provenance", "path", "unit")

# WHERE EACH KIND ACTUALLY READS FROM.
#
# This distinction caused a false alarm on 2026-07-31 and is worth stating once, plainly:
# a "file" source is loaded from `path` (see fetch(), kind == "file"), NEVER from `url`.
# A file entry may still carry `url`, and that is not a bug — it is the identity key the
# approval path uses for the stable approve-id, for double-promote dedupe, and for
# matching a promoted source back to its candidate record. On a file entry `url` is a
# REFERENCE, not a location; reading it as a fetch source is the mistake, not its presence.
KIND_LOCATION = {
    "file":              "path",
    "http_json_path":    "url",
    "http_csv":          "url",
    "http_json_count":   "url",
    "http_json_series":  "url",
    "http_gdelt_tone":   "url",
}


# The PARSING RULE each kind needs on top of its location. A source that declares where
# it lives but not how to read it fails identically on every fetch — which is a fact about
# OUR record, not about the provider, and must never be charged to the provider.
KIND_PARSE_RULE = {
    "file":              "extract",
    "http_json_path":    "extract",
    "http_json_count":   "extract",
    "http_json_series":  "extract",
    "http_csv":          "col",
    "http_gdelt_tone":   None,        # fixed payload shape, nothing to declare
}

# WHY A REFUSAL NEEDS A CLASS.
#
# Until 3 Aug 2026 every failed promotion looked the same to the approval path, so a
# candidate we had registered without a parsing rule was blacklisted exactly like a dead
# URL. Two working providers (OWID, the World Bank) were barred for a field WE had failed
# to compute, having never once been fetched. The class is what separates "our record is
# incomplete" from "this source does not work":
#   schema -> our fault. Discard, complete it, offer it again. NEVER blacklist.
#   fetch  -> the source's fault, and proven so by an actual request. Blacklisting is fair.
FAILURE_SCHEMA = "schema"
FAILURE_FETCH  = "fetch"


class PromotionRejected(ValueError):
    """A promotion refused BEFORE config/composer_specs.json was touched."""
    failure_class = FAILURE_SCHEMA
    reason_code = "incomplete_registration"


class SmokeFetchEmpty(PromotionRejected):
    """It answered, and what came back is not a number."""
    failure_class = FAILURE_FETCH
    reason_code = "no_usable_value"


class StaleData(PromotionRejected):
    """It answered with a real number whose own measurement date is already too old."""
    failure_class = FAILURE_FETCH
    reason_code = "stale_data_date"


_PARSE_ERRORS = (ValueError, TypeError, KeyError, IndexError, AttributeError,
                 json.JSONDecodeError, UnicodeDecodeError)


def classify_failure(exc: BaseException) -> tuple:
    """(failure_class, reason_code) — the honest name for why a promotion failed.

    Anything that carries its own class (the PromotionRejected family) states it. Anything
    else is a real request that went wrong, and the only question is HOW: the payload was
    unreadable, or the endpoint never answered."""
    cls = getattr(exc, "failure_class", None)
    if cls:
        return cls, getattr(exc, "reason_code", "unspecified")
    if isinstance(exc, RateLimited):
        return FAILURE_FETCH, "rate_limited"
    if isinstance(exc, FileNotFoundError):
        return FAILURE_FETCH, "dead_url"
    if isinstance(exc, _PARSE_ERRORS):
        return FAILURE_FETCH, "unparseable_payload"
    return FAILURE_FETCH, "dead_url"


def validate_rule(entry: dict) -> bool:
    """Second half of the schema wall: does this entry declare HOW to read what it points
    at? Separate from validate_entry() because the two answer different questions and the
    location check is asserted independently by test/test_promotion_seam.py."""
    kind = entry.get("kind")
    if kind not in KIND_PARSE_RULE:
        raise PromotionRejected(f"unknown kind {kind!r} — promotion rejected")
    field = KIND_PARSE_RULE[kind]
    if not field:
        return True
    val = entry.get(field)
    if isinstance(val, int) and not isinstance(val, bool):
        return True                      # column 0 is a real column
    if not str(val or "").strip():
        raise PromotionRejected(f"kind={kind} requires {field!r} (the parsing rule) — "
                                f"promotion rejected")
    return True


def validate_entry(entry: dict) -> bool:
    """Schema wall: does this entry declare the location its own kind reads from?

    A source promoted without it is a ghost — it enters the portfolio, raises on every
    fetch, and dies against DEATH_AT three cycles later while the slot has looked filled
    the whole time."""
    kind = entry.get("kind")
    loc = KIND_LOCATION.get(kind)
    if loc is None:
        raise PromotionRejected(f"unknown kind {kind!r} — promotion rejected")
    if not str(entry.get(loc) or "").strip():
        raise PromotionRejected(f"kind={kind} requires {loc!r} — promotion rejected")
    return True


def smoke_fetch(entry: dict):
    """Fetch this ONE entry with the SAME loader the composer uses, before the spec is
    written. 'Does it actually fetch?' stops being a question anyone has to ask later.

    Note 0.0 is a VALID reading (an event count of zero is a measurement); only a
    non-numeric result counts as empty.

    A source whose own measurement date is already past its declared limit is refused
    here rather than after promotion: the composer would refuse every value it served
    anyway, so promoting it only buys a slot that looks filled and never moves."""
    v, dd = fetch(entry)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:  # v!=v -> NaN
        raise SmokeFetchEmpty(f"smoke fetch returned no usable value ({v!r}) — "
                              f"promotion rejected")
    too_old, dd_age = _data_too_old(dd, float(entry.get("data_max_age_days", 3650)))
    if too_old:
        raise StaleData(f"smoke fetch read {v}, but its own data date {dd} is {dd_age}d old "
                        f"(limit {entry.get('data_max_age_days')}d) — promotion rejected")
    return v, dd


def promote(axis, url, slot, kind, org, extract=None, col=None, **fields):
    """Human-gated: a candidate becomes a spec source. The PARSING RULE travels with it —
    a promoted source without its extract/col is a source that dies on first fetch and then
    counts toward DEATH_AT, so the approval path must carry these through, not just the URL."""
    specs = _load(SPEC_FILE, {})
    spec = specs.get(axis)
    if not spec or slot not in spec.get("portfolio", {}):
        return {"error": f"axis/slot not in spec: {axis}/{slot}"}
    sid = f"promoted_{abs(hash(url)) % 100000}"
    entry = {"id": sid, "kind": kind, "url": url, "org": org}
    if extract:
        entry["extract"] = extract
    if col is not None:
        entry["col"] = col
    for k in PROMOTE_FIELDS:
        if fields.get(k) is not None:
            entry[k] = fields[k]
    entry.setdefault("provenance", "self-discovered, human-promoted")

    # THREE WALLS, all BEFORE the spec is touched. A rejected promotion must leave no
    # trace: no half-written entry, no source that only fails later. Every refusal carries
    # its CLASS, so the approval path can tell an incomplete record of ours from a source
    # that genuinely does not work — only the second may ever be blacklisted.
    try:
        validate_entry(entry)                       # 1. does it declare its location?
        validate_rule(entry)                        # 2. does it declare how to read it?
        smoke_value, smoke_date = smoke_fetch(entry)  # 3. does it actually fetch, once?
    except PromotionRejected as e:
        fclass, code = classify_failure(e)
        return {"error": str(e), "rejected": True, "id": sid,
                "failure_class": fclass, "reason_code": code,
                "exception": f"{type(e).__name__}: {e}"}
    except Exception as e:
        # the RAW exception is surfaced: "it didn't work" is not a diagnosis
        fclass, code = classify_failure(e)
        return {"error": f"smoke fetch failed — promotion rejected ({type(e).__name__}: "
                         f"{str(e)[:200]})",
                "rejected": True, "id": sid,
                "failure_class": fclass, "reason_code": code,
                "exception": f"{type(e).__name__}: {e}"}

    spec["portfolio"][slot]["sources"].append(entry)
    _save(SPEC_FILE, specs)
    return {"promoted": sid, "into_slot": slot, "smoke_value": smoke_value,
            "smoke_data_date": smoke_date,
            "note": "spec edited — review the git diff"}


def revive(axis: str) -> dict:
    """Human-gated resurrection: reset DEAD sources so they may be retried
    (e.g. after a fetch-path fix). Without this, death was permanent — a gap
    found on 30 Jul 2026 when a library bug killed two healthy sources."""
    state_file = STATE_DIR / f"{axis}.json"
    state = _load(state_file, {"sources": {}})
    revived = []
    for sid, st in state["sources"].items():
        if st.get("status") == "dead":
            st["status"] = "active"
            st["consecutive_fails"] = 0
            revived.append(sid)
    _save(state_file, state)
    return {"axis": axis, "revived": revived}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", metavar="AXIS")
    ap.add_argument("--force", action="store_true", help="ignore cache TTL and backoff")
    ap.add_argument("--needs", action="store_true")
    ap.add_argument("--revive", metavar="AXIS", help="reset dead sources for retry (human-gated)")
    ap.add_argument("--promote", metavar="AXIS")
    ap.add_argument("--url"); ap.add_argument("--slot"); ap.add_argument("--kind")
    ap.add_argument("--org", default="?"); ap.add_argument("--extract")
    ap.add_argument("--col", type=int)
    ap.add_argument("--path", help="repo-relative file for --kind file (its READ location)")
    a = ap.parse_args()

    # Caught at the parser, before promote() runs: --kind file reads from --path, and a
    # --url handed in its place is the mistake this gate exists to make impossible.
    if a.promote and a.kind == "file":
        # --url first: someone typing it HAS made the specific mistake this gate exists
        # for, and deserves to be told what the right field is rather than merely that
        # something is missing.
        if a.url:
            ap.error("--kind file reads from --path, not --url; pass --path "
                     "(on a file entry 'url' is an identity reference, set by the "
                     "approval path, never a fetch location)")
        if not a.path:
            ap.error("--kind file requires --path (the file it is read from)")

    if a.run:
        print(json.dumps(compose(a.run, force=a.force), ensure_ascii=False, indent=2))
    elif a.needs:
        print(json.dumps(_load(NEEDS_FILE, {}), ensure_ascii=False, indent=2))
    elif a.revive:
        print(json.dumps(revive(a.revive), ensure_ascii=False, indent=2))
    elif a.promote:
        print(json.dumps(promote(a.promote, a.url, a.slot, a.kind, a.org, a.extract, a.col,
                                 path=a.path), ensure_ascii=False, indent=2))
    else:
        ap.print_help()
