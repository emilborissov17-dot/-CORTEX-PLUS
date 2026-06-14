#!/usr/bin/env python3
"""
web_intelligence_agent.py — 24/7 Internet Intelligence Gathering
Покрива 28 оси на CORTEX++_QWEN.
Готов за self_observer.

REDESIGN: Заменя risk_level→trend с problem→solution фрейм.
risk_level остава САМО за dashboard (auto_levels). Тук генерираме:
  - problem: конкретен реален проблем от данните
  - root_cause: защо съществува
  - leverage_points: кои актьори/механизми имат най-голям ефект
  - proposed_actions: конкретни стъпки с measurable_goal
  - evidence: откъде знаем това (sources)

FIX: Robust JSON parsing в _analyze_for_axis — 3 опита преди UNKNOWN.
PARALLEL: ThreadPoolExecutor за паралелна обработка на оси.
MAX_AGE_HOURS: 6 часа вместо 2.
"""

import json
import os
import pathlib
import re
import sys
import time
import hashlib
import shutil
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

# -- Зависимости --------------------------------------------------------------

try:
    import feedparser
except ImportError:
    print("[WEB_INTEL] feedparser не е инсталиран: pip install feedparser --break-system-packages")
    sys.exit(1)

try:
    from ddgs import DDGS as _DDGS
    HAS_DDG = True
except ImportError:
    try:
        from duckduckgo_search import DDGS as _DDGS
        HAS_DDG = True
    except ImportError:
        HAS_DDG = False
        print("[WEB_INTEL] ddgs не е намерен — само RSS")

try:
    from youtube_intel import fetch_youtube_for_axis
    HAS_YOUTUBE = True
    print("[WEB_INTEL] YouTube модул активен")
except ImportError:
    HAS_YOUTUBE = False
    print("[WEB_INTEL] youtube_intel.py не е намерен — YouTube disabled")

# -- Конфигурация -------------------------------------------------------------

