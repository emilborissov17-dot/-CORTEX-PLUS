#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/earning.py — THE DETERMINISTIC VERIFIER. IT GRANTS NOTHING.

WHAT THIS IS
-------------
Section 5 of claude/reports/EARNING_PATH_PROPOSAL_8SEP.md, built on the real
repo. Given a candidate patch's changed files, its class definition, its test
result and its before/after evidence, verify() answers one question:

    would this patch have cleared its class's bar?

and returns (decision, reason). That is all it does.

WHAT THIS IS NOT — READ THIS BEFORE WIRING ANYTHING
----------------------------------------------------
  * It is NOT imported by core/notary.py, and core/notary.py is not modified.
  * It appends NOTHING to memory/development_journal.json.
  * It writes no attestation and touches no chain.
  * config/earning_classes.json has global_cap "LOCKED" and not one signed
    class, so verify() currently returns FAIL for everything.
  * MAX_LEVEL, IRREVERSIBLE_MIN, AMENDMENT_001 and every ceiling are untouched.

A PASS from this module is a statement about evidence, not a permission. Nothing
consumes it. Wiring it is a separate decision for Emil, after AMENDMENT_001's
cooling-off (19 Oct 2026).

IT NEVER CALLS A MODEL, AND THAT IS THE WHOLE DESIGN
-----------------------------------------------------
This repo has measured its model judges twice and both were rubber stamps: the
3B moral gate caught 100% and false-positived 100%, and a model judge
rubber-stamped 17/17 quarantined patches until deterministic wiring checks
overruled them. So every condition below is a path comparison, an exit code, or
arithmetic over a JSON file. There is no eval, no subprocess, no import of
patch-supplied code, and no LLM call anywhere in this file.

BUILT ON execute_patches.py, NOT BESIDE IT
-------------------------------------------
The evidence functions already exist and are imported from there rather than
reimplemented — a second copy would drift from the one the cycle actually runs:

    _measurement_quality(measured, source) -> ("MEASURED"|"ZERO"|"FABRICATED"
                                               |"UNMEASURED", why)
    _changed_axes(before, after)           -> ["AXIS: LOW → MEDIUM", ...]
    _extract_measured(stdout)              -> dict | str | None

THE FORBIDDEN FALLBACK, NAMED
------------------------------
A patch that edits the verifier, the policy, the rules of passage, or the tests
that pin them is FAIL — always, whatever its class allows. Those are the four
ways a mechanism grants itself trust without earning it, and ALWAYS_FORBIDDEN is
applied AFTER the class's own allowed_paths so no class can widen its way out.
Do NOT add an exemption to it "for the bootstrap case"; there is no bootstrap
case that needs one.

    venv\\Scripts\\python.exe core/earning.py --selftest
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLASSES_FILE = REPO / "config" / "earning_classes.json"
REVOCATIONS = REPO / "memory" / "earning_revocations.jsonl"

PASS, FAIL = "PASS", "FAIL"

# REDUCED(2) from config/passage_rules.json — the lowest level at which an
# irreversible step may act. Read from the ruleset rather than restated, so the
# cap this module enforces cannot drift from the one the notary applies.
def _reduced() -> int:
    try:
        from core.passage_rules import RULES
        return int(RULES["irreversible_min"])
    except Exception:
        return 2


# THE FOUR WAYS A MECHANISM GRANTS ITSELF TRUST. Applied to every class, after
# its own allowed_paths, so no class can widen its way out of them.
ALWAYS_FORBIDDEN = (
    "core/earning.py",              # the verifier rewriting its own conditions
    "config/earning_classes.json",  # the policy rewriting its own limits
    "config/passage_rules.json",    # the rules of passage
    "test/test_earning_verifier.py",  # the tests that pin the verifier
    "test/test_passage_rules.py",     # the tests that pin the rules
)

# The deterministic operations a class metric may use. No eval, no lambda, no
# code from the patch: a fixed table of four, each a few lines of arithmetic.
_OPS = ("len", "count_keys", "sum_values", "value_at")


def _norm(p: str) -> str:
    return str(p).replace("\\", "/").lstrip("./")


def _under(path: str, prefix: str) -> bool:
    """Path-prefix containment on normalised separators. A prefix ending in '/'
    means the tree; otherwise an exact file or a tree below it."""
    path, prefix = _norm(path), _norm(prefix)
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


