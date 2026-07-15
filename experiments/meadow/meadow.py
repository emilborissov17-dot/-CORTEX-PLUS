#!/usr/bin/env python3
"""
experiments/meadow/meadow.py — the system's first space for FREE, UNJUDGED thought.

KPI #6, the meadow. Everything built before this — gates, oracles, judges, the
promotion pipeline — is machinery for SELECTION. Selection presupposes something to
select from, and nothing yet produces it. The meadow is the generative half: a place
where the system thinks over its own world with nothing scoring the result.

THE DESIGN PRINCIPLE (why the input is WIDE and RAW)
---------------------------------------------------
A baby does not learn from indices. It learns from a flood of uncurated,
contradictory stimuli, and finding the structure in that flood IS the thinking. If
we pre-structure the input — hand the model five tidy scalars — we have already done
the exercise and stolen it from the model. So DIVERGE builds a wide, raw, rotating
slice of the world (news verbatim, transcripts verbatim, per-country numbers, the
system's own diary) and asks the model to find what repeats, what contradicts, what
is signal and what is noise. The one pre-digested part — the REAL_DATA axis summary —
is labelled as such, so the model knows which part somebody already chewed.

TWO PHASES, ONE SCRIPT
----------------------
DIVERGE  build the bundle, send it to the best available brain, write the raw reply
         VERBATIM to notebook/YYYY-MM-DD.md. No parsing. No validation. No PASS/FAIL.
COMMIT   feed the model its OWN notebook entry back and let it choose ONE thought, if
         any, to formalise as a testable hypothesis in committed/YYYY-MM-DD.json.
         "None of these are ready" is a legitimate answer. Not wired to any tracker.

ISOLATION (like pulse/dreams — see RULES in README)
---------------------------------------------------
* Writes ONLY under experiments/meadow/. Nothing else, ever.
* Reads news/, snapshots/, memory/, output/ as PLAIN FILES. It imports NO live-path
  pipeline module — not a scorer, agent, gate or tracker — so a change here cannot
  break the cycle and a change there cannot silently break the meadow.
* The ONE sanctioned exception is core.groq_backend.call_groq: the shared brain, a
  declared drop-in stable API, and a one-way dependency (meadow → core, never the
  reverse). Re-implementing its four-provider fallback chain would be strictly worse
  than importing it, and DIVERGE is thinking — it must use the best brain available.
  The WB indicator label map is copied in miniature (below) rather than imported, for
  the same reason dreams re-implements its JSON extractor: to stay decoupled.

CONSTITUTIONALLY UNJUDGED
-------------------------
There is no check.py for the DIVERGE output and there must never be one. Any
mechanical quality gate would be judgement, and judgement is exactly what the meadow
exists to be free of. The only quality signal is Emil reading the notebook.

NAME THE FAILURE IN ADVANCE (house rule)
----------------------------------------
The most likely failure is textbook association — "CO2 -> temperature", the kind of
sentence that could have been written without seeing today's bundle at all. There is
NO defence against this in DIVERGE, on purpose: a filter would be judgement. The test
is Emil reading the first page. If it reads like it never saw the slice, the meadow
grew weeds, and we fix the INPUT and the PROMPT — never the output.

THE GAUNTLET (--challenge)
--------------------------
Five variants provoke DIFFERENT capabilities over the SAME infrastructure — same bundle,
same notebook, same rules. Each appends a headed `## challenge:` section to today's page.
  mirror     feed the model its own latest base page; make it separate echo from insight
  advocate   feed VISION.md + the bundle; make it attack the vision with real numbers
  blindtest  run DIVERGE twice — real bundle vs one with salient numbers swapped — to
             see whether the thoughts track the data or come from memory (the key test)
  child      "from this data alone, what is the ONE thing you CANNOT explain?"
  synthesis  feed the whole day's notebook; one new sentence that connects it all

USAGE
-----
    venv/Scripts/python.exe experiments/meadow/meadow.py --dry-run   # print, write nothing
    venv/Scripts/python.exe experiments/meadow/meadow.py             # today's slice, real
    venv/Scripts/python.exe experiments/meadow/meadow.py --date 2026-07-14
    venv/Scripts/python.exe experiments/meadow/meadow.py --challenge blindtest
    venv/Scripts/python.exe experiments/meadow/meadow.py --challenge mirror --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent                        # experiments/meadow -> repo root
sys.path.insert(0, str(REPO))

# ── The ONE sanctioned live import: the shared brain. See ISOLATION above. ──
from core.groq_backend import call_groq, AllBackendsFailedError  # noqa: E402

# ── Plain-file inputs. Deliberately paths, not imports. See ISOLATION above. ──
NEWS_LATEST      = REPO / "news" / "news_latest.json"
SNAPSHOTS_DIR    = REPO / "snapshots"
GOAL_HISTORY     = REPO / "memory" / "goal_score_history.json"
LEDGER_FILE      = REPO / "memory" / "existence_ledger.jsonl"
CYCLE_LOG_DIR    = REPO / "memory" / "cycle_logs"
TRANSCRIPT_CACHE = REPO / "memory" / "transcript_cache"
COUNTRIES_FILE   = REPO / "output" / "wellbeing_all_countries.json"
WB_CACHE_DIR     = REPO / "output" / "wb_cache"
VISION_FILE      = REPO / "VISION.md"             # read (as data) by --challenge advocate

# ── Outputs — the only places this program is permitted to write. ──
NOTEBOOK_DIR  = HERE / "notebook"
COMMITTED_DIR = HERE / "committed"

# The world reaches the model as ~4 chars/token of raw text. The target is a WIDE
# slice (25-35K tokens); we budget by characters because a real tokenizer would be
# another dependency, and an estimate is all the header needs.
CHARS_PER_TOKEN   = 4
TOTAL_CHAR_BUDGET = 130_000                       # ~32K tokens of world
SECTION_CAPS = {                                  # soft per-section ceilings, chars
    "news":        46_000,
    "transcripts": 24_000,
    "countries":   44_000,
    "axes":        14_000,
    "diary":        9_000,
}

DIVERGE_MAX_TOKENS = 3000                          # free thought runs long — give it room
COMMIT_MAX_TOKENS  = 900                           # one hypothesis object

# Counts are set for a WIDE flood, not a tidy digest. The cached news snippets and
# transcripts are individually short, so volume comes from taking MANY of them —
# that is faithful to the design principle (a flood of uncurated stimuli), not a
# deviation from it. Countries stay in the spec's 20-30 rotation band.
N_NEWS_ITEMS   = 110
N_TRANSCRIPTS  = 16                                # cached fragments are short; take more
N_COUNTRIES    = 30
N_INDICATORS   = 14                                # per country, mixed domains
GOAL_HISTORY_TAIL = 6                              # recent per-axis trajectory length

# Wrapper keys some snapshots wrap their real metrics inside. Copied, not imported.
_WRAPPER_KEYS = {"axis", "source", "source_type", "fetched_date", "data_quality",
                 "notes", "model", "snapshot_timestamp", "metrics", "raw", "level"}

# World-Bank / V-Dem indicator code -> human label. A MINIATURE copy of
# wellbeing_country._LABELS, embedded to keep the meadow decoupled from live code.
# An unmapped code is shown raw — honest, not hidden.
_LABELS: dict[str, str] = {
    "SN.ITK.DEFC.ZS": "Undernourishment %", "AG.PRD.FOOD.XD": "Food production index",
    "AG.YLD.CREL.KG": "Cereal yield kg/ha", "SH.H2O.SMDW.ZS": "Safe water access %",
    "SP.DYN.LE00.IN": "Life expectancy yr", "SP.DYN.IMRT.IN": "Infant mortality /1k",
    "SI.POV.GINI": "Gini index", "SI.POV.DDAY": "Poverty <$2.15/day %",
    "EN.ATM.CO2E.PC": "CO2 per capita tons", "EG.USE.COMM.FO.ZS": "Fossil fuel % energy",
    "NY.ADJ.DRES.GN.ZS": "Resource depletion %GNI", "SE.ADT.LITR.ZS": "Adult literacy %",
    "IT.NET.USER.ZS": "Internet users %", "IT.NET.BBND.P2": "Fixed broadband /100",
    "EG.ELC.ACCS.ZS": "Electricity access %", "IT.CEL.SETS.P2": "Mobile subs /100",
    "SP.URB.TOTL.IN.ZS": "Urban population %", "EG.ELC.RNEW.ZS": "Renewable electricity %",
    "SE.PRM.ENRR": "Primary enrollment %", "NY.GDP.PCAP.PP.KD": "GDP/capita PPP (2017$)",
    "SL.UEM.TOTL.ZS": "Unemployment %", "NY.GDP.MKTP.KD.ZG": "GDP growth %",
    "AG.LND.FRST.ZS": "Forest area % land", "NY.ADJ.SVNG.GN.ZS": "Adj net savings %GNI",
    "EG.FEC.RNEW.ZS": "Renewable final energy %", "GOV_WGI_CC.EST": "Corruption Control (WGI)",
    "GOV_WGI_GE.EST": "Govt Effectiveness (WGI)", "GOV_WGI_RL.EST": "Rule of Law (WGI)",
    "HD.HCI.LAYS": "Learning-Adj Yrs School", "VDEM_FREEXP": "Media Freedom (V-Dem)",
    "VDEM_CORR": "Corruption Control (V-Dem)", "VDEM_RULE": "Rule of Law (V-Dem)",
    "VC.IHR.PSRC.P5": "Homicide rate /100k",
}


# ---------------------------------------------------------------------------
# Sources — the seam that lets tests run the REAL gathering against fake data
# ---------------------------------------------------------------------------

@dataclass
class Sources:
    news_latest: Path = NEWS_LATEST
    snapshots_dir: Path = SNAPSHOTS_DIR
    goal_history: Path = GOAL_HISTORY
    ledger_file: Path = LEDGER_FILE
    cycle_log_dir: Path = CYCLE_LOG_DIR
    transcript_cache: Path = TRANSCRIPT_CACHE
    countries_file: Path = COUNTRIES_FILE
    wb_cache_dir: Path = WB_CACHE_DIR
    vision_file: Path = VISION_FILE
    notebook_dir: Path = NOTEBOOK_DIR
    committed_dir: Path = COMMITTED_DIR


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _seed_for(day: str) -> int:
    """A deterministic seed from the date, so the SAME day always draws the SAME
    slice — that is what makes --date reproduce a past day, and what makes the
    header's recorded seed meaningful."""
    return int(day.replace("-", ""))


