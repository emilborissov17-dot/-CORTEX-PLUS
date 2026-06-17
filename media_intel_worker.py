#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
media_intel_worker.py
24/7 media intelligence pipeline:
  search_logic → YouTube search → cheap LLM relevance filter →
  yt-dlp audio download → Groq Whisper transcription →
  full LLM relevance scoring → media_seen.json + data/media_transcripts/
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from search_logic import generate_search_keywords
from core.groq_backend import call_groq

TARGET_CONFIG    = BASE / "config" / "target_config.json"
MEDIA_SEEN       = BASE / "cortex_memory" / "media_seen.json"
TRANSCRIPTS_DIR  = BASE / "data" / "media_transcripts"

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
GROQ_WHISPER_URL   = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_MODEL      = "whisper-large-v3"

PRE_RELEVANCE_THRESHOLD  = 0.40   # before transcription (title+description only)
POST_RELEVANCE_THRESHOLD = 0.45   # after transcription (full text)

PYTHON_EXE = Path(sys.executable)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        env_file = BASE / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith(name + "="):
                    val = line.split("=", 1)[1].strip()
                    break
    return val


def _load_media_seen() -> dict:
    if MEDIA_SEEN.exists():
        return json.loads(MEDIA_SEEN.read_text(encoding="utf-8"))
    return {}


def _save_media_seen(data: dict) -> None:
    MEDIA_SEEN.parent.mkdir(parents=True, exist_ok=True)
    MEDIA_SEEN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _parse_llm_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences and <think> blocks."""
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
        m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {}


def _get_axis_rationale(axis_name: str) -> str:
    config = json.loads(TARGET_CONFIG.read_text(encoding="utf-8"))
    for domain_block in config.values():
        if isinstance(domain_block, dict) and axis_name in domain_block:
            return domain_block[axis_name].get("rationale", "")
    return ""


# ---------------------------------------------------------------------------
# YouTube search
# ---------------------------------------------------------------------------

def _yt_search_one(query: str, max_results: int, api_key: str,
                   duration: str, published_after: str) -> list[dict]:
    """Single YouTube Data API search call. duration: 'long' | 'medium'."""
    import requests
    params = {
        "part":            "snippet",
        "q":               query,
        "type":            "video",
        "order":           "relevance",   # explicit; also the API default
        "videoDuration":   duration,      # 'long' >20 min | 'medium' 4-20 min
        "publishedAfter":  published_after,
        "maxResults":      max_results,
        "key":             api_key,
        "relevanceLanguage": "en",
        "videoEmbeddable": "true",
    }
    r = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("items", [])


def youtube_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search YouTube for substantive videos (medium 4-20 min + long >20 min).
    Short clips (<4 min) are excluded. order=relevance, content from last 3 years.
    Returns list of {video_id, title, description, url, channel, published}.
    """
    import requests
    api_key = _load_env("YOUTUBE_API_KEY")
    if not api_key:
        print("[YT] YOUTUBE_API_KEY missing")
        return []

    # Cutoff: 3 years back for fresh scientific content
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3 * 365)).strftime("%Y-%m-%dT00:00:00Z")

    seen_ids: set[str] = set()
    items: list = []

    for duration in ("long", "medium"):
        try:
            batch = _yt_search_one(query, max_results, api_key, duration, cutoff)
            for item in batch:
                vid_id = item.get("id", {}).get("videoId")
                if vid_id and vid_id not in seen_ids:
                    seen_ids.add(vid_id)
                    items.append(item)
        except Exception as e:
            print(f"[YT] Search error ({duration}): {e}")

    results = []
    for item in items:
        vid_id = item["id"]["videoId"]
        sn = item.get("snippet", {})
        results.append({
            "video_id":    vid_id,
            "title":       sn.get("title", ""),
            "description": sn.get("description", "")[:500],
            "url":         f"https://www.youtube.com/watch?v={vid_id}",
            "channel":     sn.get("channelTitle", ""),
            "published":   sn.get("publishedAt", ""),
        })

    print(f"[YT] Found {len(results)} results (long+medium, last 3y) for: {query!r}")
    return results[:max_results * 2]  # cap total across both duration buckets


# ---------------------------------------------------------------------------
# Relevance checks (LLM)
# ---------------------------------------------------------------------------

