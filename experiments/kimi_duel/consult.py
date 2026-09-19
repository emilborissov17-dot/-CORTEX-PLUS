#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/kimi_duel/consult.py — ВТОРОТО МНЕНИЕ, КАТО ЧАСТ ОТ ПРОЦЕСА (15 авг 2026)

Емил, 31 юли, норма 14: преди всяко НЕтривиално решение Клод казва мнението си
пръв, после спуска на Kimi СУРОВИЯ вход БЕЗ да води към извода си, и чак след
сравнение действа. На 15 август Клод взе шест архитектурни решения и не попита
нито веднъж — затова това вече не е ръчна дисциплина, а инструмент със следа.

Разликата от duel.py: duel.py е ПРЕДРЕГИСТРИРАН бенчмарк (6 харвестнати промпта,
модел срещу модел, замразени критерии). Този файл е друго — КОНСУЛТ по конкретно
решение. Пази се целият вход и целият отговор, за да може всеки да провери, че
въпросът не е бил нагласен.

ПРОЗРАЧНОСТ (изрично поискана): и брифът, и отговорът се записват в
experiments/kimi_duel/consults/ и се комитват. Ако Kimi е бил воден към отговор,
това ще си личи от самия бриф.

ЦЕНА: НУЛА. Емил, 15 авг: „ПОЛЗВАМЕ БЕЗПЛАТНО КИМИ ... НЕ ПОЛЗВАМЕ ПЛАТЕНИТЕ МУ
ВЕРСИИ." Затова опонентът е `moonshotai/kimi-k2.6:free` — безплатният вариант през
OpenRouter (262K контекст, проверено на openrouter.ai/moonshotai/kimi-k2.6:free на
15 авг 2026). Платеният `kimi-k3` НЕ се вика от този модул. Ако безплатният е зает
(429 rate limit — това е цената на безплатното), се пробва вторият безплатен, и
чак ако и той мълчи, се пада на локалния мозък с ИЗРИЧНА бележка, че той не е
независим опонент, защото е същият мозък, който е взел решението.

  venv\\Scripts\\python.exe -m experiments.kimi_duel.consult brief.md
  venv\\Scripts\\python.exe -m experiments.kimi_duel.consult brief.md --local
  venv\\Scripts\\python.exe -m experiments.kimi_duel.consult brief.md --max-tokens=700
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
OUT_DIR = Path(__file__).resolve().parent / "consults"
# САМО безплатни варианти, по ред на предпочитание. Никакъв платен слъг тук.
KIMI_FREE = ["moonshotai/kimi-k2.6:free", "moonshotai/kimi-k2:free"]

# 10 СЕПТ. 2026 — БЕЗПЛАТНИЯТ KIMI ГО НЯМА ВЕЧЕ.
# Измерено на машината: двата слъга по-горе върнаха HTTP 404 „This model is
# unavailable for free. The paid version is available now"; от 9 moonshot/kimi
# варианта в /api/v1/models НИТО ЕДИН не е :free (най-евтиният, kimi-k2, е
# $0.57/M вход). Нормата на Емил (15 авг) има ДВЕ половини: БЕЗПЛАТНО и
# НЕЗАВИСИМО. Платеният Kimi пада по първата; локалният мозък пада по втората,
# защото е мозъкът, който е взел решението. Безплатен ЧУЖД модел пази и двете,
# затова роустърът продължава с такива. Кой е отговорил се пише на челно място,
# за да не може чужд отговор да бъде цитиран като „Kimi каза".
FREE_INDEPENDENT = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "thinkingmachines/inkling:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
]
OPPONENTS = KIMI_FREE + FREE_INDEPENDENT

