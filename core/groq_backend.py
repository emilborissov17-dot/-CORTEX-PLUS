#!/usr/bin/env python3
"""
groq_backend.py — LLM backend с 4-степенен fallback chain
==========================================================
Ред на опити:
  1. Groq       (llama-3.3-70b-versatile)    — бърз, безплатен
  2. Cerebras   (llama-3.3-70b)              — cloud.cerebras.ai
  3. OpenRouter (deepseek/deepseek-r1:free)  — openrouter.ai
  4. Gemini     (gemini-2.0-flash)           — 1500 req/day безплатно

Ollama беше премахнат от веригата (2026-07-04) — локално няма нито един
pull-нат модел ("Ollama: няма налични модели"), т.е. беше мъртъв safety
net, който само маскираше AllBackendsFailedError. По-добре да гърми
ясно, отколкото тихо да минава през несъществуващ backend.

При rate limit → веднага следващ backend, БЕЗ дълго чакане.
Cooldown 60s на backend при rate limit — после се опитва пак.

При изчерпване на всички backends → вдига AllBackendsFailedError,
която caller-ите могат да уловят и да маркират snapshot с
needs_reanalysis: True за приоритетен повторен анализ.

УПОТРЕБА: Drop-in replacement, API не се променя.
  from core.groq_backend import call_groq, AllBackendsFailedError
  result = call_groq(prompt, max_tokens=800)

.env:
  GROQ_API_KEY=gsk_...
  CEREBRAS_API_KEY=csk_...
  OPENROUTER_API_KEY=sk-or-...
  GEMINI_API_KEY=AIza...
"""

import os
import re
import time
import threading
import requests
from pathlib import Path

# ---------------------------------------------------------------------------
# URLs и модели
# ---------------------------------------------------------------------------

GROQ_API_URL    = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL      = "llama-3.3-70b-versatile"

CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL   = "gpt-oss-120b"   # reasoning model; "zai-glm-4.7" е алтернатива

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL   = "nvidia/nemotron-3-super-120b-a12b:free"  # 120B, верифициран безплатен

GEMINI_API_URL  = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

OLLAMA_URL      = "http://localhost:11434/api/chat"
OLLAMA_LIST_URL = "http://localhost:11434/api/tags"
OLLAMA_PREFERRED = [
    "qwen3:8b", "qwen3:1.7b", "qwen2.5:7b",
    "qwen2.5:3b", "llama3:8b", "mistral:7b",
]

# ---------------------------------------------------------------------------
# Custom exception — raised when every backend is exhausted
# ---------------------------------------------------------------------------

class AllBackendsFailedError(RuntimeError):
    """Raised when the full fallback chain (Groq→Cerebras→OpenRouter→Gemini→Ollama)
    has been exhausted without a successful response.  Callers that write
    snapshots should catch this and set needs_reanalysis=True on the output."""
    pass


# Cooldown при rate limit:
# - При първи rate limit → 60s (може да е временен)
# - При втори rate limit → 600s (session blackout — не губим 2min/ос)
_COOLDOWN_SECS_FIRST  = 60
_COOLDOWN_SECS_REPEAT = 600   # 10 минути session blackout
_cooldowns:     dict = {}
_cooldown_hits: dict = {}     # брои колко пъти е hit-нат всеки backend
_cd_lock = threading.Lock()

# Adaptive sleep — overridden by body_scanner directives at cycle start
_SLEEP_SECS: float = 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_key(name: str) -> str:
    """Зарежда API ключ от environment или .env файл."""
    key = os.environ.get(name, "")
    if not key:
        for candidate in [
            Path(__file__).resolve().parents[1] / ".env",
            Path(__file__).resolve().parents[2] / ".env",
        ]:
            if candidate.exists():
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    if line.startswith(name + "="):
                        key = line.split("=", 1)[1].strip()
                        break
            if key:
                break
    return key


def _system_msg() -> str:
    p = Path(__file__).resolve().parent / "cortex_system_prompt.txt"
    return p.read_text(encoding="utf-8") if p.exists() else "You are CORTEX++ AGI."


def _is_cooling(name: str) -> bool:
    with _cd_lock:
        return time.time() < _cooldowns.get(name, 0)


def _set_cooldown(name: str) -> None:
    with _cd_lock:
        hits = _cooldown_hits.get(name, 0) + 1
        _cooldown_hits[name] = hits
        secs = _COOLDOWN_SECS_REPEAT if hits > 1 else _COOLDOWN_SECS_FIRST
        _cooldowns[name] = time.time() + secs
    print(f"  [LLM] {name} cooldown {secs}s (hit #{hits})")


