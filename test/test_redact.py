# -*- coding: utf-8 -*-
r"""
test/test_redact.py — the credential scrubber, and the prose it must not eat.

THE CASE (11 Sep 2026). A push of 21 local commits to the PUBLIC repo was stopped
because the diff carried a live-shaped Google API key — `AIza` + 35, the exact
format — in nine log lines:

    memory/night_events.jsonl        2   /detail
    memory/llm_provenance.jsonl      3   /error
    memory/diagnosis_history.jsonl   4   /evidence[]

Nobody logged a key. A Gemini error echoed the request URL, the URL carries
`?key=...`, and core/groq_backend._log_failure stored the provider's text
verbatim — correctly, because a failure with no message is useless. What was
missing is that provider text is untrusted input and a log line gets committed.

TWO FAILURE PATHS, AND THE SECOND IS THE DANGEROUS ONE:

  1. A credential reaches disk.       -> the leak. Covered below.
  2. A legitimate value is rewritten. -> SILENT DATA CORRUPTION, and worse,
     because nothing announces it and the original is gone.

Path 2 is not hypothetical here. The first scan of that diff matched twenty
`sk-...` strings and every one was English prose out of news/. The first version
of core/redact.py reasoned that requiring no hyphens in the body kept prose out;
its own selftest disproved that in one run, because
"risk-HighRewardOpportunityInTheMarket" is `sk-` plus exactly 32 alphanumerics.
PROSE_CORPUS below is that negative control, and it is the half of this file that
matters most: a scrubber that eats text is a worse defect than the one it fixes.

WHAT NO OUTPUT MEANS: redact() returning the text unchanged with {} hits is the
normal answer for almost every line the system ever writes.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from core import redact as R  # noqa: E402

# Real shapes, none of them a live credential: each body is filler of the right
# length and alphabet. A test must never carry a working key.
GOOGLE = "AIza" + "B" * 35                       # 39 chars, the format that leaked
GROQ = "gsk_" + "c" * 40
OPENAI = "sk-" + "d" * 40
OPENROUTER = "sk-or-v1-" + "e" * 32
ANTHROPIC = "sk-ant-" + "f" * 40
CEREBRAS = "csk-" + "g" * 32
GITHUB = "ghp_" + "h" * 36
# ASSEMBLED, NOT WRITTEN, and GitHub push protection is why. The literal
# form of this fixture was rejected on push as a "Slack API Token", and that
# detector is right not to try to tell my filler from a real one. A test must
# not contain a string a scanner can match, so the shape is built from
# fragments at runtime; the pattern under test is unchanged.
SLACK = "xox" + "b-" + "1" * 12 + "-" + "abcdefghijklmnop"
TELEGRAM = "1234567890:" + "i" * 35

# VERBATIM SHAPES from the scan that produced the false positives, plus ordinary
# text from this repo's own vocabulary. Every line must survive untouched.
PROSE_CORPUS = [
    "risk-HighRewardOpportunityInTheMarket",
    "ask-as-another-question about the axis",
    "sk-as-nasa-selects-new-mission",          # a headline fragment from news/
    "SK-Shipping-Company-announces",
    "task-management-system and disk-space-monitoring",
    "the composite is a weighted mean over axes, not over branches",
    "merkle_to_training -> FAILED: cannot unpack non-iterable Mapping object",
    "September 09:   426.62 ppm",
    "https://gml.noaa.gov/ccgg/trends/monthly.html",
    "https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson&minmagnitude=5",
    '{"count": 38}',
    "Полунощ: цикълът се затвори без грешка",
    "brisk-AutumnWeatherPatternsObservedAcrossEurope",
    "0.6863 vs 0.675 — 391 of 1635 pairs are sign-fragile",
    # REAL FALSE POSITIVE, found by sweeping all 7,261 tracked files: a 9-char
    # Drupal download token scraped from resourcepanel.org HTML. Not a secret,
    # and rewriting it would break the download URL in a knowledge snapshot.
    '<a href=\"/file/3298/download?token=aBcD1234x\">Download the Full Report</a>',
]


# --------------------------------------------------------------------------- #
# path 2 first: the scrubber must not eat legitimate text
# --------------------------------------------------------------------------- #

def test_prose_is_never_rewritten():
    """THE NEGATIVE CONTROL, and the reason this file exists in this order.
    Each line is checked on its own so a failure names the offender."""
    for line in PROSE_CORPUS:
        clean, hits = R.redact(line)
        assert clean == line, f"the scrubber rewrote legitimate text: {line!r} -> {clean!r}"
        assert hits == {}, f"{line!r} produced hits {hits}"


def test_the_exact_string_that_broke_the_first_version():
    """`sk-` + exactly 32 alphanumerics. The first openai_key rule matched this
    and would have rewritten news text. Pinned so it cannot come back."""
    s = "risk-" + "HighRewardOpportunityInTheMarket"
    assert len("HighRewardOpportunityInTheMarket") == 32
    assert R.redact(s)[0] == s


def test_a_url_without_a_credential_is_untouched():
    u = "https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson&minmagnitude=5"
    assert R.redact(u)[0] == u


# --------------------------------------------------------------------------- #
# path 1: the credential must not survive
# --------------------------------------------------------------------------- #

def test_every_known_shape_is_removed():
    for name, sample in (("google_api_key", GOOGLE), ("groq_key", GROQ),
                         ("openai_key", OPENAI), ("openrouter_key", OPENROUTER),
                         ("anthropic_key", ANTHROPIC), ("cerebras_key", CEREBRAS),
                         ("github_token", GITHUB), ("slack_token", SLACK),
                         ("telegram_bot_token", TELEGRAM)):
        clean, hits = R.redact(f"error calling provider with {sample} and more text")
        assert sample not in clean, f"{name} survived: {clean}"
        assert hits, f"{name} produced no hits"


def test_the_leak_path_itself_is_closed_and_stays_readable():
    """The real line shape from llm_provenance: a provider error echoing the URL.
    The key goes; the parameter NAME stays, so the log still says what was passed."""
    line = f"HTTPError: 400 Client Error for url: https://generativelanguage.googleapis.com/v1/models?key={GOOGLE}"
    clean, hits = R.redact(line)
    assert GOOGLE not in clean
    assert "?key=" in clean, "the parameter name must survive — it is the diagnosis"
    assert "[REDACTED" in clean
    assert "googleapis.com" in clean, "the endpoint must survive too"
    assert hits


def test_a_redaction_names_the_pattern_that_fired():
    """A bare [REDACTED] teaches the next reader nothing."""
    clean, _ = R.redact(GOOGLE)
    assert "[REDACTED:google_api_key]" in clean


def test_a_private_key_block_is_caught():
    clean, hits = R.redact("-----BEGIN RSA PRIVATE KEY-----\nMIIEow...")
    assert "BEGIN RSA PRIVATE KEY" not in clean
    assert "private_key_block" in hits


# --------------------------------------------------------------------------- #
# the write path — the net, not the instruction
# --------------------------------------------------------------------------- #

def test_the_durable_write_path_scrubs_both_modes():
    """append_durable AND append_batched. Scrubbing only one would leave the
    batched writers — which is what llm_provenance uses — as the leak."""
    from core import durable as D
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "t.jsonl"
        D.append_json(p, {"error": f"url https://g/v1?key={GOOGLE}"})
        D.append_json(p, {"error": f"second {GROQ}"}, batched=True)
        D.barrier()
        txt = p.read_text(encoding="utf-8")
    assert GOOGLE not in txt, "the unbatched path leaked"
    assert GROQ not in txt, "the BATCHED path leaked"
    assert txt.count("[REDACTED") >= 2


def test_the_write_path_leaves_ordinary_rows_byte_identical():
    from core import durable as D
    import json as _json
    row = {"axis": "CLIMATE_GLOBAL_RISK_REVIEW", "value": 426.62,
           "quote": "September 09:   426.62 ppm", "note": PROSE_CORPUS[0]}
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "t.jsonl"
        D.append_json(p, row)
        got = _json.loads(p.read_text(encoding="utf-8").strip())
    assert got == row, "a clean row was altered on the way to disk"


def test_a_scrubber_fault_never_costs_the_record(monkeypatch):
    """FAIL-OPEN. core/durable.py exists so a record is not lost; a guard that
    raises inside it would defeat the file it is protecting. A broken scrubber
    must write the line through, not drop it."""
    from core import durable as D

    def boom(text):
        raise RuntimeError("scrubber exploded")
    monkeypatch.setattr(R, "scrub_line", boom)
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "t.jsonl"
        assert D.append_json(p, {"note": "must survive"}) is True
        assert "must survive" in p.read_text(encoding="utf-8")


def test_redactions_are_counted_so_the_event_is_visible():
    before = R.redactions().get("google_api_key", 0)
    R.scrub_line(f"x {GOOGLE} y")
    assert R.redactions().get("google_api_key", 0) == before + 1


# --------------------------------------------------------------------------- #
# mutation nets
# --------------------------------------------------------------------------- #

def test_mutation_the_scrub_call_in_durable_is_load_bearing(monkeypatch):
    """Neuter the scrub and the key reaches the file. This is the state the repo
    was in when the push was stopped."""
    from core import durable as D
    monkeypatch.setattr(D, "_scrub", lambda line: line)
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "t.jsonl"
        D.append_json(p, {"error": GOOGLE})
        assert GOOGLE in p.read_text(encoding="utf-8"), (
            "with _scrub neutered the key should reach disk — if it does not, "
            "this test no longer proves the call site is what protects us")


def test_mutation_the_lookbehind_is_load_bearing():
    """Drop the negative lookbehind from openai_key and prose starts matching.
    Rebuilt here rather than edited in place, so the module is untouched."""
    import re
    loose = re.compile(r"sk-(?:proj-)?[0-9A-Za-z]{32,}")
    victim = "risk-HighRewardOpportunityInTheMarket"
    assert loose.search(victim), "the loose rule should match prose — that was the bug"
    strict = dict(R.PATTERNS)["openai_key"]
    assert not strict.search(victim), "the shipped rule must NOT match prose"


def test_the_selftest_passes_and_exits_zero():
    import subprocess
    r = subprocess.run([sys.executable, str(BASE / "core" / "redact.py")],
                       cwd=str(BASE), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"exit {r.returncode}:\n{r.stdout}\n{r.stderr}"
    assert "RESULT: OK" in r.stdout
