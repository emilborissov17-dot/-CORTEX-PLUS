#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
core/redact.py — A CREDENTIAL MUST NOT REACH A FILE THAT GETS COMMITTED.
(11 September 2026.)

WHY, WITH THE CASE THAT FORCED IT
---------------------------------
A push of 21 local commits to the PUBLIC repo (github.com/.../-CORTEX-PLUS) was
stopped on 11 Sep because the diff carried a live-shaped Google API key — 39
characters, `AIza` + 35, the exact Google format — in nine places:

    memory/night_events.jsonl        2   field /detail
    memory/llm_provenance.jsonl      3   field /error
    memory/diagnosis_history.jsonl   4   field /evidence[]

Nobody wrote a key into a log. The provider did: a Gemini error message echoes
the request URL, the URL carries `?key=...`, and the backend stored the error
text verbatim. `_log_failure` in core/groq_backend.py records
`f"{type(exc).__name__}: {exc}"` because a failure with no message is useless —
and that is right. What was missing is that provider text is UNTRUSTED INPUT,
and a log line is a thing that gets committed.

WHERE THE NET IS, AND WHY IT IS THERE AND NOT AT THE CALL SITES
---------------------------------------------------------------
core/durable.py is the single chokepoint every JSONL append passes through
(append_durable / append_batched / append_json). Redacting there catches the
three files above, every other append_* caller, and the ones nobody has written
yet. An instruction ("do not log keys") at 143 call sites is not a net; one
scrub on the write path is.

WHAT A REDACTION LOOKS LIKE, AND WHY IT IS NEVER SILENT
-------------------------------------------------------
The replacement names the pattern that fired: `[REDACTED:google_api_key]`. A
line that was scrubbed is therefore self-describing — the next reader learns a
credential was there, which is exactly the fact worth keeping, without keeping
the credential. `redactions()` counts them per process so the event is
countable, and the first hit prints one line, because a data-mutating guard that
nobody can see is its own defect.

THE FORBIDDEN FALLBACK IS AN EAGER PATTERN
-------------------------------------------
Corrupting a legitimate value is worse than the leak this prevents. The first
scan of the diff matched twenty `sk-...` strings and every one was English prose
out of news/ — "risk-High-Reward...", "ask-as-another...". A loose `sk-[\w-]{16,}`
rule would have silently rewritten news text.

So every pattern here is provider-specific and anchored on a fixed prefix plus a
length the provider actually issues.

AND THE FIRST VERSION OF THAT ANCHORING WAS STILL WRONG, caught by this file's
own selftest on its first run. The reasoning was "require [A-Za-z0-9] with no
hyphens in the body, because the prose that matched all contains them". False:
"risk-HighRewardOpportunityInTheMarket" is `sk-` followed by exactly 32
alphanumerics and matched. The fix is a negative lookbehind — a real key is a
standalone token, never the tail of a longer word. Recorded here because the
plausible-but-wrong rule is the interesting part, not the working one.

