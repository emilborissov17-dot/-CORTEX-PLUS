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

    venv\\Scripts\\python.exe core/phase_debrief.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
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


def ask_local(phase: str, evidence: dict, model: str | None = None) -> dict | None:
    """Ask the LOCAL brain only. Returns the parsed object or None."""
    try:
        from core.brain import think
    except Exception:
        return None
    try:
        said = think(
            role=f"съдия на фаза {phase}",
            question=PROMPT_BG.format(
                phase=phase,
                evidence=json.dumps(evidence, ensure_ascii=False, indent=2)[:2500]),
            schema={f: "" for f in FIELDS},
            kind="phase_debrief",
            fast=True,
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
    """Ask, judge, and write either the debrief or the rejection.

    Returns {"accepted": bool, ...}. Never raises: a debrief that cannot be
    produced must not take a phase down with it.
    """
    said = (asker or ask_local)(phase, evidence)
    accepted, reasons = (False, ["the local brain returned nothing"]) \
        if said is None else validate(said, evidence)

    record = {
        "ts": _now(),
        "phase": phase,
        "cycle_id": cycle_id,
        "accepted": accepted,
        "purpose": PURPOSE,
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
    else:
        print(f"[DEBRIEF] {phase}: REJECTED — {'; '.join(reasons)}")
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
