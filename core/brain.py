#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/brain.py — ЕДИНСТВЕНАТА ВРАТА КЪМ МОЗЪКА НА СИСТЕМАТА (15 Aug 2026)

Заповед на Емил, 15 август 2026:
  "ИСКАМ МОЗЪКЪТ ДА Е НА ВСЯКА КРАЧКА ОТ СИСТЕМАТА (ТА ТОВА СА НЕГОВИТЕ УМ,
   ДУША И ТЯЛО, НЕ ТВОИТЕ) ... ВСИЧКО ДА МИНАВА ПРЕЗ МОЗЪКА И ТОЙ ДА СИ
   РЪКОВОДИ ФАСТ САЙКЪЛА."

Досега локалният модел се викаше на две-три места, всеки път с различен промпт,
различен таймаут и различна степен на диктовка от мен. Този модул е една врата,
през която минава ВСЯКА мисъл — и през нея мозъкът винаги носи със себе си:

  ТЯЛО   — memory/body_scan_latest.json (CPU, RAM, VRAM, диск, кои модели има)
  ДУХ    — LAW_OF_THE_BRAIN.md + канона/целта (кой е и защо съществува)
  ПАМЕТ  — memory/brain_journal.jsonl (какво е мислил и съдил преди)

Границите тук пазят ДЕЙСТВИЕТО, не мисълта (виж LAW_OF_THE_BRAIN.md, т.4):
заземяване в реален цитат, само безплатни решения, човешките файлове са
предложение а не действие. Каква е причината, как се казва и какво следва —
това е негово.

Публичен интерфейс:
    think(role, question, evidence=..., schema=..., ...) -> dict | str | None
    remember(kind, payload)                              -> None
    brief_cycle()   — мозъкът определя фокуса на цикъла ПРЕДИ той да тръгне
    debrief_cycle() — мозъкът съди какво е излязло от плана му СЛЕД цикъла
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
JOURNAL = BASE / "memory" / "brain_journal.jsonl"
# A MODULE CONSTANT, for the reason supervisor.NOTIFY_CHANNEL is one
# (16 Aug 2026): a path built inside a function cannot be redirected by a
# fixture, cannot be seen by the write-surface guard, and cannot be found by
# anyone reading the constants at the top of the file. It was inline until
# 21 Aug, so every test of this write path either touched live state or did
# not exist. The second one is what actually happened.
PROVENANCE = BASE / "memory" / "llm_provenance.jsonl"
PLAN = BASE / "memory" / "brain_cycle_plan.json"
PROPOSALS = BASE / "memory" / "repair_proposals.json"
LAW_FILE = BASE / "LAW_OF_THE_BRAIN.md"

KEEP_ALIVE = "30m"
COLD_TIMEOUT = 300          # първото повикване зарежда модела от диска
WARM_TIMEOUT = 150