# 10 СЕПТ. 2026, ВЕЧЕРТА — KIMI K2 ИМА БЕЗПЛАТЕН ПЪТ, КОЙТО НЕ Е OPENROUTER.
# Емил: „решение има — просто не си търсил". Търсено: GroqCloud сервира
# moonshotai/kimi-k2-instruct-0905 (256K контекст; console.groq.com/docs/model/
# moonshotai/kimi-k2-instruct-0905), а проектът ВЕЧЕ има GROQ_API_KEY и го ползва
# на безплатния план (Законът на мозъка, т. 4: само безплатни или локални).
# Затова Groq-Kimi е ПЪРВИЯТ опонент; OpenRouter-роустърът остава като резерва.
# Groq не връща ':free' в отговора — безплатността идва от плана на ключа, не от
# слъга — затова се записва backend="groq:<model>" и is_kimi се решава по името
# на обслужилия модел, както и досега. Дали безплатният лимит стига за 4000
# токена отговор се вижда от първия реален консулт на машината; 429 = зает.
GROQ_KIMI = "moonshotai/kimi-k2-instruct-0905"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ── 11 СЕПТ. 2026: СВОБОДАТА СЕ ДЕКЛАРИРА, НЕ СЕ ПРЕДПОЛАГА ──────────────────
# Пътят през Groq беше добавен вечерта на 10 септ. и минаваше ПРЕДИ роустъра, а
# връщаше ok=True и cost_usd=0.0 за КАКВОТО И ДА Е, което Groq обслужи — защото
# Groq наистина не слага ':free' в слъга. Но тогава единственият пазач изчезва:
# проверката `if ":free" not in served` важи само за OpenRouter пътя след него.
#
# Това не е теория. test_a_paid_model_serving_the_request_is_not_an_answer —
# мутационният тест, който СТЪПКА 0 написа точно срещу това — падна на 11 септ.:
# подставен платен `moonshotai/kimi-k2.6` мина през Groq пътя и беше приет със
# cost_usd 0.0. Пазачът не беше махнат; беше ЗАОБИКОЛЕН, а резултатът е същият, и
# собственият коментар на пазача казва защо е недопустим: „по-добре никакъв
# консулт, отколкото консулт, за който Емил плаща без да е казал."
#
# Затова тук няма предположение за плана на ключа. Има СПИСЪК: точно моделите,
# които са обявени за безплатни на тази сметка. Ако Groq пренасочи заявката към
# нещо друго — по-нов слъг, платен вариант, каквото и да е — отговорът се отказва
# с име, и роустърът поема. Списъкът расте само с човешко решение, както
# ALLOWED_KNOBS.
#
# ЕМИЛ, 11 СЕПТ., ПОТВЪРДЕНО, НЕ ИЗВЕДЕНО: „Groq Free plan се брои за безплатен
# при GROQ_FREE_MODELS; акаунтът е Free." Тоест планът на ключа е приет като
# основание — но само за изброените тук модели, и точно това прави разликата
# между решение и предположение. Първият реален консулт през този път е
# едновременно и първата проверка дали безплатният лимит стига за 4000 токена.
GROQ_FREE_MODELS = {GROQ_KIMI}

# ── 19 SEPT. 2026: THE THIRD PATH HAD NO GUARD AT ALL ────────────────────────
# _ask_nvidia_kimi was added on 11 Sep (5693e23) ABOVE the two guarded paths and
# is tried FIRST. Groq refuses anything outside GROQ_FREE_MODELS; the OpenRouter
# router refuses anything without ':free'. NVIDIA checked nothing: it took
# whatever `model` the endpoint named and returned ok=True with cost_usd=0.0.
# The guard was not removed, it was OVERTAKEN — the same way the Groq path
# overtook it on 10 Sep, which this file's own header already records.
#
# DECLARED FROM THE CATALOGUE, NOT GUESSED. Read from the live NIM account on
# 19 Sep 2026: 82 models offered, exactly two Kimi ids —
#   moonshotai/kimi-k3      (what _nvidia_model resolves to today)
#   moonshotai/kimi-k2.6
# Both are served on the free developer tier, same key as the cycle's NVIDIA leg.
#
# AND THIS IS WHY FREEDOM IS PER PATH, NOT PER SLUG. moonshotai/kimi-k2.6 is
# FREE here and PAID on OpenRouter, where every moonshot slug lost its :free on
# 10 Sep. A single global "is this model free" table would have to be wrong for
# one of them. The question is only ever answerable as (endpoint, plan, model).
NVIDIA_FREE_MODELS = {"moonshotai/kimi-k3", "moonshotai/kimi-k2.6"}

