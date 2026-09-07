#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MARKET BET — next-session direction for SPY / GLD / UUP, against a momentum baseline.

PREDICTION ONLY (§VI). Nothing here places, sizes, or recommends a trade. It records a
direction and a stated reason, and reality grades the direction.

WHY MARKETS. Earthquakes were an honest but useless null: the count is close to noise
around its own mean, so a rationale about it cannot be checked against anything. A
market direction can be wrong for a NAMED reason - "CPI surprise +0.3, BLS 12 Sep" is a
fact somebody can look up, and a bet that cites it can be diagnosed rather than only
counted.

THE RATIONALE IS SEALED AND NEVER REWARDED. Only the graded direction decides whether a
bet was right. A rationale that earned credit is one the model learns to write well
rather than to mean.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.market_daily import ASSETS, INDICATORS  # noqa: E402
from tools.first_bet import MODEL_PIN, generate_completions  # noqa: E402

N_COMPLETIONS = 8
TEMPERATURE = 0.7
LEDGER = REPO / "memory" / "first_bet"

DIRECTIONS = ("UP", "DOWN")
BUCKETS = ("MACRO", "GEOPOL", "FLOW", "SECTOR")


class DryRunUnusable(RuntimeError):
    """A --dry-run was asked for and cannot be honoured. RAISED, NEVER DEGRADED.

    THIS EXISTS BECAUSE THE FALLBACK FIRED ON ME. The runner used to read
    `if "completions" in dry: ... else: generate_completions(...)`, so a dry-run file
    that was missing, malformed, or had been clobbered SILENTLY BECAME A LIVE MODEL
    RUN. I hit it by naming a fixture r52_dry.json and its output R52_DRY.json - the
    same file on a case-insensitive filesystem - so the sealed bet overwrote its own
    input, and the next "dry" run called qwen2.5:3b for real.

    "--dry-run" is a promise that no model is touched. A promise with a silent fallback
    is not a promise, and this module already says exactly that about the news path:
    REFUSE LOUD, NEVER FALL BACK.
    """

PROMPT = """You are forecasting the next-session direction of one exchange-traded fund.
This is a PREDICTION ONLY. No trade will be placed on it.

ASSET: {sym}
Last close ({close_date}): {close}
Recent closes (oldest to newest): {recent}

Answer with EXACTLY these three lines and nothing else:

DIRECTION: UP or DOWN
DEADLINE: {deadline}
RATIONALE: DRIVER [one of MACRO|GEOPOL|FLOW|SECTOR] | SIGNAL [a NAMED EXTERNAL FACT with a date and a source] | LOGIC [one sentence]

The SIGNAL must be a fact somebody else could look up - an event, a release, a printed
number - with a date and where it came from. For example:
  RATIONALE: DRIVER MACRO | SIGNAL CPI surprise +0.3, BLS 12 Sep | LOGIC a hotter print lifts real yields and weighs on equities
It must NOT be interpretation. "Sentiment feels weak" and "momentum is negative" are not
signals; they are opinions about the price you were just shown.
"""

GROUNDED_PROMPT = """You are forecasting the next-session direction of one exchange-traded fund.
This is a PREDICTION ONLY. No trade will be placed on it.

ASSET: {sym}
Last close ({close_date}): {close}

RETRIEVED NEWS — these are the ONLY facts you may cite. You have no others.
Every sentence is NUMBERED. Each source names what kind of source it is. That is not a
trust score and it is not there for you to judge credibility: the SOURCE TYPE IS PART OF
THE SIGNAL. A wire report, a government release and a broker's commentary move a price
differently.
{evidence}

Answer with EXACTLY these five lines, IN THIS ORDER, and nothing else:

DEADLINE: {deadline}
SIGNAL: [the NUMBER of one sentence above]
DRIVER: one of MACRO, GEOPOL, FLOW, SECTOR
LOGIC: [ONE sentence — the mechanism by which that fact moves the price]
DIRECTION: UP or DOWN

THE ORDER IS THE POINT, AND IT IS NOT NEGOTIABLE. Pick the fact, say what kind of force
it is, state the mechanism — and only then say which way. DIRECTION IS LAST because it
is the CONCLUSION of the three lines above it. An answer that states the direction first
and explains it afterwards is refused, because a reason written to fit a direction
already chosen cannot be told apart from a guess with a story attached.

PICK THE FACT BEFORE YOU LABEL IT. SIGNAL comes first so that you choose a sentence on
what it says, not on which sentences fit a category you have already named.

DRIVER CLASSIFIES THE SENTENCE YOU JUST PICKED. One of four words, and it says what KIND
of force this is, not which way it pushes.

SIGNAL IS A NUMBER, NOT TEXT. Do not retype the sentence, do not shorten it, do not join
two of them together. Give its number and the sentence is used exactly as printed above.
You may give more than one number, separated by commas. A number that is not in the list
above is refused, and so is anything in the SIGNAL field that is not a number.

LOGIC IS ONE SENTENCE IN YOUR OWN WORDS, and it must not be empty. Say the channel —
yields, flows, positioning, supply — by which the fact you picked reaches the price.

WORKED EXAMPLE. Suppose the evidence block had ended with:

SOURCE A — reuters.com, class independent (wire), published 2026-09-05
  [1] US inflation ticks up
  [2] CPI rose 0.3% in August, the Bureau of Labor Statistics said on Friday.
  [3] Treasury yields climbed across the curve after the release.

A correct answer is:

DEADLINE: {deadline}
SIGNAL: 2
DRIVER: MACRO
LOGIC: a hotter print lifts real yields, which discount equity cash flows harder.
DIRECTION: DOWN

Note what it does NOT do. It does not write the sentence out — it writes the number. And
it does not name a direction until the last line, after the reasoning that produces it.
"""

# ── R50: DIRECTION IS GENERATED LAST ────────────────────────────────────────
# The old grounded contract emitted DIRECTION on the FIRST line and the reasoning after
# it. A language model writes left to right, so every reasoning token was conditioned on
# a direction the model had ALREADY COMMITTED TO. The rationale could therefore only ever
# be post-hoc - not a reason for the answer, but a story about it.
#
# It showed. All eight live R48 candidates said UP, and the one that sealed cited "the
# next stock market downturn is only a matter of time" as its support. The polarity flag
# built in R49 piece 4 catches that after the fact; this changes the thing that produces
# it. The worked example was teaching it too - it also put DIRECTION first.
#
# The new order is DRIVER -> SIGNAL -> LOGIC -> DIRECTION, and it is ENFORCED rather
# than requested: an answer that names the direction before the reasoning is refused as
# the wrong contract. DEADLINE is a constant the model echoes back rather than a
# judgement, so it is positionally free - except that nothing may follow DIRECTION,
# which has to be the last thing generated for any of this to mean anything.
#
# THE FIELD SET IS MINIMAL ON PURPOSE, and this is the correction R51 makes to R50.
# R50 shipped EVENT -> RELEVANCE -> MECHANISM -> DIRECTION, which put the direction last
# but bought that with TWO free-text fields. Every free-text field a 3B is asked to fill
# is another surface it can confabulate on, and RELEVANCE in particular invited a
# plausible-sounding paragraph about why an asset matters - the exact register the whole
# grounding effort exists to remove. The set below has exactly ONE free-text field:
#
#   DRIVER     a closed four-word vocabulary       near-zero surface
#   SIGNAL     a segment index                     zero surface, verbatim by construction
#   LOGIC      one sentence                        ONE surface
#   DIRECTION  binary, and last                    no surface
#
# ── R52: WHAT THIS CONTRACT ACTUALLY BUYS ───────────────────────────────────
# STATED PLAINLY SO NOBODY OVER-READS IT, THIS COMMENT INCLUDED.
#
# Putting DIRECTION last buys THE SYNTAX OF DERIVATION, NOT CAUSATION. The model can
# still settle on UP internally and then write a LOGIC sentence that encodes it. "The
# index has recovered from every prior downturn" is a verdict wearing a mechanism's
# clothes, and no amount of field ordering can see inside it. What the order changes is
# narrower and worth exactly what it is: the verdict is no longer FORCED to come first,
# and the reasoning tokens are no longer conditioned on an answer already emitted.
#
# THE POLARITY FLAG IS WHAT MAKES THE CONTRADICTION DETECTABLE; THE ORDER JUST MAKES IT
# CATCHABLE. A bet whose cited span reads negative and whose direction is UP shows up in
# the record either way. Neither mechanism proves the reasoning caused the answer. They
# make an inconsistency BETWEEN them observable, and that is the most an offline audit
# can honestly claim. Anything stronger would be this module telling itself a story.
#
# SIGNAL IS SELECTED FIRST, BEFORE THE BUCKET - and the reason is a claim R51 made too
# strongly. R51 put DRIVER first, arguing the buckets carry no direction. What the test
# actually checks is that the four bucket WORDS are lexically neutral in OUR OWN polarity
# lexicon and are not in a hand-written list of directional words. That is a claim about
# vocabulary, not about behaviour. Whether naming "MACRO" first makes macro-flavoured
# spans look more relevant, or whether P(UP | FLOW) skews, was never measured.
#
# So the span is chosen FIRST, out of the numbered table, before any label has framed
# what counts as relevant - and DRIVER becomes a CLASSIFICATION OF THE SPAN ALREADY
# CHOSEN rather than a lens for choosing it. The skew itself is now measured rather than
# asserted: see bucket_direction_table() below, which is a MONITOR, not a gate.
GROUNDED_CONTRACT = ("SIGNAL", "DRIVER", "LOGIC", "DIRECTION")
_GROUNDED_LINE_RE = re.compile(
    r"^[\s*>-]*(DRIVER|SIGNAL|LOGIC|DIRECTION|DEADLINE)\s*:\s*(.*)$", re.I)


