#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/phase_debrief.py — THE SYSTEM SAYS WHAT JUST HAPPENED, IN FOUR FIELDS.

At the end of each phase the brain writes four things and nothing else:

    what      one sentence, and it MUST cite a number that came from this
              phase's own data
    verdict   exactly one of OK | DEGRADED | BROKEN
    risk      what could go wrong next because of what just happened
    do        the one thing a human should consider doing

LOCAL MODEL ONLY. This is a self-directed call in the sense of
core/backend_policy.SELF_DIRECTED: it must work precisely when the cloud is
gone, because a dead cloud is the thing most worth debriefing. It also must not
charge its latency to a step's ceiling.

WHY "what" MUST CARRY A NUMBER
-------------------------------
Without that rule the model writes "the phase completed successfully" for a
phase that produced nothing — which is the same defect core/phase_report.py
exists to catch, restated in prose. A number from the phase's own data is the
cheapest available proof that the sentence is ABOUT this phase rather than
about phases in general.

THE REJECTION PATH IS THE POINT
--------------------------------
A debrief is REJECTED and recorded as rejected, never published, when:

  * "what" cites no number from the phase's own data
  * ANY CJK character appears anywhere in the output
  * "verdict" is not one of the three words

The CJK rule is not hypothetical. On 20 August 2026 memory/brain_stance.json
was written entirely in Chinese by local:qwen2.5:3b — all four fields — for a
step 20 minutes before the cycle was killed:

    prev_note   前一天分析结果为正常，未发现异常情况。
    expect      继续进行共享锚点值的冲突解决和深时风险审查盲区定义工作

The operator who has to judge that cannot read it. An unreadable verdict is not
a verdict. Rejections are written to memory/phase_debriefs/<cycle>/<PHASE>.
rejected.json so that a model which keeps failing this is visible rather than
merely silent.

WHICH MODEL, AND ONE RETRY (21 August 2026)
--------------------------------------------
The 21 Aug cycle closed six phases and REJECTED six debriefs — all six for the
same reason, "'what' cites no number at all", all six written by
local:qwen2.5:3b. A gate that refuses everything teaches the operator to stop
reading it, so two things changed and neither weakens the gate:

  * THE MODEL. brain.think(fast=True) picks the SMALLEST installed model, which
    is how a 3B ended up judging phases. A debrief happens seven times a cycle,
    not seventy, so it can afford qwen3:8b. The choice goes through
    core/self_experiment.ALLOWED_KNOBS, so it is a knob an experiment can vary
    rather than a constant somebody has to remember.

  * ONE RETRY, SHARPENED. The first prompt SAYS "cite a number". The second one
    SHOWS which numbers exist and quotes the exact rejection reason back. A
    model that writes "the phase completed successfully" has not refused the
    rule — it has failed to connect it to the numbers in front of it. Exactly
    one retry: one attempt is rude to an instrument that misheard the question,
    three is pressing until it invents something. Both attempts are kept in
    `attempt_log`, so a judge that only ever passes on the second try is
    visible.

    venv\\Scripts\\python.exe core/phase_debrief.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.phase_report import REPO, safe_cycle_dir  # noqa: E402

VERDICTS = ("OK", "DEGRADED", "BROKEN")
FIELDS = ("what", "verdict", "risk", "do")

# CJK unified ideographs, plus the Hiragana/Katakana and Hangul blocks. Cyrillic
# and Latin are both fine — the system is bilingual by design.
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]")

NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")

PURPOSE = "phase_debrief"   # core/backend_policy.SELF_DIRECTED


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def out_dir(cycle_id: str, base: pathlib.Path | None = None) -> pathlib.Path:
    return ((base or REPO) / "memory" / "phase_debriefs" /
            safe_cycle_dir(cycle_id))


# ---------------------------------------------------------------------------
# The judge
# ---------------------------------------------------------------------------

def numbers_in(text: str) -> set[str]:
    return {m.group(0).replace(",", ".") for m in NUMBER.finditer(str(text or ""))}


def evidence_numbers(evidence: dict) -> set[str]:
    """Every number that appears anywhere in the phase's own data."""
    return numbers_in(json.dumps(evidence, ensure_ascii=False, default=str))


