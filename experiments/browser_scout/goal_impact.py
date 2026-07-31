#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/browser_scout/goal_impact.py — turn a read page into a GOAL-IMPACT vector.

One measure for numbers AND meaning (Emil, 30 Jul 2026). Every observation becomes a
signed, weighted component relative to CORTEX's vision/goal: does it HELP or HARM, by how
much, on which goal-dimension, and why. An axis becomes a VECTOR of such components, not a
scalar. sign*magnitude feeds the statistics; the rationale/dimension feed the brain.
(See claude/GOAL_IMPACT_VECTOR_DESIGN_30JUL.md.)

Discipline: observation+evidence must be VERBATIM from the page (anti-fabrication). The
sign/magnitude/rationale are an explicit ASSESSMENT against the goal frame — not a verdict;
contested dimensions carry a counter-reading. Grounded facts, assessed impact, kept apart.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from autonomous_scout import _local, _json_from, _digits, need_class  # local model + helpers

# The reference frame — the sign/weight are RELATIVE to this, not an arbitrary scale.
GOAL_FRAME = (
    "CORTEX goal — a sustainable, dignified civilization: peace, human dignity, ecological "
    "sustainability within planetary limits, freedom of mind/spirit/body, truth and "
    "transparency, shared abundance, and food/water/health/education/home/energy for every "
    "person, life extended beyond one planet. POSITIVE = moves toward this. NEGATIVE = "
    "design failures: war, poverty, engineered scarcity, domination, deception, ecological "
    "overshoot, loss of dignity."
)

_DIMENSIONS = ["peace", "dignity", "sustainability", "freedom", "health", "truth",
               "prosperity", "knowledge", "resilience"]

# The goal frame is the ONE always-loaded canon (core/canon.py) — every judgment measured
# against the same center, dynamically (incl. consolidated invariants). Falls back to the
# local GOAL_FRAME string only if canon can't be imported.
REPO = HERE.parents[1]
DIM_WEIGHTS_FILE = REPO / "config" / "goal_dimension_weights.json"  # human-owned, versioned
try:
    sys.path.insert(0, str(REPO))
    from core.canon import as_frame as _canon_frame
except Exception:
    _canon_frame = None


def _frame() -> str:
    if _canon_frame:
        try:
            f = _canon_frame()
            if f:
                return f
        except Exception:
            pass
    return GOAL_FRAME


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _dim_weights():
    w = _load(DIM_WEIGHTS_FILE, {})
    return {d: float(w.get(d, 1.0)) for d in _DIMENSIONS}  # default 1.0 until Emil sets them


_STRUCTURAL = os.environ.get("CORTEX_STRUCTURAL_GUARD", "0") != "0"  # opt-in DNA-vs-DNA guard


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _loose(s):
    """_norm plus punctuation-blind — for LOCATING a span only, never for comparing
    numbers."""
    return re.sub(r"[^a-z0-9 ]", "", _norm(s))


def _located(ev, text) -> bool:
    """Is this span findable on the page? Strict first (whitespace + case), then a
    punctuation-blind retry.

    Measured 2026-07-31: qwen2.5:7b quoted a real sentence from the page and wrapped it
    in quotation marks. The span was 0.981 similar and matched the page exactly once
    punctuation was ignored, but the strict check compares a 40-char prefix, so one
    leading '"' shifted every character and a TRUE observation was rejected. That was
    2 of 12 extractions.

    This loosens WHERE a span may be found, never WHAT it must contain: GUARD 1/1c still
    compare digits against the evidence with _digits(), so a fabricated number cannot ride
    in on relaxed punctuation."""
    n_ev, n_tx = _norm(ev), _norm(text)
    if n_ev and n_ev[:40] in n_tx:
        return True
    l_ev = _loose(ev)
    return bool(l_ev) and l_ev[:40] in _loose(text)