BASE_DIR = pathlib.Path(os.environ.get("CORTEX_BASE", pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(BASE_DIR))

AXIS_TIMEOUT_SEC = 90
MAX_AGE_HOURS    = 6   # Обновяване на 6 часа вместо 2
MAX_WORKERS      = 3   # Паралелни оси едновременно

# -- CLAUDE Query Proposals ---------------------------------------------------

CLAUDE_PROPOSALS_FILE = BASE_DIR / "memory" / "claude_query_proposals.json"

def _load_claude_proposals() -> dict:
    try:
        if CLAUDE_PROPOSALS_FILE.exists():
            data = json.loads(CLAUDE_PROPOSALS_FILE.read_text(encoding="utf-8"))
            proposals = {k: v for k, v in data.items() if not k.startswith("_")}
            if proposals:
                print(f"[WEB_INTEL] CLAUDE query proposals заредени: {len(proposals)} оси")
            return proposals
    except Exception as e:
        print(f"[WEB_INTEL] Грешка при зареждане на CLAUDE proposals: {e}")
    return {}

CLAUDE_QUERY_PROPOSALS = _load_claude_proposals()

try:
    from core.groq_backend import call_groq
except ImportError:
    def call_groq(prompt: str, max_tokens: int = 500) -> str:
        return "[LLM недостъпен]"

def _warmup_ollama():
    """Загрява Ollama модела при старт — преди паралелните оси."""
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        if not models:
            return
        preferred = next((m for m in ["qwen3:8b","qwen2.5:7b","qwen2.5:3b"] if m in models), models[0])
        print(f"[WEB_INTEL] Ollama warmup: зареждам {preferred}...")
        requests.post("http://localhost:11434/api/chat", json={
            "model": preferred,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "options": {"num_predict": 1},
        }, timeout=60)
        print(f"[WEB_INTEL] Ollama {preferred} готов ✓")
    except Exception as e:
        print(f"[WEB_INTEL] Ollama warmup пропуснат: {e}")

# -- Civilization goal --------------------------------------------------------

CIVILIZATION_GOAL = """
Maximize the sustainability and long-term viability of intelligent life
and its environments in the Universe, with priority for Earth.
Goals: sustainable civilization, dignity for all, transparent AGI,
peace and cooperation, healthy biosphere.
"""

# -- 28 оси + RSS конфигурация ------------------------------------------------

AXES = {
    "CLIMATE_GLOBAL_RISK_REVIEW": {
        "domain": "planet",
        "keywords": ["climate change", "global warming", "extreme weather", "IPCC"],
        "rss": [
            "https://www.nasa.gov/rss/dyn/breaking_news.rss",
            "https://www.carbonbrief.org/feed",
            "https://climate.nasa.gov/news/rss.xml",
        ],
    },
    "ENERGY_REVIEW": {
        "domain": "planet",
        "keywords": ["renewable energy", "solar power", "wind energy", "fossil fuels", "energy transition"],
        "rss": [
            "https://cleantechnica.com/feed/",
            "https://www.renewableenergyworld.com/feed/",
            "https://oilprice.com/rss/main",
        ],
    },
    "WATER_REVIEW": {
        "domain": "planet",
        "keywords": ["water scarcity", "freshwater", "drought", "ocean pollution"],
        "rss": [
            "https://www.waterworld.com/rss.xml",
            "https://www.circleofblue.org/feed/",
        ],
    },
    "FOOD_REVIEW": {
        "domain": "planet",
        "keywords": ["food security", "hunger", "agriculture", "famine"],
        "rss": [
            "https://www.fao.org/news/rss-feed/en/",
            "https://www.foodnavigator.com/rss/feed.php",
        ],
    },
    "MATERIALS_WASTE_REVIEW": {
        "domain": "planet",
        "keywords": ["plastic pollution", "recycling", "circular economy", "waste management"],
        "rss": [
            "https://www.waste360.com/rss.xml",
            "https://resource.co/rss.xml",
        ],
    },
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": {
        "domain": "planet",
        "keywords": ["biodiversity loss", "deforestation", "species extinction"],
        "rss": [
            "https://www.iucn.org/rss.xml",
            "https://www.sciencedaily.com/rss/plants_animals/endangered_animals.xml",
        ],
    },
    "HUMAN_WELL_BEING_REVIEW": {
        "domain": "human",
        "keywords": ["global health", "life expectancy", "mental health", "poverty", "WHO"],
        "rss": [
            "https://www.who.int/rss-feeds/news-english.xml",
            "https://feeds.bbci.co.uk/news/health/rss.xml",
        ],
    },
    "CULTURE_MEDIA_REVIEW": {
        "domain": "human",
        "keywords": ["media freedom", "misinformation", "social media"],
        "rss": [
            "https://rss.nytimes.com/services/xml/rss/nyt/Arts.xml",
            "https://www.theguardian.com/culture/rss",
        ],
    },
    "COGNITION_LEARNING_REVIEW": {
        "domain": "human",
        "keywords": ["education", "learning", "cognitive science", "AI education"],
        "rss": [
            "https://www.edsurge.com/feed",
            "https://feeds.feedburner.com/MindShift",
        ],
    },
    "SOCIAL_RELATIONS_REVIEW": {
        "domain": "human",
        "keywords": ["social cohesion", "inequality", "loneliness epidemic"],
        "rss": [
            "https://www.pewresearch.org/feed/",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
        ],
    },
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": {
        "domain": "human",
        "keywords": ["human rights", "democracy", "civil liberties"],
        "rss": [
            "https://www.hrw.org/rss",
            "https://freedomhouse.org/rss.xml",
        ],
    },
    "ECONOMY_WORK_REVIEW": {
        "domain": "civilization",
        "keywords": ["global economy", "GDP", "unemployment", "inflation"],
        "rss": [
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        ],
    },
    "INEQUALITY_POVERTY_REVIEW": {
        "domain": "civilization",
        "keywords": ["poverty", "income inequality", "wealth gap"],
        "rss": [
            "https://www.oxfam.org/en/feed",
            "https://blogs.worldbank.org/rss.xml",
        ],
    },
    "INFRASTRUCTURE_CITIES_REVIEW": {
        "domain": "civilization",
        "keywords": ["smart cities", "urban planning", "infrastructure"],
        "rss": [
            "https://www.smartcitiesdive.com/feeds/news/",
        ],
    },
    "GOVERNANCE_INSTITUTIONS_REVIEW": {
        "domain": "civilization",
        "keywords": ["geopolitics", "UN", "NATO", "war", "peace"],
        "rss": [
            "https://www.un.org/press/en/feed/",
            "https://foreignpolicy.com/feed/",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
        ],
    },
    "EDUCATION_CULTURE_REVIEW": {
        "domain": "civilization",
        "keywords": ["global education", "literacy", "UNESCO"],
        "rss": [
            "https://www.edsurge.com/feed",
        ],
    },
    "TECHNOLOGY_INFRA_REVIEW": {
        "domain": "civilization",
        "keywords": ["internet access", "digital divide", "5G", "semiconductor"],
        "rss": [
            "https://feeds.feedburner.com/TechCrunch",
            "https://www.wired.com/feed/rss",
        ],
    },
    "TECHNOLOGY_AI_REVIEW": {
        "domain": "civilization",
        "keywords": ["artificial intelligence", "AGI", "machine learning", "AI safety"],
        "rss": [
            "https://www.technologyreview.com/feed/",
            "https://venturebeat.com/category/ai/feed/",
            "https://aiweekly.co/issues.rss",
        ],
    },
    "SPACE_INFRASTRUCTURE_REVIEW": {
        "domain": "cosmos",
        "keywords": ["space exploration", "SpaceX", "NASA", "satellite"],
        "rss": [
            "https://www.spacenews.com/feed/",
            "https://spaceflightnow.com/feed/",
        ],
    },
    "COSMIC_RESOURCES_REVIEW": {
        "domain": "cosmos",
        "keywords": ["asteroid mining", "space resources", "space economy"],
        "rss": [
            "https://www.spacenews.com/feed/",
        ],
    },
    "LONG_TERM_FUTURE_REVIEW": {
        "domain": "cosmos",
        "keywords": ["existential risk", "civilization collapse", "future of humanity"],
        "rss": [
            "https://www.lesswrong.com/feed.xml",
            "https://forum.effectivealtruism.org/feed.xml",
        ],
    },
    "DEEP_TIME_RISKS_REVIEW": {
        "domain": "cosmos",
        "keywords": ["asteroid impact", "pandemic risk", "nuclear war"],
        "rss": [
            "https://www.who.int/rss-feeds/news-english.xml",
            "https://www.thebulletin.org/feed/",
        ],
    },
    "GENERAL_SELF_REVIEW": {
        "domain": "cosmos",
        "keywords": ["AI consciousness", "AGI progress", "AI safety"],
        "rss": [
            "https://www.technologyreview.com/feed/",
            "https://openai.com/blog/rss.xml",
        ],
    },
    "GOAL_PROGRESS_REVIEW": {
        "domain": "cosmos",
        "keywords": ["sustainable development goals", "SDG", "UN goals 2030"],
        "rss": [
            "https://www.un.org/sustainabledevelopment/feed/",
            "https://sdg.iisd.org/feed/",
        ],
    },
    "PLANETARY_POTENTIAL_REVIEW": {
        "domain": "planet",
        "keywords": ["geoengineering", "planetary boundaries", "tipping points"],
        "rss": [
            "https://www.sciencedaily.com/rss/earth_climate.xml",
        ],
    },
}

