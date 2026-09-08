#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/passage_rules.py — THE RULE AND THE ENFORCEMENT ARE THE SAME OBJECT.

WHY THIS EXISTS (8 Sep 2026)
-----------------------------
The gate's rules lived as constants inside core/notary.py — LEVEL_NAMES,
IRREVERSIBLE_MIN, MAX_LEVEL, _STALE_DAYS — and nowhere else. Two consequences,
and both are the same defect seen from different ends:

  1. THE ACTOR COULD NOT READ THE STANDARD IT WAS JUDGED BY. self_modifier was
     refused 35 nights running for an origin level, and its prompt never once
     mentioned that origin level exists. It was being marked against a rubric it
     had never been shown, and then asked to do better.

  2. NOTHING COULD DETECT DRIFT. Any prose describing the rules — a docstring, a
     report, a prompt — was a second copy, free to say something the code did
     not do. The only defence was that somebody would notice.

So the rules move into config/passage_rules.json, notary READS them to judge,
and the SAME actor_block text is injected into every gated actor's instructions.
One object, two readers. test/test_passage_rules.py fails if the enforced
constants stop matching the file, or if the text an actor is shown stops being
byte-identical to actor_block.

TRANSPARENCY, NOT POLICY. Every value was copied out of core/notary.py
unchanged. Making the ceiling configurable must not make it quietly editable, so
test_the_ratified_values_have_not_moved pins each number: raising a ceiling now
takes an edit to the config AND to that test, in one diff, where a human sees it.

FAIL CLOSED
-----------
If the file is missing, unparseable or fails validation, load() returns FAILSAFE:
irreversible_min = UNREACHABLE, so may_act() refuses every irreversible step. A
ruleset that cannot be read must never be read as permission. It prints loudly
and does not raise, because a gate that crashes the cycle is its own outage.

    venv\\Scripts\\python.exe core/passage_rules.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RULES_FILE = REPO / "config" / "passage_rules.json"

# Higher than any level the scale can produce, so `level >= irreversible_min` is
# false for everything. This is what "fail closed" means here, expressed as a
# number rather than as an intention.
UNREACHABLE = 99

_REQUIRED = ("scale", "irreversible_min", "stale_days", "ceilings",
             "verifiers", "actor_block")


class RulesUnreadable(Exception):
    """Raised only by load(strict=True), which the selftest and tests use."""


def _validate(doc: dict) -> dict:
    missing = [k for k in _REQUIRED if k not in doc]
    if missing:
        raise RulesUnreadable(f"missing keys: {', '.join(missing)}")

    scale = doc["scale"]
    if set(scale) != {"0", "1", "2", "3"}:
        raise RulesUnreadable(f"scale must be exactly 0..3, got {sorted(scale)}")
    for k, v in scale.items():
        if not isinstance(v, dict) or not v.get("name"):
            raise RulesUnreadable(f"scale[{k}] has no name")

    if not isinstance(doc["irreversible_min"], int):
        raise RulesUnreadable("irreversible_min is not an int")
    stale = doc["stale_days"]
    if (not isinstance(stale, list) or len(stale) != 3
            or sorted(stale) != list(stale)):
        raise RulesUnreadable(f"stale_days must be three ascending numbers: {stale}")
    if not isinstance(doc["ceilings"], dict):
        raise RulesUnreadable("ceilings is not an object")
    for step, lvl in doc["ceilings"].items():
        if not isinstance(lvl, int) or not 0 <= lvl <= 3:
            raise RulesUnreadable(f"ceiling for {step!r} is not a level: {lvl!r}")
    if not str(doc["actor_block"]).strip():
        raise RulesUnreadable("actor_block is empty — the actor would be shown nothing")
    return doc


