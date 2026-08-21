#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# internet_agent.py -- CORTEX++_QWEN Internet Intelligence Agent
# Събира данни от RSS, GDELT, arXiv, GitHub, Podcasts и YouTube (с Whisper).
from __future__ import annotations
import json, pathlib, subprocess, sys, time, re, os, tempfile, glob, signal, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

try:
    from dotenv import load_dotenv as _ldenv
    _ldenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../.env'))
except ImportError:
    pass

import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET

import sys as _sys
_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from core.groq_backend import call_groq as _groq
from core.llm_json import extract_json as _shared_extract_json

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]
NEWS_DIR = BASE_DIR / 'news'
NEWS_DIR.mkdir(exist_ok=True)

YOUTUBE_API_KEY      = os.environ.get("YOUTUBE_API_KEY", "")
_YT_QUOTA_EXHAUSTED  = False   # True след първи 429 — важи за целия цикъл
MAX_TRANSCRIPT_CHARS = 3000
TRANSCRIPT_LANGUAGES = ["en", "bg", "de", "fr", "es"]
TRANSCRIPT_TIMEOUT_SEC = 60
YT_DLP_TIMEOUT_SEC     = 30

# ── Sticky IP-block fallback (item 4a) ───────────────────────────────────────
# Щом YouTube блокира IP-то ни веднъж, то остава блокирано за целия цикъл.
# Досега всяко следващо видео пак пробваше youtube-transcript-api и yt-dlp,
# ядеше timeout, и чак тогава падаше към Playwright — по ~60s загубени на видео.
# Сега първият IP-block превключва ОСТАТЪКА ОТ ЦИКЪЛА директно на Playwright.
# Флагът е cycle-scoped: reset_cycle_state() в началото на run() го нулира,
# за да може следващият цикъл (нов IP / изтекъл rate limit) пак да пробва API.
# Същият модел като съществуващия _YT_QUOTA_EXHAUSTED.
_IP_BLOCKED_THIS_CYCLE = False
_STATE_LOCK = threading.Lock()

# ── Cross-cycle transcript cache (item 4c) ───────────────────────────────────
# Ключ = video ID. Проверява се ПРЕДИ какъвто и да е fetch опит, така че вече
# свалена транскрипция струва нула мрежови заявки — независимо от цикъл, ос
# или query. Кешираме САМО реални транскрипции: description-fallback, timeout
# и провал не се кешират (иначе завинаги затваряме възможността да ги вземем).
TRANSCRIPT_CACHE_DIR = BASE_DIR / "memory" / "transcript_cache"
_CACHEABLE_METHODS = {"youtube_transcript_api", "yt_dlp", "playwright_web", "whisper"}

# Playwright контексти на ос — таванът идва от BODY scan RAM директивата.
_MAX_PW_CONTEXTS = 3
_MIN_PW_CONTEXTS = 1

_SSL_CTX = None
try:
    import ssl
    _SSL_CTX = ssl.create_default_context()
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE
except Exception:
    pass

# ── RSS / GitHub / arXiv / GDELT конфигурация ────────────────────────────────

RSS_FEEDS = {
    'CLIMATE_GLOBAL_RISK_REVIEW':     'https://feeds.bbci.co.uk/news/science_and_environment/rss.xml',
    'ENERGY_REVIEW':                  'https://www.renewableenergyworld.com/feed/',
    'WATER_REVIEW':                   'https://www.theguardian.com/environment/water/rss',
    'FOOD_REVIEW':                    'https://www.sciencedaily.com/rss/plants_animals/food.xml',
    'ECOSYSTEMS_BIODIVERSITY_REVIEW': 'https://www.sciencedaily.com/rss/plants_animals/ecology.xml',
    'ECONOMY_WORK_REVIEW':            'https://feeds.bbci.co.uk/news/business/rss.xml',
    'INEQUALITY_POVERTY_REVIEW':      'https://feeds.bbci.co.uk/news/world/rss.xml',
    'TECHNOLOGY_AI_REVIEW':           'https://feeds.bbci.co.uk/news/technology/rss.xml',
    'GOVERNANCE_INSTITUTIONS_REVIEW': 'https://news.un.org/feed/subscribe/en/news/topic/human-rights/feed/rss.xml',
    'GOAL_PROGRESS_REVIEW':           'https://news.un.org/feed/subscribe/en/news/topic/sdgs/feed/rss.xml',
    'SPACE_INFRASTRUCTURE_REVIEW':    'https://www.nasa.gov/rss/dyn/breaking_news.rss',
    'LONG_TERM_FUTURE_REVIEW':        'https://feeds.bbci.co.uk/news/technology/rss.xml',
    'HUMAN_WELL_BEING_REVIEW':        'https://feeds.bbci.co.uk/news/health/rss.xml',
    'MATERIALS_WASTE_REVIEW':         'https://www.wastedive.com/feeds/news/',
    'SOCIAL_RELATIONS_REVIEW':        'https://feeds.bbci.co.uk/news/world/rss.xml',
    'COGNITION_LEARNING_REVIEW':      'https://www.sciencedaily.com/rss/mind_brain/educational_psychology.xml',
    'INFRASTRUCTURE_CITIES_REVIEW':   'https://feeds.bbci.co.uk/news/technology/rss.xml',
}

GITHUB_QUERIES = {
    'CLIMATE_GLOBAL_RISK_REVIEW':       'climate-model',
    'ENERGY_REVIEW':                    'renewable-energy',
    'WATER_REVIEW':                     'water-quality',
    'FOOD_REVIEW':                      'precision-agriculture',
    'ECOSYSTEMS_BIODIVERSITY_REVIEW':   'biodiversity',
    'MATERIALS_WASTE_REVIEW':           'circular-economy',
    'PLANETARY_POTENTIAL_REVIEW':       'earth-observation',
    'HUMAN_WELL_BEING_REVIEW':          'global-health',
    'SOCIAL_RELATIONS_REVIEW':          'social-network-analysis',
    'COGNITION_LEARNING_REVIEW':        'education-ai',
    'CULTURE_MEDIA_REVIEW':             'media-analysis',
    'GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL': 'human-rights',
    'ECONOMY_WORK_REVIEW':              'economic-modeling',
    'INEQUALITY_POVERTY_REVIEW':        'poverty-mapping',
    'INFRASTRUCTURE_CITIES_REVIEW':     'smart-city',
    'GOVERNANCE_INSTITUTIONS_REVIEW':   'open-government',
    'EDUCATION_CULTURE_REVIEW':         'open-education',
    'TECHNOLOGY_INFRA_REVIEW':          'distributed-systems',
    'TECHNOLOGY_AI_REVIEW':             'agi-safety',
    'LONG_TERM_FUTURE_REVIEW':          'ai-alignment',
    'SPACE_INFRASTRUCTURE_REVIEW':      'space-exploration',
    'COSMIC_RESOURCES_REVIEW':          'asteroid-mining',
    'DEEP_TIME_RISKS_REVIEW':           'existential-risk',
    'GOAL_PROGRESS_REVIEW':             'sustainable-development',
}