# -- Timeout ------------------------------------------------------------------

@contextmanager
def _time_limit(seconds: int):
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise TimeoutError(f"Axis timeout {seconds}s")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)

# -- Helpers ------------------------------------------------------------------

def _fetch_rss(url: str, max_items: int = 5) -> list:
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            items.append({
                "title":       entry.get("title", ""),
                "summary":     entry.get("summary", entry.get("description", ""))[:500],
                "link":        entry.get("link", ""),
                "published":   entry.get("published", ""),
                "source_type": "rss",
            })
        return items
    except Exception:
        return []


def _ddg_search(query: str, max_results: int = 5) -> list:
    if not HAS_DDG:
        return []
    try:
        with _DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return [
                {
                    "title":       r.get("title", ""),
                    "summary":     r.get("body", "")[:400],
                    "link":        r.get("href", ""),
                    "source_type": "ddg",
                }
                for r in results
            ]
    except Exception:
        return []


def _parse_llm_json(raw: str) -> dict:
    try:
        return json.loads(raw.strip())
    except Exception:
        pass

    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if not part or part.startswith("`"):
                continue
            try:
                return json.loads(part)
            except Exception:
                continue

    matches = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
    for match in sorted(matches, key=len, reverse=True):
        try:
            return json.loads(match)
        except Exception:
            continue

    raise ValueError(f"Не може да се parse JSON от LLM отговор: {raw[:200]}")


