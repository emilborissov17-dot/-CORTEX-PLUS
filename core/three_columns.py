#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/three_columns.py — THREE WITNESSES, AND THE DISTANCE BETWEEN THEM.

WHERE THE THREE COLUMNS COME FROM
----------------------------------
Not invented here. config/reporter_independence.json already defines exactly
four independence classes, and CLAUDE.md forbids adding a fifth. Three of them
can be placed:

    self_reported   the measured entity produces the statistic
    independent     a third party measures without the subject's control
    adversarial     a party whose interest opposes the subject's

The fourth, `unknown`, is by its own definition unplaceable — "never inferred to
be independent" — so it cannot be a column. It becomes the DEMOTED panel, along
with any source whose track record has gone bad.

WHY THE CONSENSUS IS A MIDPOINT AND NOT A WEIGHTED AVERAGE
-----------------------------------------------------------
A weighted average always produces a number. That is precisely its defect: three
sources that flatly contradict each other yield a confident-looking figure sitting
in a gap where no witness placed the value, and nothing downstream can tell it
from agreement. The geometric intersection cannot do that. Either the three
intervals overlap — and the overlap is a region every witness endorses, whose
midpoint is the least committed point inside it — or they do not, and that is a
HARD_FAULT which must be reported rather than averaged away.

    intersection = [max(lows), min(highs)]
    empty  -> HARD_FAULT, no consensus value at all
    else   -> consensus = midpoint of the intersection

QUALITATIVE CLAIMS ARE NEVER AGGREGATED
----------------------------------------
There is no midpoint between "the election was free" and "the election was
stolen". Qualitative columns are kept SIDE BY SIDE, forever, and the only thing
computed over them is how far apart they are: pairwise cosine, and if the closest
pair is below 0.6 the record carries a SOFT_FAULT. Nothing merges them.

EPISTEMIC TENSION
------------------
    quantitative   ET = 1 - |intersection| / mean(|range_i|)
    qualitative    ET = 1 - max(pairwise cosine)

    green  < 0.3      the witnesses substantially agree
    yellow 0.3 - 0.7
    red    > 0.7      and the record is marked MUST_UNPACK

MUST_UNPACK is a display rule with teeth: at ET > 0.7 no consumer may aggregate
the record into anything. An average of three witnesses who disagree this much is
not a summary, it is a fabrication with a small standard error.

THE LINK IS NOT OPTIONAL
-------------------------
Every column entry carries the url of the source it came from. A write without
one is REJECTED. Same rule as scripts/intel_daemon.py, for the same reason: a
claim nobody can open is not evidence, and this module's whole output is a
comparison of evidence.

NOT WIRED. Nothing writes here and nothing reads it. Storage: memory/columns/.

    venv\\Scripts\\python.exe core/three_columns.py --selftest
"""
from __future__ import annotations

import json
import math
import pathlib
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
STORE = BASE / "memory" / "columns"
INDEPENDENCE = BASE / "config" / "reporter_independence.json"

# The three columns, in the vocabulary config/reporter_independence.json already
# uses. `unknown` is deliberately absent — see the module docstring.
SELF_REPORTED, INDEPENDENT, ADVERSARIAL = "self_reported", "independent", "adversarial"
COLUMNS = (SELF_REPORTED, INDEPENDENT, ADVERSARIAL)
UNKNOWN_CLASS = "unknown"

# Claim types. A track record is kept PER TYPE because being right about a stock
# says nothing about being right about a rate: a statistical office may report
# population accurately and inflation politically, and one number for the source
# would let the first launder the second.
STOCK, FLOW, RATE, EVENT, CLAIM = "stock", "flow", "rate", "event", "claim"
TYPES = (STOCK, FLOW, RATE, EVENT, CLAIM)
QUALITATIVE_TYPES = (EVENT, CLAIM)

HARD_FAULT = "HARD_FAULT"
SOFT_FAULT = "SOFT_FAULT"
DEMOTION_REVIEW = "DEMOTION_REVIEW"
MUST_UNPACK = "MUST_UNPACK"

GREEN_BELOW = 0.3
RED_ABOVE = 0.7
QUALITATIVE_AGREEMENT_FLOOR = 0.6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LinkRequired(ValueError):
    """A claim nobody can open is not evidence."""


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

@dataclass
class Entry:
    """One witness's account of one claim."""
    source: str
    url: str
    column: str
    claim_type: str
    estimate: Optional[float] = None      # quantitative
    error: float = 0.0                    # +/- around the estimate
    text: str = ""                        # qualitative
    ts: str = field(default_factory=_now)

    def __post_init__(self):
        if not self.url or not str(self.url).strip():
            raise LinkRequired(
                "entry from {!r} has no url. Every row in this module carries the "
                "link to what it is quoting; a claim nobody can open cannot be "
                "compared with another.".format(self.source))
        if self.claim_type not in TYPES:
            raise ValueError("unknown claim type {!r}; the five are {}".format(
                self.claim_type, ", ".join(TYPES)))
        if self.column not in COLUMNS and self.column != UNKNOWN_CLASS:
            raise ValueError(
                "unknown column {!r}. The three are {} and {} is the demoted "
                "panel; config/reporter_independence.json defines no others "
                "and CLAUDE.md forbids a fifth.".format(
                    self.column, ", ".join(COLUMNS), UNKNOWN_CLASS))

    @property
    def interval(self) -> Optional[tuple]:
        if self.estimate is None:
            return None
        e = abs(float(self.error))
        return (float(self.estimate) - e, float(self.estimate) + e)

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Track record, and who is demoted
# ---------------------------------------------------------------------------

