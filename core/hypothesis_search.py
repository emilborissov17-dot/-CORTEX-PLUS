#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/hypothesis_search.py — LOOK FOR SOMETHING, INSTEAD OF LOOKING AROUND.

WHAT IT REPLACES
-----------------
Collection today is recall-shaped: for each axis, hit the same feeds and keep
whatever arrives. Nothing is being LOOKED FOR, so nothing can be found or not
found, and there is no way to tell a fetch that settled a question from one that
added another article to a pile.

This turns a question into queries and then judges whether the queries answered
it. Three parts, and the middle one is deliberately not clever:

  (a) a prompt for the warm 3b that asks for hypotheses, validated FAIL-CLOSED
  (b) a DETERMINISTIC hypothesis -> query mapper. Codes come from a dict; no
      exact match means SKIP, never guess
  (c) a ledger that adjudicates each hypothesis after 3 cycles and prioritises
      the next round by INFORMATION GAIN PER FETCH, not by how much came back

FAIL-CLOSED, AND WHAT THAT COSTS
---------------------------------
Zero hypotheses is a valid outcome. An invented one is not. The 3b model is
small and returns malformed JSON often enough that a lenient parser would be
manufacturing research questions out of parse errors — and a hypothesis is not a
harmless artifact: it decides what the system spends its next fetches on. So a
malformed item is DROPPED and counted, a malformed payload yields an empty list,
and nothing is ever repaired by guessing.

WHY THE CODE MAPPER IS A DICT AND NOT A MODEL
----------------------------------------------
GDELT theme codes are a controlled vocabulary. A model asked to produce one will
produce something that LOOKS like one — ENV_CLIMATE_CHANGE instead of
ENV_CLIMATECHANGE — and GDELT answers a wrong-but-well-formed code with an empty
result set, which is indistinguishable from "nothing is happening". A dict with
no entry simply skips that source and says so.

The free-text query variants (YouTube, GitHub) DO come from the model, because
there is no controlled vocabulary to get wrong, and they ride in the SAME batch
call as the hypotheses — one model call per axis, not two.

NOT WIRED. Nothing calls this. `ask` is injected, and defaults to None, so a
caller must hand it a model deliberately.

    venv\\Scripts\\python.exe core/hypothesis_search.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
LEDGER = BASE / "memory" / "hypotheses.jsonl"
KNOWLEDGE_BASE = BASE / "memory" / "knowledge_base.json"
ORCHESTRATION = BASE / "memory" / "orchestration_grounded_latest.json"

HYPOTHESES_PER_CALL = 5
CYCLES_BEFORE_VERDICT = 3

PENDING, CONFIRMED, FALSIFIED, UNKNOWN = "pending", "confirmed", "falsified", "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# (a) The prompt, and the fail-closed contract
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    hypothesis: str
    seeking: list
    confidence: float
    axis: str = ""
    youtube: list = field(default_factory=list)
    github: list = field(default_factory=list)

    @property
    def id(self) -> str:
        return hashlib.sha1(
            "{}|{}".format(self.axis, self.hypothesis).encode("utf-8")
        ).hexdigest()[:12]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d


def recent_claims(axis: str, limit: int = 20,
                  kb: Optional[dict] = None) -> list:
    """The last `limit` claims for this axis, with whatever status is on record.

    HONEST NOTE ON THE SCHEMA, because the shape is not what one would expect.
    memory/knowledge_base.json is {axis: {cycle_count, key_insights: [str]}} —
    plain strings, with NO confirmed/falsified/pending marking anywhere. So the
    status reported here is `pending` for every existing claim, and that is a
    statement about the store, not a default this module chose. The ledger in
    part (c) is what begins recording real verdicts; as those accumulate they are
    joined in below, so this function tells the truth on both sides of that gap.
    """
    if kb is None:
        try:
            kb = json.loads(KNOWLEDGE_BASE.read_text(encoding="utf-8"))
        except Exception:
            kb = {}
    entry = kb.get(axis) or {}
    insights = entry.get("key_insights") or []
    if not isinstance(insights, list):
        return []
    verdicts = _verdicts_by_text(axis)
    out = []
    for text in insights[-limit:]:
        if not isinstance(text, str) or not text.strip():
            continue
        out.append({"claim": text.strip()[:400],
                    "status": verdicts.get(text.strip()[:400], PENDING)})
    return out


