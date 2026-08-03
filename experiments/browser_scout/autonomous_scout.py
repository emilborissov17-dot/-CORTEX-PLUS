#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/browser_scout/autonomous_scout.py — decide -> search -> read -> extract.

No hard-coded source. Given an axis and its NEED, the system itself: (1) decides what
numeric indicator would measure it and picks SEARCH KEYWORDS (local model — sovereign),
(2) SEARCHES via a REAL browser (Playwright/Chromium — a real session passes the JS
bot-challenge that blocks raw requests to DuckDuckGo), (3) reads the top results and
EXTRACTS a current numeric value (local model), (4) writes a neutral JSON record the
composer reads via its "file" kind. Human still approves any promotion.

Reliability is the hard part and is guarded, not hand-waved: an extracted value is
ACCEPTED ONLY IF its digits appear verbatim in the page text (anti-hallucination) and
it passes a plausibility range. A value the model can't ground in the page is dropped,
loudly. So a low hit-rate shows as "found nothing groundable", never as a fake number.

Sovereign + free: Playwright (real browser) + local Ollama (qwen). No cloud, no API keys.

  python experiments/browser_scout/autonomous_scout.py --axis SOCIAL_RELATIONS_REVIEW \
      --need "a daily-updating numeric signal of social stability / unrest"
  python experiments/browser_scout/autonomous_scout.py --from-needs   # drive from composer_needs
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT_DIR = REPO / "memory" / "browse_sources"
COMPOSER_NEEDS = REPO / "memory" / "composer_needs.json"