def track_record_path() -> pathlib.Path:
    return STORE / "track_record.json"


def load_track_record(path: Optional[pathlib.Path] = None) -> dict:
    p = pathlib.Path(path) if path else track_record_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_track_record(record: dict, path: Optional[pathlib.Path] = None) -> None:
    p = pathlib.Path(path) if path else track_record_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def note_physical_check(record: dict, source: str, claim_type: str,
                        confirmed: bool) -> dict:
    """Record that a physical measurement agreed or disagreed with `source`.

    PHYSICAL, not consensus. A source confirmed by the other columns has only
    been confirmed by other reporters; the track record is about contact with
    something that does not have an opinion — a satellite pass, a sensor, a
    price actually paid.
    """
    per_source = record.setdefault(source, {})
    cell = per_source.setdefault(claim_type, {"confirmed_by_physical": 0,
                                              "falsified_by_physical": 0})
    cell["confirmed_by_physical" if confirmed else "falsified_by_physical"] += 1
    return record


def is_demoted(source: str, claim_type: str, column: str,
               record: Optional[dict] = None) -> tuple:
    """(demoted, why). Two ways in, and only one of them is about performance.

    A source whose class is `unknown` is demoted BY DEFINITION — that class means
    "cannot be determined; never inferred to be independent", so it has no column
    to sit in. A source with more physical falsifications than confirmations FOR
    THIS TYPE is demoted on its record.
    """
    if column == UNKNOWN_CLASS:
        return True, ("independence class is `unknown` — never inferred to be "
                      "independent, so it has no column")
    cell = ((record or {}).get(source) or {}).get(claim_type) or {}
    c = int(cell.get("confirmed_by_physical", 0))
    f = int(cell.get("falsified_by_physical", 0))
    if f > c:
        return True, ("physical checks on {} claims: {} falsified vs {} confirmed"
                      .format(claim_type, f, c))
    return False, ""


# ---------------------------------------------------------------------------
# Quantitative: geometric intersection
# ---------------------------------------------------------------------------

def intersect(intervals: list) -> Optional[tuple]:
    """[max(lows), min(highs)], or None when they do not all overlap.

    A single point of contact (low == high) IS an intersection: three witnesses
    who agree on exactly one value agree. Zero WIDTH is not zero overlap.
    """
    usable = [iv for iv in intervals if iv is not None]
    if not usable:
        return None
    lo = max(iv[0] for iv in usable)
    hi = min(iv[1] for iv in usable)
    return (lo, hi) if lo <= hi else None


def epistemic_tension_quantitative(intervals: list) -> float:
    """1 - |intersection| / mean(|range_i|), clamped to [0,1].

    Reads as: how much of the witnesses' typical uncertainty is NOT shared. Zero
    when they agree exactly; one when they do not overlap at all.

    THE DEGENERATE CASE IS NOT A DIVISION BY ZERO. Three witnesses each reporting
    a value with no error bar have mean range 0. If they agree, the honest answer
    is 0.0 tension; if they disagree, it is 1.0 — and the intersection already
    distinguishes those two, so the ratio is never needed.
    """
    usable = [iv for iv in intervals if iv is not None]
    if len(usable) < 2:
        return 0.0
    inter = intersect(usable)
    if inter is None:
        return 1.0
    widths = [abs(hi - lo) for lo, hi in usable]
    mean_width = sum(widths) / len(widths)
    if mean_width <= 0:
        return 0.0          # they overlap and have no width: identical points
    return max(0.0, min(1.0, 1.0 - (inter[1] - inter[0]) / mean_width))


# ---------------------------------------------------------------------------
# Qualitative: side by side, never merged
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z0-9']+")