def validate(debrief: dict, evidence: dict) -> tuple[bool, list[str]]:
    """Returns (accepted, reasons_for_rejection). Never raises."""
    reasons: list[str] = []

    if not isinstance(debrief, dict):
        return False, [f"not an object: {type(debrief).__name__}"]

    for field in FIELDS:
        if not str(debrief.get(field) or "").strip():
            reasons.append(f"missing or empty field {field!r}")

    verdict = str(debrief.get("verdict") or "").strip().upper()
    if verdict not in VERDICTS:
        reasons.append(
            f"verdict {debrief.get('verdict')!r} is not one of {'/'.join(VERDICTS)}")

    blob = " ".join(str(debrief.get(f) or "") for f in FIELDS)
    found_cjk = CJK.findall(blob)
    if found_cjk:
        reasons.append(
            f"contains CJK characters ({''.join(found_cjk[:8])}…) — an operator "
            f"who cannot read the verdict cannot act on it")

    said = numbers_in(debrief.get("what"))
    from_phase = evidence_numbers(evidence)
    if not said:
        reasons.append("'what' cites no number at all")
    elif not (said & from_phase):
        reasons.append(
            f"'what' cites {sorted(said)[:4]} but none of those appear in this "
            f"phase's own data — the sentence is not about this phase")

    return (not reasons), reasons


# ---------------------------------------------------------------------------
# Asking the local brain
# ---------------------------------------------------------------------------

PROMPT_BG = """Ти си CORTEX++. Току-що приключи фаза {phase} от собствения ти цикъл.

ДАННИТЕ НА ФАЗАТА:
{evidence}

Напиши РОВНО четири полета, като JSON и нищо друго:
  what    — едно изречение какво стана. ЗАДЪЛЖИТЕЛНО цитирай число от данните горе.
  verdict — точно една от думите: OK, DEGRADED, BROKEN
  risk    — какво може да се обърка след това заради станалото
  do      — едно нещо, което човек да обмисли

Пиши на български или английски. НЕ пиши на китайски, японски или корейски —
човекът, който чете това, не ги чете."""

# ── ВТОРИЯТ ОПИТ (21 август 2026) ──────────────────────────────────────────
# Първият промпт КАЗВА „цитирай число". Вторият ПОКАЗВА кои числа са налични и
# защо първият опит е отхвърлен. Разликата не е учтивост: моделът, който пише
# „фазата приключи успешно", не е отказал да цитира число — той не е свързал
# изискването с конкретните числа пред себе си. Един опит е грубост към уред,
# който не е разбрал въпроса; три опита са настояване, докато не съчини.
# Затова точно един.
PROMPT_SHARP = """Ти си CORTEX++. Приключи фаза {phase} от собствения ти цикъл.

ПЪРВИЯТ ТИ ОТГОВОР БЕШЕ ОТХВЪРЛЕН. Причина:
{why}

ДАННИТЕ НА ФАЗАТА:
{evidence}

ЧИСЛАТА, КОИТО ИМАШ ПРАВО ДА ЦИТИРАШ (други няма да бъдат приети):
{numbers}

Напиши РОВНО четири полета, като JSON и нищо друго:
  what    — едно изречение. То ТРЯБВА да съдържа поне едно от числата по-горе,
            написано точно както е дадено.
  verdict — точно една от думите: OK, DEGRADED, BROKEN
  risk    — какво може да се обърка след това заради станалото
  do      — едно нещо, което човек да обмисли

Само български или английски. Никакви йероглифи."""

# The model that writes the debriefs. qwen2.5:3b was the default because
# brain.think(fast=True) picks the SMALLEST installed model, and on 21 Aug 2026
# it failed the number gate on all six phases that closed — six for six, every
# one with 'what' citing no number at all. The judge of a phase is not a call
# that repeats dozens of times per cycle; it happens seven times, so it can
# afford the bigger model.
DEBRIEF_MODEL = "qwen3:8b"

BASE_PROMPT, SHARP_PROMPT = "base", "sharpened"

# How long the FIRST attempt may take and still leave room for a second.
# Measured 21 Aug 2026: qwen3:8b writes one debrief in 124.5 s.
RETRY_BUDGET_SEC = 150