def check_field_order(seen) -> str | None:
    """None when the answer follows the contract, else a NAMED problem.

    Case is not reasoning, so it is not checked. ORDER is the whole point, so it is.
    """
    dupes = sorted({f for f in seen if seen.count(f) > 1})
    if dupes:
        return (f"{' and '.join(dupes)} is given more than once, so which answer the "
                f"model actually committed to cannot be decided without guessing.")
    order = [f for f in seen if f in GROUNDED_CONTRACT]
    missing = [f for f in GROUNDED_CONTRACT if f not in order]
    if missing:
        return (f"the answer names no {' or '.join(missing)}. The contract is "
                f"{' -> '.join(GROUNDED_CONTRACT)}, and a missing field is a step of "
                f"the reasoning that was never done.")
    if order[0] == "DIRECTION":
        return ("DIRECTION comes FIRST, before any reasoning. That is the contract this "
                "round exists to replace: a direction committed to before the reasoning "
                "makes every line after it a justification rather than a derivation, "
                "and the two cannot be told apart once written down.")
    if order != list(GROUNDED_CONTRACT):
        return (f"the fields are in the order {' -> '.join(order)}, not "
                f"{' -> '.join(GROUNDED_CONTRACT)}. The order IS the contract, because "
                f"it is what conditions the direction on the reasoning.")
    if seen[-1] != "DIRECTION":
        return (f"{seen[-1]} is generated AFTER DIRECTION. DIRECTION has to be the last "
                f"thing written or it is not the conclusion of anything.")
    return None


def parse_grounded_completion(raw: str) -> dict:
    """The grounded contract, parsed IN THE ORDER IT WAS GENERATED.

    `field_order` is kept because the order is the property being bought, and a record
    that does not show it cannot be checked later.
    """
    out = {"raw": raw, "deadline": None, "driver": None, "signal": None,
           "logic": None, "direction": None,
           "field_order": [], "order_problem": None}
    seen = []
    for line in str(raw).splitlines():
        m = _GROUNDED_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1).upper(), m.group(2).strip()
        seen.append(key)
        if out[key.lower()] is None:
            out[key.lower()] = val.upper().strip(" .*") if key == "DIRECTION" else val
    out["field_order"] = list(seen)
    out["order_problem"] = check_field_order(seen) if seen else (
        "the answer names none of the contract's fields.")
    return out


_DATE_RE = re.compile(
    r"\b(\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})\b", re.I)
_SOURCE_RE = re.compile(
    r"\b(BLS|BEA|Fed|FOMC|ECB|BOJ|OPEC|EIA|Treasury|Reuters|Bloomberg|WSJ|FT|"
    r"CPI|PPI|NFP|ISM|PMI|GDP|Census|IMF|OECD|SEC)\b")


# US EQUITY MARKET HOLIDAYS 2026 (NYSE/NYSE Arca calendar). A weekday rule alone is
# NOT enough, and the dry run proved it: Friday 2026-09-04 + one weekday gave
# 2026-09-07, which is LABOR DAY and has no session at all. A bet whose deadline falls
# on a closed market cannot be graded, and nothing in the price data says "closed" -
# a missing bar looks exactly like a bar that has not arrived yet.
#
# This list is a MAINTENANCE BURDEN and is written down as one: it is correct for 2026
# and will be wrong for 2027 unless somebody updates it. next_session() refuses rather
# than guesses once it runs past the end of the declared year.
US_MARKET_HOLIDAYS_2026 = frozenset({
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # Martin Luther King Jr. Day
    "2026-02-16",  # Washington's Birthday
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
})


# ── B3: the machine guard, ported from first_bet.py:369-383 ─────────────────
# tools/first_bet.py refuses to generate while the 03:04 cycle holds the GPU, and its
# own comment says why: "this is how A3 died four times on 6 September". THAT GUARD WAS
# NEVER REACHED FROM HERE. market_bet.py imports only MODEL_PIN and
# generate_completions, never first_bet.main(), so the grounded bet - the one that
# actually gets sealed - could start eight generations on top of a running cycle.
#
# A guard that exists in a sibling script and not on the path that runs is a guard
# nobody has.
GPU_BUSY_MIB = 600
CYCLE_LOCK = REPO / "memory" / "cycle.lock"


