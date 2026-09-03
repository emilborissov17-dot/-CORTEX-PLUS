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
BASE_DIR      = pathlib.Path(__file__).resolve().parent
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


# The web_intelligence writer puts its verdict under "analysis", but older files
# (and some axes) carry the same keys at the root. _format_as_markdown solved that
# from the day it was written; _publish_daily_index did not, and read the root
# only. The result was public for months: every row of every daily index read
# "UNKNOWN | ..." while the axis page one click behind it read "Severity: HIGH".
# Lifted out of _format_as_markdown rather than copied, so there is one definition
# of where a field lives and the index cannot drift away from the page again.
def get_field(data: dict, *keys):
    """First non-empty value for `keys`, looked up under "analysis" then the root."""
    analysis = data.get("analysis") or {}
    if not isinstance(analysis, dict):
        analysis = {}
    for k in keys:
        v = analysis.get(k) or data.get(k)
        if v:
            return v
    return None


def _format_as_markdown(axis: str, data: dict, date: str) -> str:
    md = f"# {axis.replace('_', ' ')}\n"
    md += f"**Date:** {date}\n\n"

    severity  = get_field(data, "severity")
    action    = get_field(data, "action")
    goal      = get_field(data, "measurable_goal")
    problem   = get_field(data, "problem")
    root_cause= get_field(data, "root_cause")
    timeframe = get_field(data, "timeframe")

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
    proposed = get_field(data, "proposed_actions")
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

    md += f"\n---\n*Generated by CORTEX++ — an auditable civilization-monitoring instrument | {date}*\n"
    return md


# master_web_intel.json is the RUN SUMMARY, not an axis. It has no axis,
# severity, problem or analysis — only axes_covered, total_sources and
# critical_axes — so listing it in the axis table produced a permanent
# "UNKNOWN | ..." row and made the table 26 rows long while the README (and the
# file's own axes_covered) say 25.
#
# It stays PUBLISHED as its own page: reports/{date}/master_web_intel.md has
# existed in 33 report folders and dropping it would break links in published
# history for no gain. What changes is where it appears — its numbers now open
# the index as a coverage line, which is what a summary is for, and the table
# below it contains axes and only axes.
SUMMARY_STEMS = {"master_web_intel"}