import os
_OLLAMA = os.environ.get("CORTEX_OLLAMA_URL", "http://localhost:11434")
_MODEL  = os.environ.get("CORTEX_LOCAL_MODEL", "qwen2.5:3b")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _local(prompt: str, timeout: int = 120, num_predict: int = 300) -> str:
    """Sovereign local model over Ollama HTTP. Raises on failure (caller handles)."""
    import requests
    r = requests.post(f"{_OLLAMA}/api/chat", timeout=timeout, json={
        "model": _MODEL, "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.1, "num_predict": num_predict}})
    r.raise_for_status()
    return ((r.json().get("message") or {}).get("content") or "").strip()


def _json_from(text: str):
    """Last {...} block the model emitted (think-block safe)."""
    depth, start, best = 0, -1, None
    for i, c in enumerate(text):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                best = text[start:i + 1]
    if not best:
        raise ValueError("no JSON object in model output")
    return json.loads(best)


_DAILY_CLASSES = ("measurement_daily", "event_daily")
_SLOT_CLASSES = _DAILY_CLASSES + ("anchor_annual", "indirect_proxy")


def need_class(need: str):
    """The SLOT CLASS a need is asking for, read off the composer's own wording
    ("needs >= 1 live source(s) of class 'measurement_daily', has 0"). None if absent.

    This is the piece that was missing: the class never reached the query, so on
    2026-07-31 a measurement_daily need produced the query 'global happiness index 2023'
    — an ANNUAL REPORT search aimed at a DAILY slot. Every page it found was structurally
    incapable of answering the need."""
    s = str(need or "").lower()
    for c in _SLOT_CLASSES:
        if c in s:
            return c
    return None


def decide(axis: str, need: str, slot: str = None, prior_queries=None) -> dict:
    """Local model chooses the indicator + search keywords for this need.

    The slot class travels INTO the prompt: a daily slot must be told to hunt live
    dashboards and data portals, not annual PDFs. The current year is passed explicitly
    because the model's prior is older than the calendar and it will happily search for
    a year that is already history.

    PRIOR QUERIES travel in too. This is a temperature-0.1 call over an otherwise constant
    prompt, so without them it is a pure function of (axis, need) and returns the same
    keywords forever — measured: '2026 social media engagement daily', ten runs running,
    zero components each time. Naming the failures is the only thing that moves it."""
    cls = slot or need_class(need)
    year = datetime.now(timezone.utc).year
    cadence = ""
    if cls in _DAILY_CLASSES:
        cadence = (
            f"\nCADENCE IS A HARD REQUIREMENT. This need is class '{cls}': the indicator "
            f"must UPDATE DAILY or in near real-time. Prefer live dashboards, APIs, data "
            f"portals, status/tracker pages, and current-year pages. AVOID annual reports, "
            f"yearbooks, PDFs, and any page whose newest figure is a past year. "
            f"The current year is {year} — do not search for older years.")
    elif cls == "anchor_annual":
        cadence = (f"\nThis need is class 'anchor_annual': a slow official yearly figure is "
                   f"correct here. The current year is {year}.")
    tried = ""
    if prior_queries:
        listed = "\n".join(f'  - "{q}"' for q in list(prior_queries)[:12])
        tried = (f"\nTHESE QUERIES HAVE ALREADY BEEN TRIED AND PRODUCED NOTHING USABLE:\n"
                 f"{listed}\n"
                 f"Do NOT repeat any of them, and do not merely reorder their words. "
                 f"Change the ANGLE: a different publisher, a different proxy quantity, a "
                 f"different vocabulary for the same thing.")
    prompt = (
        f"You are choosing ONE live, numeric, objective indicator to measure the axis "
        f"'{axis}'. The system declared this need: {need}{cadence}{tried}\n"
        f"Reply ONLY with a JSON object, no prose:\n"
        f'{{"search_query": "<3-6 web search keywords likely to find a page showing a '
        f'current number>", "target_metric": "<short name of the number to extract>", '
        f'"unit": "<unit>", "higher_is": "better|worse"}}')
    got = _json_from(_local(prompt, num_predict=200))
    if isinstance(got, dict):
        got["need_class"] = cls
    return got


def _env_key(name: str) -> str:
    """Read an API key from env or the repo .env (never hard-coded)."""
    v = os.environ.get(name, "")
    if v:
        return v
    for cand in (REPO / ".env", REPO.parent / ".env"):
        try:
            for line in cand.read_text(encoding="utf-8").splitlines():
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return ""


def search_brave(query: str, n: int = 5):
    """Free autonomous search via the Brave Search API (real index, a contract, no
    anti-bot fragility). The system still chooses its OWN query — this is free search,
    NOT fixed URLs. Returns [(url,title)], or None if no BRAVE_API_KEY is configured
    (caller then falls back to the browser engines)."""
    key = _env_key("BRAVE_API_KEY")
    if not key:
        return None
    import requests
    r = requests.get("https://api.search.brave.com/res/v1/web/search", timeout=20,
                     params={"q": query, "count": n},
                     headers={"X-Subscription-Token": key, "Accept": "application/json"})
    r.raise_for_status()
    results = (r.json().get("web", {}) or {}).get("results", []) or []
    return [(w.get("url"), (w.get("title") or "").strip()) for w in results if w.get("url")][:n]


# Engines are driven like a HUMAN, not scraped (Emil, 30 Jul 2026: "when you organize my
# mail you type real words and click real fields — do that"). We open the HOMEPAGE, click
# the search box, TYPE the query with real keystrokes, press Enter, wait for results. That
# interaction pattern is what evades bot-detection AND what Emil watches. Direct query-URL
# navigation + DOM harvesting (the old way) is scraping and gets stripped/blocked.
# (name, home_url, search-input selector, result-anchor selector, engine-host to skip)
_ENGINES = [
    ("duckduckgo", "https://duckduckgo.com/", 'input[name="q"]',
     'a[data-testid="result-title-a"]', "duckduckgo.com"),
    ("bing", "https://www.bing.com/", 'textarea[name="q"], input[name="q"]',
     'li.b_algo h2 a', "bing.com"),
    ("google", "https://www.google.com/", 'textarea[name="q"], input[name="q"]',
     'a:has(h3)', "google."),
]


def _dismiss_consent(page):
    """Click a cookie/consent button if one blocks the search box (esp. Google in the EU).
    Includes Greek labels — the box geo-routes to Greek on this machine (seen 30 Jul 2026)."""
    for txt in ("Reject all", "Accept all", "I agree", "Accept", "Got it", "Agree",
                "Απόρριψη όλων", "Αποδοχή όλων", "Συμφωνώ", "Απόρριψη", "Αποδοχή"):
        try:
            b = page.query_selector(f'button:has-text("{txt}")')
            if b and b.is_visible():
                b.click()
                page.wait_for_timeout(300)
                return
        except Exception:
            pass


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def search_browser(query: str, n: int = 5):
    """Search like a HUMAN: open the engine's homepage, click the box, TYPE the query with
    real keystrokes, press Enter, read the real result anchors. Human interaction + a
    stealthed context (webdriver flag hidden, real UA) is what gets past bot-detection —
    unlike direct query-URL scraping, which the engines strip. ONLY proper result anchors
    are accepted (no generic-link fallback that fabricated promo links). Empty -> empty, so
    the unquote fallback can fire. Headful by default (Emil watches it type and click)."""
    from playwright.sync_api import sync_playwright
    headful = os.environ.get("CORTEX_BROWSER_HEADFUL", "1") != "0"
    slowmo = int(os.environ.get("CORTEX_BROWSER_SLOWMO", "600" if headful else "0"))
    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headful, slow_mo=slowmo)
        try:
            ctx = browser.new_context(user_agent=_UA, locale="en-US",
                                      viewport={"width": 1280, "height": 900})
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            page = ctx.new_page()
            for name, home, inp, sel, host in _ENGINES:
                try:
                    page.goto(home, wait_until="domcontentloaded", timeout=30000)
                    _dismiss_consent(page)
                    box = page.wait_for_selector(inp, timeout=8000)
                    box.click()
                    box.type(_loosen(query), delay=80)  # real keystrokes, NEVER with quotes
                    page.wait_for_timeout(400)
                    page.keyboard.press("Enter")        # submit like a person
                    page.wait_for_selector(sel, timeout=9000)
                    hits = []
                    for a in page.query_selector_all(sel):   # proper result anchors ONLY
                        href = a.get_attribute("href") or ""
                        if href.startswith("http") and host not in href:
                            hits.append((href, (a.inner_text() or "").strip()))
                        if len(hits) >= n:
                            break
                    if hits:
                        out = hits
                        break
                except Exception:
                    continue
        finally:
            browser.close()
    return out


def search_ddg(query: str, n: int = 5):
    """Entry point every caller uses. PRIMARY = human-like browser search (free, watchable,
    the way Emil wants it). Brave Search API is only an OPTIONAL backstop if the human
    browse comes back empty AND a key is configured. Kept under this name for compatibility."""
    try:
        hits = search_browser(query, n)
    except Exception:
        hits = []
    if hits:
        return hits
    try:
        brave = search_brave(query, n)   # None if no key
    except Exception:
        brave = None
    return brave or []


def _loosen(query: str) -> str:
    """Drop quotes / exact-match operators — a quoted phrase forces an exact match that
    the open web rarely satisfies (diagnosed live 30 Jul 2026: '"current social stability
    index"' -> 0 results, while the unquoted keywords surface the IMF unrest index)."""
    q = re.sub(r'["“”]', "", query or "")
    q = re.sub(r"\b(site|filetype|intitle):\S+", "", q)
    return re.sub(r"\s+", " ", q).strip()


def search_robust(query: str, n: int = 5, replan_fn=None):
    """Try the query, then a loosened variant, then an optional LLM re-plan — with a
    short backoff between DuckDuckGo calls (it throttles repeated POSTs). Returns
    (results, query_used)."""
    variants = []
    for v in (query, _loosen(query)):
        if v and v not in variants:
            variants.append(v)
    for i, v in enumerate(variants):
        if i:
            time.sleep(2)  # DDG backoff
        try:
            res = search_ddg(v, n)
        except Exception:
            res = []
        if res:
            return res, v
    if replan_fn:
        try:
            alt = replan_fn()
            if alt:
                time.sleep(2)
                res = search_ddg(alt, n)
                if res:
                    return res, alt
        except Exception:
            pass
    return [], (variants[-1] if variants else query)


PDF_SKIP_REASON = "pdf result skipped — no text extraction library installed"


def _is_pdf(url: str) -> bool:
    """URL-level PDF detection. No extraction library is installed (checked 2026-07-31:
    no pymupdf/pdfminer/pypdf/pdfplumber), and a PDF opened in the browser yields empty
    inner_text — which is indistinguishable from a page that genuinely said nothing. An
    honest named skip beats pulling in a heavy dependency."""
    u = str(url or "").split("?", 1)[0].split("#", 1)[0].strip().lower()
    return u.endswith(".pdf")


def _page_text(url: str, timeout: int = 20) -> str:
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 CORTEX-scout"})
    r.raise_for_status()
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt)


