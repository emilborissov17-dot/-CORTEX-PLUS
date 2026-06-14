#!/usr/bin/env python3
"""
youtube_intel.py — YouTube Intelligence Module за CORTEX++ Web Intelligence Agent
Търси YouTube видеа по осите и извлича транскрипции.

FIX: _get_transcript_yt_dlp() вече има timeout=30 (вече го имаше, но липсваше
     и на subprocess.run — сега е явен и верифициран).
FIX: get_transcript() има глобален timeout guard (60s на видео).

Интеграция: добавя се към run_axis() в web_intelligence_agent.py
    all_items.extend(fetch_youtube_for_axis(axis, config))

Изисквания:
    pip install youtube-transcript-api yt-dlp feedparser --break-system-packages
    (опционално) YOUTUBE_API_KEY env variable за по-добро търсене
"""

import os
import re
import json
import time
import hashlib
import pathlib
import urllib.request
import urllib.parse
import ssl
import subprocess
import tempfile
import glob
import signal
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

# Зареди .env от директорията на файла
try:
    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# ── Конфигурация ─────────────────────────────────────────────────────────────

YOUTUBE_API_KEY     = os.environ.get("YOUTUBE_API_KEY", "")
MAX_VIDEOS_PER_AXIS = 1
MAX_TRANSCRIPT_CHARS = 3000
TRANSCRIPT_LANGUAGES = ["en", "bg", "de", "fr", "es", "auto"]

# Timeout за цялото извличане на транскрипция на 1 видео
TRANSCRIPT_TIMEOUT_SEC = 60
# Timeout за yt-dlp процеса
YT_DLP_TIMEOUT_SEC     = 30

# Глобален флаг: YouTube е блокирал IP-а → спираме transcript заявки
_YT_IP_BLOCKED = False

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE


# ── Timeout helper ────────────────────────────────────────────────────────────