ARXIV_QUERIES = {
    'CLIMATE_GLOBAL_RISK_REVIEW':       'climate change risk prediction',
    'ENERGY_REVIEW':                    'renewable energy storage efficiency',
    'WATER_REVIEW':                     'water scarcity prediction',
    'FOOD_REVIEW':                      'food security machine learning',
    'ECOSYSTEMS_BIODIVERSITY_REVIEW':   'biodiversity loss ecosystem',
    'MATERIALS_WASTE_REVIEW':           'circular economy waste reduction',
    'PLANETARY_POTENTIAL_REVIEW':       'earth system resilience tipping points',
    'HUMAN_WELL_BEING_REVIEW':          'global health wellbeing index',
    'SOCIAL_RELATIONS_REVIEW':          'social cohesion trust networks',
    'COGNITION_LEARNING_REVIEW':        'education learning outcomes AI',
    'CULTURE_MEDIA_REVIEW':             'media influence culture AI',
    'GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL': 'human rights measurement index',
    'ECONOMY_WORK_REVIEW':              'economic inequality automation labor',
    'INEQUALITY_POVERTY_REVIEW':        'poverty measurement multidimensional',
    'INFRASTRUCTURE_CITIES_REVIEW':     'urban infrastructure resilience',
    'GOVERNANCE_INSTITUTIONS_REVIEW':   'democratic governance institutions',
    'EDUCATION_CULTURE_REVIEW':         'education access equity outcomes',
    'TECHNOLOGY_INFRA_REVIEW':          'digital infrastructure access global',
    'TECHNOLOGY_AI_REVIEW':             'artificial general intelligence alignment',
    'LONG_TERM_FUTURE_REVIEW':          'existential risk civilizational collapse',
    'SPACE_INFRASTRUCTURE_REVIEW':      'space colonization infrastructure',
    'COSMIC_RESOURCES_REVIEW':          'asteroid mining space resources',
    'DEEP_TIME_RISKS_REVIEW':           'long term existential risk',
    'GOAL_PROGRESS_REVIEW':             'sustainable development goals measurement',
}

ARXIV_CATEGORIES = {
    'CLIMATE_GLOBAL_RISK_REVIEW':       'physics.ao-ph',
    'ENERGY_REVIEW':                    'eess.SY',
    'WATER_REVIEW':                     'physics.ao-ph',
    'FOOD_REVIEW':                      'q-bio.PE',
    'ECOSYSTEMS_BIODIVERSITY_REVIEW':   'q-bio.PE',
    'MATERIALS_WASTE_REVIEW':           'cond-mat.mtrl-sci',
    'PLANETARY_POTENTIAL_REVIEW':       'physics.geo-ph',
    'HUMAN_WELL_BEING_REVIEW':          'q-bio.NC',
    'SOCIAL_RELATIONS_REVIEW':          'cs.SI',
    'COGNITION_LEARNING_REVIEW':        'cs.CY',
    'CULTURE_MEDIA_REVIEW':             'cs.SI',
    'GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL': 'cs.CY',
    'ECONOMY_WORK_REVIEW':              'econ.GN',
    'INEQUALITY_POVERTY_REVIEW':        'econ.GN',
    'INFRASTRUCTURE_CITIES_REVIEW':     'cs.CY',
    'GOVERNANCE_INSTITUTIONS_REVIEW':   'cs.CY',
    'EDUCATION_CULTURE_REVIEW':         'cs.CY',
    'TECHNOLOGY_INFRA_REVIEW':          'cs.NI',
    'TECHNOLOGY_AI_REVIEW':             'cs.AI',
    'LONG_TERM_FUTURE_REVIEW':          'cs.AI',
    'SPACE_INFRASTRUCTURE_REVIEW':      'astro-ph.IM',
    'COSMIC_RESOURCES_REVIEW':          'astro-ph.EP',
    'DEEP_TIME_RISKS_REVIEW':           'cs.AI',
    'GOAL_PROGRESS_REVIEW':             'econ.GN',
}

GDELT_QUERIES = {
    'CLIMATE_GLOBAL_RISK_REVIEW':       'climate change CO2 emissions',
    'ENERGY_REVIEW':                    'renewable energy solar wind',
    'WATER_REVIEW':                     'water scarcity drinking water',
    'FOOD_REVIEW':                      'food security hunger famine',
    'ECOSYSTEMS_BIODIVERSITY_REVIEW':   'biodiversity species extinction',
    'MATERIALS_WASTE_REVIEW':           'plastic waste pollution recycling',
    'PLANETARY_POTENTIAL_REVIEW':       'earth resources sustainability',
    'HUMAN_WELL_BEING_REVIEW':          'mental health wellbeing global',
    'SOCIAL_RELATIONS_REVIEW':          'social inequality conflict trust',
    'COGNITION_LEARNING_REVIEW':        'education learning children schools',
    'CULTURE_MEDIA_REVIEW':             'media disinformation culture',
    'GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL': 'human rights democracy freedom',
    'ECONOMY_WORK_REVIEW':              'economy unemployment poverty wages',
    'INEQUALITY_POVERTY_REVIEW':        'inequality poverty wealth gap',
    'INFRASTRUCTURE_CITIES_REVIEW':     'cities infrastructure urban development',
    'GOVERNANCE_INSTITUTIONS_REVIEW':   'government corruption institutions',
    'EDUCATION_CULTURE_REVIEW':         'education access schools literacy',
    'TECHNOLOGY_INFRA_REVIEW':          'technology internet digital access',
    'TECHNOLOGY_AI_REVIEW':             'artificial intelligence AI regulation',
    'LONG_TERM_FUTURE_REVIEW':          'existential risk future civilization',
    'SPACE_INFRASTRUCTURE_REVIEW':      'space exploration NASA SpaceX',
    'COSMIC_RESOURCES_REVIEW':          'asteroid mining space resources',
    'DEEP_TIME_RISKS_REVIEW':           'nuclear war pandemic existential risk',
    'GOAL_PROGRESS_REVIEW':             'sustainable development goals SDG',
}