def quick_relevance_check(axis_name: str, rationale: str, title: str, description: str) -> float:
    """Cheap pre-transcription relevance check — title + description only."""
    prompt = (
        f"You are a relevance filter for CORTEX++, a civilization-monitoring AI.\n\n"
        f"Axis: {axis_name}\n"
        f"Axis goal: {rationale}\n\n"
        f"Video title: {title}\n"
        f"Video description: {description}\n\n"
        "Rate relevance to the axis 0.0–1.0.\n"
        'Return ONLY valid JSON: {"relevance_score": <float>, "reason": "<10 words>"}'
    )
    try:
        raw  = call_groq(prompt, max_tokens=80)
        data = _parse_llm_json(raw)
        score = float(data.get("relevance_score", 0.0))
        score = max(0.0, min(1.0, score))
        print(f"  [PRE]  score={score:.2f}  reason={data.get('reason', '')}")
        return score
    except Exception as e:
        print(f"  [PRE]  error: {e}")
        return 0.0


def full_relevance_check(axis_name: str, rationale: str, transcript: str) -> tuple[float, str]:
    """Full relevance check on complete transcript text."""
    excerpt = transcript[:3000]
    prompt = (
        f"You are a relevance filter for CORTEX++, a civilization-monitoring AI.\n\n"
        f"Axis: {axis_name}\n"
        f"Axis goal: {rationale}\n\n"
        f"Video transcript excerpt:\n{excerpt}\n\n"
        "Rate relevance 0.0–1.0 and summarise key insights in ≤30 words.\n"
        'Return ONLY valid JSON: {"relevance_score": <float>, "key_insights": "<text>"}'
    )
    try:
        raw  = call_groq(prompt, max_tokens=150)
        data = _parse_llm_json(raw)
        score    = float(data.get("relevance_score", 0.0))
        score    = max(0.0, min(1.0, score))
        insights = data.get("key_insights", "")
        print(f"  [POST] score={score:.2f}  insights={insights}")
        return score, insights
    except Exception as e:
        print(f"  [POST] error: {e}")
        return 0.0, ""


# ---------------------------------------------------------------------------
# Audio download + transcription
# ---------------------------------------------------------------------------