def bag_of_words(text: str) -> dict:
    """The default vectoriser: deterministic, dependency-free, offline.

    Deliberately NOT the embedding index. This module must be able to say how far
    apart two accounts are without a model being warm, and a similarity that
    silently changes when a model is reloaded is not a measurement. A caller with
    embeddings can inject a better `embed`.
    """
    v: dict = {}
    for w in _WORD.findall((text or "").lower()):
        v[w] = v.get(w, 0.0) + 1.0
    return v


def cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    dot = sum(w * b.get(k, 0.0) for k, w in a.items())
    na = math.sqrt(sum(w * w for w in a.values()))
    nb = math.sqrt(sum(w * w for w in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def pairwise_similarities(texts: list, embed: Optional[Callable] = None) -> list:
    e = embed or bag_of_words
    vecs = [e(t) for t in texts]
    out = []
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            out.append({"i": i, "j": j, "cosine": round(cosine(vecs[i], vecs[j]), 4)})
    return out


def epistemic_tension_qualitative(texts: list, embed: Optional[Callable] = None) -> float:
    """1 - max(pairwise cosine). One account cannot disagree with itself: 0.0."""
    if len(texts) < 2:
        return 0.0
    sims = pairwise_similarities(texts, embed)
    return max(0.0, min(1.0, 1.0 - max(s["cosine"] for s in sims)))


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

def band(et: float) -> str:
    if et < GREEN_BELOW:
        return "green"
    if et > RED_ABOVE:
        return "red"
    return "yellow"


def compare(claim_id: str, axis: str, entries: list,
            track: Optional[dict] = None,
            embed: Optional[Callable] = None) -> dict:
    """Build one claim's record: columns side by side, faults, ET, demoted panel.

    Never raises on disagreement. Disagreement is the output.
    """
    track = track if track is not None else load_track_record()
    if not entries:
        raise ValueError("a claim record needs at least one entry")

    claim_type = entries[0].claim_type
    qualitative = claim_type in QUALITATIVE_TYPES

    trusted, demoted = [], []
    for e in entries:
        dem, why = is_demoted(e.source, e.claim_type, e.column, track)
        (demoted if dem else trusted).append((e, why))

    record = {
        "claim_id": claim_id, "axis": axis, "claim_type": claim_type,
        "ts": _now(), "qualitative": qualitative,
        "columns": {c: [] for c in COLUMNS},
        "demoted": [],
        "signals": [], "faults": [],
        "consensus": None, "intersection": None,
        "epistemic_tension": 0.0, "band": "green",
    }

    for e, _ in trusted:
        record["columns"][e.column].append(e.as_dict())
    for e, why in demoted:
        d = e.as_dict()
        d["demoted_because"] = why
        record["demoted"].append(d)

    if qualitative:
        _compare_qualitative(record, trusted, demoted, embed)
    else:
        _compare_quantitative(record, trusted, demoted)

    record["band"] = band(record["epistemic_tension"])
    if record["epistemic_tension"] > RED_ABOVE:
        record["signals"].append(MUST_UNPACK)
    return record


def _compare_quantitative(record: dict, trusted: list, demoted: list) -> None:
    intervals = [e.interval for e, _ in trusted if e.interval is not None]
    record["epistemic_tension"] = epistemic_tension_quantitative(intervals)

    if len(intervals) < 2:
        record["faults"].append({
            "kind": "INSUFFICIENT_WITNESSES",
            "detail": "{} usable interval(s); a comparison needs at least two"
                      .format(len(intervals))})
        return

    inter = intersect(intervals)
    if inter is None:
        record["faults"].append({
            "kind": HARD_FAULT,
            "detail": "the columns' intervals do not all overlap; there is no "
                      "value every witness endorses, so no consensus is offered"})
        return

    record["intersection"] = [inter[0], inter[1]]
    # MIDPOINT of the intersection. Not a weighted average — see the docstring.
    record["consensus"] = (inter[0] + inter[1]) / 2.0

    # A demoted witness landing INSIDE the trusted overlap is the rehabilitation
    # path: it was excluded from the arithmetic and turned out to be right anyway.
    for e, why in demoted:
        iv = e.interval
        if iv is None:
            continue
        if iv[0] <= inter[1] and iv[1] >= inter[0]:
            record["signals"].append(DEMOTION_REVIEW)
            record.setdefault("demotion_review", []).append({
                "source": e.source, "url": e.url, "was_demoted_because": why,
                "detail": "its interval [{:.4g}, {:.4g}] meets the trusted "
                          "intersection [{:.4g}, {:.4g}]".format(
                              iv[0], iv[1], inter[0], inter[1])})


def _compare_qualitative(record: dict, trusted: list, demoted: list,
                         embed: Optional[Callable]) -> None:
    texts = [e.text for e, _ in trusted if (e.text or "").strip()]
    record["epistemic_tension"] = epistemic_tension_qualitative(texts, embed)
    record["pairwise"] = pairwise_similarities(texts, embed)
    # No consensus field is ever populated for a qualitative claim. There is no
    # midpoint between "free" and "stolen", and leaving the key None is how a
    # consumer discovers that rather than averaging something.
    if len(texts) < 2:
        record["faults"].append({
            "kind": "INSUFFICIENT_WITNESSES",
            "detail": "{} account(s); side-by-side needs at least two".format(len(texts))})
        return
    closest = max(s["cosine"] for s in record["pairwise"])
    if closest < QUALITATIVE_AGREEMENT_FLOOR:
        record["faults"].append({
            "kind": SOFT_FAULT,
            "detail": "the closest pair of accounts agrees only {:.2f} (< {}); "
                      "these are different stories, not one story".format(
                          closest, QUALITATIVE_AGREEMENT_FLOOR)})

    for e, why in demoted:
        if not (e.text or "").strip():
            continue
        sims = [cosine((embed or bag_of_words)(e.text), (embed or bag_of_words)(t))
                for t in texts]
        if sims and max(sims) >= QUALITATIVE_AGREEMENT_FLOOR:
            record["signals"].append(DEMOTION_REVIEW)
            record.setdefault("demotion_review", []).append({
                "source": e.source, "url": e.url, "was_demoted_because": why,
                "detail": "its account agrees {:.2f} with a trusted column".format(
                    max(sims))})


def may_aggregate(record: dict) -> bool:
    """False when the record is MUST_UNPACK. Consumers ask before summarising."""
    return MUST_UNPACK not in (record.get("signals") or [])


# ---------------------------------------------------------------------------
# Per axis
# ---------------------------------------------------------------------------

def axis_tension(records: list, axis: str) -> dict:
    """Mean ET over active claims, PLUS the top 3 by ET, named.

    The mean alone is the thing that hides what matters: an axis of forty quiet
    claims and three that flatly contradict each other averages to a comfortable
    number. So the three worst are stored explicitly, with their ids, and a
    consumer that shows the mean without them is showing half the finding.
    """
    active = [r for r in records if r.get("axis") == axis]
    if not active:
        return {"axis": axis, "ts": _now(), "claims": 0,
                "et_axis": 0.0, "band": "green", "top3": [],
                "must_unpack": 0, "hard_faults": 0}
    ets = [float(r.get("epistemic_tension", 0.0)) for r in active]
    mean_et = sum(ets) / len(ets)
    top = sorted(active, key=lambda r: -float(r.get("epistemic_tension", 0.0)))[:3]
    return {
        "axis": axis, "ts": _now(), "claims": len(active),
        "et_axis": mean_et, "band": band(mean_et),
        "top3": [{"claim_id": r.get("claim_id"),
                  "epistemic_tension": r.get("epistemic_tension"),
                  "band": r.get("band"),
                  "faults": [f["kind"] for f in r.get("faults", [])]} for r in top],
        "must_unpack": sum(1 for r in active if not may_aggregate(r)),
        "hard_faults": sum(1 for r in active
                           if any(f["kind"] == HARD_FAULT for f in r.get("faults", []))),
    }


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def save_record(record: dict, store: Optional[pathlib.Path] = None) -> pathlib.Path:
    """Persist one claim record. Refuses any row that lost its url."""
    root = pathlib.Path(store) if store else STORE
    for column_rows in (record.get("columns") or {}).values():
        for row in column_rows:
            if not (row.get("url") or "").strip():
                raise LinkRequired(
                    "refusing to store claim {!r}: a column row from {!r} has no "
                    "url".format(record.get("claim_id"), row.get("source")))
    for row in record.get("demoted") or []:
        if not (row.get("url") or "").strip():
            raise LinkRequired(
                "refusing to store claim {!r}: a demoted row from {!r} has no "
                "url".format(record.get("claim_id"), row.get("source")))
    root.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(record.get("claim_id") or "claim"))
    path = root / "{}.json".format(safe)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_records(store: Optional[pathlib.Path] = None) -> list:
    root = pathlib.Path(store) if store else STORE
    out = []
    if not root.exists():
        return out
    for p in sorted(root.glob("*.json")):
        if p.name == "track_record.json":
            continue
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/three_columns.py --selftest")
    print("  repo base            {}".format(BASE))
    ok = True

    if INDEPENDENCE.exists():
        cls = json.loads(INDEPENDENCE.read_text(encoding="utf-8")).get("_classes") or {}
        print("  independence classes LIVE ({}: {})".format(len(cls), ", ".join(sorted(cls))))
        expected = set(COLUMNS) | {UNKNOWN_CLASS}
        if set(cls) != expected:
            print("    MISMATCH — this module's columns are {} plus the demoted "
                  "{}".format(", ".join(COLUMNS), UNKNOWN_CLASS))
            ok = False
    else:
        print("  independence classes INERT (no config/reporter_independence.json)")
        ok = False

    print("  store                {}  exists={}  ({} record(s))".format(
        STORE, STORE.exists(), len(load_records())))

    # Quantitative: three witnesses that overlap.
    ents = [
        Entry("StatOffice", "https://a/1", SELF_REPORTED, RATE, 5.0, 1.0),
        Entry("Satellite", "https://b/2", INDEPENDENT, RATE, 5.5, 1.0),
        Entry("Watchdog", "https://c/3", ADVERSARIAL, RATE, 6.0, 1.0),
    ]
    r = compare("selftest_overlap", "ENERGY_REVIEW", ents, track={})
    print("  overlapping           intersection={} consensus={} ET={:.3f} ({})".format(
        r["intersection"], r["consensus"], r["epistemic_tension"], r["band"]))
    assert r["consensus"] == 5.5, r["consensus"]

    # Quantitative: no overlap at all.
    ents2 = [
        Entry("StatOffice", "https://a/1", SELF_REPORTED, RATE, 2.0, 0.1),
        Entry("Satellite", "https://b/2", INDEPENDENT, RATE, 9.0, 0.1),
        Entry("Watchdog", "https://c/3", ADVERSARIAL, RATE, 20.0, 0.1),
    ]
    r2 = compare("selftest_hardfault", "ENERGY_REVIEW", ents2, track={})
    kinds = [f["kind"] for f in r2["faults"]]
    print("  contradicting         faults={} consensus={} ET={:.3f} may_aggregate={}".format(
        kinds, r2["consensus"], r2["epistemic_tension"], may_aggregate(r2)))
    assert HARD_FAULT in kinds and r2["consensus"] is None

    # Qualitative: two different stories.
    q = [
        Entry("Ministry", "https://a/1", SELF_REPORTED, CLAIM,
              text="The election was free, fair and widely praised."),
        Entry("Observers", "https://b/2", INDEPENDENT, CLAIM,
              text="Ballot stuffing was recorded at hundreds of polling stations."),
    ]
    rq = compare("selftest_qual", "GOVERNANCE_INSTITUTIONS_REVIEW", q, track={})
    print("  two stories           faults={} consensus={} ET={:.3f} ({})".format(
        [f["kind"] for f in rq["faults"]], rq["consensus"],
        rq["epistemic_tension"], rq["band"]))
    assert rq["consensus"] is None, "a qualitative claim was given a consensus value"

    # Rehabilitation.
    track = note_physical_check({}, "OldSource", RATE, confirmed=False)
    ents3 = ents + [Entry("OldSource", "https://d/4", INDEPENDENT, RATE, 5.4, 0.2)]
    r3 = compare("selftest_rehab", "ENERGY_REVIEW", ents3, track=track)
    print("  demoted-but-right     signals={} demoted_rows={}".format(
        r3["signals"], len(r3["demoted"])))
    assert DEMOTION_REVIEW in r3["signals"]

    print("  axis roll-up          {}".format(
        {k: v for k, v in axis_tension([r, r2], "ENERGY_REVIEW").items()
         if k in ("claims", "et_axis", "band", "must_unpack", "hard_faults")}))

    try:
        Entry("NoLink", "", INDEPENDENT, RATE, 1.0)
        print("  link-required        BROKEN — an entry with no url was accepted")
        ok = False
    except LinkRequired:
        print("  link-required        enforced at construction")

    print("  cockpit / scoring    NOT WIRED — nothing writes these records and "
          "nothing reads them; ET reaches no display yet")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())


