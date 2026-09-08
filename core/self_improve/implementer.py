#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/self_improve/implementer.py — THE SPECIALIST WRITES CODE, FROM A SPEC IT DID NOT WRITE.

EXPERIMENTAL, on branch experimental/self-mod. Not imported by
fast_cycle_runner.py, not in the cycle. It APPLIES NOTHING: it returns a unified
diff as text and never touches the working tree, git, or any tracked file.

WHICH MODEL, AND WHY THIS ONE
------------------------------
core/groq_backend.call_groq — the cloud ladder (Groq -> OpenRouter -> Gemini),
the same entry agents/core/self_modifier.py:486 already uses. Measured
2026-08-04: the cloud model closes the write -> test -> fix loop 3 times out of
3; the local model closes it 0 out of 3, with identical retries at any
temperature. So the local brain writes the spec (requirer.py) and this writes the
code. Neither is asked to do the other's job.

The requirer refuses to reach for the cloud. This one refuses to reach for the
local model, for the same reason and in the same direction: a silent swap would
make the output look fine and end the experiment without saying so.

THE ALLOWLIST IS ENFORCED HERE, BEFORE THE DIFF LEAVES
-------------------------------------------------------
The spec carries allowed_paths. A diff touching anything outside them is REFUSED
by this module — not passed downstream for someone else to catch. core/earning.py
checks paths too, and that is not a duplicate: earning is the judge and can only
grade what it is handed, while this is the producer and must not hand over work
it already knows is out of scope. A producer that emits out-of-scope work and
relies on the judge has moved its own failure into someone else's budget.

FORBIDDEN FALLBACKS, NAMED
  * do NOT drop the offending hunks and return the rest. A partial diff is a
    different change from the one the model proposed, and nothing downstream
    would know. PatchOutOfScope is raised whole.
  * do NOT widen allowed_paths to fit the diff.
  * do NOT fall back to the local model when the ladder is cooling — raise.
  * do NOT apply, stage, or write the patch anywhere. This returns text.

    venv\\Scripts\\python.exe core/self_improve/implementer.py --selftest
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Same shape as core/earning.ALWAYS_FORBIDDEN, and deliberately restated at the
# PRODUCING end: a patch that edits the verifier, the policy or the rules of
# passage must never even be generated, let alone judged.
NEVER_TOUCH = (
    "core/earning.py",
    "config/earning_classes.json",
    "config/passage_rules.json",
    "core/notary.py",
    "config/step_inputs.json",
    "test/test_earning_verifier.py",
    "test/test_passage_rules.py",
    "test/test_irreversible_boundary_holds.py",
)

_DIFF_PATHS = re.compile(r"^(?:\+\+\+|---)\s+(?:[ab]/)?(\S+)", re.M)
# A HUNK HEADER NEEDS ITS LINE RANGES (corrected 8 Sep 2026).
#
# This was r"^@@ ", I relaxed it to r"^@@" in ceca31f believing it had
# falsely refused a good patch, and that was a MISDIAGNOSIS. Measured with
# git itself:
#
#   a bare   @@               -> error: No valid patches in input
#   a ranged @@ -1,1 +1,1 @@  -> error: patch does not apply
#
# The first cannot be PARSED; the second parses and fails later on content.
# So a bare `@@` really is not a unified diff, the original check was right
# in outcome, and relaxing it made this module accept patches git cannot
# read. Restored — but the REASON string was the part that was actually
# wrong, and it is fixed below: it used to say "no unified-diff hunk (@@)"
# about output that plainly contained four of them, which sent me chasing
# the wrong defect for a full commit.
_HUNK = re.compile(r"^@@ ", re.M)


class PatchOutOfScope(Exception):
    """The diff touches a path the spec does not allow. Refused whole."""


class PatchUnusable(Exception):
    """The model returned something that is not a unified diff."""


def _norm(p: str) -> str:
    return str(p).replace("\\", "/").lstrip("./")


def _under(path: str, prefix: str) -> bool:
    path, prefix = _norm(path), _norm(prefix)
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


