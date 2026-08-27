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
# THE RATIO — a number that moves before anyone reads a digest
# ---------------------------------------------------------------------------
#
# The drift ran for six days in plain sight. Every one of those verdicts was on
# disk, readable, and nobody read them, because reading a journal is something a
# human does when already suspicious. A ratio is a number that changes on its
# own and can be compared with a threshold without anyone forming a suspicion
# first.
#
# 98%: not a tuning knob. Below it, roughly one model output in fifty is not
# English, and the 17 Aug transition — 31 clean then 17 dirty in a row — would
# have crossed it inside one cycle. A looser threshold would have let 18 Aug
# happen before anyone was told.
PURITY_FLOOR = 0.98

# Under this many samples a ratio is an anecdote. Two dirty answers out of six
# is 67% and means nothing; the same two out of two hundred is a real signal.
MIN_SAMPLE = 20

QUARANTINE_FILE = BASE / "memory" / "language_quarantine.json"

# One alarm per rolling 24 hours. A ratio that stays below the floor is the
# SAME fact every cycle, and a fact repeated four times a night stops being read
# — which is exactly how the siren lost its meaning in the first place.
ALARM_EVERY_SEC = 24 * 3600


def _parse_ts(value):
    from datetime import datetime, timezone
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def purity_ratio(hours: int = 24, journal: Optional[pathlib.Path] = None,
                 now=None) -> tuple:
    """(ratio, n_total) of clean model outputs over a rolling window.

    Rows written before the gate existed carry no `lang` field and are judged
    from their stored summary as they are read, so the window is comparable
    across the change rather than starting at zero on the day it shipped.

    Returns (None, 0) when nothing is in the window: no ratio is not a ratio of
    zero, and a caller that cannot tell those apart will alarm on an idle night.
    """
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    path = pathlib.Path(journal or JOURNAL)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None, 0

    total = clean = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        ts = _parse_ts(row.get("ts"))
        if ts is None or ts < cutoff:
            continue
        total += 1
        ok, _reason = entry_is_clean(row)
        if ok:
            clean += 1
    if not total:
        return None, 0
    return clean / total, total


def purity_by_kind(hours: int = 24, journal: Optional[pathlib.Path] = None,
                   now=None) -> dict:
    """{kind: {"clean": n, "total": n, "ratio": f}} over the same window.

    The breakdown is what makes the alarm actionable. "92% clean" is a number;
    "constancy 0/24, everything else 100%" names the call site to go and look at.
    """
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    path = pathlib.Path(journal or JOURNAL)
    out: dict = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        ts = _parse_ts(row.get("ts"))
        if ts is None or ts < cutoff:
            continue
        kind = str(row.get("kind") or "unknown")
        rec = out.setdefault(kind, {"clean": 0, "total": 0, "ratio": 0.0})
        rec["total"] += 1
        ok, _reason = entry_is_clean(row)
        if ok:
            rec["clean"] += 1
    for rec in out.values():
        rec["ratio"] = round(rec["clean"] / rec["total"], 4) if rec["total"] else 0.0
    return out