def _failsafe(why: str) -> dict:
    print(f"[PASSAGE_RULES] UNREADABLE — the gate is now closed to every "
          f"irreversible step: {why}")
    return {
        "version": "FAILSAFE",
        "level_names": {3: "level_3", 2: "level_2", 1: "level_1", 0: "level_0"},
        # The whole point: nothing can reach this, so nothing irreversible acts.
        "irreversible_min": UNREACHABLE,
        "stale_days": (2, 30, 365),
        "ceilings": {},
        "verifiers": set(),
        "actor_block": (
            "THE RULES OF PASSAGE could not be loaded, so the gate is closed to "
            "every irreversible step until config/passage_rules.json is readable "
            "again. Nothing you write can pass while this is true."),
        "unreadable": why,
    }


def load(path: Path | None = None, strict: bool = False) -> dict:
    """The ruleset, shaped for the notary. Never raises unless strict."""
    src = path or RULES_FILE
    try:
        doc = _validate(json.loads(src.read_text(encoding="utf-8")))
    except Exception as exc:                                     # noqa: BLE001
        if strict:
            raise
        return _failsafe(f"{type(exc).__name__}: {exc}")

    return {
        "version": doc.get("version", "?"),
        # int keys, because that is what the notary indexes by
        "level_names": {int(k): v["name"] for k, v in doc["scale"].items()},
        "level_earns": {int(k): v.get("earns", "") for k, v in doc["scale"].items()},
        "irreversible_min": doc["irreversible_min"],
        "stale_days": tuple(doc["stale_days"]),
        "ceilings": dict(doc["ceilings"]),
        "verifiers": set(doc["verifiers"]),
        "actor_block": doc["actor_block"],
        "dimensions": doc.get("dimensions", {}),
        "unreadable": None,
    }


RULES = load()


def actor_block() -> str:
    """The text every gated actor is shown, verbatim.

    SHARED BY DESIGN. self_modifier is the first caller; hyperclaw and any future
    producer that faces the gate call this same function and receive the same
    bytes. A second actor with its own paraphrase would recreate exactly the
    drift this module exists to end.
    """
    return RULES["actor_block"]


def _selftest() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    print("core/passage_rules.py --selftest")
    print(f"  config/passage_rules.json : "
          f"{'LIVE' if RULES_FILE.exists() else 'INERT (missing)'}")

    try:
        strict = load(strict=True)
        print(f"  validation               : LIVE (version {strict['version']})")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  validation               : BROKEN ({type(exc).__name__}: {exc})")
        return 1

    ok = True
    try:
        from core import notary as N
        same = (N.IRREVERSIBLE_MIN == strict["irreversible_min"]
                and N.MAX_LEVEL == strict["ceilings"]
                and tuple(N._STALE_DAYS) == strict["stale_days"]
                and N.LEVEL_NAMES == strict["level_names"]
                and N.VERIFIERS == strict["verifiers"])
        print(f"  notary enforces this file: {'LIVE' if same else 'DRIFTED'}")
        if not same:
            print(f"      notary irreversible_min={N.IRREVERSIBLE_MIN} "
                  f"file={strict['irreversible_min']}")
            print(f"      notary ceilings={N.MAX_LEVEL} file={strict['ceilings']}")
            ok = False
    except Exception as exc:                                     # noqa: BLE001
        print(f"  notary enforces this file: INERT ({type(exc).__name__}: {exc})")
        ok = False

    try:
        from agents.core.self_modifier import PASSAGE_RULES_BLOCK
        shown = PASSAGE_RULES_BLOCK == strict["actor_block"]
        print(f"  actor is shown this file : {'LIVE' if shown else 'DRIFTED'}")
        ok = ok and shown
    except Exception as exc:                                     # noqa: BLE001
        print(f"  actor is shown this file : INERT ({type(exc).__name__}: {exc})")
        ok = False

    bad = load(path=REPO / "config" / "does_not_exist.json")
    closed = bad["irreversible_min"] == UNREACHABLE
    print(f"  fail-closed on a bad file: {'LIVE' if closed else 'BROKEN — OPENS'}")
    ok = ok and closed

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
