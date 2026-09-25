"""
test/test_log_masking.py — a key that reaches the cycle log keeps at most 4 characters.

Why (24 Sep 2026): the cycle log is the runner's stdout, and stdout never passes
through core/durable.py's scrub. So the Gemini key (17 lines of
cycle_2026-09-22_030401.log, via core/groq_backend.py's "[LLM] ... failed" print)
and the Telegram bot token (cycle_2026-09-23_101901.log:32, via
experiments/needs/approve_reader.py's getUpdates-failed print) were written
verbatim. The existing Telegram rule in core/redact.py also missed the token
because it sat right after "bot" in the URL, where \b cannot match.

The failure these tests exist to catch: any 5-character slice of a fake secret
surviving into a printed line or into the channel-state file. The fake values are
random per run so an accidental substring elsewhere cannot make a test pass.
"""
from __future__ import annotations

import ast
import json
import secrets
import string
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.redact import mask_secrets  # noqa: E402

ALNUM = string.ascii_letters + string.digits


def _fake_telegram() -> str:
    return "".join(secrets.choice("123456789") for _ in range(10)) + ":" + \
        "".join(secrets.choice(ALNUM) for _ in range(35))


def _fake_gemini() -> str:
    return "AIza" + "".join(secrets.choice(ALNUM) for _ in range(35))


def _leaks(secret: str, text: str) -> bool:
    """True if more than 4 characters of `secret` survive anywhere in `text`."""
    return any(secret[i:i + 5] in text for i in range(len(secret) - 4))


def test_a_telegram_token_in_a_url_keeps_at_most_four_chars():
    tok = _fake_telegram()
    line = mask_secrets(f"Max retries exceeded with url: /bot{tok}/getUpdates")
    assert not _leaks(tok, line), line
    assert f"/bot{tok[:4]}…/getUpdates" in line


def test_a_gemini_key_in_a_url_keeps_at_most_four_chars():
    key = _fake_gemini()
    line = mask_secrets("400 Client Error: Bad Request for url: https://generativelanguage."
                        f"googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={key}")
    assert not _leaks(key, line), line
    assert "?key=AIza…" in line


def test_prose_and_near_misses_are_untouched():
    for s in ("risk-HighRewardOpportunityInTheMarket", "20260924:12:00", "step 12.6 ok",
              "ask-as-another-question task-management-system"):
        assert mask_secrets(s) == s


def test_the_approve_reader_print_and_state_file_are_masked(tmp_path, monkeypatch, capsys):
    """The real call path: approve_reader.run() with getUpdates failing the way
    requests fails, URL and token inside the exception message."""
    import experiments.needs.approve_reader as ar
    tok = _fake_telegram()
    monkeypatch.setattr(ar, "_load", lambda p, default=None:
                        {"channel": "telegram", "token": tok, "chat_id": "1"}
                        if p == ar.NOTIFY_CFG else (default if default is not None else {}))

    def _boom(token, method, **params):
        raise requests.exceptions.ConnectionError(
            f"HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded "
            f"with url: /bot{token}/{method}?offset=1&timeout=0")
    monkeypatch.setattr(ar, "_tg", _boom)
    from experiments.needs import channel as _ch
    monkeypatch.setattr(_ch, "CHANNEL_STATE", tmp_path / "human_channel_state.json")

    assert ar.run() == 0
    out = capsys.readouterr().out
    assert "getUpdates FAILED" in out
    assert not _leaks(tok, out), out
    state = (tmp_path / "human_channel_state.json").read_text(encoding="utf-8")
    assert json.loads(state)["state"] == "dead"
    assert not _leaks(tok, state), state


def test_the_llm_failure_print_goes_through_the_mask():
    """Structural: the '[LLM] ... failed' print in groq_backend must be wrapped in
    mask_secrets(...). Checked on the AST (identifiers), not on comments."""
    tree = ast.parse((REPO / "core" / "groq_backend.py").read_text(encoding="utf-8"))
    found = masked = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            text = ast.unparse(node)
            if "failed (" in text and "-- next" in text:
                found += 1
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Call) and getattr(arg.func, "id", None) == "mask_secrets":
                    masked += 1
    assert found >= 1, "the '[LLM] ... failed' print was not found — test is stale"
    assert masked == found, "an '[LLM] ... failed' print writes provider text unmasked"