def check_purity(hours: int = 24, journal: Optional[pathlib.Path] = None,
                 quarantine: Optional[pathlib.Path] = None,
                 sender=None, now=None) -> dict:
    """Measure, and alarm at most once per rolling 24 hours. NEVER RAISES.

    `sender(subject, detail)` is the seam the tests hold. The default is
    supervisor.alarm_human at ALARM level — the same one path to the phone that
    COMMAND 23 reserved, not a second channel.

    WHY ALARM AND NOT NOTICE. COMMAND 23 reserved the siren for
    halt_and_call_human, a red-line threshold, and a death. This is the second
    of those: a threshold a human set, crossed now. It is also the failure that
    ran for six days without anyone being told, which is the argument for it
    being loud rather than filed for the morning.
    """
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    qpath = pathlib.Path(quarantine or QUARANTINE_FILE)

    result = {"ts": now.isoformat(), "window_hours": hours, "ratio": None,
              "n_total": 0, "floor": PURITY_FLOOR, "min_sample": MIN_SAMPLE,
              "verdict": None, "alarmed": False, "written": False, "why": ""}
    try:
        ratio, total = purity_ratio(hours, journal, now)
        result["ratio"] = None if ratio is None else round(ratio, 4)
        result["n_total"] = total

        if total < MIN_SAMPLE:
            result["verdict"] = "INSUFFICIENT_SAMPLE"
            result["why"] = ("{} model output(s) in {}h; a ratio under {} "
                             "samples is an anecdote".format(total, hours,
                                                             MIN_SAMPLE))
            return result

        if ratio >= PURITY_FLOOR:
            result["verdict"] = "OK"
            result["why"] = "{:.1%} clean over {} outputs".format(ratio, total)
            return result

        result["verdict"] = "BELOW_FLOOR"
        by_kind = purity_by_kind(hours, journal, now)
        result["by_kind"] = by_kind
        result["why"] = "{:.1%} clean over {} outputs, floor is {:.0%}".format(
            ratio, total, PURITY_FLOOR)

        # Read the previous stamp BEFORE overwriting it, or the rate limit
        # resets itself every time it fires.
        last_alarm = None
        try:
            prev = json.loads(qpath.read_text(encoding="utf-8"))
            last_alarm = _parse_ts(prev.get("last_alarm_at"))
        except Exception:
            pass
        due = (last_alarm is None
               or (now - last_alarm).total_seconds() >= ALARM_EVERY_SEC)

        payload = dict(result)
        payload["last_alarm_at"] = (now.isoformat() if due
                                    else (last_alarm.isoformat()
                                          if last_alarm else None))
        payload["alarmed"] = bool(due)
        # SET BEFORE THE SNAPSHOT IS WRITTEN, not after. `payload` is copied
        # from `result` above, and result["written"] was only set once the file
        # had landed — which is after the copy, so the persisted file said
        # "written": false EVERY TIME, including the times it wrote perfectly.
        # A reader checking that field would conclude the quarantine record had
        # failed to save while holding the saved record in their hand.
        #
        # Claiming it before the write is not optimism: if the write raises
        # there is no file, so there is no false claim on disk to read. The
        # field can only ever be seen inside a file that exists.
        payload["written"] = True

        try:
            qpath.parent.mkdir(parents=True, exist_ok=True)
            qpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
            result["written"] = True
        except Exception as exc:                        # noqa: BLE001
            result["why"] += " (quarantine write failed: {})".format(
                type(exc).__name__)

        if not due:
            result["why"] += " (alarm rate-limited: one per 24h)"
            return result

        worst = sorted(by_kind.items(), key=lambda kv: kv[1]["ratio"])[:4]
        detail = ("Language purity {:.1%} over the last {}h ({} model outputs, "
                  "floor {:.0%}).\n".format(ratio, hours, total, PURITY_FLOOR)
                  + "\n".join("  {}: {}/{} clean".format(k, v["clean"],
                                                         v["total"])
                              for k, v in worst)
                  + "\n\nThe model is answering in a language it was told not "
                    "to. Exemplars from those kinds are already being withheld "
                    "(core/language_gate.py); this says the OUTPUT is still "
                    "drifting.\nRead: memory/language_quarantine.json")
        try:
            if sender is not None:
                sender("language purity below floor", detail)
            else:
                import supervisor                       # noqa: PLC0415
                supervisor.alarm_human(
                    "language purity below floor", detail,
                    dedup_key="language_purity:{}".format(
                        now.strftime("%Y-%m-%d")),
                    trigger="MANUAL",
                    level=supervisor.ALARM)
            result["alarmed"] = True
        except Exception as exc:                        # noqa: BLE001
            result["why"] += " (alarm failed: {}: {})".format(
                type(exc).__name__, exc)
        return result
    except Exception as exc:                            # noqa: BLE001
        # A ratio that cannot be computed must not cost a cycle. It is a
        # measurement about the cycle, not a step of it.
        result["verdict"] = "CHECK_FAILED"
        result["why"] = "{}: {}".format(type(exc).__name__, exc)
        return result


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
    ratio, total = purity_ratio(24)
    print("  live purity   last 24h: {} over {} output(s){}".format(
        "n/a" if ratio is None else "{:.1%}".format(ratio), total,
        "  [INSUFFICIENT SAMPLE]" if total < MIN_SAMPLE else
        ("  [BELOW FLOOR {:.0%}]".format(PURITY_FLOOR)
         if ratio is not None and ratio < PURITY_FLOOR else "  [OK]")))
    for kind, rec in sorted(purity_by_kind(24).items(),
                            key=lambda kv: kv[1]["ratio"]):
        print("      {:<18} {}/{} clean".format(kind, rec["clean"], rec["total"]))
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