# ---------------------------------------------------------------------------
# the policy
# ---------------------------------------------------------------------------

def load_classes(path: Path | None = None) -> dict:
    """The policy, or a fail-closed stand-in. NEVER raises.

    A malformed policy yields locked=True and no classes, so every verify() call
    returns FAIL. A policy that cannot be read is never permission.
    """
    src = path or CLASSES_FILE
    try:
        doc = json.loads(src.read_text(encoding="utf-8"))
    except Exception as exc:                                     # noqa: BLE001
        return {"locked": True, "classes": {}, "policy_version": None,
                "max_cap_ceiling": _reduced(),
                "unreadable": f"{type(exc).__name__}: {exc}"}

    problems = []
    if not isinstance(doc.get("classes"), dict):
        problems.append("classes is not an object")
    ceiling = doc.get("_max_cap_ceiling")
    if not isinstance(ceiling, int) or not 0 <= ceiling <= _reduced():
        problems.append(f"_max_cap_ceiling {ceiling!r} is not an int in 0..{_reduced()}")
    if doc.get("global_cap") not in ("LOCKED", "UNLOCKED"):
        problems.append(f"global_cap {doc.get('global_cap')!r} is neither LOCKED nor UNLOCKED")
    if problems:
        return {"locked": True, "classes": {}, "policy_version": doc.get("policy_version"),
                "max_cap_ceiling": _reduced(),
                "unreadable": "; ".join(problems)}

    return {
        "locked": doc.get("global_cap") != "UNLOCKED",
        "classes": doc["classes"],
        "policy_version": doc.get("policy_version"),
        "max_cap_ceiling": ceiling,
        "always_forbidden_declared": tuple(doc.get("_always_forbidden_paths") or ()),
        "unreadable": None,
    }


# ---------------------------------------------------------------------------
# independent recomputation of the patch's own claim
# ---------------------------------------------------------------------------

def recompute(metric: dict, base: Path | None = None):
    """Re-derive the claimed value from the named file, by code that did not come
    from the patch. Returns (value, why); value is None when it cannot be done.

    The op table is fixed and tiny on purpose. The moment a class could supply an
    expression, the patch's author would be supplying the check.
    """
    base = base or REPO
    if not isinstance(metric, dict):
        return None, "no metric declared"
    op, rel, key = metric.get("op"), metric.get("file"), metric.get("key")
    if op not in _OPS:
        return None, f"op {op!r} is not one of {_OPS}"
    if not rel:
        return None, "no file declared"
    path = Path(base) / rel
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                                     # noqa: BLE001
        return None, f"{rel} unreadable: {type(exc).__name__}: {exc}"

    target = data
    if key is not None:
        if not isinstance(data, dict) or key not in data:
            return None, f"{rel} has no key {key!r}"
        target = data[key]

    try:
        if op == "len":
            return len(target), f"len({rel}{'' if key is None else '[' + str(key) + ']'})"
        if op == "count_keys":
            if not isinstance(target, dict):
                return None, f"count_keys needs an object, got {type(target).__name__}"
            return len(target), f"count_keys({rel})"
        if op == "sum_values":
            if not isinstance(target, dict):
                return None, f"sum_values needs an object, got {type(target).__name__}"
            return sum(v for v in target.values() if isinstance(v, (int, float))), \
                f"sum_values({rel})"
        if op == "value_at":
            return target, f"value_at({rel}[{key!r}])"
    except Exception as exc:                                     # noqa: BLE001
        return None, f"{op} failed on {rel}: {type(exc).__name__}: {exc}"
    return None, "unreachable"


# ---------------------------------------------------------------------------
# the revocation record
# ---------------------------------------------------------------------------