# ===========================================================================
# THE FIVE DISPLAY COLUMNS — a refinement of the four classes, not a fifth one
# ===========================================================================
# Emil's ruling, 22 August 2026: the cockpit shows FIVE columns —
# PHYSICAL | SCIENCE | OFFICIAL | NATIONAL | FREE.
#
# THIS IS NOT A FIFTH INDEPENDENCE CLASS, and the distinction is load-bearing.
# CLAUDE.md says config/reporter_independence.json defines exactly four classes
# and no fifth may be invented; COLUMNS above still holds exactly the three
# placeable ones, and the test that pins them to the config still passes
# unchanged. What is added here is a finer PARTITION of those same classes for
# display:
#
#     PHYSICAL   refines independent    a sensor this machine can read
#     SCIENCE    refines independent    peer review
#     OFFICIAL   refines self_reported  an international body aggregating states
#     NATIONAL   refines self_reported  the state measuring itself
#     FREE       refines adversarial    press, NGOs, anyone with no seat at the table
#
# WHAT MAKES SOMETHING A COLUMN
# ------------------------------
# A column must have an INDEPENDENT INPUT PIPELINE: a different API, a hardware
# sensor, or a peer-review process, queryable without an LLM intermediary. Two
# columns sharing a scraper or an LLM summariser are ECHO, not columns. Maximum
# five. That criterion is not decoration — it is checked, in
# assert_columns_independent(), and it has teeth on this repo's real data:
#
#     OFFICIAL and NATIONAL can share their upstream measurer. The World Bank
#     does not measure safe water access; national statistical offices do, and
#     the Bank aggregates them. config/reporter_independence.json says so in its
#     own words: "Includes AGGREGATORS of national reporting — the aggregator is
#     not the measurer."
#
# So an OFFICIAL row whose upstream is a national office is marked echo_of
# NATIONAL and is EXCLUDED from the independent-witness count. It still renders,
# in its own column, with the badge. Hiding it would lose information; counting
# it as a second witness would manufacture agreement out of one measurement
# quoted twice, which is the exact failure this whole module exists to catch.