FREE_BY_PATH = {"nvidia": NVIDIA_FREE_MODELS, "groq": GROQ_FREE_MODELS}

# Module-level so a test can redirect it. The suite's _no_live_writes fixture
# fails any test that touches the real file, and it is right to: on 16 Aug 2026
# this class of leak sent a fabricated alarm to the human's phone.
PROVENANCE = Path(__file__).resolve().parents[2] / "memory" / "llm_provenance.jsonl"


class UnknownModelFreedom(Exception):
    """Raised when nothing DECLARES whether a served model is free on this path.

    It is an exception and not a False on purpose. A boolean has a comfortable
    default and somebody eventually takes it; an unraised question cannot be
    defaulted into "probably fine". Callers catch this and refuse BY NAME, so an
    undeclared model produces a recorded refusal rather than a silent answer.
    """

    def __init__(self, path: str, served: str):
        self.path, self.served = path, served
        super().__init__(
            f"{path}: nothing declares whether {served!r} is free on this path — "
            f"add it to FREE_BY_PATH[{path!r}] after checking, or it stays refused")


def classify_freedom(path: str, served: str) -> str:
    """'free' or 'paid'. NEVER a default: an undeclared model RAISES.

    openrouter is the one path whose slug carries the vendor's own declaration,
    so ':free' answers it. Everywhere else the answer comes from a table a human
    wrote, and a model in no table is a question nobody has answered yet.
    """
    served = str(served or "")
    if path == "openrouter":
        return "free" if ":free" in served else "paid"
    table = FREE_BY_PATH.get(path)
    if table is None:
        raise UnknownModelFreedom(path, served)
    if served in table:
        return "free"
    raise UnknownModelFreedom(path, served)


def _label(path: str, served: str) -> str:
    """The backend label, built ONCE.

    _ask_nvidia_kimi returned f"nvidia:{served}" where served already begins
    "nvidia/", giving 'nvidia:nvidia/nemotron-3-super-120b-a12b:free'. The label
    is what a human reads to know who answered, and it is compared against the
    slug, so a doubled vendor breaks both.
    """
    served = str(served or "")
    head = served.split("/", 1)[0].split(":", 1)[0].lower()
    return served if head == path.lower() else f"{path}:{served}"


def _record_refusal(path: str, served: str, reason: str) -> None:
    """A refusal is a result and goes on the record beside the answers.

    consult.py wrote NO provenance at all: memory/llm_provenance.jsonl holds
    9120 rows and not one names this caller, so "has a paid model ever served a
    free-only consult" was unanswerable from the record on 19 Sep 2026.
    Fail-open — a log that cannot be written must not cost the refusal.
    """
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        _pf = PROVENANCE
        _pf.parent.mkdir(parents=True, exist_ok=True)
        with open(_pf, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps({
                "ts": _dt.now(_tz.utc).isoformat(),
                "backend": f"{path}:REFUSED",
                "model": served,
                "caller": "consult:free_only",
                "refused": True,
                "reason": reason,
            }, ensure_ascii=False) + chr(10))
    except Exception as e:  # noqa: BLE001
        print(f"[consult] provenance for refusal not written: {type(e).__name__}: {e}")