# Page furniture that carries NUMBERS the model can mistake for data. The live case:
# Wikipedia renders "List of ongoing armed conflicts 33 languages" in its nav block, and
# qwen2.5:7b reported "33 ongoing armed conflicts" — 6 runs out of 6, deterministic,
# because the chrome is always there. The page is 60k chars and the model sees the first
# 6500, so the nav block was a large fraction of everything it saw.
#
# Stripped from the model's VIEW ONLY. Grounding is still checked against the untouched
# page, so this can never make a fabrication easier to pass — only harder to invent.
_CHROME = re.compile(
    r"toggle the table of contents"
    r"|jump to (?:content|navigation|search)"
    r"|\b\d{1,3}\s+languages\b"                     # the exact '33 languages' trap
    r"|create account\s*log\s?in"
    r"|personal tools|move to sidebar|add topic|edit source|view history"
    r"|skip to (?:main )?content"
    r"|accept all cookies?|manage (?:your )?preferences"
    r"|this website (?:uses|utilizes)[^.]{0,140}\."
    r"|all rights reserved|privacy policy|terms of (?:use|service)",
    re.IGNORECASE)


def _strip_chrome(text: str) -> str:
    """Drop navigation/consent furniture BEFORE the 6500-char truncation, so the budget
    is spent on the page's content instead of its menus."""
    return re.sub(r"\s+", " ", _CHROME.sub(" ", str(text))).strip()


def _decompose_claims(observation, evidence, text):
    """Break the observation into atomic claims, each with its OWN verbatim evidence span.
    Grounding is enforced in code (_claim_grounded), never trusted from the model."""
    prompt = (
        "Decompose the OBSERVATION into atomic factual claims. For EACH claim copy the exact "
        "phrase FROM THE PAGE that carries it (verbatim, no paraphrase).\n"
        'Reply ONLY JSON: {"claims":[{"text":"<one assertion>","entity":"<subject>",'
        '"predicate":"<rose|fell|is|threatens|...>","quantity":{"value":<number or null>,'
        '"unit":"<unit or empty>"},"polarity":"+|-|0","evidence_span":"<exact phrase from the '
        'page>"}]}\n'
        f"OBSERVATION: {observation}\nEVIDENCE HINT: {evidence}\n"
        f"PAGE TEXT (truncated):\n{_strip_chrome(text)[:6500]}")
    try:
        got = _json_from(_local(prompt, timeout=300, num_predict=700))
    except Exception as e:
        return {"_transport_error": f"{type(e).__name__}: {e}"}
    cl = got.get("claims")
    return cl if isinstance(cl, list) else []


def _claim_grounded(claim, text):
    """Per-claim generalisation of GUARD 1/1c: the claim's evidence_span must be verbatim in
    the page, and EVERY number in the claim (quantity or free text) must be in that span."""
    ev = str(claim.get("evidence_span", "")).strip()
    if not ev or not _located(ev, text):
        return False, "evidence_span not verbatim in page"
    q = (claim.get("quantity") or {}).get("value")
    if q is not None:
        d = _digits(q)
        if not d or d not in _digits(ev):
            return False, f"claim quantity {q} absent from its evidence_span"
    for m in re.findall(r"[0-9][0-9,\.]*", str(claim.get("text", ""))):
        dn = _digits(m)
        if dn and dn not in _digits(ev):
            return False, f"claim states number {m} absent from its evidence_span"
    return True, "ok"