def _analyze_for_axis(axis: str, items: list, domain: str) -> dict:
    if not items:
        return {
            "problem":          "Няма достатъчно данни за анализ",
            "root_cause":       "Липсващи или недостъпни sources",
            "severity":         "UNKNOWN",
            "leverage_points":  [],
            "proposed_actions": [],
            "evidence":         [],
            "generalization":   "",
            "risk_level":       "UNKNOWN",
            "trend":            "UNKNOWN",
            "summary":          "Няма данни",
        }

    yt_items  = [i for i in items if i.get("source_type") == "youtube"]
    rss_items = [i for i in items if i.get("source_type") != "youtube"]

    rss_text = "\n".join([f"- {i['title']}: {i['summary'][:200]}" for i in rss_items[:8]])
    yt_text  = "\n".join([
        f"- [VIDEO] {i['title']}:\n  {i['summary'][:400]}"
        for i in yt_items[:3]
    ])

    sources_block = f"=== RSS/WEB ===\n{rss_text}"
    if yt_text:
        sources_block += f"\n\n=== YOUTUBE ТРАНСКРИПЦИИ ===\n{yt_text}"

    prompt = f"""You are an analyst for the CORTEX++ AGI system.
System goal: {CIVILIZATION_GOAL}

Analyze the data for axis {axis} (domain: {domain}):
{sources_block}

Return ONLY valid JSON without markdown. All text values must be in English:
{{
  "problem": "Specific real problem found in the data (not abstract, not 'risk is high')",
  "root_cause": "Why this problem exists — real underlying cause",
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "leverage_points": [
    "Which actor/mechanism has the greatest effect on the problem",
    "Second leverage point"
  ],
  "proposed_actions": [
    {{
      "action": "Specific concrete action",
      "measurable_goal": "How to measure if it worked",
      "timeframe": "short-term|medium-term|long-term"
    }}
  ],
  "evidence": ["Fact 1 from the data", "Fact 2 from the data"],
  "generalization": "How this problem connects to other domains",
  "summary": "1-2 sentence summary",
  "risk_level": "LOW|MEDIUM|HIGH|CRITICAL"
}}"""

    raw = ""
    try:
        raw = call_groq(prompt, max_tokens=800)
        result = _parse_llm_json(raw)
        if result.get("severity") not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            result["severity"] = result.get("risk_level", "UNKNOWN")
        return result
    except Exception as e:
        print(f"  [LLM_PARSE_ERROR] {axis}: {e}")
        return {
            "problem":          f"Анализ на {axis} — данни получени но LLM грешка",
            "root_cause":       f"LLM parsing грешка: {str(e)[:100]}",
            "severity":         "UNKNOWN",
            "leverage_points":  [],
            "proposed_actions": [],
            "evidence":         [i["title"] for i in items[:3]],
            "generalization":   "",
            "summary":          (rss_text or yt_text)[:200],
            "risk_level":       "UNKNOWN",
            "trend":            "UNKNOWN",
            "llm_raw":          raw[:500] if raw else "",
        }


def _get_output_path(axis: str, domain: str) -> pathlib.Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path  = BASE_DIR / "memory" / "web_intelligence" / today / domain
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{axis.lower()}_web_intel.json"


MIN_VALID_BYTES = 500  # Файл под това се счита за празен/прекъснат

def _already_fresh(path: pathlib.Path, max_age_hours: int = MAX_AGE_HOURS) -> bool:
    """Пресен = файлът съществува, има реално съдържание И е в рамките на MAX_AGE_HOURS."""
    if not path.exists():
        return False
    # Провери размер — прекъснат запис може да е празен или непълен JSON
    if path.stat().st_size < MIN_VALID_BYTES:
        print(f"    [STALE] {path.name} — твърде малък ({path.stat().st_size} bytes), ще се презареди")
        return False
    # Провери дали JSON-ът е валиден и има анализ
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        analysis = data.get("analysis", {})
        if not analysis or analysis.get("severity") in ("UNKNOWN", None) or not analysis.get("problem"):
            print(f"    [STALE] {path.name} — непълен анализ (severity={analysis.get('severity','?')}), ще се презареди")
            return False
    except Exception:
        print(f"    [STALE] {path.name} — невалиден JSON, ще се презареди")
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime) < timedelta(hours=max_age_hours)


