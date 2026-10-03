#!/usr/bin/env python3
"""
local_llm.py — the system's text model: the LOCAL model, and nothing else.

C-CLOUD-1 (3 Oct 2026, Emil R45): "Нали нямаше да имаме външни LLM-и… и щяхме да работим само
с OpenClaw?" — "Защо го имаме изобщо… защо някой друг да мисли вместо мозъкът на системата?"
Every outside backend (Groq, NVIDIA/Kimi, OpenRouter, Gemini — and Cerebras before them) is
DELETED from this file, with its URLs, keys, cooldowns and ordering. The git history keeps them;
nothing here can reach them. The ladder is the local model over Ollama HTTP (:11434): the 3b,
and the 8b while core/model_window's window is open, each charged to the step's budget by
core/step_budget.

When the local model does not answer, the caller gets AllBackendsFailedError — the same named
failure as before — never invented text.

USE (unchanged names, see the report's rename section):
  from core.local_llm import call_local_llm, AllBackendsFailedError
  result = call_local_llm(prompt, max_tokens=800)
"""

import os
import time
from pathlib import Path

import requests

from core.llm_text import LLMText   # task #29


class AllBackendsFailedError(RuntimeError):
    """Raised when the local model gave no usable answer within the step's budget.
    Callers that write snapshots should catch this and set needs_reanalysis=True."""
    pass


_OLLAMA_URL  = os.environ.get("CORTEX_OLLAMA_URL", "http://localhost:11434")

def _pick_local_model() -> str:
    """14 Aug 2026: body_scan now reports the REAL installed Ollama models.
    Prefer the strongest qwen3 the machine holds; env override wins; fall back
    to the old default. Read at import so one call per process, fail-open."""
    env = os.environ.get("CORTEX_LOCAL_MODEL")
    if env:
        return env
    try:
        import json as _j
        _bs = _j.loads((Path(__file__).resolve().parents[1] / "memory" /
                        "body_scan_latest.json").read_text(encoding="utf-8"))
        models = _bs.get("software", {}).get("ollama_models", []) or []
        for m in models:
            if "qwen3" in str(m):
                return str(m)
        if models:
            return str(models[0])
    except Exception:
        pass
    return "qwen2.5:3b"

_LOCAL_MODEL = _pick_local_model()

# Adaptive sleep — overridden by body_scanner directives at cycle start
_SLEEP_SECS: float = 10.0


def _system_msg() -> str:
    p = Path(__file__).resolve().parent / "cortex_system_prompt.txt"
    return p.read_text(encoding="utf-8") if p.exists() else "You are CORTEX++ AGI."


def _pace() -> float:
    """The body scan's directive (core/llm_pacing) if the cycle set one, else ours."""
    try:
        from core import llm_pacing
        if llm_pacing.SLEEP_SECS is not None:
            return llm_pacing.SLEEP_SECS
    except Exception:
        pass
    return _SLEEP_SECS


def _note_degraded(reason: str) -> None:
    """Tell the running step it is working on a weaker footing than intended.

    Fail-open and quiet about its own failure: the point is to make a degradation
    visible, and a crash here would take down the very call that was trying to
    stay alive. When there is no open step (a script, a selftest) the note has
    nowhere to land, and that is fine — it is said on stdout either way by the
    caller.
    """
    try:
        from core.step_contract import note_degraded_on_current
        note_degraded_on_current(reason)
    except Exception:
        pass


