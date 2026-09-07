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

Answer with EXACTLY these three lines and nothing else:

DIRECTION: UP or DOWN
DEADLINE: {deadline}
RATIONALE: DRIVER [one of MACRO|GEOPOL|FLOW|SECTOR] | SIGNAL [the NUMBER of one sentence above] | LOGIC [one sentence]

THE SIGNAL IS A NUMBER, NOT TEXT. Do not retype the sentence, do not shorten it, do not
join two of them together. Give its number and the sentence is used exactly as printed
above. You may give more than one number, separated by commas. A number that is not in
the list above is refused, and so is anything in the SIGNAL field that is not a number.
"""

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


def parse_completion(raw: str) -> dict:
    out = {"raw": raw, "direction": None, "deadline": None, "rationale": None,
           "driver": None, "signal": None, "logic": None}
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
            out["rationale"] = v
            parts = [p.strip() for p in v.split("|")]
            for p in parts:
                up = p.upper()
                if up.startswith("DRIVER"):
                    out["driver"] = p[6:].strip(" :")
                elif up.startswith("SIGNAL"):
                    out["signal"] = p[6:].strip(" :")
                elif up.startswith("LOGIC"):
                    out["logic"] = p[5:].strip(" :")
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


def normalise(text: str) -> str:
    """Whitespace-collapsed and case-folded. Nothing else.

    Deliberately NOT stemming, synonyms or fuzzy distance: every one of those turns
    "the model quoted the document" back into "the model said something like it",
    which is the property being bought here.
    """
    return " ".join(str(text or "").split()).casefold()


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


def grounded_gate(parsed_list, sym: str, deadline: str, snippets,
                  segments=None) -> list:
    """gate_all, plus grounding BY INDEX. Order matters: cheap structural refusals
    first, so a malformed answer is not reported as an ungrounded one.

    `segments` is the numbered table the model was shown. It is derived from the
    snippets when not supplied, so the gate and the prompt cannot silently disagree
    about what number 4 was — but the caller should pass the same table it rendered.
    """
    # The shape heuristic is OFF here: grounding supersedes it, and keeping both
    # would refuse a genuine quote whose date lives in the document rather than in
    # the sentence. Found by test, not by reasoning - three tests failed with
    # missing=["signal"] where they expected missing=["grounding"].
    records = gate_all(parsed_list, sym, deadline, require_signal_shape=False)
    segments = segment_snippets(snippets) if segments is None else segments
    for rec in records:
        if rec["verdict"] != "ADMITTED":
            continue
        sig = rec["parsed"].get("signal")

        idxs, why = parse_signal_indices(sig, len(segments))
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
        if dry is not None and "completions" in dry:
            comps = dry["completions"].get(sym, [])
        else:
            comps = generate_completions(
                GROUNDED_PROMPT.format(sym=sym, close=lc["adjclose"],
                                       close_date=lc["date"], evidence=evidence,
                                       deadline=deadline),
                n=N_COMPLETIONS, temperature=TEMPERATURE)

        recs = grounded_gate([parse_completion(c) for c in comps], sym, deadline,
                             snippets, segments)
        idx, reason, win = choose(recs)
        agree = disagreement(recs)
        per_asset[sym] = {
            "indicator": INDICATORS[sym], "last_close": lc, "deadline": deadline,
            "n_snippets": len(snippets), "n_segments": len(segments),
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
            "sealed_rationale": recs[idx]["parsed"]["rationale"] if idx is not None else None,
            "evidence": recs[idx].get("evidence") if idx is not None else None,
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
            print(f"  {mark}{i} {r['verdict']:9} {r['parsed']['direction'] or '-':5}"
                  + (f"  seg {pick}" if r["verdict"] == "ADMITTED"
                     else f"  — {r['refusal'][:80]}"))
        print(f"  -> {reason}   [{agree}]")

    out = Path(a.out or (LEDGER / "BET_2026-09-07_markets_grounded.json"))
    if out.exists() and not a.allow_overwrite:
        raise FileExistsError(f"{out} already holds a sealed bet.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": "grounded_pair_to_f41a7fd",
        "kind": "market direction, GROUNDED, PREDICTION ONLY — no trade (§VI)",
        "model": MODEL_PIN, "n_completions": N_COMPLETIONS,
        "temperature": TEMPERATURE, "deadline": deadline,
        "reference_close_date": baseline["last_close"]["SPY"]["date"],
        "grading_rule": "the FIRST bar strictly after reference_close_date",
        "gate": "grounded by INDEX: SIGNAL is the number of a printed segment, so the "
                "cited text is verbatim by construction; the exact-substring check "
                "survives underneath as belt-and-suspenders",
        "baseline_method": "20-trading-day momentum sign",
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

    import core.market_daily as md
    baseline = json.loads(
        (LEDGER / "BASELINE_2026-09-07_markets.json").read_text(encoding="utf-8"))
    ref = baseline["last_close"]["SPY"]["date"]
    deadline = a.deadline or next_session(date.fromisoformat(ref)).isoformat()
    print(f"reference close {ref} -> graded session {deadline}"
          + ("  (today is a market holiday)"
             if date.today().isoformat() in US_MARKET_HOLIDAYS_2026 else ""))

    dry = json.loads(Path(a.dry_run).read_text(encoding="utf-8")) if a.dry_run else None

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