PHYSICAL, SCIENCE, OFFICIAL, NATIONAL, FREE = (
    "physical", "science", "official", "national", "free")
DISPLAY_COLUMNS = (PHYSICAL, SCIENCE, OFFICIAL, NATIONAL, FREE)

# Pipeline kinds that satisfy the criterion. An LLM is deliberately not one.
HARDWARE, PEER_REVIEW, API, EDITORIAL = "hardware", "peer_review", "api", "editorial"
PIPELINE_KINDS = (HARDWARE, PEER_REVIEW, API, EDITORIAL)

# The lifecycle state a row defaults to. NAMED HERE so nobody has to guess:
# core/source_lifecycle.py's ladder is CANDIDATE -> TRUSTED -> DEMOTED. There is
# no SHADOW state in it. "SHADOW" exists only as a ROW STATUS in
# scripts/openclaw_axis_worker.py, for a reading stored but not believed. The
# columns panel displays the SOURCE_LIFECYCLE state, and says so in its legend.
CANDIDATE_STATE = "CANDIDATE"
LIFECYCLE_LADDER = "CANDIDATE -> TRUSTED -> DEMOTED (core/source_lifecycle.py)"

# Badges and coverage labels.
NO_PHYSICAL = "no physical coverage"
INVALID = "INVALID"