def changed_files(diff: str) -> list:
    """Repo-relative paths a unified diff touches, from its ---/+++ headers.

    /dev/null is dropped: it is how a diff spells "this file did not exist" and
    is not a path anyone can touch.
    """
    out = []
    for m in _DIFF_PATHS.finditer(diff or ""):
        p = _norm(m.group(1))
        if p in ("dev/null", "/dev/null") or p.endswith("/dev/null"):
            continue
        if p not in out:
            out.append(p)
    return out


def enforce_scope(diff: str, allowed_paths) -> list:
    """Every touched path inside allowed_paths and outside NEVER_TOUCH, or raise.

    Returns the touched paths so the caller does not parse the diff twice.
    """
    if not _HUNK.search(diff or ""):
        raise PatchUnusable(
            "no hunk header with line ranges. A unified diff needs "
            "'@@ -old,count +new,count @@'; a bare '@@' is not parseable — git "
            "answers 'No valid patches in input'. If the output DOES contain "
            "'@@' markers, they are missing their ranges: that is the model's "
            "format, not the absence of a patch.")

    touched = changed_files(diff)
    if not touched:
        raise PatchUnusable("the diff names no file")

    for path in touched:
        for prefix in NEVER_TOUCH:
            if _under(path, prefix):
                raise PatchOutOfScope(
                    f"{path} is in NEVER_TOUCH ({prefix}) — the verifier, the "
                    f"policy, the rules of passage and the tests that pin them "
                    f"may not be edited by a generated patch, whatever the spec "
                    f"allows.")

    allowed = list(allowed_paths or [])
    if not allowed:
        raise PatchOutOfScope("the spec allows no path at all")

    # ── THE PATH MUST BE REAL, NOT MERELY ALLOWED (8 Sep 2026) ────────────
    # This checked the diff against the SPEC and nothing else. When both were
    # hallucinated they AGREED, and a patch to src/ai/self_observer.py — a file
    # that does not exist — passed the scope gate cleanly. Matching an invented
    # allowlist is not scope; it is two errors cancelling.
    #
    # A diff may CREATE a file (its --- side is /dev/null, already dropped by
    # changed_files), so a path is acceptable if it exists OR if its parent
    # directory does. Both are checked against the real repo.
    for path in touched:
        target = REPO / path
        if not target.exists() and not target.parent.is_dir():
            raise PatchOutOfScope(
                f"{path} does not exist in this repo, and neither does its "
                f"parent directory. A patch against a file that is not there "
                f"cannot be applied or judged — matching the spec's allowlist "
                f"proves only that the spec was wrong in the same way.")

    for path in touched:
        if not any(_under(path, a) for a in allowed):
            raise PatchOutOfScope(
                f"{path} is outside the spec's allowed_paths {allowed}. The "
                f"patch is refused WHOLE: dropping the offending hunk would "
                f"hand downstream a different change from the one the model "
                f"proposed, and nothing would know.")
    return touched


def build_prompt(spec: dict, context: str = "") -> str:
    allowed = ", ".join(spec.get("allowed_paths") or [])
    return (
        "You are the CORTEX++ implementer. You are handed a SPECIFICATION you "
        "did not write, and you return ONE unified diff.\n\n"
        f"PROBLEM: {spec.get('problem','')}\n"
        f"ROOT CAUSE: {spec.get('root_cause','')}\n"
        f"DESIRED CHANGE: {spec.get('desired_change','')}\n"
        f"SUCCESS METRIC: {spec.get('success_metric','')}\n"
        f"GOAL AXIS: {spec.get('goal_axis','')}\n\n"
        f"YOU MAY ONLY TOUCH: {allowed}\n"
        "A diff touching anything else is REFUSED WHOLE before it leaves this "
        "step — not trimmed, not partially applied. Staying in scope is part of "
        "the work, not a formality.\n\n"
        f"NEVER TOUCH, whatever the spec says: {', '.join(NEVER_TOUCH)}\n\n"
        + (f"CONTEXT:\n{context[:2000]}\n\n" if context else "")
        + "Return ONLY a unified diff with --- / +++ headers and @@ hunks. "
          "No prose, no markdown fences, no explanation."
    )


