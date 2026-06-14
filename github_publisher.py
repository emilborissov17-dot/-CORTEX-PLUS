# github_publisher.py
# Публикува синтезите от CORTEX++ в GitHub след всеки цикъл.
# Файл: C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\github_publisher.py

import json
import os
import pathlib
import base64
import requests
from datetime import datetime, timezone

GITHUB_API    = "https://api.github.com"
REPO_OWNER    = "emilborissov17-dot"
REPO_NAME     = "cortex-civilization-watch"
BASE_DIR      = pathlib.Path(r"C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN")
VISION_FILE   = BASE_DIR / "civilization_vision.txt"
GOAL_FILE     = BASE_DIR / "civilization_goal.txt"


def _load_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        env = BASE_DIR / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("GITHUB_TOKEN="):
                    token = line.split("=", 1)[1].strip()
    return token


def _headers():
    return {
        "Authorization": f"token {_load_token()}",
        "Accept": "application/vnd.github.v3+json",
    }


def _get_sha(path: str) -> str | None:
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    r = requests.get(url, headers=_headers(), timeout=30)
    if r.status_code == 200:
        return r.json().get("sha")
    return None


def _push_file(path: str, content: str, message: str):
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    sha = _get_sha(path)
    payload = {"message": message, "content": encoded}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return r.status_code


def _find_latest_web_intel_dir() -> pathlib.Path | None:
    """
    Връща последната папка в memory/web_intelligence/ която съдържа JSON файлове.
    Първо проверява днешната дата, после търси назад.
    """
    web_intel_base = BASE_DIR / "memory" / "web_intelligence"
    if not web_intel_base.exists():
        return None

    # Вземи всички папки с дата-формат, сортирани низходящо
    date_dirs = sorted(
        [d for d in web_intel_base.iterdir() if d.is_dir() and len(d.name) == 10],
        reverse=True
    )

    for d in date_dirs:
        # Провери дали има JSON файлове вътре
        if any(d.rglob("*.json")):
            return d

    return None


