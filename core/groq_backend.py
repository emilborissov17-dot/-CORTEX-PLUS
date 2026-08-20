#!/usr/bin/env python3
"""
groq_backend.py — LLM backend с 4-степенен fallback chain
==========================================================
Ред на опити:
  1. Groq       (llama-3.3-70b-versatile)    — бърз, безплатен
  2. Cerebras   (llama-3.3-70b)              — cloud.cerebras.ai
  3. OpenRouter (deepseek/deepseek-r1:free)  — openrouter.ai
  4. Gemini     (gemini-2.0-flash)           — 1500 req/day безплатно

Ollama беше премахнат от веригата (2026-07-04) като ТИХ safety net, който
маскираше AllBackendsFailedError. Това остава в сила: локалният модел НЕ е
обикновена стъпка във веригата и НЕ маскира тихо нищо.
ИЗКЛЮЧЕНИЕ (30 юли 2026, задача #16, изрично одобрено от Емил): локалният
модел се връща като ЯВНА последна инстанция САМО когато и четирите облачни
backend-а са в cooldown (пълен blackout). Отговорът е маркиран
backend="local:<model>", degraded=True — видимо, не тихо. Целта е жива-но-
деградирала оса вместо мъртва (LLM_FAILED) при едновременен blackout.

При rate limit → веднага следващ backend, БЕЗ дълго чакане.
Cooldown прогресивен с капак 180s (60/120/180) — край на 10-мин blackout,
който гладеше цикъла; hit-броячът се нулира при успешен отговор.

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
import json
from datetime import datetime, timezone
import threading
import requests
from pathlib import Path

# ---------------------------------------------------------------------------
# URLs и модели
# ---------------------------------------------------------------------------

GROQ_API_URL    = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL      = "openai/gpt-oss-120b"

CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL   = "gpt-oss-120b"   # reasoning model; "zai-glm-4.7" е алтернатива

# Cerebras budget transform — виж _effective_budget() по-долу.
# gpt-oss-120b е reasoning модел: reasoning токените се броят В max_completion_tokens
# (Cerebras docs: "including reasoning tokens"), т.е. мисленето изяжда бюджета
# ПРЕДИ payload-а. Call site-овете тук са оразмерени за llama-3.3-70b (80..4096),
# затова при Cerebras ги мащабираме и — по-важното — слагаме ПОД.
CEREBRAS_BUDGET_MULT  = float(os.environ.get("CEREBRAS_BUDGET_MULT",  "3"))
CEREBRAS_BUDGET_FLOOR = int(os.environ.get("CEREBRAS_BUDGET_FLOOR", "1500"))
CEREBRAS_BUDGET_CAP   = int(os.environ.get("CEREBRAS_BUDGET_CAP",   "8192"))
# low | medium | high (Cerebras default за gpt-oss-120b е "medium")
CEREBRAS_REASONING_EFFORT = os.environ.get("CEREBRAS_REASONING_EFFORT", "low")

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL   = "nvidia/nemotron-3-super-120b-a12b:free"  # 120B, верифициран безплатен

GEMINI_API_URL  = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"

# Ollama константите и _call_ollama/_get_ollama_model са премахнати (2026-07-13).
# Ollama излезе от веригата на 2026-07-04 (виж docstring-а горе) — оттогава кодът
# беше мъртъв: нищо не го викаше, но URL-ите стояха и подвеждаха, че локален
# backend още е опция. По конвенция (CLAUDE.md) Ollama няма място в живия цикъл.

# ---------------------------------------------------------------------------
# Custom exception — raised when every backend is exhausted
# ---------------------------------------------------------------------------

class AllBackendsFailedError(RuntimeError):
    """Raised when the full fallback chain (Groq→Cerebras→OpenRouter→Gemini→Ollama)
    has been exhausted without a successful response.  Callers that write
    snapshots should catch this and set needs_reanalysis=True on the output."""
    pass


# Cooldown при rate limit — ПРОГРЕСИВЕН, но с КАПАК (30 юли 2026, задача #16).
# Старо: 2-ри hit → 600s "session blackout". Диагнозата показа, че точно това
# причинява LLM-глада: Groq пада 2 пъти рано → изпада за 10 мин → товарът се
# излива на другите 3 → каскаден blackout → осите връщат LLM_FAILED. Ново: 60/120/180s
# с капак 180s — backend се възстановява В РАМКИТЕ на цикъла вместо да изпада за 10 мин.
# При успешен отговор hit-броячът се нулира (виж call_groq_meta), за да не се третира
# вечно като хронично падащ.
_COOLDOWN_SECS_FIRST = 60
_COOLDOWN_SECS_MAX   = 180
_cooldowns:     dict = {}
_cooldown_hits: dict = {}     # брои колко пъти е hit-нат всеки backend
_cd_lock = threading.Lock()

# Local last-resort brain (Ollama HTTP :11434) — качва се САМО когато и четирите
# облачни backend-а са в cooldown (пълен blackout). Изрично решение на Емил (30 юли
# 2026) да се отпусне конвенцията "Ollama мъртъв в scoring" ЗА ПОСЛЕДНАТА ИНСТАНЦИЯ:
# жива-но-деградирала оса > мъртва оса. Отговорът се маркира degraded=True/backend=
# "local:<model>", за да е видно в самомодела, че е локален, не облачен.
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
        secs = min(_COOLDOWN_SECS_FIRST * hits, _COOLDOWN_SECS_MAX)  # 60/120/180, capped
        _cooldowns[name] = time.time() + secs
    print(f"  [LLM] {name} cooldown {secs}s (hit #{hits})")


def _clear_cooldown(name: str) -> None:
    """A backend answered → it's healthy again. Reset its hit count so a past
    rate-limit streak doesn't keep escalating its future cooldowns."""
    with _cd_lock:
        _cooldown_hits.pop(name, None)
        _cooldowns.pop(name, None)


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


