# -*- coding: utf-8 -*-
"""
How often an indicator can produce a NEW observation — and the deadlines that
refuses.

WHY (6 Sep 2026, Kimi R35)
--------------------------
proposal_intake admitted `WATER_REVIEW +1.2 by 2026-09-10`. WATER_REVIEW is the
World Bank's safe-water-access series, percent of population, **last observed in
2024**. Nothing can arrive before 10 September that would settle the prediction
either way: it is not wrong, it is unsettleable, and a ledger that scores it will
score noise.

A deadline is only meaningful if an observation can land inside it. So every
source declares a cadence, every indicator declares where its last observation
date is read from, and the gate refuses a deadline that falls before the next
observation is due — BY NAME, never by silently shortening or downgrading it.

NO DEFAULT ANYWHERE. A source or indicator without a declared cadence fails loud
at load and is named. Defaulting to "daily" is precisely the assumption that let
a four-day deadline onto an annual series in the first place.
"""
from __future__ import annotations

import json
import pathlib
from datetime import date, timedelta

BASE = pathlib.Path(__file__).resolve().parents[1]
CONFIG = BASE / "config" / "indicator_cadence.json"
SPECS = BASE / "config" / "composer_specs.json"
SNAPSHOT = BASE / "snapshots" / "master" / "global_indicators_latest.json"

CADENCES = ("daily", "weekly", "monthly", "quarterly", "annual")
DAILY_TIER = ("daily", "weekly")
SLOW_TIER = ("monthly", "quarterly", "annual")

# How far ahead the next observation is, once one is due.
_STEP_DAYS = {"daily": 1, "weekly": 7, "monthly": 31, "quarterly": 92, "annual": 366}

# A deadline this far out is allowed for a daily-tier indicator without asking
# when the next observation lands, because one lands every day or week anyway.
DAILY_TIER_HORIZON_DAYS = 30


class CadenceError(ValueError):
    """A source or indicator with no declared cadence. Loud, and named."""