def publish_cycle(web_intel_dir: pathlib.Path = None):
    """
    Публикува последните синтези в GitHub.
    Ако web_intel_dir не е подаден — намира последната налична папка автоматично.
    """
    if web_intel_dir is None:
        web_intel_dir = _find_latest_web_intel_dir()
        if web_intel_dir is None:
            print("[GitHub] Няма налични данни за публикуване.")
            return
        print(f"[GitHub] Публикувам данни от: {web_intel_dir.name}")

    # Използвай датата от папката (не непременно днес)
    date = web_intel_dir.name

    published = 0
    errors = 0

    for json_file in sorted(web_intel_dir.rglob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            axis = data.get("axis", json_file.stem)
            md = _format_as_markdown(axis, data, date)
            gh_path = f"reports/{date}/{axis.lower()}.md"
            _push_file(gh_path, md, f"[{date}] {axis} update")
            print(f"[GitHub] OK {axis}")
            published += 1
        except Exception as e:
            print(f"[GitHub] FAIL {json_file.name}: {e}")
            errors += 1

    try:
        _publish_daily_index(date, web_intel_dir)
    except Exception as e:
        print(f"[GitHub] FAIL Daily index: {e}")

    print(f"[GitHub] Публикувани: {published} | Грешки: {errors}")


def _format_as_markdown(axis: str, data: dict, date: str) -> str:
    md = f"# {axis.replace('_', ' ')}\n"
    md += f"**Date:** {date}\n\n"

    # analysis може да е dict вътре или директно в root
    analysis = data.get("analysis", {}) or {}
    if not isinstance(analysis, dict):
        analysis = {}

    # Четем от analysis или от root
    def get_field(*keys):
        for k in keys:
            v = analysis.get(k) or data.get(k)
            if v:
                return v
        return None

    severity  = get_field("severity")
    action    = get_field("action")
    goal      = get_field("measurable_goal")
    problem   = get_field("problem")
    root_cause= get_field("root_cause")
    timeframe = get_field("timeframe")

    if severity:
        md += f"**Severity:** {severity}\n\n"
    if problem:
        md += f"## Problem\n{problem}\n\n"
    if root_cause:
        md += f"## Root Cause\n{root_cause}\n\n"
    if action:
        md += f"## Proposed Action\n{action}\n\n"
    if goal:
        md += f"**Measurable Goal:** {goal}\n\n"
    if timeframe:
        md += f"**Timeframe:** {timeframe}\n\n"

    # proposed_actions като списък
    proposed = data.get("proposed_actions") or analysis.get("proposed_actions")
    if proposed and isinstance(proposed, list):
        md += "## Proposed Actions\n"
        for a in proposed:
            if isinstance(a, dict):
                md += f"- **{a.get('action', '')}** — {a.get('measurable_goal', '')}\n"
            else:
                md += f"- {a}\n"
        md += "\n"

    # YouTube sources
    yt_items = data.get("youtube_items", [])
    if yt_items:
        md += "## Sources (YouTube)\n"
        for yt in yt_items[:3]:
            title = yt.get("title", "").replace("[YT] ", "")
            link  = yt.get("link", "")
            summary = yt.get("summary", "")[:200]
            md += f"- [{title}]({link})\n  > {summary}...\n\n"

    # RSS sources
    rss_items = [i for i in data.get("raw_items", []) if i.get("source_type") == "rss"]
    if rss_items:
        md += "## Sources (RSS)\n"
        for rss in rss_items[:3]:
            title = rss.get("title", "")
            link  = rss.get("link", "")
            md += f"- [{title}]({link})\n"
        md += "\n"

    md += f"\n---\n*Generated by CORTEX++ AGI | {date}*\n"
    return md


def _publish_daily_index(date: str, web_intel_dir: pathlib.Path):
    axes = []
    for json_file in sorted(web_intel_dir.rglob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            axis = data.get("axis", json_file.stem)
            severity = data.get("severity", "UNKNOWN")
            problem = data.get("problem", "")[:100]
            axes.append((axis, severity, problem))
        except Exception:
            pass

    md = f"# CORTEX++ Daily Report — {date}\n\n"
    md += "> An autonomous system monitoring 25 axes of civilization toward dignity, sustainability and long-term survival of intelligent life.\n\n"
    md += "## Today's Findings\n\n"
    md += "| Axis | Severity | Summary |\n|------|----------|----------|\n"
    for axis, severity, problem in axes:
        link = f"[{axis}]({axis.lower()}.md)"
        md += f"| {link} | {severity} | {problem[:80]}... |\n"

    md += f"\n---\n*Generated by CORTEX++ AGI | {date}*\n"
    _push_file(f"reports/{date}/index.md", md, f"[{date}] Daily index")
    print(f"[GitHub] OK Daily index")


def publish_vision():
    try:
        vision = VISION_FILE.read_text(encoding="utf-8") if VISION_FILE.exists() else ""
        goal = GOAL_FILE.read_text(encoding="utf-8") if GOAL_FILE.exists() else ""

        readme = "# CORTEX++ — Civilization Watch\n\n"
        readme += "> An attempt to build an autonomous system monitoring 25 axes of civilization — toward dignity, sustainability and long-term survival of intelligent life.\n\n"
        readme += "## Vision\n\n" + vision + "\n\n"
        readme += "## Global Goal\n\n" + goal + "\n\n"
        readme += "## Reports\nSee the [reports/](reports/) folder for daily findings.\n\n"
        readme += "---\n*CORTEX++ AGI — Open witness of civilization*\n"

        _push_file("README.md", readme, "Update README with vision and goal")
        print("[GitHub] OK README публикуван")
    except Exception as e:
        print(f"[GitHub] FAIL README: {e}")


if __name__ == "__main__":
    print("[GitHub] Публикувам визията...")
    publish_vision()
    print("[GitHub] Публикувам последните синтези...")
    publish_cycle()