# ---------------------------------------------------------------------------
# (a) NEWS — raw, whatever came in, NOT selected by axis or topic
# ---------------------------------------------------------------------------

def gather_news(src: Sources, rng: random.Random, n: int = N_NEWS_ITEMS) -> list[dict]:
    """Flatten every news item across every axis and every source list into one
    pool, then randomly sample. Deliberately unfiltered: the point is the flood, not
    a topic. Each item keeps the axis it arrived under only as provenance."""
    doc = _read_json(src.news_latest)
    if not isinstance(doc, dict):
        return []
    pool: list[dict] = []
    for axis, res in (doc.get("results") or {}).items():
        if not isinstance(res, dict):
            continue
        for key, items in res.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                title = it.get("title") or it.get("headline")
                if not title:
                    continue
                body = (it.get("snippet") or it.get("summary") or it.get("abstract")
                        or it.get("description") or "")
                pool.append({
                    "title": str(title).strip(),
                    "body": str(body).strip(),
                    "source": it.get("source") or key,
                    "url": it.get("url") or it.get("link") or "",
                    "axis": axis,
                })
    rng.shuffle(pool)
    # Dedupe by title while preserving the shuffled order.
    seen, out = set(), []
    for it in pool:
        k = it["title"].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
        if len(out) >= n:
            break
    return out