def _effective_budget(max_tokens: int) -> int:
    """Бюджетът, който реално пращаме на Cerebras.

    ПОДЪТ е същината, не множителят: 3 x 80 = 240 пак не стига дори за
    мисленето. Подът гарантира, че reasoning-ът има място да СВЪРШИ, преди
    payload-ът изобщо да започне — независимо колко малко е поискал call
    site-ът. Капът ни държи далеч под 32k тавана на free tier-а.
    """
    scaled = int(max_tokens * CEREBRAS_BUDGET_MULT)
    return min(CEREBRAS_BUDGET_CAP, max(CEREBRAS_BUDGET_FLOOR, scaled))


def _call_cerebras(prompt: str, max_tokens: int):
    key = _load_key("CEREBRAS_API_KEY")
    if not key:
        raise ValueError("CEREBRAS_API_KEY не е намерен")

    print(f"  [LLM] Cerebras {CEREBRAS_MODEL}...")

    budget = _effective_budget(max_tokens)
    if budget >= 2 * max_tokens:
        reason = "floor" if budget == CEREBRAS_BUDGET_FLOOR else f"x{CEREBRAS_BUDGET_MULT:g}"
        print(f"  [CEREBRAS] budget {max_tokens}->{budget} ({reason})")

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
        # Документираното име при Cerebras (max_tokens се приема само като
        # legacy alias). Броят се И reasoning токените — оттам транформът горе.
        "max_completion_tokens": budget,
        "reasoning_effort": CEREBRAS_REASONING_EFFORT,
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