def _load(path: pathlib.Path | None = None) -> dict:
    p = path or CONFIG
    if not p.is_file():
        raise CadenceError(f"no cadence declaration at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def declared(path: pathlib.Path | None = None) -> dict:
    """indicator -> declaration. Raises naming any bad cadence word."""
    blob = _load(path)
    out = dict(blob.get("indicators") or {})
    bad = [k for k, v in out.items()
           if str((v or {}).get("cadence")) not in CADENCES]
    if bad:
        raise CadenceError(
            "cadence missing or not one of " + "/".join(CADENCES) + " for: "
            + ", ".join(sorted(bad)))
    return out


def tier(cadence: str) -> str:
    return "DAILY-TIER" if cadence in DAILY_TIER else "SLOW-TIER"


def _dig(blob: dict, dotted: str):
    node = blob
    for part in str(dotted).split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _as_date(raw) -> date | None:
    """'2024' -> 2024-12-31 (an annual figure describes the whole year, and is
    published the year after). '2026-08-30' -> that day."""
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        if len(s) == 4 and s.isdigit():
            return date(int(s), 12, 31)
        return date.fromisoformat(s[:10])
    except Exception:                                            # noqa: BLE001
        return None


def next_expected(last: date | None, cadence: str, today: date | None = None) -> date | None:
    """When the next observation can be expected. None when the last one is
    unknown — a named unknown, never 'today'.

    OVERDUE SERIES ROLL FORWARD (measured 6 Sep 2026). WATER_REVIEW was last
    observed in 2024, so last + one year = 2026-01-01, which is already in the
    past: the 2025 figure has NOT arrived and the snapshot still reads 2024. A
    naive last+step would then say "next expected January", eight months ago,
    and wave through a September deadline on a series that has not moved in two
    years. When the due date has passed with no new value, the earliest an
    observation can honestly be expected is one full period from TODAY.
    """
    if last is None:
        return None
    today = today or date.today()
    nxt = last + timedelta(days=_STEP_DAYS[cadence])
    if nxt <= today:
        nxt = today + timedelta(days=_STEP_DAYS[cadence])
    return nxt


def is_overdue(last: date | None, cadence: str, today: date | None = None) -> bool:
    """The series should already have produced a new value and has not."""
    if last is None:
        return False
    today = today or date.today()
    return (last + timedelta(days=_STEP_DAYS[cadence])) <= today


def for_indicator(name: str, snapshot: pathlib.Path | None = None,
                  path: pathlib.Path | None = None, today: date | None = None) -> dict:
    """{"cadence", "tier", "last_observed", "next_expected", "source"} or raises.

    An indicator nobody declared is an error, not a daily one.
    """
    decl = declared(path)
    if name not in decl:
        raise CadenceError(f"indicator {name!r} has no declared cadence in {CONFIG.name}")
    d = decl[name]
    cad = d["cadence"]
    blob = {}
    sp = snapshot or SNAPSHOT
    if sp.is_file():
        try:
            blob = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:                                        # noqa: BLE001
            blob = {}
    last = _as_date(_dig(blob, d.get("last_observed_from", "")))
    today = today or date.today()
    return {"indicator": name, "cadence": cad, "tier": tier(cad),
            "last_observed": last.isoformat() if last else None,
            "next_expected": (next_expected(last, cad, today).isoformat()
                              if last else None),
            "overdue": is_overdue(last, cad, today),
            "source": d.get("source", ""), "note": d.get("note", "")}


def annotate(indicators: dict, snapshot: pathlib.Path | None = None,
             path: pathlib.Path | None = None) -> dict:
    """{indicator: {value, cadence, tier, last_observed, next_expected}}.

    An indicator with no declaration is carried with cadence None and an
    `undeclared` flag rather than dropped: the gate must be able to refuse it by
    name, and dropping it here would hide it instead.
    """
    out = {}
    for name, value in (indicators or {}).items():
        try:
            info = for_indicator(name, snapshot, path)
        except CadenceError as e:
            out[name] = {"value": value, "cadence": None, "tier": "UNDECLARED",
                         "last_observed": None, "next_expected": None,
                         "undeclared": str(e)}
            continue
        info["value"] = value
        out[name] = info
    return out


def deadline_refusal(indicator: str, deadline: date, snapshot: pathlib.Path | None = None,
                     path: pathlib.Path | None = None) -> str | None:
    """The refusal string, or None when the deadline can be settled.

    Daily-tier indicators pass on any deadline inside DAILY_TIER_HORIZON_DAYS,
    because a new observation lands every day or week regardless.
    """
    try:
        info = for_indicator(indicator, snapshot, path)
    except CadenceError as e:
        return f"cadence: {e}"
    if info["cadence"] in DAILY_TIER:
        return None
    nxt = info["next_expected"]
    if nxt is None:
        return (f"cadence: {indicator} is {info['cadence']} and its last observation "
                f"date is unknown, so no deadline can be checked against it")
    if deadline < date.fromisoformat(nxt):
        overdue = " and already overdue" if info.get("overdue") else ""
        return (f"cadence: {indicator} is {info['cadence']}, last observed "
                f"{info['last_observed']}{overdue}, next expected {nxt}; deadline "
                f"{deadline.isoformat()} is before any new observation")
    return None


# ── the 81 source entries in composer_specs.json ────────────────────────────

def audit_specs(specs: pathlib.Path | None = None) -> dict:
    """{"total", "with_cadence", "missing": [ids]} — every source must declare one."""
    p = specs or SPECS
    blob = json.loads(p.read_text(encoding="utf-8"))
    total, missing = 0, []
    for axis, spec in blob.items():
        if axis.startswith("_") or not isinstance(spec, dict):
            continue
        for slot, pf in (spec.get("portfolio") or {}).items():
            for s in (pf.get("sources") or []):
                total += 1
                if str(s.get("cadence")) not in CADENCES:
                    missing.append(f"{axis}/{slot}/{s.get('id', '?')}")
    return {"total": total, "with_cadence": total - len(missing), "missing": missing}


def load_specs(specs: pathlib.Path | None = None) -> dict:
    """composer_specs.json, refusing to load if any source has no cadence."""
    rep = audit_specs(specs)
    if rep["missing"]:
        raise CadenceError(
            f"{len(rep['missing'])} source(s) in composer_specs.json declare no "
            f"cadence: " + ", ".join(rep["missing"][:8])
            + (" ..." if len(rep["missing"]) > 8 else ""))
    return json.loads((specs or SPECS).read_text(encoding="utf-8"))