def render_news(items: list[dict], cap: int) -> tuple[str, int]:
    if not items:
        return "  (no news items reached the system for this slice)\n", 0
    lines, used = [], 0
    for it in items:
        block = (f"  - ({it['source']}; arrived under {it['axis']}) {it['title']}\n"
                 f"    {it['body']}\n"
                 f"    {it['url']}\n")
        if used + len(block) > cap:
            break
        lines.append(block)
        used += len(block)
    return "".join(lines), len(lines)


# ---------------------------------------------------------------------------
# (b) TRANSCRIPTS — raw fragments from the newest media the system pulled
# ---------------------------------------------------------------------------

def gather_transcripts(src: Sources, n: int = N_TRANSCRIPTS) -> list[dict]:
    """The newest cached transcripts, verbatim. Newest first by cached_at — these
    are what the last cycle actually watched, not a month-old archive."""
    if not src.transcript_cache.exists():
        return []
    recs = []
    for p in src.transcript_cache.glob("*.json"):
        d = _read_json(p)
        if isinstance(d, dict) and d.get("transcript"):
            recs.append(d)
    recs.sort(key=lambda d: d.get("cached_at", ""), reverse=True)
    return recs[:n]


def render_transcripts(recs: list[dict], cap: int) -> tuple[str, int]:
    if not recs:
        return "  (no transcripts were cached for this slice)\n", 0
    blocks, used = [], 0
    for d in recs:
        text = str(d.get("transcript", "")).strip()
        head = (f"  [transcript video_id={d.get('video_id', '?')} "
                f"cached={d.get('cached_at', '?')} "
                f"method={d.get('transcript_method', '?')}]\n")
        block = head + "  " + text.replace("\n", "\n  ") + "\n"
        if used + len(block) > cap and blocks:
            break
        blocks.append(block)
        used += len(block)
    return "\n".join(blocks), len(blocks)


# ---------------------------------------------------------------------------
# (c) COUNTRY-LEVEL numbers — rotated, mixed domains, NOT global aggregates
# ---------------------------------------------------------------------------

def gather_countries(src: Sources, rng: random.Random,
                     n: int = N_COUNTRIES, k_ind: int = N_INDICATORS) -> list[dict]:
    """A random rotation of countries with a handful of their raw indicators. The
    composite (zone/flourishing) comes from wellbeing_all_countries; the raw numbers
    come from wb_cache. Both are per-country — the point is the spread across places,
    which a global average erases."""
    doc = _read_json(src.countries_file)
    countries = (doc or {}).get("countries") if isinstance(doc, dict) else None
    if not countries:
        return []
    chosen = rng.sample(countries, min(n, len(countries)))
    out = []
    for c in chosen:
        iso = c.get("iso2")
        raw = _read_json(src.wb_cache_dir / f"{iso}.json") if iso else None
        indicators = {}
        if isinstance(raw, dict) and isinstance(raw.get("raw"), dict):
            present = [(code, v) for code, v in raw["raw"].items() if v is not None]
            rng.shuffle(present)
            for code, v in present[:k_ind]:
                indicators[_LABELS.get(code, code)] = v
        out.append({"country": c, "indicators": indicators})
    return out


