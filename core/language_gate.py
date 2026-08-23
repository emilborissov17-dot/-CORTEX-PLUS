#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/language_gate.py — NEVER USE A MODEL OUTPUT AS A FEW-SHOT EXAMPLE WITHOUT
VALIDATION.

THE FAILURE THIS EXISTS FOR
-----------------------------
core/brain.py::_memory(kind) hands the model its own five most recent same-kind
outputs as worked examples. With no language pin in the prompt, one spontaneous
drift became the example for the next call, and the ratchet never released:

    16 Aug   24 entries    0 Russian
    17 Aug   48 entries   17 Russian      ...............................RRRRRRRRRRRRRRRRR
    18 Aug   48 entries   48 Russian
    19-23 Aug            100% Russian, every day

The model never changed. Every one of those 360 verdicts is qwen2.5:3b, and
nothing in this repo contains Russian. The repo taught it the drift, one cycle
at a time, by feeding it back its own output as the definition of "correct".

So: a model output is a CANDIDATE exemplar, never an exemplar. This module is
the validation between the two.

WHY SCRIPT FRACTIONS AND NOT A LANGUAGE MODEL
-----------------------------------------------
The failure is Cyrillic and Han text where English was wanted. Counting letters
by Unicode block catches exactly that, deterministically, in microseconds, with
no dependency and no training data. A statistical language detector would be a
better judge of "is this English or Dutch" — a question nobody here is asking.

The thresholds are asymmetric on purpose, and 3% is STRICT — measured, after the
first draft of this docstring claimed otherwise. Two Bulgarian words inside a
210-letter English sentence is 9.5% and is rejected. Three percent is roughly one
Cyrillic word per thirty English ones, which in practice means: an English summary
may carry an axis name, and not a phrase.

That is the right side to err on here and the cost is bounded. A rejected entry
is not deleted and not hidden; it is written to the journal exactly as it was,
flagged, and merely not offered back to the model as an example of correct
output. The price of a false rejection is one lost exemplar. The price of a false
acceptance is six days of Russian, which is the thing that already happened.

Han 1%: there is no legitimate reason for a Han character to appear in this
system's output at all, so one in a hundred is already a report.

HONEST LIMIT: a model that answers in fluent French or German passes this gate.
That is not the observed failure and this module does not pretend to catch it.
If it ever happens, the second layer below is where it gets caught, and today
that layer is not installed.

    venv/Scripts/python.exe core/language_gate.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
JOURNAL = BASE / "memory" / "brain_journal.jsonl"

# Fractions OF LETTERS, not of characters. A JSON blob is mostly punctuation and
# digits; judging it by total characters would call every structured answer
# "English" because the braces outnumber the words.
MAX_CYRILLIC = 0.03
MAX_HAN = 0.01

# Below this a statistical detector is guessing, so the second layer is not
# consulted at all rather than consulted and disbelieved.
MIN_CHARS_FOR_DETECTOR = 60

OK = "OK"
NO_LETTERS = "NO_LETTERS"


# ---------------------------------------------------------------------------
# Layer 1 — the script census
# ---------------------------------------------------------------------------

def script_profile(text) -> dict:
    """Fractions of LETTER characters by script. Digits and punctuation ignored.

    `letters` is carried alongside because a fraction over three letters is not
    a measurement, and every caller needs to be able to see that.
    """
    latin = cyrillic = han = other = 0
    for ch in str(text or ""):
        if not ch.isalpha():
            continue
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
            han += 1
        elif 0x0400 <= o <= 0x04FF or 0x0500 <= o <= 0x052F:
            cyrillic += 1
        elif o < 0x0250:                       # Basic Latin + Latin-1 + Ext-A/B
            latin += 1
        else:
            other += 1
    n = latin + cyrillic + han + other
    if not n:
        return {"latin": 0.0, "cyrillic": 0.0, "han": 0.0, "other": 0.0,
                "letters": 0}
    return {"latin": latin / n, "cyrillic": cyrillic / n, "han": han / n,
            "other": other / n, "letters": n}


# ---------------------------------------------------------------------------
# Layer 2 — a statistical detector, IF one is already installed
# ---------------------------------------------------------------------------

def _detector():
    """(name, callable) for an installed detector, or (None, None).

    NOTHING IS INSTALLED BY THIS MODULE. A language gate that pip-installs a
    dependency at import time is a language gate that fails on the machine with
    no network, at the moment the network is why the cycle is degraded.
    """
    try:
        from langdetect import detect, DetectorFactory   # noqa: PLC0415
        DetectorFactory.seed = 0                          # deterministic
        return "langdetect", detect
    except Exception:
        pass
    try:
        import fasttext                                   # noqa: PLC0415, F401
        model_path = BASE / "models" / "lid.176.ftz"
        if model_path.exists():
            mdl = fasttext.load_model(str(model_path))

            def _detect(text):
                label = mdl.predict(str(text).replace("\n", " "), k=1)[0][0]
                return label.replace("__label__", "")
            return "fasttext", _detect
    except Exception:
        pass
    return None, None


_DETECTOR_NAME, _DETECT = _detector()