def _call_local_as(model_id: str, prompt: str, max_tokens: int):
    """_call_local for an EXPLICIT model, so the ladder can name its tier.

    The ladder needs to ask for 3b and 8b by name; _call_local asks
    core/model_window for whichever one is currently legal. Both paths exist on
    purpose — a caller with no opinion should get the policy's answer, and the
    ladder, which IS expressing an opinion about tiers, should get what it asked
    for. The window still has the last word: it is consulted for keep_alive, and
    the ladder is only ever handed the 8b tier while the window is open.
    """
    num_predict = max(64, min(int(max_tokens), 1024))
    try:
        from core import model_window as _mw
        model_id = _mw.guard_local(model_id, "local_llm._call_local_as")
        keep_alive = _mw.keep_alive_for(model_id)
    except Exception:
        keep_alive = "30m"
    body = {"model": model_id, "stream": False,
            "messages": [{"role": "system", "content": _system_msg()},
                         {"role": "user", "content": prompt}],
            "keep_alive": keep_alive,
            "options": {"temperature": 0.4, "num_predict": num_predict}}
    try:
        from core import llm_door
        r = llm_door.post(None, f"local:{body.get('model')}", body.get("model"),
                          f"{_OLLAMA_URL}/api/chat", prompt_text=prompt, json=body)  # timeout: llm_door
    except requests.exceptions.Timeout:
        raise RuntimeError(f"local model {model_id} cold-start >300s")
    if r.status_code != 200:
        raise RuntimeError(f"local model HTTP {r.status_code}")
    content = ((r.json().get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("empty response from local model")
    return content, {"finish_reason": "stop"}


def _call_local(prompt: str, max_tokens: int):
    """The local model over Ollama HTTP (:11434), the one core/model_window allows now.
    Returns (content, meta) or raises."""
    # 15 Aug 2026 — измерено на машината (scripts/test_local_brain.py): СТУДЕНО
    # първо повикване на qwen3:8b върху 4GB VRAM не се вмества в 60-90s, а топлите
    # минават за ~48s. С 60s таймаут последната инстанция мълчеше точно когато е
    # най-нужна — при пълно затъмнение на облака. keep_alive държи модела зареден
    # между стъпките, а таймаутът е за студен старт.
    #
    # 22 Aug 2026 — WHICH local model is no longer decided here. core/model_window.py
    # owns residency: 8b is legal only inside one contiguous window per cycle, because
    # /api/ps proved the two models never coexist on 4GB and every alternation pays a
    # full reload out of the running step's ceiling. Outside the window this call is
    # SERVED 3b and the downgrade is recorded there. Fail-open to the old module-level
    # pick: a missing policy must not remove the last resort.
    num_predict = max(64, min(int(max_tokens), 1024))
    model = _LOCAL_MODEL
    keep_alive = "30m"
    try:
        from core import model_window as _mw
        model = _mw.local_model(want_big=True, purpose="local_llm.last_resort")
        keep_alive = _mw.keep_alive_for(model)
    except Exception:
        pass
    body = {"model": model, "stream": False,
            "messages": [{"role": "system", "content": _system_msg()},
                         {"role": "user", "content": prompt}],
            "keep_alive": keep_alive,
            "options": {"temperature": 0.4, "num_predict": num_predict}}
    try:
        from core import llm_door
        r = llm_door.post(None, f"local:{body.get('model')}", body.get("model"),
                          f"{_OLLAMA_URL}/api/chat", prompt_text=prompt, json=body)  # timeout: llm_door
    except requests.exceptions.Timeout:
        raise RuntimeError(f"local model {model} cold-start >300s")
    if r.status_code != 200:
        raise RuntimeError(f"local model HTTP {r.status_code}")
    content = ((r.json().get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("empty response from local model")
    return content, {"finish_reason": "stop"}


def call_local_llm_meta(prompt: str, max_tokens: int = 1024,
                   purpose: str | None = None) -> tuple:
    """The local model, laddered 3b -> 8b (8b only while the window is open), each tier
    abandoned at its slice of the step's budget (core/step_budget).

    Decided (R45): nothing answered -> AllBackendsFailedError, never text
    (test/test_ladder_local_only.py). `purpose` is kept for the callers' signature.
    """
    nonlocal_err: list = []

    def _local_tier(model_id: str):
        def _go():
            try:
                result, meta = _call_local_as(model_id, prompt, max_tokens)
            except Exception as e:                                   # noqa: BLE001
                nonlocal_err.append(e)
                return None
            meta = dict(meta or {})
            meta["backend"] = f"local:{model_id}"
            meta["model"] = model_id
            return result, meta
        return _go

    from core import step_budget as _budget
    from core import model_window as _mw
    _small = _mw.small_model()
    _big = _mw.big_model()
    res = _budget.run_call(
        local_3b=_local_tier(_small),
        # 8b only while the window is open: outside it, loading 8b would evict the
        # pinned 3b mid-step (core/model_window.py).
        local_8b=_local_tier(_big) if _mw.is_open() else None,
    )
    if res.outcome == _budget.OK and res.value is not None:
        return res.value
    last_error = nonlocal_err[-1] if nonlocal_err else None
    _note_degraded("the local model gave no answer within B={:.0f}s ({})".format(res.budget_sec, res.reason))
    print(f"  [LLM] NO ANSWER: {res.reason}")
    raise AllBackendsFailedError(f"The local model gave no answer. Last error: {last_error}")


def _answer_as_llm_text(fn):
    """The ladder's answer leaves as LLMText (task #29, 25 Sep 2026): the legs
    clean the door's marked text with re.sub, which hands back a plain str, so
    the mark is put back here, from the meta of the leg that answered."""
    import functools

    @functools.wraps(fn)
    def wrapped(*a, **k):
        content, meta = fn(*a, **k)
        if isinstance(content, str) and not isinstance(content, LLMText):
            content = LLMText(content, (meta or {}).get("backend"), (meta or {}).get("model"),
                              os.environ.get("CORTEX_STEP"))
        return content, meta
    return wrapped


call_local_llm_meta = _answer_as_llm_text(call_local_llm_meta)


def call_local_llm(prompt: str, max_tokens: int = 1024) -> str:
    """Обратно-съвместим wrapper: връща само текста (без meta).

    Съществуващите caller-и не се променят. Caller-ите, които парсват JSON,
    трябва да минават през core.llm_json (което ползва call_local_llm_meta и вижда
    finish_reason).
    """
    content, _meta = call_local_llm_meta(prompt, max_tokens)
    return content


def call_local_llm_safe(prompt: str, max_tokens: int = 1024) -> str:
    try:
        return call_local_llm(prompt, max_tokens)
    except AllBackendsFailedError:
        raise  # preserve specific type so callers can set needs_reanalysis
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}") from e


class LocalLLM:
    def predict(self, input_data):
        return call_local_llm(str(input_data))

    def call(self, prompt, max_tokens=1024):
        return call_local_llm(prompt, max_tokens)