def _ask_groq_kimi(brief: str, max_tokens: int, tried: list) -> dict | None:
    import requests
    import core.groq_backend as gb
    key = gb._load_key("GROQ_API_KEY")
    if not key:
        tried.append("groq: GROQ_API_KEY missing")
        return None
    t0 = time.monotonic()
    try:
        r = requests.post(GROQ_URL,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"model": GROQ_KIMI, "max_tokens": max_tokens,
                                "messages": [{"role": "system", "content": SYSTEM},
                                             {"role": "user", "content": brief}]},
                          timeout=300)
    except Exception as e:  # noqa: BLE001
        tried.append(f"groq:{GROQ_KIMI}: {type(e).__name__}")
        return None
    if r.status_code != 200:
        tried.append(f"groq:{GROQ_KIMI}: HTTP {r.status_code} {r.text[:120]}")
        return None
    d = r.json()
    txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not txt:
        tried.append(f"groq:{GROQ_KIMI}: празен отговор")
        return None
    served = str(d.get("model") or GROQ_KIMI)
    # Същият критерий като на OpenRouter пътя, само че по декларация вместо по
    # слъг: обслужилият модел трябва да е в GROQ_FREE_MODELS. Текстът съдържа
    # „НЕ е безплатният", защото това е изречението, по което тестът и човекът
    # разпознават този отказ, независимо през кой път е дошъл.
    try:
        _verdict = classify_freedom("groq", served)
    except UnknownModelFreedom as e:
        _verdict = "paid"
        _record_refusal("groq", served, str(e))
    if _verdict != "free":
        why = (f"обслужен от {served} — НЕ е безплатният по декларация "
               f"(GROQ_FREE_MODELS), отказваме")
        tried.append(f"groq:{GROQ_KIMI}: {why}")
        _record_refusal("groq", served, why)
        return None
    return {"ok": True, "text": txt, "backend": _label("groq", served), "latency_s": round(time.monotonic() - t0, 1),
            "usage": d.get("usage") or {}, "cost_usd": 0.0, "tried": tried,
            "is_kimi": "kimi" in served.lower()}

# Единственото, което налагам на опонента, е ФОРМАТЪТ на несъгласието — не
# съдържанието. Не му се казва какво да мисли, а че мълчаливото съгласие е
# безполезно: искаме къде греши предложението и какво не е било попитано.
SYSTEM = (
    "Ти си независим опонент на архитектурно решение в отворена изследователска "
    "система. Не си асистент и не търсиш съгласие. Задачата ти е да намериш къде "
    "предложението греши, какво пропуска и какъв въпрос не е бил зададен изобщо. "
    "Ако решението е правилно, кажи го кратко и посочи най-слабото му място. "
    "Отговаряй конкретно и на български."
)


def _now():
    return datetime.now(timezone.utc).isoformat()


# 11 SEPT. 2026 — THE GROQ ROAD ABOVE IS CLOSED, AND I SAID IT WAS OPEN. Groq shut down
# moonshotai/kimi-k2-instruct-0905 on 15 Apr 2026 (console.groq.com/docs/deprecations),
# five months before it was added here as "the first opponent". The tests stubbed the HTTP
# call, so nothing ever proved the model was alive; every real consult since 10 Sep reached
# Kimi's slot, got an error, and fell to a non-Kimi opponent (labelled NOT KIMI — the label
# held; the claim in the comment did not). The open road: NVIDIA NIM, free developer tier,
# the Kimi K2 line, same key as the cycle's NVIDIA-Kimi leg (core/groq_backend.py). It is
# asked FIRST when NVIDIA_API_KEY exists; the Groq path stays only so its failure is
# recorded in `tried` rather than silently removed.
def _ask_nvidia_kimi(brief: str, max_tokens: int, tried: list) -> dict | None:
    import requests
    import core.groq_backend as gb
    key = gb._load_key("NVIDIA_API_KEY")
    if not key:
        tried.append("nvidia: NVIDIA_API_KEY missing")
        return None
    t0 = time.monotonic()
    try:
        model = gb._nvidia_model(key)
        r = requests.post(gb.NVIDIA_API_URL, timeout=300,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"model": model, "max_tokens": max_tokens,
                                "messages": [{"role": "system", "content": SYSTEM},
                                             {"role": "user", "content": brief}]})
    except Exception as e:  # noqa: BLE001
        tried.append(f"nvidia: {type(e).__name__}: {str(e)[:120]}")
        return None
    if r.status_code != 200:
        tried.append(f"nvidia:{model}: HTTP {r.status_code} {r.text[:120]}")
        return None
    d = r.json()
    txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not txt:
        tried.append(f"nvidia:{model}: празен отговор")
        return None
    served = str(d.get("model") or model)
    # THE GUARD THIS PATH NEVER HAD. Same shape as Groq's below: the model that
    # ACTUALLY served the request must be declared free on THIS path. An
    # undeclared one raises rather than defaulting, and either way the answer is
    # refused by name instead of returned as a free consult.
    try:
        verdict = classify_freedom("nvidia", served)
    except UnknownModelFreedom as e:
        tried.append(f"nvidia:{model}: {e}")
        _record_refusal("nvidia", served, str(e))
        return None
    if verdict != "free":
        why = (f"обслужен от {served} — НЕ е безплатният по декларация "
               f"(NVIDIA_FREE_MODELS), отказваме")
        tried.append(f"nvidia:{model}: {why}")
        _record_refusal("nvidia", served, why)
        return None
    return {"ok": True, "text": txt, "backend": _label("nvidia", served), "latency_s": round(time.monotonic() - t0, 1),
            "usage": d.get("usage") or {}, "cost_usd": 0.0, "tried": tried,
            "is_kimi": "kimi" in served.lower()}