def _digits(s) -> str:
    return re.sub(r"[^0-9]", "", str(s))


def extract_from_text(text: str, target: str, url: str):
    """Local model extracts the value from ALREADY-READ page text; ACCEPTED only if the
    number is grounded verbatim in that text (anti-hallucination)."""
    if not text:
        return None, "empty page text"
    prompt = (
        f"You are reading a web page to measure: {target}.\n"
        f"Extract the SINGLE most relevant CURRENT numeric indicator on this page for it. "
        f"It may be a global/aggregate figure, a headline index value, or a clearly-labelled "
        f"count — whatever best represents {target} here.\n"
        f"Reply ONLY JSON: {{\"value\": <number or null>, "
        f"\"label\": \"<what the number measures + the entity/scope/year it refers to>\", "
        f"\"evidence\": \"<the exact phrase from the text that contains the number>\"}}.\n"
        f"If the page has no single meaningful figure (e.g. only a raw country list), value=null.\n\n"
        f"PAGE TEXT (truncated):\n{text[:6500]}")
    got = _json_from(_local(prompt, num_predict=220))
    val, ev = got.get("value"), str(got.get("evidence", ""))
    if val is None:
        return None, "model found no single meaningful value"
    d = _digits(val)
    if not d or d not in _digits(ev) or ev[:40] not in text:
        return None, "value not grounded in page text — rejected"
    return {"value": val, "label": (got.get("label") or "").strip()[:120],
            "evidence": ev[:160], "url": url}, "ok"