def _get_ollama_model():
    try:
        r = requests.get(OLLAMA_LIST_URL, timeout=5)
        r.raise_for_status()
        available = {m["name"] for m in r.json().get("models", [])}
        for preferred in OLLAMA_PREFERRED:
            if preferred in available:
                return preferred
        return next(iter(available)) if available else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Backend извиквания
# ---------------------------------------------------------------------------

def _call_groq(prompt: str, max_tokens: int):
    key = _load_key("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY не е намерен")

    print("  [LLM] Groq llama-3.3-70b...")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _system_msg()},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens": max_tokens,
    }
    time.sleep(_SLEEP_SECS)  # adaptive: set by body_scanner directives (default 2s)
    r = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=(10, 60))

    if r.status_code == 429:
        _set_cooldown("groq")
        raise RuntimeError("Groq rate limit")

    r.raise_for_status()
    choice = r.json()["choices"][0]
    return choice["message"]["content"], {"finish_reason": choice.get("finish_reason")}


def _call_cerebras(prompt: str, max_tokens: int):
    key = _load_key("CEREBRAS_API_KEY")
    if not key:
        raise ValueError("CEREBRAS_API_KEY не е намерен")

    print(f"  [LLM] Cerebras {CEREBRAS_MODEL}...")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": CEREBRAS_MODEL,
        "messages": [
            {"role": "system", "content": _system_msg()},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens": max_tokens,
    }
    time.sleep(_SLEEP_SECS)
    r = requests.post(CEREBRAS_API_URL, headers=headers, json=payload, timeout=(10, 60))

    if r.status_code == 429:
        _set_cooldown("cerebras")
        raise RuntimeError("Cerebras rate limit")

    r.raise_for_status()
    choice = r.json()["choices"][0]
    msg = choice["message"]
    # gpt-oss-120b / zai-glm-4.7 са reasoning модели: отговорът е в "content",
    # "reasoning" е вътрешното мислене. При твърде нисък max_tokens "content"
    # може да липсва — в такъв случай fallback-ваме към "reasoning".
    #
    # ВАЖНО: точно този fallback е причината parser-ите да получават суров
    # reasoning текст ("The user asks: ...", "done thinking."). Не го махаме
    # (по-добре нещо, отколкото нищо), но го МАРКИРАМЕ в meta, за да може
    # core/llm_json.py да разпознае случая и да го третира като TRUNCATED,
    # вместо да го бърка с "моделът върна боклук".
    content = msg.get("content") or ""
    used_reasoning_fallback = False
    if not content.strip():
        content = msg.get("reasoning") or ""
        used_reasoning_fallback = bool(content.strip())
    if not content.strip():
        raise ValueError(f"Cerebras {CEREBRAS_MODEL}: празен отговор (content и reasoning са празни)")
    return content, {
        "finish_reason": choice.get("finish_reason"),
        "used_reasoning_fallback": used_reasoning_fallback,
    }


def _call_openrouter(prompt: str, max_tokens: int):
    key = _load_key("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPENROUTER_API_KEY не е намерен")

    print(f"  [LLM] OpenRouter {OPENROUTER_MODEL}...")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/cortex-agi",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _system_msg()},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens": max_tokens,
    }
    time.sleep(_SLEEP_SECS)
    r = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=(10, 90))

    if r.status_code == 429:
        _set_cooldown("openrouter")
        raise RuntimeError("OpenRouter rate limit")

    r.raise_for_status()
    choice = r.json()["choices"][0]
    content = choice["message"]["content"] or ""
    # Някои OpenRouter модели могат да връщат <think>...</think> блокове.
    # (core/llm_json.strip_reasoning прави същото и покрива още варианти —
    # тук го оставяме за callers, които не минават през llm_json.)
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return content, {"finish_reason": choice.get("finish_reason")}


