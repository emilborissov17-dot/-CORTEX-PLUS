#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_need_class.py — the need CLASS must reach the query and the acceptance (#41).

Born from the scheduled run of 2026-07-31: a `measurement_daily` need produced the query
"global happiness index 2023" — an ANNUAL REPORT search aimed at a DAILY slot. Four pages
were read, two of them PDFs that yield empty text, and nothing could possibly have filled
the slot. The class was known all along; it just never travelled.

Three changes, three fixture groups:
  decide()        the slot class and the CURRENT YEAR go into the prompt
  _is_pdf         a PDF result is skipped by name, not silently read as an empty page
  _cadence_match  an annual figure against a daily need is kept but marks the slot HUNGRY

No live model, no browser, no network.

  venv\\Scripts\\python.exe test\\test_need_class.py
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "browser_scout"))
import autonomous_scout as scout
import goal_impact as gi

YEAR = datetime.now(timezone.utc).year
FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

# ---------- need_class ----------
DAILY = "needs >= 1 live source(s) of class 'measurement_daily', has 0"
EVENT = "needs >= 1 live source(s) of class 'event_daily', has 0"
ANNUAL = "needs >= 1 live source(s) of class 'anchor_annual', has 0"
check("class read off the composer's wording", scout.need_class(DAILY) == "measurement_daily")
check("event_daily recognised", scout.need_class(EVENT) == "event_daily")
check("anchor_annual recognised", scout.need_class(ANNUAL) == "anchor_annual")
check("free-text need has no class", scout.need_class("a signal of social cohesion") is None)
check("None need is safe", scout.need_class(None) is None)

# ---------- decide(): the class and the year reach the prompt ----------
seen = {}
def spy(prompt, timeout=120, num_predict=300):
    seen["p"] = prompt
    return json.dumps({"search_query": "q", "target_metric": "m", "unit": "u",
                       "higher_is": "better"})
scout._local = spy

plan = scout.decide("SOCIAL_RELATIONS_REVIEW", DAILY)
p = seen["p"]
check("daily need: prompt demands daily cadence",
      "UPDATE DAILY" in p and "near real-time" in p)
check("daily need: prompt steers to live sources",
      "dashboards" in p and "data portals" in p)
check("daily need: prompt forbids annual reports and PDFs",
      "AVOID annual reports" in p and "PDF" in p)
check(f"daily need: current year {YEAR} is stated, not left to the model's prior",
      str(YEAR) in p)
check("daily need: the class itself is named", "measurement_daily" in p)
check("plan carries the class back for the trail", plan.get("need_class") == "measurement_daily")

scout.decide("X", ANNUAL)
check("annual need does NOT get the daily instruction",
      "UPDATE DAILY" not in seen["p"] and "anchor_annual" in seen["p"])

scout.decide("X", "some free-text need with no class")
check("classless need gets no cadence clause (nothing invented)",
      "UPDATE DAILY" not in seen["p"] and "anchor_annual" not in seen["p"])

check("explicit slot argument overrides the string",
      scout.decide("X", "free text", slot="event_daily").get("need_class") == "event_daily"
      and "UPDATE DAILY" in seen["p"])

# ---------- _is_pdf ----------
check("plain .pdf detected", scout._is_pdf("https://x.org/a/report.pdf"))
check("query string does not hide a pdf",
      scout._is_pdf("https://x.org/a/Report_0.pdf?download=1&v=2"))
check("fragment does not hide a pdf", scout._is_pdf("https://x.org/a/r.PDF#page=3"))
check("html page is not a pdf", not scout._is_pdf("https://x.org/report/2023/"))
check("'pdf' inside a path is not a pdf file",
      not scout._is_pdf("https://x.org/pdf-viewer/article"))
check("empty url is safe", not scout._is_pdf(""))
check("a named reason exists for the trail",
      "pdf" in scout.PDF_SKIP_REASON.lower() and "skip" in scout.PDF_SKIP_REASON.lower())

# ---------- _cadence_match ----------
check("annual figure against a DAILY need -> slot stays hungry",
      gi._cadence_match("Global Happiness Index 2023 annual report", DAILY) is False)
check("current-year figure satisfies the cadence",
      gi._cadence_match(f"as measured in {YEAR}", DAILY) is True)
check("an explicit daily marker satisfies it even with an old year",
      gi._cadence_match("updated daily; series began in 2019", DAILY) is True)
check("'real-time' counts as fresh", gi._cadence_match("real-time tracker, 2018 baseline", DAILY) is True)
check("no year and no marker is not held against it",
      gi._cadence_match("the number of active conflicts rose to 56", DAILY) is True)
check("event_daily is checked too",
      gi._cadence_match("2021 yearbook of disasters", EVENT) is False)
check("ANNUAL need: cadence is not applicable (None, not False)",
      gi._cadence_match("Global Happiness Index 2023", ANNUAL) is None)
check("classless need: not applicable",
      gi._cadence_match("something from 2019", "a free-text need") is None)

# ---------- cadence_match rides on the observation, and does NOT reject ----------
PAGE = ("The Global Happiness Index 2023 annual report was published. "
        "Life satisfaction averaged 5.5 across surveyed countries.")
GOOD = {"observation": "the global happiness index annual report was published",
        "evidence": "The Global Happiness Index 2023 annual report was published.",
        "value": None, "unit": "", "sign": "+", "magnitude": 0.3,
        "dimension": "dignity", "rationale": "wellbeing", "contested": False,
        "counterview": ""}
gi._RELEVANCE_GATE = False
gi._SIGN_GUARD = False
gi._STRUCTURAL = False
gi._local = lambda prompt, num_predict=350, **kw: json.dumps(GOOD)

o, why = gi.extract_goal_impact(PAGE, "SOCIAL_RELATIONS_REVIEW", DAILY, "http://x")
check("an annual observation is still ACCEPTED (cadence is a flag, not a gate)", o is not None)
check("...and carries cadence_match False", o is not None and o.get("cadence_match") is False)

o2, _ = gi.extract_goal_impact(PAGE, "SOCIAL_RELATIONS_REVIEW", ANNUAL, "http://x")
check("same observation against an ANNUAL need has cadence_match None",
      o2 is not None and o2.get("cadence_match") is None)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