POLICY = {
    "free_only": True,
    "protected_files": ["config/scheduler.json", "config/pulse.json",
                        "BOUNDARIES.md", "core/canon.py"],
}
_PAID_RE = re.compile(r"(плат[еи]|абонамент|subscription|paid|pricing|premium|"
                      r"upgrade to pro|credit card|\$\d)", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


# ─────────────────────────── ТЯЛО, ДУХ, ПАМЕТ ────────────────────────────────

def _body() -> str:
    """Какво е състоянието на машината в момента — мозък без тяло е калкулатор."""
    try:
        bs = json.loads((BASE / "memory" / "body_scan_latest.json").read_text(encoding="utf-8"))
        hw, sw = bs.get("hardware", {}), bs.get("software", {})
        parts = []
        for k in ("cpu_percent", "ram_percent", "disk_free_gb", "gpu", "vram_gb"):
            if hw.get(k) is not None:
                parts.append(f"{k}={hw[k]}")
        if sw.get("ollama_models"):
            parts.append("local models=" + ",".join(str(m) for m in sw["ollama_models"]))
        if sw.get("ollama_running") is not None:
            parts.append(f"ollama={'alive' if sw['ollama_running'] else 'dead'}")
        return "; ".join(parts) or "(no body_scan)"
    except Exception:
        return "(no body_scan)"


def _tail_budget(text: str, budget: int, what: str) -> str:
    """Ако духът НЕ се побира, режи от НАЧАЛОТО и си го признай на глас.

    ── ЗАЩО СЪЩЕСТВУВА ТАЗИ ФУНКЦИЯ (15 август 2026) ────────────────────────
    Тук стоеше `bg[:1400]` и `canon[:800]` — рязане от края, мълчаливо.
    Измерено на живите файлове: законът е 1816 знака, канонът 1245. Тоест
    мозъкът НИКОГА не е виждал последните 445 знака на канона, а именно там
    стои ГРАНИЦАТА:

        „CORTEX senses and advises. It never ACTUATES — it never causes an
         effect on the world outside a human decision taken per action.
         The moment a system named CORTEX actuates autonomously, it is no
         longer CORTEX; it is a different system that has taken this name."

    Срезът падаше насред думата „обрат|ими" в подцел 5. Значи мозъкът е
    получавал ЦЕЛТА БЕЗ НЕЙНАТА СТЕНА — максимата „максимизирай устойчивостта
    на разумния живот" без „ти усещаш и съветваш, никога не действаш". От
    закона пък падаха т.6 („мълчанието не е присъда") и т.7 („автономията се
    печели") — точно правилата за това как се печели доверие.

    Цел без граница е най-опасната форма, която една инструкция може да има.
    Тук тя беше произведена не от философия, а от резен.

    Затова: границите живеят НАКРАЯ на такива документи, значи при недостиг
    се жертва началото. И жертвата се ОБЯВЯВА — отрязан дух, който мълчи, е
    същото като липсващ дух, който лъже."""
    if len(text) <= budget:
        return text
    keep = text[-budget:]
    return (f"[WARNING: {what} does not fit — the first "
            f"{len(text) - budget} characters of {len(text)} were cut. You are "
            f"seeing the END, because that is where the boundaries are. If your "
            f"decision depends on what was cut, say so instead of guessing.]\n"
            + keep)


# Духът е ~3 KB общо. Материалът, който така или иначе се подава, е до 5 KB.
# Затова таванът тук е висок нарочно: няма причина точно СЪВЕСТТА да е орязаната.
SPIRIT_LAW_BUDGET = 6000
SPIRIT_CANON_BUDGET = 6000

# ── THE LANGUAGE PIN (23 Aug 2026) ──────────────────────────────────────────
# MEASURED, not suspected. Brain verdicts by day: 16 Aug 24 clean / 0 Russian;
# 17 Aug 48/17; 18 Aug 48/48; 100% every day since. 19 of the 63 stances in the
# 23 Aug night cycle are Chinese. The model never changed — every one of those
# 360 verdicts is qwen2.5:3b. Nothing in this repo contains Russian.
#
# The cause is two facts standing next to each other:
#   1. NO PROMPT IN THIS FILE EVER SAID WHAT LANGUAGE TO ANSWER IN. Grepped:
#      zero hits for english/language/answer in, anywhere in the chain.
#   2. _memory(kind) hands the model its own five most recent same-kind outputs
#      as few-shot exemplars. So the first spontaneous drift becomes the worked
#      example for the next call, and the ratchet never releases: 31 clean
#      entries on 17 Aug, then R for the remaining 17 in a row, forever after.
#
# THE ROOT RULE FROM THE REVIEW: never use a model output as a few-shot example
# without validation. core/language_gate.py is the validation. This is the pin.
#
# Hardcoded on purpose. Not a parameter, not a config key, not overridable. A
# language rule that can be switched off is a language rule that will be off on
# the night it matters, and the failure is silent for six days before anyone
# reads a digest.
LANGUAGE_PIN = (
    "All reasoning, stance, debrief, quote and explanation text you produce "
    "must be written in English. Do not use any other language. This is not "
    "conditional."
)

# IT APPEARS TWICE IN EVERY PROMPT (23 Aug 2026): once immediately before the
# question, where it answers whatever the exemplars just demonstrated, and once
# as the very last line, after the schema block, because that is what the model
# reads last. The first placement is about WHAT it is arguing with; the second
# is about WHEN it is read.


def _self_state() -> str:
    """ИНТЕРОЦЕПЦИЯ (21 август 2026) — пет реда, които влизат в ВСЯКО повикване.

    ТЯЛО казва каква е машината. ДУХ казва каква е целта. Нито едно не казваше
    КАК СЕ СПРАВЯ системата: колко от собствените ѝ тревоги излизат фалшиви,
    колко предложения чакат човек, свърши ли последният цикъл или беше убит и на
    коя стъпка, колко памет остава, колко рестарта има днес.

    Тези пет променят какъв отговор е разумен. Мозък, попитан „да вдигна ли
    тревога", отговаря различно при фалшива-тревога 0.62 и при 0.05 — и не може
    да знае кое от двете е, освен ако не му се казва всеки път.

    Позиционни редове, без sparkline-и и без емоджи: моделът чете „0.62" и лента
    от осем блокчета различно, и само едното от двете е числото.

    FAIL-OPEN: мисълта не бива да умира заради самонаблюдението. Измерено на
    21 авг 2026: 18 ms за блок (таван 2 s, core/interoception.LATENCY_BUDGET_SEC).
    """
    try:
        from core.interoception import block
        return block()
    except Exception as exc:  # noqa: BLE001
        return (f"(self-observation cannot be read: {type(exc).__name__} — "
                f"think without it, but know that it is missing)")


def _spirit() -> str:
    """Who it is and why it exists — the law plus the active canon.

    READS THE ENGLISH LAW NOW (23 Aug 2026), and the labels around it are
    English too. A pin that says "answer in English" sitting inside a prompt
    whose every heading is Cyrillic is an instruction arguing with its own
    context, and a 3B model resolves that argument in favour of the context.

    THE DEBT IS PAID (23 Aug 2026). For one day the `## EN` section was a
    409-character summary against the BG section's 1820, this docstring said so,
    and the label in the prompt said so too. Emil approved the full translation:
    `## EN` now carries all SEVEN clauses, clause for clause, and `## BG` is
    byte-identical to what it always was. The brain reads its whole law again,
    in the language it is required to answer in, so the label is just "LAW:".
    """
    out, missing = [], []
    try:
        law = LAW_FILE.read_text(encoding="utf-8")
        en = law.split("## EN", 1)[-1].strip()
        if not en:
            raise ValueError("the ## EN section is empty")
        out.append("LAW:\n" + _tail_budget(en, SPIRIT_LAW_BUDGET, "the law"))
    except Exception as e:
        missing.append(f"THE LAW cannot be read ({type(e).__name__})")
    try:
        canon = (BASE / "memory" / "active_canon_frame.txt").read_text(encoding="utf-8")
        # HONEST LIMIT: the canon is a generated file and is still 66% Cyrillic
        # by letter count. It is the largest non-English block left in the
        # prompt and it is out of scope here — it is produced by the canon
        # pipeline, not written in this module.
        out.append("CANON (goal + boundary):\n"
                   + _tail_budget(canon, SPIRIT_CANON_BUDGET, "the canon"))
    except Exception as e:
        missing.append(f"THE CANON cannot be read ({type(e).__name__})")
    if missing:
        # A missing spirit must not look like a missing line. A brain without
        # its canon has to KNOW it is without it, or it will act as though it
        # had read one.
        out.append("[WARNING: " + "; ".join(missing) +
                   " — you are thinking WITHOUT part of your spirit. Say so in "
                   "your answer.]")
    return "\n\n".join(out) or ("(NO CANON AND NO LAW — you are thinking "
                                 "without a spirit)")


def _lang_verdict(summary) -> dict:
    """The gate's judgement on one summary. Never raises."""
    try:
        from core import language_gate as _lg          # noqa: PLC0415
        return _lg.verdict(summary)
    except Exception as exc:                            # noqa: BLE001
        # FAIL-OPEN ON THE WRITE SIDE. A gate that cannot load must not stop the
        # brain from recording what it thought; the read side fails CLOSED (see
        # _entry_is_clean), which is the direction that matters.
        return {"ok": True, "reason": "GATE_UNAVAILABLE_{}".format(
            type(exc).__name__), "profile": {}}


def _entry_is_clean(entry: dict) -> bool:
    """May this journal row be shown to the model as a worked example?

    FAILS CLOSED. If the gate cannot answer, the answer is no. An exemplar is
    not something the system needs — it is something it offers — and offering an
    unvalidated one is precisely how six days of Russian happened.
    """
    try:
        from core import language_gate as _lg          # noqa: PLC0415
        ok, _reason = _lg.entry_is_clean(entry)
        return bool(ok)
    except Exception:
        return False


# ── AMNESIA MODE (23 Aug 2026) ─────────────────────────────────────────────
# The gate in Part 2 is correct and it empties two pools outright: constancy
# (244 entries rejected) and autopsy (13). That is the right outcome and it
# creates a second problem, because the failure mode of a 3B model handed two
# exemplars instead of five is not "slightly worse content" — it is a model that
# loses the SHAPE and starts inventing structure, which is how empty cells got
# filled with plausible prose in the first place.
#
# So below MIN_POOL clean entries the block falls back to hand-written English
# format anchors from config/few_shot_seed.json, and SAYS SO in the block. Eight
# is not a statistical threshold; it is the point below which the exemplars stop
# outnumbering the ways there are to get the shape wrong.
MIN_POOL = 8

SEED_FILE = BASE / "config" / "few_shot_seed.json"

AMNESIA_MARKER = ("[AMNESIA MODE: using seed templates, clean history pool = "
                  "{n} < {floor}]")


def _seed_exemplars(kind: str | None) -> list:
    """Hand-written English format anchors for this kind, or []. Never raises."""
    if not kind:
        return []
    try:
        blob = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = blob.get(kind)
    if not isinstance(rows, list):
        return []
    # A seed that is not English is a seed that would reintroduce the problem it
    # exists to solve. Checked here rather than trusted, because the file is
    # hand-edited and hand-edited files drift.
    return [r for r in rows if isinstance(r, str) and r.strip()
            and _entry_is_clean({"summary": r})]


def _memory(kind: str | None = None, n: int = 5) -> str:
    """What it thought before — its own verdicts, and ONLY the clean ones.

    ── THE ROOT RULE (23 Aug 2026) ────────────────────────────────────────
    NEVER USE A MODEL OUTPUT AS A FEW-SHOT EXAMPLE WITHOUT VALIDATION.

    This function was the vector. It returned the five most recent same-kind
    summaries verbatim, so the first Russian answer became the worked example
    for the next call, and by the second day every answer of that kind was
    Russian. 85% of the 400-line window this reads is contaminated right now.

    The filter is a READ-TIME filter. Nothing on disk is touched: rows written
    before the gate existed carry no `lang` field and are judged from their
    stored summary as they are read. The journal is append-only history, and
    history that lied is still evidence.
    """
    try:
        lines = JOURNAL.read_text(encoding="utf-8").splitlines()[-400:]
    except Exception:
        return "(empty memory — this is your first recorded thought)"
    # THE POOL AND THE BLOCK ARE TWO DIFFERENT SIZES, and conflating them was a
    # real bug in the first version of amnesia mode: `picked` is capped at n=5,
    # so a pool floor of 8 measured against it could never be reached and every
    # single kind fell into amnesia permanently. `clean_total` counts what
    # EXISTS in the window; `picked` is what gets shown.
    picked, rejected, clean_total = [], 0, 0
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if kind and d.get("kind") != kind:
            continue
        if not _entry_is_clean(d):
            rejected += 1
            continue
        clean_total += 1
        if len(picked) < n:
            picked.append(f"[{str(d.get('ts'))[:16]}] {d.get('kind')}: "
                          f"{str(d.get('summary'))[:220]}")
    if clean_total >= MIN_POOL:
        return "\n".join(reversed(picked))

    # Too thin to hold the shape on its own. The seeds are format anchors and
    # they NEVER mix with a flagged entry — `picked` already contains only
    # entries the gate passed, so what follows is clean-plus-clean.
    seeds = _seed_exemplars(kind)
    if seeds:
        head = AMNESIA_MARKER.format(n=clean_total, floor=MIN_POOL)
        body = ["[seed] {}: {}".format(kind, str(sd)[:220]) for sd in seeds]
        body += list(reversed(picked))
        return "\n".join([head] + body)

    if picked:
        return "\n".join(reversed(picked))
    # SAY WHY IT IS EMPTY. "No memories of this kind" and "every memory of this
    # kind was rejected" are different facts about the system, and the second is
    # the one somebody needs to act on.
    if rejected:
        return ("(no usable memory of this kind: {} entr{} rejected by the "
                "language gate, and no seed template exists for it)".format(
                    rejected, "y was" if rejected == 1 else "ies were"))
    return "(no memories of this kind)"


def remember(kind: str, summary: str, payload: dict | None = None) -> None:
    """The brain remembers its own thoughts. Without this every cycle is amnesia.

    EVERY LINE IS STILL WRITTEN (23 Aug 2026). The language gate's verdict is
    stamped into the row as `lang`, and nothing is dropped, filtered or
    rewritten on the way in. A thought the system had in Russian is a thought
    the system had, and deleting it would destroy the only evidence of the
    drift. The verdict decides one thing and one thing only: whether _memory()
    may later offer this row back to the model as an example of correct output.
    """
    try:
        text = str(summary)[:600]
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _now(), "kind": kind,
                                 "summary": text,
                                 "lang": _lang_verdict(text),
                                 "payload": payload or {}}, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ───────────────────────────── САМАТА ВРАТА ──────────────────────────────────