test/test_redact.py holds the prose corpus as a negative control and fails if any
rule starts eating it.
"""
from __future__ import annotations

import re
import threading

# (name, pattern). Anchored on real provider prefixes; see the docstring on why
# nothing here is generic.
PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    # Google / Gemini: AIza + 35 = 39 chars exactly. This is the one that was found.
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    # The leak PATH, not just the key: any credential-bearing URL parameter.
    # Keeps the parameter name so the log still says what was being passed.
    #
    # THE MINIMUM IS 20, AND IT WAS 8 FOR ONE HOUR. A sweep of all 7,261 tracked
    # files with this rule at {8,} flagged
    # knowledge/materials_snapshots/www.resourcepanel.org_...json 16 times — and
    # every hit was a NINE-character Drupal download token scraped out of someone
    # else's public HTML (`/file/3298/download?token=...`). Those are not secrets,
    # and rewriting them would have broken the download URLs in a knowledge
    # snapshot: the eager-pattern failure this module's docstring warns about,
    # caught in real data rather than in theory. Every credential worth hiding is
    # long — Google 39, Groq 40+, OpenAI 40+, bearer tokens 30+ — so 20 keeps the
    # leak closed and lets third-party junk through untouched.
    ("url_credential", re.compile(
        r"([?&](?:key|api_?key|access_token|auth|token|password)=)[^&\s\"'<>]{20,}",
        re.I)),
    # NOTE THE LOOKBEHIND ON EVERY `sk-`/`csk-` RULE, and it is not decoration.
    # The first version of this file reasoned that "no hyphen inside the body" was
    # enough to keep prose out. Its own selftest corpus disproved it in one run:
    # "risk-HighRewardOpportunityInTheMarket" is `sk-` followed by exactly 32
    # alphanumerics, so the openai_key rule matched and would have rewritten news
    # text. A real key is a standalone token — preceded by whitespace, a quote, an
    # `=` or the start of the string — never by a letter of a longer word.
    # NVIDIA NIM — ADDED 11 Sep 2026, and the gap is the lesson. This module was
    # written because a Gemini error echoed ?key=... into three tracked logs. On
    # 11 Sep the chain gained an NVIDIA leg (NVIDIA_API_KEY, "nvapi-..."), and a
    # check of the pending diff showed a real-shaped nvapi- key passing straight
    # through redact() untouched: the net knew every provider the system used
    # YESTERDAY. A scrubber is only as current as its list, so adding a backend
    # now means adding its key shape in the same breath.
    ("nvidia_api_key", re.compile(r"(?<![0-9A-Za-z_])nvapi-[0-9A-Za-z_\-]{20,}")),
    ("groq_key", re.compile(r"(?<![0-9A-Za-z_])gsk_[0-9A-Za-z]{20,}")),
    ("openrouter_key", re.compile(r"(?<![0-9A-Za-z_])sk-or-v1-[0-9A-Za-z]{20,}")),
    ("anthropic_key", re.compile(r"(?<![0-9A-Za-z_])sk-ant-[0-9A-Za-z_\-]{20,}")),
    ("cerebras_key", re.compile(r"(?<![0-9A-Za-z_])csk-[0-9A-Za-z]{20,}")),
    ("openai_key", re.compile(r"(?<![0-9A-Za-z_])sk-(?:proj-)?[0-9A-Za-z]{32,}")),
    ("github_token", re.compile(r"(?:gh[pousr]_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{30,})")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}")),
    # Telegram bot tokens: <numeric id>:<35-char secret>
    ("telegram_bot_token", re.compile(r"\b\d{8,12}:[A-Za-z0-9_\-]{30,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

_lock = threading.Lock()
_counts: dict[str, int] = {}
_announced = False


def redact(text: str) -> tuple[str, dict[str, int]]:
    """(clean_text, {pattern_name: hits}). Pure; never raises on str input."""
    if not text:
        return text, {}
    hits: dict[str, int] = {}
    out = text
    for name, pat in PATTERNS:
        if name == "url_credential":
            out, n = pat.subn(lambda m: f"{m.group(1)}[REDACTED:url_credential]", out)
        else:
            out, n = pat.subn(f"[REDACTED:{name}]", out)
        if n:
            hits[name] = hits.get(name, 0) + n
    return out, hits


def scrub_line(line: str) -> str:
    """The write-path entry point. Counts, announces once, returns clean text.

    Deliberately fail-open on anything unexpected: a scrubber that raises would
    take down the append it was protecting, and a lost record is the defect
    core/durable.py exists to prevent.
    """
    global _announced
    try:
        clean, hits = redact(line)
    except Exception:
        return line
    if hits:
        with _lock:
            for k, v in hits.items():
                _counts[k] = _counts.get(k, 0) + v
            first = not _announced
            _announced = True
        if first:
            names = ", ".join(sorted(hits))
            print(f"  [REDACT] a credential-shaped string was removed from a log "
                  f"line before it was written ({names}). This is the guard "
                  f"working; core/redact.py says why it exists.")
    return clean


def redactions() -> dict[str, int]:
    """What this process has removed, by pattern. {} is the normal answer."""
    with _lock:
        return dict(_counts)


def _selftest() -> int:
    print("core/redact.py --selftest")
    google = "AIza" + "B" * 35
    prose = ("risk-HighRewardOpportunityInTheMarket ask-as-another-question "
             "task-management-system disk-space-monitoring")
    checks = [
        ("a Google key is removed", "[REDACTED:google_api_key]" in redact(google)[0]),
        ("the key itself is gone", google not in redact(google)[0]),
        ("a key in a URL is removed",
         "[REDACTED:url_credential]" in redact("https://x/y?key=" + "A" * 30)[0]),
        ("the parameter name survives",
         "?key=" in redact("https://x/y?key=" + "A" * 30)[0]),
        ("English prose is untouched", redact(prose)[0] == prose),
        ("clean text is returned unchanged", redact("nothing here")[0] == "nothing here"),
        ("empty input is safe", redact("")[0] == ""),
        ("hits are reported", redact(google)[1].get("google_api_key") == 1),
        ("no hits on clean text", redact(prose)[1] == {}),
    ]
    ok = True
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
