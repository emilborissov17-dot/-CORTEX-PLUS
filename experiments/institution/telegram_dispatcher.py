#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/institution/telegram_dispatcher.py — ONE FETCH, ONE OFFSET, TWO READERS.

THE DEFECT THIS EXISTS FOR, measured 18 September 2026
------------------------------------------------------
Emil replied "NOTHING" to institution #0's message 682 at about 18:15 local.
The witness reader polled and saw zero updates. Diagnosis:

    getWebhookInfo      url ''            no webhook
    getUpdates          0 updates         nothing pending
    telegram_offset.json {"offset": 172872863, "ts": "2026-09-18T15:10:02Z"}
    institution_offset.json  ABSENT
    schtasks \\CORTEX_Approvals   Repeat: Every 1 Minute(s)   Status: Ready
    approvals_ledger.jsonl  last entry 2026-09-12 — the reply is NOWHERE

`getUpdates` acknowledges server-side PER BOT TOKEN. When approve_reader polls
with `offset=its_offset+1`, Telegram DELETES every update below that id — for
every reader of that token, not just for it. It runs every minute, so it won
every race, and because it matches only `OK <id>` / `NO <id>` it dropped the
reply without recording it anywhere.

I GOT THIS WRONG WHEN I BUILT THE WITNESS READER. Giving it its own offset file
was the right instinct aimed at the wrong mechanism: the offset FILE was never
the shared thing — the ACK is. Two independent readers on one token cannot both
work, and no number of offset files fixes it.

WHAT THIS DOES
--------------
One `getUpdates` with one offset, then routes by the first word:

    OK <id> / NO <id>      -> approve_reader.apply_updates(...)  UNCHANGED
    USED|NOTHING|COUNTERMANDED -> witness_reader.apply_to_latest(...)
    anything else          -> memory/institution_witness.jsonl as unparsed

APPROVE_READER'S REFUSAL BOUNDARY IS NOT TOUCHED. Its decision logic was moved
into `apply_updates()` without a line changing: only the configured chat_id may
approve, only OK/NO are matched, only the three action types are applied. This
file hands it a list instead of letting it fetch one; it decides exactly what it
decided before. Widening that parser so one reader could serve both purposes was
the other way to fix this and it is the wrong one — the boundary is a feature.

NOTHING IS EVER GUESSED. A message that matches neither grammar is logged with
its text and the reason, and changes nothing. That is the whole point: the
witness bit is worth having because a human stated it.

  venv\\Scripts\\python.exe experiments/institution/telegram_dispatcher.py
  venv\\Scripts\\python.exe experiments/institution/telegram_dispatcher.py --selftest
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "needs"))

CHANNEL = REPO / "memory" / "notify_channel.json"
# THE ESTABLISHED OFFSET FILE, deliberately. It already holds a real offset
# (172872863) and approve_reader has been keeping it since long before this
# experiment. A fresh file would re-read months of history on the first run.
OFFSET = REPO / "memory" / "telegram_offset.json"
UNPARSED = REPO / "memory" / "institution_witness.jsonl"

APPROVE_PREFIXES = ("OK", "NO")
WITNESS_PREFIXES = ("USED", "NOTHING", "COUNTERMANDED")
# 25 Sep 2026 (task #9b): "SIGN <row_id> <row_sha256>" signs a forward row;
# approve_reader.apply_signature checks the sha against the row file and writes
# experiments/institution/signatures.jsonl. The model never writes a signature.
SIGN_PREFIXES = ("SIGN",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tg(token: str, method: str, **params):
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot%s/%s" % (token, method),
                                 data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def route(text: str) -> str:
    """'approve' | 'witness' | 'unparsed', by the FIRST WORD only.

    Deliberately not a search: a message containing the word "nothing" somewhere
    in a sentence is not a witness verdict, and treating it as one would invent
    the bit this experiment exists to collect honestly.
    """
    head = (text or "").strip().split(" ", 1)[0].upper()
    if head in APPROVE_PREFIXES:
        return "approve"
    if head in WITNESS_PREFIXES:
        return "witness"
    if head in SIGN_PREFIXES:
        return "sign"
    return "unparsed"


def _record_unparsed(update_id, text, why) -> None:
    UNPARSED.parent.mkdir(parents=True, exist_ok=True)
    with UNPARSED.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _now(), "update_id": update_id, "text": text,
                             "status": "unparsed", "why": why}, ensure_ascii=False) + "\n")