@contextmanager
def _time_limit(seconds: int, label: str = ""):
    """SIGALRM timeout — само на Linux/Mac."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise TimeoutError(f"Timeout {seconds}s{' на ' + label if label else ''}")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# ── YouTube Search ────────────────────────────────────────────────────────────

def _search_youtube_api(query: str, max_results: int = 3) -> list[dict]:
    if not YOUTUBE_API_KEY:
        return []
    try:
        params = urllib.parse.urlencode({
            "part":             "snippet",
            "q":                query,
            "type":             "video",
            "maxResults":       max_results,
            "relevanceLanguage": "en",
            "videoCaption":     "closedCaption",
            "key":              YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "CortexIntelAgent/1.0"})
        resp = urllib.request.urlopen(req, context=_SSL_CTX, timeout=15)
        data = json.loads(resp.read())
        results = []
        for item in data.get("items", []):
            vid  = item.get("id", {}).get("videoId", "")
            snip = item.get("snippet", {})
            if vid:
                results.append({
                    "video_id":    vid,
                    "title":       snip.get("title", ""),
                    "description": snip.get("description", "")[:500],
                    "channel":     snip.get("channelTitle", ""),
                    "published":   snip.get("publishedAt", ""),
                    "url":         f"https://www.youtube.com/watch?v={vid}",
                    "source":      "youtube_api",
                })
        print(f"    [YT-API] '{query}' → {len(results)} видеа")
        return results
    except Exception as e:
        print(f"    [YT-API] грешка: {e}")
        return []


def _search_youtube_rss_channel(channel_ids: list[str], max_items: int = 3) -> list[dict]:
    results = []
    import feedparser
    for channel_id in channel_ids:
        try:
            url  = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_items]:
                vid_id = entry.get("yt_videoid", "")
                if not vid_id:
                    link   = entry.get("link", "")
                    m      = re.search(r"v=([A-Za-z0-9_-]{11})", link)
                    vid_id = m.group(1) if m else ""
                if vid_id:
                    results.append({
                        "video_id":    vid_id,
                        "title":       entry.get("title", ""),
                        "description": entry.get("summary", "")[:500],
                        "channel":     entry.get("author", channel_id),
                        "published":   entry.get("published", ""),
                        "url":         f"https://www.youtube.com/watch?v={vid_id}",
                        "source":      "youtube_rss",
                    })
        except Exception as e:
            print(f"    [YT-RSS] channel {channel_id}: {e}")
    return results


def _search_youtube_ddg(query: str, max_results: int = 3) -> list[dict]:
    results = []
    try:
        from ddgs import DDGS
        ddgs_cls = DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
            ddgs_cls = DDGS
        except ImportError:
            return []

    try:
        with ddgs_cls() as ddgs:
            yt_query = f"youtube.com/watch {query}"
            search_results = list(ddgs.text(yt_query, max_results=max_results * 2))
            for r in search_results:
                link = r.get("href", "")
                m    = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})", link)
                if m:
                    vid_id = m.group(1)
                    results.append({
                        "video_id":    vid_id,
                        "title":       r.get("title", ""),
                        "description": r.get("body", "")[:500],
                        "channel":     "",
                        "published":   "",
                        "url":         f"https://www.youtube.com/watch?v={vid_id}",
                        "source":      "ddg_search",
                    })
                    if len(results) >= max_results:
                        break
        print(f"    [YT-DDG] '{query}' → {len(results)} видеа")
    except Exception as e:
        print(f"    [YT-DDG] грешка: {e}")
    return results


def search_youtube(query: str, max_results: int = MAX_VIDEOS_PER_AXIS,
                   channel_ids: list[str] = None) -> list[dict]:
    """Waterfall: API → RSS канали → DDG"""
    if YOUTUBE_API_KEY:
        results = _search_youtube_api(query, max_results)
        if results:
            return results

    if channel_ids:
        results = _search_youtube_rss_channel(channel_ids, max_results)
        if results:
            return results

    return _search_youtube_ddg(query, max_results)


# ── Transcript извличане ──────────────────────────────────────────────────────

def _get_transcript_api(video_id: str) -> Optional[str]:
    global _YT_IP_BLOCKED
    if _YT_IP_BLOCKED:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()

        for lang in TRANSCRIPT_LANGUAGES[:-1]:
            try:
                transcript_list = api.fetch(video_id, languages=[lang])
                text = " ".join([t.text if hasattr(t, "text") else t.get("text", "") if isinstance(t, dict) else str(t) for t in list(transcript_list)])
                if text.strip():
                    return text[:MAX_TRANSCRIPT_CHARS]
            except Exception:
                continue

        try:
            transcript_list = api.fetch(video_id)
            text = " ".join([t.text if hasattr(t, "text") else t.get("text", "") if isinstance(t, dict) else str(t) for t in list(transcript_list)])
            if text.strip():
                return text[:MAX_TRANSCRIPT_CHARS]
        except Exception:
            pass

    except ImportError:
        pass
    except Exception as e:
        err = str(e)
        if "blocking" in err.lower() or "IP" in err or "RequestBlocked" in err or "IPBlocked" in err:
            _YT_IP_BLOCKED = True
            print(f"    [TRANSCRIPT-API] ⛔ YouTube IP блок засечен — спираме transcript заявки за този цикъл")
        else:
            print(f"    [TRANSCRIPT-API] {video_id}: {e}")

    return None


def _get_transcript_yt_dlp(video_id: str) -> Optional[str]:
    """yt-dlp — сваля VTT субтитри. FIX: явен timeout=YT_DLP_TIMEOUT_SEC."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_template = os.path.join(tmpdir, "%(id)s")
            cmd = [
                "yt-dlp",
                "--no-check-certificate",
                "--write-auto-sub",
                "--write-sub",
                "--skip-download",
                "--sub-lang", "en,bg",
                "--convert-subs", "vtt",
                "-o", out_template,
                f"https://www.youtube.com/watch?v={video_id}",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=YT_DLP_TIMEOUT_SEC,   # FIX: явен timeout
            )

            vtt_files = glob.glob(os.path.join(tmpdir, "*.vtt"))
            if not vtt_files:
                return None

            text = _parse_vtt(vtt_files[0])
            return text[:MAX_TRANSCRIPT_CHARS] if text else None

    except subprocess.TimeoutExpired:
        print(f"    [TRANSCRIPT-YT-DLP] {video_id}: timeout {YT_DLP_TIMEOUT_SEC}s")
        return None
    except FileNotFoundError:
        # yt-dlp не е инсталиран
        return None
    except Exception as e:
        print(f"    [TRANSCRIPT-YT-DLP] {video_id}: {e}")
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