# YouTube queries — пълен набор за всички 25 оси
YOUTUBE_QUERIES = {
    "CLIMATE_GLOBAL_RISK_REVIEW":       "climate change extreme weather 2025",
    "ENERGY_REVIEW":                    "renewable energy transition solar wind 2025",
    "WATER_REVIEW":                     "water crisis drought freshwater scarcity",
    "FOOD_REVIEW":                      "food security global hunger agriculture 2025",
    "MATERIALS_WASTE_REVIEW":           "plastic pollution circular economy recycling",
    "ECOSYSTEMS_BIODIVERSITY_REVIEW":   "biodiversity loss deforestation species extinction",
    "HUMAN_WELL_BEING_REVIEW":          "global health WHO poverty inequality 2025",
    "CULTURE_MEDIA_REVIEW":             "media freedom misinformation social media impact",
    "COGNITION_LEARNING_REVIEW":        "education future AI learning skills 2025",
    "SOCIAL_RELATIONS_REVIEW":          "social inequality loneliness epidemic community",
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": "human rights democracy civil liberties 2025",
    "ECONOMY_WORK_REVIEW":              "global economy recession inflation unemployment 2025",
    "INEQUALITY_POVERTY_REVIEW":        "income inequality wealth gap poverty 2025",
    "INFRASTRUCTURE_CITIES_REVIEW":     "smart cities urban planning infrastructure future",
    "GOVERNANCE_INSTITUTIONS_REVIEW":   "geopolitics war peace UN NATO 2025",
    "EDUCATION_CULTURE_REVIEW":         "global education UNESCO literacy 2025",
    "TECHNOLOGY_INFRA_REVIEW":          "digital divide 5G semiconductor tech infrastructure",
    "TECHNOLOGY_AI_REVIEW":             "artificial intelligence AGI machine learning safety 2025",
    "SPACE_INFRASTRUCTURE_REVIEW":      "space exploration SpaceX NASA satellite 2025",
    "COSMIC_RESOURCES_REVIEW":          "asteroid mining space economy resources",
    "LONG_TERM_FUTURE_REVIEW":          "existential risk humanity future civilization",
    "DEEP_TIME_RISKS_REVIEW":           "pandemic risk nuclear war asteroid impact supervolcano",
    "GOAL_PROGRESS_REVIEW":             "sustainable development goals SDG 2030 UN progress",
    "PLANETARY_POTENTIAL_REVIEW":       "planetary boundaries geoengineering tipping points",
}

PODCAST_FEEDS = {
    'CLIMATE_GLOBAL_RISK_REVIEW':       'https://futureoflife.org/feed/',
    'ENERGY_REVIEW':                    'https://feeds.feedburner.com/TEDTalks_audio',
    'WATER_REVIEW':                     'https://feeds.feedburner.com/radiolab',
    'FOOD_REVIEW':                      'https://feeds.npr.org/510289/podcast.xml',
    'ECOSYSTEMS_BIODIVERSITY_REVIEW':   'https://feeds.feedburner.com/radiolab',
    'MATERIALS_WASTE_REVIEW':           'https://feeds.feedburner.com/TEDTalks_audio',
    'PLANETARY_POTENTIAL_REVIEW':       'https://lexfridman.com/feed/podcast/',
    'HUMAN_WELL_BEING_REVIEW':          'https://feeds.megaphone.fm/hubermanlab',
    'SOCIAL_RELATIONS_REVIEW':          'https://feeds.feedburner.com/TEDTalks_audio',
    'COGNITION_LEARNING_REVIEW':        'https://feeds.megaphone.fm/hubermanlab',
    'CULTURE_MEDIA_REVIEW':             'https://feeds.feedburner.com/TEDTalks_audio',
    'GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL': 'https://feeds.transistor.fm/80000-hours-podcast',
    'ECONOMY_WORK_REVIEW':              'https://feeds.npr.org/510289/podcast.xml',
    'INEQUALITY_POVERTY_REVIEW':        'https://feeds.transistor.fm/80000-hours-podcast',
    'INFRASTRUCTURE_CITIES_REVIEW':     'https://feeds.feedburner.com/TEDTalks_audio',
    'GOVERNANCE_INSTITUTIONS_REVIEW':   'https://feeds.transistor.fm/80000-hours-podcast',
    'EDUCATION_CULTURE_REVIEW':         'https://feeds.feedburner.com/TEDTalks_audio',
    'TECHNOLOGY_INFRA_REVIEW':          'https://lexfridman.com/feed/podcast/',
    'TECHNOLOGY_AI_REVIEW':             'https://lexfridman.com/feed/podcast/',
    'LONG_TERM_FUTURE_REVIEW':          'https://futureoflife.org/feed/',
    'SPACE_INFRASTRUCTURE_REVIEW':      'https://lexfridman.com/feed/podcast/',
    'COSMIC_RESOURCES_REVIEW':          'https://feeds.feedburner.com/TEDTalks_audio',
    'DEEP_TIME_RISKS_REVIEW':           'https://futureoflife.org/feed/',
    'GOAL_PROGRESS_REVIEW':             'https://feeds.transistor.fm/80000-hours-podcast',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def _http_get(url, timeout=12):
    try:
        headers = {'User-Agent': 'CORTEX++_QWEN/1.0'}
        if 'api.github.com' in url:
            token = os.environ.get('GITHUB_TOKEN', '')
            if token:
                headers['Authorization'] = f'token {token}'
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None

def _wiki(query):
    try:
        encoded = urllib.parse.quote(query.split('2025')[0].strip())
        data = json.loads(_http_get(f'https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}') or b'{}')
        extract = data.get('extract', '')
        return '. '.join(extract.split('. ')[:3]) + '.' if extract else None
    except Exception:
        return None

def _rss(url, max_items=3):
    raw = _http_get(url)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
        items = []
        for item in root.iter('item'):
            title = item.findtext('title', '').strip()
            desc  = re.sub(r'<[^>]+>', '', item.findtext('description', ''))[:300]
            link  = item.findtext('link', '').strip()
            if title:
                items.append({'title': title, 'snippet': desc, 'url': link, 'source': 'RSS'})
            if len(items) >= max_items:
                break
        return items
    except Exception:
        return []

def _github(topic, max_repos=3):
    url = f'https://api.github.com/search/repositories?q=topic:{topic}&sort=stars&order=desc&per_page={max_repos}'
    raw = _http_get(url)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [{'title': r.get('full_name', ''), 'snippet': r.get('description', '')[:200],
                 'stars': r.get('stargazers_count', 0), 'url': r.get('html_url', ''),
                 'updated': r.get('updated_at', '')[:10], 'source': 'GitHub'}
                for r in data.get('items', [])[:max_repos]]
    except Exception:
        return []

def _arxiv(query, max_papers=2, axis=''):
    encoded = urllib.parse.quote(query)
    cat = ARXIV_CATEGORIES.get(axis, '')
    first_word = query.split()[0].lower()
    if cat:
        url = f'https://export.arxiv.org/api/query?search_query=cat:{cat}+AND+ti:{first_word}&max_results={max_papers}&sortBy=submittedDate&sortOrder=descending'
    else:
        url = f'https://export.arxiv.org/api/query?search_query=ti:{encoded}&max_results={max_papers}&sortBy=submittedDate&sortOrder=descending'
    raw = _http_get(url)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        papers = []
        for entry in root.findall('atom:entry', ns):
            title   = entry.findtext('atom:title', '', ns).strip().replace('\n', ' ')
            summary = entry.findtext('atom:summary', '', ns).strip()[:300]
            link    = entry.find("atom:link[@rel='alternate']", ns)
            url_    = link.get('href', '') if link is not None else ''
            papers.append({'title': title, 'snippet': summary, 'url': url_, 'source': 'arXiv'})
        return papers
    except Exception:
        return []

def _gdelt(query, max_items=3):
    encoded = urllib.parse.quote(query)
    url = f'https://api.gdeltproject.org/api/v2/doc/doc?query={encoded}&mode=artlist&maxrecords={max_items}&format=json'
    raw = _http_get(url)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [{'title': a.get('title', '')[:150], 'snippet': a.get('title', '')[:300],
                 'url': a.get('url', ''), 'source': a.get('domain', 'GDELT')}
                for a in (data.get('articles') or [])[:max_items]]
    except Exception:
        return []

def _podcast(axis, query=""):
    all_feeds = list(dict.fromkeys(PODCAST_FEEDS.values()))
    url = PODCAST_FEEDS.get(axis)
    if url and url not in all_feeds[:3]:
        all_feeds = [url] + all_feeds
    keywords = set(query.lower().split()[:5]) if query else set()
    best_text = ""
    best_score = -1
    for feed_url in all_feeds[:5]:
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=8)
            root = ET.fromstring(r.read())
            for item in root.findall(".//item")[:10]:
                t = item.find("title")
                title = (t.text or "") if t is not None else ""
                desc = item.find("description")
                body = re.sub(r"<[^>]+>", "", (desc.text or "") if desc is not None else "").strip()
                score = sum(1 for k in keywords if k in (title + " " + body).lower())
                if score > best_score and len(body) > 100:
                    best_score = score
                    best_text = "[" + title + "] " + body[:400]
        except Exception:
            continue
    return best_text