# -- Checkpoint система -------------------------------------------------------

CHECKPOINT_FILE = BASE_DIR / "memory" / "web_intelligence" / "cycle_checkpoint.json"

def _checkpoint_load() -> dict:
    """Зарежда checkpoint от текущия ден, ако съществува и не е done."""
    try:
        if CHECKPOINT_FILE.exists():
            cp = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
            cp_date = cp.get("date", "")
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if cp_date == today and not cp.get("done", False):
                completed = cp.get("completed", [])
                print(f"[WEB_INTEL] RESUME: намерен checkpoint от днес — {len(completed)} оси завършени")
                return cp
    except Exception as e:
        print(f"[WEB_INTEL] Checkpoint четене грешка: {e}")
    return {}

def _checkpoint_save(completed: list, done: bool = False):
    """Записва прогреса след всяка успешна ос."""
    try:
        CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        cp = {
            "date":      datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "completed": completed,
            "done":      done,
        }
        CHECKPOINT_FILE.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WEB_INTEL] Checkpoint запис грешка: {e}")


# -- Основна функция за ос ---------------------------------------------------

def run_axis(axis: str, config: dict, force: bool = False) -> dict:
    domain      = config["domain"]
    output_path = _get_output_path(axis, domain)

    if not force and _already_fresh(output_path):
        print(f"  [SKIP] {axis} — пресен (={MAX_AGE_HOURS}h)")
        return json.loads(output_path.read_text(encoding="utf-8"))

    print(f"  [FETCH] {axis}...")
    all_items = []

    try:
        with _time_limit(AXIS_TIMEOUT_SEC):
            for url in config.get("rss", []):
                items = _fetch_rss(url, max_items=4)
                all_items.extend(items)
                if items:
                    print(f"    RSS {url[:50]}... → {len(items)} items")
                time.sleep(0.3)

            claude_queries = CLAUDE_QUERY_PROPOSALS.get(axis, [])
            if claude_queries:
                print(f"    [CLAUDE→] Умни queries за {axis}: {claude_queries[:2]}")

            if len(all_items) < 5 and HAS_DDG:
                search_queries = claude_queries[:2] if claude_queries else config.get("keywords", [])[:2]
                for kw in search_queries:
                    ddg = _ddg_search(kw, max_results=3)
                    all_items.extend(ddg)
                    time.sleep(0.5)

            if HAS_YOUTUBE:
                try:
                    if claude_queries:
                        config_with_proposals = dict(config)
                        config_with_proposals["claude_queries"] = claude_queries
                        yt_items = fetch_youtube_for_axis(axis, config_with_proposals, max_videos=3)
                    else:
                        yt_items = fetch_youtube_for_axis(axis, config, max_videos=3)
                    all_items.extend(yt_items)
                    yt_with_tr = sum(1 for i in yt_items if i.get("has_full_transcript"))
                    print(f"    YouTube: {len(yt_items)} видеа, {yt_with_tr} с транскрипция")
                except Exception as e:
                    print(f"    [YT] грешка: {e}")

    except TimeoutError:
        print(f"  [TIMEOUT] {axis} — изтекло {AXIS_TIMEOUT_SEC}s, продължаваме с {len(all_items)} items")

    # Дедупликация
    seen = set()
    unique_items = []
    for item in all_items:
        h = hashlib.md5(item["title"].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique_items.append(item)

    print(f"    Общо: {len(unique_items)} уникални sources")

    analysis = _analyze_for_axis(axis, unique_items, domain)

    result = {
        "axis":          axis,
        "domain":        domain,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "sources_count": len(unique_items),
        "rss_count":     sum(1 for i in unique_items if i.get("source_type") == "rss"),
        "ddg_count":     sum(1 for i in unique_items if i.get("source_type") == "ddg"),
        "youtube_count": sum(1 for i in unique_items if i.get("source_type") == "youtube"),
        "youtube_items": [i for i in unique_items if i.get("source_type") == "youtube"],
        "analysis":      analysis,
        "raw_items":     unique_items[:10],
    }

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"    → записан: {output_path.relative_to(BASE_DIR)}")
    return result