def get_transcript(video_id: str, title: str = "", description: str = "") -> dict:
    """
    Извлича транскрипция. FIX: глобален TRANSCRIPT_TIMEOUT_SEC guard.
    Ако YouTube е блокирал IP → пропускаме API и директно към yt-dlp.
    """
    global _YT_IP_BLOCKED
    transcript = None
    method     = "none"

    try:
        with _time_limit(TRANSCRIPT_TIMEOUT_SEC, f"transcript {video_id}"):
            # Опит 1: youtube-transcript-api (пропускаме ако IP е блокиран)
            if not _YT_IP_BLOCKED:
                transcript = _get_transcript_api(video_id)
                if transcript:
                    method = "youtube_transcript_api"
                    print(f"    [TRANSCRIPT] {video_id[:11]} ✅ ({len(transcript)} chars, api)")
            else:
                print(f"    [TRANSCRIPT] {video_id[:11]} ⏭ API skip (IP блок активен)")

            # Опит 2: yt-dlp
            if not transcript:
                transcript = _get_transcript_yt_dlp(video_id)
                if transcript:
                    method = "yt_dlp"
                    print(f"    [TRANSCRIPT] {video_id[:11]} ✅ ({len(transcript)} chars, yt-dlp)")

    except TimeoutError:
        print(f"    [TRANSCRIPT] {video_id[:11]} ⏱ timeout {TRANSCRIPT_TIMEOUT_SEC}s")
        transcript = None
        method     = "timeout"

    # Опит 3: Whisper
    if not transcript:
        try:
            import tempfile, subprocess, whisper, os
            url = f"https://www.youtube.com/watch?v={video_id}"
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path = f"{tmpdir}/audio.mp3"
                dl = subprocess.run(["yt-dlp", "-x", "--audio-format", "mp3", "-o", audio_path, url], capture_output=True, timeout=60)
                if dl.returncode == 0 and os.path.exists(audio_path):
                    model = whisper.load_model("tiny")
                    result = model.transcribe(audio_path, fp16=False)
                    del model
                    import gc; gc.collect()
                    transcript = result.get("text", "").strip() if isinstance(result, dict) else getattr(result, "text", "").strip()
                    if transcript:
                        method = "whisper"
                        print(f"    [TRANSCRIPT] {video_id[:11]} 2705 whisper ({len(transcript)} chars)")
        except Exception as e:
            print(f"    [TRANSCRIPT] {video_id[:11]} 26a0Fe0f whisper failed: {e}")

    # Fallback: description
    if not transcript and description:
        transcript = f"[DESCRIPTION FALLBACK] {description}"
        method     = "description"
        print(f"    [TRANSCRIPT] {video_id[:11]} ⚠️ fallback към description")

    if not transcript:
        print(f"    [TRANSCRIPT] {video_id[:11]} ❌ няма транскрипция")

    return {
        "video_id":          video_id,
        "title":             title,
        "url":               f"https://www.youtube.com/watch?v={video_id}",
        "transcript":        transcript or "",
        "transcript_chars":  len(transcript) if transcript else 0,
        "transcript_method": method,
        "has_transcript":    bool(transcript and method not in ["none", "timeout"]),
    }


# ── Главна функция за ос ─────────────────────────────────────────────────────

