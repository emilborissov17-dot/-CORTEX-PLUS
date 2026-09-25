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

# ── TIMEOUTS FROM MEASUREMENT (24 Sep 2026, task #19 c) ──────────────────────
# Per leg: max(FLOOR_S, p95 of that leg's ok latencies over the last NIGHTS
# nights x FACTOR), recomputed from provenance into TIMEOUTS by recompute(),
# which fast_cycle_runner calls at boot. Until a value is measured the SEED
# applies (the 24 Sep figures). The door ENFORCES it: post() replaces whatever
# timeout the caller passed for a known leg, so no caller keeps a 60-120 s literal.
# A local model is "cold" on its first call in this process (LOCAL_COLD_S) and
# warm after; provenance cannot tell cold from warm until it carries
# load_duration, so the cold figure stays a seed.
TIMEOUTS = BASE / "memory" / "llm_timeouts.json"
FLOOR_S, FACTOR, NIGHTS = 8.0, 1.5, 7
SEED = {"Groq": 25.0, "OpenRouter": 45.0, "NVIDIA": 45.0, "Gemini": 45.0, "local": 60.0}
LOCAL_COLD_S = 300.0
CONNECT_S = 10.0
TRUNCATED = ("length", "MAX_TOKENS")
_warm: set = set()
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
        # task #19 e: what a model switch costs is on the row, in seconds
        for k in ("load_duration", "prompt_eval_duration", "eval_duration"):
            if isinstance(d.get(k), (int, float)):
                out[k + "_s"] = round(d[k] / 1e9, 3)
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
           prompt_text: str | None = None, batched: bool = True, **extra) -> dict:
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
    if outcome == "ok":
        for k in [k for k in _ok_cache if k[1] == backend]:
            _ok_cache.pop(k, None)
    try:
        PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
        if PROVENANCE.exists() and PROVENANCE.stat().st_size > _ROTATE_BYTES:
            PROVENANCE.replace(PROVENANCE.with_suffix(".jsonl.1"))
        from core.durable import append_json as _append_json
        _append_json(PROVENANCE, row, batched=batched)
    except Exception:
        pass
    return row


# ── DEAD LEGS LEAVE THE LADDER BY EVIDENCE (24 Sep 2026, task #19 d) ────────
# A leg with 0 ok rows in the last 24 h of provenance is skipped. Once per night
# (calendar date, across every process - LEG_STATE) its first call goes through as
# a PROBE, whose own row is the new evidence; after that the leg is skipped for the
# rest of the night, and ONE row per leg per night says so.
LEG_STATE = BASE / "memory" / "llm_leg_state.json"
DEAD_WINDOW_H = 24
SKIPPED = "leg skipped: 0 ok/24h"
_ok_cache: dict = {}
_alive: set = set()          # legs that answered ok in this process


def note_ok(backend: str) -> None:
    """The ladder got a usable answer from this leg: it is alive, whatever the
    cached count says (a successful probe must not be skipped on the next call)."""
    _alive.add(backend)


def ok_count(backend: str, now: datetime | None = None, hours: int = DEAD_WINDOW_H) -> int:
    """ok rows for this backend label in the last `hours`. Cached for 10 min."""
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    key = (str(PROVENANCE), backend, hours)
    hit = _ok_cache.get(key)
    if hit and (now - hit[0]).total_seconds() < 600:
        return hit[1]
    cut = (now - timedelta(hours=hours)).isoformat()
    n = 0
    try:
        for line in PROVENANCE.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("backend") == backend and str(r.get("ts", "")) >= cut \
                    and r.get("outcome", "ok") == "ok" and r.get("finish_reason") not in TRUNCATED:
                n += 1
    except Exception:
        pass
    _ok_cache[key] = (now, n)
    return n


