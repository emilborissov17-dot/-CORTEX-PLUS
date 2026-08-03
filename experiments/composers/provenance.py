#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/composers/provenance.py — where a number actually comes from, and who measured it.

TWO LIES THE PORTFOLIO WAS TELLING, both by omission.

ORIGIN. A source declared an `org` — a free-text label an LLM supplied at discovery — and
the composer counted distinct orgs as DIVERSITY. Measured on the live spec: 43 of 60
sources are kind:file and 41 of those read ONE file,
snapshots/master/global_indicators_latest.json. They carry 15 different org labels, so the
diversity score reads well while the entire portfolio stands on a single file.
SOCIAL_RELATIONS_REVIEW/anchor_annual holds two sources labelled UNHCR and UCDP/PRIO: two
orgs, one origin, min:1 satisfied, slot reported filled. Origin is what a source RESOLVES
to — the file it is read from, or the host it is fetched from — and it is derived at read
time rather than stored, because a stored copy of a derivable fact goes stale the day a URL
changes and then lies with a straight face. An explicit src["origin"] is honoured when a
human sets one, which is the case that is NOT derivable: declaring that
global_indicators_latest.json ultimately resolves to the World Bank.

REPORTER INDEPENDENCE. The guard stack proves we did not invent a number and did read it
correctly. It says nothing about whether the number is true, and
world_bank.safe_water_access_pct originates from national statistical offices — the
measured entity reporting on itself. That is the third layer and it is OPEN. This module
does not close it. It makes it VISIBLE: every source carries a class, the classes are
counted per axis, and an axis satisfied entirely by self-reported sources says so out loud.

THE CLASS IS NEVER SCORED. Nothing here feeds a confidence, a weight, a composite or a
ranking. Discounting a self_reported source would be asserting that governments lie about
water access — which may be true, and which we have no evidence for. A visibility flag for
a human is exactly as far as the evidence goes. test/test_origin_honesty.py asserts the
composite is byte-identical with the flag present and absent.

The mapping is human-owned (config/reporter_independence.json). The system may write into
`proposed`; only `confirmed` is admissible. Unmapped is `unknown`, and unknown is never
upgraded to independent.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

REPORTER_FILE = REPO / "config" / "reporter_independence.json"

# More than this share of an axis's sources on ONE origin and the axis is flagged. 50% is a
# deliberately loud threshold: at half, the axis's answer moves when that one origin moves,
# whatever the other half says.
ORIGIN_CONCENTRATION_THRESHOLD = 0.5

CLASSES = ("self_reported", "independent", "adversarial", "unknown")
UNKNOWN = "unknown"


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def host_of(url: str) -> str:
    """The hostname, by string surgery rather than urllib, so this stays trivially
    re-implementable inside scripts/cortex_query.py — which may not import anything."""
    s = str(url or "").strip()
    s = s.split("://", 1)[-1]
    s = s.split("/", 1)[0]
    s = s.split("@")[-1]
    s = s.split(":")[0]
    return s.lower()


def origin(src: dict) -> str:
    """What this source ULTIMATELY resolves to.

    Derived, not stored. An explicit src["origin"] wins — that is the human's way of
    saying what a derivation cannot know (that a local snapshot file is really the World
    Bank). A file is its path; anything fetched is its host.
    """
    explicit = str(src.get("origin") or "").strip()
    if explicit:
        return explicit
    if src.get("kind") == "file":
        return str(src.get("path") or "?")
    return host_of(src.get("url")) or "?"


def reporter_config(path=None) -> dict:
    return _load(path or REPORTER_FILE, {}) or {}