def _call_gemini(prompt: str, max_tokens: int):
    key = _load_key("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY не е намерен")

    print("  [LLM] Gemini 2.0-flash...")
    url = f"{GEMINI_API_URL}?key={key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    time.sleep(_SLEEP_SECS)
    r = requests.post(url, json=payload, timeout=(10, 60))

    if r.status_code == 429:
        _set_cooldown("gemini")
        raise RuntimeError("Gemini rate limit")

    r.raise_for_status()
    candidates = r.json().get("candidates", [])
    if not candidates:
        raise ValueError("Gemini: празен отговор")
    cand = candidates[0]
    # Gemini казва "MAX_TOKENS" там, където OpenAI-съвместимите казват "length".
    # Нормализираме към "length", за да има llm_json един-единствен признак.
    raw_reason = (cand.get("finishReason") or "").upper()
    finish_reason = "length" if raw_reason == "MAX_TOKENS" else raw_reason.lower() or None
    return cand["content"]["parts"][0]["text"], {"finish_reason": finish_reason}


def _call_ollama(prompt: str, max_tokens: int):
    model = _get_ollama_model()
    if not model:
        raise RuntimeError("Ollama: няма налични модели")

    print(f"  [LLM] Ollama {model}...")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_msg()},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "think": False,
        "options": {"num_predict": max_tokens, "num_ctx": 2048},
        "keep_alive": 0,
    }
    r = requests.post(OLLAMA_URL, json=payload, timeout=(10, 120))
    r.raise_for_status()
    body = r.json()
    content = body["message"]["content"]
    # Strip <think>...</think> блок (qwen3 reasoning mode)
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    # Ollama: done_reason == "length" при изчерпан num_predict.
    return content, {"finish_reason": body.get("done_reason")}


# ---------------------------------------------------------------------------
# Публичен интерфейс — API не се променя
# ---------------------------------------------------------------------------

def call_groq_meta(prompt: str, max_tokens: int = 1024) -> tuple:
    """
    Fallback chain: Groq → Cerebras → OpenRouter → Gemini

    Връща (content, meta), където meta съдържа:
      backend                 — кой backend отговори ("Groq", "Cerebras", ...)
      finish_reason           — "length" ако отговорът е отрязан (нормализирано
                                през всички providers), иначе "stop"/None
      used_reasoning_fallback — True само за Cerebras, когато "content" е бил
                                празен и сме взели суровия "reasoning" текст

    core/llm_json.py ползва точно тези две полета, за да различи "отрязан
    отговор" (→ retry) от "моделът върна боклук" (→ грешка).

    При rate limit на даден backend → веднага следващ (без дълго чакане).
    Backend с активен cooldown се прескача докато cooldown-ът не изтече.
    При изчерпване на всички → вдига AllBackendsFailedError (subclass на
    RuntimeError, съвместима с всички съществуващи except-клаузи).
    """
    backends = [
        ("Groq",       "groq",       _call_groq),
        ("Cerebras",   "cerebras",   _call_cerebras),
        ("OpenRouter", "openrouter", _call_openrouter),
        ("Gemini",     "gemini",     _call_gemini),
    ]

    last_error = None
    for label, key, fn in backends:
        if _is_cooling(key):
            print(f"  [LLM] {label} in cooldown -- skipping")
            continue
        try:
            result, meta = fn(prompt, max_tokens)
            if result and result.strip():
                meta = dict(meta or {})
                meta["backend"] = label
                if meta.get("finish_reason") == "length":
                    print(f"[LLM] {label} OK (finish_reason=length — ОТРЯЗАН отговор)")
                elif meta.get("used_reasoning_fallback"):
                    print(f"[LLM] {label} OK (внимание: празен content, ползван е reasoning)")
                else:
                    print(f"[LLM] {label} OK")
                return result, meta
            raise ValueError(f"Empty response from {label}")
        except Exception as e:
            print(f"  [LLM] {label} failed ({e}) -- next...")
            last_error = e

    raise AllBackendsFailedError(
        f"All LLM backends failed (Groq/Cerebras/OpenRouter/Gemini). "
        f"Last error: {last_error}"
    )


def call_groq(prompt: str, max_tokens: int = 1024) -> str:
    """Обратно-съвместим wrapper: връща само текста (без meta).

    Съществуващите caller-и не се променят. Caller-ите, които парсват JSON,
    трябва да минават през core.llm_json (което ползва call_groq_meta и вижда
    finish_reason).
    """
    content, _meta = call_groq_meta(prompt, max_tokens)
    return content


def call_groq_safe(prompt: str, max_tokens: int = 1024) -> str:
    try:
        return call_groq(prompt, max_tokens)
    except AllBackendsFailedError:
        raise  # preserve specific type so callers can set needs_reanalysis
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}") from e


class GroqBackend:
    def predict(self, input_data):
        return call_groq(str(input_data))

    def call(self, prompt, max_tokens=1024):
        return call_groq(prompt, max_tokens)