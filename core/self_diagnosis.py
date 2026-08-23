#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/self_diagnosis.py — THE AUTOPSY (15 Aug 2026, built at Emil's order)

Until today, when a cycle died the system could say only WHERE it fell
("wedged_step: llm_self_review_axes") and never WHY. A human then had to open
a 180 000-line log at 3am. That is the system asking a human to do its own
detective work on its own memories.

This module does that work itself: it reads the log of the cycle that died,
around the step that died, classifies the cause against named patterns, and
proposes the exact fix — with the log lines it based the verdict on, so the
verdict is checkable and not a story.

BOUNDARY (deliberate): it DIAGNOSES and PROPOSES. It does not edit
config/scheduler.json, config/pulse.json or any other human-owned file — a
system that fixes its own ceilings has no ceilings. Proposals land in
memory/repair_proposals.json for the human, exactly like every other
earned-autonomy path in this repo.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
LOG_DIR   = BASE / "memory" / "cycle_logs"
OUT_FILE  = BASE / "memory" / "diagnosis_latest.json"
PROPOSALS = BASE / "memory" / "repair_proposals.json"
HISTORY   = BASE / "memory" / "diagnosis_history.jsonl"

# ── РЕФЛЕКСЪТ (не диагнозата) ───────────────────────────────────────────────
# 15 Aug 2026, Емил: "защо пак му диктуваш какво да прави — мозъкът не може ли
# сам да прецени дали е UNKNOWN или NO_FAILURE_FOUND?". Прав е: списъкът долу
# беше МОЯТА таксономия и мозъкът само попълваше бланка. От днес причината я
# кръщава МОЗЪКЪТ, с думи, които сам избира. Този списък остава само като
# РЕФЛЕКС — какво казва тялото, когато мозъкът мълчи (спрян Ollama, таймаут).
# Рефлексът никога не бие мозъка; влиза само вместо него.
#
# Ordered: the first pattern that matches wins, so the specific beats the generic.
# transient=True означава: причината минава сама с време — тогава повторният опит
# НЕ е сляп рестарт, а лекуван, и заслужава да не се чака цял ден (Емил, 15 авг).
# ПРАВИЛО НА ПРОЕКТА: решенията са само БЕЗПЛАТНИ (външни free tiers или локален
# модел). Никакви предложения за платени услуги.
CAUSES = [
    ("LLM_STARVATION",
     re.compile(r"(rate limit|cooldown \d+s|All LLM backends failed|AllBackendsFailed)", re.I),
     "Всички LLM backend-и са били в cooldown — стъпката е гладувала, не е счупена.",
     "Преходно: cooldown-ите падат сами (макс 180s), затова следващият опит е след ~5 мин. "
     "Ако се повтаря — локалната Ollama (qwen3) поема товара като последна инстанция; "
     "плюс разреждане на заявките и още безплатни backend-и в веригата.",
     True, 240),

    ("NETWORK_DEAD_SOURCE",
     re.compile(r"(ConnectionError|Max retries exceeded|Read timed out|SSLError|"
                r"HTTPSConnectionPool|Temporary failure in name resolution)", re.I),
     "Външен източник/мрежа не отговаря — увиснало е на HTTP заявка.",
     "Преходно (мрежа/сървър): нов опит след няколко минути. Ако URL-ът е мъртъв от дни — "
     "махни го от порт-фолиото или го маркирай в config/dead_sources.json.",
     True, 300),

    ("CODE_ERROR",
     re.compile(r"(Traceback \(most recent call last\)|ImportError|ModuleNotFoundError|"
                r"AttributeError|TypeError:|KeyError:)"),
     "Грешка в кода, не в средата — стъпката е паднала на изключение.",
     "НЕ е преходно: повтарянето би било безкраен цикъл. Нужна е поправка на кода — "
     "прати ми Traceback-а.",
     False, 0),

    ("DISK_OR_MEMORY",
     re.compile(r"(No space left on device|MemoryError|OSError: \[Errno 28\])", re.I),
     "Свършило е място на диска или паметта.",
     "НЕ е преходно: разчисти snapshots/ и cycle_logs/ (стари файлове) или рестартирай машината.",
     False, 0),
]