def debrief_model() -> str:
    """The model to use — the experiment overlay may vary it, within the
    choices core/self_experiment.ALLOWED_KNOBS declares."""
    try:
        from core.self_experiment import knob
        return knob("debrief_model", default=DEBRIEF_MODEL) or DEBRIEF_MODEL
    except Exception:
        return DEBRIEF_MODEL


def prompt_variant() -> str:
    try:
        from core.self_experiment import knob
        return knob("debrief_prompt", default=BASE_PROMPT) or BASE_PROMPT
    except Exception:
        return BASE_PROMPT


def _numbers_menu(evidence: dict, limit: int = 24) -> str:
    """The numbers actually present in this phase's data, as a list."""
    found = sorted(evidence_numbers(evidence),
                   key=lambda s: (len(s), s))[:limit]
    return ", ".join(found) if found else "(няма нито едно число в данните)"


def ask_local(phase: str, evidence: dict, model: str | None = None,
              why: str | None = None) -> dict | None:
    """Ask the LOCAL brain only. Returns the parsed object or None.

    `why` switches to the sharpened prompt: it is the rejection reason from the
    first attempt, handed back so the second attempt answers the actual
    objection instead of repeating the same shape.
    """
    try:
        from core.brain import think
    except Exception:
        return None
    ev = json.dumps(evidence, ensure_ascii=False, indent=2)[:2500]
    sharpened = bool(why) or prompt_variant() == SHARP_PROMPT
    question = (PROMPT_SHARP.format(phase=phase, evidence=ev,
                                    why=why or "нямаше число в 'what'",
                                    numbers=_numbers_menu(evidence))
                if sharpened else
                PROMPT_BG.format(phase=phase, evidence=ev))
    try:
        said = think(
            role=f"съдия на фаза {phase}",
            question=question,
            schema={f: "" for f in FIELDS},
            kind="phase_debrief",
            model_override=model or debrief_model(),
        )
        return said if isinstance(said, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Rendering — Bulgarian for Telegram, English for console
# ---------------------------------------------------------------------------

def render_console(phase: str, d: dict) -> str:
    return (f"[DEBRIEF] {phase}: {d['verdict']}\n"
            f"  what: {d['what']}\n"
            f"  risk: {d['risk']}\n"
            f"  do:   {d['do']}")


def render_telegram(phase: str, d: dict) -> str:
    return (f"CORTEX++ · фаза {phase} · {d['verdict']}\n"
            f"Какво: {d['what']}\n"
            f"Риск: {d['risk']}\n"
            f"Да се направи: {d['do']}")


# ---------------------------------------------------------------------------
# The one entry point
# ---------------------------------------------------------------------------

def debrief_phase(phase: str, cycle_id: str, evidence: dict,
                  base: pathlib.Path | None = None,
                  asker=None) -> dict:
    """Ask, judge, ONE sharpened retry, then write the debrief or the rejection.

    Returns {"accepted": bool, ...}. Never raises: a debrief that cannot be
    produced must not take a phase down with it.
    """
    ask = asker or ask_local
    attempts = []
    started = time.time()

    said = ask(phase, evidence)
    accepted, reasons = (False, ["the local brain returned nothing"]) \
        if said is None else validate(said, evidence)
    attempts.append({"prompt": BASE_PROMPT, "said": said,
                     "accepted": accepted, "rejected_because": reasons})

    # ── ЕДИН ВТОРИ ОПИТ, С ИЗОСТРЕН ПРОМПТ ─────────────────────────────────
    # Не защото моделът заслужава втори шанс, а защото първият отказ носи
    # информация, която първият промпт не е носел: КОЕ точно е сгрешено и кои
    # числа са допустими. Ако и вторият падне, отказът се записва с ДВАТА
    # отговора — история на един провалил се съдия, а не един анонимен ред.
    # ── ВТОРИЯТ ОПИТ ИМА БЮДЖЕТ ────────────────────────────────────────────
    # Измерено на живо: qwen3:8b пише един дебриф за 124.5 s. Затварянето на
    # фаза става ВЪТРЕ в beat(), тоест закъснението се плаща от тавана на
    # стъпката, която току-що е започнала. Един опит е поносим; два прави 250 s
    # срещу таван от 900 s, а това вече е причина стъпка да бъде убита заради
    # съдията си. Затова вторият опит се пуска само ако първият е свършил
    # достатъчно бързо — и когато не се пусне, отказът го КАЗВА, вместо да
    # изглежда като модел, който не е бил питан втори път.
    if not accepted and (time.time() - started) > RETRY_BUDGET_SEC:
        reasons = reasons + [
            f"no retry: the first attempt took {time.time() - started:.0f}s, "
            f"past the {RETRY_BUDGET_SEC}s budget — a second call would be "
            f"charged to the step that just started"]
    elif not accepted:
        why = "; ".join(reasons)[:400]
        # An injected asker (tests, fixtures) may take only (phase, evidence).
        # Deciding that by INSPECTION rather than by catching TypeError matters:
        # a TypeError raised INSIDE a real asker would otherwise be swallowed
        # and read as "this asker has no retry", hiding a live bug.
        import inspect
        try:
            takes_why = "why" in inspect.signature(ask).parameters
        except (TypeError, ValueError):
            takes_why = False
        retry = ask(phase, evidence, why=why) if takes_why else None
        if retry is not None:
            ok2, reasons2 = validate(retry, evidence)
            attempts.append({"prompt": SHARP_PROMPT, "said": retry,
                             "accepted": ok2, "rejected_because": reasons2})
            if ok2:
                said, accepted, reasons = retry, True, []
            else:
                said, reasons = retry, reasons2

    record = {
        "ts": _now(),
        "phase": phase,
        "cycle_id": cycle_id,
        "accepted": accepted,
        "purpose": PURPOSE,
        "model": debrief_model(),
        "attempts": len(attempts),
        "seconds": round(time.time() - started, 1),
        "attempt_log": attempts,
        "debrief": said,
        "rejected_because": reasons,
    }
    if accepted:
        record["debrief"] = {**said,
                             "verdict": str(said["verdict"]).strip().upper()}
        record["console"] = render_console(phase, record["debrief"])
        record["telegram"] = render_telegram(phase, record["debrief"])

    try:
        d = out_dir(cycle_id, base)
        d.mkdir(parents=True, exist_ok=True)
        name = f"{phase}.json" if accepted else f"{phase}.rejected.json"
        (d / name).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        record["written_to"] = str(d / name)
    except Exception as exc:  # noqa: BLE001
        record["written_to"] = f"{type(exc).__name__}: {exc}"

    if accepted:
        print(record["console"])
        if len(attempts) > 1:
            print(f"[DEBRIEF] {phase}: accepted on the sharpened retry")
    else:
        print(f"[DEBRIEF] {phase}: REJECTED after {len(attempts)} attempt(s) "
              f"— {'; '.join(reasons)}")
    return record


def _selftest() -> int:
    import tempfile
    print("core/phase_debrief.py --selftest")
    evidence = {"axes_scored": 25, "measured_weight": 0, "total_weight": 173}
    ok = True

    cases = [
        ("good", {"what": "Scored 25 axes, 0 of 173 weight measured.",
                  "verdict": "DEGRADED", "risk": "composite is assertion",
                  "do": "wire a real metric"}, True),
        ("CJK", {"what": "已评分25个轴。", "verdict": "OK",
                 "risk": "无", "do": "无"}, False),
        ("no number", {"what": "The phase completed successfully.",
                       "verdict": "OK", "risk": "none", "do": "nothing"}, False),
        ("foreign number", {"what": "Scored 999 axes.", "verdict": "OK",
                            "risk": "none", "do": "nothing"}, False),
        ("bad verdict", {"what": "Scored 25 axes.", "verdict": "FINE",
                         "risk": "none", "do": "nothing"}, False),
    ]
    for name, payload, expected in cases:
        accepted, reasons = validate(payload, evidence)
        good = accepted is expected
        ok = ok and good
        print(f"  {'OK  ' if good else 'FAIL'}  {name:<15} accepted={accepted} "
              f"{reasons[0][:60] if reasons else ''}")

    with tempfile.TemporaryDirectory() as tmp:
        rec = debrief_phase("D_SCORE", "selftest", evidence,
                            base=pathlib.Path(tmp),
                            asker=lambda p, e: cases[1][1])
        wrote_rejection = str(rec["written_to"]).endswith("D_SCORE.rejected.json")
        print(f"  {'OK  ' if wrote_rejection else 'FAIL'}  rejection is written to disk")
        ok = ok and wrote_rejection

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