def _publish_daily_index(date: str, web_intel_dir: pathlib.Path):
    axes, summary = [], {}
    for json_file in sorted(web_intel_dir.rglob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if json_file.stem in SUMMARY_STEMS:
            summary = data
            continue
        axis = data.get("axis", json_file.stem)
        # get_field, not data.get: severity and problem live under "analysis".
        # Reading the root only is what made every published index say the
        # system knew nothing about all 26 axes.
        severity = get_field(data, "severity") or "UNKNOWN"
        problem = str(get_field(data, "problem") or "")[:100]
        axes.append((axis, severity, problem))

    md = f"# CORTEX++ Daily Report — {date}\n\n"
    md += "> An autonomous system monitoring 25 axes of civilization toward dignity, sustainability and long-term survival of intelligent life.\n\n"
    if summary:
        crit = summary.get("critical_axes") or []
        md += (f"**Coverage:** {summary.get('axes_covered', len(axes))} axes · "
               f"{summary.get('total_sources', '?')} sources · "
               f"{summary.get('youtube_videos_total', '?')} videos · "
               f"{len(crit)} axes flagged critical "
               f"([details](master_web_intel.md))\n\n")
        if crit:
            md += "**Critical this run:** " + ", ".join(str(c) for c in crit[:12]) + "\n\n"
    md += "## Today's Findings\n\n"
    md += "| Axis | Severity | Summary |\n|------|----------|----------|\n"
    for axis, severity, problem in axes:
        link = f"[{axis}]({axis.lower()}.md)"
        ellipsis = "..." if len(problem) > 80 else ""
        md += f"| {link} | {severity} | {problem[:80]}{ellipsis} |\n"

    md += f"\n---\n*Generated by CORTEX++ — an auditable civilization-monitoring instrument | {date}*\n"
    _push_file(f"reports/{date}/index.md", md, f"[{date}] Daily index")
    print(f"[GitHub] OK Daily index")


SCORED = "SCORED"
EXPIRED = "EXPIRED"
PENDING = "PENDING"

# Any field whose presence means somebody actually resolved this prediction.
_RESOLUTION_FIELDS = ("outcome", "actual_value", "resolved", "scored", "resolved_at")


def _resolution_state(h: dict, today: str = None) -> tuple:
    """(SCORED | EXPIRED | PENDING, human detail) for one hypothesis record.

    WHY THIS LIVES IN THE PUBLISHER AND NOT UPSTREAM (17 Aug 2026)
    ---------------------------------------------------------------
    The store is not lying. `cortex_memory/hypotheses/pending.json` says exactly
    what is true: prediction_date 2026-07-20, unresolved. The FORMATTER turned
    that true record into a false public statement by titling it with today's
    date and calling it "Verified Hypotheses". The defect is in publication, so
    the guard belongs at the last gate before the claim becomes public.

    The alternative — sweeping the store and stamping records EXPIRED upstream —
    would be a guarantee that depends on another job running. That is precisely
    what failed here: `evaluator.py` owns this store and NOTHING on the cycle
    calls it, so a sweep would not have run either and the publisher would have
    gone on publishing. A check that holds only when a second job runs is not
    structural. This one holds unconditionally.

    THE HONEST ROOT CAUSE, NOT PAPERED OVER: this store has no resolver on the
    cycle. `scripts/score_prophecies.py` runs every cycle and works fine — it
    scores a DIFFERENT store (the prophecy ledger, via
    core/cortex_orchestrator.py:321, logging "calendar prophecies: 0 hit / 0
    miss / 0 unresolvable / 1 waiting"). The resolver for THIS store is
    `evaluator.check_due_hypotheses`, whose only caller in the repo is
    `hypothesis_generator.py:521`, inside its `if __name__ == "__main__"` block
    behind a `--check` flag. Until the cycle runs it, every prediction here will
    reach its date and stop. This function makes that visible instead of
    invisible; it does not fix it.

    Note the structural fact this leans on: `evaluator.py` REMOVES resolved
    records from pending.json and moves them to resolved.json. So a record still
    in pending.json past its date is unresolved by construction. The explicit
    field check below is belt-and-braces for a future shape change.
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if any(h.get(f) is not None for f in _RESOLUTION_FIELDS):
        return SCORED, "resolved against an observed value"

    raw = str(h.get("prediction_date") or "").strip()
    if not raw:
        # FAIL CLOSED. An undatable claim must never read as current: with no
        # date there is nothing to check it against and nothing to expire it.
        return EXPIRED, "no usable prediction_date — cannot be treated as current"
    try:
        due = datetime.strptime(raw[:10], "%Y-%m-%d").date()
        now = datetime.strptime(today, "%Y-%m-%d").date()
    except Exception:
        return EXPIRED, f"unparseable prediction_date {raw!r}"

    days = (now - due).days
    if days > 0:
        return EXPIRED, f"due {raw}, {days} days overdue, never resolved"
    if days == 0:
        return PENDING, f"due today ({raw}), not yet resolved"
    return PENDING, f"due {raw}, in {-days} days"


def publish_verified_hypotheses() -> int:
    """
    Чете pending.json, взима хипотезите оценени от citation_verifier
    (тези с verification_status) и ги публикува на
    reports/{date}/verified_hypotheses.md.
    """
    pending_path = BASE_DIR / "cortex_memory" / "hypotheses" / "pending.json"
    if not pending_path.exists():
        print("[GitHub] verified_hypotheses -> no pending.json found")
        return 0
    try:
        records = json.loads(pending_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[GitHub] verified_hypotheses -> cannot read pending.json: {e}")
        return 0
    if not isinstance(records, list):
        records = []
    assessed = [r for r in records if r.get("verification_status")]
    if not assessed:
        print("[GitHub] verified_hypotheses -> 0 assessed hypotheses to publish")
        return 0
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    states = [(h, _resolution_state(h)) for h in assessed]
    expired = [h for h, (st, _d) in states if st == EXPIRED]

    # The title used to be "Verified Hypotheses — {today}", which is the whole
    # defect in one line: a prediction due 2026-07-20 was re-stamped with today's
    # date every night for four weeks and published as current. The publication
    # date and the prediction date are now different things and both are visible.
    md  = f"# Hypotheses — published {date}\n\n"
    md += ("> Auto-generated by CORTEX++. This file lists predictions and what has "
           "become of them. **The date in the title is the publication date, not "
           "the prediction date** — each row carries its own.\n\n")
    if expired:
        md += (f"> ⚠️ **{len(expired)} of {len(states)} prediction(s) below are PAST DUE "
               f"and still UNRESOLVED.** They are shown with their original dates and "
               f"are NOT current claims. Nothing on the cycle resolves this store — see "
               f"`evaluator.py`, whose only caller is `hypothesis_generator.py --check`, "
               f"a manual CLI flag.\n\n")

    md += "| Axis | Prediction | Value | Predicted for | Resolution | Checks | Confidence |\n"
    md += "|------|-----------|-------|---------------|------------|--------|------------|\n"
    for h, (state, detail) in states:
        text = h.get("hypothesis_text", "")[:120].replace("|", "╎")
        md += (f"| {h.get('axis', '?')} | {text} | {h.get('predicted_value', '?')} "
               f"| {h.get('prediction_date', '?')} | **{state}** — {detail} "
               f"| {h.get('verification_status', '?')} "
               f"| {h.get('confidence', '?')} |\n")
    md += "\n## Detail\n\n"
    for h, (state, detail) in states:
        md += f"### {h.get('axis', '?')} — {h.get('id', '')}\n"
        md += f"**Hypothesis:** {h.get('hypothesis_text', '')}\n\n"
        md += f"- **Resolution:** `{state}` — {detail}\n"
        md += f"- **Predicted value:** `{h.get('predicted_value', '?')}`\n"
        md += f"- **Predicted for:** {h.get('prediction_date', '?')}\n"
        md += f"- **Model:** {h.get('model_type', '?')}\n"
        md += f"- **Confidence:** {h.get('confidence', '?')}\n"
        md += f"- **Verification status:** `{h.get('verification_status', '?')}`\n"
        reasons = h.get("verification_reasons", [])
        if reasons:
            md += "- **Flags:** " + "; ".join(reasons[:5]) + "\n"
        md += "\n"
    md += f"\n---\n*Generated by CORTEX++ — an auditable civilization-monitoring instrument | published {date}*\n"
    try:
        _push_file(
            f"reports/{date}/verified_hypotheses.md",
            md,
            f"[{date}] verified hypotheses ({len(assessed)})",
        )
        print(f"[GitHub] verified_hypotheses -> {len(assessed)} published")
        return len(assessed)
    except Exception as e:
        print(f"[GitHub] verified_hypotheses -> PUSH FAILED: {e}")
        return 0


def publish_synthesis():
    """Web intelligence + verified hypotheses. Called by fast_cycle_runner."""
    publish_cycle()
    publish_verified_hypotheses()


def publish_vision():
    try:
        vision = VISION_FILE.read_text(encoding="utf-8") if VISION_FILE.exists() else ""
        goal = GOAL_FILE.read_text(encoding="utf-8") if GOAL_FILE.exists() else ""

        readme = "# CORTEX++ — Civilization Watch\n\n"
        readme += "> An attempt to build an autonomous system monitoring 25 axes of civilization — toward dignity, sustainability and long-term survival of intelligent life.\n\n"
        readme += "## Vision\n\n" + vision + "\n\n"
        readme += "## Global Goal\n\n" + goal + "\n\n"
        readme += "## Reports\nSee the [reports/](reports/) folder for daily findings.\n\n"
        readme += "---\n*CORTEX++ — an auditable civilization-monitoring instrument*\n"

        _push_file("README.md", readme, "Update README with vision and goal")
        print("[GitHub] OK README публикуван")
    except Exception as e:
        print(f"[GitHub] FAIL README: {e}")


if __name__ == "__main__":
    print("[GitHub] Публикувам визията...")
    publish_vision()
    print("[GitHub] Публикувам последните синтези...")
    publish_cycle()