# Every ET value carries one of these. The label is not decoration: an ET of 0.1
# agreed by two institutions that both read the same press release means
# something different from an ET of 0.1 where one of the witnesses is a sensor,
# and a number without that label invites the reader to treat them as equal.
ANCHORED = "physically anchored"
UNANCHORED = "unanchored"


@dataclass(frozen=True)
class DisplayColumn:
    """One visible column and the pipeline that makes it independent."""
    key: str
    title: str
    refines: str            # which of the three independence classes
    pipeline: str           # the concrete pipeline id
    pipeline_kind: str      # HARDWARE | PEER_REVIEW | API | EDITORIAL
    why: str


COLUMN_SPEC = {
    PHYSICAL: DisplayColumn(
        PHYSICAL, "PHYSICAL", INDEPENDENT, "local_hardware_sensors", HARDWARE,
        "sensors on this machine. No API, no publisher, nothing to persuade."),
    SCIENCE: DisplayColumn(
        SCIENCE, "SCIENCE", INDEPENDENT, "peer_review_archives", PEER_REVIEW,
        "arXiv/DOI/journals. The pipeline is refereeing, not an endpoint."),
    OFFICIAL: DisplayColumn(
        OFFICIAL, "OFFICIAL", SELF_REPORTED, "international_institution_api", API,
        "WHO/World Bank/UN endpoints. Often an AGGREGATOR — see echo_of."),
    NATIONAL: DisplayColumn(
        NATIONAL, "NATIONAL", SELF_REPORTED, "national_statistical_api", API,
        "the state measuring itself. Its own jurisdiction, its own number."),
    FREE: DisplayColumn(
        FREE, "FREE", ADVERSARIAL, "open_press_and_ngo_feeds", EDITORIAL,
        "press, NGOs, anyone whose interest is not the subject's. Holds DEMOTED."),
}