AXIS_YOUTUBE_CHANNELS = {
    "CLIMATE_GLOBAL_RISK_REVIEW": [
        "UCSGs4W0NsKs9EBcO1wMTOQw",  # Climate Town
        "UCJXGnj8nJ3GzJDVu-0NRHIA",  # NASA Climate
    ],
    "TECHNOLOGY_AI_REVIEW": [
        "UCbmNph6atAoGfqLoCL_duAg",  # Two Minute Papers
        "UCLB7AzTwc6VFZrBsO2ucBMg",  # Lex Fridman
    ],
    "SPACE_INFRASTRUCTURE_REVIEW": [
        "UCVTomc35agH1SMWpDcl0dTg",  # Scott Manley
        "UCLA_DiR1FfKNvjuUpBHmylQ",  # NASA
    ],
    "ENERGY_REVIEW": [
        "UCqd7is2M8vH3cKrPHOOBOuQ",  # Real Engineering
        "UCSGs4W0NsKs9EBcO1wMTOQw",  # Climate Town
    ],
    "HUMAN_WELL_BEING_REVIEW": [
        "UCznv7Vf9nBdJYvBagFdAHWw",  # Kurzgesagt
    ],
    "ECONOMY_WORK_REVIEW": [
        "UCWvnqjmJHSXdCGmogdRCWAQ",  # Economics Explained
    ],
}

AXIS_YOUTUBE_QUERIES = {
    "CLIMATE_GLOBAL_RISK_REVIEW":       "climate breakdown extreme weather systemic failure",
    "ENERGY_REVIEW":                    "energy transition renewable fossil fuel accountability",
    "WATER_REVIEW":                     "freshwater crisis water scarcity community impact",
    "FOOD_REVIEW":                      "food sovereignty hunger crisis systemic failure",
    "MATERIALS_WASTE_REVIEW":           "plastic pollution circular economy regenerative model",
    "ECOSYSTEMS_BIODIVERSITY_REVIEW":   "biodiversity collapse habitat destruction root causes",
    "HUMAN_WELL_BEING_REVIEW":          "global health inequality poverty dignity",
    "CULTURE_MEDIA_REVIEW":             "media manipulation misinformation freedom of press",
    "COGNITION_LEARNING_REVIEW":        "education inequality learning access alternatives",
    "SOCIAL_RELATIONS_REVIEW":          "social cohesion loneliness epidemic community solutions",
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": "human rights violations democracy accountability",
    "ECONOMY_WORK_REVIEW":              "economic inequality labor rights wealth concentration",
    "INEQUALITY_POVERTY_REVIEW":        "poverty systemic failure wealth gap root causes",
    "INFRASTRUCTURE_CITIES_REVIEW":     "urban inequality housing crisis infrastructure gap",
    "GOVERNANCE_INSTITUTIONS_REVIEW":   "geopolitical conflict institutional failure accountability",
    "EDUCATION_CULTURE_REVIEW":         "education access literacy gap policy failure",
    "TECHNOLOGY_INFRA_REVIEW":          "digital divide internet access inequality",
    "TECHNOLOGY_AI_REVIEW":             "AI safety AGI alignment algorithmic accountability",
    "SPACE_INFRASTRUCTURE_REVIEW":      "space exploration orbital infrastructure humanity",
    "COSMIC_RESOURCES_REVIEW":          "asteroid mining space resources off-world economy",
    "LONG_TERM_FUTURE_REVIEW":          "existential risk civilization resilience long-term",
    "DEEP_TIME_RISKS_REVIEW":           "pandemic preparedness nuclear risk catastrophic threat",
    "GENERAL_SELF_REVIEW":              "AI consciousness AGI progress machine awareness",
    "GOAL_PROGRESS_REVIEW":             "SDG failure UN accountability development gap",
    "PLANETARY_POTENTIAL_REVIEW":       "planetary boundaries tipping points geoengineering",
}



# ── Adaptive Query Engine ─────────────────────────────────────────────────────

# Persistent memory: axis → performance history
# Структура: { axis: { "queries": [...], "scores": [...], "failures": [...] } }
_ADAPTIVE_MEMORY_FILE = pathlib.Path("memory/youtube_adaptive_memory.json")

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
        _ADAPTIVE_MEMORY_FILE.write_text(
            json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"    [ADAPTIVE] Грешка при запис на memory: {e}")