def leg_gate(backend: str, model: str | None = None, now: datetime | None = None) -> str:
    """"use", "probe" or "skip" for a cloud leg. Writes LEG_STATE and, on the
    first skip of a night, one provenance row. Never raises (fails open: "use")."""
    now = now or datetime.now(timezone.utc)
    night = now.date().isoformat()
    try:
        if backend in _alive or ok_count(backend, now) > 0:
            return "use"
        try:
            state = json.loads(LEG_STATE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
        leg = state.setdefault(backend, {})
        if leg.get("probed_night") != night:
            leg["probed_night"] = night
            verdict = "probe"
        else:
            verdict = "skip"
            if leg.get("skip_row_night") != night:
                leg["skip_row_night"] = night
                record(caller="ladder", backend=backend, model=model, outcome="refused",
                       error=SKIPPED, batched=False)   # rare; on disk at once
        LEG_STATE.parent.mkdir(parents=True, exist_ok=True)
        LEG_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return verdict
    except Exception:
        return "use"


# ── THE CYCLE NEVER LOADS A MODEL (24 Sep 2026, task #8 part 1) ───────────────
# Inside a cycle a local request goes out only if its model is already resident
# (GET /api/ps). If not, the row says outcome=refused "warm core absent" and
# WarmCoreAbsent is raised - the caller degrades; nothing is loaded.
class WarmCoreAbsent(RuntimeError):
    pass


_ps_cache: dict = {}


def _resident(base: str) -> set | None:
    """Model names resident in the Ollama at `base`, or None if it cannot be asked."""
    hit = _ps_cache.get(base)
    if hit and time.monotonic() - hit[0] < 5:
        return hit[1]
    try:
        import requests
        names = {m.get("name") for m in (requests.get(base + "/api/ps", timeout=3).json().get("models") or [])}
    except Exception:
        return None
    _ps_cache[base] = (time.monotonic(), names)
    return names


def _base_of(url: str | None) -> str:
    try:
        from urllib.parse import urlsplit
        u = urlsplit(url or "")
        if u.scheme and u.netloc:
            return f"{u.scheme}://{u.netloc}"
    except Exception:
        pass
    return os.environ.get("CORTEX_OLLAMA_URL", "http://localhost:11434").rstrip("/")


def _require_warm(caller, backend: str, model: str | None, url: str | None, prompt_text) -> None:
    try:
        from core import model_window as _mw
        if not _mw.in_cycle():
            return
        absent = _mw.WARM_CORE_ABSENT
    except Exception:
        return
    names = _resident(_base_of(url))
    if names is not None and (model or backend[6:]) in names:
        return
    why = absent + ("" if names is not None else " (Ollama /api/ps did not answer)")
    record(caller=caller, backend=backend, model=model, outcome="refused", latency_s=0.0,
           error=why, prompt_text=prompt_text, batched=False)
    raise WarmCoreAbsent(f"{why}: {model or backend} is not resident; the cycle does not load models")


def _family(backend: str) -> str:
    return "local" if str(backend).startswith("local:") else str(backend)


def _p95(xs: list) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]


def recompute(provenance: Path | None = None, out: Path | None = None,
              now: datetime | None = None) -> dict:
    """Measured timeouts from the last NIGHTS nights of ok, untruncated rows.
    Keys: every backend label seen, plus its family ("local" for local:*).
    Writes `out` (default TIMEOUTS) and returns the table. Never raises."""
    import collections
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    cut = (now - timedelta(days=NIGHTS)).isoformat()
    lat = collections.defaultdict(list)
    try:
        for line in (provenance or PROVENANCE).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if str(r.get("ts", "")) < cut or r.get("outcome", "ok") != "ok":
                continue
            if r.get("finish_reason") in TRUNCATED:
                continue
            v = r.get("latency_s") if r.get("latency_s") is not None else r.get("sec")
            if not v:
                continue
            b = str(r.get("backend"))
            lat[b].append(float(v))
            if _family(b) != b:
                lat[_family(b)].append(float(v))
    except Exception:
        pass
    table = {"computed_utc": now.isoformat(), "floor_s": FLOOR_S, "factor": FACTOR,
             "nights": NIGHTS, "local_cold_s": LOCAL_COLD_S, "legs": {}}
    for k, xs in lat.items():
        p = _p95(xs)
        table["legs"][k] = {"timeout_s": round(max(FLOOR_S, p * FACTOR), 1),
                            "p95_ok_s": round(p, 1), "n": len(xs)}
    try:
        (out or TIMEOUTS).parent.mkdir(parents=True, exist_ok=True)
        (out or TIMEOUTS).write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return table