def _ladder(prompt: str, max_tokens: int = 1400) -> str:
    """The CLOUD ladder, and only the cloud ladder.

    NO LOCAL FALLBACK. core.groq_backend.call_groq already falls back Groq ->
    OpenRouter -> Gemini internally; if all three are cooling it raises
    AllBackendsFailedError and that is the honest outcome. Reaching for the local
    model here would silently put the 0/3 model back on the job this module
    exists to take away from it.
    """
    from core.groq_backend import call_groq
    return call_groq(prompt, max_tokens=max_tokens)


def _strip_fences(text: str) -> str:
    """Models fence diffs even when told not to. Unwrapping a fence is not the
    forbidden 'clean it up': the diff inside is unchanged, and no hunk is
    dropped."""
    t = (text or "").strip()
    m = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", t, re.S)
    out = m.group(1).strip() if m else t
    # A UNIFIED DIFF MUST END WITH A NEWLINE, and .strip() had just eaten it.
    # git's answer to a patch whose last line is unterminated is
    #     error: corrupt patch at line N
    # which reads like the model produced garbage. It had not: this function
    # broke a valid patch on its way through. Found on 2026-09-08 by the
    # git-apply net refusing a fixture diff that applied perfectly when tested
    # directly — the net caught a defect in the code that feeds it.
    return (out + "\n") if out and not out.endswith("\n") else out


def implement(spec: dict, model=None, context: str = "") -> dict:
    """SPEC -> {diff, changed_files, spec}. Raises rather than degrading.

    Applies nothing. The returned diff is text; whether it is ever applied is a
    decision made somewhere else, by a human.
    """
    if not isinstance(spec, dict):
        raise PatchUnusable(f"spec is {type(spec).__name__}, not an object")
    for field in ("desired_change", "allowed_paths"):
        if not spec.get(field):
            raise PatchUnusable(f"the spec has no {field}")

    raw = (model or _ladder)(build_prompt(spec, context))
    diff = _strip_fences(raw)
    touched = enforce_scope(diff, spec.get("allowed_paths"))

    return {"diff": diff, "changed_files": touched, "spec": spec,
            "_source": "implementer/cloud_ladder"}


def _selftest() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    print("core/self_improve/implementer.py --selftest")
    try:
        from core.groq_backend import call_groq  # noqa: F401
        print("  cloud ladder entry : LIVE (core.groq_backend.call_groq)")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  cloud ladder entry : INERT ({type(exc).__name__}: {exc})")
        return 1

    spec = {"problem": "p", "root_cause": "r", "desired_change": "d",
            "success_metric": "m", "goal_axis": "WATER_REVIEW",
            "allowed_paths": ["data_providers/"]}

    in_scope = ("--- a/data_providers/water_provider.py\n"
                "+++ b/data_providers/water_provider.py\n"
                "@@ -1,2 +1,3 @@\n line\n+added\n")
    out_of_scope = ("--- a/core/notary.py\n+++ b/core/notary.py\n"
                    "@@ -1,2 +1,3 @@\n line\n+added\n")

    ok = True
    try:
        res = implement(spec, model=lambda p: in_scope)
        print(f"  an in-scope diff   : accepted, touches {res['changed_files']}")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  an in-scope diff   : WRONGLY REFUSED ({exc})")
        ok = False

    for label, bad in (("an out-of-scope diff", out_of_scope),
                       ("not a diff at all", "I would change the provider.")):
        try:
            implement(spec, model=lambda p, b=bad: b)
            print(f"  {label:<21}: NOT REFUSED — the scope check is open")
            ok = False
        except (PatchOutOfScope, PatchUnusable):
            print(f"  {label:<21}: refused")

    print("  applies nothing    : returns text; no write, no git, no apply")
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