def _score_results(items: list[dict]) -> float:
    """Оценява колко добри са резултатите: 0.0 (лошо) → 1.0 (отлично)."""
    if not items:
        return 0.0
    full_transcripts = sum(1 for i in items if i.get("has_full_transcript"))
    avg_chars = sum(i.get("transcript_chars", 0) for i in items) / len(items)
    score = (full_transcripts / len(items)) * 0.6 + min(avg_chars / 3000, 1.0) * 0.4
    return round(score, 3)

def _diagnose_failures(items: list[dict], query: str) -> list[str]:
    """Вижда слабостите и ги формулира като проблеми."""
    problems = []
    if not items:
        problems.append(f"ZERO_RESULTS: query '{query}' върна 0 видеа")
    else:
        no_transcript = [i for i in items if not i.get("has_full_transcript")]
        if len(no_transcript) == len(items):
            problems.append(f"NO_TRANSCRIPTS: никое видео няма транскрипция за '{query}'")
        elif len(no_transcript) > 0:
            problems.append(f"PARTIAL_TRANSCRIPTS: {len(no_transcript)}/{len(items)} без транскрипция")
        low_chars = [i for i in items if i.get("transcript_chars", 0) < 500]
        if low_chars:
            problems.append(f"LOW_CONTENT: {len(low_chars)} видеа с <500 chars съдържание")
    return problems

def _generate_adaptive_queries(axis: str, config: dict, failures: list[str],
                                past_queries: list[str]) -> list[str]:
    """
    Генерира нови query варианти БЕЗ фиксирана година.
    Използва ротационни формати, региони и аспекти за разнообразие.
    """
    import random

    keywords = config.get("keywords", [])
    domain   = config.get("domain", "")
    base     = AXIS_YOUTUBE_QUERIES.get(axis, " ".join(keywords[:3]))
    kw0      = keywords[0] if keywords else base.split()[0]
    kw1      = keywords[1] if len(keywords) > 1 else ""

    # Ротационни пулове — без фиксирана година
    FORMATS  = ["documentary", "lecture", "expert analysis", "investigation", "debate", "field report"]
    REGIONS  = ["Sub-Saharan Africa", "South Asia", "Latin America", "Middle East", "Southeast Asia", "Eastern Europe"]
    ASPECTS  = ["root causes", "systemic failure", "community impact", "alternatives", "policy gap", "accountability"]
    RECENCY  = ["recent", "latest", "emerging", "new research on", "current state of"]

    fmt    = random.choice(FORMATS)
    region = random.choice(REGIONS)
    aspect = random.choice(ASPECTS)
    rec    = random.choice(RECENCY)

    candidates = []

    # Базови варианти — без година, с разнообразни суфикси
    if keywords:
        candidates.append(f"{kw0} {kw1} {fmt}".strip())
        candidates.append(f"{rec} {kw0} {aspect}")
        candidates.append(f"{kw0} {region} {aspect}")

    # При ZERO_RESULTS — по-общи но без година
    if any("ZERO_RESULTS" in f for f in failures):
        candidates.append(f"{kw0} {fmt}")
        candidates.append(f"{kw0} crisis explained")
        candidates.append(f"{axis.replace('_', ' ').lower()} {fmt}")

    # При NO_TRANSCRIPTS — търсим лекции и дискусии
    if any("NO_TRANSCRIPTS" in f for f in failures):
        candidates.append(f"{kw0} lecture university talk")
        candidates.append(f"{kw0} expert panel discussion")
        candidates.append(f"{kw0} ted talk explained")

    # При LOW_CONTENT — търсим по-дълги формати
    if any("LOW_CONTENT" in f for f in failures):
        candidates.append(f"{kw0} in depth {aspect}")
        candidates.append(f"{kw0} comprehensive {fmt}")
        candidates.append(f"{kw0} full {fmt} {region}")

    # Domain контекст
    if domain:
        candidates.append(f"{domain} {kw0} {aspect}")

    # Филтрираме вече пробваните
    novel = [q for q in candidates if q not in past_queries and q.strip()]
    return novel[:3]