# ── YouTube: пълна верига API → yt-dlp → Whisper ─────────────────────────────

@contextmanager
def _time_limit(seconds: int, label: str = ""):
    """SIGALRM timeout — само на Linux/Mac, само в главния thread.

    signal.signal() вдига ValueError, ако бъде извикан извън main thread. Откакто
    транскрипциите се теглят паралелно (ThreadPoolExecutor), този contextmanager
    се вика и от worker threads — затова проверката за main thread е задължителна,
    иначе на Linux целият паралелен fetch щеше да гърми.
    """
    if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return
    def _handler(signum, frame):
        raise TimeoutError(f"Timeout {seconds}s{' ' + label if label else ''}")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# ── Cycle state: sticky IP-block + parallelism budget ────────────────────────

def reset_cycle_state() -> None:
    """Нулира cycle-scoped флаговете. Вика се в началото на run().

    Без това sticky IP-block флагът щеше да остане вдигнат завинаги в
    дълго-живеещ процес и никога повече нямаше да пробваме бързия API път.
    """
    global _IP_BLOCKED_THIS_CYCLE, _YT_QUOTA_EXHAUSTED
    with _STATE_LOCK:
        _IP_BLOCKED_THIS_CYCLE = False
        _YT_QUOTA_EXHAUSTED = False


def _is_ip_blocked() -> bool:
    with _STATE_LOCK:
        return _IP_BLOCKED_THIS_CYCLE


def _mark_ip_blocked(source: str) -> None:
    """Първият IP-block превключва остатъка от цикъла на Playwright."""
    global _IP_BLOCKED_THIS_CYCLE
    with _STATE_LOCK:
        already = _IP_BLOCKED_THIS_CYCLE
        _IP_BLOCKED_THIS_CYCLE = True
    if not already:
        print(f"    [YT] IP BLOCK ({source}) → останалите fetch-ове в този цикъл "
              f"минават директно през Playwright (API се прескача)")


_IP_BLOCK_MARKERS = ("requestblocked", "ipblocked", "blocking requests", "too many requests")


def _is_ip_block_error(err: Exception) -> bool:
    """Разпознава YouTube IP-block по текста на грешката."""
    text = str(err).lower()
    if any(m in text for m in _IP_BLOCK_MARKERS):
        return True
    # youtube-transcript-api вдига именовани класове за това
    return type(err).__name__ in ("RequestBlocked", "IpBlocked", "YouTubeRequestFailed")


def _playwright_workers() -> int:
    """Колко паралелни Playwright контекста на ос.

    Чете memory/adaptive_directives.json точно както fast_cycle_runner._load_directives:
    body_scanner сваля max_parallel_workers на 2 при RAM/CPU > 70% и на 1 при > 85%.
    Всеки Playwright контекст е цял Chromium — това е най-RAM-лакомото нещо в цикъла,
    така че уважаваме същия таван, вместо да въвеждаме собствен.
    """
    workers = 3
    p = BASE_DIR / "memory" / "adaptive_directives.json"
    if p.exists():
        try:
            workers = int(json.loads(p.read_text(encoding="utf-8")).get("max_parallel_workers", 3))
        except Exception:
            pass
    return max(_MIN_PW_CONTEXTS, min(_MAX_PW_CONTEXTS, workers))


# ── Cross-cycle transcript cache ─────────────────────────────────────────────

def _cache_path(video_id: str) -> pathlib.Path:
    return TRANSCRIPT_CACHE_DIR / f"{video_id}.json"


def _cache_get(video_id: str) -> Optional[dict]:
    """Кеширана транскрипция или None. Никаква мрежа."""
    p = _cache_path(video_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None  # повреден кеш файл → третираме го като miss
    if not data.get("transcript"):
        return None
    return data


def _cache_put(video_id: str, data: dict) -> None:
    """Кешира САМО реални транскрипции (не description-fallback / timeout)."""
    if data.get("transcript_method") not in _CACHEABLE_METHODS:
        return
    if not data.get("transcript"):
        return
    try:
        TRANSCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "video_id":          video_id,
            "transcript":        data["transcript"],
            "transcript_chars":  data.get("transcript_chars", len(data["transcript"])),
            "transcript_method": data["transcript_method"],
            "cached_at":         datetime.now(timezone.utc).isoformat(),
        }
        _cache_path(video_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"    [TRANSCRIPT-CACHE] запис провален за {video_id}: {e}")

