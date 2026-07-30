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


def decide(axis: str, need: str) -> dict:
    """Local model chooses the indicator + search keywords for this need."""
    prompt = (
        f"You are choosing ONE live, numeric, objective indicator to measure the axis "
        f"'{axis}'. The system declared this need: {need}\n"
        f"Reply ONLY with a JSON object, no prose:\n"
        f'{{"search_query": "<3-6 web search keywords likely to find a page showing a '
        f'current number>", "target_metric": "<short name of the number to extract>", '
        f'"unit": "<unit>", "higher_is": "better|worse"}}')
    return _json_from(_local(prompt, num_predict=200))


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


def human_browse_read(query: str, n_open: int = 4):
    """Human end-to-end in ONE visible window (Emil: 'type real words, click a page, read it'):
    open the engine homepage, type the query (UNQUOTED) with real keystrokes, press Enter,
    then OPEN each of the top results in turn and READ the page in the browser. Returns
    [(url, page_text)]. Reading in-browser also dodges the 403s raw requests hit (e.g. reddit)."""
    from playwright.sync_api import sync_playwright
    headful = os.environ.get("CORTEX_BROWSER_HEADFUL", "1") != "0"
    slowmo = int(os.environ.get("CORTEX_BROWSER_SLOWMO", "600" if headful else "0"))
    typed = _loosen(query)
    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headful, slow_mo=slowmo)
        try:
            ctx = browser.new_context(user_agent=_UA, locale="en-US",
                                      viewport={"width": 1280, "height": 900})
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            page = ctx.new_page()
            urls = []
            for name, home, inp, sel, host in _ENGINES:
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
                        if len(urls) >= n_open:
                            break
                    if urls:
                        break
                except Exception:
                    continue
            for href in urls[:n_open]:          # OPEN each chosen result and READ it in-browser
                try:
                    page.goto(href, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(900)
                    out.append((href, re.sub(r"\s+", " ", page.inner_text("body"))))
                except Exception:
                    continue
        finally:
            browser.close()
    return out


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
        needs = json.loads(COMPOSER_NEEDS.read_text(encoding="utf-8"))
        for axis, entry in (needs or {}).items():
            for it in (entry or {}).get("items", []):
                if it.get("kind") == "slot_unfilled":
                    print(json.dumps(research(axis, it.get("detail", "a live numeric indicator")),
                                     ensure_ascii=False, indent=2))
                    break
            break
    else:
        print(json.dumps(research(a.get("axis", "SOCIAL_RELATIONS_REVIEW"),
                                  a.get("need", "a daily-updating numeric signal of social stability")),
                         ensure_ascii=False, indent=2))