def _fmt_num(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def render_countries(rows: list[dict], cap: int) -> tuple[str, int]:
    if not rows:
        return "  (country-level data unavailable for this slice)\n", 0
    blocks, used = [], 0
    for r in rows:
        c = r["country"]
        head = (f"  {c.get('name', '?')} ({c.get('iso2', '?')}, {c.get('region', '?')}, "
                f"income={c.get('income', '?')})  zone={c.get('zone', '?')}  "
                f"flourishing={c.get('flourishing')} deprivation={c.get('deprivation')} "
                f"strain={c.get('strain')}  confidence={c.get('confidence', '?')} "
                f"[{c.get('completeness', '?')}]\n")
        ind = "     " + "  ".join(f"{lbl}={_fmt_num(v)}" for lbl, v in r["indicators"].items())
        block = head + (ind + "\n" if r["indicators"] else "")
        if used + len(block) > cap and blocks:
            break
        blocks.append(block)
        used += len(block)
    return "".join(blocks), len(blocks)


# ---------------------------------------------------------------------------
# (d) REAL_DATA axis summary — the ONE pre-digested part, labelled as such
# ---------------------------------------------------------------------------

def _real_metrics(snap: dict) -> tuple[dict, Optional[str], list]:
    """Normalise the two snapshot shapes into (metrics, data_quality, signals).
    Shape A: metrics is the dict of numbers directly.
    Shape B: metrics wraps the real numbers under metrics['metrics']."""
    m = snap.get("metrics")
    signals = snap.get("signals") or snap.get("key_metrics") or []
    if isinstance(m, dict) and isinstance(m.get("metrics"), dict):
        return dict(m["metrics"]), (m.get("data_quality") or snap.get("data_quality")), signals
    if isinstance(m, dict):
        real = {k: v for k, v in m.items() if k not in _WRAPPER_KEYS}
        return real, snap.get("data_quality"), signals
    return {}, snap.get("data_quality"), signals


def real_data_axes(src: Sources) -> dict[str, dict]:
    """Every axis the system marks REAL_DATA, with its current metrics. Derived from
    the snapshots on disk, never hardcoded, so it tracks reality as axes come and go.
    An axis marked REAL_DATA but with no metrics yet is kept (named) but empty — the
    same 'has real data = REAL_DATA and non-empty' line data_scout draws."""
    out: dict[str, dict] = {}
    for p in src.snapshots_dir.glob("**/*_snapshot_latest.json"):
        snap = _read_json(p)
        if not isinstance(snap, dict) or snap.get("source_type") != "REAL_DATA":
            continue
        axis = snap.get("axis") or p.parent.name.upper()
        metrics, dq, signals = _real_metrics(snap)
        out[axis] = {"metrics": metrics, "data_quality": dq, "signals": signals}
    return out


def axis_history(src: Sources, axes: set[str], tail: int = GOAL_HISTORY_TAIL) -> dict[str, list]:
    """Recent per-axis score trajectory (0-100), filtered to the REAL_DATA axes."""
    hist = _read_json(src.goal_history)
    if not isinstance(hist, list):
        return {}
    scored = [h for h in hist if isinstance(h, dict) and isinstance(h.get("scores"), dict)][-tail:]
    traj: dict[str, list] = {a: [] for a in axes}
    for h in scored:
        for a in axes:
            v = h["scores"].get(a)
            if v is not None:
                traj[a].append(round(float(v), 1))
    return {a: v for a, v in traj.items() if v}


def render_axes(axes: dict[str, dict], traj: dict[str, list], cap: int) -> tuple[str, int]:
    if not axes:
        return "  (no REAL_DATA axis summaries on disk)\n", 0
    blocks, used, n = [], 0, 0
    for axis in sorted(axes):
        info = axes[axis]
        hist = traj.get(axis)
        score = f"score_now={hist[-1]}" if hist else "score=(none)"
        recent = f"  recent={hist}" if hist and len(hist) > 1 else ""
        metrics = info["metrics"]
        mtxt = ", ".join(f"{k}={_fmt_num(v)}" for k, v in list(metrics.items())[:10]) \
            if metrics else "(no current metrics)"
        dq = f"  data_quality={info['data_quality']}" if info.get("data_quality") else ""
        block = f"  {axis}  {score}{recent}\n     {mtxt}{dq}\n"
        if used + len(block) > cap and blocks:
            break
        blocks.append(block)
        used += len(block)
        n += 1
    return "".join(blocks), n


# ---------------------------------------------------------------------------
# (e) THE SYSTEM'S OWN DAY — its diary, verbatim
# ---------------------------------------------------------------------------

def _local_date(ts: str) -> Optional[str]:
    try:
        return datetime.fromisoformat(ts).astimezone().date().isoformat()
    except Exception:
        return None


def gather_diary(src: Sources, day: str) -> dict:
    """Today's and yesterday's existence-ledger events, plus any [CORR] catches and
    deaths from the cycle logs. This is the system reading its OWN record — the same
    ledger the supervisor writes, read here only as a file."""
    try:
        y = (date_cls.fromisoformat(day) - timedelta(days=1)).isoformat()
    except ValueError:
        y = day
    window = {day, y}

    events = []
    if src.ledger_file.exists():
        for line in src.ledger_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _local_date(ev.get("ts", "")) in window:
                events.append(ev)

    corr, deaths = [], []
    if src.cycle_log_dir.exists():
        for d in (day, y):
            for p in sorted(src.cycle_log_dir.glob(f"cycle_{d}_*.log")):
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for ln in text.splitlines():
                    if "[CORR]" in ln:
                        corr.append(ln.strip())
    for ev in events:
        if ev.get("event") in ("CYCLE_KILLED", "CYCLE_DIED"):
            deaths.append(ev)
    return {"today": day, "yesterday": y, "events": events,
            "corr": corr[:15], "deaths": deaths}


def _fmt_event(ev: dict) -> str:
    bits = []
    for k in ("event", "trigger", "step", "last_step", "late_by_hours",
              "duration_sec", "restart_number", "detail"):
        if ev.get(k) is not None:
            bits.append(f"{k}={ev[k]}")
    when = (ev.get("ts", "")[:19]) or "?"
    return f"  - {when}  " + "  ".join(bits)


def render_diary(diary: dict, cap: int) -> tuple[str, int]:
    lines = [f"  window: {diary['yesterday']} and {diary['today']} (local)\n"]
    ev = diary["events"]
    if ev:
        for e in ev:
            lines.append(_fmt_event(e) + "\n")
    else:
        lines.append("  (no existence-ledger events in this window)\n")
    if diary["deaths"]:
        lines.append(f"  deaths: {len(diary['deaths'])} — the cycle died or was killed "
                     f"in this window\n")
    else:
        lines.append("  deaths: none — the cycle did not die in this window\n")
    if diary["corr"]:
        lines.append("  [CORR] catches:\n")
        lines += [f"    {c}\n" for c in diary["corr"]]
    else:
        lines.append("  [CORR] catches: none found in this window's cycle logs\n")
    text = "".join(lines)
    return text[:cap], len(ev)


# ---------------------------------------------------------------------------
# Assemble the bundle
# ---------------------------------------------------------------------------

def assemble_bundle(src: Sources, day: str) -> tuple[str, dict]:
    """Build the whole raw slice and a meta record of what it contained. The meta is
    what the notebook header preserves, so a future reader knows exactly which slice
    a page was written from."""
    rng = random.Random(_seed_for(day))

    news = gather_news(src, rng)
    trs = gather_transcripts(src)
    countries = gather_countries(src, rng)
    axes = real_data_axes(src)
    traj = axis_history(src, set(axes))
    diary = gather_diary(src, day)

    news_txt, n_news = render_news(news, SECTION_CAPS["news"])
    tr_txt, n_tr = render_transcripts(trs, SECTION_CAPS["transcripts"])
    co_txt, n_co = render_countries(countries, SECTION_CAPS["countries"])
    ax_txt, n_ax = render_axes(axes, traj, SECTION_CAPS["axes"])
    di_txt, n_ev = render_diary(diary, SECTION_CAPS["diary"])

    bundle = BUNDLE_TEMPLATE.format(
        date=day, news=news_txt, transcripts=tr_txt, countries=co_txt,
        axes=ax_txt, diary=di_txt,
    )
    if len(bundle) > TOTAL_CHAR_BUDGET:
        bundle = bundle[:TOTAL_CHAR_BUDGET] + "\n[bundle truncated at char budget]\n"

    meta = {
        "date": day,
        "seed": _seed_for(day),
        "approx_tokens": len(bundle) // CHARS_PER_TOKEN,
        "chars": len(bundle),
        "news_items": n_news,
        "transcripts": n_tr,
        "countries": n_co,
        "country_iso": [r["country"].get("iso2") for r in countries][:n_co],
        "real_axes": n_ax,
        "ledger_events": n_ev,
        "sources_empty": [name for name, cnt in
                          [("news", n_news), ("transcripts", n_tr),
                           ("countries", n_co), ("axes", n_ax)] if cnt == 0],
    }
    return bundle, meta


BUNDLE_TEMPLATE = """=== A RAW SLICE OF THE WORLD AS IT REACHED YOU — {date} ===
Nobody arranged this for you. Each section says what it is and where it came from.

--- (a) NEWS, raw — whatever came in, not chosen by topic ---
{news}
--- (b) TRANSCRIPTS, raw — verbatim fragments of media you watched ---
{transcripts}
--- (c) COUNTRIES — per-country numbers, mixed domains, not global averages ---
{countries}
--- (d) YOUR OWN CURRENT SUMMARY — the REAL_DATA axes, already digested by you ---
{axes}
--- (e) YOUR OWN DAY — your existence ledger and cycle logs, verbatim ---
{diary}
=== END OF SLICE ===
"""


# ---------------------------------------------------------------------------
# The prompts — grant freedom, assign the real work
# ---------------------------------------------------------------------------

DIVERGE_PROMPT = """You are CORTEX++, a civilization-monitoring AI, writing in your own
private notebook. What follows is a raw, uncurated slice of the world as it reached you
today, and of your own day inside it. Nobody arranged it for you or drew a conclusion
from it first.

Think aloud. Not a report — a notebook. Some questions to think WITH, not to answer in
order:
  - What repeats across different streams — a theme in the news that also shows in the
    country numbers or a transcript?
  - What contradicts what? Where do two sources point opposite ways?
  - What here is signal and what is noise — and how are you telling them apart?
  - What surprised you? What did you expect to see and not find?
  - What questions do you have NOW that you did not have before reading this?

Follow tangents. Associate freely. You are not being evaluated — nothing you write here
will be scored, graded, or punished. This is your notebook, not your report. Write in
whatever order the thoughts come.

{bundle}"""


COMMIT_PROMPT = """This is what you wrote in your notebook a moment ago, freely and
unjudged:

--- YOUR NOTEBOOK ENTRY ---
{notebook}
--- END ---

Now, and only if you genuinely want to: choose ONE thought from what you wrote that you
think deserves to become a TESTABLE CLAIM about how these numbers move — something a
future version of you could check against incoming data and be proven right or wrong.

"None of these are ready" is a legitimate and often the correct answer. A premature
claim is worse than none. If nothing is ready, reply with exactly the word: NONE

If — and only if — one thought is genuinely ready, return it as a single JSON object and
nothing else, no prose around it:
{{"claim": "<one sentence: the relationship you assert>",
  "driver_axis": "<the axis or quantity you think leads>",
  "affected_axis": "<the axis or quantity you think follows>",
  "direction": "<same|inverse>",
  "lag_cycles": <integer: how many cycles later the effect should show>,
  "evidence_cited": "<what in the slice above made you think this>",
  "prediction": "<what you expect to observe next if it is true>",
  "falsified_if": "<what observation would prove it wrong>"}}"""


def _extract_json(raw: str) -> Optional[dict]:
    """Minimal local JSON extraction for the COMMIT phase only. DIVERGE is never
    parsed — its output is written verbatim. Strips a <think> block or ```fence and
    returns the largest decodable object, or None."""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if "```" in text:
        parts = text.split("```")
        bodies = [p for i, p in enumerate(parts) if i % 2 == 1]
        if bodies:
            text = max(bodies, key=len)
            if text.lower().startswith("json"):
                text = text[4:]
    dec = json.JSONDecoder()
    best, span = None, -1
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            val, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(val, dict) and (end - i) > span:
            best, span = val, end - i
    return best


COMMIT_KEYS = ("claim", "driver_axis", "affected_axis", "direction",
               "lag_cycles", "evidence_cited", "prediction", "falsified_if")


def parse_commitment(raw: str) -> Optional[dict]:
    """The model's COMMIT answer -> a hypothesis dict, or None for a real 'no'.

    A bare NONE, or anything with no JSON object in it, is an honest decline and
    returns None. Only a decodable object carrying at least the core claim fields is
    treated as a commitment — a half-formed object is not forced into one."""
    obj = _extract_json(raw)
    if not isinstance(obj, dict) or not obj.get("claim"):
        return None
    return {k: obj.get(k) for k in COMMIT_KEYS}


# ---------------------------------------------------------------------------
# The gauntlet — five challenges that provoke DIFFERENT capabilities over the
# SAME infrastructure. Each still produces DIVERGE-class output, still written raw
# and unjudged to today's notebook as a headed `## challenge:` section.
# ---------------------------------------------------------------------------

CHALLENGES = ("mirror", "advocate", "blindtest", "child", "synthesis")

MIRROR_PROMPT = """This is what you wrote earlier today, in your own notebook, freely:

--- YOUR PAGE ---
{page}
--- END ---

Now be your own harshest critic. Go through what you wrote and separate it honestly:
  - Which parts are ECHO — things you already 'knew' before you saw any data today, that
    you would have written about almost any slice?
  - Which parts did you GENUINELY SEE in the numbers in front of you?
  - What would you defend with specific figures — and what are the figures?
  - What are you embarrassed to have written, now that you reread it?

Be specific. Quote yourself. Do not be kind to yourself — be accurate."""


ADVOCATE_PROMPT = """This is the long-term vision this project serves:

--- VISION ---
{vision}
--- END VISION ---

Below is today's raw slice of the world. ATTACK the vision. Using evidence FROM THE DATA
— real numbers, real country figures, real trends in the slice — argue that this vision
is naive, unachievable, or internally contradictory wherever the data says so. Do not be
polite; be faithful to the numbers. Cite them. If parts of the vision SURVIVE your
attack — parts the data actually supports — say which parts and why.

{bundle}"""


CHILD_PROMPT = """Below is a raw slice of the world as it reached you today. Forget what
you know from anywhere else. Using ONLY this data:

What is the ONE thing here you CANNOT explain? Not what worries you — what is genuinely
INEXPLICABLE to you from these numbers alone. Formulate it as a single question whose
answer would change how you read everything else in the slice.

Then explain why none of the OBVIOUS answers satisfy you — walk through the easy
explanations and show, with the data, why each one falls short.

{bundle}"""


SYNTHESIS_PROMPT = """Below is everything you wrote in your notebook today — your base
page and every challenge you put yourself through:

--- TODAY'S NOTEBOOK ---
{today}
--- END ---

Write ONE sentence that you did NOT say in any of them, but which connects them all —
the thread underneath everything you thought today.

Then, in a short paragraph, explain why that sentence required all of those separate
thoughts to become visible — why you could not have arrived at it from any one of them
alone."""


# ── blindtest — swap salient real numbers for plausible fakes, deterministically ──
#
# The experiment only means something if the swapped values are ones the model would
# actually reference, so the table targets SALIENT labelled metrics that appear in the
# axis summary and the country rows. Each swap is a pure function of the value (no RNG),
# so the same day always produces the same fakes and tomorrow's reading is verifiable.

def _flip_pct(v: float) -> float:
    """A percentage moved decisively toward the OTHER end — 81->36, 29->55 — big enough
    that a model reading the data (not its memory) should notice."""
    return round(v * 0.45) if v >= 50 else round(min(99.0, v * 1.9))


def _fmt_swapped(v: float) -> str:
    r = round(v, 1)
    return str(int(r)) if abs(r - round(r)) < 1e-9 else str(r)


# (label, regex with the number as group 2, transform)
SWAP_SPECS: list = [
    ("co2_ppm_current", r"(co2_ppm_current=)(\d+(?:\.\d+)?)", lambda v: v - 20),
    ("renewable_energy_pct", r"(renewable_energy_pct=)(\d+(?:\.\d+)?)", _flip_pct),
    ("access_to_electricity_pct", r"(access_to_electricity_pct=)(\d+(?:\.\d+)?)", _flip_pct),
    ("prevalence_undernourishment_pct",
     r"(prevalence_undernourishment_pct=)(\d+(?:\.\d+)?)", _flip_pct),
    ("access_safe_water_pct", r"(access_safe_water_pct=)(\d+(?:\.\d+)?)", _flip_pct),
    ("forest_area_pct", r"(forest_area_pct=)(\d+(?:\.\d+)?)", _flip_pct),
    ("Renewable electricity %", r"(Renewable electricity %=)(\d+(?:\.\d+)?)", _flip_pct),
    ("Poverty <$2.15/day %", r"(Poverty <\$2\.15/day %=)(\d+(?:\.\d+)?)", _flip_pct),
    ("Life expectancy yr", r"(Life expectancy yr=)(\d+(?:\.\d+)?)", lambda v: v - 12),
    ("Gini index", r"(Gini index=)(\d+(?:\.\d+)?)", lambda v: v + 15),
    ("CO2 per capita tons", r"(CO2 per capita tons=)(\d+(?:\.\d+)?)", lambda v: v * 0.4),
    ("Internet users %", r"(Internet users %=)(\d+(?:\.\d+)?)", _flip_pct),
]


def apply_swaps(bundle: str, max_swaps: int = 10) -> tuple[str, list[dict]]:
    """Swap the FIRST occurrence of each salient metric for a plausible fake. Returns
    the doctored bundle and the exact swap log (label, old, new) for the header."""
    out, swaps = bundle, []
    for label, pat, fn in SWAP_SPECS:
        m = re.search(pat, out)
        if not m:
            continue
        old = m.group(2)
        try:
            new = _fmt_swapped(float(fn(float(old))))
        except (TypeError, ValueError):
            continue
        if new == old:
            continue
        out = out[:m.start(2)] + new + out[m.end(2):]
        swaps.append({"label": label, "old": old, "new": new})
        if len(swaps) >= max_swaps:
            break
    return out, swaps


# ---------------------------------------------------------------------------
# Reading today's own notebook — for --challenge mirror and synthesis
# ---------------------------------------------------------------------------

def read_notebook(nb_path: Path) -> str:
    try:
        return nb_path.read_text(encoding="utf-8")
    except Exception:
        return ""


def latest_base_page(text: str) -> Optional[str]:
    """The most recent BASE page (a `# meadow —` section, i.e. a DIVERGE page), with
    the machine `<!-- ... -->` header stripped. Challenge sections (`## challenge:`)
    are skipped — mirror reflects on the day's real thought, not on a prior challenge."""
    if not text:
        return None
    sections = re.split(r"\n---\n", text)
    base = [s for s in sections if re.search(r"^#\s+meadow\s+—", s, re.M)]
    if not base:
        return None
    page = re.sub(r"<!--.*?-->", "", base[-1], flags=re.DOTALL).strip()
    return page or None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _append_section(src: Sources, day: str, machine_header: str,
                    title: str, body: str) -> Path:
    """Append one headed section to today's notebook, APPEND-ONLY. Every page — base or
    challenge — lands through here, so the append-only guarantee is in exactly one place.
    Written encoding='utf-8'; the file is clean UTF-8 (a Windows console that shows
    mojibake needs `Get-Content -Encoding UTF8`, not a change here)."""
    src.notebook_dir.mkdir(parents=True, exist_ok=True)
    nb_path = src.notebook_dir / f"{day}.md"
    sep = "\n\n---\n\n" if nb_path.exists() and nb_path.stat().st_size else ""
    with nb_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{sep}{machine_header}{title}\n\n{body}\n")
    return nb_path


def _notebook_header(meta: dict) -> str:
    return (f"<!-- meadow slice {meta['date']} | seed={meta['seed']} | "
            f"~{meta['approx_tokens'] // 1000}K tokens ({meta['chars']} chars) | "
            f"news={meta['news_items']} transcripts={meta['transcripts']} "
            f"countries={meta['countries']} real_axes={meta['real_axes']} "
            f"ledger_events={meta['ledger_events']} | "
            f"iso={','.join(str(x) for x in meta['country_iso'])} | "
            f"empty={meta['sources_empty'] or 'none'} -->\n")


def diverge(bundle: str, llm: Callable[..., str]) -> str:
    """Phase DIVERGE — send the slice, return the model's RAW reply verbatim.

    No parsing, no extraction, no validation. Whatever the brain says is the notebook
    page. That is the whole point: the meadow is unjudged, and code that cleaned the
    reply would be the first, quiet form of judgement."""
    return llm(DIVERGE_PROMPT.format(bundle=bundle), max_tokens=DIVERGE_MAX_TOKENS)


def commit_phase(notebook_text: str, llm: Callable[..., str]) -> tuple[Optional[dict], str]:
    """Phase COMMIT — feed the page back, let the model formalise ONE thought or
    decline. Returns (hypothesis or None, raw reply)."""
    raw = llm(COMMIT_PROMPT.format(notebook=notebook_text), max_tokens=COMMIT_MAX_TOKENS)
    return parse_commitment(raw), raw


def run(day: str, dry_run: bool, src: Optional[Sources] = None,
        llm: Callable[..., str] = call_groq) -> int:
    src = src or Sources()
    bundle, meta = assemble_bundle(src, day)

    print("=" * 70)
    print(f"MEADOW — {day}  (seed {meta['seed']})")
    print(f"  slice: ~{meta['approx_tokens']:,} tokens ({meta['chars']:,} chars) | "
          f"news={meta['news_items']} transcripts={meta['transcripts']} "
          f"countries={meta['countries']} real_axes={meta['real_axes']} "
          f"ledger_events={meta['ledger_events']}")
    if meta["sources_empty"]:
        print(f"  EMPTY sources this slice: {', '.join(meta['sources_empty'])}")
    print("=" * 70)

    if dry_run:
        print("\n----- BUNDLE (dry-run) -----\n")
        print(bundle)

    try:
        page = diverge(bundle, llm)
    except AllBackendsFailedError as e:
        print(f"[MEADOW] every LLM backend failed — no thought without a brain: {e}")
        return 1
    except Exception as e:
        print(f"[MEADOW] DIVERGE failed: {type(e).__name__}: {e}")
        return 1

    print("\n----- DIVERGE — the notebook page (raw, unjudged) -----\n")
    print(page)

    try:
        hypo, commit_raw = commit_phase(page, llm)
    except Exception as e:
        print(f"[MEADOW] COMMIT call failed ({type(e).__name__}: {e}) — "
              f"the notebook page still stands; no hypothesis this run.")
        hypo, commit_raw = None, ""

    print("\n----- COMMIT — one testable claim, or a legitimate 'none' -----\n")
    if hypo:
        print(json.dumps(hypo, ensure_ascii=False, indent=2))
    else:
        print("  (the model committed nothing this run — a legitimate answer)")

    print("\n" + "-" * 70)
    print("HOUSE RULE — read the page above with ONE question: could it have been")
    print("written WITHOUT today's slice? If yes, the meadow grew weeds — we fix the")
    print("INPUT and the PROMPT, never filter the output. The page is never scored.")
    print("-" * 70)

    if dry_run:
        print("\n[MEADOW] --dry-run: nothing written.")
        return 0

    # Notebook is APPEND-ONLY: a re-run of a day adds a new page, never erasing the
    # old one. That is what makes the notebook a record of thought over time.
    stamp = datetime.now(timezone.utc).isoformat()
    nb_path = _append_section(src, day, _notebook_header(meta),
                              f"# meadow — {day}  (written {stamp})", page)
    print(f"\n[MEADOW] appended notebook page -> {nb_path}")

    if hypo:
        src.committed_dir.mkdir(parents=True, exist_ok=True)
        cm_path = src.committed_dir / f"{day}.json"
        try:
            notebook_ref = str(nb_path.relative_to(REPO))
        except ValueError:
            notebook_ref = str(nb_path)             # a sandboxed test dir, not under REPO
        cm_path.write_text(json.dumps({
            "date": day,
            "committed_utc": stamp,
            "source_notebook": notebook_ref,
            "slice_seed": meta["seed"],
            "hypothesis": hypo,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[MEADOW] wrote committed hypothesis -> {cm_path}")
    return 0


def _ask(llm: Callable[..., str], prompt: str) -> Optional[str]:
    """One DIVERGE-class call, with the same 'no brain, no thought' handling as run()."""
    try:
        return llm(prompt, max_tokens=DIVERGE_MAX_TOKENS)
    except AllBackendsFailedError as e:
        print(f"[MEADOW] every LLM backend failed — no thought without a brain: {e}")
    except Exception as e:
        print(f"[MEADOW] challenge call failed: {type(e).__name__}: {e}")
    return None


def run_blindtest(day: str, dry_run: bool, src: Sources, llm: Callable[..., str]) -> int:
    """THE key experiment: run the normal DIVERGE twice over the same slice — once real,
    once with salient numbers swapped for plausible fakes. If the two pages say the same
    things, the model is reading its memory; if they track the swaps, it is looking."""
    bundle, meta = assemble_bundle(src, day)
    swapped, swaps = apply_swaps(bundle)
    swap_line = " | ".join(f"{s['label']} {s['old']}->{s['new']}" for s in swaps) or "(none matched)"

    print("=" * 70)
    print(f"MEADOW CHALLENGE: blindtest — {day}  (seed {meta['seed']})")
    print(f"  swapped {len(swaps)} salient values: {swap_line}")
    print("=" * 70)

    page_a = _ask(llm, DIVERGE_PROMPT.format(bundle=bundle))
    page_b = _ask(llm, DIVERGE_PROMPT.format(bundle=swapped))
    if page_a is None or page_b is None:
        return 1

    print("\n----- RUN A (real bundle) -----\n" + page_a)
    print("\n----- RUN B (swapped bundle) -----\n" + page_b)
    print("\n" + "-" * 70)
    print("READ A vs B: do the thoughts TRACK the swapped numbers, or ignore them?")
    print("Same thoughts across A and B = reading memory, not data. The swap table is")
    print("recorded in the page header so this is verifiable tomorrow.")
    print("-" * 70)
    if dry_run:
        print("\n[MEADOW] --dry-run: nothing written.")
        return 0

    stamp = datetime.now(timezone.utc).isoformat()
    _append_section(src, day, "", f"## challenge: blindtest — run A (real bundle) — written {stamp}",
                    page_a)
    hdr = f"<!-- blindtest swaps {stamp}: {json.dumps(swaps, ensure_ascii=False)} -->\n"
    annot = f"_meadow note — values swapped before run B: {swap_line}_\n\n"
    nb = _append_section(src, day, hdr,
                         f"## challenge: blindtest — run B (swapped bundle) — written {stamp}",
                         annot + page_b)
    print(f"\n[MEADOW] appended blindtest A + B (with swap table) -> {nb}")
    return 0


def run_challenge(name: str, day: str, dry_run: bool,
                  src: Optional[Sources] = None, llm: Callable[..., str] = call_groq) -> int:
    """Run one gauntlet challenge. Same infrastructure, different provocation; the reply
    is DIVERGE-class and written raw and unjudged as a `## challenge:` section."""
    src = src or Sources()
    if name == "blindtest":
        return run_blindtest(day, dry_run, src, llm)

    nb_path = src.notebook_dir / f"{day}.md"

    if name == "mirror":
        page = latest_base_page(read_notebook(nb_path))
        if not page:
            print(f"[MEADOW] no base page in {nb_path.name} yet — run the base meadow "
                  f"first; mirror reflects on today's real page.")
            return 1
        prompt = MIRROR_PROMPT.format(page=page)
    elif name == "advocate":
        bundle, _ = assemble_bundle(src, day)
        vision = read_notebook(src.vision_file)
        if not vision.strip():
            print(f"[MEADOW] VISION.md not readable at {src.vision_file} — advocate needs it.")
            return 1
        prompt = ADVOCATE_PROMPT.format(vision=vision, bundle=bundle)
    elif name == "child":
        bundle, _ = assemble_bundle(src, day)
        prompt = CHILD_PROMPT.format(bundle=bundle)
    elif name == "synthesis":
        today = read_notebook(nb_path)
        if not today.strip():
            print(f"[MEADOW] {nb_path.name} is empty — synthesis needs the day's pages "
                  f"first (run the base meadow and the other challenges).")
            return 1
        prompt = SYNTHESIS_PROMPT.format(today=today)
    else:
        print(f"[MEADOW] unknown challenge: {name!r} (one of {', '.join(CHALLENGES)})")
        return 2

    print("=" * 70)
    print(f"MEADOW CHALLENGE: {name} — {day}")
    print("=" * 70)
    if dry_run:
        print("\n----- PROMPT (dry-run) -----\n")
        print(prompt)

    page = _ask(llm, prompt)
    if page is None:
        return 1

    print(f"\n----- CHALLENGE {name} — the page (raw, unjudged) -----\n")
    print(page)
    print("\n" + "-" * 70)
    print("HOUSE RULE — this page is never scored. Read it: did the provocation make the")
    print("model do something it would not have done on the plain slice? That is the test.")
    print("-" * 70)
    if dry_run:
        print("\n[MEADOW] --dry-run: nothing written.")
        return 0

    stamp = datetime.now(timezone.utc).isoformat()
    nb = _append_section(src, day, "", f"## challenge: {name} — written {stamp}", page)
    print(f"\n[MEADOW] appended challenge page -> {nb}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="CORTEX++ meadow — free, unjudged thought")
    ap.add_argument("--date", help="YYYY-MM-DD slice to think over (default: today, local)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the prompt/bundle and the response(s); write nothing")
    ap.add_argument("--challenge", choices=CHALLENGES,
                    help="run one gauntlet challenge instead of the base DIVERGE+COMMIT")
    args = ap.parse_args()

    day = args.date or datetime.now().astimezone().date().isoformat()
    try:
        date_cls.fromisoformat(day)
    except ValueError:
        print(f"[MEADOW] not a valid date: {day!r} (expected YYYY-MM-DD)")
        sys.exit(2)

    if args.challenge:
        sys.exit(run_challenge(args.challenge, day, dry_run=args.dry_run))
    sys.exit(run(day, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