def _run_with_adaptive_queries(axis: str, config: dict, max_videos: int,
                                base_query: str, channel_ids: list[str]) -> list[dict]:
    """
    Изпълнява search с адаптивна логика:
    1. Пробва base query
    2. Ако резултатите са слаби → диагностицира → генерира нови queries → пробва отново
    3. Записва в паметта за следващия цикъл
    """
    mem = _load_adaptive_memory()
    axis_mem = mem.get(axis, {"queries": [], "scores": [], "failures": [], "best_query": None})

    # Ако имаме добре работил query от миналото → пробваме него първо
    best_past = axis_mem.get("best_query")
    queries_to_try = []
    if best_past and best_past != base_query:
        queries_to_try.append(best_past)
    queries_to_try.append(base_query)

    best_items  = []
    best_score  = -1.0
    best_q_used = base_query

    for q in queries_to_try:
        print(f"    [ADAPTIVE] Пробвам query: '{q}'")
        items = search_youtube(q, max_results=max_videos, channel_ids=channel_ids)
        # Извличаме транскрипции за да оценим
        enriched = []
        for video in items:
            time.sleep(0.5)
            td = get_transcript(video["video_id"], video["title"], video["description"])
            content = td["transcript"] or video["description"]
            enriched.append({
                "title":               f"[YT] {video['title']}",
                "summary":             content[:800],
                "link":                video["url"],
                "published":           video.get("published", ""),
                "source_type":         "youtube",
                "channel":             video.get("channel", ""),
                "video_id":            video["video_id"],
                "transcript_method":   td["transcript_method"],
                "transcript_chars":    td["transcript_chars"],
                "has_full_transcript": td["has_transcript"] and td["transcript_method"] not in ["description", "timeout"],
            })
        score = _score_results(enriched)
        print(f"    [ADAPTIVE] Score: {score:.2f} ({len(enriched)} видеа)")

        if score > best_score:
            best_score  = score
            best_items  = enriched
            best_q_used = q

        if score >= 0.7:  # Достатъчно добре → спираме
            break

    # Диагностика ако резултатите са слаби
    failures = []
    if best_score < 0.4:
        failures = _diagnose_failures(best_items, best_q_used)
        if failures:
            print(f"    [ADAPTIVE] ⚠️ Проблеми: {failures}")
            past_queries = axis_mem.get("queries", [])
            new_queries  = _generate_adaptive_queries(axis, config, failures, past_queries + queries_to_try)
            if new_queries:
                print(f"    [ADAPTIVE] 🔄 Нови adaptive queries: {new_queries}")
                for aq in new_queries:
                    items2 = search_youtube(aq, max_results=max_videos, channel_ids=channel_ids)
                    enriched2 = []
                    for video in items2:
                        time.sleep(0.5)
                        td = get_transcript(video["video_id"], video["title"], video["description"])
                        content = td["transcript"] or video["description"]
                        enriched2.append({
                            "title":               f"[YT] {video['title']}",
                            "summary":             content[:800],
                            "link":                video["url"],
                            "published":           video.get("published", ""),
                            "source_type":         "youtube",
                            "channel":             video.get("channel", ""),
                            "video_id":            video["video_id"],
                            "transcript_method":   td["transcript_method"],
                            "transcript_chars":    td["transcript_chars"],
                            "has_full_transcript": td["has_transcript"] and td["transcript_method"] not in ["description", "timeout"],
                        })
                    score2 = _score_results(enriched2)
                    print(f"    [ADAPTIVE] '{aq}' → score {score2:.2f}")
                    if score2 > best_score:
                        best_score  = score2
                        best_items  = enriched2
                        best_q_used = aq
                    if best_score >= 0.5:
                        break

    # Обновяване на паметта
    axis_mem["queries"]  = (axis_mem.get("queries", []) + [best_q_used])[-20:]  # последните 20
    axis_mem["scores"]   = (axis_mem.get("scores",  []) + [best_score])[-20:]
    axis_mem["failures"] = (axis_mem.get("failures", []) + failures)[-10:]
    # Запомняме най-добрия query ако е бил успешен
    if best_score > (axis_mem.get("best_score", 0.0) or 0.0):
        axis_mem["best_query"] = best_q_used
        axis_mem["best_score"] = best_score
    mem[axis] = axis_mem
    _save_adaptive_memory(mem)

    return best_items