def _yt_search_html(query: str, max_results: int = 10) -> list[dict]:
    """Fallback: извлича video_id от HTML на YouTube results страница."""
    encoded = urllib.parse.quote(query)
    raw = _http_get(f'https://www.youtube.com/results?search_query={encoded}')
    if not raw:
        return []
    try:
        text = raw.decode('utf-8', errors='ignore')
        video_ids = list(dict.fromkeys(re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', text)))
        return [{'video_id': vid, 'title': f'YouTube:{vid}',
                 'url': f'https://www.youtube.com/watch?v={vid}',
                 'description': '', 'channel': '', 'published': ''}
                for vid in video_ids[:max_results]]
    except Exception:
        return []

def _yt_search_playwright(query: str, max_results: int = 5) -> list[dict]:
    """YouTube search чрез Playwright Chromium — заобикаля IP block и API quota."""
    import random
    pause = random.uniform(2.0, 4.0)
    print(f"    [YT-PW] пауза {pause:.1f}s → '{query}'")
    time.sleep(pause)

    encoded = urllib.parse.quote(query)
    url = f"https://www.youtube.com/results?search_query={encoded}"

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as _PWTimeout
    except ImportError:
        print("    [YT-PW] playwright не е инсталиран")
        return []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
            page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except _PWTimeout:
                pass
            html = page.content()
            browser.close()

        video_ids = list(dict.fromkeys(re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)))
        results = [
            {"video_id": vid, "title": f"YouTube:{vid}",
             "url": f"https://www.youtube.com/watch?v={vid}",
             "description": "", "channel": "", "published": ""}
            for vid in video_ids[:max_results]
        ]
        print(f"    [YT-PW] '{query}' → {len(results)} видеа")
        return results
    except Exception as e:
        print(f"    [YT-PW] грешка: {e}")
        return []


def _yt_search_api(query: str, max_results: int = 3) -> list[dict]:
    """YouTube Data API v3 — само ако е зададен YOUTUBE_API_KEY."""
    if not YOUTUBE_API_KEY:
        return []
    try:
        params = urllib.parse.urlencode({
            "part": "snippet", "q": query, "type": "video",
            "maxResults": max_results, "relevanceLanguage": "en",
            "key": YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "CortexIntelAgent/1.0"})
        kwargs = {"timeout": 15}
        if _SSL_CTX:
            kwargs["context"] = _SSL_CTX
        resp = urllib.request.urlopen(req, **kwargs)
        data = json.loads(resp.read())
        results = []
        for item in data.get("items", []):
            vid  = item.get("id", {}).get("videoId", "")
            snip = item.get("snippet", {})
            if vid:
                results.append({
                    "video_id": vid, "title": snip.get("title", ""),
                    "description": snip.get("description", "")[:500],
                    "channel": snip.get("channelTitle", ""),
                    "published": snip.get("publishedAt", ""),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                })
        print(f"    [YT-API] '{query}' → {len(results)} видеа")
        return results
    except Exception as e:
        print(f"    [YT-API] грешка: {e}")
        return []

def _search_youtube(query: str, max_results: int = 5) -> list[dict]:
    """Waterfall: YouTube API -> Playwright (HTML scrape e IP-blocked).

    При вдигнат sticky IP-block флаг отиваме директно на Playwright.
    """
    if _is_ip_blocked():
        return _yt_search_playwright(query, max_results)
    if YOUTUBE_API_KEY and not _YT_QUOTA_EXHAUSTED:
        results = _yt_search_api(query, max_results)
        if results:
            return results
    return _yt_search_playwright(query, max_results)

def _get_transcript_api(video_id: str) -> Optional[str]:
    """Опит 1: youtube-transcript-api (официални субтитри).

    Прескача се напълно, ако IP-то вече е блокирано в този цикъл — тогава
    заявката е гарантирано губене на време.
    """
    if _is_ip_blocked():
        return None

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        for lang in TRANSCRIPT_LANGUAGES:
            try:
                tl = api.fetch(video_id, languages=[lang])
                text = " ".join([t.text for t in list(tl)])
                if text.strip():
                    return text[:MAX_TRANSCRIPT_CHARS]
            except Exception as inner:
                # IP-block вътре в per-language цикъла: няма смисъл да пробваме
                # останалите езици — блокът е за целия IP, не за езика.
                if _is_ip_block_error(inner):
                    _mark_ip_blocked("transcript-api")
                    return None
                continue
        # автоматични субтитри без зададен език
        tl = api.fetch(video_id)
        text = " ".join([t.text for t in list(tl)])
        if text.strip():
            return text[:MAX_TRANSCRIPT_CHARS]
    except ImportError:
        pass
    except Exception as e:
        if _is_ip_block_error(e):
            _mark_ip_blocked("transcript-api")
        else:
            print(f"    [TRANSCRIPT-API] {video_id}: {str(e).splitlines()[0]}")
    return None

def _parse_vtt(filepath: str) -> str:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        lines = []
        for line in content.split("\n"):
            if re.match(r"^\d{2}:\d{2}[\d:.]+ -->", line):
                continue
            if line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
                continue
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if clean and (not lines or clean != lines[-1]):
                lines.append(clean)
        return " ".join(lines)
    except Exception:
        return ""

def _get_transcript_ytdlp(video_id: str) -> Optional[str]:
    """Опит 2: yt-dlp VTT субтитри.

    Също се прескача при IP-block: yt-dlp удря YouTube от СЪЩОТО IP, така че
    блокът важи и за него. (Playwright минава през истински браузър и оцелява.)
    """
    if _is_ip_blocked():
        return None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_template = os.path.join(tmpdir, "%(id)s")
            cmd = [
                "yt-dlp", "--no-check-certificate",
                "--write-auto-sub", "--write-sub",
                "--skip-download", "--sub-lang", "en,bg",
                "--convert-subs", "vtt",
                "-o", out_template,
                f"https://www.youtube.com/watch?v={video_id}",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=YT_DLP_TIMEOUT_SEC)
            vtt_files = glob.glob(os.path.join(tmpdir, "*.vtt"))
            if not vtt_files:
                return None
            text = _parse_vtt(vtt_files[0])
            return text[:MAX_TRANSCRIPT_CHARS] if text else None
    except subprocess.TimeoutExpired:
        print(f"    [TRANSCRIPT-YTDLP] {video_id}: timeout {YT_DLP_TIMEOUT_SEC}s")
        return None
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"    [TRANSCRIPT-YTDLP] {video_id}: {e}")
        return None