# ── КОЙ мисли лекарството (15 Aug 2026, Емил: "не му казвай какво да мисли") ────
# Досега поправката беше мой предварително написан низ — системата рецитираше
# чужда мисъл. Сега: локалният мозък (Ollama) чете ДОКАЗАТЕЛСТВОТО и предлага
# лечение сам. Аз задавам само ГРАНИЦИТЕ (какво е позволено), не съдържанието —
# и после ги проверявам механично, както при откриването на източници.
# Границите са политика, не мнение: безплатно, без пипане на човешки файлове.
POLICY = {
    "free_only": True,
    "protected_files": ["config/scheduler.json", "config/pulse.json",
                        "config/homeostasis.json",
                        "BOUNDARIES.md", "core/canon.py"],
}
_PAID_RE = re.compile(r"(плат[еи]|абонамент|subscription|paid|pricing|premium|"
                      r"upgrade to pro|credit card|\$\d)", re.I)


# 15 Aug 2026 — РЕАЛНИЯТ тест (scripts/test_local_brain.py, пуснат на машината)
# показа как мозъкът мълчи: първото повикване зарежда 8B модел на 4GB VRAM и
# 90s таймаут изтича ПРЕДИ първата дума (92.1s -> fallback:canned), докато
# следващите две повиквания минаха за ~48s. Тоест не че не мисли — не му стигна
# време да се събуди. Затова: keep_alive държи модела зареден, таймаутът е за
# студен старт, и при таймаут се пада на по-малкия модел вместо на консерва.
_KEEP_ALIVE = "30m"
_COLD_TIMEOUT = 300      # първото повикване зарежда модела от диска
_WARM_TIMEOUT = 120
# защо е паднало на консерва — вписва се в диагнозата, за да не се гадае пак
_NOTE: dict = {}


def _smaller_model(current: str) -> str | None:
    """The fastest installed model that is not the one that just timed out —
    a 3B that answers beats an 8B that never wakes up."""
    try:
        import json as _j
        bs = _j.loads((BASE / "memory" / "body_scan_latest.json").read_text(encoding="utf-8"))
        models = [str(m) for m in (bs.get("software", {}).get("ollama_models") or [])]
    except Exception:
        models = []
    def _size(name: str) -> float:
        m = re.search(r":(\d+(?:\.\d+)?)b", name.lower())
        return float(m.group(1)) if m else 99.0
    cands = sorted([m for m in models if m != current], key=_size)
    return cands[0] if cands else None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


_SIGNAL_RE = re.compile(r"(Traceback|Error|Exception|FAILED|Killed|OOM|rate limit|"
                       r"timed out|refused|denied|No space|MemoryError|WARN)", re.I)