def timeout_for(backend: str) -> float | None:
    """Wall timeout for this leg: measured if TIMEOUTS has it, else the SEED.
    None for a backend the table does not govern (the caller's value stands)."""
    legs = {}
    try:
        legs = json.loads(TIMEOUTS.read_text(encoding="utf-8")).get("legs") or {}
    except Exception:
        pass
    for key in (str(backend), _family(backend)):
        if key in legs:
            return float(legs[key]["timeout_s"])
    return SEED.get(_family(backend))


def _enforced_timeout(backend: str, model: str | None, asked):
    t = timeout_for(backend)
    if t is None:
        return asked
    if _family(backend) == "local" and (model or backend) not in _warm:
        t = max(t, LOCAL_COLD_S)
    return (min(CONNECT_S, t), t)


def post(caller: str | None, backend: str, model: str | None, url: str, *,
         prompt_text: str | None = None, row_extra: dict | None = None, **kw):
    """requests.post through the door. Returns the Response; re-raises what
    requests raises. Exactly one provenance row on every path."""
    # Imported per call, not at module import: a module-level binding would keep
    # whatever `requests` was in sys.modules the first time this module loaded
    # (a test's stand-in, once), for the life of the process.
    import requests
    caller = caller or _caller_from_stack()
    if _family(backend) == "local":
        _require_warm(caller, backend, model, url, prompt_text)
    kw["timeout"] = _enforced_timeout(backend, model, kw.get("timeout"))
    if _family(backend) == "local" and isinstance(kw.get("json"), dict):
        # ONE keep_alive policy (config/model_window.json keep_alive_policy)
        try:
            from core import model_window as _mw
            kw["json"] = {**kw["json"], "keep_alive": _mw.keep_alive_policy(model or backend)}
        except Exception:  # noqa: BLE001
            pass
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
    outcome, err = _judge(status, facts)
    if outcome == "ok" and _family(backend) == "local":
        _warm.add(model or backend)
    record(caller=caller, backend=backend, model=model, outcome=outcome,
           latency_s=latency, http_status=status, error=err,
           prompt_text=prompt_text, **facts, **(row_extra or {}))
    _restore_core_after(backend, model, url)
    return resp


def _restore_core_after(backend: str, model: str | None, url: str | None) -> None:
    """Outside a cycle, a local call to any model but the warm core ends with the
    core restored (core.model_window.restore_core). Fail-open: never raises."""
    if _family(backend) != "local":
        return
    try:
        from core import model_window as _mw
        r = _mw.restore_core(model or backend[6:], _base_of(url))
        if r and r.get("reloaded"):
            print(f"  [LOCAL] warm core restored after {model}: {r.get('model')} in {r.get('seconds')} s")
    except Exception:
        pass


def _judge(status, facts) -> tuple:
    """A truncated answer is an error, never an ok (task #19 c)."""
    if status is not None and status >= 400:
        return "error", f"HTTP {status}"
    if facts.get("finish_reason") in TRUNCATED:
        return "error", f"truncated (finish_reason={facts.get('finish_reason')})"
    if facts.get("reply_chars") == 0:
        return "error", "empty reply"
    return "ok", None


def call(caller: str | None, backend: str, model: str | None, fn, *,
         prompt_text: str | None = None, row_extra: dict | None = None):
    """The door for a caller that does its own HTTP (urllib, an injected opener):
    fn() makes the request and returns the parsed JSON reply. Timed, recorded
    with the same schema as post(), re-raised on failure."""
    caller = caller or _caller_from_stack()
    if _family(backend) == "local":
        _require_warm(caller, backend, model, None, prompt_text)
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
    outcome, err = _judge(None, facts)
    record(caller=caller, backend=backend, model=model, outcome=outcome,
           latency_s=round(time.monotonic() - t0, 2), error=err,
           prompt_text=prompt_text, **facts, **(row_extra or {}))
    _restore_core_after(backend, model, None)
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