def _refute_claim(claim, votes=1):
    """Adversarial entailment: a strict skeptic sees ONLY the claim's evidence_span and tries
    to REFUTE the claim (default to unsupported when uncertain). Survives iff a strict majority
    of votes could NOT refute it. Catches non-numeric fabrication the digit guard misses."""
    ev = str(claim.get("evidence_span", "")).strip()
    ctext = str(claim.get("text", "")).strip()
    prompt = (
        "You are a strict skeptic. Using ONLY the evidence below — nothing else, no outside "
        "knowledge — decide if it SUPPORTS the claim. If the evidence does not CLEARLY state "
        'it (wrong direction, missing number, different entity), answer supported=false.\n'
        'Reply ONLY JSON: {"supported": true|false, "why": "<short>"}\n'
        f'EVIDENCE: "{ev}"\nCLAIM: {ctext}')
    refutes = 0
    v = max(1, votes)
    for _ in range(v):
        try:
            g = _json_from(_local(prompt, timeout=300, num_predict=400))
        except Exception:
            refutes += 1
            continue
        if not bool(g.get("supported")):
            refutes += 1
    return refutes < (v // 2 + 1)   # survives unless a strict majority refuted


def structural_faithful(observation, evidence, text, max_claims=3, votes=1):
    """Gate: decompose -> per-claim grounding -> adversarial entailment. Returns
    (passed, survivors, broken). Faithful iff there is >=1 claim and NONE broke; broken names
    the exact claim + stage (grounding|entailment) so the trail is inspectable."""
    claims = _decompose_claims(observation, evidence, text)
    # A timeout / dead server is INFRASTRUCTURE, not a faithfulness verdict — surface it as
    # stage "transport" so it can never masquerade as "[none] no atomic claim survived".
    if isinstance(claims, dict) and claims.get("_transport_error"):
        return False, [], [{"claim": observation, "stage": "transport",
                            "why": claims["_transport_error"]}]
    claims = claims[:max_claims]
    survivors, broken = [], []
    for c in claims:
        ok, why = _claim_grounded(c, text)
        if not ok:
            broken.append({"claim": c.get("text"), "stage": "grounding", "why": why})
            continue
        if not _refute_claim(c, votes=votes):
            broken.append({"claim": c.get("text"), "stage": "entailment",
                           "why": "refuted from its own evidence_span"})
            continue
        survivors.append(c)
    passed = bool(claims) and not broken
    return passed, survivors, broken


_SIGN_GUARD = os.environ.get("CORTEX_SIGN_GUARD", "1") != "0"   # canon-anchored sign skeptic


def _looks_like_scale(ev: str, val) -> bool:
    """#40 'measurement, not furniture': True when the claimed value sits inside a monotonic
    run of >=5 numbers in the evidence span — the signature of axis/legend tick labels
    ('-14 -10 -6 -3 -1 -0.5 0 0.5 1 3 6 10 14'), not of a stated measurement. Deterministic.
    Live failure this catches: climatecentral legend read as 'today's anomaly -0.5'."""
    if val is None:
        return False
    try:
        nums = [float(m.group()) for m in re.finditer(r"-?\d+(?:\.\d+)?", ev.replace(",", ""))]
        v = float(str(val).replace(",", ""))
    except Exception:
        return False
    if len(nums) < 5:
        return False
    for i in range(len(nums)):
        run = [nums[i]]
        for j in range(i + 1, len(nums)):
            if nums[j] >= run[-1]:
                run.append(nums[j])
            else:
                break
        if len(run) >= 5 and any(abs(x - v) < 1e-9 for x in run):
            return True
    return False


def _sign_refuted(obs_text: str, ev: str, sign: str, dimension) -> tuple:
    """#39 canon-anchored sign skeptic: sees the CANON and tries to refute the PROPOSED SIGN
    (never the fact). Catches stably-wrong signs that vote-consistency cannot ('+1.0 for
    more warming', '+1.0 resilience for 254k deaths' — both live). FAIL-CLOSED for the
    assertion, open for the fact: any failure -> the sign is simply not asserted."""
    d = dimension or "the goal"
    prompt = (
        f"{_frame()}\n\n"
        f"An observation and its evidence:\nOBSERVATION: {obs_text}\nEVIDENCE: \"{ev}\"\n"
        f"A reader claims its impact on '{d}' relative to the GOAL above is "
        f"'{'POSITIVE (toward the goal)' if sign == '+' else 'NEGATIVE (away from the goal)'}'.\n"
        f"You are a strict skeptic: try to REFUTE that direction. If the direction is wrong "
        f"or not clearly justified by the observation, answer holds=false.\n"
        f'Reply ONLY JSON: {{"holds": true|false, "why": "<short>"}}')
    try:
        g = _json_from(_local(prompt, timeout=300, num_predict=200))
    except Exception as e:
        return True, f"sign check unavailable ({type(e).__name__}) — sign not asserted"
    if bool(g.get("holds")):
        return False, ""
    return True, str(g.get("why", "sign refuted against the goal frame"))[:200]


_RELEVANCE_GATE = os.environ.get("CORTEX_RELEVANCE_GATE", "1") != "0"  # is it even ABOUT the axis

# words that mark a figure as current rather than a yearly retrospective
_FRESH_MARKERS = ("today", "daily", "per day", "hourly", "real-time", "realtime",
                  "live", "current", "updated", "this week", "last 24 hours", "past 24",
                  "monthly", "per month", "as of", "latest")


def _cadence_match(ev: str, need: str):
    """Does the evidence's own cadence match what the SLOT asked for?

    Returns None when the need is not a daily class (nothing to check), else True/False.
    A False does NOT reject: the observation may be perfectly true and useful in the
    vector. It means the HUNGER STAYS DECLARED — an annual figure cannot fill a
    measurement_daily slot, and silently counting it as filled is how a daily slot ends up
    permanently satisfied by a yearly report (2026-07-31: a measurement_daily need was
    answered with 'global happiness index 2023')."""
    if need_class(need) not in ("measurement_daily", "event_daily"):
        return None
    low = str(ev).lower()
    if any(m in low for m in _FRESH_MARKERS):
        return True
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", str(ev))]
    if years and max(years) < datetime.now(timezone.utc).year:
        return False
    return True

# Unambiguous site-chrome phrases. Two or more must co-occur, so an article that merely
# mentions advertising or privacy is not caught — only the furniture itself.
_BOILERPLATE = (
    "cookie", "consent", "privacy policy", "terms of use", "terms of service",
    "newsletter", "subscribe", "sign up", "log in", "enable javascript",
    "targeted advertising", "personalization", "site functionality", "all rights reserved",
    "skip to main content", "accept all", "manage preferences", "your browser",
)


def _is_boilerplate(obs: str, ev: str) -> bool:
    """Deterministic 'this is the page, not the world': >=2 site-chrome phrases co-occurring.
    Live failure this catches: the first real drop's only surviving component was a cookie
    banner — verbatim, number-free, uncontested, so every anti-fabrication guard passed it."""
    blob = _norm(str(obs) + " " + str(ev))
    return sum(1 for k in _BOILERPLATE if k in blob) >= 2


def _relevance_refuted(obs_text: str, ev: str, axis: str, need: str) -> tuple:
    """Axis-anchored relevance skeptic: is the observation ABOUT what we set out to measure?
    Every other guard is anti-FABRICATION — they ask whether a claim is grounded, never
    whether it bears on the axis. FAIL-CLOSED for the whole observation (unlike the sign
    guard, which keeps the fact): an unverifiable relevance claim is precisely the
    zero-information commit this gate exists to prevent. The reason is always named."""
    prompt = (
        f"An observation was extracted from a web page while trying to measure:\n"
        f"AXIS: {axis}\nNEED: {need}\n\n"
        f"OBSERVATION: {obs_text}\nEVIDENCE: \"{ev}\"\n\n"
        f"Is this observation actually ABOUT that axis/need — a substantive fact or figure "
        f"bearing on it? Answer relevant=false if it is site furniture (cookie or consent "
        f"notices, navigation, subscription prompts, legal boilerplate), or if its subject "
        f"is simply something else.\n"
        f'Reply ONLY JSON: {{"relevant": true|false, "why": "<short>"}}')
    try:
        g = _json_from(_local(prompt, timeout=300, num_predict=200))
    except Exception as e:
        return True, f"relevance check unavailable ({type(e).__name__})"
    if bool(g.get("relevant")):
        return False, ""
    return True, str(g.get("why", "not about the axis/need"))[:200]


def extract_goal_impact(text: str, axis: str, need: str, url: str) -> tuple:
    """Read page text -> one goal-impact observation. Returns (obs, why). obs is None when
    nothing groundable is found (never fabricated)."""
    if not text:
        return None, "empty page text"
    prompt = (
        f"{_frame()}\n\n"
        f"You are measuring the axis '{axis}' (need: {need}) by reading a web page.\n"
        f"Find the SINGLE most relevant observation for it (a number or a stated fact), and "
        f"assess its impact RELATIVE TO THE GOAL ABOVE.\n"
        f"Reply ONLY JSON:\n"
        f'{{"observation": "<what the page states>", '
        f'"evidence": "<the exact phrase copied verbatim from the page, AT MOST 200 characters>", '
        f'"value": <number or null>, "unit": "<unit or empty>", '
        f'"sign": "+"|"-"|"0", "magnitude": <0.0-1.0>, '
        f'"dimension": "<one of: {", ".join(_DIMENSIONS)}>", '
        f'"rationale": "<why this sign and weight, referring to the goal>", '
        f'"contested": true|false, '
        f'"counterview": "<the strongest opposing reading — required if contested, else empty>"}}\n'
        f"If the page has nothing relevant, set observation to \"\" and value null.\n\n"
        f"PAGE TEXT (truncated):\n{_strip_chrome(text)[:6500]}")
    try:
        got = _json_from(_local(prompt, num_predict=900))
    except Exception as e:
        return None, f"model output unparseable — rejected ({type(e).__name__})"

    obs, ev = str(got.get("observation", "")).strip(), str(got.get("evidence", "")).strip()
    if not obs and got.get("value") is None:
        return None, "nothing relevant found"
    # GUARD 1 (grounding): the evidence must be a verbatim span of the page text; and if a
    # number is claimed, its digits must be in the evidence. Facts must be locatable.
    if not ev or not _located(ev, text):
        return None, "evidence not grounded verbatim in page — rejected"
    val = got.get("value")
    if val is not None:
        d = _digits(val)
        if not d or d not in _digits(ev):
            return None, "claimed number not present in the evidence — rejected"
    # GUARD 1c: any number stated in the free-text OBSERVATION must also be grounded in the
    # evidence span. Without this, the model can quote a contentless verbatim sentence (which
    # passes GUARD 1) while smuggling a FABRICATED count into the observation (e.g. "33
    # conflicts" on a page that says 48). value-only checking misses it because value is null.
    for _m in re.findall(r"[0-9][0-9,\.]*", obs):
        _dn = _digits(_m)
        if _dn and _dn not in _digits(ev):
            return None, f"observation states a number ({_m}) not present in the evidence — rejected"
    # GUARD 1d (#40, deterministic): a value that sits inside a numeric scale run is chart
    # furniture (axis/legend ticks), not a measurement.
    if _looks_like_scale(ev, val):
        return None, "value appears to be an axis/legend scale tick, not a measurement — rejected"
    # GUARD 1e (relevance, deterministic): site furniture is the page describing itself, not
    # a reading of the world. Free, so it runs before any model-based relevance call.
    if _RELEVANCE_GATE and _is_boilerplate(obs, ev):
        return None, "relevance: observation is site boilerplate, not a reading of the world — rejected"
    # GUARD 2 (assessment hygiene): a contested reading MUST carry a counter-view.
    sign = got.get("sign") if got.get("sign") in ("+", "-", "0") else "0"
    try:
        mag = max(0.0, min(1.0, float(got.get("magnitude", 0.0))))
    except Exception:
        mag = 0.0
    cv = str(got.get("counterview", "")).strip()
    if got.get("contested") and len(cv) < 15:
        return None, "contested impact without a counter-reading — rejected"

    # GUARD 5 (relevance, axis-anchored): the observation must be ABOUT the axis/need. Runs
    # before the sign guard so we never pay for a value-judgment on something off-topic, and
    # fails closed — an unverifiable relevance claim is rejected, never quietly committed.
    if _RELEVANCE_GATE:
        _irr, _rel_why = _relevance_refuted(obs, ev, axis, need)
        if _irr:
            return None, f"relevance: not about the axis/need — rejected ({_rel_why})"

    # GUARD 4 (#39, canon-anchored): the value-judgment (sign) must survive a skeptic who
    # reads it against the goal frame. Refuted or uncheckable -> the FACT is kept but the
    # sign is NOT asserted (sign 0), with the reason named. Runs before the (expensive)
    # structural guard so a bad sign fails fast.
    _sg_note = ""
    if _SIGN_GUARD and sign in ("+", "-"):
        _ref, _sg_note = _sign_refuted(obs, ev, sign, got.get("dimension"))
        if _ref:
            sign = "0"

    # GUARD 3 (structural faithfulness, opt-in via CORTEX_STRUCTURAL_GUARD): the observation
    # must decompose into atomic claims that each survive grounding + adversarial entailment.
    _claims = None
    if _STRUCTURAL:
        _passed, _survivors, _broken = structural_faithful(obs, ev, text)
        if not _passed:
            _b = _broken[0] if _broken else {"stage": "none", "why": "no atomic claim survived",
                                             "claim": obs}
            return None, (f"structural faithfulness [{_b.get('stage')}]: {_b.get('why')} "
                          f"— claim: {_b.get('claim')}")
        _claims = _survivors

    return {
        "axis": axis, "url": url,
        "observation": obs, "evidence": ev[:200],
        "value": val, "unit": str(got.get("unit", "")).strip(),
        "sign": sign, "magnitude": round(mag, 3),
        "signed_scalar": round((1 if sign == "+" else -1 if sign == "-" else 0) * mag, 3),
        "dimension": got.get("dimension"),
        "rationale": str(got.get("rationale", "")).strip()[:300],
        "contested": bool(got.get("contested", False)),
        "counterview": cv[:300],
        "sign_guard": _sg_note,
        # does this observation's cadence match the slot class the need asked for?
        # None = not a daily need; False = kept, but the slot stays HUNGRY.
        "cadence_match": _cadence_match(ev, need),
        "claims": _claims,
    }, "ok"


def compose_vector(observations: list) -> dict:
    """Aggregate goal-impact components into the axis vector the system consumes — WITHOUT
    hiding the disagreement (Emil's rule: the aggregate never discards the components, and
    where sources conflict, the conflict is itself signal). Cross-dimension overall uses the
    HUMAN dimension weights, not model-invented ones."""
    obs = [o for o in observations if o]
    weights = _dim_weights()
    by_dim = {}
    signs_by_dim = {}
    for o in obs:
        d = o.get("dimension") or "unspecified"
        by_dim[d] = round(by_dim.get(d, 0.0) + o.get("signed_scalar", 0.0), 3)
        signs_by_dim.setdefault(d, set()).add(o.get("sign", "0"))
    # DISAGREEMENT is signal: same dimension, both + and - present -> flag, don't average away
    disagreements = [{"dimension": d, "signs": sorted(s),
                      "sources": [o.get("url") for o in obs if o.get("dimension") == d]}
                     for d, s in signs_by_dim.items() if "+" in s and "-" in s]
    overall_weighted = round(sum(o.get("signed_scalar", 0.0) * weights.get(o.get("dimension"), 1.0)
                                 for o in obs), 3)
    return {"n": len(obs),
            "overall_signed_weighted": overall_weighted,
            "by_dimension": by_dim,
            "disagreements": disagreements,     # kept, never averaged away
            "dim_weights_used": weights,
            "components": obs}                   # full detail always preserved


def extract_calibrated(text: str, axis: str, need: str, url: str, votes: int = 2) -> tuple:
    """Calibrate the SIGN/WEIGHT (the model's value-judgment, the soft dangerous part).
    Run the impact read `votes` times; the FACT is already grounded, but the impact is only
    trusted if the sign is CONSISTENT across votes. Disagreeing votes -> the observation is
    kept but marked impact_unstable (sign 0, low confidence) rather than asserting a
    confident vector we didn't actually verify. Verification over assertion, for the weight."""
    reads = []
    last_why = "no read attempted"
    for _ in range(max(1, votes)):
        o, why = extract_goal_impact(text, axis, need, url)
        if o:
            reads.append(o)
        else:
            last_why = why          # keep the REASON — a dead server must never look
    if not reads:                   # like a clean faithfulness rejection
        return None, f"nothing groundable — last: {last_why}"
    signs = {o["sign"] for o in reads}
    base = reads[0]
    if len(signs) == 1:                          # consistent judgment -> trust it
        mags = sorted(o["magnitude"] for o in reads)
        base["magnitude"] = mags[len(mags) // 2]  # median
        base["signed_scalar"] = round((1 if base["sign"] == "+" else -1 if base["sign"] == "-" else 0)
                                       * base["magnitude"], 3)
        base["impact_confidence"] = "calibrated" if len(reads) > 1 else "single"
        return base, "ok"
    # signs disagree across votes -> do NOT assert an impact we can't verify
    base["sign"], base["signed_scalar"] = "0", 0.0
    base["impact_confidence"] = "unstable"
    base["impact_note"] = f"sign varied across {len(reads)} reads ({sorted(signs)}) — impact not trusted"
    return base, "ok:unstable_impact"