def _verdicts_by_text(axis: str) -> dict:
    """{claim text: status} for hypotheses this module has already adjudicated."""
    out = {}
    for rec in read_ledger():
        if rec.get("axis") == axis and rec.get("status") in (CONFIRMED, FALSIFIED):
            out[str(rec.get("hypothesis", ""))[:400]] = rec["status"]
    return out


def priorities(orchestration: Optional[dict] = None) -> dict:
    """{'THREAT': [...], 'WATCH': [...]} from core/orchestrator_grounded's output."""
    if orchestration is None:
        try:
            orchestration = json.loads(ORCHESTRATION.read_text(encoding="utf-8"))
        except Exception:
            orchestration = {}
    sets = orchestration.get("sets") or {}
    return {"THREAT": list(sets.get("THREAT") or []),
            "WATCH": list(sets.get("WATCH") or [])}


def build_prompt(axis: str, prio: Optional[dict] = None,
                 claims: Optional[list] = None,
                 n: int = HYPOTHESES_PER_CALL) -> str:
    """The batch prompt: hypotheses AND their free-text query variants, at once.

    Written for a 3b model, so: the contract is stated twice, the example is
    complete rather than elided, and there is an explicit instruction that fewer
    than n is acceptable. A small model told "give me exactly 5" will pad to five
    with restatements of the axis name, and padding is the failure this whole
    module is trying to avoid.
    """
    prio = prio if prio is not None else priorities()
    claims = claims if claims is not None else recent_claims(axis)
    threat = ", ".join(prio.get("THREAT") or []) or "(none)"
    watch = ", ".join(prio.get("WATCH") or []) or "(none)"

    known = "\n".join(
        "  [{}] {}".format(c.get("status", PENDING), str(c.get("claim", ""))[:200])
        for c in claims) or "  (nothing on record for this axis yet)"

    return (
        "You are the research planner for one axis of a world-monitoring system.\n"
        "AXIS: {axis}\n"
        "Axes currently classed THREAT: {threat}\n"
        "Axes currently classed WATCH:  {watch}\n"
        "\n"
        "What this axis already believes (status in brackets):\n"
        "{known}\n"
        "\n"
        "Propose up to {n} HYPOTHESES that are worth testing against new "
        "documents in the next 24 hours. A good hypothesis is one that new "
        "evidence could CONFIRM OR REFUTE. Do not restate what is already "
        "confirmed. Do not propose anything that cannot be checked against a "
        "published document.\n"
        "\n"
        "FEWER IS BETTER THAN PADDED. If only two are worth testing, return two. "
        "If none are, return an empty list.\n"
        "\n"
        "Answer with JSON only, no prose, in exactly this shape:\n"
        "{{\"hypotheses\": [\n"
        "  {{\"hypothesis\": \"one testable sentence\",\n"
        "    \"seeking\": [\"the specific thing a document would have to show\"],\n"
        "    \"confidence\": 0.4,\n"
        "    \"youtube\": [\"search phrase\", \"another phrase\"],\n"
        "    \"github\": [\"search phrase\"]}}\n"
        "]}}\n"
        "\n"
        "Rules: hypothesis is a non-empty sentence. seeking is a non-empty list "
        "of short strings. confidence is a number between 0 and 1. youtube and "
        "github are 2-3 short search phrases each; omit them rather than "
        "inventing.\n"
    ).format(axis=axis, threat=threat, watch=watch, known=known, n=n)