# -- Master report ------------------------------------------------------------

def generate_master_report(results: list) -> pathlib.Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    critical_axes   = []
    deteriorating   = []
    problems_found  = []
    cross_domain    = []

    for r in results:
        a = r.get("analysis", {})
        severity = a.get("severity", a.get("risk_level", ""))
        if severity in ("HIGH", "CRITICAL"):
            critical_axes.append(r["axis"])
        if a.get("trend") == "DETERIORATING":
            deteriorating.append(r["axis"])
        if a.get("problem") and a.get("problem") != "Няма достатъчно данни за анализ":
            problems_found.append({
                "axis":    r["axis"],
                "problem": a["problem"],
                "severity": severity,
                "actions": a.get("proposed_actions", []),
            })
        if a.get("generalization"):
            cross_domain.append({
                "from_axis": r["axis"],
                "insight":   a["generalization"],
            })

    total_yt      = sum(r.get("youtube_count", 0) for r in results)
    total_sources = sum(r.get("sources_count", 0) for r in results)

    master = {
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "date":               today,
        "axes_covered":       len(results),
        "total_sources":      total_sources,
        "youtube_videos_total": total_yt,
        "critical_axes":      critical_axes,
        "deteriorating_axes": deteriorating,
        "problems_found":     problems_found,
        "cross_domain_insights": cross_domain,
        "civilization_goal_alignment": {
            "critical_count":     len(critical_axes),
            "problems_with_actions": len([p for p in problems_found if p.get("actions")]),
            "status": "ALERT" if len(critical_axes) > 3 else "MONITORING",
        },
        "axes":               {r["axis"]: r.get("analysis", {}) for r in results},
        "ready_for_self_observer": True,
    }

    dated_path = BASE_DIR / "memory" / "web_intelligence" / today / "master_web_intel.json"
    dated_path.parent.mkdir(parents=True, exist_ok=True)
    dated_path.write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")

    latest = BASE_DIR / "memory" / "web_intelligence" / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    shutil.copy2(dated_path, latest)

    try:
        verify = json.loads(latest.read_text(encoding="utf-8"))
        assert verify.get("ready_for_self_observer") is True
        print(f"[WEB_INTEL] latest.json верифициран ({latest.stat().st_size} bytes)")
    except Exception as e:
        print(f"[WEB_INTEL] WARN: latest.json верификация неуспешна: {e}")

    print(f"\n[WEB_INTEL] Master report: {dated_path.relative_to(BASE_DIR)}")
    print(f"[WEB_INTEL] Критични оси:  {critical_axes}")
    print(f"[WEB_INTEL] Проблеми с actions: {len([p for p in problems_found if p.get('actions')])}/{len(problems_found)}")
    print(f"[WEB_INTEL] YouTube видеа:  {total_yt}")
    return latest


# -- Main run (ПАРАЛЕЛЕН) -----------------------------------------------------