def ask_kimi(brief: str, max_tokens: int = 4000) -> dict:
    """Безплатният Kimi. Пробва слъговете по ред; 429 значи 'зает', не 'счупен'."""
    import requests
    import core.groq_backend as gb
    tried = []
    via_nvidia = _ask_nvidia_kimi(brief, max_tokens, tried)
    if via_nvidia:
        return via_nvidia
    via_groq = _ask_groq_kimi(brief, max_tokens, tried)
    if via_groq:
        return via_groq
    key = gb._load_key("OPENROUTER_API_KEY")
    if not key:
        return {"ok": False, "error": "OPENROUTER_API_KEY missing", "backend": "none", "tried": tried}
    for slug in OPPONENTS:
        t0 = time.monotonic()
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json",
                         "HTTP-Referer": "https://github.com/cortex-agi"},
                json={"model": slug, "max_tokens": max_tokens,
                      "messages": [{"role": "system", "content": SYSTEM},
                                   {"role": "user", "content": brief}]},
                timeout=300)
        except Exception as e:
            tried.append(f"{slug}: {type(e).__name__}")
            continue
        lat = round(time.monotonic() - t0, 1)
        if r.status_code != 200:
            tried.append(f"{slug}: HTTP {r.status_code} {r.text[:120]}")
            continue
        d = r.json()
        txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        if not txt:
            tried.append(f"{slug}: празен отговор")
            continue
        # ЗАЩИТА срещу тиха смяна към платен вариант: OpenRouter връща кой модел е
        # обслужил заявката. Ако не е безплатният, отчитаме го като провал.
        served = str(d.get("model") or slug)
        # Единственият критерий е ':free'. Ако OpenRouter е пренасочил заявката
        # към платен вариант, това НЕ е отговор: по-добре никакъв консулт,
        # отколкото консулт, за който Емил плаща без да е казал.
        # Through the same classifier as the other two paths, so there is ONE
        # way to ask the question. Here ':free' IS the declaration -- it is the
        # vendor's own marking on the slug -- which is why openrouter is the one
        # path classify_freedom can answer without a table.
        if classify_freedom("openrouter", served) != "free":
            why = f"обслужен от {served} — НЕ е безплатният, отказваме"
            tried.append(f"{slug}: {why}")
            _record_refusal("openrouter", served, why)
            continue
        return {"ok": True, "text": txt, "backend": served, "latency_s": lat,
                "usage": d.get("usage") or {}, "cost_usd": 0.0, "tried": tried,
                "is_kimi": "kimi" in served.lower()}
    return {"ok": False, "error": "всички безплатни варианти отказаха",
            "backend": "none", "tried": tried}