def run() -> dict:
    cfg = json.loads(CHANNEL.read_text(encoding="utf-8"))
    token, chat_id = cfg["token"], str(cfg["chat_id"])
    offset = 0
    if OFFSET.exists():
        try:
            offset = int(json.loads(OFFSET.read_text(encoding="utf-8"))["offset"])
        except (ValueError, KeyError, json.JSONDecodeError):
            offset = 0

    data = _tg(token, "getUpdates", offset=offset + 1, timeout=0)
    if not data.get("ok"):
        return {"ok": False, "why": "getUpdates ok=false: %s" % data.get("description")}
    updates = data.get("result", [])

    approve, witness, sign, unparsed, foreign = [], [], [], 0, 0
    max_id = offset
    for u in updates:
        max_id = max(max_id, int(u.get("update_id", offset)))
        msg = u.get("message") or u.get("edited_message") or u.get("channel_post") or {}
        if str((msg.get("chat") or {}).get("id") or "") != chat_id:
            foreign += 1              # only the owner is heard, as before
            continue
        text = (msg.get("text") or "").strip()
        where = route(text)
        if where == "approve":
            approve.append(u)
        elif where == "witness":
            witness.append((u, text))
        elif where == "sign":
            sign.append((u, text))
        else:
            _record_unparsed(u.get("update_id"), text,
                             "first word is neither %s nor %s"
                             % ("/".join(APPROVE_PREFIXES), "/".join(WITNESS_PREFIXES)))
            unparsed += 1

    applied_approvals = 0
    if approve:
        import approve_reader                                   # noqa: E402
        applied_approvals = approve_reader.apply_updates(approve, token, chat_id, offset)

    applied_witness = 0
    verdicts = []
    if witness:
        from experiments.institution import witness_reader as wr   # noqa: E402
        for _u, text in witness:
            verdict, reason, refusal = wr.parse_reply(text)
            if verdict is None:
                _record_unparsed(_u.get("update_id"), text, refusal or "?")
                unparsed += 1
                continue
            applied_witness += wr.apply_to_latest(verdict, reason)
            verdicts.append({"verdict": verdict, "reason": reason})

    signed = []
    for _u, text in sign:
        import approve_reader                                   # noqa: E402
        signed.append(approve_reader.apply_signature(text, token, chat_id,
                                                     update_id=_u.get("update_id")))

    # The offset is written ONCE, by this file, after both readers have had the
    # updates. approve_reader.apply_updates no longer writes it when called from
    # here — it is given `offset` and returns a count, and its own run() is the
    # only path that still persists one.
    if updates and max_id > offset:
        OFFSET.parent.mkdir(parents=True, exist_ok=True)
        OFFSET.write_text(json.dumps({"offset": max_id, "ts": _now()}), encoding="utf-8")

    return {"ok": True, "updates": len(updates), "approve_routed": len(approve),
            "approvals_applied": applied_approvals, "witness_routed": len(witness),
            "witness_lines_written": applied_witness, "verdicts": verdicts,
            "signatures": signed,
            "unparsed": unparsed, "from_other_chats_ignored": foreign,
            "offset": max_id}


def selftest() -> dict:
    cases = [("OK 4f2a", "approve"), ("ok 4f2a", "approve"), ("NO 4f2a", "approve"),
             ("NOTHING", "witness"), ("nothing", "witness"),
             ("USED reprioritised DRC", "witness"),
             ("COUNTERMANDED coding artefact", "witness"),
             ("SIGN F-001 abc", "sign"), ("sign F-001 abc", "sign"),
             ("there is nothing to report", "unparsed"),
             ("thanks", "unparsed"), ("", "unparsed")]
    out = {"router": {}, "ok": True}
    for text, want in cases:
        got = route(text)
        out["router"][text or "(empty)"] = {"routed": got, "as_expected": got == want}
        out["ok"] = out["ok"] and got == want
    out["offset_file"] = str(OFFSET)
    out["shares_the_established_offset"] = OFFSET.name == "telegram_offset.json"
    try:
        import approve_reader
        out["approve_reader.apply_updates"] = ("LIVE" if hasattr(approve_reader, "apply_updates")
                                               else "INERT (not split out)")
    except Exception as e:                                       # noqa: BLE001
        out["approve_reader.apply_updates"] = "INERT (%s)" % type(e).__name__
    vbs = REPO / "experiments" / "needs" / "run_approvals.vbs"
    out["scheduled_task_points_here"] = (
        "LIVE" if vbs.exists() and "telegram_dispatcher" in vbs.read_text(errors="replace")
        else "INERT (run_approvals.vbs still launches approve_reader directly)")
    return out


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        print(json.dumps(selftest(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(run(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
