#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_needs_approvals.py — the Telegram approval UX + goal dedup, fixtures.

Two behaviours, both born from live use of the approval loop:

  ONE-TAP REPLIES — the brief names an id inline ("reply: OK 5dad"), which on a phone
  means selecting four characters out of a paragraph. After the brief lands, each reply
  string is also sent as its OWN message, bare, so it is copyable with a single tap.
  Telegram only (on ntfy every message is a separate notification), and fail-open: the
  brief is already delivered, so a failed extra must never downgrade a successful push.

  GOAL DEDUP — an approve_id is STABLE across cycles, so the same goal reappears in every
  brief. Without a guard a second "OK <id>" appends a twin: three identical
  SOCIAL_RELATIONS_REVIEW entries accumulated in improvement_proposals.json this way
  (30 Jul 10:45, 31 Jul 11:08, 31 Jul 11:56) before this existed. Promotions already
  deduped; goals did not.

No network, no real config, no real proposals file.

  venv\\Scripts\\python.exe test\\test_needs_approvals.py
"""
import json, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "needs"))
sys.path.insert(0, str(REPO / "experiments" / "composers"))
import approve_reader as A
import needs_report as N

_REAL_REQUESTS = sys.modules.get("requests")
FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

# ---------- goal dedup ----------
tmp = Path(tempfile.mkdtemp()) / "proposals.json"
tmp.write_text(json.dumps({"proposals": []}), encoding="utf-8")
A.PROPOSALS = tmp
SPEC = {"type": "accept_goal", "axis": "SOCIAL_RELATIONS_REVIEW",
        "proposal": {"measurable_goal": "Social Relations Review score increases by 10%",
                     "authored_by": "local:qwen2.5:3b", "moral_check": "passed"},
        "need": "furthest from the goal"}

def _n():
    return len(json.loads(tmp.read_text(encoding="utf-8"))["proposals"])

r1 = A._apply_goal(SPEC, "123")
check("first accept appends", r1.get("ok") and not r1.get("duplicate") and _n() == 1)

r2 = A._apply_goal(SPEC, "123")
check("second accept is a no-op, not a twin",
      r2.get("ok") and r2.get("duplicate") and _n() == 1
      and "already accepted" in (r2.get("note") or ""))

A._apply_goal(SPEC, "123")
check("third accept still a no-op (the live 'OK d24e' case)", _n() == 1)

check("no-op is flagged distinctly from a real accept, so the reply can differ",
      bool(r1.get("duplicate")) is False and bool(r2.get("duplicate")) is True)

A._apply_goal({**SPEC, "axis": "WATER_REVIEW"}, "123")
check("a different axis still appends (dedup is not a blanket block)", _n() == 2)

A._apply_goal({**SPEC, "proposal": {**SPEC["proposal"],
                                    "measurable_goal": "a genuinely different goal"}}, "123")
check("a different goal on the same axis still appends", _n() == 3)

# ---------- one-tap extras ----------
sent = []
class _FakeRequests:
    @staticmethod
    def post(url, **kw):
        sent.append((url, kw.get("json") or {"_data": kw.get("data")}))
        return object()
sys.modules["requests"] = _FakeRequests

N.NOTIFY_CFG = Path(tempfile.mkdtemp()) / "notify.json"
N.NOTIFY_CFG.write_text(json.dumps({"channel": "telegram", "token": "T", "chat_id": "C"}),
                        encoding="utf-8")
N.PUSH_STATE = Path(tempfile.mkdtemp()) / "push.json"

REP = {"ts": "2026-07-31T00:00:00+00:00", "state": {},
       "items": [
           {"domain": "MIND", "severity": "medium", "need": "n1", "approve_id": "5dad",
            "approve": {"label": "Climate <- NASA"}},
           {"domain": "MIND", "severity": "medium", "need": "n2", "approve_id": "0a38",
            "approve": {"label": "Water <- USGS"}},
           {"domain": "BODY", "severity": "high", "need": "a high item with no approve_id"},
       ]}

check("push reports sent", N._push_status(REP) == "sent:telegram")
texts = [b.get("text") for _, b in sent]
check("the brief goes first", len(texts) >= 1 and "CORTEX needs" in (texts[0] or ""))
check("one extra per APPROVAL item — the high-only item gets none",
      texts[1:] == ["OK 5dad", "OK 0a38"])
check("each extra is EXACTLY the reply text and nothing else",
      all(t == t.strip() and t.startswith("OK ") and "\n" not in t for t in texts[1:]))
check("the inline hint stays in the brief (extras are an addition, not a move)",
      "(reply: OK 5dad)" in texts[0])
check("count recorded on the report", REP.get("_one_tap_sent") == 2)

sent.clear()
N.PUSH_STATE.write_text("{}", encoding="utf-8")
N._push_status({"ts": "t", "state": {},
                "items": [{"domain": "BODY", "severity": "high", "need": "x"}]})
check("no approval items -> brief only, zero extras", len(sent) == 1)

# an extra that fails must not downgrade a delivered push
sent.clear()
N.PUSH_STATE.write_text("{}", encoding="utf-8")
calls = {"n": 0}
class _FlakyRequests:
    @staticmethod
    def post(url, **kw):
        calls["n"] += 1
        if calls["n"] > 1:
            raise ConnectionError("extra failed")
        sent.append(url)
        return object()
sys.modules["requests"] = _FlakyRequests
check("failing extra still reports sent (fail-open)", N._push_status(REP) == "sent:telegram")

# never leave a stubbed requests behind for a sibling suite
if _REAL_REQUESTS is not None:
    sys.modules["requests"] = _REAL_REQUESTS
else:
    sys.modules.pop("requests", None)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