def assert_columns_independent(spec: Optional[dict] = None) -> list:
    """Violations of the column criterion. An empty list means the five are five.

    Returns rather than raises: the point is to SHOW the reader where two
    columns lean on one pipeline, not to refuse to render.
    """
    spec = spec if spec is not None else COLUMN_SPEC
    problems = []
    if len(spec) > 5:
        problems.append("more than five columns: {}".format(sorted(spec)))
    seen = {}
    for key in sorted(spec):
        col = spec[key]
        if col.pipeline_kind not in PIPELINE_KINDS:
            problems.append("{}: {!r} is not an input pipeline kind".format(
                key, col.pipeline_kind))
        if col.pipeline in seen:
            problems.append(
                "{} and {} share the pipeline {!r} — that is echo, not two "
                "columns".format(seen[col.pipeline], key, col.pipeline))
        seen[col.pipeline] = key
        if col.refines not in COLUMNS:
            problems.append("{}: refines {!r}, which is not one of the three "
                            "independence classes".format(key, col.refines))
    return problems


def display_row(raw: dict) -> dict:
    """One raw source row -> one renderable row. NEVER raises, never hides.

    A row without a url is not dropped and not corrected: it comes back with
    valid=False so the panel renders it INVALID in red. Entry() raises on a
    missing url because a claim being COMPARED must be openable; a row being
    DISPLAYED must be visible precisely when it is broken, or the reader never
    learns the pipeline is producing junk.
    """
    url = str(raw.get("url") or "").strip()
    column = str(raw.get("display_column") or "").strip().lower()
    row = {
        "source": raw.get("source") or raw.get("source_id") or "(unnamed)",
        "url": url,
        "display_column": column if column in DISPLAY_COLUMNS else "",
        "claim_type": raw.get("claim_type") or CLAIM,
        "estimate": raw.get("estimate"),
        "error": raw.get("error", 0.0),
        "text": raw.get("text") or raw.get("claim_text") or "",
        "ts": raw.get("ts"),
        "lifecycle_state": raw.get("lifecycle_state") or CANDIDATE_STATE,
        "echo_of": raw.get("echo_of") or None,
        "valid": True,
        "invalid_reason": None,
        "demoted": False,
        "demoted_because": None,
        "rehabilitation": None,
    }
    if not url:
        row["valid"] = False
        row["invalid_reason"] = "no url — a claim nobody can open is not evidence"
    elif not row["display_column"]:
        row["valid"] = False
        row["invalid_reason"] = "no display column: {!r} is not one of {}".format(
            raw.get("display_column"), ", ".join(DISPLAY_COLUMNS))
    return row


def _rehabilitation_of(source: str, claim_type: str, track: dict) -> dict:
    """What it would take for this source to be believed again."""
    rec = ((track.get(source) or {}).get(claim_type) or {})
    return {
        "physical_checks": int(rec.get("physical_checks") or 0),
        "falsified_by_physical": int(rec.get("falsified_by_physical") or 0),
        "note": ("rehabilitation is earned by physical checks that do NOT "
                 "falsify. Nothing here is deleted and nothing expires by time."),
    }