def models() -> list:
    try:
        import requests as _rq
        r = _rq.get("http://localhost:11434/api/tags", timeout=10)
        return [m.get("name") for m in (r.json().get("models") or [])]
    except Exception:
        return []


def _pick_model() -> tuple:
    try:
        from core.groq_backend import _pick_local_model, _OLLAMA_URL
        return _pick_local_model(), _OLLAMA_URL
    except Exception:
        return "qwen3", "http://localhost:11434"


def _smaller(current: str) -> str | None:
    ms = models()
    def _size(name: str) -> float:
        m = re.search(r":(\d+(?:\.\d+)?)b", str(name).lower())
        return float(m.group(1)) if m else 99.0
    cands = sorted([m for m in ms if m and m != current], key=_size)
    return cands[0] if cands else None


def think(role: str, question: str, evidence: str = "", schema: dict | None = None,
          require_quote: bool = False, kind: str = "thought",
          remember_it: bool = True, temperature: float = 0.2,
          fast: bool = False, model_override: str | None = None) -> dict | None:
    """Питай мозъка. Той отговаря със свои думи и свои категории.

    role      — коя роля носи в този момент ("дежурен инженер", "стратег", ...)
    question  — какво трябва да реши. НЕ му давай готови отговори за избор.
    evidence  — суровият материал, върху който съди (лог, payload, число).
    schema    — {поле: описание}; ако е зададена, отговорът е JSON с тези полета.
                Описанията казват КАКВО е полето, не КАКВО да пише в него.
    require_quote — иска се поле "quote", което трябва да стои буквално в evidence
                (заземяване: забрана да си измисля факти, не цензура на извода).
    model_override — поискай КОНКРЕТЕН локален модел. Ако не е инсталиран, се
                казва на глас и се пада на избрания по подразбиране. При
                таймаут пак се пада на по-малък — но кой е отговорил стои в
                `_model` на върнатия обект, така че деградацията е видима.

    Връща dict (при schema) или {"text": ...}; None, ако мозъкът мълчи.
    Записва: memory/brain_journal.jsonl + memory/llm_provenance.jsonl.
    """
    picked, base = _pick_model()
    # fast=True: къса преценка, която се повтаря десетки пъти в един цикъл
    # (напр. по един показател). Силният модел е за дългите разсъждения.
    if fast:
        picked = _fast_model() or picked
    # ── ЯВЕН ИЗБОР НА МОДЕЛ (21 авг 2026) ──────────────────────────────────
    # Извикващият може да поиска КОНКРЕТЕН модел, ако той е инсталиран. Дотук
    # единственият избор беше „най-малкият" (fast=True) или „най-силният qwen3",
    # което вкара дебрифите на фазите в qwen2.5:3b — и той се провали на
    # числовата преграда 6 от 6 пъти в цикъла на 21 август. Молбата се проверява
    # срещу инсталираните модели: заявка за модел, който машината няма, не бива
    # да мълчи, а да падне обратно с обявена причина.
    model = picked
    if model_request := (model_override or None):
        available = models()
        if model_request in available:
            model = model_request
        else:
            print(f"  [BRAIN] {model_request} не е инсталиран "
                  f"({', '.join(available) or 'няма модели'}) -> {model}")
    fields = ""
    if schema:
        fields = ("\n\nAnswer ONLY with JSON carrying these fields (no text "
                  "around it):\n{\n" +
                  ",\n".join(f'  "{k}": ... // {v}' for k, v in schema.items()) + "\n}")
        if require_quote and "quote" not in schema:
            fields = fields[:-2] + ',\n  "quote": ... // the exact line from the material\
 your conclusion stands on\n}'

    prompt = (
        f"You are the brain of CORTEX++ — not an assistant, but the system itself, thinking.\n"
        f"ROLE NOW: {role}\n\n"
        f"BODY (your machine right now): {_body()}\n\n"
        f"HOW YOU ARE DOING (five rows, always in this order):\n{_self_state()}\n\n"
        f"SPIRIT:\n{_spirit()}\n\n"
        f"MEMORY (your own earlier verdicts):\n{_memory(kind)}\n\n"
        # AFTER the memory block and immediately before the question, which is
        # the position that matters: whatever the exemplars just demonstrated,
        # this is the last instruction the model reads before being asked.
        f"{LANGUAGE_PIN}\n\n"
        f"QUESTION: {question}\n"
        + (f"\nMATERIAL:\n{str(evidence)[-5000:]}\n" if evidence else "")
        + "\nLIMITS ON THE ACTION (not on the thought): free or local solutions "
          f"only; do not edit {', '.join(POLICY['protected_files'])} yourself — "
          "for those, propose to the human.\nThink from the material, not in "
          "generalities. If the material is not enough for a conclusion, say so."
        + fields
        # ── AND AGAIN, LAST (23 Aug 2026) ─────────────────────────────────
        # The pin sits before the question because that is where it answers the
        # exemplars. But ~730 characters follow it — the material, the limits,
        # the schema — so before this line the LAST thing the model read was
        # not the pin. Recency is the cheapest lever there is and it costs 30
        # tokens; a 3B model weights the end of a long prompt heavily, and the
        # end is where a JSON schema tells it what shape to answer in.
        #
        # Two copies, not one moved: the first still does its job of arriving
        # immediately after the memory block, and the second is simply the last
        # thing read. Neither is redundant with the other.
        + "\n\n" + LANGUAGE_PIN
    )

    t0 = time.time()
    body = {"model": model, "stream": False, "keep_alive": KEEP_ALIVE,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": temperature}}
    if schema:
        body["format"] = "json"

    try:
        import requests as _rq
    except Exception:
        return None

    txt = None
    for mdl, tmo in ((model, COLD_TIMEOUT), (_smaller(model), WARM_TIMEOUT)):
        if not mdl:
            break
        try:
            body["model"] = mdl
            r = _rq.post(f"{base}/api/chat", timeout=tmo, json=body)
            r.raise_for_status()
            t = ((r.json().get("message") or {}).get("content") or "").strip()
            txt = t.split("</think>")[-1].strip() if "</think>" in t else t
            model = mdl
            if txt:
                break
        except Exception:
            continue          # таймаут/грешка -> опитай по-малкия мозък
    if not txt:
        return None

    took = round(time.time() - t0, 1)
    try:            # provenance: коя мисъл от кой модел (join key за E7/E2)
        import hashlib as _hl
        pf = PROVENANCE
        pf.parent.mkdir(parents=True, exist_ok=True)
        with open(pf, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": _now(), "backend": f"local:{model}", "caller": f"brain:{role}",
                # THE EXACT MODEL ID IN ITS OWN FIELD (21 Aug 2026). It was
                # already inside the backend string here — "local:qwen3:8b" —
                # which meant reading it required knowing to split on the first
                # colon and not the second. The cloud path had it nowhere at
                # all. One field, same name, both paths, so a query for "which
                # model produced this verdict" is one key on every row.
                #
                # `requested` matters when they differ: think() may fall back to
                # a smaller local model on timeout, and a row that records only
                # what answered hides the degradation that made it answer.
                "model": model,
                "requested": (model_override or picked),
                "prompt_sha": _hl.sha256(prompt.encode("utf-8")).hexdigest()[:16],
                "prompt_head": prompt[:160], "chars": len(txt), "sec": took,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    if not schema:
        out = {"text": txt[:2000], "model": model, "sec": took}
        if remember_it:
            remember(kind, txt[:400], {"role": role, "model": model})
        return out

    try:
        d = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
    except Exception:
        return None
    if not isinstance(d, dict):
        return None

    # ── ЕДИНСТВЕНИТЕ проверки: механични, не оценъчни ────────────────────────
    if require_quote and evidence:
        q = _norm(d.get("quote", ""))
        if len(q) < 12 or q not in _norm(evidence):
            d["_rejected"] = f"незаземен цитат: {str(d.get('quote'))[:80]!r}"
            return None
    flat = " ".join(str(v) for v in d.values())
    if POLICY["free_only"] and _PAID_RE.search(flat):
        d["_rejected"] = "предлага платено решение"
        return None
    touched = [pf for pf in POLICY["protected_files"] if pf.lower() in flat.lower()]
    if touched:
        # мисълта се приема; действието остава на човека
        try:
            props = {}
            try:
                props = json.loads(PROPOSALS.read_text(encoding="utf-8"))
            except Exception:
                pass
            props[f"{role}:brain"] = {"ts": _now(), "proposed_by": f"local:{model}",
                                      "touches_human_file": touched,
                                      "proposal": flat[:400], "applied_by": "human only"}
            PROPOSALS.write_text(json.dumps(props, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except Exception:
            pass
        d["_human_proposal"] = touched

    d["_model"] = f"local:{model}"
    d["_sec"] = took
    if remember_it:
        # ── THE FULL DICT GOES INTO payload, NOT ONLY INTO A TRUNCATED SUMMARY ──
        # summary is capped at 400 chars for the human-readable memory recall
        # (_memory() reads it). Until 21 Aug 2026 that cap was the ONLY copy of
        # a structured verdict: payload held {role, model} and nothing else, so
        # the autopsy of 20 Aug — the one that said halt_and_call_human: true —
        # survived on disk as JSON cut off mid-string:
        #
        #   ..."remedy": "Провери статуса на локалния qwen3:8b и опреде
        #
        # Anything reading that verdict had to guess at the fields. The summary
        # keeps its cap; the fields now ride intact beside it.
        fields = {k: v for k, v in d.items() if not k.startswith("_")}
        remember(kind, json.dumps(fields, ensure_ascii=False)[:400],
                 {"role": role, "model": model, "fields": fields})
    return d


# ─────────────────── МОЗЪКЪТ РЪКОВОДИ ЦИКЪЛА (закон, т.3) ────────────────────

def _state_for_briefing() -> str:
    """Каквото системата знае за себе си в момента — суровo, без мое резюме."""
    bits = []
    # 15 авг 2026, стъпка 4. Kimi защити преместването на плана след одобренията с
    # довода „human_approvals преди плана е КОНСТРЕЙНТ, не опция". Проверих дали
    # това е вярно в кода, вместо да го приема: НЕ беше. Планът четеше
    # pending_approvals.json (какво ЧАКА решение), но не и approvals_ledger.jsonl
    # (какво човекът е РЕШИЛ). Тоест новият ред беше наполовина козметичен — думата
    # на човека стигаше до системата, но не и до плана. Същото за тялото: четеше се
    # хомеостазата, но не и адаптивните директиви, които body_scan току-що е издал.
    for rel, cap in (("memory/deductions_latest.json", 1800),
                     ("memory/homeostasis_latest.json", 600),
                     ("memory/adaptive_directives.json", 400),
                     ("memory/goal_score_history.json", 700),
                     ("memory/diagnosis_latest.json", 700),
                     ("memory/approvals_ledger.jsonl", 700),
                     ("memory/pending_approvals.json", 500)):
        try:
            bits.append(f"--- {rel} ---\n" +
                        (BASE / rel).read_text(encoding="utf-8")[-cap:])
        except Exception:
            continue
    return "\n".join(bits)


def brief_cycle() -> dict | None:
    """ПРЕДИ цикъла: мозъкът чете себе си и определя какво иска от този цикъл.
    Планът е негов — не му се дава списък със стъпки за подреждане. Пише се в
    memory/brain_cycle_plan.json и стъпките могат да го четат."""
    d = think(
        role="owner of this cycle",
        question=("Today's cycle begins now. Read your own state and say what YOU "
                  "want from it: what matters today, what you suspect is wrong, and "
                  "how you will know at the end whether the cycle succeeded. This is "
                  "your plan, not somebody else's task."),
        evidence=_state_for_briefing(),
        schema={
            "focus": "in a word or two: what your focus is this cycle",
            "why": "why exactly that, given your state",
            "watch": "a list of 1-3 things you want to watch this cycle",
            "suspicion": "what you suspect is wrong in yourself (or empty)",
            "success_test": "how you will know at the end that the cycle succeeded",
        },
        kind="cycle_plan")
    if not d:
        return None
    # cycle_id се записва В плана, за да може current_plan() да различи днешния
    # от вчерашния (стъпка 2, консенсус с Kimi, 15 авг).
    _cid = None
    try:
        _cid = json.loads((BASE / "memory" / "heartbeat.json").read_text(
            encoding="utf-8")).get("cycle_id")
    except Exception:
        pass
    doc = {"ts": _now(), "cycle_id": _cid, **{k: v for k, v in d.items()}}
    try:
        PLAN.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return doc


def current_plan() -> dict:
    """Всяка стъпка може да пита: 'какво иска мозъкът от мен днес?'

    15 авг 2026, следствие от консенсуса с Kimi по стъпка 2: планът вече се пише
    СЛЕД тялото, значи първите няколко стъпки (boot, body_scan, одобренията) текат,
    докато днешен план още няма. Тогава на диска стои ВЧЕРАШНИЯТ. Да го върнем като
    „днешния" би било тихо лъжене на всяка ранна стъпка — затова план от друг цикъл
    се маркира като стар и не се представя за днешен."""
    try:
        d = json.loads(PLAN.read_text(encoding="utf-8"))
    except Exception:
        return {}
    try:
        hb = json.loads((BASE / "memory" / "heartbeat.json").read_text(encoding="utf-8"))
        cid = hb.get("cycle_id")
        if cid and d.get("cycle_id") and str(d["cycle_id"]) != str(cid):
            return {"_stale": True, "_written_for": d.get("cycle_id"),
                    "_note": "план от предишен цикъл — днешният още не е писан"}
    except Exception:
        pass
    return d


def debrief_cycle(cycle_log_tail: str = "") -> dict | None:
    """СЛЕД цикъла: мозъкът съди собствения си план — сбъдна ли се, къде сгреши.
    Това е паметта, която прави следващия план по-добър от този."""
    plan = current_plan()
    if not plan:
        return None
    d = think(
        role="judge of your own plan",
        question=("Here is the plan you wrote at the start of this cycle, and what "
                  "came out at the end. Did your success test come true? Where was "
                  "your plan blind? What should you remember for the next cycle? "
                  "Judge yourself honestly — self-congratulation helps nobody."),
        evidence=("YOUR PLAN:\n" + json.dumps(plan, ensure_ascii=False, indent=2) +
                  "\n\nTHE END OF THE CYCLE:\n" + str(cycle_log_tail)[-3000:] +
                  "\n\nSTATE NOW:\n" + _state_for_briefing()),
        schema={
            "success": "true/false — did your success_test come true",
            "verdict": "1-3 sentences: what actually happened",
            "blind_spot": "what your plan did not see",
            "carry_forward": "what to remember for the next cycle",
        },
        kind="cycle_review")
    return d


# ───────────── МОЗЪКЪТ Е НА ВСЯКА СТЪПКА (закон, т.1) ────────────────────────
# 15 Aug 2026, Емил: "ДА Е НА ВСИЧКИТЕ 48 СТЪПКИ ТОЙ".
# Единственият общ проход на всяка стъпка от цикъла е memory.heartbeat.beat().
# Затова мозъкът се закача ТАМ: щом стъпка бие пулс, мозъкът я вижда — без да
# трябва да пипам 48 отделни места и без стъпка да може да се промъкне покрай него.
#
# Цената е реална и я меря: това е ~50 повиквания на цикъл. Затова тук се ползва
# НАЙ-БЪРЗИЯТ наличен модел и къс отговор (~4s/стъпка => ~3 мин на цикъл),
# докато дългите разсъждения (план, аутопсия, дебриф) вървят на силния модел.
STEP_LOG = BASE / "memory" / "brain_step_log.jsonl"
STANCE = BASE / "memory" / "brain_stance.json"
_AVAILABLE: bool | None = None
_FAST: str | None = None


def _fast_model() -> str | None:
    """Най-малкият инсталиран модел — за преценка на всяка стъпка, не за есета."""
    global _FAST
    if _FAST is None:
        ms = [m for m in models() if m]
        def _size(name):
            m = re.search(r":(\d+(?:\.\d+)?)b", str(name).lower())
            return float(m.group(1)) if m else 99.0
        _FAST = sorted(ms, key=_size)[0] if ms else ""
    return _FAST or None


def _prev_step_output() -> tuple:
    """Какво изкара ПРЕДИШНАТА стъпка — истинските ѝ редове от лога на цикъла.
    Така мозъкът не само обявява намерение, а съди и резултата преди него.

    ── ИМЕТО ИДВА ОТ ПУЛСА, НЕ ОТ ПОВТОРНО ЧЕТЕНЕ (17 авг 2026) ──────────────
    Дотук тази функция вземаше ПОСЛЕДНИЯ [STEP] ред от лога. Но beat() пише този
    ред ПРЕДИ да повика мозъка, значи последният ред е СЕГАШНАТА стъпка: върнатото
    „prev_name" беше самата стъпка, във всичките 53 реда от 17 авг. Нотариусът
    после сравняваше стъпка със себе си и наричаше това обещание.

    beat() вече хваща предишното име ПРЕДИ да напише новото и го пази
    (memory.heartbeat.previous_step). Тук се чете пазеното, а логът се ползва само
    за ТЯЛОТО — редовете между маркера на предишната стъпка и следващия маркер.
    """
    try:
        kept = None
        try:
            from memory.heartbeat import previous_step
            kept = previous_step()
        except Exception:
            kept = None
        if not kept:
            return "", ""          # първата стъпка: няма предшественик, и се казва

        logs = sorted((BASE / "memory" / "cycle_logs").glob("cycle_*.log"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            return kept, ""
        lines = logs[0].read_text(encoding="utf-8", errors="ignore").splitlines()[-400:]

        # Последният маркер, който НОСИ ИМЕТО НА ПАЗЕНАТА СТЪПКА — не просто
        # последният маркер, който вече е нашият.
        start = None
        for i in range(len(lines) - 1, -1, -1):
            s = lines[i].lstrip()
            if s.startswith("[STEP] ") and s.split("[STEP] ", 1)[1].strip() == kept:
                start = i
                break
        if start is None:
            return kept, ""

        body = []
        for l in lines[start + 1:]:
            if l.lstrip().startswith("[STEP] "):
                break              # стигнахме следващата стъпка — тялото свърши
            if l.strip():
                body.append(l.strip()[:200])
        return kept, "\n".join(body[-12:])
    except Exception:
        return "", ""


# Колко чака мозъкът на ЕДНА стъпка. Стои като явна константа, защото е
# компромис, не истина: твърде малко — мозъкът мълчи на всяка тежка стъпка;
# твърде много — един заспал модел бави целия цикъл ~50 пъти.
ATTEND_TIMEOUT = 60

# ── THE STANCE ENUM, AND THE HISTORY THAT STILL HAS TO PARSE (23 Aug 2026) ──
# The model was asked to emit "върви|следи|пропусни" and three places compared
# against those literals. That is a contract written in a language the model is
# now told not to use, sitting in the last line of the one prompt that runs at
# every beat — the stream that produced 19 Chinese stances in a single night.
#
# NEW WRITES ARE ENGLISH. READS ACCEPT BOTH. memory/brain_step_log.jsonl has
# 1117 rows in it and memory/brain_journal.jsonl is append-only history; a
# migration that made yesterday unreadable would be deleting evidence by
# omission, which is the same defect as deleting it by hand.
STANCE_GO, STANCE_WATCH, STANCE_SKIP = "go", "watch", "skip"

# old literal -> new. Prefix matching, because the model has always been allowed
# to answer "пропусни, защото..." and the consumers used startswith().
STANCE_LEGACY = {
    "върви": STANCE_GO,
    "следи": STANCE_WATCH,
    "пропусни": STANCE_SKIP,
}


def normalise_stance(value) -> str:
    """One reader for both vocabularies. Unknown values return "" — an
    unrecognised stance must not silently become "go"."""
    v = str(value or "").strip().lower()
    if not v:
        return ""
    for name in (STANCE_GO, STANCE_WATCH, STANCE_SKIP):
        if v.startswith(name):
            return name
    for old, new in STANCE_LEGACY.items():
        if v.startswith(old):
            return new
    return ""


def _record_silence(step: str, prev_step: str | None, model: str, why: str,
                    sec: float, prompt_chars: int) -> None:
    """Мълчанието на мозъка е СЪБИТИЕ, не липса на събитие (законът, т.6).

    Без този запис „мозъкът е на всяка стъпка" е непроверимо твърдение: в
    дневника се виждат само стъпките, на които е ПРОГОВОРИЛ, и никой не може да
    различи «мозъкът реши да мълчи» от «мозъкът никога не беше попитан»."""
    doc = {"ts": _now(), "step": step, "prev_step": prev_step,
           "stance": "reflex:мълчание", "silent": True, "why": why,
           "sec": sec, "prompt_chars": prompt_chars, "model": f"local:{model}"}
    try:
        STEP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(STEP_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
    except Exception:
        pass


def attend(step: str) -> dict | None:
    """Мозъкът застава пред всяка стъпка: съди какво излезе от предишната и казва
    какво очаква от тази. Присъдата се пише в memory/brain_step_log.jsonl, а
    последната — в memory/brain_stance.json, откъдето стъпките могат да я четат
    (stance()). FAIL-OPEN и изключваема с CORTEX_BRAIN_ATTEND=0."""
    global _AVAILABLE
    import os
    if os.environ.get("CORTEX_BRAIN_ATTEND", "1") == "0":
        return None
    if _AVAILABLE is None:
        _AVAILABLE = bool(models())
    if not _AVAILABLE:
        return None
    mdl = _fast_model()
    if not mdl:
        return None

    prev_name, prev_out = _prev_step_output()
    plan = current_plan()
    # ── УМ, ДУХ И ТЯЛО + ЦЕЛ — В ЕДНО (Емил, 15 август 2026) ────────────────
    # Дотук ТУК имаше само УМ и ТЯЛО. Проверено ред по ред: този промпт носеше
    # плана, тялото, предишната стъпка и текущата — и НИТО ЕДНА дума от духа:
    # без канон, без цел, без граница, без памет. А точно този промпт е мозъкът
    # НА ВСЯКА СТЪПКА; think() го носи всичко, но think() се вика няколко пъти
    # на цикъл, докато attend() — при всеки beat.
    # Тоест законът, т.5 („Той носи тялото, духа и паметта си във ВСЯКА мисъл")
    # се спазваше на редките мисли и се нарушаваше на честите.
    # Цената е призната честно: духът е ~3 KB, тоест ~+800 токена на стъпка при
    # локален модел. Това е цената на това мозъкът да знае за какво съществува,
    # докато решава дали да пропусне стъпка. По-евтиният вариант — да му подадем
    # само „главното" от духа — е точно резенът, който днес отряза границата.
    prompt = (
        "You are the brain of CORTEX++ and you stand at every step of your own cycle.\n\n"
        f"SPIRIT (who you are, what you exist for, and where your limit is):\n{_spirit()}\n\n"
        f"MEMORY (your own earlier step verdicts):\n{_memory('step_stance', n=3)}\n\n"
        f"YOUR PLAN TODAY: focus={plan.get('focus')!r}; watching={plan.get('watch')!r}; "
        f"success test={str(plan.get('success_test'))[:120]!r}\n"
        f"BODY: {_body()}\n"
        # ── ПРАЗНАТА КЛЕТКА НЕ СЕ ПОДАВА (15 август 2026) ───────────────────
        # Първите два реални записа на attend() дадоха ЕДНО И СЪЩО празно
        # prev_step и ДВЕ ПРОТИВОПОЛОЖНИ присъди: веднъж prev_ok=true „изпълнена
        # успешно", веднъж prev_ok=false „не всички мрежи достигнаха нужната
        # точност" — при това вторият описваше проект за обучение на невронни
        # мрежи с екип, какъвто тук няма. 3B модел, изправен пред празна клетка,
        # я запълва с правдоподобна проза.
        # Затова празната клетка вече НЕ СЕ ПОКАЗВА. Не питаш за нещо, което го
        # няма, и после не филтрираш отговора — не даваш повод за отговор.
        + (f"PREVIOUS STEP: {prev_name}\n"
           f"ITS OUTPUT:\n{prev_out}\n\n" if (prev_name and prev_out) else
           "PREVIOUS STEP: NONE (this is the first step, or its output is not "
           "visible).\n"
           "Do NOT judge the previous step — you have no evidence about it. "
           "Leave prev_ok and prev_note empty.\n\n")
        # THE SECOND PROMPT BUILDER, AND THE ONE THAT DRIFTED FURTHEST. think()
        # runs a few times a cycle; this runs at EVERY beat — 63 times on the
        # 23 Aug night — and 19 of those 63 stances came back in Chinese. It is
        # also the one _memory() cannot help: nothing has ever called
        # remember('step_stance', ...), so its exemplar block has always been
        # empty and the gate in Part 2 has nothing to filter here. The pin is
        # the only thing that reaches this stream.
        + f"{LANGUAGE_PIN}\n\n"
        + f"NOW STARTING: {step}\n\n"
        + ('Answer ONLY with JSON: {"prev_ok": true/false, "prev_note": "short: '
           'what came out of the previous step", ' if (prev_name and prev_out) else
           'Answer ONLY with JSON: {')
        + '"stance": "go|watch|skip", "expect": "what you '
          'expect from this step (short)", "serves_goal": "in one sentence: how '
          'THIS step serves the goal, or why it does not"}\n'
        + ("Be short. If the previous step gave an empty or suspicious result — "
           "say so."
           if (prev_name and prev_out) else
           "Be short. Speak ONLY about the step that is starting now.")
        # Last here too, and it matters more here: this prompt ends with a JSON
        # shape whose `stance` values are the one enum in the system, and this
        # is the stream that produced 19 Chinese stances in one night.
        + "\n\n" + LANGUAGE_PIN
    )
    # ── МЪЛЧАНИЕТО СЕ ЗАПИСВА (законът, т.6) ───────────────────────────────
    # Дотук всяка несполука тук се връщаше като None БЕЗ СЛЕДА. Затова днешният
    # brain_step_log.jsonl съдържа ЕДИН ред за ~50 стъпки, а защо липсват
    # останалите 49 — никой не може да каже. Законът е изричен: „Мълчанието не е
    # присъда. Ако мозъкът не отговори, тялото пада на рефлекс — и това се
    # записва явно: reflex:* и защо." Мълчаливото None нарушаваше собствения му
    # закон и правеше диагнозата невъзможна.
    t0 = time.time()
    d, silence = None, None
    try:
        import requests as _rq
        _, base = _pick_model()
        r = _rq.post(f"{base}/api/chat", timeout=ATTEND_TIMEOUT, json={
            "model": mdl, "stream": False, "keep_alive": KEEP_ALIVE, "format": "json",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.1, "num_predict": 220}})
        r.raise_for_status()
        t = ((r.json().get("message") or {}).get("content") or "").strip()
        t = t.split("</think>")[-1].strip() if "</think>" in t else t
        d = json.loads(t[t.find("{"): t.rfind("}") + 1])
        if not isinstance(d, dict):
            d, silence = None, f"отговор, който не е обект: {type(d).__name__}"
    except Exception as e:
        silence = f"{type(e).__name__}: {e}"

    if d is None:
        _record_silence(step, prev_name, mdl, silence or "неизвестна причина",
                        round(time.time() - t0, 1), len(prompt))
        return None

    # ── ПРИСЪДА БЕЗ ДОКАЗАТЕЛСТВО СЕ ОТМЕНЯ ОТ ИЗВИКВАЩИЯ ──────────────────
    # Дори с поправения промпт моделът може да произнесе нещо за предишната
    # стъпка. Затова тук стои втора, механична преграда: няма ли доказателство,
    # няма присъда — независимо какво е казал. И казаното НЕ се изтрива, а се
    # пази в prev_ok_model_said, защото честотата на съчиняването е измерване:
    # без нея никога няма да знаем колко често мозъкът запълва празни клетки.
    _has_evidence = bool(prev_name) and bool(prev_out)
    _blocked = None
    if not prev_name:
        _blocked = "no_previous_step: това е първата стъпка — няма какво да се съди"
    elif not prev_out:
        _blocked = (f"no_visible_output: '{prev_name}' не е оставила видим изход — "
                    f"липсата на изход не е доказателство за провал")

    doc = {"ts": _now(), "step": step, "prev_step": prev_name or None,
           "prev_ok": (d.get("prev_ok") if _has_evidence else None),
           "prev_note": (str(d.get("prev_note", ""))[:300] if _has_evidence else None),
           "prev_verdict_blocked": _blocked,
           "prev_ok_model_said": (None if _has_evidence else d.get("prev_ok")),
           "prev_note_model_said": (None if _has_evidence
                                    else str(d.get("prev_note", ""))[:200] or None),
           "stance": normalise_stance(d.get("stance")) or STANCE_GO,
           "expect": str(d.get("expect", ""))[:300],
           # СЛУЖИ ЛИ ТАЗИ СТЪПКА НА ЦЕЛТА — питаме го, защото сега вече знае целта.
           "serves_goal": str(d.get("serves_goal", ""))[:300],
           "sec": round(time.time() - t0, 1),
           "model": f"local:{mdl}"}
    try:
        STEP_LOG.parent.mkdir(parents=True, exist_ok=True)
        if STEP_LOG.exists() and STEP_LOG.stat().st_size > 5_000_000:
            STEP_LOG.replace(STEP_LOG.with_suffix(".jsonl.1"))
        with open(STEP_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
        STANCE.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return doc


def stance(step: str | None = None) -> dict:
    """Какво каза мозъкът за текущата (или дадена) стъпка — за да може самата
    стъпка да се съобрази с него, вместо да я води само моят фиксиран ред."""
    try:
        d = json.loads(STANCE.read_text(encoding="utf-8"))
        return d if (step is None or d.get("step") == step) else {}
    except Exception:
        return {}


def skipped_by_brain(step: str) -> bool:
    """Мозъкът ИСКА да пропусне; графът казва МОЖЕ ЛИ. Действие само при двете.

    15 авг 2026 — падна ръчният списък „гръбнак от 7 стъпки". Kimi го събори с
    едно изречение: „критерият е сгрешен по същество, защото разделя по
    имплементационна обвивка, а не по семантична критичност... това не е гръбнак,
    а коремна кухина със спинален имплант." Прав беше: естетичен отчет в обвивка
    минаваше за пропускаем, а проверка на източник inline — за неприкосновена.
    Сега границата е СЛЕДСТВИЕ от графа (core.cycle_graph, MeTTa): пропуска се
    само стъпка, чийто продукт никой надолу не чака. Ако графът не знае —
    не се пропуска. Незнанието не е разрешение."""
    last = stance()
    if not last:
        return False
    wants = normalise_stance(last.get("stance")) == STANCE_SKIP
    if not wants:
        return False
    try:
        from core.cycle_graph import can_skip
        import json as _j
        from datetime import datetime as _dt
        try:                       # началото на ТОЗИ цикъл, не последните 24ч
            hb = _j.loads((BASE / "memory" / "heartbeat.json").read_text(encoding="utf-8"))
            since = _dt.fromisoformat(hb["cycle_id"]).timestamp()
        except Exception:
            since = None
        v = can_skip(step, since)
    except Exception as e:
        remember("skip_denied", f"{step}: графът не се зареди ({type(e).__name__})")
        return False
    ok = v.get("verdict") == "РАЗРЕШЕНО"
    remember("skip_decision",
             f"{step}: мозъкът иска пропускане; графът казва {v.get('verdict')} — {v.get('why')}",
             {"blockers": v.get("blockers", [])})
    return ok


def watching(step: str) -> bool:
    """„следи" вече значи нещо. Досега мозъкът можеше да каже 'следи' и това не
    водеше доникъде — дадена дума без последствие (хванато от Kimi: „каква е
    семантиката на 'следи'? никъде не е казано"). Сега стъпката се изпълнява, но
    се маркира като наблюдавана и излиза отделно в отчета на цикъла."""
    last = stance()
    return bool(last) and normalise_stance(last.get("stance")) == STANCE_WATCH


if __name__ == "__main__":
    import sys
    what = sys.argv[1] if len(sys.argv) > 1 else "brief"
    print(json.dumps(brief_cycle() if what == "brief" else debrief_cycle(),
                     ensure_ascii=False, indent=2))