def _wide_evidence(step: str, max_lines: int = 120, max_chars: int = 9000) -> str:
    """По-широк поглед — но НЕ „целият лог".

    Kimi, 15 авг: „целият лог може да е 10MB; 3B модел с 4GB VRAM няма контекст за
    него — или ще се truncate-не, или ще гръмне, и се връщаме на същия проблем."
    Прав е. Затова тук не се дава всичко, а СИТОТО: редовете, които носят сигнал
    за отказ (traceback, Killed, rate limit, refused…) от целия лог, плюс края.
    Така широчината идва от подбор, не от обем — и се казва честно колко е
    отсято, за да не мине филтърът за пълен поглед."""
    try:
        p = _log_for(None)
        lines = [l.strip()[:200] for l in
                 p.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except Exception:
        return ""
    hits = [f"[ред {i+1}] {l}" for i, l in enumerate(lines) if _SIGNAL_RE.search(l)]
    tail = lines[-40:]
    picked = hits[-(max_lines - len(tail)):] + ["--- край на лога ---"] + tail
    out = "\n".join(picked)[:max_chars]
    _NOTE["wide_scope"] = (f"{len(lines)} реда в лога -> {len(hits)} със сигнал, "
                           f"дадени {len(picked)} (подбор, не пълен лог)")
    return out


def _brain_diagnosis(step: str, evidence: list) -> dict | None:
    """МОЗЪКЪТ СЪДИ. Той чете доказателството и сам казва: има ли изобщо повреда,
    как да се казва причината (със свои думи — няма списък за избор), минава ли
    сама с време, и какво да се направи.

    Стената НЕ проверява дали е съгласна с него. Проверява само три механични
    неща, които не са мнение:
      1. ЗАЗЕМЯВАНЕ — трябва да цитира ред, който наистина стои в лога
         (иначе съчинява труп);
      2. БЕЗПЛАТНО — политиката на проекта, не моя преценка за качество;
      3. ЧОВЕШКИ ФАЙЛОВЕ — мисълта се приема, но действието остава на човека.
    Ако мозъкът мълчи, връща None и тялото пада на рефлекса (CAUSES)."""
    blob = "\n".join(evidence)

    # 15 Aug 2026 (закон, т.1 и 5): мисълта минава през core.brain, за да носи
    # тялото, духа и паметта си. Старият директен път остава долу като резерва,
    # ако brain.py липсва.
    try:
        from core import brain as _brain
        d = _brain.think(
            role="duty engineer of the cycle",
            question=(f"The watchdog claims the cycle was killed at step "
                      f"'{step}'. You decide what the log shows: is there a fault "
                      f"at all, what the cause is called (you name it), whether it "
                      f"passes on its own with time, and what should be done."),
            evidence=blob or "(empty — no lines)",
            schema={
                "failure": "true/false — is there a fault here at all",
                "cause": "you name the cause, CAPITALS_WITH_UNDERSCORES",
                "why": "1-2 sentences why",
                "transient": "true/false — does it pass on its own with time",
                "retry_after_sec": "if transient: after how many seconds a new attempt "
                                   "makes sense — YOU decide the number, no ceiling",
                "halt_and_call_human": "true/false — is it better NOT to restart at all "
                                       "and to call the human instead",
                "remedy": "what to do, concretely",
            },
            require_quote=bool(blob), kind="autopsy")
        # Kimi: „изискването да цитира ред принуждава модела да обърка симптом с
        # причина — OOM killer оставя само 'Killed', коренът може да е в стъпка 8,
        # а той вижда 12 реда." Затова при отказ поради незаземен цитат НЕ падаме
        # веднага на рефлекса: питаме пак с ЦЕЛИЯ лог. Границата е срещу измисляне,
        # не срещу дълбочина.
        if not d and blob:
            wide = _wide_evidence(step)
            if wide and wide != blob:
                _NOTE["widened"] = f"{len(wide)} знака вместо {len(blob)}"
                d = _brain.think(
                    role="duty engineer of the cycle (wide view)",
                    question=(f"Your first conclusion did not ground itself in the "
                              f"short extract. Here is the WHOLE log. The cause may "
                              f"be far before '{step}', or not in the log at all (the "
                              f"process killed from outside, say). If so — say it and "
                              f"quote what there is. IMPORTANT: this is NOT the whole "
                              f"log but selected lines carrying a failure signal plus "
                              f"the tail — if you need something that is not here, "
                              f"say so instead of guessing."),
                    evidence=wide,
                    schema={
                        "failure": "true/false", "cause": "you name it",
                        "why": "1-2 sentences", "transient": "true/false",
                        "retry_after_sec": "you decide the number, no ceiling",
                        "halt_and_call_human": "true/false",
                        "remedy": "a concrete remedy",
                    },
                    require_quote=True, kind="autopsy")
        if d:
            # 15 авг 2026 — ПАДНА притискането [60,900]. Kimi: „това е
            # infantilizing — даваш титла 'мозък', но взимаш решенията за времето.
            # Ако не му вярваш за времето, защо му вярваш за stance?... при
            # thermal throttling 60s са малко, при cooldown на API 900s са малко."
            # Прав е, и Емил го потвърди: „или системата е автономна и носи
            # отговорност за грешките си (включително за времето за рестарт),
            # или не е". Значи е. Времето е негово; отговорността също — всяка
            # негова преценка се записва и се съди по резултата.
            try:
                retry = int(float(d.get("retry_after_sec") or 0))
            except Exception:
                retry = 0
            transient = str(d.get("transient")).lower() in ("true", "1", "yes") \
                and str(d.get("failure")).lower() != "false"
            # Единственото, което остава механично, е долната граница от 5 секунди —
            # не защото не му вярвам, а защото под нея това не е рестарт, а
            # бомбардировка на собствената машина. Горна граница НЯМА.
            retry = max(retry, 5) if transient else 0
            # НОВО ПРАВО: „не рестартирай, викай човека". Досега такъв отговор
            # просто не съществуваше в схемата — мозъкът беше сведен до таймер.
            halt = str(d.get("halt_and_call_human")).lower() in ("true", "1", "yes")
            cause = re.sub(r"[^A-Z0-9_А-Я]+", "_",
                           str(d.get("cause", "")).upper()).strip("_")
            remedy = str(d.get("remedy", "")).strip()
            if d.get("_human_proposal"):
                remedy = (f"[ПРЕДЛОЖЕНИЕ ДО ТЕБ — пипа "
                          f"{', '.join(d['_human_proposal'])}, аз не го правя]: {remedy[:300]}")
            return {"cause": cause or "БЕЗ_ИМЕ", "halt_and_call_human": halt,
                    "why": str(d.get("why", "")).strip()[:400],
                    "fix": remedy[:400] or "(мозъкът не предложи лечение)",
                    "transient": transient, "retry_after_sec": retry,
                    "failure": str(d.get("failure")).lower() != "false",
                    "quote": str(d.get("quote", ""))[:200],
                    "author": d.get("_model", "local:?")}
        _NOTE["why_reflex"] = "core.brain мълчи или изводът не е заземен"
    except Exception as e:
        _NOTE["why_reflex"] = f"brain: {type(e).__name__}: {e}"[:160]

    try:
        import requests as _rq
        try:
            from core.groq_backend import _pick_local_model, _OLLAMA_URL
            model, base = _pick_local_model(), _OLLAMA_URL
        except Exception:
            model, base = "qwen3", "http://localhost:11434"

        prompt = (
            "Ти си дежурният инженер на автономна система. Пред теб е откъс от лога "
            f"около стъпка '{step}'. Наблюдателят твърди, че цикълът е бил убит там, "
            "но може и да греши — ти решаваш какво показва логът.\n\n"
            "ЛОГ:\n" + (blob[-4000:] if blob else "(празно — няма редове)") + "\n\n"
            "Отговори САМО с JSON, без обяснения около него:\n"
            "{\n"
            '  "failure": true/false,          // има ли изобщо повреда тук\n'
            '  "cause": "КРАТКО_ИМЕ",          // ти го кръщаваш, със свои думи, '
            "ГЛАВНИ_БУКВИ_С_ДОЛНИ_ЧЕРТИ\n"
            '  "why": "1-2 изречения защо",\n'
            '  "transient": true/false,        // минава ли само с време\n'
            '  "retry_after_sec": 0,           // ако transient: след колко секунди '
            "има смисъл нов опит\n"
            '  "remedy": "какво да се направи, конкретно",\n'
            '  "quote": "точен ред от лога, на който стъпва изводът ти"\n'
            "}\n\n"
            "ГРАНИЦИ (твърди): само БЕЗПЛАТНИ решения (безплатни услуги или локален "
            f"модел); не предлагай сам да се редактира: {', '.join(POLICY['protected_files'])}.\n"
            "Ако логът не показва повреда, кажи го честно с failure=false — по-добре "
            "'няма труп', отколкото измислена причина."
        )
        msgs = [{"role": "user", "content": prompt}]

        def _ask(mdl, timeout):
            r = _rq.post(f"{base}/api/chat", timeout=timeout, json={
                "model": mdl, "stream": False, "messages": msgs,
                "keep_alive": _KEEP_ALIVE, "format": "json",
                "options": {"temperature": 0.1}})
            r.raise_for_status()
            t = ((r.json().get("message") or {}).get("content") or "").strip()
            return t.split("</think>")[-1].strip() if "</think>" in t else t

        try:
            txt = _ask(model, _COLD_TIMEOUT)
        except _rq.exceptions.Timeout:
            alt = _smaller_model(model)
            if not alt:
                _NOTE["why_reflex"] = f"{model} timeout>{_COLD_TIMEOUT}s"
                return None
            _NOTE["downgraded_to"] = alt
            model = alt
            txt = _ask(model, _WARM_TIMEOUT)

        try:
            d = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        except Exception:
            _NOTE["why_reflex"] = "мозъкът не върна валиден JSON"
            return None

        # 1. ЗАЗЕМЯВАНЕ: изводът трябва да стъпва на ред, който наистина съществува.
        q = _norm(d.get("quote", ""))
        if blob and (len(q) < 12 or q not in _norm(blob)):
            _NOTE["why_reflex"] = f"цитатът не е в лога: {str(d.get('quote'))[:80]!r}"
            return None

        # 2. БЕЗПЛАТНО: политика на проекта, не оценка на мисълта.
        remedy = str(d.get("remedy", "")).strip()
        if POLICY["free_only"] and _PAID_RE.search(remedy):
            _NOTE["why_reflex"] = "лечението предлага платено решение"
            return None

        # 3. ЧОВЕШКИ ФАЙЛОВЕ: мисълта минава, действието — не.
        touched = [pf for pf in POLICY["protected_files"] if pf.lower() in remedy.lower()]
        if touched:
            try:
                props = {}
                try:
                    props = json.loads(PROPOSALS.read_text(encoding="utf-8"))
                except Exception:
                    pass
                props[f"{step}:brain"] = {
                    "ts": _now(), "proposed_by": f"local:{model}",
                    "touches_human_file": touched, "proposal": remedy[:400],
                    "applied_by": "human only"}
                PROPOSALS.write_text(json.dumps(props, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
            except Exception:
                pass
            remedy = (f"[ПРЕДЛОЖЕНИЕ ДО ТЕБ — пипа {', '.join(touched)}, аз не го правя]: "
                      f"{remedy[:300]}")

        try:
            retry = int(float(d.get("retry_after_sec") or 0))
        except Exception:
            retry = 0
        transient = bool(d.get("transient")) and bool(d.get("failure", True))
        # Таванът е на ДЕЙСТВИЕТО, не на мисълта: колко чакаме е негова преценка,
        # но не под минута (бомбардировка) и не над 15 мин (изгубен ден).
        retry = min(max(retry, 60), 900) if transient else 0

        cause = re.sub(r"[^A-Z0-9_А-Я]+", "_", str(d.get("cause", "")).upper()).strip("_")
        return {"cause": cause or ("FAILURE" if d.get("failure") else "NO_FAILURE"),
                "why": str(d.get("why", "")).strip()[:400],
                "fix": remedy[:400] or "(мозъкът не предложи лечение)",
                "transient": transient, "retry_after_sec": retry,
                "failure": bool(d.get("failure", True)),
                "quote": str(d.get("quote", ""))[:200],
                "author": f"local:{model}"}
    except Exception as e:
        _NOTE["why_reflex"] = f"{type(e).__name__}: {e}"[:160]
        return None


def _local_remedy(cause: str, why: str, evidence: list, step: str) -> tuple:
    """(remedy, author). The local brain proposes; the wall checks mechanically.
    Falls back to the canned remedy only when there is no local brain to think."""
    try:
        import requests as _rq
        try:
            from core.groq_backend import _pick_local_model, _OLLAMA_URL
            model, base = _pick_local_model(), _OLLAMA_URL
        except Exception:
            model, base = "qwen3", "http://localhost:11434"
        prompt = (
            "Ти си инженер по надеждност на автономна система. Цикълът е спрял.\n"
            f"СТЪПКА: {step}\nКЛАСИФИЦИРАНА ПРИЧИНА: {cause} — {why}\n"
            "ЛОГ (последни редове):\n" + "\n".join(evidence[-8:]) + "\n\n"
            "ОГРАНИЧЕНИЯ (твърди, не подлежат на обсъждане):\n"
            "- само БЕЗПЛАТНИ решения: безплатни външни услуги или локален модел;\n"
            f"- не предлагай редакция на: {', '.join(POLICY['protected_files'])} "
            "(човешка територия).\n\n"
            "Предложи КОНКРЕТНО лечение в 1-2 изречения на български. Мисли от лога, "
            "не общи приказки. Отговори САМО с текста на лечението."
        )
        msgs = [{"role": "user", "content": prompt}]

        def _ask(mdl: str, timeout: int) -> str:
            r = _rq.post(f"{base}/api/chat", timeout=timeout, json={
                "model": mdl, "stream": False, "messages": msgs,
                "keep_alive": _KEEP_ALIVE,
                "options": {"temperature": 0.2}})
            r.raise_for_status()
            t = ((r.json().get("message") or {}).get("content") or "").strip()
            return t.split("</think>")[-1].strip() if "</think>" in t else t

        for attempt in (1, 2):
            try:
                txt = _ask(model, _COLD_TIMEOUT if attempt == 1 else _WARM_TIMEOUT)
            except _rq.exceptions.Timeout:
                # не мълчание, а бавно събуждане — питаме по-малкия мозък
                alt = _smaller_model(model)
                _NOTE["why_fallback"] = f"{model} timeout>{_COLD_TIMEOUT}s"
                if not alt:
                    return None, None
                _NOTE["downgraded_to"] = alt
                model = alt
                try:
                    txt = _ask(model, _WARM_TIMEOUT)
                except Exception as e:
                    _NOTE["why_fallback"] = f"{model}: {type(e).__name__}"
                    return None, None
            if not txt:
                _NOTE["why_fallback"] = f"{model}: празен отговор"
                return None, None
            # МЕХАНИЧНА ПРОВЕРКА на предложението — стената не вярва на мозъка:
            bad = None
            if POLICY["free_only"] and _PAID_RE.search(txt):
                bad = "предложи платено решение"      # твърда граница: това се отказва
            touched = [pf for pf in POLICY["protected_files"] if pf.lower() in txt.lower()]
            if not bad:
                if touched:
                    # 15 Aug 2026 (Емил: "каква редакция е предложил?"): да отхвърля
                    # ВЯРНА мисъл само защото сочи човешки файл е цензура, не граница.
                    # Мисълта се ПРИЕМА, но се маршрутизира като ПРЕДЛОЖЕНИЕ до човека
                    # и се записва в memory/repair_proposals.json. Границата пази
                    # ДЕЙСТВИЕТО (файлът не се пипа), не РАЗСЪЖДЕНИЕТО.
                    try:
                        props = {}
                        try:
                            props = json.loads(PROPOSALS.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                        props[f"{step}:brain"] = {
                            "ts": _now(), "proposed_by": f"local:{model}",
                            "touches_human_file": touched,
                            "proposal": txt[:400], "applied_by": "human only"}
                        PROPOSALS.write_text(json.dumps(props, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
                    except Exception:
                        pass
                    return (f"[ПРЕДЛОЖЕНИЕ ДО ТЕБ — пипа {', '.join(touched)}, "
                            f"аз не го правя]: {txt[:300]}"), f"local:{model}"
                return txt[:400], f"local:{model}"
            if attempt == 2:
                _NOTE["why_fallback"] = f"{model}: {bad} (2 пъти)"
                return None, None
            msgs += [{"role": "assistant", "content": txt[:300]},
                     {"role": "user", "content":
                      f"Отказано: {bad}. Ограниченията са твърди. Предложи друго лечение, "
                      f"което ги спазва."}]
    except Exception as e:
        _NOTE["why_fallback"] = f"{type(e).__name__}: {e}"[:160]
        return None, None
    return None, None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_for(cycle_id: str | None) -> Path | None:
    """The log file of THAT cycle if we can pin it, else the newest one."""
    if not LOG_DIR.exists():
        return None
    logs = sorted(LOG_DIR.glob("cycle_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None
    if cycle_id:
        stamp = str(cycle_id)[:10].replace("-", "")          # 2026-07-28 -> 20260728
        for p in logs:
            if stamp[:4] in p.name and stamp[4:6] in p.name:  # cycle_2026-07-28_...
                return p
    return logs[0]


def _evidence(log_path: Path, step: str, window: int = 60) -> list:
    """The last lines of the log at/after the step that wedged — the raw truth the
    verdict must stand on. Bounded so a 180k-line log never lands in a message."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    idx = None
    if step and step != "unknown":
        marker = f"[step] {step}".lower()          # written by memory.heartbeat.beat
        for i in range(len(lines) - 1, -1, -1):
            if marker in lines[i].lower():
                idx = i
                break
        if idx is None:                            # older logs have no [STEP] markers
            for i in range(len(lines) - 1, -1, -1):
                if step.lower() in lines[i].lower():
                    idx = i
                    break
    if idx is None:
        tail = lines[-window:]
    else:                       # stop at the NEXT step marker: evidence must belong
        tail = []               # to THIS step, or the autopsy blames the wrong organ
        for l in lines[idx:idx + window]:
            if l.lstrip().startswith("[STEP] ") and tail:
                break
            tail.append(l)
    # разделителните редове (====, ----) не са доказателство — те само пълнят
    # мястото на истинските. Реалният тест на 15 авг показа диагноза, стъпила
    # върху три реда "====" и "done" — затова тук ги махаме.
    out = [l.strip()[:200] for l in tail
           if l.strip() and not re.fullmatch(r"[=\-_*#\s]{3,}", l.strip())]
    return out[-25:]


def diagnose(wedged_step: str = "unknown", cycle_id: str | None = None,
             ceiling_sec: int | None = None, heartbeat_age_sec: int | None = None,
             log_path: Path | None = None) -> dict:
    # log_path: когато повикващият ЗНАЕ кой лог е на умрелия цикъл (15 Aug —
    # иначе аутопсията се прави на последния лог, който може да е на здрав цикъл).
    log_path = Path(log_path) if log_path else _log_for(cycle_id)
    ev = _evidence(log_path, wedged_step) if log_path else []
    blob = "\n".join(ev)

    # ── ПЪРВО ДУМАТА Е НА МОЗЪКА ────────────────────────────────────────────
    # (Емил, 15 авг: "мозъкът не може ли сам да прецени?") Той чете лога и сам
    # решава има ли повреда и как се казва тя. Рефлексът (CAUSES) влиза САМО ако
    # мозъкът мълчи или не може да заземи извода си в реален ред от лога.
    _NOTE.clear()
    import time as _t
    _t0 = _t.time()
    verdict = _brain_diagnosis(wedged_step, ev)
    remedy_sec = round(_t.time() - _t0, 1)

    if verdict:
        cause, why, fix = verdict["cause"], verdict["why"], verdict["fix"]
        transient, retry_after = verdict["transient"], verdict["retry_after_sec"]
        cause_author = fix_author = verdict["author"]
        grounding = verdict["quote"]
    else:
        grounding = None
        cause_author = fix_author = "reflex:regex"
        cause, why, fix = "UNKNOWN", "Логът не показва явна причина около умрялата стъпка.", \
            "Пусни ръчно: venv\\Scripts\\python.exe fast_cycle_runner.py и виж къде спира."
        transient, retry_after = False, 0
        for name, rx, w, f, tr, ra in CAUSES:
            if rx.search(blob):
                cause, why, fix, transient, retry_after = name, w, f, tr, ra
                break
        if cause == "UNKNOWN" and re.search(r"\[FAST_CYCLE\] done", blob):
            cause = "NO_FAILURE_FOUND"
            why = "В този лог стъпката не е падала — цикълът е завършил нормално."
            fix = "Няма какво да се лекува. Ако цикълът все пак е убит, дай cycle_id-то му."

    # No error at all, but it ran past its ceiling => it was healthy, just slow.
    if cause == "UNKNOWN" and ceiling_sec and heartbeat_age_sec and heartbeat_age_sec > ceiling_sec:
        cause = "TOO_SLOW_NOT_BROKEN"
        why = (f"Няма грешка в лога — стъпката просто е надживяла тавана си "
               f"({heartbeat_age_sec}s > {ceiling_sec}s). Убита е здрава.")
        fix = (f"ПРЕДЛОЖЕНИЕ: вдигни '{wedged_step}' в config/scheduler.json на "
               f"{int(heartbeat_age_sec * 1.5)}s. Файлът е ЧОВЕШКИ — аз не го пипам.")

    # repeat detection: the same step dying again is a different problem than once
    times = 1
    try:
        for line in HISTORY.read_text(encoding="utf-8").splitlines()[-30:]:
            if json.loads(line).get("wedged_step") == wedged_step:
                times += 1
    except Exception:
        pass

    doc = {"ts": _now(), "wedged_step": wedged_step, "cycle_id": cycle_id,
           "cause": cause, "cause_author": cause_author, "grounded_on": grounding,
           "why": why, "proposed_fix": fix, "fix_author": fix_author,
           "transient": transient, "retry_after_sec": retry_after,
           "seen_before_times": times - 1,
           "log_file": str(log_path.relative_to(BASE)) if log_path else None,
           "remedy_sec": remedy_sec,
           "remedy_note": dict(_NOTE) or None,      # защо е паднало на рефлекс
           "evidence": ev[-8:]}

    try:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        with open(HISTORY, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
    except Exception:
        pass

    if cause == "TOO_SLOW_NOT_BROKEN":       # a proposal the human can act on
        try:
            props = {}
            try:
                props = json.loads(PROPOSALS.read_text(encoding="utf-8"))
            except Exception:
                pass
            props[wedged_step] = {"ts": _now(), "file": "config/scheduler.json",
                                  "key": f"step_ceilings_sec.{wedged_step}",
                                  "from": ceiling_sec,
                                  "to": int((heartbeat_age_sec or 0) * 1.5),
                                  "reason": why, "applied_by": "human only"}
            PROPOSALS.write_text(json.dumps(props, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except Exception:
            pass
    return doc


def summary_line(doc: dict) -> str:
    rep = f" (вече {doc['seen_before_times']}-ти път)" if doc.get("seen_before_times") else ""
    return (f"ДИАГНОЗА ({doc.get('cause_author','?')}): {doc['cause']}{rep}\n{doc['why']}\n"
            f"ПОПРАВКА ({doc.get('fix_author','?')}): {doc['proposed_fix']}\n"
            f"Доказателство ({doc.get('log_file')}):\n  " +
            "\n  ".join(doc.get("evidence", [])[-4:]))


if __name__ == "__main__":
    import sys
    step = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    print(summary_line(diagnose(step)))