def _get_transcript_whisper(video_id: str) -> Optional[str]:
    """Опит 3: Groq Whisper API — изтегля аудио с yt-dlp, праща към Groq endpoint."""
    import requests as _req
    # Load key from env or .env file
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("GROQ_API_KEY="):
                    groq_key = line.split("=", 1)[1].strip()
                    break
    if not groq_key:
        print(f"    [TRANSCRIPT] {video_id[:11]} ⚠️ groq-whisper: no API key")
        return None

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.mp3")
            dl = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "-x", "--audio-format", "mp3",
                 "-o", audio_path, "--no-playlist", "--quiet", url],
                capture_output=True, timeout=90,
            )
            if dl.returncode != 0 or not os.path.exists(audio_path):
                return None
            file_size = os.path.getsize(audio_path)
            if file_size > 24 * 1024 * 1024:
                print(f"    [TRANSCRIPT] {video_id[:11]} ⚠️ audio > 24 MB — skip")
                return None
            with open(audio_path, "rb") as f:
                resp = _req.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    files={"file": ("audio.mp3", f, "audio/mpeg")},
                    data={"model": "whisper-large-v3", "response_format": "json"},
                    timeout=120,
                )
            resp.raise_for_status()
            text = resp.json().get("text", "").strip()
            if text:
                print(f"    [TRANSCRIPT] {video_id[:11]} OK groq-whisper ({len(text)} chars)")
                return text[:MAX_TRANSCRIPT_CHARS]
    except Exception as e:
        print(f"    [TRANSCRIPT] {video_id[:11]} WARN groq-whisper failed: {e}")
    return None

def _transcript_result(video_id: str, title: str, transcript: Optional[str], method: str) -> dict:
    return {
        "video_id":          video_id,
        "title":             title,
        "url":               f"https://www.youtube.com/watch?v={video_id}",
        "transcript":        transcript or "",
        "transcript_chars":  len(transcript) if transcript else 0,
        "transcript_method": method,
        "has_transcript":    bool(transcript and method not in ["none", "timeout"]),
    }


def get_transcript(video_id: str, title: str = "", description: str = "") -> dict:
    """
    Пълна верига: cache → youtube-transcript-api → yt-dlp VTT → Playwright →
    Whisper → description fallback.

    Кешът се проверява ПРЕДИ всеки друг опит: hit = нула мрежови заявки.
    При вдигнат IP-block флаг API и yt-dlp стъпките се самопрескачат (виж
    _get_transcript_api / _get_transcript_ytdlp), тоест веригата започва
    директно от Playwright.
    """
    # ── Cache first: преди ВСЯКАКЪВ fetch опит ──────────────────────────────
    cached = _cache_get(video_id)
    if cached:
        print(f"    [TRANSCRIPT] {video_id[:11]} ⚡ cache hit "
              f"({cached['transcript_chars']} chars, {cached['transcript_method']})")
        return _transcript_result(
            video_id, title, cached["transcript"], cached["transcript_method"]
        )

    transcript = None
    method = "none"

    try:
        with _time_limit(TRANSCRIPT_TIMEOUT_SEC, f"transcript {video_id}"):
            transcript = _get_transcript_api(video_id)
            if transcript:
                method = "youtube_transcript_api"
                print(f"    [TRANSCRIPT] {video_id[:11]} ✅ api ({len(transcript)} chars)")

            if not transcript:
                transcript = _get_transcript_ytdlp(video_id)
                if transcript:
                    method = "yt_dlp"
                    print(f"    [TRANSCRIPT] {video_id[:11]} ✅ yt-dlp ({len(transcript)} chars)")

    except TimeoutError:
        print(f"    [TRANSCRIPT] {video_id[:11]} ⏱ timeout {TRANSCRIPT_TIMEOUT_SEC}s")
        transcript = None
        method = "timeout"

    # Опит 3: Playwright — youtube-transcript.ai (по-бърз от Whisper, без локален модел)
    if not transcript:
        try:
            from youtube_intel import _get_transcript_playwright as _pw
            transcript = _pw(video_id)
            if transcript:
                method = "playwright_web"
                print(f"    [TRANSCRIPT] {video_id[:11]} OK ({len(transcript)} chars, playwright)")
        except Exception as _e:
            print(f"    [TRANSCRIPT-PW] {video_id[:11]} error: {_e}")

    # Whisper — извън time_limit (има собствен timeout в subprocess)
    if not transcript:
        transcript = _get_transcript_whisper(video_id)
        if transcript:
            method = "whisper"

    # Fallback: description
    if not transcript and description:
        transcript = f"[DESCRIPTION FALLBACK] {description}"
        method = "description"
        print(f"    [TRANSCRIPT] {video_id[:11]} ⚠️ fallback към description")

    if not transcript:
        print(f"    [TRANSCRIPT] {video_id[:11]} ❌ няма транскрипция")

    result = _transcript_result(video_id, title, transcript, method)
    _cache_put(video_id, result)   # no-op за description/timeout/none
    return result

# ── Adaptive YouTube memory ───────────────────────────────────────────────────

_ADAPTIVE_MEMORY_FILE = BASE_DIR / "memory" / "youtube_adaptive_memory.json"

def _load_adaptive_memory() -> dict:
    try:
        if _ADAPTIVE_MEMORY_FILE.exists():
            return json.loads(_ADAPTIVE_MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_adaptive_memory(mem: dict):
    try:
        _ADAPTIVE_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ADAPTIVE_MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"    [ADAPTIVE] Грешка при запис: {e}")

def _score_results(items: list) -> float:
    if not items:
        return 0.0
    full = sum(1 for i in items if i.get("has_full_transcript"))
    avg_chars = sum(i.get("transcript_chars", 0) for i in items) / len(items)
    return round((full / len(items)) * 0.6 + min(avg_chars / 3000, 1.0) * 0.4, 3)