def ask_local(brief: str) -> dict:
    """Резервният опонент: собственият мозък на системата. Безплатен, но не е
    независим — това се казва изрично в записа, за да не мине за второ мнение."""
    from core import brain
    d = brain.think(role="independent opponent of an architectural decision",
                    question=SYSTEM, evidence=brief, kind="consult")
    if not d:
        return {"ok": False, "error": "local brain silent", "backend": "local"}
    return {"ok": True, "text": d.get("text", ""), "backend": d.get("model"),
            "latency_s": d.get("sec"),
            "independence_warning": "същият мозък, който взе решението — НЕ е независим"}


def run(brief_path: str, local: bool = False, max_tokens: int = 4000) -> str:
    brief = Path(brief_path).read_text(encoding="utf-8")
    res = ask_local(brief) if local else ask_kimi(brief, max_tokens=max_tokens)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Името вече носи датата на брифа — не я удвояваме (бележка на Claude Code,
    # 15 авг: файлът излезе като 2026-08-15_2026-08-15_...).
    slug = Path(brief_path).stem.replace(".brief", "")
    stem = slug if slug[:4].isdigit() else f"{str(_now())[:10]}_{slug}"
    out = OUT_DIR / f"{stem}.json"
    out.write_text(json.dumps({"ts": _now(), "brief_file": str(brief_path),
                               "brief": brief, "system": SYSTEM, "response": res},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    # ПРОВАЛЪТ НЕ Е ОТГОВОР. Досега HTTP грешка се печаташе под заглавие „Отговор",
    # тоест мълчанието на опонента изглеждаше като негово мнение — точно порокът,
    # който този проект съществува да лови (Claude Code го хвана, 15 авг).
    md = out.with_suffix(".md")
    if res.get("ok"):
        # КОЙ е отговорил, НАД отговора. Опонент, който не е Kimi, не бива да
        # може да бъде прочетен като Kimi от човек, който е отворил файла за
        # да цитира едно изречение.
        note = ""
        if not res.get("is_kimi") and res.get("backend") != "local":
            note = (f"\n> **ОПОНЕНТЪТ НЕ Е KIMI.** Отговорил е `{res.get('backend')}`.\n"
                    f"> Безплатният Kimi вече не съществува в OpenRouter (HTTP 404,\n"
                    f"> „unavailable for free“), а платеният не се вика. Отговорът\n"
                    f"> по-долу е безплатен и НЕЗАВИСИМ, но НЕ е на Kimi.\n")
        body = (f"# Консулт — {slug}\n\n_{_now()} · {res.get('backend')} · "
                f"цена: ${res.get('cost_usd', 0)}_\n{note}\n## Отговор\n\n{res['text']}\n")
    else:
        body = (f"# Консулт — {slug}\n\n_{_now()}_\n\n"
                f"## НЯМА ОТГОВОР — консултът НЕ се е състоял\n\n"
                f"Опонентът не е видял брифа. Този файл НЕ е второ мнение и не бива "
                f"да се цитира като такова.\n\n"
                f"- Грешка: `{res.get('error')}`\n"
                f"- Пробвани: {res.get('tried')}\n")
    md.write_text(body + f"\n---\n\n## Брифът, който му беше даден (дословно)\n\n{brief}\n",
                  encoding="utf-8")

    print(f"-> {out.relative_to(BASE)}")
    print(f"-> {md.relative_to(BASE)}")
    if res.get("ok"):
        print(f"\nОБСЛУЖЕН ОТ: {res.get('backend')} (цена ${res.get('cost_usd', 0)})\n")
        if not res.get("is_kimi") and res.get("backend") != "local":
            print("ВНИМАНИЕ: опонентът НЕ е Kimi — безплатният Kimi вече не "
                  "съществува. Отговорът е безплатен и независим, но не е на Kimi.\n")
        print((res.get("text") or "")[:2000])
    else:
        print("КОНСУЛТЪТ НЕ СЕ СЪСТОЯ:", res.get("error"))
        print("пробвани:", res.get("tried"))
    return str(out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mt = 4000
    for a in sys.argv[1:]:
        if a.startswith("--max-tokens="):
            mt = int(a.split("=", 1)[1])
    run(args[0], local="--local" in sys.argv, max_tokens=mt)