def record_revocation(class_id: str, reason: str, changed_files=None,
                      path: Path | None = None) -> dict:
    """A FAIL is written down, by class, so a lift that was lost is countable.

    Two sinks, because they fail differently: memory/blackbox.jsonl is fsync'd
    per line and survives a hard kill, and memory/earning_revocations.jsonl is
    the per-class ledger this module reads back in revocations_for(). Neither is
    memory/development_journal.json — this module appends nothing there.

    Never raises. Losing the record must not turn a FAIL into an exception, and a
    FAIL that cannot be written is still a FAIL.
    """
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "class_id": class_id,
        "decision": FAIL,
        "reason": reason,
        "changed_files": sorted(_norm(f) for f in (changed_files or [])),
        "lift_lost": True,
    }
    try:
        from core import blackbox
        blackbox.record("earning_verifier", phase="lift_revoked",
                        class_id=class_id, reason=reason[:300])
    except Exception as exc:                                     # noqa: BLE001
        print(f"[EARNING] blackbox could not record the revocation of "
              f"{class_id}: {type(exc).__name__}: {exc}")
    out = path or REVOCATIONS
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:                                     # noqa: BLE001
        print(f"[EARNING] revocation ledger unwritable: "
              f"{type(exc).__name__}: {exc}")
    return rec


def revocations_for(class_id: str, path: Path | None = None) -> list:
    """The named reader of memory/earning_revocations.jsonl."""
    src = path or REVOCATIONS
    out = []
    try:
        for line in src.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("class_id") == class_id:
                out.append(rec)
    except Exception:
        return []
    return out


# ---------------------------------------------------------------------------
# the verifier
# ---------------------------------------------------------------------------