def run(axes_filter: Optional[list] = None, force: bool = False, resume: bool = True) -> pathlib.Path:
    print("=" * 60)
    print("[WEB_INTEL] CORTEX++ Web Intelligence Agent")
    print(f"[WEB_INTEL] started at {datetime.now(timezone.utc).isoformat()}")
    print(f"[WEB_INTEL] Оси: {len(AXES)} | DDG: {'✓' if HAS_DDG else '✗'} | YouTube: {'✓' if HAS_YOUTUBE else '✗'}")
    print(f"[WEB_INTEL] Timeout за ос: {AXIS_TIMEOUT_SEC}s | Паралелни: {MAX_WORKERS}")
    print("=" * 60)
    _warmup_ollama()

    target_axes = axes_filter or list(AXES.keys())

    # -- Checkpoint: продължи от където е спряло ---
    checkpoint = _checkpoint_load() if (resume and not force) else {}
    already_done_in_checkpoint = set(checkpoint.get("completed", []))
    completed_axes = list(already_done_in_checkpoint)  # ще растем тук

    # Раздели на: пресни (само зареди) и за fetch (паралелно)
    to_skip  = []
    to_fetch = []
    for axis in target_axes:
        if axis not in AXES:
            print(f"  [WARN] Непозната ос: {axis}")
            continue
        # Ако е в checkpoint като завършена — директно skip без проверка на файл
        if axis in already_done_in_checkpoint:
            to_skip.append(axis)
            continue
        domain = AXES[axis]["domain"]
        output_path = _get_output_path(axis, domain)
        if not force and _already_fresh(output_path):
            to_skip.append(axis)
        else:
            to_fetch.append(axis)

    # Покажи пропуснатите
    for axis in to_skip:
        reason = "checkpoint" if axis in already_done_in_checkpoint else f"пресен (={MAX_AGE_HOURS}h)"
        print(f"  [SKIP] {axis} — {reason}")

    results = []

    # Зареди пресните от диска
    for axis in to_skip:
        domain = AXES[axis]["domain"]
        output_path = _get_output_path(axis, domain)
        try:
            results.append(json.loads(output_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    # Паралелна обработка на останалите
    if to_fetch:
        print(f"\n[WEB_INTEL] Паралелна обработка на {len(to_fetch)} оси (workers={MAX_WORKERS})...")
        # Checkpoint при старт на нов цикъл
        _checkpoint_save(completed_axes, done=False)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(run_axis, axis, AXES[axis], force): axis
                for axis in to_fetch
            }
            for future in as_completed(futures):
                axis = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    # Запиши checkpoint след всяка успешна ос
                    completed_axes.append(axis)
                    _checkpoint_save(completed_axes, done=False)
                    print(f"  [CHECKPOINT] {axis} ✓ ({len(completed_axes)}/{len(target_axes)})")
                except Exception as e:
                    print(f"  [ERROR] {axis}: {e}")

    master_path = generate_master_report(results)
    # Маркирай цикъла като завършен
    _checkpoint_save(completed_axes, done=True)
    print("[WEB_INTEL] Checkpoint: цикълът завършен ✓")

    try:
        from memory.continuous_learner import learn_from_cycle
        learn_from_cycle({
            "source":          "web_intelligence_agent",
            "axes_covered":    len(results),
            "youtube_enabled": HAS_YOUTUBE,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        })
        print("[WEB_INTEL] continuous_learner ✓")
    except Exception as e:
        print(f"[WEB_INTEL] learner: {e}")

    print(f"\n[WEB_INTEL] done at {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    return master_path


# -- CLI ----------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CORTEX++ Web Intelligence Agent")
    parser.add_argument("--axes",       nargs="*", help="Конкретни оси (по подразбиране: всички)")
    parser.add_argument("--force",      action="store_true", help="Игнорирай cache")
    parser.add_argument("--resume",     action="store_true", default=True, help="Продължи от checkpoint (по подразбиране: вкл.)")
    parser.add_argument("--no-resume",  action="store_true", help="Игнорирай checkpoint, започни отново")
    parser.add_argument("--daemon",     action="store_true", help="24/7 режим")
    parser.add_argument("--interval",   type=int, default=21600, help="Интервал в секунди (default: 21600 = 6ч)")
    parser.add_argument("--no-youtube", action="store_true", help="Изключи YouTube")
    parser.add_argument("--workers",    type=int, default=MAX_WORKERS, help=f"Паралелни оси (default: {MAX_WORKERS})")
    args = parser.parse_args()

    if args.no_youtube:
        HAS_YOUTUBE = False

    MAX_WORKERS = args.workers

    if args.daemon:
        print(f"[WEB_INTEL] Daemon режим — интервал {args.interval}s")
        while True:
            try:
                run(axes_filter=args.axes, force=args.force, resume=not args.no_resume)
            except Exception as e:
                print(f"[WEB_INTEL] Грешка в daemon: {e}")
            print(f"[WEB_INTEL] Следващ цикъл след {args.interval}s...")
            time.sleep(args.interval)
    else:
        run(axes_filter=args.axes, force=args.force, resume=not args.no_resume)