def gpu_used_mib():
    """MiB in use, or None when nvidia-smi says nothing.

    NONE IS NOT ZERO. An unknown occupancy is a refusal, not a green light — the same
    rule first_bet.py states, and the reason it is stated twice is that getting it
    backwards turns a safety check into a rubber stamp.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return int(out.splitlines()[0].strip())
    except Exception:                                              # noqa: BLE001
        return None


def machine_is_free(lock_path: Path | None = None, probe=None) -> tuple:
    """(True, note) when it is safe to generate, else (False, the refusal).

    Checked BEFORE any completion is requested. `probe` and `lock_path` are injectable
    so the tests never need a GPU or a real lock.
    """
    lock = lock_path if lock_path is not None else CYCLE_LOCK
    if lock.exists():
        return False, (f"REFUSED: {lock} is present — a cycle is running and owns the "
                       f"GPU until it seals. Generating now competes with it, which is "
                       f"how A3 died four times on 6 September. Wait, then re-run.")
    used = (probe or gpu_used_mib)()
    if used is None:
        return False, ("REFUSED: nvidia-smi gave nothing, so GPU occupancy is UNKNOWN. "
                       "Refusing rather than guessing — an unknown is not a zero.")
    if used > GPU_BUSY_MIB:
        return False, (f"REFUSED: {used} MiB already held on the GPU (limit "
                       f"{GPU_BUSY_MIB}). Something else is using the card.")
    return True, f"GPU free ({used} MiB), no cycle lock."


class BaselineUnavailable(RuntimeError):
    """Fresh prices could not be had. REFUSED, never substituted with a stale file.

    The stale file is exactly what this replaces, so falling back to it on a fetch
    failure would reinstate the bug under a different name.
    """


def compute_baseline(fetcher=None) -> dict:
    """The 20-trading-day momentum baseline, COMPUTED NOW FROM FRESH PRICES.

    IT USED TO BE READ FROM BASELINE_2026-09-07_markets.json, a file whose SPY last
    close is 2026-09-04. Every bet after the 7th would have been graded against a stale
    close and compared to a momentum sign computed from a window that had already moved.
    The baseline is the null the bet must beat; a null from last week is not a null.

    `fetcher(sym) -> bars` is injectable so the tests never touch the network.
    """
    import core.market_daily as md

    fetch = fetcher or (lambda sym: md.parse_chart(md.fetch_chart(sym)))
    baseline, closes = {}, {}
    for sym in ASSETS:
        try:
            bars = fetch(sym)
            baseline[sym] = md.momentum_sign(bars)
            d, px = md.last_close(bars)
            closes[sym] = {"date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                           "adjclose": px}
        except Exception as exc:                                   # noqa: BLE001
            raise BaselineUnavailable(
                f"{sym}: could not compute a fresh baseline — {type(exc).__name__}: "
                f"{exc}. REFUSED rather than falling back to a sealed file from an "
                f"earlier day: a stale null is worse than no bet, because it looks "
                f"exactly like a fresh one in the record.") from exc

    return {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "method": "20-trading-day momentum sign",
            "note": ("computed at bet time from fresh prices, sealed with the bet; "
                     "the null the bet must beat"),
            "computed_at_bet_time": True,
            "baseline": baseline, "last_close": closes}


def seal_path(day: date | None = None, ledger: Path | None = None) -> Path:
    """Where TODAY's grounded bet is sealed. One file per day, derived, never hardcoded.

    THE OLD TARGET WAS THE LITERAL STRING "BET_2026-09-07_markets_grounded.json", and
    that file has existed since 3e60956. So from 8 September onward a bare --live either
    died on FileExistsError, or, with --allow-overwrite, DESTROYED THE SEALED R48 BET -
    the only live grounded bet on record and the thing tomorrow's grading reads.

    A sealed prediction that a later run can silently overwrite is not sealed. The date
    in the name is what makes yesterday's bet safe from tonight's run.
    """
    d = day or date.today()
    return (ledger or LEDGER) / f"BET_{d.isoformat()}_markets_grounded.json"


def same_file(a, b) -> bool:
    """Do two paths name one file? CASE-INSENSITIVELY, and via the real path.

    os.path.samefile is the correct answer but it raises when the target does not exist
    yet, which is the normal case for --out. So: samefile when both exist, and a
    normalised-case comparison of the resolved paths otherwise.

    THIS IS NOT PARANOIA, IT IS A MEASURED FAILURE. 'r52_dry.json' and 'R52_DRY.json'
    are one file on Windows. The seal overwrote the fixture it had just read.
    """
    import os

    pa, pb = Path(a), Path(b)
    try:
        if pa.exists() and pb.exists():
            return os.path.samefile(pa, pb)
    except OSError:
        pass
    return (os.path.normcase(str(pa.resolve()))
            == os.path.normcase(str(pb.resolve())))


def next_session(after: date) -> date:
    """The next US equity session strictly after `after`.

    Refuses outside 2026 rather than guessing: an out-of-date holiday table that
    silently returns a closed day is worse than an error.
    """
    d = after + timedelta(days=1)
    for _ in range(10):
        if d.year != 2026:
            raise ValueError(
                f"next_session({after}) reached {d}: the holiday table only covers "
                f"2026. Update US_MARKET_HOLIDAYS_2026 before betting past it.")
        if d.weekday() < 5 and d.isoformat() not in US_MARKET_HOLIDAYS_2026:
            return d
        d += timedelta(days=1)
    raise ValueError(f"no session found within 10 days of {after}")


# ── THE RATIONALE SPLIT ─────────────────────────────────────────────────────
# THE OLD SPLIT WAS ON "|" ALONE, and a missing pipe lost a field WITHOUT SAYING SO.
# Measured on the four shapes a model actually produces:
#
#   DRIVER MACRO | SIGNAL 7 | LOGIC yields lift   driver MACRO  signal 7  logic OK
#   DRIVER MACRO | SIGNAL 7 LOGIC: yields lift    logic=None - swallowed into SIGNAL
#   DRIVER MACRO SIGNAL 7 LOGIC: yields lift      driver="MACRO SIGNAL 7 LOGIC: ...",
#                                                 signal=None, logic=None
#   ...| SIGNAL 7 \n LOGIC: yields lift           logic=None - the line matched no branch
#
# All three failures produce logic=None, WHICH IS INDISTINGUISHABLE FROM A MODEL THAT
# GAVE NO REASON. Three of the eight live R48 candidates were in the second shape. The
# third is the nastiest: "MACRO SIGNAL 7 LOGIC: ..." splits to a first token of "MACRO",
# which IS a valid bucket, so the driver check PASSES and the run then reports an empty
# SIGNAL - a correct refusal for the wrong reason, which is how a real bug hides.
#
# The fix is to split on the CONTRACT'S OWN FIELD NAMES rather than on its punctuation.
# That is not guessing what the model meant: DRIVER, SIGNAL and LOGIC are the declared
# field headers, and the pipe is decoration between them. What IS guessing - picking one
# of two LOGIC markers, or inventing a field that was never named - stays a refusal.
_RATIONALE_FIELDS = ("DRIVER", "SIGNAL", "LOGIC")
# Matched only as a HEADER: at the start, or after whitespace or a pipe, uppercase, on a
# word boundary. A lowercase "logic" inside a free-text SIGNAL ("the logic of the
# market") is therefore not a marker, which matters because the ungrounded path still
# puts prose in that field.
_FIELD_MARKER_RE = re.compile(
    r"(?:^|(?<=[\s|]))(DRIVER|SIGNAL|LOGIC)\b[ \t]*:?[ \t]*")


def split_rationale(rationale) -> tuple:
    """(fields, parsed_by, problem). `problem` is None only when all three were found.

    Never returns a quietly missing field: whatever it could not resolve is NAMED, and
    the caller turns that name into a refusal.
    """
    text = str(rationale or "").strip()
    if not text:
        return {}, None, "the RATIONALE is empty."
    marks = list(_FIELD_MARKER_RE.finditer(text))
    if not marks:
        return {}, None, (
            "the RATIONALE names none of DRIVER, SIGNAL or LOGIC, so there is no way "
            "to tell which part of it is which.")

    seen = [m.group(1) for m in marks]
    dupes = sorted({f for f in seen if seen.count(f) > 1})
    if dupes:
        # Deliberately NOT "take the first one". Two LOGIC markers mean two candidate
        # reasons, and choosing between them is the module deciding what the model
        # meant - the habit the index parser already refuses to fall into.
        return {}, None, (
            f"{' and '.join(dupes)} appears more than once, so which text is the "
            f"field cannot be decided without guessing.")

    fields = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        fields[m.group(1).lower()] = text[m.end():end].strip().rstrip("|").strip()

    # Did the model actually use the format, or did the markers rescue it? Recorded so
    # a repaired answer is visibly repaired rather than passing as a clean one.
    parts = [p.strip() for p in text.split("|")]
    by_pipe = sum(1 for p in parts if p.upper().startswith(_RATIONALE_FIELDS))
    parsed_by = "pipes" if by_pipe == len(marks) else "markers"

    missing = [f for f in _RATIONALE_FIELDS if f.lower() not in fields]
    if missing:
        return fields, parsed_by, (
            f"the RATIONALE names no {' or '.join(missing)}. A field the parser cannot "
            f"find is a field that would otherwise be dropped in silence.")
    return fields, parsed_by, None


def parse_completion(raw: str) -> dict:
    out = {"raw": raw, "direction": None, "deadline": None, "rationale": None,
           "driver": None, "signal": None, "logic": None,
           "rationale_parsed_by": None, "rationale_problem": None}
    rationale, continued = None, []
    for line in str(raw).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().upper(), v.strip()
        if k == "DIRECTION":
            out["direction"] = v.upper().strip(" .*")
        elif k == "DEADLINE":
            out["deadline"] = v
        elif k == "RATIONALE":
            rationale = v
        elif k in _RATIONALE_FIELDS and rationale is not None:
            # A CONTINUATION LINE: the model put LOGIC on its own line rather than
            # after a pipe. This branch did not exist, so the line matched nothing and
            # the reason vanished. Folded back in, and `raw` still holds the original.
            continued.append(f"{k}: {v}")

    if rationale is not None:
        full = " | ".join([rationale, *continued]) if continued else rationale
        fields, parsed_by, problem = split_rationale(full)
        out.update(rationale=full, driver=fields.get("driver"),
                   signal=fields.get("signal"), logic=fields.get("logic"),
                   rationale_parsed_by=parsed_by, rationale_problem=problem)
    return out


def signal_is_external_fact(signal) -> bool:
    """Best-effort: a SIGNAL must carry a DATE or a NAMED SOURCE.

    This cannot verify that the fact is true - only that it is the KIND of thing that
    could be checked. "Sentiment feels weak" names nothing and fails; "CPI surprise
    +0.3, BLS 12 Sep" names a release, a number, a source and a date and passes. The
    check is deliberately weak and deliberately stated as weak: it filters interpretation
    dressed as evidence, not lies.
    """
    s = str(signal or "").strip()
    if len(s) < 8:
        return False
    return bool(_DATE_RE.search(s) or _SOURCE_RE.search(s))


def gate_all(parsed_list, sym: str, deadline: str,
             require_signal_shape: bool = True) -> list:
    """One record per candidate, each with a verdict and an exact refusal string.

    `require_signal_shape` is the old "does it carry a date or a named source"
    heuristic. It is a PROXY for "could somebody check this", and R43 replaced the
    proxy with the thing itself: an exact quote from a retrieved document. Stacking
    both refuses TRUE quotes - "US inflation ticks up" is a real Reuters headline
    with a real published date, and it carries neither a date nor a source IN ITS
    TEXT. So the grounded gate turns this off and the document supplies the date.
    """
    out = []
    for p in parsed_list:
        rec = {"raw": p["raw"], "parsed": {k: v for k, v in p.items() if k != "raw"}}
        d = (p.get("direction") or "").upper()
        if d not in DIRECTIONS:
            rec.update(verdict="REFUSED", missing=["direction"],
                       refusal=(f"direction: {p.get('direction')!r} is not a direction. "
                                f"UP or DOWN, and nothing else, can be graded."))
        elif not str(p.get("rationale") or "").strip():
            rec.update(verdict="REFUSED", missing=["rationale"],
                       refusal=("rationale: the bet states a direction with no reason. "
                                "DRIVER | SIGNAL | LOGIC is required, and it is recorded "
                                "but never rewarded."))
        elif p.get("rationale_problem"):
            rec.update(verdict="REFUSED", missing=["rationale_format"],
                       refusal=(f"rationale_format: {p['rationale_problem']} The "
                                f"contract is DRIVER ... | SIGNAL ... | LOGIC ... . "
                                f"This refusal exists so a lost field is NAMED: the "
                                f"old parser split on the pipe alone and a missing "
                                f"one silently left logic=None, which reads exactly "
                                f"like a model that gave no reason at all."))
        elif (p.get("driver") or "").upper().split()[0:1] and \
                (p.get("driver") or "").upper().split()[0] not in BUCKETS:
            rec.update(verdict="REFUSED", missing=["driver"],
                       refusal=(f"driver: {p.get('driver')!r} is not one of "
                                f"{'|'.join(BUCKETS)}."))
        elif require_signal_shape and not signal_is_external_fact(p.get("signal")):
            rec.update(verdict="REFUSED", missing=["signal"],
                       refusal=(f"signal: {p.get('signal')!r} is interpretation, not a "
                                f"dated external fact. A SIGNAL must carry a date or a "
                                f"named source so somebody else could look it up."))
        elif str(p.get("deadline") or "").strip() != deadline:
            rec.update(verdict="REFUSED", missing=["deadline"],
                       refusal=(f"deadline: {p.get('deadline')!r} is not the graded "
                                f"session {deadline!r}."))
        else:
            rec.update(verdict="ADMITTED", missing=[], refusal=None)
        out.append(rec)
    return out


# ── R43: GROUNDED SIGNALS ───────────────────────────────────────────────────
# The 7 Sep run sealed three bets whose every cited fact was invented, and the gate
# admitted 22 of 24 because it checked SHAPE. The model has now stopped supplying facts:
# it is handed retrieved snippets and its SIGNAL must be an EXACT SUBSTRING of one.
# Not "similar to", not "supported by" - a substring, or REFUSED.

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# Compiled here rather than inline so the bytes are visible in one place and a
# mangled escape shows up as an import-time error instead of a silent no-match.
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\b")
_MONTH_DAY_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})\b")


# R49 PIECE 2. GLYPH FOLDING, WHICH IS NOT FUZZY MATCHING.
#
# Publishers emit curly quotes, en and em dashes, non-breaking spaces and a single
# ellipsis character; a model retyping the sentence emits the ASCII forms. Under R48
# that difference alone - not one word changed - was a REFUSAL, and the refusal read
# "not an exact substring", which is true of the bytes and false of the sentence.
#
# The line this draws: CANONICALISING A GLYPH is deciding that U+2019 and "'" are the
# same character, which they are. STEMMING, SYNONYMS AND EDIT DISTANCE decide that two
# different sentences are close enough, which is the thing being refused. The first is
# spelling, the second is meaning, and only the second turns "quoted the document" back
# into "said something like it".
#
# NFKC handles the non-breaking space, the ellipsis and the ligatures. It does NOT
# touch dashes or quotes, so those are mapped explicitly.
_GLYPHS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "«": '"', "»": '"',
    # U+2033 DOUBLE PRIME is deliberately absent: NFKC runs first and decomposes it
    # into two U+2032 PRIMEs, which the line above then folds to "''". Listing it here
    # would be a dead entry that reads as if it were doing something. Found by a test
    # that expected '"' and got "''".
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "⁃": "-",
    "­": "",   # soft hyphen: invisible in the page, a byte in the string
}
_GLYPH_TABLE = str.maketrans(_GLYPHS)


def normalise(text: str) -> str:
    """NFKC, glyph-folded, whitespace-collapsed, case-folded. Nothing else.

    Deliberately NOT stemming, synonyms or fuzzy distance: every one of those turns
    "the model quoted the document" back into "the model said something like it",
    which is the property being bought here. Folding a curly quote onto a straight one
    does not - it is the same character spelled two ways.
    """
    s = unicodedata.normalize("NFKC", str(text or "")).translate(_GLYPH_TABLE)
    return " ".join(s.split()).casefold()


def signal_grounded(signal, snippets) -> tuple:
    """(True, snippet) when the signal is an exact substring of one, else (False, None)."""
    needle = normalise(signal)
    if len(needle) < 12:
        return False, None
    for sn in snippets or []:
        hay = normalise(_field(sn, "snippet"))
        if needle and needle in hay:
            return True, sn
        title = normalise(_field(sn, "title"))
        if needle and needle in title:
            return True, sn
    return False, None


def _field(obj, name):
    """One accessor for both a Snippet dataclass and a plain dict.

    `getattr(sn, 'published_utc') or sn.get(...)` looked harmless and was not: an
    undated snippet has published_utc == "", which is FALSY, so the fallback fired on a
    dataclass that has no .get and the whole run died.
    """
    if hasattr(obj, name):
        return getattr(obj, name)
    try:
        return obj.get(name)
    except AttributeError:
        return None


# ── R49 PIECE 1: THE SIGNAL IS AN INDEX, NOT A COPIED PHRASE ────────────────
# R48 asked a 3B model to COPY a sentence word-for-word. Live, it copied one of eight
# and failed the other seven - and the failures were NOT mostly paraphrase. Replayed:
# one was verbatim but had "LOGIC:" spilled into the same field, three spliced two
# separate bullets into one sentence that no document contains, two were true
# paraphrase, one reworded a photo caption. Copying is simply the wrong task for this
# model, and the gate was measuring copying ability rather than grounding.
#
# So the task changes. The snippets are split into NUMBERED sentences and the model
# returns a NUMBER. The SIGNAL text is then the sentence at that number, which is
# verbatim BY CONSTRUCTION - there is no copy step left to get wrong. The exact
# substring check survives underneath as belt-and-suspenders on the reconstructed text,
# so a segmentation bug that invented a sentence would still be caught.
#
# NOTHING IS LOOSENED. An out-of-range number is refused, an empty selection is refused,
# and prose in the SIGNAL field is refused. What is removed is the requirement that the
# model be good at transcription.

# A segment must be a real sentence rather than a nav label: long enough, several
# words, and at least one actual word in it. Deliberately blunt. Anything cleverer is
# an editorial judgement about which facts count, which is not this module's job - the
# junk in a page is a property of the page, and the record shows exactly what was
# selected out of it.
SEG_MIN_CHARS = 12
SEG_MIN_TOKENS = 4

# `[...]` is Tavily's own elision marker between extracted passages; a newline ends a
# block. Split on those first, then on sentence ends.
_BLOCK_SPLIT_RE = re.compile(r"\[\s*\.\.\.\s*\]|[\r\n]+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(“‘A-Z0-9])")
# Markdown and page furniture, stripped from the ENDS only. Never from the middle:
# a segment has to stay a contiguous slice of the source text or the substring check
# underneath it becomes a lie.
_EDGE_NOISE_RE = re.compile(r"^[\s#>*_\-•■-◿─-╿]+|[\s#>*_]+$")
_HAS_WORD_RE = re.compile(r"[A-Za-z]{3,}")

# Written as a character class rather than a bare "\d+" so a mangled escape shows up
# as an import-time error instead of a silent no-match. dates_in() was broken that way
# once and matched nothing at all.
_INDEX_RE = re.compile(r"[0-9]+")
# The only non-numeric text tolerated in a SIGNAL field. Everything else means the
# model answered with prose, which is the contract it was told not to use.
_INDEX_FILLER = {"segment", "segments", "sentence", "sentences", "no", "nos", "number",
                 "numbers", "item", "items", "and", "index", "indices"}
# Punctuation a list of numbers may legitimately carry. A MINUS IS NOT ON IT: "-1"
# would otherwise have its sign dropped and be read as segment 1, and "1-3" would be
# read as segments 1 and 3 rather than the range the model meant. Both are the module
# quietly deciding what the model meant, which is the habit this whole gate exists to
# break. Caught by a test, not by reasoning.
_INDEX_PUNCT_RE = re.compile(r"^[0-9\s\[\](),.;:#&+/]*$")


def segment_text(text: str) -> list:
    """One blob of retrieved text -> its usable sentences, in order.

    EVERY RETURNED SEGMENT IS A CONTIGUOUS SLICE OF `text` once whitespace is
    collapsed. That is the invariant the whole piece rests on and it is tested: strip
    at the edges, never in the middle, and never rewrite a character.
    """
    out = []
    for block in _BLOCK_SPLIT_RE.split(str(text or "")):
        for raw in _SENT_SPLIT_RE.split(block):
            seg = _EDGE_NOISE_RE.sub("", " ".join(raw.split())).strip()
            if len(seg) < SEG_MIN_CHARS:
                continue
            if len(seg.split()) < SEG_MIN_TOKENS:
                continue
            if not _HAS_WORD_RE.search(seg):
                continue
            out.append(seg)
    return out


def segment_snippets(snippets) -> list:
    """All snippets -> one globally numbered segment table.

    Numbering is 1..N over the segments that SURVIVE the filter, so every number the
    model can see is a number it may use. Numbering the dropped ones too would put
    holes in the list and invite an out-of-range answer that is really a formatting
    accident.

    The title is a segment like any other: it was already citable under R48.
    """
    table, n = [], 0
    for s_i, sn in enumerate(snippets or []):
        for field in ("title", "snippet"):
            for seg in segment_text(_field(sn, field)):
                if any(t["text"] == seg and t["source"] == s_i for t in table):
                    continue  # a title repeated as the snippet's first line
                n += 1
                table.append({"index": n, "text": seg, "source": s_i, "field": field})
    return table


def render_evidence(snippets, segments) -> str:
    """The numbered evidence block, grouped by source so the class is stated once."""
    lines = []
    for s_i, sn in enumerate(snippets or []):
        rows = [t for t in segments if t["source"] == s_i]
        if not rows:
            continue
        pub = (_field(sn, "published_utc") or "")[:10] or "UNDATED"
        lines.append(f"\nSOURCE {chr(65 + s_i)} — {_field(sn, 'host')}, "
                     f"class {_field(sn, 'source_class')} "
                     f"({_field(sn, 'source_kind')}), published {pub}")
        for t in rows:
            lines.append(f"  [{t['index']}] {t['text']}")
    return "\n".join(lines)


def parse_signal_indices(signal, n_segments: int) -> tuple:
    """(indices, None) or (None, refusal). Order preserved, duplicates dropped.

    Refuses prose, refuses an empty selection, refuses out of range. An index is the
    one thing in this contract that can be checked without trusting the model at all,
    so it is checked strictly.
    """
    s = str(signal or "").strip()
    if not s:
        return None, ("signal_index: the SIGNAL field is empty. It must carry the "
                      "NUMBER of a numbered sentence from the evidence block.")
    prose = [w for w in re.split(r"[^A-Za-z]+", s) if w and w.lower() not in _INDEX_FILLER]
    if prose:
        return None, (f"signal_index: {s!r} is prose, not a segment number. The SIGNAL "
                      f"is now an INDEX — the model no longer copies text, so text in "
                      f"this field cannot be trusted to be verbatim "
                      f"(offending words: {', '.join(prose[:4])}).")
    stripped = " ".join(w for w in re.split(r"\s+", s)
                        if w.strip("[](),.;:#&+/").lower() not in _INDEX_FILLER)
    if not _INDEX_PUNCT_RE.match(stripped):
        return None, (f"signal_index: {s!r} carries something that is neither a number "
                      f"nor list punctuation. Give plain numbers separated by commas — "
                      f"a range and a sign are both read by guessing, and this module "
                      f"does not guess what the model meant.")
    seen, idxs = set(), []
    for m in _INDEX_RE.finditer(s):
        i = int(m.group(0))
        if i not in seen:
            seen.add(i)
            idxs.append(i)
    if not idxs:
        return None, (f"signal_index: {s!r} names no segment number.")
    bad = [i for i in idxs if i < 1 or i > n_segments]
    if bad:
        return None, (f"signal_index: segment {bad} is out of range — the evidence "
                      f"block offered 1..{n_segments}. A number nobody printed is an "
                      f"invented citation with a shorter spelling.")
    return idxs, None


def signal_from_indices(indices, segments) -> tuple:
    """(text, chosen rows). The text is verbatim by construction — assembled from the
    table, never from anything the model wrote."""
    by_index = {t["index"]: t for t in segments}
    chosen = [by_index[i] for i in indices]
    return " ".join(t["text"] for t in chosen), chosen


def dates_in(text: str, year: int) -> list:
    """Every date the text names, as (year, month, day). Best effort, and only used to
    REFUSE - never to admit.

    THE FIRST VERSION OF THIS FUNCTION MATCHED NOTHING and would have let the Jackson
    Hole case through a second time. A heredoc wrote a literal BACKSPACE byte (0x08)
    where \\b belonged and a literal backslash-d where \\d belonged; grep and sed both
    rendered it as if it were correct, and only inspect.getsource() showed the real
    bytes. A regex that silently matches nothing is indistinguishable from a document
    with no dates in it.
    """
    out = []
    t = str(text or "")
    for m in _ISO_RE.finditer(t):
        out.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _DAY_MONTH_RE.finditer(t):
        mo = _MONTHS.get(m.group(2)[:3].lower())
        if mo:
            out.append((year, mo, int(m.group(1))))
    for m in _MONTH_DAY_RE.finditer(t):
        mo = _MONTHS.get(m.group(1)[:3].lower())
        if mo:
            out.append((year, mo, int(m.group(2))))
    return out


def signal_dated_after(signal, deadline: str) -> bool:
    """THE JACKSON HOLE CASE. On 7 Sep a bet cited a transcript dated 'Sept 21' - thirteen
    days AFTER the session it claimed to explain - and the gate admitted it. A fact that
    has not happened cannot have driven a price."""
    dl = date.fromisoformat(deadline)
    for y, mo, d in dates_in(signal, dl.year):
        try:
            if date(y, mo, d) > dl:
                return True
        except ValueError:
            continue
    return False


# ── R49 PIECE 4: COHERENCE IS RECORDED, NOT ENFORCED ────────────────────────
# The R48 bet sealed UP while its SIGNAL said a downturn is only a matter of time and
# its LOGIC said the index has usually fallen into correction. Nothing checked that the
# reason supported the direction, and the obvious fix is to add that check.
#
# THE OBVIOUS FIX IS THE WRONG ONE. A gate on "direction must match the rationale"
# does not teach the model to reason better; it teaches the model to WRITE A RATIONALE
# THAT MATCHES THE DIRECTION IT ALREADY PICKED. That is rationalisation, and it would
# poison the one artefact this whole exercise exists to produce - an honest record of
# why a bet was placed, readable later against what actually happened.
#
# So the triple {direction, signal_polarity, rationale} is computed, recorded on the
# candidate, sealed with the bet and appended to a ledger. A mismatch is FLAGGED and
# STILL ADMITTED. The market grades the direction; this is a calibration signal for
# whoever reads fifty of these later, not a filter.
#
# The lexicon is small and blunt on purpose, and it is scored on the SELECTED span -
# text this module put there, not text the model wrote - so it cannot be gamed by
# word choice. NEUTRAL is a real answer and the common one.
_POS_TERMS = frozenset("""
rose rise rises rising rose gain gains gained gaining advance advances advanced
climb climbs climbed jump jumps jumped surge surges surged rally rallies rallied
rebound rebounds rebounded higher up upside record high highs strong strength
beat beats outperform outperformed boom expansion growth grew recovery optimism
""".split())
_NEG_TERMS = frozenset("""
fell fall falls falling drop drops dropped decline declines declined slid slide
slipped slips slump slumps slumped plunge plunges plunged sink sinks sank tumble
tumbles tumbled lower down downside correction crash bear selloff sell-off
weak weakness weaker loss losses lose miss missed underperform recession
contraction downturn slowdown fear fears risk risks headwinds
""".split())
# A three-token window is the standard blunt choice. Longer and "no" reaches across a
# clause boundary and flips a term it has nothing to do with.
_NEGATORS = frozenset("not no never none nor without n't cannot".split())
_NEG_WINDOW = 3

POLARITIES = ("POSITIVE", "NEGATIVE", "NEUTRAL")
POLARITY_OK = {"UP": "POSITIVE", "DOWN": "NEGATIVE"}
POLARITY_LEDGER = LEDGER / "POLARITY_LEDGER.jsonl"


def signal_polarity(text: str) -> dict:
    """{polarity, pos, neg, terms}. Blunt lexicon plus negation. Never a gate.

    Declared weak in the same breath as it is used: it cannot tell a hedge from a
    claim, and a headline like "fears of a slowdown fade" will score NEGATIVE on two
    terms and one flip. That is exactly why it flags rather than refuses.
    """
    toks = re.findall(r"[a-z']+", normalise(text))
    pos, neg, hits = 0, 0, []
    for i, t in enumerate(toks):
        base = "POSITIVE" if t in _POS_TERMS else "NEGATIVE" if t in _NEG_TERMS else None
        if base is None:
            continue
        window = toks[max(0, i - _NEG_WINDOW):i]
        flipped = any(w in _NEGATORS or w.endswith("n't") for w in window)
        eff = base if not flipped else ("NEGATIVE" if base == "POSITIVE" else "POSITIVE")
        hits.append({"term": t, "base": base, "negated": flipped, "effect": eff})
        if eff == "POSITIVE":
            pos += 1
        else:
            neg += 1
    polarity = "NEUTRAL" if pos == neg else ("POSITIVE" if pos > neg else "NEGATIVE")
    return {"polarity": polarity, "pos": pos, "neg": neg, "terms": hits}


def coherence(direction: str, signal_text: str, rationale) -> dict:
    """The triple, plus a flag. ADMISSION IS NOT AFFECTED — the caller records this and
    moves on."""
    pol = signal_polarity(signal_text)
    expected = POLARITY_OK.get((direction or "").upper())
    mismatch = (pol["polarity"] != "NEUTRAL" and expected is not None
                and pol["polarity"] != expected)
    return {
        "direction": direction,
        "signal_polarity": pol["polarity"],
        "rationale": rationale,
        "polarity_terms": pol["terms"],
        "polarity_counts": {"positive": pol["pos"], "negative": pol["neg"]},
        "flag": "DIRECTION_POLARITY_MISMATCH" if mismatch else None,
        "_not_a_gate": ("Recorded, never enforced. A gate here would teach the model "
                        "to write a rationale that matches the direction it already "
                        "picked, which is rationalisation, and it would poison the "
                        "record this exists to keep honest. The market grades the "
                        "direction."),
    }


# ── R52 item 4: ONE correction turn before refusing ─────────────────────────
# A wrong field ORDER is a formatting failure, not a dishonest answer, and refusing it
# outright throws away a candidate that may have picked a real span for a real reason.
# R48 measured what that costs: five of seven refusals that night were transcription
# accidents rather than fabrications.
#
# So a wrong-order answer gets EXACTLY ONE correction turn, and then it refuses. One,
# not "until it works": a retry loop would keep asking until the model stumbled into
# the right shape, which selects for persistence rather than for reasoning and quietly
# turns the gate into a formatter.
#
# WHAT THE CORRECTION MAY NOT DO IS HINT AT THE ANSWER. It restates the field order and
# nothing else - no mention of which direction, no mention of what was wrong with the
# reasoning, no repetition of the model's own first attempt back at it. A correction
# that echoed the first attempt would re-prime the very verdict the ordering exists to
# stop being generated first.
RETRY_CORRECTION = (
    "Your fields were out of order. Answer again with EXACTLY these lines, in this "
    "order, and nothing else:\n\n"
    "DEADLINE: {deadline}\n"
    "SIGNAL: [the NUMBER of one sentence from the evidence]\n"
    "DRIVER: one of MACRO, GEOPOL, FLOW, SECTOR\n"
    "LOGIC: [ONE sentence — the mechanism]\n"
    "DIRECTION: UP or DOWN\n\n"
    "DIRECTION must be the LAST line."
)


def correction_prompt(deadline: str) -> str:
    """The correction turn. Order only — it names no direction and no evidence."""
    return RETRY_CORRECTION.format(deadline=deadline)


def retry_wrong_order(parsed_list, deadline: str, retry_fn) -> tuple:
    """(parsed_list, log). One correction turn per wrong-order candidate, then stop.

    `retry_fn(index, correction) -> str` is injectable so tests and the dry run never
    touch a model. It returns the model's second answer, which is re-parsed and kept
    ONLY if it fixes the order - a second wrong answer leaves the first in place, so a
    retry can never make a candidate worse.
    """
    out, log = list(parsed_list), []
    if retry_fn is None:
        return out, log
    for i, p in enumerate(out):
        if not p.get("order_problem"):
            continue
        entry = {"candidate": i, "problem": p["order_problem"], "outcome": None}
        try:
            raw = retry_fn(i, correction_prompt(deadline))
        except Exception as exc:                                   # noqa: BLE001
            entry["outcome"] = f"RETRY_FAILED ({type(exc).__name__}: {exc})"
            log.append(entry)
            continue
        if not str(raw or "").strip():
            entry["outcome"] = "RETRY_EMPTY"
            log.append(entry)
            continue
        second = parse_grounded_completion(raw)
        second["retried"] = True
        second["retry_of"] = p["raw"]
        if second.get("order_problem"):
            # The second answer is still wrong. Keep the FIRST, so the record shows
            # what the model actually did first and the retry cannot launder it.
            entry["outcome"] = f"STILL_WRONG ({second['order_problem'][:60]}...)"
        else:
            out[i] = second
            entry["outcome"] = "FIXED"
        entry["second_field_order"] = second.get("field_order")
        log.append(entry)
    return out, log


def bucket_direction_table(rows) -> dict:
    """P(DIRECTION=UP | DRIVER=bucket) over admitted candidates. A MONITOR, NOT A GATE.

    R51 asserted the four buckets were direction-neutral. The only evidence for that was
    that the four WORDS are neutral in our own lexicon, which is a fact about vocabulary
    and not about the model. This measures the thing that was asserted.

    NOTHING IS REFUSED ON THIS NUMBER, and nothing should be. A bucket that skews is a
    FINDING - it might mean the label is leaking a direction, or it might mean the world
    genuinely handed us four bearish MACRO facts this week. Those two look identical at
    n=8 and are told apart by watching the number over many bets, not by gating one.

    `n` is reported beside every rate precisely so a 2-of-2 "100%" cannot be read as a
    result. Below MIN_BUCKET_N the rate is computed but marked as noise.
    """
    out = {}
    for bucket in BUCKETS:
        hits = [r for r in rows
                if str(r.get("driver") or "").upper().split()[0:1] == [bucket]]
        n = len(hits)
        ups = sum(1 for r in hits if (r.get("direction") or "").upper() == "UP")
        out[bucket] = {
            "n": n,
            "up": ups,
            "down": n - ups,
            "p_up": (round(ups / n, 3) if n else None),
            "enough_to_read": n >= MIN_BUCKET_N,
        }
    seen = [b for b, v in out.items() if v["n"]]
    skewed = [b for b in seen
              if out[b]["enough_to_read"] and (out[b]["p_up"] <= 0.1
                                               or out[b]["p_up"] >= 0.9)]
    out["_summary"] = {
        "buckets_used": len(seen),
        "skewed": skewed,
        "_finding": (f"{', '.join(skewed)} came out near-unanimous on direction. That is "
                     f"a FINDING TO REPORT, not a refusal: it may mean the label leaks a "
                     f"direction, or it may mean the week's facts in that bucket really "
                     f"did point one way. Watch it across bets."
                     if skewed else None),
        "_not_a_gate": ("Measured because R51 asserted bucket neutrality without "
                        "evidence. Nothing is refused on this number."),
    }
    return out


# A rate over fewer than this many candidates is arithmetic, not evidence. Stated as a
# constant so the threshold is visible rather than buried in a conditional.
MIN_BUCKET_N = 4


def append_polarity_ledger(rows, path: Path | None = None) -> str:
    """Append-only. One line per admitted candidate, so fifty bets from now somebody
    can ask whether mismatched bets were actually worse."""
    p = path or POLARITY_LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return str(p)


def grounded_gate(parsed_list, sym: str, deadline: str, snippets,
                  segments=None) -> list:
    """gate_all, plus grounding BY INDEX. Order matters: cheap structural refusals
    first, so a malformed answer is not reported as an ungrounded one.

    `segments` is the numbered table the model was shown. It is derived from the
    snippets when not supplied, so the gate and the prompt cannot silently disagree
    about what number 4 was — but the caller should pass the same table it rendered.
    """
    # THE ORDER IS CHECKED BEFORE ANYTHING ELSE, because an answer in the wrong order
    # is the wrong contract, and grading its content would be grading a different
    # question than the one asked. gate_all is NOT used here any more: it speaks the
    # DIRECTION-first shape with its DRIVER|SIGNAL|LOGIC rationale, and the two
    # contracts no longer have fields in common beyond DIRECTION and DEADLINE.
    segments = segment_snippets(snippets) if segments is None else segments
    records = []
    for p in parsed_list:
        rec = {"raw": p["raw"], "parsed": {k: v for k, v in p.items() if k != "raw"},
               "verdict": "ADMITTED", "missing": [], "refusal": None}
        records.append(rec)

        if p.get("order_problem"):
            rec.update(verdict="REFUSED", missing=["field_order"],
                       refusal=(f"field_order: {p['order_problem']} The contract is "
                                f"{' -> '.join(GROUNDED_CONTRACT)}, with DIRECTION "
                                f"LAST so that it is conditioned on the reasoning "
                                f"rather than followed by it."))
            continue
        d = (p.get("direction") or "").upper()
        if d not in DIRECTIONS:
            rec.update(verdict="REFUSED", missing=["direction"],
                       refusal=(f"direction: {p.get('direction')!r} is not a direction. "
                                f"UP or DOWN, and nothing else, can be graded."))
            continue
        if str(p.get("deadline") or "").strip() != deadline:
            rec.update(verdict="REFUSED", missing=["deadline"],
                       refusal=(f"deadline: {p.get('deadline')!r} is not the graded "
                                f"session {deadline!r}."))
            continue

        idxs, why = parse_signal_indices(p.get("signal"), len(segments))
        if why is not None:
            rec.update(verdict="REFUSED", missing=["signal_index"], refusal=why)
            continue
        text, chosen = signal_from_indices(idxs, segments)
        rec["parsed"]["signal_indices"] = idxs
        rec["parsed"]["signal_text"] = text

        if signal_dated_after(text, deadline):
            rec.update(verdict="REFUSED", missing=["signal_date"],
                       refusal=(f"signal_date: segment {idxs} — {text!r} — names a date "
                                f"after the graded session {deadline}. A fact that has "
                                f"not happened cannot have driven the price."))
            continue

        # DRIVER and LOGIC are checked AFTER the span, because the contract now reads
        # SIGNAL -> DRIVER -> LOGIC and the first refusal reported should be the
        # earliest broken field rather than whichever check happened to be written
        # first. DRIVER classifies a span that has already been chosen.
        bucket = (p.get("driver") or "").upper().split()[0:1]
        if not bucket or bucket[0] not in BUCKETS:
            rec.update(verdict="REFUSED", missing=["driver"],
                       refusal=(f"driver: {p.get('driver')!r} is not one of "
                                f"{'|'.join(BUCKETS)}. The bucket is a closed "
                                f"vocabulary, and it labels the sentence already "
                                f"selected rather than choosing which one to select."))
            continue
        if not str(p.get("logic") or "").strip():
            rec.update(verdict="REFUSED", missing=["logic"],
                       refusal=("logic: empty. LOGIC is the one sentence that turns a "
                                "cited fact into a direction; without it DIRECTION is "
                                "a guess with a citation stapled to it."))
            continue

        # BELT AND SUSPENDERS. The text came out of the table, so this can only fail if
        # segmentation invented or rewrote a character. That would be a bug in this
        # module rather than a lie by the model, and it is named as one - but it is
        # still a refusal, because an unverifiable citation is unverifiable whoever
        # broke it. Checked PER SEGMENT: a two-index selection is two true sentences,
        # and their concatenation is a substring of nothing.
        broken = [t for t in chosen if not signal_grounded(t["text"], snippets)[0]]
        if broken:
            rec.update(verdict="REFUSED", missing=["grounding"],
                       refusal=(f"grounding: segment {[t['index'] for t in broken]} is "
                                f"not an exact substring of any retrieved snippet "
                                f"({len(snippets or [])} available). The segment table "
                                f"and the documents disagree — this is a segmentation "
                                f"bug, not a model error, and it still refuses."))
            continue

        sn = (snippets or [])[chosen[0]["source"]]
        rec["evidence"] = {
            "url": _field(sn, "url"),
            "published_utc": _field(sn, "published_utc") or None,
            "host": _field(sn, "host"),
            "source_class": _field(sn, "source_class"),
            "dated": bool(_field(sn, "published_utc")),
            "segment_indices": idxs,
            "segment_text": text,
            "segments_available": len(segments),
            "sources": [{"index": t["index"], "field": t["field"],
                         "host": _field((snippets or [])[t["source"]], "host"),
                         "url": _field((snippets or [])[t["source"]], "url")}
                        for t in chosen],
            # Two verbatim sentences from two DIFFERENT documents are still two true
            # sentences, but their pairing is the model's claim rather than any
            # publisher's. Recorded so grading can tell the two cases apart.
            "spans_multiple_sources": len({t["source"] for t in chosen}) > 1,
        }

        # R49 PIECE 4, UNCHANGED IN KIND. Computed AFTER the verdict is settled and
        # never able to change it. The rationale it records is now the model's own two
        # sentences rather than a pipe-separated line - which is what the flag was
        # always about: does the stated reasoning point the same way as the answer.
        rec["coherence"] = coherence(
            rec["parsed"]["direction"], text,
            f"DRIVER {p.get('driver')} | LOGIC {p.get('logic')}")
    return records


def disagreement(records) -> str:
    """NO_DISAGREEMENT when every passing candidate says the same thing.

    All 24 completions said UP on 7 Sep and the record called it a majority. Best-of-N
    over a constant selected nothing, and that must be named rather than dressed.
    """
    dirs = {r["parsed"]["direction"] for r in records if r["verdict"] == "ADMITTED"}
    if not dirs:
        return "NO_PASSING_CANDIDATE"
    return "DISAGREEMENT" if len(dirs) > 1 else "NO_DISAGREEMENT"


def choose(records) -> tuple:
    """The MAJORITY direction among passing candidates; ties break to the first.

    Majority, not "most confident": there is no confidence field here, and picking the
    single most fluent rationale would let the prose choose the bet - exactly what the
    reward rule forbids.
    """
    ok = [(i, r) for i, r in enumerate(records) if r["verdict"] == "ADMITTED"]
    if not ok:
        return None, "no candidate passed the gate", None
    votes = {d: [i for i, r in ok if r["parsed"]["direction"] == d] for d in DIRECTIONS}
    win = max(DIRECTIONS, key=lambda d: len(votes[d]))
    if not votes[win]:
        return None, "no candidate passed the gate", None
    idx = votes[win][0]
    return idx, (f"majority direction {win} "
                 f"({len(votes['UP'])} UP / {len(votes['DOWN'])} DOWN of {len(ok)} "
                 f"passing); first such candidate sealed"), win


def seal(per_asset: dict, baseline: dict, out_path: Path,
         allow_overwrite: bool = False) -> str:
    if out_path.exists() and not allow_overwrite:
        raise FileExistsError(f"{out_path} already holds a sealed bet.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": "market direction, PREDICTION ONLY — no trade (§VI)",
        "model": MODEL_PIN, "n_completions": N_COMPLETIONS,
        "temperature": TEMPERATURE,
        "gate_entry_point": "tools/market_bet.gate_all (direction + DRIVER|SIGNAL|LOGIC); "
                            "the cycle's proposal gate judges proposals, not directions",
        "baseline_method": "20-trading-day momentum sign, sealed in "
                           "BASELINE_2026-09-07_markets.json before any bet",
        "assets": per_asset, "baseline": baseline,
        "reference_close_date": "2026-09-04",
        "grading_rule": "the FIRST bar strictly after reference_close_date, "
                        "whatever date it carries - so a wrong deadline guess "
                        "cannot corrupt the grade",
        "outcome": "SEALED — not graded. Grading is +24 h against the next session close.",
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return str(out_path)


def sha_of(sym: str, direction: str, deadline: str) -> str:
    return hashlib.sha256(json.dumps(
        {"asset": sym, "direction": direction, "deadline": deadline},
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _grounded_run(a, baseline, deadline: str, dry) -> int:
    """R43. Evidence first; an asset with no fact gets NO BET and there is no fallback."""
    from core.market_news import NewsUnavailable, fetch_news

    # CHECKED ONCE, UP FRONT, BEFORE ANY ASSET IS TOUCHED. Checking it per-asset was
    # too late to be a guard: every asset can refuse on evidence first, and the run
    # then seals an empty bet with a 0 exit code and never reaches the check at all.
    # Found by the test for this very fix.
    if dry is not None and "completions" not in dry:
        raise DryRunUnusable(
            f"--dry-run file has no 'completions' key (top-level keys: "
            f"{sorted(dry)[:8]}). REFUSED rather than generating: --dry-run promises "
            f"no model is touched, and falling through to the model here is how a "
            f"clobbered fixture became a live qwen2.5:3b run.")

    per_asset = {}
    for sym in ASSETS:
        lc = baseline["last_close"][sym]
        snippets, refusal, ungrounded = [], None, False
        try:
            if dry is not None and "snippets" in dry:
                from core.market_news import Snippet
                snippets = [Snippet(**x) for x in dry["snippets"].get(sym, [])]
                if not snippets:
                    raise NewsUnavailable(f"dry-run: no snippets staged for {sym}")
                ungrounded = not all(getattr(s_, "dated", True) for s_ in snippets)
            else:
                snippets, ungrounded = fetch_news(sym)
        except NewsUnavailable as e:
            refusal = str(e)

        if refusal:
            # NO FALLBACK. Not a price-only rationale, not yesterday's snippet.
            per_asset[sym] = {"indicator": INDICATORS[sym], "last_close": lc,
                              "deadline": deadline, "sealed_direction": None,
                              "outcome": "REFUSED_NO_EVIDENCE", "why": refusal,
                              "n_snippets": 0, "ungrounded_citation": False,
                              "candidates": []}
            print(f"\n{sym}  REFUSED_NO_EVIDENCE — {refusal}")
            continue

        # ONE table, rendered into the prompt AND handed to the gate. Building it twice
        # would let the prompt's [4] and the gate's [4] drift apart, which is the one
        # way index selection could quietly stop being verbatim.
        segments = segment_snippets(snippets)
        evidence = render_evidence(snippets, segments)
        if not segments:
            per_asset[sym] = {"indicator": INDICATORS[sym], "last_close": lc,
                              "deadline": deadline, "sealed_direction": None,
                              "outcome": "REFUSED_NO_EVIDENCE",
                              "why": (f"{len(snippets)} snippet(s) but no usable "
                                      f"sentence in any of them — there is nothing to "
                                      f"select, so there is no bet."),
                              "n_snippets": len(snippets), "n_segments": 0,
                              "ungrounded_citation": False, "candidates": []}
            print(f"\n{sym}  REFUSED_NO_EVIDENCE — {len(snippets)} snippet(s), "
                  f"0 usable segments")
            continue
        if dry is not None:
            # NO FALLBACK. The `else` that used to sit here turned a clobbered fixture
            # into a live model call without a word; the key itself was verified once
            # at the top of this function.
            comps = dry["completions"].get(sym, [])
        else:
            comps = generate_completions(
                GROUNDED_PROMPT.format(sym=sym, close=lc["adjclose"],
                                       close_date=lc["date"], evidence=evidence,
                                       deadline=deadline),
                n=N_COMPLETIONS, temperature=TEMPERATURE)

        # R52 item 4. ONE correction turn for a wrong-order answer, then refuse.
        # In a dry run the second answers are staged under "retries"; live, the
        # correction goes back to the same pinned model. Either way it is one turn.
        parsed = [parse_grounded_completion(c) for c in comps]
        if dry is not None and "retries" in dry:
            staged = dry["retries"].get(sym, {})

            def _retry(i, _correction, _staged=staged):
                return _staged.get(str(i)) or _staged.get(i)
        elif dry is not None:
            _retry = None                       # dry run with no retries staged
        else:
            def _retry(i, correction, _base=None):
                _base = GROUNDED_PROMPT.format(
                    sym=sym, close=lc["adjclose"], close_date=lc["date"],
                    evidence=evidence, deadline=deadline)
                got = generate_completions(_base + "\n\n" + correction, n=1,
                                           temperature=TEMPERATURE)
                return got[0] if got else ""

        parsed, retry_log = retry_wrong_order(parsed, deadline, _retry)
        for entry in retry_log:
            print(f"  [RETRY] candidate {entry['candidate']}: {entry['outcome']} "
                  f"— was: {entry['problem'][:60]}...")
        if retry_log:
            print(f"  [RETRY] {sum(1 for e in retry_log if e['outcome'] == 'FIXED')}"
                  f"/{len(retry_log)} fixed by one correction turn")

        recs = grounded_gate(parsed, sym,
                             deadline, snippets, segments)
        idx, reason, win = choose(recs)
        agree = disagreement(recs)
        per_asset[sym] = {
            "indicator": INDICATORS[sym], "last_close": lc, "deadline": deadline,
            # R50. The order the fields were GENERATED in, sealed with the bet, because
            # the order is the property the whole round buys and a record that does not
            # show it cannot be checked later. DIRECTION is last or the answer did not
            # pass the gate.
            "contract": " -> ".join(GROUNDED_CONTRACT),
            "direction_generated_last": True,
            "sealed_field_order": (recs[idx]["parsed"]["field_order"]
                                   if idx is not None else None),
            "n_snippets": len(snippets), "n_segments": len(segments),
            # R52 item 4. Every correction turn is logged with the bet, including the
            # ones that did not work — a retry that quietly succeeded and left no trace
            # would make the model look better at the contract than it is.
            "retry_log": retry_log,
            # The numbered table exactly as the model saw it. Without it, "SIGNAL 4"
            # in the record means nothing a month from now.
            "segments": segments,
            # PIECE 5 — THE SNAPSHOT. The full retrieved text is sealed with the bet,
            # so tomorrow's grading can re-verify that the citation really was a
            # substring of what was retrieved, even if the page has since changed or
            # gone. A citation that can only be checked against a live URL is a
            # citation that stops being checkable the moment the publisher edits it.
            "snippets": [s.as_dict() for s in snippets],
            "ungrounded_citation": ungrounded,
            "sealed_direction": win,
            # The reasoning that PRODUCED the direction, in the order it was written.
            "sealed_driver": (recs[idx]["parsed"]["driver"]
                              if idx is not None else None),
            "sealed_logic": (recs[idx]["parsed"]["logic"]
                             if idx is not None else None),
            "evidence": recs[idx].get("evidence") if idx is not None else None,
            # R49 PIECE 4. The triple travels with the sealed bet, flag and all. A
            # flagged bet is a SEALED bet - the flag is for whoever reads fifty of these.
            "coherence": recs[idx].get("coherence") if idx is not None else None,
            "chosen_reason": reason, "agreement": agree,
            "sha256": sha_of(sym, win, deadline) if win else None,
            "baseline_momentum_sign": baseline["baseline"][sym]["sign"],
            "n_passed_gate": sum(r["verdict"] == "ADMITTED" for r in recs),
            "outcome": (("SEALED (ungrounded-citation)" if ungrounded else "SEALED")
                        if win else "REFUSED_NO_GROUNDED_CANDIDATE"),
            "candidates": [dict(r, sealed=(i == idx)) for i, r in enumerate(recs)],
        }
        flag = "  [UNGROUNDED-CITATION: no dated evidence existed]" if ungrounded else ""
        print(f"\n{sym}  {len(snippets)} snippet(s), {len(segments)} numbered "
              f"segment(s)  last {lc['date']} {lc['adjclose']}{flag}")
        for i, r in enumerate(recs):
            mark = "SEALED " if i == idx else "       "
            pick = r["parsed"].get("signal_indices")
            coh = r.get("coherence") or {}
            note = (f"  seg {pick}  polarity {coh.get('signal_polarity')}"
                    + ("  [FLAG direction<->polarity mismatch — ADMITTED anyway]"
                       if coh.get("flag") else ""))
            print(f"  {mark}{i} {r['verdict']:9} {r['parsed']['direction'] or '-':5}"
                  + (note if r["verdict"] == "ADMITTED"
                     else f"  — {r['refusal'][:80]}"))
        print(f"  -> {reason}   [{agree}]")

        # The ledger takes every ADMITTED candidate, not only the sealed one: the
        # question it exists to answer later is whether mismatched REASONING predicts
        # anything, and eight rows a night answers it faster than one.
        rows = [{"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "asset": sym, "deadline": deadline, "candidate": i,
                 "sealed": (i == idx),
                 "segment_indices": r["parsed"].get("signal_indices"),
                 "signal_text": r["parsed"].get("signal_text"),
                 "field_order": r["parsed"].get("field_order"),
                 "driver": r["parsed"].get("driver"),
                 **{k: v for k, v in (r.get("coherence") or {}).items()
                    if k != "_not_a_gate"}}
                for i, r in enumerate(recs) if r["verdict"] == "ADMITTED"]

        n_flag = sum(1 for row in rows if row.get("flag"))
        buckets = bucket_direction_table(rows)
        per_asset[sym]["bucket_direction"] = buckets

        if rows:
            print(f"  [POLARITY] {len(rows)} row(s), {n_flag} flagged"
                  + ("" if not a.dry_run
                     else "  (dry run — ledger not written)"))
            print("  [BUCKET]   P(UP | DRIVER)  — a MONITOR, never a gate")
            for b in BUCKETS:
                v = buckets[b]
                if not v["n"]:
                    continue
                print(f"             {b:<8} n={v['n']:<3} up={v['up']:<3} "
                      f"P(UP)={v['p_up']}"
                      + ("" if v["enough_to_read"]
                         else f"   [n<{MIN_BUCKET_N}: noise, not a rate]"))
            if buckets["_summary"]["skewed"]:
                print(f"             FINDING: {buckets['_summary']['_finding']}")
        if rows and not a.dry_run:
            print(f"  [POLARITY] -> {append_polarity_ledger(rows)}")

    out = Path(a.out or seal_path())
    if out.exists() and not a.allow_overwrite:
        raise FileExistsError(
            f"{out} already holds a sealed bet for today. Pass --allow-overwrite ONLY "
            f"for a deliberate same-day re-seal; a different day gets a different file "
            f"automatically, so this can no longer reach yesterday's bet.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": "grounded_pair_to_f41a7fd",
        "kind": "market direction, GROUNDED, PREDICTION ONLY — no trade (§VI)",
        "model": MODEL_PIN, "n_completions": N_COMPLETIONS,
        "temperature": TEMPERATURE, "deadline": deadline,
        "reference_close_date": baseline["last_close"]["SPY"]["date"],
        "grading_rule": "the FIRST bar strictly after reference_close_date",
        "gate": "grounded by INDEX, and ordered: the contract is "
                "SIGNAL -> DRIVER -> LOGIC -> DIRECTION with DIRECTION "
                "GENERATED LAST, so it is conditioned on the reasoning rather "
                "than followed by it. SIGNAL is the number of a printed segment, "
                "so the cited text is verbatim by construction; the "
                "exact-substring check survives underneath as belt-and-suspenders. "
                "An answer that names the direction first is REFUSED as the "
                "wrong contract.",
        "baseline_method": ("20-trading-day momentum sign, COMPUTED AT BET TIME from "
                            "fresh prices and sealed here — not read from an earlier "
                            "day's file"),
        # D2. The whole freshly-computed baseline travels with the bet, so grading can
        # see WHICH window the null was measured over rather than assuming today's.
        "baseline_computed_at": baseline.get("ts"),
        "baseline_full": baseline,
        "assets": per_asset, "baseline": baseline["baseline"],
        "outcome": "SEALED — not graded. Grading is +24 h.",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {out}")
    return 0

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", metavar="JSON",
                    help="{sym: [8 completions]} instead of a model")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--grounded", action="store_true",
                    help="R43: evidence first, SIGNAL must be an exact quote")
    ap.add_argument("--allow-overwrite", action="store_true")
    ap.add_argument("--deadline", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if not a.dry_run and not a.live:
        print("REFUSED: pass --dry-run <json> or --live. Nothing ran.")
        return 3

    # B3. BEFORE anything is fetched or generated. A refusal after the prices are
    # pulled and the prompt is built is a refusal that already cost the thing it was
    # protecting.
    if a.live:
        free, note = machine_is_free()
        print(note)
        if not free:
            return 4

    if a.dry_run and a.out and same_file(a.dry_run, a.out):
        print(f"REFUSED: --dry-run {a.dry_run!r} and --out {a.out!r} are THE SAME FILE. "
              f"Sealing would destroy the fixture it just read, and the next run of it "
              f"would find no 'completions' and be refused. Give the output a "
              f"distinctly different name.")
        return 5

    # Loaded before the baseline, because a dry run may stage the baseline too.
    dry = json.loads(Path(a.dry_run).read_text(encoding="utf-8")) if a.dry_run else None

    # D2. FRESH, EVERY TIME. A dry run may stage the baseline so the tests and the
    # rehearsal never touch the network; anything else computes it now.
    if dry is not None and "baseline" in dry:
        baseline = dry["baseline"]
        print("baseline: staged by --dry-run (no prices fetched)")
    else:
        baseline = compute_baseline()
        print(f"baseline: computed now — "
              + ", ".join(f"{s} {baseline['baseline'][s]['sign']}"
                          + f" to {baseline['baseline'][s]['to_date']}"
                          for s in ASSETS))
    ref = baseline["last_close"]["SPY"]["date"]
    deadline = a.deadline or next_session(date.fromisoformat(ref)).isoformat()
    print(f"reference close {ref} -> graded session {deadline}"
          + ("  (today is a market holiday)"
             if date.today().isoformat() in US_MARKET_HOLIDAYS_2026 else ""))

    if a.grounded:
        return _grounded_run(a, baseline, deadline, dry)

    per_asset = {}
    for sym in ASSETS:
        lc = baseline["last_close"][sym]
        if dry is not None:
            comps = dry[sym]
        else:
            import evaluator
            live = json.loads(Path(evaluator.TRENDS_PATH).read_text(encoding="utf-8"))
            recent = ", ".join(f"{v:.2f}" for v in live[INDICATORS[sym]][-10:])
            comps = generate_completions(
                PROMPT.format(sym=sym, close=lc["adjclose"], close_date=lc["date"],
                              recent=recent, deadline=deadline),
                n=N_COMPLETIONS, temperature=TEMPERATURE)
        recs = gate_all([parse_completion(c) for c in comps], sym, deadline)
        idx, reason, win = choose(recs)
        per_asset[sym] = {
            "indicator": INDICATORS[sym], "last_close": lc,
            "deadline": deadline,
            "sealed_direction": win,
            "sealed_rationale": recs[idx]["parsed"]["rationale"] if idx is not None else None,
            "chosen_reason": reason,
            "sha256": sha_of(sym, win, deadline) if win else None,
            "baseline_momentum_sign": baseline["baseline"][sym]["sign"],
            "n_passed_gate": sum(r["verdict"] == "ADMITTED" for r in recs),
            "candidates": [dict(r, sealed=(i == idx)) for i, r in enumerate(recs)],
        }
        print(f"\n{sym}  last {lc['date']} {lc['adjclose']}  deadline {deadline}")
        for i, r in enumerate(recs):
            mark = "SEALED " if i == idx else "       "
            print(f"  {mark}{i} {r['verdict']:9} "
                  + (r["parsed"]["direction"] or "-")
                  + ("" if r["verdict"] == "ADMITTED" else f"  — {r['refusal'][:88]}"))
        print(f"  -> {reason}")

    out = Path(a.out or (LEDGER / "BET_2026-09-07_markets.json"))
    print("\n" + seal(per_asset, baseline["baseline"], out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