def reporter_class(src: dict, cfg: dict = None) -> tuple:
    """(class, why). Only human-CONFIRMED mappings are admissible.

    A class written straight onto a source record is honoured only when the record also
    names the human who confirmed it — otherwise it is a claim the system made about
    itself, which is evidence of nothing. `proposed` is never read here.
    """
    cfg = reporter_config() if cfg is None else cfg
    confirmed = cfg.get("confirmed") or {}

    onrec = str(src.get("reporter_class") or "").strip()
    by = str(src.get("reporter_class_confirmed_by") or "").strip()
    if onrec in CLASSES and by:
        return onrec, f"confirmed on the source record by {by}"

    for key in (f"host:{host_of(src.get('url'))}" if src.get("url") else None,
                f"org:{src.get('org')}" if src.get("org") else None,
                f"path:{src.get('path')}" if src.get("path") else None):
        if key and key in confirmed:
            hit = confirmed[key]
            return (hit.get("class", UNKNOWN),
                    f"{key} — {hit.get('why', 'no reason recorded')} "
                    f"[confirmed by {hit.get('confirmed_by', '?')}]")

    return UNKNOWN, ("no confirmed mapping for this org or host — and unknown is never "
                     "read as independent")


def unmapped_keys(sources, cfg: dict = None) -> list:
    """Orgs and hosts a human has not ruled on. The queue, not a verdict."""
    cfg = reporter_config() if cfg is None else cfg
    out = set()
    for s in sources:
        cls, _why = reporter_class(s, cfg)
        if cls != UNKNOWN:
            continue
        if s.get("url"):
            out.add(f"host:{host_of(s['url'])}")
        if s.get("org"):
            out.add(f"org:{s['org']}")
    return sorted(out)


def concentration(sources, threshold: float = None) -> dict:
    """Origin concentration over a set of sources."""
    thr = ORIGIN_CONCENTRATION_THRESHOLD if threshold is None else threshold
    counts = Counter(origin(s) for s in sources)
    total = sum(counts.values())
    if not total:
        return {"origins": {}, "n_sources": 0, "n_origins": 0, "top_origin": None,
                "top_share": None, "concentrated": False, "threshold": thr}
    top, n = counts.most_common(1)[0]
    share = n / total
    return {"origins": dict(counts), "n_sources": total, "n_origins": len(counts),
            "top_origin": top, "top_share": round(share, 3),
            "concentrated": share > thr, "threshold": thr}


def class_shares(sources, cfg: dict = None) -> dict:
    cfg = reporter_config() if cfg is None else cfg
    counts = Counter(reporter_class(s, cfg)[0] for s in sources)
    total = sum(counts.values())
    return {
        "counts": {c: counts.get(c, 0) for c in CLASSES},
        "n_sources": total,
        "shares": {c: (round(counts.get(c, 0) / total, 3) if total else None)
                   for c in CLASSES},
        "self_reported_only": bool(total) and counts.get("self_reported", 0) == total,
        "never_scored": "these classes feed no confidence, weight or composite anywhere",
    }


def slot_status(live_sources, minimum: int) -> tuple:
    """(status, note). 'filled' | 'nominally_filled' | 'unfilled'.

    NOMINALLY FILLED is the case this whole module exists for: the count is met and the
    redundancy is not real, because every source meeting it resolves to the same origin.
    If that origin goes down or goes wrong, the slot goes with it — which is exactly what
    'filled' was quietly promising it would not do.
    """
    n = len(live_sources)
    if n < max(1, int(minimum or 1)):
        return "unfilled", f"{n} live source(s), needs {minimum}"
    origins = {origin(s) for s in live_sources}
    if len(origins) == 1:
        only = next(iter(origins))
        # Two ways to arrive at one origin, and they deserve different sentences. Several
        # sources on one origin is a FALSE redundancy — the count promised something the
        # provenance does not deliver. One source on one origin promised nothing; it is
        # simply as reliable as that origin, which is worth saying and is not a betrayal.
        if n > 1:
            note = (f"{n} live source(s) meeting min={minimum}, but all of them resolve to "
                    f"one origin ({only}) — the redundancy is in the labels, not in the "
                    f"provenance")
        else:
            note = (f"1 live source meeting min={minimum} — the slot is exactly as "
                    f"reliable as {only}, no more and no less")
        return "nominally_filled", note
    return "filled", f"{n} live source(s) across {len(origins)} origins"
