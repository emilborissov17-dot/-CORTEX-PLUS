#!/usr/bin/env python3
"""
groq_backend.py — LLM backend с 4-степенен fallback chain
==========================================================
Ред на опити (моделите са верифицирани срещу живите листинги на 20 август 2026;
трите reasoning пътя минават през _reasoning_budget — виж него):
  1. Groq       (openai/gpt-oss-120b)                  — reasoning, бърз, безплатен
  2. Cerebras   (gpt-oss-120b)   DECLARED DEAD — see DECLARED_DEAD below: its
     reasoning tokens are charged against max_tokens, and there is no budget for
     the paid tier that would make that affordable. The code path is intact and
     the chain skips it by name.
  3. OpenRouter (nvidia/nemotron-3-super-120b-a12b:free) — openrouter.ai
  4. Gemini     (gemini-3.5-flash)                     — reasoning, 1500 req/day

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

# 20 август 2026 — СЪЩИЯТ трансформ, сега и за Groq и за Gemini.
#
# Groq вече сервира openai/gpt-oss-120b — точно моделът, за който подът горе беше
# въведен при Cerebras. Gemini сервира gemini-3.5-flash. И двата МИСЛЯТ, и при
# двата мисленето се брои В бюджета на отговора. Измерено днес, не предположено:
#
#   Groq   gpt-oss-120b     completion_tokens=150 при content 549 знака
#                           + отделно поле "reasoning" -> мисленето е вътре
#   Gemini gemini-3.5-flash maxOutputTokens=100 -> thoughts=93 candidates=3  MAX_TOKENS
#                           maxOutputTokens=300 -> thoughts=285 candidates=11 MAX_TOKENS
#                           maxOutputTokens=1024-> thoughts=460 candidates=62 STOP
#
# Тоест thoughts + candidates <= тавана: мисленето изяжда бюджета ПРЕДИ отговора.
# Call site-овете тук са оразмерени за llama-3.3-70b (80..4096) — при 80 токена
# gpt-oss/gemini свършват бюджета още в мисленето и връщат отрязан или празен
# отговор. Точно това се случи в цикъла от 17:05: 29 отрязвания, 19 Groq и
# 10 Gemini, докато Cerebras (който има пода) не отряза нито веднъж.
GROQ_BUDGET_MULT  = float(os.environ.get("GROQ_BUDGET_MULT",  "3"))
GROQ_BUDGET_FLOOR = int(os.environ.get("GROQ_BUDGET_FLOOR", "1500"))
GROQ_BUDGET_CAP   = int(os.environ.get("GROQ_BUDGET_CAP",   "8192"))

GEMINI_BUDGET_MULT  = float(os.environ.get("GEMINI_BUDGET_MULT",  "3"))
# THE 1500 FLOOR WAS NOT ENOUGH. Measured in cycle 2026-08-28T08:05:00, not
# assumed: Gemini cut 14 of 19 answers (finishReason=MAX_TOKENS). The truncated
# reply lengths in characters, from memory/llm_provenance.jsonl:
#
#   77 171 174 182 191 193 239 256 258 271 293 519 1348 1382   median 247.5
#
# Eleven of the fourteen came back under 300 characters — the model spent the
# whole budget thinking and emitted a stub. For comparison the two COMPLETE
# answers at the same call site were 1711 and 1764 characters, about 430-440
# output tokens, so thinking took ~1060-1070 of the 1500 there. In the fourteen
# it took all of it.
#
# 4000 leaves room for a full answer after the longest thinking observed and
# stays under half the 8192 cap. The value lives IN CODE, not in .env: a
# threshold that exists only in an untracked file is invisible to git and to
# every future reader.
GEMINI_BUDGET_FLOOR = int(os.environ.get("GEMINI_BUDGET_FLOOR", "4000"))
GEMINI_BUDGET_CAP   = int(os.environ.get("GEMINI_BUDGET_CAP",   "8192"))
# low | medium | high (Cerebras default за gpt-oss-120b е "medium")
CEREBRAS_REASONING_EFFORT = os.environ.get("CEREBRAS_REASONING_EFFORT", "low")

# ── PROVIDERS DECLARED DEAD (23 Aug 2026) ───────────────────────────────────
# A provider that cannot serve this system is skipped BY NAME, with the reason
# written down, and its code path is left exactly where it is. Deleting the path
# would make the decision unreviewable: nobody reading this file later could
# tell "we tried it and it does not work for us" from "nobody ever wired it".
#
# The reason is a literal string and it travels into the log line, so the
# question "why is there no Cerebras in this run" is answered in the run's own
# output rather than in somebody's memory.
#
# To bring one back: delete its entry here. Nothing else has to change.
DECLARED_DEAD = {
    "cerebras": "DISABLED: reasoning tokens consume max_tokens; "
                "no budget for a paid tier",
}

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

    print(f"  [LLM] Groq {GROQ_MODEL}...")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    # gpt-oss-120b е reasoning модел: мисленето се брои В бюджета на отговора,
    # точно както при Cerebras. max_completion_tokens е полето, което покрива
    # двете заедно; "max_tokens" е наследеният псевдоним.
    budget = _reasoning_budget(max_tokens, GROQ_BUDGET_MULT,
                               GROQ_BUDGET_FLOOR, GROQ_BUDGET_CAP)
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _system_msg()},
            {"role": "user",   "content": prompt},
        ],
        "max_completion_tokens": budget,
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
    return _reasoning_budget(max_tokens, CEREBRAS_BUDGET_MULT,
                             CEREBRAS_BUDGET_FLOOR, CEREBRAS_BUDGET_CAP)


def _reasoning_budget(max_tokens: int, mult: float, floor: int, cap: int) -> int:
    """Бюджет за модел, който МИСЛИ вътре в бюджета на отговора.

    Един и същ трансформ за трите reasoning backend-а (Cerebras, Groq, Gemini).
    Подът е същината: 3 x 80 = 240 не стига дори за мисленето, така че малките
    call site-ове (media_intel_worker подава 80) получават пода, не кратното.
    """
    return min(cap, max(floor, int(max_tokens * mult)))


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

    model_name = GEMINI_API_URL.rsplit("/", 1)[-1].split(":")[0]
    print(f"  [LLM] Gemini {model_name}...")
    url = f"{GEMINI_API_URL}?key={key}"
    # Измерено 20 август 2026 срещу gemini-3.5-flash: thoughts + candidates <=
    # maxOutputTokens. При 100 -> thoughts=93, candidates=3, finishReason=
    # MAX_TOKENS. Мисленето изяжда бюджета преди отговора, точно както при
    # Groq и Cerebras, затова същият под важи и тук.
    budget = _reasoning_budget(max_tokens, GEMINI_BUDGET_MULT,
                               GEMINI_BUDGET_FLOOR, GEMINI_BUDGET_CAP)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": budget},
    }
    time.sleep(_SLEEP_SECS)
    r = requests.post(url, json=payload, timeout=(10, 60))

    if r.status_code == 429:
        _set_cooldown("gemini")
        raise RuntimeError("Gemini rate limit")

    r.raise_for_status()
    body = r.json()
    candidates = body.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini: празен отговор")
    cand = candidates[0]
    # Gemini казва "MAX_TOKENS" там, където OpenAI-съвместимите казват "length".
    # Нормализираме към "length", за да има llm_json един-единствен признак.
    raw_reason = (cand.get("finishReason") or "").upper()
    finish_reason = "length" if raw_reason == "MAX_TOKENS" else raw_reason.lower() or None
    # THE SPLIT IS MEASURED, NOT INFERRED (28 Aug 2026). Gemini returns
    # usageMetadata with thoughtsTokenCount and candidatesTokenCount — thinking
    # and answer, separately — and this function read the text and the finish
    # reason and threw the rest away. So when 14 answers were cut short the only
    # evidence left on disk was reply LENGTH IN CHARACTERS, and the size of the
    # thinking that ate the budget had to be estimated from it. Carried now, so
    # the next person reads the number instead of reconstructing it.
    usage = body.get("usageMetadata") or {}
    meta = {"finish_reason": finish_reason}
    for src, dst in (("thoughtsTokenCount", "thoughts_tokens"),
                     ("candidatesTokenCount", "answer_tokens"),
                     ("promptTokenCount", "prompt_tokens"),
                     ("totalTokenCount", "total_tokens")):
        if isinstance(usage.get(src), int):
            meta[dst] = usage[src]
    if "thoughts_tokens" in meta or "answer_tokens" in meta:
        meta["budget"] = budget
    return cand["content"]["parts"][0]["text"], meta


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
        keep_alive = _mw.keep_alive_for(model_id)
    except Exception:
        keep_alive = "30m"
    body = {"model": model_id, "stream": False,
            "messages": [{"role": "system", "content": _system_msg()},
                         {"role": "user", "content": prompt}],
            "keep_alive": keep_alive,
            "options": {"temperature": 0.4, "num_predict": num_predict}}
    try:
        r = requests.post(f"{_OLLAMA_URL}/api/chat", json=body, timeout=300)
    except requests.exceptions.Timeout:
        raise RuntimeError(f"local model {model_id} cold-start >300s")
    if r.status_code != 200:
        raise RuntimeError(f"local model HTTP {r.status_code}")
    content = ((r.json().get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("empty response from local model")
    return content, {"finish_reason": "stop", "degraded": True}


def _call_local(prompt: str, max_tokens: int):
    """Last-resort sovereign brain over Ollama HTTP (:11434). Called ONLY when all
    four cloud backends are cooling. Returns (content, meta) or raises. No external
    API — this is the local model, deliberately, so a full-blackout cycle stays alive."""
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
        model = _mw.local_model(want_big=True, purpose="groq_backend.last_resort")
        keep_alive = _mw.keep_alive_for(model)
    except Exception:
        pass
    body = {"model": model, "stream": False,
            "messages": [{"role": "system", "content": _system_msg()},
                         {"role": "user", "content": prompt}],
            "keep_alive": keep_alive,
            "options": {"temperature": 0.4, "num_predict": num_predict}}
    try:
        r = requests.post(f"{_OLLAMA_URL}/api/chat", json=body, timeout=300)
    except requests.exceptions.Timeout:
        raise RuntimeError(f"local model {model} cold-start >300s")
    if r.status_code != 200:
        raise RuntimeError(f"local model HTTP {r.status_code}")
    content = ((r.json().get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("empty response from local model")
    return content, {"finish_reason": "stop", "degraded": True}


# ---------------------------------------------------------------------------
# Публичен интерфейс — API не се променя
# ---------------------------------------------------------------------------

def call_groq_meta(prompt: str, max_tokens: int = 1024,
                   purpose: str | None = None) -> tuple:
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

    def _model_for(backend_label: str) -> str:
        """Which model actually answered — for provenance.

        Added 17 Aug 2026: meta already said WHICH BACKEND replied but never
        which model, so anything archiving a verdict could record "Groq" and not
        the id it actually called. Gemini's name is parsed out of GEMINI_API_URL
        (.../models/<id>:generateContent) rather than duplicated into a constant,
        so the two cannot drift apart.

        MOVED ABOVE _log_provenance ON 21 AUG 2026, because for four days it was
        computed and then thrown away — see the note there.
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
        if backend_label.startswith("local:"):
            return backend_label.split(":", 1)[1]
        return backend_label

    def _log_provenance(backend_label: str, prompt_text: str, content_text: str,
                        meta: dict | None = None):
        """PROVENANCE (14 Aug 2026): every verdict the system records used to be
        anonymous — no trace of WHICH model produced it, though the chain falls
        through 4 providers many times per cycle. E7 (calibrated ensemble) and E2
        (LLM-vs-data grounding) both need this join key. Append-only, fail-open,
        5MB rotation; prompt is stored as a hash + head, never in full.

        THE EXACT MODEL ID (21 Aug 2026, Emil). _model_for() has existed since
        17 Aug and this function never called it: every cloud row on disk says
        "Groq" or "Cerebras" and not one of them says WHICH model. Counted on
        the live log: 235 Groq rows, 440 Cerebras, 232 OpenRouter, 41 Gemini —
        948 cloud verdicts whose model is unrecoverable.

        That is not bookkeeping pedantry, it is the reason the 18-20 Aug outage
        took log-grepping to diagnose. 471 lines of
        "Groq failed (404 Client Error)" sat in memory/cycle_logs/, and the only
        way to learn which id had 404'd was to read the [LLM] print line
        immediately above each one. Provenance — the file that exists to answer
        "which model said this" — could not.

        `backend` keeps its old values on purpose: core/phase_report
        ._provenance_between() groups by it, and renaming the field would break
        the per-phase LLM-call table for every historical row. `model` is added
        beside it.
        """
        try:
            import hashlib as _hl
            _pf = Path(__file__).resolve().parents[1] / "memory" / "llm_provenance.jsonl"
            _pf.parent.mkdir(parents=True, exist_ok=True)
            if _pf.exists() and _pf.stat().st_size > 5_000_000:
                _pf.replace(_pf.with_suffix(".jsonl.1"))
            # BATCHED (23 Aug 2026). The cloud half of the same
            # 143-writes-a-night provenance stream as core/brain.py.
            # Same trade, same barrier: beat(). See core/durable.py.
            from core.durable import append_json as _append_json  # noqa: PLC0415
            _row = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "backend": backend_label,
                    "model": _model_for(backend_label),
                    "prompt_sha1": _hl.sha1(prompt_text.encode("utf-8", "ignore")).hexdigest()[:12],
                    "prompt_head": prompt_text[:80],
                    "reply_chars": len(content_text or ""),
                }
            # WHY THE ANSWER WAS THAT SHORT, not just how short it was. Where
            # the provider reports its own token accounting, it is carried here
            # verbatim. Item 4(d) had to estimate the thinking/answer split from
            # reply_chars because these fields were read and discarded; whoever
            # asks next reads the number. Absent for providers that report none
            # — an absent key is honest, a zero would not be.
            if meta:
                for _k in ("finish_reason", "thoughts_tokens", "answer_tokens",
                           "prompt_tokens", "total_tokens", "budget",
                           "used_reasoning_fallback"):
                    if meta.get(_k) is not None:
                        _row[_k] = meta[_k]
            _append_json(_pf, _row, batched=True)
        except Exception:
            pass  # bookkeeping must never break the chain

    last_error = None

    # ── THE POLICY GATE (20 Aug 2026) ───────────────────────────────────────
    # Not every failure is the same failure. See core/backend_policy.py: a 402
    # is an account that will not serve this run, a 429 is a window that will
    # reopen, and a step that has already watched all four die three times over
    # should stop spending its ceiling proving it again.
    from core import backend_policy as _policy
    _cloud_ok, _why = _policy.cloud_allowed(purpose)
    if not _cloud_ok:
        print(f"  [LLM] cloud skipped -- {_why}")
        backends = []

    # ── THE LADDER (22 Aug 2026) ────────────────────────────────────────────
    # Until today this function walked cloud -> cloud -> cloud -> cloud -> local
    # with no timeout the CALLER controlled. A provider that accepts a connection
    # and then says nothing blocks here for as long as its own socket timeout
    # allows; the step stops beating; the ceiling passes; the watchdog kills the
    # whole cycle for one step's unavailable model. That is the shape of all six
    # internet_intelligence kills in the existence ledger.
    #
    # core/step_budget.py spends the step's budget B in thirds and never blocks
    # past a slice. The three tiers are the same three that were always here —
    # what changes is that each one is ABANDONED at its slice instead of waited
    # on, and that running out means DEGRADED rather than a dead cycle.
    #
    # The cloud tier below is the ENTIRE original chain, unchanged, moved into a
    # closure: cooldowns, the policy gate, provenance, per-backend logging. This
    # is a change to how long it may take, not to how it chooses.

    def _cloud_chain():
        nonlocal last_error
        for label, key, fn in backends:
            # A DECLARED SKIP, NOT A DELETED PATH. _call_cerebras is still here,
            # still tested, still correct; it is simply not on the ladder, and
            # the run says why every time it walks past it.
            if key in DECLARED_DEAD:
                print(f"  [LLM] {label} -- {DECLARED_DEAD[key]}")
                continue
            if _policy.is_disabled(key):
                print(f"  [LLM] {label} disabled for this run -- skipping")
                continue
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
                    _log_provenance(label, prompt, result, meta)
                    _policy.note_cloud_success()
                    return result, meta
                raise ValueError(f"Empty response from {label}")
            except Exception as e:
                _policy.note_failure(key, e)
                print(f"  [LLM] {label} failed ({e}) -- next...")
                last_error = e
        return None                      # None => this tier declined, next tier

    def _local_tier(model_id: str):
        def _go():
            try:
                result, meta = _call_local_as(model_id, prompt, max_tokens)
            except Exception as e:
                nonlocal_err.append(e)
                return None
            meta = dict(meta or {})
            meta["backend"] = f"local:{model_id}"
            meta["model"] = model_id
            meta["degraded"] = True
            _log_provenance(f"local:{model_id}", prompt, result)
            return result, meta
        return _go

    nonlocal_err: list = []

    from core import step_budget as _budget
    from core import model_window as _mw
    _small = _mw.small_model()
    _big = _mw.big_model()

    res = _budget.run_call(
        cloud=_cloud_chain,
        local_3b=_local_tier(_small),
        # The 8b tier is offered only when the window is open. Outside it, handing
        # step_budget a callable that loads 8b would evict the pinned 3b mid-step —
        # the exact churn core/model_window.py exists to stop — and the ladder's
        # own CRITICAL check is about priority, not residency.
        local_8b=_local_tier(_big) if _mw.is_open() else None,
    )

    if res.outcome == _budget.OK and res.value is not None:
        result, meta = res.value
        if res.tier != _budget.CLOUD:
            _note_degraded(
                f"answered by {res.tier} ({meta.get('model')}) after the cloud "
                f"tier was abandoned at its slice of B={res.budget_sec:.0f}s")
            print(f"[LLM] cloud abandoned -> {res.tier} {meta.get('model')} OK "
                  f"(DEGRADED)")
        return result, meta

    # Nothing answered inside B. The step is TOLD, and then the original exception
    # is raised so that 127 existing call sites keep the contract they were written
    # against (a string, or AllBackendsFailedError). What is new is that the
    # degradation is on the record BEFORE the raise — _run()'s `except Exception`
    # prints one line and carries on, and a step that carried on without a model
    # used to be indistinguishable from one that worked.
    if _cloud_ok:
        # Only count it when the cloud was actually attempted. A call that
        # skipped the cloud by policy must not push the counter further.
        _policy.note_all_cloud_failed()
    if nonlocal_err:
        last_error = nonlocal_err[-1]
    _note_degraded("no tier answered within B={:.0f}s ({})".format(
        res.budget_sec, res.reason))
    print(f"  [LLM] DEGRADED: {res.reason}")

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