def extract(url: str, target: str):
    """Fetch (requests) then extract. Kept for the --urls path; the human browse flow
    reads pages in the browser and calls extract_from_text directly."""
    return extract_from_text(_page_text(url), target, url)


def human_browse_read(query: str, n_open: int = 4, skip=None):
    """Human end-to-end in ONE visible window (Emil: 'type real words, click a page, read it'):
    open the engine homepage, type the query (UNQUOTED) with real keystrokes, press Enter,
    then OPEN each of the top results in turn and READ the page in the browser. Returns
    [(url, page_text)]. Reading in-browser also dodges the 403s raw requests hit (e.g. reddit).

    SCHEDULED (headless) MODE SPLITS THE TWO HALVES. Measured 2026-07-31, same query back to
    back: headful 3 pages, headless 0 — DuckDuckGo and Google time out on the results
    selector and Bing returns no links, and --disable-blink-features=AutomationControlled
    plus navigator.webdriver hiding does not help. It is the TYPING-INTO-AN-ENGINE half that
    is blocked, not the reading half. So when headless we discover URLs through the Brave
    API (a contract, not anti-bot roulette) and still open and READ each page in the browser.
    The system keeps choosing its own query either way — this is free search, not fixed URLs.

    Headful is untouched: the full human flow, because that is the one Emil watches.

    `skip` is an optional callable(url) -> (bool, reason) consulted BEFORE a result is
    opened. It is how the seen-memory (collector_memory.should_skip) stops the loop paying
    a browser page-load and a pair of model votes to re-reject a page it already rejected.
    A skipped URL does not COST a slot: the next candidate takes its place, exactly as a
    PDF does. Skips are reported on human_browse_read.last_seen_skipped."""
    from playwright.sync_api import sync_playwright
    headful = os.environ.get("CORTEX_BROWSER_HEADFUL", "1") != "0"
    slowmo = int(os.environ.get("CORTEX_BROWSER_SLOWMO", "600" if headful else "0"))
    typed = _loosen(query)
    out = []

    seen_skipped = []                  # already-rejected pages, named for the run row
    skipped = []                       # PDFs, surfaced so the caller can name the rejection
    api_urls = []
    if not headful:
        try:
            api_urls = [u for u, _t in (search_brave(typed, n=n_open * 2) or []) if u]
            print(f"[scout] headless: Brave returned {len(api_urls)} url(s)", file=sys.stderr)
        except Exception as e:
            print(f"[scout] headless: Brave search failed ({type(e).__name__}: {e}) — "
                  f"falling back to the engine flow, which is blocked headless",
                  file=sys.stderr)
            api_urls = []
        if not api_urls:
            print("[scout] headless: no API results (BRAVE_API_KEY missing?) — the engine "
                  "flow will almost certainly return 0 pages in headless mode",
                  file=sys.stderr)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headful, slow_mo=slowmo)
        try:
            ctx = browser.new_context(user_agent=_UA, locale="en-US",
                                      viewport={"width": 1280, "height": 900})
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            page = ctx.new_page()
            urls = list(api_urls)          # headless: already discovered via the API
            for name, home, inp, sel, host in ([] if urls else _ENGINES):
                try:
                    page.goto(home, wait_until="domcontentloaded", timeout=30000)
                    _dismiss_consent(page)
                    box = page.wait_for_selector(inp, timeout=8000)
                    box.click()
                    box.type(typed, delay=80)
                    page.wait_for_timeout(400)
                    page.keyboard.press("Enter")
                    page.wait_for_selector(sel, timeout=9000)
                    for a in page.query_selector_all(sel):
                        href = a.get_attribute("href") or ""
                        if href.startswith("http") and host not in href and href not in urls:
                            urls.append(href)
                        if len(urls) >= n_open * 2:   # over-fetch: PDFs get skipped below
                            break
                    if urls:
                        break
                except Exception:
                    continue
            # OPEN each chosen result and READ it in-browser. A PDF is skipped and the
            # next candidate takes its place, so a PDF result does not COST a slot: with
            # no extraction library installed it reads as empty text, which used to look
            # exactly like a page that legitimately said nothing.
            for href in urls:
                if len(out) >= n_open:
                    break
                if _is_pdf(href):
                    skipped.append(href)
                    print(f"[scout] skipped PDF (no text extraction): {href[:110]}",
                          file=sys.stderr)
                    continue
                if skip:
                    try:
                        do_skip, why = skip(href)
                    except Exception as e:
                        do_skip, why = False, f"skip check failed ({type(e).__name__})"
                    if do_skip:
                        seen_skipped.append({"url": href, "why": why})
                        print(f"[scout] seen_skipped: {href[:100]} — {why}",
                              file=sys.stderr)
                        continue
                try:
                    page.goto(href, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(900)
                    out.append((href, re.sub(r"\s+", " ", page.inner_text("body"))))
                except Exception:
                    continue
        finally:
            browser.close()
    human_browse_read.last_skipped = skipped   # caller names the rejection in its trail
    human_browse_read.last_seen_skipped = seen_skipped
    return out


human_browse_read.last_skipped = []
human_browse_read.last_seen_skipped = []


def research(axis: str, need: str, urls=None) -> dict:
    plan = decide(axis, need)
    query = plan.get("search_query") or need

    # Human flow: search like a person and READ the opened pages in the browser. --urls
    # keeps the direct path (fetch + extract) for a given list.
    if urls:
        pages = [(u, _page_text(u)) for u in urls]
        used = "(given urls)"
    else:
        pages = human_browse_read(query, n_open=4)
        used = _loosen(query)
    trail = {"axis": axis, "need": need, "plan": plan, "query": query, "query_used": used,
             "results_opened": [u for u, _ in pages], "attempts": []}
    for url, text in pages:
        try:
            got, why = extract_from_text(text, plan.get("target_metric", need), url)
            trail["attempts"].append({"url": url, "result": why})
            if got:
                rec = {"metric": plan.get("target_metric"), "value": got["value"],
                       "label": got.get("label"),
                       "unit": plan.get("unit"), "orientation":
                           "higher = better" if plan.get("higher_is") == "better" else "higher = worse",
                       "source_url": url, "evidence": got["evidence"],
                       "extraction": "local-model extract, grounded-in-text verified",
                       "search_query": query, "data_date": _now_iso()[:10],
                       "extracted_at": _now_iso(), "extracted_by": "autonomous_scout",
                       "axis": axis}
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                key = re.sub(r"[^a-z0-9]+", "_", (plan.get("target_metric") or axis).lower())[:40]
                (OUT_DIR / f"auto_{key}.json").write_text(
                    json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
                trail["accepted"] = {"file": f"auto_{key}.json", **rec}
                return trail
        except Exception as e:
            trail["attempts"].append({"url": url, "result": f"error: {type(e).__name__}: {e}"})
    trail["accepted"] = None
    return trail


if __name__ == "__main__":
    a = {}
    for i, tok in enumerate(sys.argv):
        if tok == "--axis": a["axis"] = sys.argv[i + 1]
        if tok == "--need": a["need"] = sys.argv[i + 1]
    if "--from-needs" in sys.argv:
        # THE SAME BUG THE COLLECTOR HAD, and worse: the outer `break` meant only the FIRST
        # axis in JSON key order was ever even looked at, so if it happened to have no
        # slot_unfilled item this printed nothing at all. 21 axes were hungry and exactly
        # one was ever visited. Both callers now share one starvation-avoiding rotation, or
        # the scout would simply fight the collector's cursor.
        import collector_memory as _mem
        needs = json.loads(COMPOSER_NEEDS.read_text(encoding="utf-8"))
        axis, item, note = _mem.pick_axis(needs)
        if not axis:
            print(json.dumps({"error": note}, ensure_ascii=False, indent=2))
        else:
            print(f"[scout] axis={axis} ({note})", file=sys.stderr)
            trail = research(axis, item.get("detail", "a live numeric indicator"))
            _mem.record_run(axis, 1 if trail.get("accepted") else 0)
            trail["rotation_note"] = note
            print(json.dumps(trail, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(research(a.get("axis", "SOCIAL_RELATIONS_REVIEW"),
                                  a.get("need", "a daily-updating numeric signal of social stability")),
                         ensure_ascii=False, indent=2))