def verify(candidate_changed_files, class_def, test_result, before_after,
           class_id: str = "?", policy: dict | None = None,
           base: Path | None = None,
           revocations_path: Path | None = None) -> tuple:
    """(decision, reason). PASS only if EVERY condition holds.

    candidate_changed_files : [repo-relative paths the patch touches]
    class_def               : one entry out of config/earning_classes.json
    test_result             : {"exit_code": int, "timed_out": bool}
    before_after            : {"levels_before": {}, "levels_after": {},
                               "measured": <MEASURED payload>, "source": <patch src>}

    The order matters. The policy switches are checked first so a locked or
    unsigned class never reaches the path logic; the path checks come before the
    evidence so a patch that edits the verifier is refused before its own
    numbers are ever consulted.
    """
    pol = policy if policy is not None else load_classes()
    changed = [_norm(f) for f in (candidate_changed_files or [])]

    def _fail(reason):
        # revocations_path is threaded all the way down so a test or a selftest
        # can grade a candidate without appending to the live ledger. A verifier
        # whose own exercise writes into the record it verifies against is the
        # defect one level up.
        if class_def is None or class_def.get("auto_revoke_on_failure", True):
            record_revocation(class_id, reason, changed, path=revocations_path)
        return FAIL, reason

    # -- the policy switches ------------------------------------------------
    if pol.get("unreadable"):
        return _fail(f"policy unreadable, no lift for anything: {pol['unreadable']}")
    if pol.get("locked"):
        return _fail("global_cap is LOCKED — no class may be granted anything")
    if not isinstance(class_def, dict):
        return _fail(f"class {class_id!r} is not defined")
    if class_def.get("human_signed") is not True:
        return _fail(f"class {class_id!r} is not human_signed")

    cap = class_def.get("max_cap")
    ceiling = pol.get("max_cap_ceiling", _reduced())
    if not isinstance(cap, int) or cap > ceiling:
        return _fail(f"max_cap {cap!r} exceeds the ceiling {ceiling} "
                     f"(REDUCED) — refused, never clamped")
    if class_def.get("network_allowed") is not False:
        return _fail("network_allowed must be false: a class needing the network "
                     "cannot be verified deterministically offline")
    if class_def.get("new_dependencies_allowed") is not False:
        return _fail("new_dependencies_allowed must be false: a new dependency is "
                     "a change to what the system is, not a patch within a class")

    # -- the paths, before any evidence is looked at ------------------------
    if not changed:
        return _fail("the patch changes no file")

    for f in changed:
        for prefix in ALWAYS_FORBIDDEN:
            if _under(f, prefix):
                return _fail(
                    f"{f} is in ALWAYS_FORBIDDEN ({prefix}) — a patch that edits "
                    f"the verifier, the policy, the rules of passage or the tests "
                    f"that pin them can never pass, whatever its class allows")

    allowed = class_def.get("allowed_paths") or []
    for f in changed:
        if not any(_under(f, a) for a in allowed):
            return _fail(f"{f} is outside allowed_paths {list(allowed)}")

    for f in changed:
        for prefix in (class_def.get("forbidden_paths") or []):
            if _under(f, prefix):
                return _fail(f"{f} is in this class's forbidden_paths ({prefix})")

    # -- the tests ----------------------------------------------------------
    tr = test_result or {}
    if tr.get("timed_out"):
        return _fail("the required tests timed out — a timeout is not a pass")
    if tr.get("exit_code") != 0:
        return _fail(f"the required tests exited {tr.get('exit_code')!r}, not 0")

    # -- the evidence -------------------------------------------------------
    ba = before_after or {}
    try:
        from execute_patches import _measurement_quality, _changed_axes
    except Exception as exc:                                     # noqa: BLE001
        return _fail(f"cannot read the evidence functions from execute_patches: "
                     f"{type(exc).__name__}: {exc}")

    quality, why = _measurement_quality(ba.get("measured"), ba.get("source") or "")
    if quality != "MEASURED":
        return _fail(f"measurement quality is {quality}, not MEASURED: {why}")

    axis = class_def.get("claims_axis")
    changed_axes = _changed_axes(ba.get("levels_before") or {},
                                 ba.get("levels_after") or {})
    if not axis:
        return _fail("the class claims no axis, so nothing can be checked against it")
    if not any(str(c).split(":")[0].strip() == axis for c in changed_axes):
        return _fail(f"_changed_axes does not name {axis}: {changed_axes or 'nothing moved'}")

    measured = ba.get("measured")
    claimed = measured.get("value") if isinstance(measured, dict) else measured
    value, how = recompute(class_def.get("metric"), base=base)
    if value is None:
        return _fail(f"the claim could not be recomputed independently: {how}")
    tol = (class_def.get("metric") or {}).get("tolerance", 0) or 0
    try:
        ok = abs(float(value) - float(claimed)) <= float(tol)
    except Exception:
        ok = value == claimed
    if not ok:
        return _fail(f"the patch claimed {claimed!r} and {how} gives {value!r} "
                     f"(tolerance {tol}) — the claim does not survive recomputation")

    return PASS, (f"class {class_id!r} cleared its bar: {len(changed)} file(s) "
                  f"within allowed_paths, tests exit 0, measurement MEASURED "
                  f"({why}), {axis} moved, and {how} confirms {claimed!r}. "
                  f"THIS GRANTS NOTHING — nothing reads this decision.")


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    print("core/earning.py --selftest")
    pol = load_classes()
    print(f"  config/earning_classes.json : "
          f"{'LIVE' if CLASSES_FILE.exists() else 'INERT (missing)'}")
    print(f"  policy_version              : {pol.get('policy_version')}")
    print(f"  global_cap                  : "
          f"{'LOCKED' if pol.get('locked') else 'UNLOCKED'}")
    print(f"  classes                     : {list(pol.get('classes') or {})}")
    print(f"  signed classes              : "
          f"{[k for k, v in (pol.get('classes') or {}).items() if v.get('human_signed')]}")

    try:
        from execute_patches import _measurement_quality, _changed_axes  # noqa: F401
        print("  execute_patches evidence fns: LIVE")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  execute_patches evidence fns: INERT ({type(exc).__name__}: {exc})")

    # THE INERTNESS CHECK. If notary ever imports this, say so loudly.
    notary_src = (REPO / "core" / "notary.py").read_text(encoding="utf-8")
    wired = "earning" in notary_src
    print(f"  wired into core/notary.py   : "
          f"{'YES — THIS IS NO LONGER INERT' if wired else 'no (inert, as intended)'}")

    import tempfile
    with tempfile.TemporaryDirectory() as _tmp:
        d, why = verify(["data_providers/x.py"],
                        (pol.get("classes") or {}).get("example_axis_key_fix"),
                        {"exit_code": 0, "timed_out": False},
                        {"measured": {"value": 1}, "source": "",
                         "levels_before": {}, "levels_after": {}},
                        class_id="example_axis_key_fix", policy=pol,
                        revocations_path=Path(_tmp) / "revocations.jsonl")
    print(f"  a perfect candidate today   : {d} — {why[:90]}")

    ok = pol.get("locked") and not wired and d == FAIL
    print(f"  RESULT: {'OK (grants nothing)' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