def _extract_json(raw: str) -> Optional[object]:
    """The outermost JSON object/array in `raw`, or None. Never repairs."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    # Try whichever bracket opens FIRST. Found by test: a bare list of hypotheses
    # `[{"hypothesis": ...}]` contains a `{`, so trying objects first matched the
    # inner element, parsed it successfully, and returned a dict with no
    # "hypotheses" key — a valid reply rejected as malformed.
    candidates = []
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if i >= 0 and j > i:
            candidates.append((i, text[i:j + 1]))
    for _, blob in sorted(candidates):
        try:
            return json.loads(blob)
        except ValueError:
            continue
    return None


def _clean_phrases(value, cap: int = 3) -> list:
    """Up to `cap` non-empty short strings, or []. Never invents one."""
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        if isinstance(v, str) and v.strip():
            out.append(v.strip()[:120])
        if len(out) >= cap:
            break
    return out


def parse_hypotheses(raw: str, axis: str = "",
                     n: int = HYPOTHESES_PER_CALL) -> tuple:
    """(hypotheses, rejections) — STRICT. Returns ([], [...]) on junk.

    Every rejection carries its reason, because "the model gave us nothing" and
    "the model gave us five things and all five were malformed" are different
    facts about the model, and only the second one is a bug worth chasing.
    """
    rejections = []
    data = _extract_json(raw)
    if data is None:
        return [], [{"reason": "no JSON object or array in the reply",
                     "sample": (raw or "")[:160]}]

    items = data.get("hypotheses") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return [], [{"reason": "payload has no 'hypotheses' list",
                     "sample": json.dumps(data, ensure_ascii=False)[:160]}]

    out = []
    for idx, item in enumerate(items):
        if len(out) >= n:
            rejections.append({"reason": "beyond the {} asked for".format(n),
                               "index": idx})
            continue
        bad = _why_invalid(item)
        if bad:
            rejections.append({"reason": bad, "index": idx,
                               "sample": json.dumps(item, ensure_ascii=False)[:160]
                               if not isinstance(item, str) else item[:160]})
            continue
        out.append(Hypothesis(
            hypothesis=item["hypothesis"].strip()[:400],
            seeking=[s.strip()[:200] for s in item["seeking"]
                     if isinstance(s, str) and s.strip()],
            confidence=float(item["confidence"]),
            axis=axis,
            youtube=_clean_phrases(item.get("youtube")),
            github=_clean_phrases(item.get("github")),
        ))
    return out, rejections


def _why_invalid(item) -> Optional[str]:
    if not isinstance(item, dict):
        return "not an object"
    h = item.get("hypothesis")
    if not isinstance(h, str) or not h.strip():
        return "hypothesis missing or not a non-empty string"
    seeking = item.get("seeking")
    if not isinstance(seeking, list) or not seeking:
        return "seeking missing or not a non-empty list"
    if not any(isinstance(s, str) and s.strip() for s in seeking):
        return "seeking contains no usable string"
    c = item.get("confidence")
    if isinstance(c, bool) or not isinstance(c, (int, float)):
        return "confidence missing or not a number"
    if not (0.0 <= float(c) <= 1.0):
        return "confidence {} is outside [0,1]".format(c)
    return None


def propose(axis: str, ask: Optional[Callable] = None, **kw) -> tuple:
    """Ask the warm 3b for hypotheses. `ask(prompt) -> str`.

    INJECTED, and there is no default. A module that reaches for its own model
    can be made to call one by any caller that forgets to stub it, and this one
    is meant to run on the small local model only.
    """
    if ask is None:
        raise ValueError(
            "hypothesis_search.propose needs an `ask` callable; it does not "
            "choose a model for itself")
    prompt = build_prompt(axis, **kw)
    try:
        raw = ask(prompt)
    except Exception as e:
        return [], [{"reason": "the model call failed: {}: {}".format(
            type(e).__name__, e)}]
    return parse_hypotheses(raw, axis=axis)


# ---------------------------------------------------------------------------
# (b) The deterministic mapper
# ---------------------------------------------------------------------------

# GDELT GKG themes are a CONTROLLED VOCABULARY. An axis with no entry here is
# skipped, never guessed — a wrong-but-well-formed code returns an empty result
# set, which reads exactly like "nothing is happening in the world".
GDELT_THEMES = {
    "CLIMATE_GLOBAL_RISK_REVIEW": "ENV_CLIMATECHANGE",
    "ENERGY_REVIEW": "ENV_OIL",
    "WATER_REVIEW": "ENV_WATERWAYS",
    "FOOD_REVIEW": "FOOD_SECURITY",
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": "ENV_BIODIVERSITY",
    "MATERIALS_WASTE_REVIEW": "ENV_MINING",
    "ECONOMY_WORK_REVIEW": "ECON_STOCKMARKET",
    "INEQUALITY_POVERTY_REVIEW": "POVERTY",
    "GOVERNANCE_INSTITUTIONS_REVIEW": "DEMOCRACY",
    "SOCIAL_RELATIONS_REVIEW": "SOC_GENERALPOPULATION",
    "HUMAN_WELL_BEING_REVIEW": "WB_2670_JOBS",
    "EDUCATION_CULTURE_REVIEW": "EDUCATION",
    "TECHNOLOGY_AI_REVIEW": "SCIENCE",
    "INFRASTRUCTURE_CITIES_REVIEW": "URBAN",
}

# FIPS 10-4 country codes, which is what GDELT's `locationcc` expects — NOT
# ISO-3166. The two disagree on exactly the cases that matter (UK is "UK" in
# FIPS and "GB" in ISO), so mixing them yields silent empty results.
GDELT_LOCATIONS = {
    "world": None,          # no location filter
    "united states": "US",
    "china": "CH",
    "india": "IN",
    "germany": "GM",
    "united kingdom": "UK",
    "russia": "RS",
    "brazil": "BR",
    "bulgaria": "BU",
}

GDELT_TIMESPANS = {"24h": "1d", "7d": "7d", "30d": "1m"}

ARXIV_CATEGORIES = {
    "CLIMATE_GLOBAL_RISK_REVIEW": "physics.ao-ph",
    "ENERGY_REVIEW": "eess.SY",
    "WATER_REVIEW": "physics.ao-ph",
    "FOOD_REVIEW": "q-bio.PE",
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": "q-bio.PE",
    "MATERIALS_WASTE_REVIEW": "cond-mat.mtrl-sci",
    "HUMAN_WELL_BEING_REVIEW": "q-bio.NC",
    "SOCIAL_RELATIONS_REVIEW": "cs.SI",
    "EDUCATION_CULTURE_REVIEW": "cs.CY",
    "TECHNOLOGY_AI_REVIEW": "cs.AI",
    "ECONOMY_WORK_REVIEW": "econ.GN",
    "GOVERNANCE_INSTITUTIONS_REVIEW": "cs.CY",
}


def to_queries(h: Hypothesis, axis: Optional[str] = None,
               location: str = "world", timespan: str = "24h") -> list:
    """Hypothesis -> concrete queries. Pure, deterministic, and skips what it
    cannot address.

    Returns a list of {source, query, url, skipped_reason}. A source that cannot
    be addressed appears with `skipped_reason` rather than being silently absent:
    the caller needs to be able to tell "we looked and found nothing" from "we
    never looked".
    """
    axis = axis or h.axis
    out = []

    theme = GDELT_THEMES.get(axis)
    if not theme:
        out.append({"source": "GDELT", "query": None, "url": None,
                    "skipped_reason": "no GDELT theme code for axis {!r} — "
                                      "skipping rather than guessing one".format(axis)})
    elif location not in GDELT_LOCATIONS:
        out.append({"source": "GDELT", "query": None, "url": None,
                    "skipped_reason": "no FIPS code for location {!r}".format(location)})
    elif timespan not in GDELT_TIMESPANS:
        out.append({"source": "GDELT", "query": None, "url": None,
                    "skipped_reason": "unknown timespan {!r}".format(timespan)})
    else:
        parts = ["theme:{}".format(theme)]
        cc = GDELT_LOCATIONS[location]
        if cc:
            parts.append("locationcc:{}".format(cc))
        q = " ".join(parts)
        out.append({
            "source": "GDELT", "query": q, "skipped_reason": None,
            "url": "https://api.gdeltproject.org/api/v2/doc/doc?query={}"
                   "&mode=artlist&maxrecords=8&format=json&timespan={}".format(
                       _quote(q), GDELT_TIMESPANS[timespan])})

    cat = ARXIV_CATEGORIES.get(axis)
    term = _first_term(h.seeking)
    if not cat:
        out.append({"source": "arXiv", "query": None, "url": None,
                    "skipped_reason": "no arXiv category for axis {!r}".format(axis)})
    elif not term:
        out.append({"source": "arXiv", "query": None, "url": None,
                    "skipped_reason": "hypothesis names nothing to seek"})
    else:
        q = "cat:{}+AND+all:{}".format(cat, _quote(term))
        out.append({
            "source": "arXiv", "query": q, "skipped_reason": None,
            "url": "https://export.arxiv.org/api/query?search_query={}"
                   "&max_results=8&sortBy=submittedDate&sortOrder=descending".format(q)})

    for phrase in h.youtube:
        out.append({"source": "YouTube", "query": phrase, "skipped_reason": None,
                    "url": "https://www.youtube.com/results?search_query={}".format(
                        _quote(phrase))})
    if not h.youtube:
        out.append({"source": "YouTube", "query": None, "url": None,
                    "skipped_reason": "the model offered no search phrases"})

    for phrase in h.github:
        out.append({"source": "GitHub", "query": phrase, "skipped_reason": None,
                    "url": "https://api.github.com/search/repositories?q={}"
                           "&sort=updated&per_page=5".format(_quote(phrase))})
    if not h.github:
        out.append({"source": "GitHub", "query": None, "url": None,
                    "skipped_reason": "the model offered no search phrases"})
    return out


def _quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(str(s))


def _first_term(seeking: list) -> Optional[str]:
    """ONE term from `seeking` — the first usable one, by position.

    By position and not by "the best one": any ranking here would be a second,
    undocumented opinion about what the hypothesis is about, competing with the
    model's own ordering. First is a rule; best is a guess.
    """
    for s in seeking or []:
        word = re.sub(r"[^A-Za-z0-9 \-]", " ", str(s)).strip()
        if len(word) >= 3:
            return " ".join(word.split()[:4])
    return None


# ---------------------------------------------------------------------------
# (c) The ledger
# ---------------------------------------------------------------------------

def read_ledger(path: Optional[pathlib.Path] = None) -> list:
    """The CURRENT state of each hypothesis — last record per id wins."""
    p = pathlib.Path(path) if path else LEDGER
    latest: dict = {}
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue        # a torn final line must not lose the rest
            if rec.get("id"):
                latest[rec["id"]] = rec
    except OSError:
        return []
    return list(latest.values())


def _append(rec: dict, path: Optional[pathlib.Path] = None) -> dict:
    p = pathlib.Path(path) if path else LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def open_hypothesis(h: Hypothesis, path: Optional[pathlib.Path] = None) -> dict:
    """Record a new hypothesis, or return the existing one untouched."""
    existing = {r["id"]: r for r in read_ledger(path)}
    if h.id in existing:
        return existing[h.id]
    return _append({
        "id": h.id, "ts": _now(), "axis": h.axis,
        "hypothesis": h.hypothesis, "seeking": h.seeking,
        "confidence_initial": h.confidence,
        "cycles": 0, "docs_fetched": 0,
        "docs_supporting": 0, "docs_refuting": 0,
        "urls": [], "status": PENDING,
    }, path)


def record_evidence(hid: str, urls: list, supporting: int = 0, refuting: int = 0,
                    path: Optional[pathlib.Path] = None) -> Optional[dict]:
    """One cycle's worth of evidence against a hypothesis.

    `urls` is what was actually fetched. supporting/refuting are the caller's
    judgement of how many of those DISCRIMINATED — bore on the question either
    way. Documents that merely mention the topic count as fetched and as neither,
    which is exactly the distinction information_gain_per_fetch is built on.
    """
    cur = {r["id"]: r for r in read_ledger(path)}.get(hid)
    if cur is None:
        return None
    urls = [u for u in (urls or []) if u]
    merged = list(dict.fromkeys(list(cur.get("urls") or []) + urls))
    rec = dict(cur)
    rec.update({
        "ts": _now(),
        "cycles": int(cur.get("cycles", 0)) + 1,
        "docs_fetched": int(cur.get("docs_fetched", 0)) + len(urls),
        "docs_supporting": int(cur.get("docs_supporting", 0)) + int(supporting),
        "docs_refuting": int(cur.get("docs_refuting", 0)) + int(refuting),
        "urls": merged[:200],
    })
    rec["status"] = adjudicate(rec)
    return _append(rec, path)


def adjudicate(rec: dict) -> str:
    """PENDING until CYCLES_BEFORE_VERDICT, then a verdict that can be UNKNOWN.

    UNKNOWN is a real outcome and is kept distinct from FALSIFIED. "Three cycles
    of looking turned up nothing that bore on this either way" says something
    about the SEARCH; "the evidence went against it" says something about the
    WORLD. Collapsing them would let a badly-formed query masquerade as a
    refutation.
    """
    if int(rec.get("cycles", 0)) < CYCLES_BEFORE_VERDICT:
        return PENDING
    s, r = int(rec.get("docs_supporting", 0)), int(rec.get("docs_refuting", 0))
    if s == 0 and r == 0:
        return UNKNOWN
    if s > r:
        return CONFIRMED
    if r > s:
        return FALSIFIED
    return UNKNOWN


def information_gain_per_fetch(rec: dict) -> float:
    """Fraction of fetched documents that DISCRIMINATED, in [0,1].

    THE POINT OF THE WHOLE MODULE IS IN THIS ONE FUNCTION, so the choice is
    spelled out. The obvious metric is recall — how many documents came back —
    and it is exactly wrong: it rewards a query that returns a hundred articles
    mentioning the topic over one that returns two that settle the question. What
    is scarce here is not documents, it is the cycle's time and the network.

    So: (supporting + refuting) / fetched. A hypothesis whose fetches keep
    landing on neither side scores near 0 and stops being asked. One never
    fetched for scores 1.0 — untried, therefore maximally worth trying, which is
    the right default for an explore/exploit trade with no data yet.
    """
    fetched = int(rec.get("docs_fetched", 0))
    if fetched <= 0:
        return 1.0
    discriminating = int(rec.get("docs_supporting", 0)) + int(rec.get("docs_refuting", 0))
    return max(0.0, min(1.0, discriminating / float(fetched)))


def prioritize(records: Optional[list] = None,
               path: Optional[pathlib.Path] = None, limit: int = 10) -> list:
    """Which hypotheses to spend the next round's fetches on.

    Settled ones are dropped — a confirmed or falsified hypothesis has no gain
    left. Ties break toward FEWER cycles spent, so a question that has been asked
    three times without resolving yields to one that has been asked once.
    """
    recs = records if records is not None else read_ledger(path)
    live = [r for r in recs if r.get("status") in (PENDING, UNKNOWN)]
    live.sort(key=lambda r: (-information_gain_per_fetch(r), int(r.get("cycles", 0))))
    return live[:limit]


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/hypothesis_search.py --selftest")
    print("  repo base            {}".format(BASE))
    ok = True

    kb_ok = KNOWLEDGE_BASE.exists()
    print("  knowledge_base.json  {}".format("LIVE" if kb_ok else "INERT"))
    if kb_ok:
        claims = recent_claims("ENERGY_REVIEW")
        print("    ENERGY_REVIEW      {} claim(s); statuses: {}".format(
            len(claims), sorted({c["status"] for c in claims}) or "(none)"))
        print("    NOTE: the store has no confirmed/falsified marking at all, so "
              "every existing claim reads `pending`. That is the schema, not a "
              "default chosen here; this module's ledger is what starts recording "
              "verdicts.")
    else:
        ok = False

    prio = priorities()
    print("  orchestration        {} (THREAT={}, WATCH={})".format(
        "LIVE" if ORCHESTRATION.exists() else "INERT",
        len(prio["THREAT"]), len(prio["WATCH"])))

    print("  GDELT themes         {} axes mapped".format(len(GDELT_THEMES)))
    print("  arXiv categories     {} axes mapped".format(len(ARXIV_CATEGORIES)))

    print("  ledger               {} exists={} ({} hypotheses)".format(
        LEDGER.name, LEDGER.exists(), len(read_ledger())))

    # Fail-closed, on the shapes a 3b actually produces.
    cases = [
        ("well formed", '{"hypotheses":[{"hypothesis":"h","seeking":["s"],'
                        '"confidence":0.5,"youtube":["a","b"]}]}', 1),
        ("truncated", '{"hypotheses":[{"hypothesis":"h","seeking":', 0),
        ("prose only", "Sure! Here are some hypotheses about energy.", 0),
        ("confidence as text", '{"hypotheses":[{"hypothesis":"h","seeking":["s"],'
                               '"confidence":"high"}]}', 0),
        ("empty list", '{"hypotheses":[]}', 0),
    ]
    for label, raw, expect in cases:
        got, rej = parse_hypotheses(raw, axis="X")
        mark = "ok " if len(got) == expect else "BAD"
        if len(got) != expect:
            ok = False
        print("    {} {:<20} -> {} kept, {} rejected".format(
            mark, label, len(got), len(rej)))

    h = Hypothesis("test", ["grid capacity"], 0.5, axis="ENERGY_REVIEW",
                   youtube=["grid storage"], github=["grid-sim"])
    qs = to_queries(h)
    print("  mapper               {} queries, {} skipped".format(
        sum(1 for q in qs if not q["skipped_reason"]),
        sum(1 for q in qs if q["skipped_reason"])))
    unmapped = Hypothesis("t", ["x"], 0.5, axis="NO_SUCH_AXIS")
    skipped = [q for q in to_queries(unmapped) if q["skipped_reason"]]
    print("    unmapped axis      {} sources skipped, none guessed".format(len(skipped)))

    print("  fast_cycle_runner    NOT WIRED — nothing proposes hypotheses; "
          "B_SENSE still collects by recall")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