def _call_local(prompt: str, max_tokens: int):
    """Last-resort sovereign brain over Ollama HTTP (:11434). Called ONLY when all
    four cloud backends are cooling. Returns (content, meta) or raises. No external
    API — this is the local model, deliberately, so a full-blackout cycle stays alive."""
    # 15 Aug 2026 — измерено на машината (scripts/test_local_brain.py): СТУДЕНО
    # първо повикване на qwen3:8b върху 4GB VRAM не се вмества в 60-90s, а топлите
    # минават за ~48s. С 60s таймаут последната инстанция мълчеше точно когато е
    # най-нужна — при пълно затъмнение на облака. keep_alive държи модела зареден
    # между стъпките, а таймаутът е за студен старт.
    num_predict = max(64, min(int(max_tokens), 1024))
    body = {"model": _LOCAL_MODEL, "stream": False,
            "messages": [{"role": "system", "content": _system_msg()},
                         {"role": "user", "content": prompt}],
            "keep_alive": "30m",
            "options": {"temperature": 0.4, "num_predict": num_predict}}
    try:
        r = requests.post(f"{_OLLAMA_URL}/api/chat", json=body, timeout=300)
    except requests.exceptions.Timeout:
        raise RuntimeError(f"local model {_LOCAL_MODEL} cold-start >300s")
    if r.status_code != 200:
        raise RuntimeError(f"local model HTTP {r.status_code}")
    content = ((r.json().get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("empty response from local model")
    return content, {"finish_reason": "stop", "degraded": True}


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

    def _log_provenance(backend_label: str, prompt_text: str, content_text: str):
        """PROVENANCE (14 Aug 2026): every verdict the system records used to be
        anonymous — no trace of WHICH model produced it, though the chain falls
        through 4 providers many times per cycle. E7 (calibrated ensemble) and E2
        (LLM-vs-data grounding) both need this join key. Append-only, fail-open,
        5MB rotation; prompt is stored as a hash + head, never in full."""
        try:
            import hashlib as _hl
            _pf = Path(__file__).resolve().parents[1] / "memory" / "llm_provenance.jsonl"
            _pf.parent.mkdir(parents=True, exist_ok=True)
            if _pf.exists() and _pf.stat().st_size > 5_000_000:
                _pf.replace(_pf.with_suffix(".jsonl.1"))
            with open(_pf, "a", encoding="utf-8") as _fh:
                _fh.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "backend": backend_label,
                    "prompt_sha1": _hl.sha1(prompt_text.encode("utf-8", "ignore")).hexdigest()[:12],
                    "prompt_head": prompt_text[:80],
                    "reply_chars": len(content_text or ""),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass  # bookkeeping must never break the chain

    def _model_for(backend_label: str) -> str:
        """Which model actually answered — for provenance.

        Added 17 Aug 2026: meta already said WHICH BACKEND replied but never
        which model, so anything archiving a verdict could record "Groq" and not
        "llama-3.3-70b-versatile". Gemini's name is parsed out of GEMINI_API_URL
        (.../models/gemini-2.0-flash:generateContent) rather than duplicated into
        a constant, so the two cannot drift apart.
        """
        if backend_label == "Groq":
            return GROQ_MODEL
        if backend_label == "Cerebras":
            return CEREBRAS_MODEL
        if backend_label == "OpenRouter":
            return OPENROUTER_MODEL
        if backend_label == "Gemini":
            try:
                return GEMINI_API_URL.rsplit("/", 1)[-1].split(":")[0]
            except Exception:
                return "gemini (model in GEMINI_API_URL)"
        return backend_label

    last_error = None
    for label, key, fn in backends:
        if _is_cooling(key):
            print(f"  [LLM] {label} in cooldown -- skipping")
            continue
        try:
            result, meta = fn(prompt, max_tokens)
            if result and result.strip():
                _clear_cooldown(key)  # healthy again → reset its escalation
                meta = dict(meta or {})
                meta["backend"] = label
                meta["model"] = _model_for(label)
                if meta.get("finish_reason") == "length":
                    print(f"[LLM] {label} OK (finish_reason=length — ОТРЯЗАН отговор)")
                elif meta.get("used_reasoning_fallback"):
                    print(f"[LLM] {label} OK (внимание: празен content, ползван е reasoning)")
                else:
                    print(f"[LLM] {label} OK")
                _log_provenance(label, prompt, result)
                return result, meta
            raise ValueError(f"Empty response from {label}")
        except Exception as e:
            print(f"  [LLM] {label} failed ({e}) -- next...")
            last_error = e

    # LAST RESORT: all four cloud backends failed/cooling → local sovereign brain,
    # so the axis stays alive (degraded) instead of dying with LLM_FAILED. Clearly
    # labelled so the self-model knows this answer was local. (Task #16; Emil-approved
    # relaxation of the "no Ollama in scoring" convention for this blackout case only.)
    try:
        result, meta = _call_local(prompt, max_tokens)
        meta = dict(meta or {})
        meta["backend"] = f"local:{_LOCAL_MODEL}"
        meta["model"] = _LOCAL_MODEL
        print(f"[LLM] ALL cloud backends down -> LOCAL {_LOCAL_MODEL} OK (DEGRADED)")
        _log_provenance(f"local:{_LOCAL_MODEL}", prompt, result)
        return result, meta
    except Exception as e:
        print(f"  [LLM] local last-resort failed ({e})")
        last_error = e

    raise AllBackendsFailedError(
        f"All LLM backends failed (Groq/Cerebras/OpenRouter/Gemini + local). "
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