def active_layers() -> list:
    """Which checks are actually running. Printed, never assumed."""
    layers = [{"layer": "script_census", "active": True,
               "detail": "cyrillic > {:.0%} or han > {:.0%} rejects".format(
                   MAX_CYRILLIC, MAX_HAN)}]
    layers.append({
        "layer": "statistical_detector",
        "active": _DETECT is not None,
        "detail": ("{} installed; requires en on text >= {} chars".format(
            _DETECTOR_NAME, MIN_CHARS_FOR_DETECTOR) if _DETECT is not None
            else "no detector installed (langdetect/fasttext); NOT installed by "
                 "this module. The script census is the layer that catches the "
                 "observed failure, and it is active."),
    })
    return layers


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def is_english_enough(text) -> tuple:
    """(bool, reason). Reason is a short machine string like CYRILLIC_0.41.

    Text with no letters at all passes with NO_LETTERS: a summary that is pure
    numbers has no language to be wrong about, and rejecting it would quietly
    empty the exemplar pool for the kinds that answer with figures.
    """
    p = script_profile(text)
    if p["letters"] == 0:
        return True, NO_LETTERS
    if p["han"] > MAX_HAN:
        return False, "HAN_{:.2f}".format(p["han"])
    if p["cyrillic"] > MAX_CYRILLIC:
        return False, "CYRILLIC_{:.2f}".format(p["cyrillic"])
    if _DETECT is not None and p["letters"] >= MIN_CHARS_FOR_DETECTOR:
        try:
            lang = _DETECT(str(text))
        except Exception:
            return True, OK           # a detector that cannot answer does not veto
        if str(lang).lower()[:2] != "en":
            return False, "DETECTOR_{}".format(str(lang).upper()[:8])
    return True, OK


def verdict(text) -> dict:
    """The whole judgement, in the shape the journal stores."""
    ok, reason = is_english_enough(text)
    p = script_profile(text)
    return {"ok": bool(ok), "reason": reason,
            "profile": {"latin": round(p["latin"], 4),
                        "cyrillic": round(p["cyrillic"], 4),
                        "han": round(p["han"], 4),
                        "letters": p["letters"]}}


def entry_is_clean(entry: dict) -> tuple:
    """(bool, reason) for one journal row, stored verdict or computed on the fly.

    Rows written before this gate existed carry no `lang` field. They are judged
    from their stored summary AT READ TIME rather than being rewritten: the
    journal is append-only history, and history that lied is still evidence.
    """
    lang = entry.get("lang")
    if isinstance(lang, dict) and "ok" in lang:
        return bool(lang["ok"]), str(lang.get("reason") or "")
    return is_english_enough(entry.get("summary"))


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/language_gate.py --selftest")
    print()
    print("  ACTIVE LAYERS")
    for layer in active_layers():
        print("    {:<22} {:<6} {}".format(
            layer["layer"], "ON" if layer["active"] else "OFF", layer["detail"]))
    print()

    cases = [
        ("The indicator has not moved for 48 days, which suggests a frozen sensor.",
         True),
        ("Показателята 'co2_annual_mean' оставя без изменений за 48 дней подряд, "
         "что указывает на возможную замръзнала сензор или застой.", False),
        ("确认并修复NOAA锚点在气候和材料废物审查中的重复使用", False),
        ("The CLIMATE_GLOBAL_RISK_REVIEW axis reuses the NOAA anchor.", True),
        ('{"composite": 0.6282, "coverage": 11}', True),
        ("", True),
    ]
    print("  VERDICTS")
    for text, want in cases:
        ok, reason = is_english_enough(text)
        mark = "ok " if ok == want else "BAD"
        print("    [{}] {:<5} {:<16} {}".format(
            mark, str(ok), reason, (text[:52] or "(empty)")))
        assert ok == want, text[:40]

    print()
    p = script_profile("Материалът показва, че the indicator is frozen")
    print("  a mixed line: cyrillic={:.0%} latin={:.0%} letters={}".format(
        p["cyrillic"], p["latin"], p["letters"]))

    print()
    print("  HOW STRICT 3% ACTUALLY IS — measured, not asserted:")
    borderline = ("The axis CLIMATE_GLOBAL_RISK_REVIEW reuses the NOAA anchor, "
                  "which the report calls a повторно използване, and the "
                  "measurement accuracy drops as a result of that reuse across "
                  "both of the affected reviews in the current cycle window.")
    ok, reason = is_english_enough(borderline)
    print("    two Bulgarian words in a {}-letter English sentence -> "
          "cyrillic {:.1%}, ok={} ({})".format(
              script_profile(borderline)["letters"],
              script_profile(borderline)["cyrillic"], ok, reason))
    print("    that is a REJECTION, and the cost is one lost exemplar. The "
          "journal line is still written, flagged.")
    assert not ok, "the 3% threshold stopped being strict"

    print()
    print("  ONE HAN CHARACTER IN A LONG ENGLISH LINE IS STILL A REPORT:")
    one_han = "The step completed and the artefact was written to disk 是 " + \
              "and nothing else changed during this cycle at all."
    ok, reason = is_english_enough(one_han)
    print("    ok={} reason={}".format(ok, reason))

    print()
    print("  entry_is_clean on a row with a STORED verdict:")
    print("    {}".format(entry_is_clean(
        {"summary": "anything at all", "lang": {"ok": False, "reason": "CYRILLIC_0.90"}})))
    print("  entry_is_clean on a row with NO lang field (computed at read time):")
    print("    {}".format(entry_is_clean({"summary": "Это указывает на застой"})))

    print()
    print("  live journal: {}  exists={}".format(JOURNAL, JOURNAL.exists()))
    try:
        brain_src = (BASE / "core" / "brain.py").read_text(encoding="utf-8")
        # A CALL, NOT A MENTION. The first version of this check grepped for
        # "language_gate" and reported WIRED against a prompt comment that names
        # this module — the exact false-liveness reading this repo keeps finding.
        code = "\n".join(l for l in brain_src.splitlines()
                         if not l.lstrip().startswith("#"))
        wired = "_lang_verdict(" in code and "_entry_is_clean(" in code
        print("  core/brain.py  {}".format(
            "WIRED — remember() stamps and _memory() filters"
            if wired else
            "NOT WIRED — nothing validates an exemplar before it is used"))
    except OSError:
        pass
    print("  RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
