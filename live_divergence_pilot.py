#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_divergence_pilot.py — Phase 3 Part 2: live web signal as a THIRD divergence source,
alongside WB (quantitative) and V-Dem (qualitative-annual) from the validated pilot
(_divergence_pilot.py, commit 50bc2bf).

Construct for this run: media_freedom (V-Dem v2x_freexp_altinf) — most documented, best
starting point per the approved design.

Chain per country: EN + local-language queries -> DDG search (Level 1, read-only) ->
classify each result's direction (CONFIRMS/CONTRADICTS/NEUTRAL the low V-Dem reading) via
LLM -> weight by publisher independence (V-Dem freexp of the OUTLET's country) ->
aggregate -> structured JSON with links.

Pre-registered test: CN/RS/RU/TR/BA (facade top 5, commit 50bc2bf) show a live signal
that CONFIRMS weak media freedom. EE/DK (controls) do not.

n_sources < 5 (informative sources: CONFIRMS+CONTRADICTS, NEUTRAL excluded) ->
status=INSUFFICIENT_DATA, agrees_with_vdem=null. Never silently treated as False.

Level 1 autonomy only: web_search (DDGS.text), no POST, no writes outside
output/phase3_pilot/. Rate limit: 5 DDG search requests/min (lesson from the WB batch
rate-limit incident). Fetches cached to avoid repeat searches on re-run.

Not part of the production pipeline.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from ddgs import DDGS
from core.groq_backend import call_groq
from wellbeing_country import _load_vdem, _iso2_to_iso3

OUT_DIR = BASE / "output" / "phase3_pilot"
CACHE_DIR = OUT_DIR / "_search_cache"

CONSTRUCT = "media_freedom"
N_SOURCES_MIN = 5          # below this -> INSUFFICIENT_DATA, not a false "not facade"
CONFIRM_THRESHOLD = 0.50   # weighted_confirm >= this -> live signal confirms weak practice
DDG_MIN_INTERVAL = 12.0    # seconds -> 5 requests/min ceiling
MAX_RESULTS_PER_QUERY = 5

PILOT_COUNTRIES = {
    "CN": {"name": "China",                  "local_name": "中国",           "lang": "zh"},
    "RS": {"name": "Serbia",                 "local_name": "Srbija",                  "lang": "sr"},
    "RU": {"name": "Russia",                 "local_name": "Россия", "lang": "ru"},
    "TR": {"name": "Turkiye",                "local_name": "Türkiye",             "lang": "tr"},
    "BA": {"name": "Bosnia and Herzegovina", "local_name": "Bosna i Hercegovina",     "lang": "bs"},
    "EE": {"name": "Estonia",                "local_name": "Eesti",                   "lang": "et"},
    "DK": {"name": "Denmark",                "local_name": "Danmark",                 "lang": "da"},
}
FACADE_EXPECTED = {"CN", "RS", "RU", "TR", "BA"}
CONTROL_EXPECTED = {"EE", "DK"}

QUERY_TOPICS_EN = [
    "press freedom {country} report",
    "media independence {country}",
]

# Known major outlet -> home country (extend as needed; not exhaustive by design)
OUTLET_COUNTRY = {
    "reuters.com": "GB", "apnews.com": "US", "bbc.com": "GB", "bbc.co.uk": "GB",
    "theguardian.com": "GB", "nytimes.com": "US", "cnn.com": "US", "washingtonpost.com": "US",
    "aljazeera.com": "QA", "dw.com": "DE", "france24.com": "FR", "rferl.org": "US",
    "themoscowtimes.com": "NL", "rsf.org": "FR", "hrw.org": "US", "freedomhouse.org": "US",
    "cpj.org": "US", "politico.eu": "BE", "euractiv.com": "BE", "balkaninsight.com": "RS",
    "meduza.io": "LV", "novayagazeta.eu": "LV",
}
TLD_COUNTRY = {
    "ru": "RU", "cn": "CN", "rs": "RS", "tr": "TR", "ba": "BA", "ee": "EE", "dk": "DK",
    "uk": "GB", "de": "DE", "fr": "FR", "us": "US",
}

def _parse_llm_json(text: str):
    """Robust JSON extraction from LLM output — handles code fences, <think> blocks,
    and falls back to regex-extracting a {...} or [...] block from noisy text.
    Same pattern as media_intel_worker._parse_llm_json (fallback LLMs, e.g. OpenRouter
    under Groq cooldown, don't always return clean JSON)."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    if "</think>" in text:
        text = text.split("</think>")[-1]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for pattern in (r"\{[^{}]*\}", r"\[[^\[\]]*\]"):
            m = re.search(pattern, text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass
    return None


_last_ddg_call = 0.0


def _throttle_ddg() -> None:
    global _last_ddg_call
    elapsed = time.time() - _last_ddg_call
    if elapsed < DDG_MIN_INTERVAL:
        time.sleep(DDG_MIN_INTERVAL - elapsed)
    _last_ddg_call = time.time()


def _cache_path(query: str) -> Path:
    h = hashlib.md5(query.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{h}.json"


def ddg_search_cached(query: str, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    cp = _cache_path(query)
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    _throttle_ddg()
    try:
        results = DDGS().text(query, max_results=max_results)
    except Exception as e:
        print(f"  [DDG] error for {query!r}: {e}")
        results = []
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def translate_topics(topics: list[str], lang: str) -> list[str]:
    if lang == "en":
        return topics
    prompt = (
        f"Translate these short search-query phrases into {lang} (ISO 639-1). "
        f"Keep them as natural search queries, not literal word-for-word.\n"
        + "\n".join(f"- {t}" for t in topics)
        + '\n\nReturn ONLY a JSON array of translated strings, same order, no explanation.'
    )
    try:
        raw = call_groq(prompt, max_tokens=200)
        arr = _parse_llm_json(raw)
        if isinstance(arr, list) and len(arr) == len(topics):
            return arr
    except Exception as e:
        print(f"  [translate] failed for lang={lang}: {e}")
    return topics  # fallback: reuse English topics


def outlet_country_for(url: str) -> tuple[str, str]:
    """Return (country_code, method) for weighting purposes."""
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    if not m:
        return "unknown", "no_domain"
    domain = m.group(1).lower()
    for known, cc in OUTLET_COUNTRY.items():
        if known in domain:
            return cc, "known_outlet"
    tld = domain.rsplit(".", 1)[-1]
    if tld in TLD_COUNTRY:
        return TLD_COUNTRY[tld], "tld"
    return "unknown", "unresolved"


def independence_weight(outlet_cc: str, vdem: dict) -> float:
    if outlet_cc == "unknown":
        return 0.5  # neutral default, flagged separately in output
    iso3 = _iso2_to_iso3(outlet_cc)
    if iso3 and iso3 in vdem:
        return round(vdem[iso3]["v2x_freexp_altinf"], 3)
    return 0.5


def classify_direction(country_name: str, qual_pct: float, title: str, body: str) -> dict:
    prompt = (
        f"V-Dem experts rate {country_name}'s media freedom / freedom of expression at "
        f"percentile {qual_pct:.2f} out of 1.0 (low = weak, censored, unfree in practice).\n\n"
        f"Does the following search result describe conditions CONSISTENT with that low "
        f"rating (CONFIRMS), conditions clearly BETTER than that (CONTRADICTS), or is it "
        f"off-topic / not enough signal (NEUTRAL)?\n\n"
        f"Title: {title}\nSnippet: {body}\n\n"
        'Return ONLY JSON: {"direction": "CONFIRMS|CONTRADICTS|NEUTRAL", "rationale": "<15 words>"}'
    )
    try:
        raw = call_groq(prompt, max_tokens=400)
        data = _parse_llm_json(raw)
        if not data:
            return {"direction": "NEUTRAL", "rationale": f"classify_error: unparseable LLM output: {raw[:80]!r}"}
        direction = data.get("direction", "NEUTRAL")
        if direction not in ("CONFIRMS", "CONTRADICTS", "NEUTRAL"):
            direction = "NEUTRAL"
        return {"direction": direction, "rationale": data.get("rationale", "")}
    except Exception as e:
        return {"direction": "NEUTRAL", "rationale": f"classify_error: {e}"}


def get_freexp_pct(vdem: dict, universe_iso2: list[str]) -> dict[str, float]:
    """Percentile-rank v2x_freexp_altinf across all V-Dem countries (not just the 7)."""
    raw = {iso3: d["v2x_freexp_altinf"] for iso3, d in vdem.items()}
    ordered = sorted(raw.items(), key=lambda kv: kv[1])
    n = len(ordered)
    rank_by_iso3 = {k: (i / (n - 1) if n > 1 else 0.5) for i, (k, _) in enumerate(ordered)}
    out = {}
    for iso2 in universe_iso2:
        iso3 = _iso2_to_iso3(iso2)
        if iso3 and iso3 in rank_by_iso3:
            out[iso2] = rank_by_iso3[iso3]
    return out


def run_country(iso2: str, info: dict, qual_pct: float, vdem: dict) -> dict:
    print(f"\n{'='*70}\n[{iso2}] {info['name']}  (V-Dem freexp percentile={qual_pct:.3f})\n{'='*70}")

    topics_en = [t.format(country=info["name"]) for t in QUERY_TOPICS_EN]
    topics_local = translate_topics(
        [t.format(country=info["local_name"]) for t in QUERY_TOPICS_EN], info["lang"]
    ) if info["lang"] != "en" else topics_en

    all_queries = list(dict.fromkeys(topics_en + topics_local))  # dedupe, preserve order

    seen_urls: set[str] = set()
    sources = []
    for q in all_queries:
        print(f"  [search] {q!r}")
        results = ddg_search_cached(q)
        print(f"    -> {len(results)} results")
        for r in results:
            url = r.get("href", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title, body = r.get("title", ""), r.get("body", "")
            cls = classify_direction(info["name"], qual_pct, title, body)
            outlet_cc, method = outlet_country_for(url)
            weight = independence_weight(outlet_cc, vdem)
            sources.append({
                "url": url, "title": title, "outlet_country": outlet_cc,
                "outlet_resolution": method, "weight": weight,
                "direction": cls["direction"], "rationale": cls["rationale"],
                "query": q,
            })
            print(f"    [{cls['direction']:11}] w={weight:.2f} cc={outlet_cc:7} {title[:60]}")
            time.sleep(0.3)

    informative = [s for s in sources if s["direction"] in ("CONFIRMS", "CONTRADICTS")]
    n_sources = len(informative)

    result = {
        "iso2": iso2, "name": info["name"], "construct": CONSTRUCT,
        "official": {"vdem_freexp_pct": qual_pct},
        "n_total_sources": len(sources), "n_informative_sources": n_sources,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
    }

    if n_sources < N_SOURCES_MIN:
        result["status"] = "INSUFFICIENT_DATA"
        result["agrees_with_vdem"] = None
        result["confidence"] = "LOW"
        result["note"] = f"only {n_sources} informative sources (< {N_SOURCES_MIN}) — cannot confirm or contradict"
    else:
        confirm_w = sum(s["weight"] for s in informative if s["direction"] == "CONFIRMS")
        total_w = sum(s["weight"] for s in informative)
        weighted_confirm = confirm_w / total_w if total_w > 0 else 0.0
        agrees = weighted_confirm >= CONFIRM_THRESHOLD
        result["status"] = "OK"
        result["weighted_confirm"] = round(weighted_confirm, 3)
        result["agrees_with_vdem"] = agrees
        result["confidence"] = "HIGH" if n_sources >= 15 else "MEDIUM"

    return result


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vdem = _load_vdem()
    freexp_pct = get_freexp_pct(vdem, list(PILOT_COUNTRIES))

    # Optional: only (re)run specific countries, e.g. `python live_divergence_pilot.py BA EE DK`.
    # Countries not re-run are loaded from their existing output/phase3_pilot/{ISO2}_*.json
    # so the summary table still covers all 7 without re-spending LLM/DDG budget.
    only = set(a.upper() for a in sys.argv[1:]) or None

    all_results = {}
    for iso2, info in PILOT_COUNTRIES.items():
        qual_pct = freexp_pct.get(iso2)
        if qual_pct is None:
            print(f"[{iso2}] SKIP — no V-Dem freexp data")
            continue
        out_path = OUT_DIR / f"{iso2}_{CONSTRUCT}.json"
        if only and iso2 not in only:
            if out_path.exists():
                all_results[iso2] = json.loads(out_path.read_text(encoding="utf-8"))
                print(f"[{iso2}] reused existing result (not in rerun list)")
            continue
        res = run_country(iso2, info, qual_pct, vdem)
        all_results[iso2] = res
        out_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [save] -> {out_path.relative_to(BASE)}")

    # ── Summary table ──
    print(f"\n\n{'='*90}")
    print("SUMMARY — live signal vs V-Dem facade classification")
    print(f"{'='*90}")
    print(f"{'ISO':4} {'freexp_pct':>10} {'n_info':>7} {'confirm%':>9} {'agrees_vdem':>12} {'expected':>10} {'match':>6}")
    print("-" * 70)
    for iso2, res in all_results.items():
        expected = "FACADE" if iso2 in FACADE_EXPECTED else "CONTROL"
        if res["status"] == "INSUFFICIENT_DATA":
            print(f"{iso2:4} {res['official']['vdem_freexp_pct']:10.3f} {res['n_informative_sources']:7} "
                  f"{'--':>9} {'INSUFFICIENT':>12} {expected:>10} {'?':>6}")
            continue
        agrees = res["agrees_with_vdem"]
        agrees_str = "True" if agrees else "False"
        if expected == "FACADE":
            match = "OK" if agrees else "FAIL"
        else:
            match = "OK" if not agrees else "FAIL"
        print(f"{iso2:4} {res['official']['vdem_freexp_pct']:10.3f} {res['n_informative_sources']:7} "
              f"{res['weighted_confirm']*100:8.1f}% {agrees_str:>12} {expected:>10} {match:>6}")

    print(f"\n[PRE-REGISTERED TEST] CN/RS/RU/TR/BA -> live confirms weak media freedom; EE/DK -> does not")
    facade_ok = all(
        all_results[i]["status"] == "OK" and all_results[i]["agrees_with_vdem"]
        for i in FACADE_EXPECTED if i in all_results
    )
    control_ok = all(
        all_results[i]["status"] != "OK" or not all_results[i]["agrees_with_vdem"]
        for i in CONTROL_EXPECTED if i in all_results
    )
    control_broke = any(
        all_results[i]["status"] == "OK" and all_results[i]["agrees_with_vdem"]
        for i in CONTROL_EXPECTED if i in all_results
    )
    if control_broke:
        print("  CONTROL FIRED FACADE -> STOP, inspect the metric before scaling.")
    elif facade_ok and control_ok:
        print("  RESULT: TEST PASSED")
    else:
        print("  RESULT: TEST FAILED (facade side incomplete or insufficient data) -- see table above")


if __name__ == "__main__":
    main()
