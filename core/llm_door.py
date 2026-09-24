"""
core/llm_door.py — THE ONE DOOR every LLM call in the cycle passes through.

Emil, 19 Sep 2026; built 24 Sep 2026 after phase 1 of task #19 measured it: 12 call
sites reached a model without going through core.groq_backend.call_groq, 11 of them
wrote no provenance, and the two writers that did used two schemas — one recorded
outcome and finish_reason but timed only successes, the other recorded neither.

post() makes the HTTP request, times it, writes ONE provenance row and returns the
response untouched — each caller keeps its own parsing. The row is written on
every path: a success, an HTTP error, an exception, an empty answer. record() writes
the same row for an event with no request behind it (a refusal, a skipped leg).

THE SCHEMA (schema=2), one for every backend:
  ts, schema, caller, step, backend, model, outcome (ok|error|refused),
  finish_reason, latency_s (also on error), prompt_tokens, completion_tokens,
  http_status, error, prompt_sha1, prompt_chars, reply_chars
`backend` keeps the labels core/phase_report groups by ("Groq", "OpenRouter",
"NVIDIA", "Gemini", "local:<model>").

test/test_llm_one_door.py fails on any HTTP call to a model endpoint outside this
module in the cycle's code paths.

    venv\\Scripts\\python.exe -m core.llm_door --selftest
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PROVENANCE = BASE / "memory" / "llm_provenance.jsonl"
SCHEMA = 2
_ROTATE_BYTES = 5_000_000
_SKIP_FRAMES = ("llm_door.py", "groq_backend.py", "llm_json.py", "step_budget.py")


def _caller_from_stack() -> str:
    """module:function of the first frame outside the LLM plumbing."""
    for fr in inspect.stack()[2:]:
        name = os.path.basename(fr.filename)
        if name not in _SKIP_FRAMES:
            return f"{os.path.splitext(name)[0]}:{fr.function}"
    return "unknown"


def _reply_facts(backend: str, resp) -> dict:
    """finish_reason, token counts and reply length, from whichever dialect answered."""
    try:
        return _facts_from_dict(resp.json())
    except Exception:
        return {}


def _facts_from_dict(d) -> dict:
    out: dict = {}
    if not isinstance(d, dict):
        return out
    if "choices" in d:                                     # OpenAI-compatible
        ch = (d.get("choices") or [{}])[0] or {}
        out["finish_reason"] = ch.get("finish_reason")
        msg = ch.get("message") or {}
        # a reasoning model may leave content empty and answer in reasoning; the
        # ladder uses that answer, so it is not an empty reply
        out["reply_chars"] = len(str(msg.get("content") or msg.get("reasoning")
                                     or msg.get("reasoning_content") or ch.get("text") or ""))
        u = d.get("usage") or {}
        out["prompt_tokens"], out["completion_tokens"] = u.get("prompt_tokens"), u.get("completion_tokens")
    elif "candidates" in d:                                # Gemini
        c = (d.get("candidates") or [{}])[0] or {}
        out["finish_reason"] = c.get("finishReason")
        parts = ((c.get("content") or {}).get("parts") or [])
        out["reply_chars"] = sum(len(str(p.get("text") or "")) for p in parts)
        u = d.get("usageMetadata") or {}
        out["prompt_tokens"], out["completion_tokens"] = u.get("promptTokenCount"), u.get("candidatesTokenCount")
        out["thoughts_tokens"] = u.get("thoughtsTokenCount")
    elif "message" in d or "response" in d or "done_reason" in d:   # Ollama
        out["finish_reason"] = d.get("done_reason")
        out["reply_chars"] = len(str((d.get("message") or {}).get("content") or d.get("response") or ""))
        out["prompt_tokens"], out["completion_tokens"] = d.get("prompt_eval_count"), d.get("eval_count")
    elif "text" in d:                                      # Whisper transcription
        out["reply_chars"] = len(str(d.get("text") or ""))
    return {k: v for k, v in out.items() if v is not None}


def _mask(error) -> str | None:
    """Provider errors echo the request URL, and a Gemini URL carries ?key=."""
    if not error:
        return None
    try:
        from core.redact import mask_secrets
        return mask_secrets(str(error))[:300]
    except Exception:
        return str(error)[:300]


def record(*, caller: str | None, backend: str, model: str | None, outcome: str,
           latency_s: float | None = None, finish_reason: str | None = None,
           http_status: int | None = None, error: str | None = None,
           prompt_text: str | None = None, **extra) -> dict:
    """Append one schema-2 row. Never raises: bookkeeping must not break a call."""
    row = {"ts": datetime.now(timezone.utc).isoformat(), "schema": SCHEMA,
           "caller": caller or _caller_from_stack(),
           "step": os.environ.get("CORTEX_STEP") or None,
           "backend": backend, "model": model, "outcome": outcome,
           "finish_reason": finish_reason, "latency_s": latency_s,
           "http_status": http_status, "error": _mask(error)}
    if prompt_text is not None:
        row["prompt_sha1"] = hashlib.sha1(prompt_text.encode("utf-8", "ignore")).hexdigest()[:12]
        row["prompt_chars"] = len(prompt_text)
    row.update({k: v for k, v in extra.items() if v is not None})
    try:
        PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
        if PROVENANCE.exists() and PROVENANCE.stat().st_size > _ROTATE_BYTES:
            PROVENANCE.replace(PROVENANCE.with_suffix(".jsonl.1"))
        try:
            from core.durable import append_json
            append_json(PROVENANCE, row, batched=True)
        except Exception:
            with PROVENANCE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return row


def post(caller: str | None, backend: str, model: str | None, url: str, *,
         prompt_text: str | None = None, row_extra: dict | None = None, **kw):
    """requests.post through the door. Returns the Response; re-raises what
    requests raises. Exactly one provenance row on every path."""
    # Imported per call, not at module import: a module-level binding would keep
    # whatever `requests` was in sys.modules the first time this module loaded
    # (a test's stand-in, once), for the life of the process.
    import requests
    caller = caller or _caller_from_stack()
    t0 = time.monotonic()
    try:
        resp = requests.post(url, **kw)
    except Exception as e:  # noqa: BLE001
        record(caller=caller, backend=backend, model=model, outcome="error",
               latency_s=round(time.monotonic() - t0, 2),
               error=f"{type(e).__name__}: {e}", prompt_text=prompt_text,
               **(row_extra or {}))
        raise
    latency = round(time.monotonic() - t0, 2)
    status = getattr(resp, "status_code", None)
    facts = _reply_facts(backend, resp) if (status or 200) < 400 else {}
    if status is not None and status >= 400:
        outcome, err = "error", f"HTTP {status}"
    elif facts.get("reply_chars") == 0:
        outcome, err = "error", "empty reply"
    else:
        outcome, err = "ok", None
    record(caller=caller, backend=backend, model=model, outcome=outcome,
           latency_s=latency, http_status=status, error=err,
           prompt_text=prompt_text, **facts, **(row_extra or {}))
    return resp


def call(caller: str | None, backend: str, model: str | None, fn, *,
         prompt_text: str | None = None, row_extra: dict | None = None):
    """The door for a caller that does its own HTTP (urllib, an injected opener):
    fn() makes the request and returns the parsed JSON reply. Timed, recorded
    with the same schema as post(), re-raised on failure."""
    caller = caller or _caller_from_stack()
    t0 = time.monotonic()
    try:
        d = fn()
    except Exception as e:  # noqa: BLE001
        record(caller=caller, backend=backend, model=model, outcome="error",
               latency_s=round(time.monotonic() - t0, 2),
               error=f"{type(e).__name__}: {e}", prompt_text=prompt_text,
               **(row_extra or {}))
        raise
    facts = _facts_from_dict(d)
    outcome, err = ("error", "empty reply") if facts.get("reply_chars") == 0 else ("ok", None)
    record(caller=caller, backend=backend, model=model, outcome=outcome,
           latency_s=round(time.monotonic() - t0, 2), error=err,
           prompt_text=prompt_text, **facts, **(row_extra or {}))
    return d


def _read_json(opened) -> dict:
    """json from an urllib-style response (a context manager with .read())."""
    with opened as r:
        return json.loads(r.read().decode("utf-8"))


def _selftest() -> int:
    print("core/llm_door.py --selftest")
    print(f"  provenance file      {PROVENANCE} exists={PROVENANCE.exists()}")
    try:
        import core.groq_backend as gb
        src = inspect.getsource(gb)
        print(f"  groq_backend legs    {'LIVE ' if 'llm_door.post(' in src else 'INERT'} (legs call llm_door.post)")
    except Exception as e:  # noqa: BLE001
        print(f"  groq_backend legs    UNKNOWN ({type(e).__name__}: {e})")
    try:
        import core.brain as br
        print(f"  brain                {'LIVE ' if 'llm_door.post(' in inspect.getsource(br) else 'INERT'}")
    except Exception as e:  # noqa: BLE001
        print(f"  brain                UNKNOWN ({type(e).__name__}: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else 0)