def fetch_youtube_for_axis(axis: str, config: dict,
                           max_videos: int = MAX_VIDEOS_PER_AXIS) -> list[dict]:
    global _YT_IP_BLOCKED
    if _YT_IP_BLOCKED:
        print(f"    [YT] ⛔ IP блок активен — само yt-dlp за {axis}")
    # CLAUDE proposals — умни query-та от анализа на аномалии
    claude_queries = config.get("claude_queries", [])

    # Базов query: CLAUDE proposal -> AXIS_YOUTUBE_QUERIES -> keywords
    if claude_queries:
        query = claude_queries[0]
        print(f"    [YT] Ос: {axis} | Query: '{query}' (CLAUDE proposal)")
    else:
        query = AXIS_YOUTUBE_QUERIES.get(axis)
        if not query:
            keywords = config.get("keywords", [])
            query    = " ".join(keywords[:3]) if keywords else axis.lower()
        print(f"    [YT] Ос: {axis} | Query: '{query}' (adaptive mode)")

    channel_ids = AXIS_YOUTUBE_CHANNELS.get(axis, [])

    # Ако имаме CLAUDE proposals — добавяме ги като допълнителни queries за adaptive engine
    if claude_queries and len(claude_queries) > 1:
        config = dict(config)
        config["_extra_queries"] = claude_queries[1:]

    items = _run_with_adaptive_queries(axis, config, max_videos, query, channel_ids)

    if not items:
        print(f"    [YT] Няма намерени видеа за {axis}")
        return []

    print(f"    [YT] {axis}: {len(items)} видеа, "
          f"{sum(1 for i in items if i['has_full_transcript'])} с транскрипция")
    return items


# ── Тест ─────────────────────────────────────────────────────────────────────

def _test_single_axis(axis: str = "TECHNOLOGY_AI_REVIEW"):
    print(f"\n{'='*60}\n[YT-INTEL TEST] Ос: {axis}\n{'='*60}")
    test_config = {"domain": "civilization", "keywords": ["artificial intelligence", "AGI"]}
    items = fetch_youtube_for_axis(axis, test_config, max_videos=2)
    print(f"\n[РЕЗУЛТАТ] {len(items)} видеа:")
    for i, item in enumerate(items, 1):
        print(f"\n  {i}. {item['title'][:70]}")
        print(f"     URL: {item['link']}")
        print(f"     Метод: {item['transcript_method']} | Chars: {item['transcript_chars']}")
        print(f"     Preview: {item['summary'][:200]}...")
    return items


def _test_all_axes_summary():
    print("\n[YT-INTEL] Query map за всички оси:\n")
    for ax, q in AXIS_YOUTUBE_QUERIES.items():
        has_ch = "📺" if ax in AXIS_YOUTUBE_CHANNELS else "  "
        print(f"  {has_ch} {ax[:40]:40} → {q}")
    print(f"\nОси с query: {len(AXIS_YOUTUBE_QUERIES)}/28")
    print(f"Оси с канали: {len(AXIS_YOUTUBE_CHANNELS)}/28")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="YouTube Intelligence Module за CORTEX++")
    parser.add_argument("--axis",       default="TECHNOLOGY_AI_REVIEW")
    parser.add_argument("--list-axes",  action="store_true")
    parser.add_argument("--video-id",   help="Тествай транскрипция на конкретно видео")
    args = parser.parse_args()

    if args.list_axes:
        _test_all_axes_summary()
    elif args.video_id:
        result = get_transcript(args.video_id)
        print(f"Метод: {result['transcript_method']}")
        print(f"Chars: {result['transcript_chars']}")
        print(f"Preview:\n{result['transcript'][:500]}")
    else:
        _test_single_axis(args.axis)