def five_column_view(claim_id: str, axis: str, raw_rows: list,
                     track: Optional[dict] = None) -> dict:
    """The cockpit's view of one claim across five columns.

    ET IS COMPUTED OVER ALL FIVE, with two rules that change the arithmetic:

      * ET is computed whenever TWO INDEPENDENT WITNESSES exist. PHYSICAL is one
        possible witness and never an entry ticket — the earlier rule made ET
        None without a sensor, which silenced it for essentially every world
        statistic and turned a missing anchor into a missing number.
      * witnesses are keyed by UPSTREAM MEASURER. An ECHO row (OFFICIAL
        aggregating NATIONAL) collapses into the column it echoes rather than
        voting twice; it still renders, in its own column, with the badge.
      * every ET carries a coverage label naming the participating columns and
        saying whether PHYSICAL was among them: anchored or unanchored.

    Demoted rows are visible INSIDE their column with reason and rehabilitation
    status, and collected into `demoted` for the FREE panel. No voice is ever
    deleted, and falsified_by_physical keeps writing track records either way.
    """
    track = track if track is not None else load_track_record()
    rows = [display_row(r) for r in raw_rows]

    cols = {c: [] for c in DISPLAY_COLUMNS}
    invalid = []
    for row in rows:
        if not row["valid"]:
            invalid.append(row)
        # An invalid row still belongs to the column it named, so it renders in
        # place rather than in an orphan bin nobody scrolls to. A row that named
        # no column at all goes to FREE, visibly broken.
        cols[row["display_column"] or FREE].append(row)

    demoted = []
    for col_key, col_rows in cols.items():
        refines = (COLUMN_SPEC[col_key].refines
                   if col_key in COLUMN_SPEC else UNKNOWN_CLASS)
        for row in col_rows:
            dem, why = is_demoted(row["source"], row["claim_type"], refines, track)
            row["demoted"] = bool(dem)
            row["demoted_because"] = why if dem else None
            if dem:
                row["rehabilitation"] = _rehabilitation_of(
                    row["source"], row["claim_type"], track)
                demoted.append({**row, "was_column": col_key})

    physical_rows = [r for r in cols[PHYSICAL] if r["valid"] and not r["demoted"]]
    has_physical = bool(physical_rows)

    # ── WITNESSES, AND WHAT MAKES TWO OF THEM ONE (22 Aug 2026) ───────────
    # A witness is keyed by its UPSTREAM MEASURER, not by the column it renders
    # in. A row that declares echo_of collapses into the column it is echoing,
    # so OFFICIAL aggregating NATIONAL is one witness quoted twice rather than
    # two witnesses agreeing. Every row still RENDERS, in its own column, with
    # its badge; what it loses is a second vote it never earned.
    witness_rows = [(c, r) for c in DISPLAY_COLUMNS for r in cols[c]
                    if r["valid"] and not r["demoted"]]
    upstream_of = {}
    for col_key, row in witness_rows:
        upstream_of.setdefault(row["echo_of"] or col_key, []).append((col_key, row))

    witnesses = [(k, rows) for k, rows in upstream_of.items()]
    echoes = [r for c in DISPLAY_COLUMNS for r in cols[c] if r["echo_of"]]

    participating = sorted({c for _, rows in witnesses for c, _ in rows})
    classes = sorted({COLUMN_SPEC[c].refines for c in participating
                      if c in COLUMN_SPEC})

    badges = []
    if not has_physical:
        badges.append(NO_PHYSICAL)
    if invalid:
        badges.append("{} INVALID row(s)".format(len(invalid)))
    if echoes:
        badges.append("{} echo row(s) not counted as a second witness".format(
            len(echoes)))

    # ── ET IS COMPUTED ON TWO INDEPENDENT WITNESSES. PHYSICAL IS NOT A GATE.
    # The rule this replaces made ET None whenever no local sensor covered the
    # claim, which silenced it for essentially every world statistic — verified
    # on safe-water-access BG. That inverted the intent: the ABSENCE of a
    # physical anchor is something the reader must SEE, not something that
    # removes the number they were reading. So ET is now computed whenever two
    # independent witnesses exist, and every value carries a coverage label
    # saying which columns took part and whether PHYSICAL was one of them.
    #
    # PHYSICAL is one possible witness. It is never an entry ticket.
    et, et_band, undefined_reason = None, None, None

    quantitative = []
    for key, rows in witnesses:
        for _, row in rows:
            if row.get("estimate") is not None:
                e = abs(float(row.get("error") or 0.0))
                quantitative.append((key, (float(row["estimate"]) - e,
                                           float(row["estimate"]) + e)))
                break                       # one interval per WITNESS, not per row

    qualitative_texts = []
    for key, rows in witnesses:
        for _, row in rows:
            if (row.get("text") or "").strip():
                qualitative_texts.append((key, row["text"]))
                break

    if len(witnesses) < 2:
        undefined_reason = (
            "one witness, echo not counted" if echoes else
            "{} independent witness(es); ET needs two".format(len(witnesses)))
    elif len(quantitative) >= 2:
        et = epistemic_tension_quantitative([iv for _, iv in quantitative])
        et_band = band(et)
    elif len(qualitative_texts) >= 2:
        et = epistemic_tension_qualitative([t for _, t in qualitative_texts])
        et_band = band(et)
    else:
        undefined_reason = (
            "{} independent witnesses, but fewer than two carry a comparable "
            "value".format(len(witnesses)))

    coverage = {
        "witnesses": len(witnesses),
        "columns": participating,
        "independence_classes": classes,
        "physical": has_physical,
        "label": ANCHORED if has_physical else UNANCHORED,
        "echo_collapsed": len(echoes),
        "undefined_reason": undefined_reason,
    }

    return {
        "claim_id": claim_id,
        "axis": axis,
        "ts": _now(),
        "columns": cols,
        "column_order": list(DISPLAY_COLUMNS),
        "column_spec": {k: asdict(v) for k, v in COLUMN_SPEC.items()},
        "independence_violations": assert_columns_independent(),
        "physical_coverage": has_physical,
        "independent_witnesses": len(witnesses),
        "epistemic_tension": et,
        "band": et_band,
        "coverage": coverage,
        "badges": badges,
        "invalid": invalid,
        "demoted": demoted,
        "lifecycle_ladder": LIFECYCLE_LADDER,
    }