def download_audio(url: str, video_id: str, output_dir: Path) -> Path | None:
    """Download audio-only from YouTube via yt-dlp. Returns path to .mp3 file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(id)s.%(ext)s")

    cmd = [
        str(PYTHON_EXE), "-m", "yt_dlp",
        "--format", "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio",
        "-o", output_template,
        "--no-playlist",
        "--quiet",
        "--no-update",
        url,
    ]
    print(f"  [DL]  Downloading audio for {video_id}...")
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="ignore")[:400]
            print(f"  [DL]  yt-dlp error (rc={result.returncode}): {err}")
            return None
        # yt-dlp names file as {id}.{ext} — search all supported audio exts
        for ext in ("webm", "m4a", "opus", "ogg", "mp3", "mp4"):
            expected = output_dir / f"{video_id}.{ext}"
            if expected.exists():
                print(f"  [DL]  {expected.name}  ({expected.stat().st_size // 1024} KB)")
                return expected
        # Last resort: any audio file in the dir
        for ext in ("webm", "m4a", "opus", "ogg", "mp3", "mp4"):
            found = list(output_dir.glob(f"*.{ext}"))
            if found:
                print(f"  [DL]  {found[0].name}  ({found[0].stat().st_size // 1024} KB)")
                return found[0]
        print("  [DL]  No audio file found after yt-dlp")
        return None
    except subprocess.TimeoutExpired:
        print("  [DL]  Timeout (180s)")
        return None
    except Exception as e:
        print(f"  [DL]  Exception: {e}")
        return None


def transcribe_audio(audio_path: Path) -> str | None:
    """Transcribe audio file using Groq Whisper API."""
    import requests
    api_key = _load_env("GROQ_API_KEY")
    if not api_key:
        print("  [TR]  GROQ_API_KEY missing")
        return None

    file_size = audio_path.stat().st_size
    print(f"  [TR]  Sending {audio_path.name} ({file_size // 1024} KB) to Groq Whisper...")

    if file_size > 24 * 1024 * 1024:
        print("  [TR]  File > 24 MB — skipping (Whisper API limit)")
        return None

    _MIME = {
        "webm": "audio/webm", "m4a": "audio/mp4", "mp4": "audio/mp4",
        "mp3": "audio/mpeg", "opus": "audio/ogg", "ogg": "audio/ogg",
    }
    mime = _MIME.get(audio_path.suffix.lstrip("."), "audio/webm")
    try:
        with open(audio_path, "rb") as f:
            resp = requests.post(
                GROQ_WHISPER_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio_path.name, f, mime)},
                data={"model": WHISPER_MODEL, "response_format": "json"},
                timeout=120,
            )
        resp.raise_for_status()
        text = resp.json().get("text", "").strip()
        if not text:
            print("  [TR]  Empty transcript returned")
            return None
        print(f"  [TR]  Transcript OK — {len(text)} chars")
        return text
    except Exception as e:
        print(f"  [TR]  Error: {e}")
        return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_axis(axis_name: str, max_videos_per_phrase: int = 2) -> dict:
    """
    Full media-intel pipeline for one CORTEX++ axis.
    Returns a summary dict with results for each video processed.
    """
    print(f"\n{'='*62}")
    print(f"[WORKER] Axis: {axis_name}")
    print(f"{'='*62}")

    rationale  = _get_axis_rationale(axis_name)
    keywords   = generate_search_keywords(axis_name)
    media_seen = _load_media_seen()
    summary    = []

    for phrase in keywords:
        videos = youtube_search(phrase, max_results=5)
        processed = 0

        for video in videos:
            if processed >= max_videos_per_phrase:
                break

            url   = video["url"]
            uhash = _url_hash(url)

            if uhash in media_seen:
                print(f"  [SKIP] Already seen: {video['title'][:60]}")
                continue

            print(f"\n  [VIDEO] {video['title'][:72]}")
            print(f"          {url}")

            # ── Step 1: Cheap pre-transcription relevance check ──────────
            pre_score = quick_relevance_check(
                axis_name, rationale, video["title"], video["description"]
            )

            if pre_score < PRE_RELEVANCE_THRESHOLD:
                print(f"  [SKIP] Pre-score {pre_score:.2f} < {PRE_RELEVANCE_THRESHOLD} — not worth transcribing")
                media_seen[uhash] = {
                    "keywords_used":   [phrase],
                    "relevance_score": pre_score,
                    "stage":           "pre_check_skipped",
                    "timestamp":       _utc_now(),
                    "axis":            axis_name,
                    "title":           video["title"],
                    "url":             url,
                }
                _save_media_seen(media_seen)
                summary.append({"url": url, "action": "skipped_pre", "score": pre_score})
                processed += 1
                continue

            # ── Step 2: Download audio ───────────────────────────────────
            tmp_dir = Path(tempfile.mkdtemp(prefix="cortex_media_"))
            audio_path = download_audio(url, video["video_id"], tmp_dir)

            if not audio_path:
                summary.append({"url": url, "action": "download_failed"})
                _try_rmdir(tmp_dir)
                processed += 1
                continue

            # ── Step 3: Transcribe ───────────────────────────────────────
            transcript = transcribe_audio(audio_path)

            try:
                audio_path.unlink()
            except Exception:
                pass
            _try_rmdir(tmp_dir)

            if not transcript:
                summary.append({"url": url, "action": "transcription_failed"})
                processed += 1
                continue

            # ── Step 4: Save transcript ──────────────────────────────────
            axis_dir = TRANSCRIPTS_DIR / axis_name
            axis_dir.mkdir(parents=True, exist_ok=True)
            safe_title = re.sub(r"[^\w\-]", "_", video["title"])[:50]
            ts_file = axis_dir / f"{safe_title}_{uhash[:8]}.txt"
            ts_file.write_text(
                f"URL: {url}\n"
                f"Title: {video['title']}\n"
                f"Channel: {video['channel']}\n"
                f"Published: {video['published']}\n"
                f"Timestamp: {_utc_now()}\n"
                f"Axis: {axis_name}\n"
                f"Search phrase: {phrase}\n\n"
                f"{transcript}",
                encoding="utf-8",
            )
            print(f"  [SAVE] → {ts_file.relative_to(BASE)}")

            # ── Step 5: Full relevance check on transcript ───────────────
            post_score, insights = full_relevance_check(axis_name, rationale, transcript)

            # ── Step 6: Log to media_seen ────────────────────────────────
            media_seen[uhash] = {
                "keywords_used":   [phrase],
                "relevance_score": post_score,
                "stage":           "transcribed",
                "timestamp":       _utc_now(),
                "axis":            axis_name,
                "title":           video["title"],
                "url":             url,
                "transcript_file": str(ts_file),
                "key_insights":    insights,
            }
            _save_media_seen(media_seen)
            summary.append({
                "url":        url,
                "title":      video["title"],
                "action":     "transcribed",
                "score":      post_score,
                "insights":   insights,
                "transcript": str(ts_file),
            })
            processed += 1
            time.sleep(2)   # courtesy pause between videos

    return {
        "axis":         axis_name,
        "search_phrases": keywords,
        "results":      summary,
        "timestamp":    _utc_now(),
    }


def _try_rmdir(path: Path) -> None:
    try:
        path.rmdir()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_axis = sys.argv[1] if len(sys.argv) > 1 else "CLIMATE_GLOBAL_RISK_REVIEW"
    result = process_axis(test_axis, max_videos_per_phrase=2)
    print(f"\n{'='*62}")
    print("[DONE] Pilot test summary:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