def _fetch_youtube_for_axis(axis: str) -> list:
    """
    Взима YouTube видеа за оста, извлича транскрипции с пълната верига.
    Запомня кой query е работил най-добре (adaptive memory).
    """
    base_query = YOUTUBE_QUERIES.get(axis, axis.replace("_", " ").lower())
    mem = _load_adaptive_memory()
    axis_mem = mem.get(axis, {"queries": [], "scores": [], "best_query": None})

    queries_to_try = []
    best_past = axis_mem.get("best_query")
    if best_past and best_past != base_query:
        queries_to_try.append(best_past)
    queries_to_try.append(base_query)

    best_items = []
    best_score = -1.0
    best_q = base_query

    for q in queries_to_try:
        print(f"    [YT] Query: '{q}'")
        videos = _search_youtube(q, max_results=5)
        targets = videos[:3]

        def _enrich(vid: dict) -> dict:
            td = get_transcript(vid["video_id"], vid.get("title", ""), vid.get("description", ""))
            content = td["transcript"] or vid.get("description", "")
            return {
                "title":               f"[YT] {vid.get('title', vid['video_id'])}",
                "summary":             content[:800],
                "link":                vid["url"],
                "source_type":         "youtube",
                "channel":             vid.get("channel", ""),
                "video_id":            vid["video_id"],
                "transcript_method":   td["transcript_method"],
                "transcript_chars":    td["transcript_chars"],
                "has_full_transcript": td["has_transcript"] and td["transcript_method"] not in ["description", "timeout"],
            }

        # Паралелен fetch, ограничен от BODY scan RAM директивата. Всеки
        # Playwright контекст е отделен Chromium — при RAM > 85% body_scanner
        # сваля max_parallel_workers на 1 и тук ставаме отново серийни.
        workers = min(_playwright_workers(), len(targets)) or 1
        if workers > 1 and len(targets) > 1:
            print(f"    [YT] {len(targets)} видеа, {workers} паралелни контекста "
                  f"(BODY директива)")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                enriched = [r for r in pool.map(_enrich, targets) if r]
        else:
            enriched = []
            for vid in targets:
                time.sleep(0.5)
                enriched.append(_enrich(vid))

        score = _score_results(enriched)
        print(f"    [YT] Score: {score:.2f} ({len(enriched)} видеа)")
        if score > best_score:
            best_score = score
            best_items = enriched
            best_q = q
        if score >= 0.6:
            break

    # Запази в паметта
    axis_mem["queries"] = (axis_mem.get("queries", []) + [best_q])[-20:]
    axis_mem["scores"]  = (axis_mem.get("scores", []) + [best_score])[-20:]
    if best_score > (axis_mem.get("best_score", 0.0) or 0.0):
        axis_mem["best_query"] = best_q
        axis_mem["best_score"] = best_score
    mem[axis] = axis_mem
    _save_adaptive_memory(mem)

    return best_items

# ── Основни функции ───────────────────────────────────────────────────────────

def _generate_smart_query(axis, snapshot_data):
    return GDELT_QUERIES.get(axis, axis.replace("_", " ").lower())

def _parse_llm_json(raw: str) -> dict:
    """Robust JSON parsing — делегира на споделения core/llm_json.

    Старият вариант правеше re.search(r'\\{.*\\}', DOTALL), което е лакомо:
    хваща от първата '{' до ПОСЛЕДНАТА '}' в целия текст, включително
    trailing проза. Освен това не хващаше отрязани отговори — те просто
    гърмяха като "LLM parsing грешка" и никой не ретрайваше.
    """
    return _shared_extract_json(raw, expect=dict, backend="internet_agent")

def _llm_synthesize(axis, sources):
    ctx = ''
    if sources.get('wiki'):
        ctx += f'[Wikipedia]\n{sources["wiki"]}\n\n'
    for k in ['rss', 'gdelt']:
        if sources.get(k):
            ctx += f'[{k.upper()} News]\n'
            for it in sources[k][:2]:
                ctx += f'- {it.get("title", "")}\n'
            ctx += '\n'
    if sources.get('arxiv'):
        ctx += '[arXiv]\n'
        for p in sources['arxiv'][:2]:
            ctx += f'- {p.get("title", "")}\n'
        ctx += '\n'
    if sources.get('github'):
        ctx += '[GitHub]\n'
        for r in sources['github'][:3]:
            ctx += f'- {r.get("title", "")} star={r.get("stars", 0)}: {r.get("snippet", "")[:80]}\n'
        ctx += '\n'
    if sources.get('youtube_transcripts'):
        ctx += '[YouTube Transcript]\n' + sources['youtube_transcripts'][0][:800] + '\n\n'
    if not ctx.strip():
        return {'summary': 'No data.', 'sentiment': 'NEUTRAL', 'urgency': 'LOW', 'key_developments': []}

    prompt = (
        f"CORTEX++ AGI analyzing axis: {axis}\n"
        "ВИЗИЯ: Устойчива цивилизация с достоен живот за всеки. Войната, бедността и изкуственият недостиг са провал на дизайна.\n\n"
        f"Sources:\n{ctx[:2500]}\n\n"
        "RULES:\n"
        "- summary: 2-3 sentences Bulgarian about THIS axis only\n"
        "- key_developments: ONLY real items from sources above, NO placeholders\n"
        "- If no real items found return empty list []\n"
        "- open_source_momentum: from GitHub only, or No data\n"
        "- scientific_frontier: from arXiv only, or No data\n"
        'Return ONLY valid JSON: {"summary":"...","key_developments":["real item"],'
        '"sentiment":"POSITIVE|NEUTRAL|NEGATIVE|CRITICAL","urgency":"LOW|MEDIUM|HIGH|CRITICAL",'
        '"open_source_momentum":"...","scientific_frontier":"...","relevance_to_goal":"..."}'
    )
    try:
        raw = _groq(prompt, max_tokens=400)
        if 'done thinking.' in raw:
            raw = raw.split('done thinking.')[-1].strip()
        if '</think>' in raw:
            raw = raw.split('</think>')[-1].strip()
        return _parse_llm_json(raw)
    except Exception as e:
        return {'summary': ctx[:200], 'sentiment': 'NEUTRAL', 'urgency': 'LOW', 'key_developments': [], 'error': str(e)}

def fetch_axis(axis, snapshot_data):
    print(f'\n[INTERNET] -- {axis} --')
    smart_query = _generate_smart_query(axis, snapshot_data)
    print(f'  Query: {smart_query}')

    sources = {}
    sources['wiki']  = _wiki(smart_query)
    rss_url = RSS_FEEDS.get(axis)
    if rss_url:
        sources['rss'] = _rss(rss_url)
        print(f'  RSS: {len(sources["rss"])} items')
    gdelt_q = GDELT_QUERIES.get(axis, smart_query)
    sources['gdelt'] = _gdelt(gdelt_q)
    print(f'  GDELT: {len(sources["gdelt"])} items')
    arxiv_q = ARXIV_QUERIES.get(axis) or ' '.join(smart_query.split()[:4])
    sources['arxiv'] = _arxiv(arxiv_q, axis=axis)
    print(f'  arXiv: {len(sources["arxiv"])} papers')
    github_t = GITHUB_QUERIES.get(axis) or smart_query.split()[0]
    sources['github'] = _github(github_t)
    print(f'  GitHub: {len(sources["github"])} repos')

    # YouTube с пълна верига (API → yt-dlp → Whisper)
    yt_items = _fetch_youtube_for_axis(axis)
    sources['youtube_transcripts'] = [
        item['summary'] for item in yt_items if item.get('transcript_chars', 0) > 100
    ]
    if yt_items:
        has_t = sum(1 for i in yt_items if i.get('has_full_transcript'))
        print(f'  YouTube: {len(yt_items)} видеа, {has_t} с транскрипция')
    else:
        print(f'  YouTube: НЯМА видеа')

    sources['podcast'] = _podcast(axis, smart_query)
    if sources['podcast']:
        print(f'  Podcast: {len(sources["podcast"])} chars')

    # LLM синтез за тази ос
    analysis = _llm_synthesize(axis, sources)

    result = {
        'axis': axis, 'fetched_at': _utc_now(), 'smart_query': smart_query,
        'sources_count': {k: len(v) if isinstance(v, list) else (1 if v else 0) for k, v in sources.items()},
        'rss':           sources.get('rss', []),
        'gdelt':         sources.get('gdelt', []),
        'github_repos':  sources.get('github', []),
        'arxiv_papers':  sources.get('arxiv', []),
        'podcast':       sources.get('podcast', ''),
        'wiki':          sources.get('wiki', ''),
        'youtube_items': yt_items,
        'summary':       analysis.get('summary', ''),
        'urgency':       analysis.get('urgency', 'LOW'),
        'sentiment':     analysis.get('sentiment', 'NEUTRAL'),
        'key_developments':   analysis.get('key_developments', []),
        'open_source_momentum': analysis.get('open_source_momentum', ''),
        'scientific_frontier':  analysis.get('scientific_frontier', ''),
        'relevance_to_goal':    analysis.get('relevance_to_goal', ''),
    }
    icon = {'LOW': '🟢', 'MEDIUM': '🟢', 'HIGH': '🟡', 'CRITICAL': '🔴'}.get(result['urgency'], '🟢')
    print(f'  {icon} {result["urgency"]} | {result["summary"][:80]}')
    return result

def _load_master():
    p = BASE_DIR / 'snapshots' / 'master' / 'master_snapshot_latest.json'
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}

def run(axes=None):
    # Нов цикъл → нулирай sticky флаговете (IP-block, YT quota). Иначе един
    # блок в 09:00 щеше да държи целия ден на Playwright.
    reset_cycle_state()

    today   = date.today().isoformat()
    out_dir = NEWS_DIR / today
    out_dir.mkdir(exist_ok=True)
    master    = _load_master()
    snapshots = master.get('snapshots', {})
    if axes is None:
        axes = list(set(list(RSS_FEEDS.keys()) + list(GITHUB_QUERIES.keys()) + list(ARXIV_QUERIES.keys())))

    all_results = {}
    critical = []
    high_urgency = []

    for axis in axes:
        snap_data = snapshots.get(axis, {})
        try:
            result = fetch_axis(axis, snap_data)
            all_results[axis] = result
            (out_dir / f'{axis.lower()}_news_latest.json').write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8'
            )
            if result['urgency'] == 'CRITICAL':
                critical.append(axis)
            elif result['urgency'] == 'HIGH':
                high_urgency.append(axis)
            time.sleep(1)
        except Exception as e:
            print(f'[INTERNET] ERROR {axis}: {e}')

    # Глобален синтез за всички оси
    try:
        ctx = ""
        for ax, res in all_results.items():
            news   = [i.get('title', '') for i in (res.get('rss', []) + res.get('gdelt', []))[:2]]
            arxiv  = [p.get('title', '') for p in res.get('arxiv_papers', [])[:1]]
            yt_sum = res.get('youtube_items', [{}])[0].get('summary', '')[:100] if res.get('youtube_items') else ''
            ctx += f"[{ax}] News: {news} | Science: {arxiv} | YT: {yt_sum}\n"
        prompt = (
            "Анализирай 25 оси на планетата. За всяка ос определи urgency (LOW/MEDIUM/HIGH/CRITICAL) "
            "и summary (1 изречение на български).\n\n"
            f"ДАННИ:\n{ctx[:6000]}\n\n"
            'Върни САМО JSON: {"axes": {"ИМЕ_ОС": {"urgency": "...", "summary": "...", "sentiment": "POSITIVE|NEUTRAL|NEGATIVE|CRITICAL"}}}'
        )
        response = _groq(prompt, max_tokens=2000)
        if 'done thinking.' in response:
            response = response.split('done thinking.')[-1].strip()
        if '</think>' in response:
            response = response.split('</think>')[-1].strip()
        analyses = _parse_llm_json(response).get("axes", {})
        for ax, analysis in analyses.items():
            if ax in all_results:
                all_results[ax]['summary']   = analysis.get('summary', all_results[ax]['summary'])
                all_results[ax]['urgency']   = analysis.get('urgency', all_results[ax]['urgency'])
                all_results[ax]['sentiment'] = analysis.get('sentiment', all_results[ax]['sentiment'])
                if analysis.get('urgency') == 'CRITICAL' and ax not in critical:
                    critical.append(ax)
                elif analysis.get('urgency') == 'HIGH' and ax not in high_urgency:
                    high_urgency.append(ax)
        print(f"[INTERNET] Глобален синтез: {len(analyses)} оси анализирани")
    except Exception as e:
        print(f"[INTERNET] Синтез грешка: {e}")

    report = {
        'date': today, 'timestamp': _utc_now(),
        'axes_fetched': len(all_results),
        'critical_axes': critical, 'high_urgency_axes': high_urgency,
        'results': all_results,
    }
    (NEWS_DIR / 'news_latest.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'\n[INTERNET] SUMMARY:')
    print(f'  🔴 CRITICAL:  {critical}')
    print(f'  🟡 HIGH:      {high_urgency}')
    print(f'  Total: {len(all_results)} axes')

if __name__ == '__main__':
    test_axes = ['TECHNOLOGY_AI_REVIEW', 'CLIMATE_GLOBAL_RISK_REVIEW', 'ENERGY_REVIEW',
                 'INEQUALITY_POVERTY_REVIEW', 'GOAL_PROGRESS_REVIEW']
    print('[INTERNET] TEST MODE - 5 axes')
    run(axes=test_axes)
