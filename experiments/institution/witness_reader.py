#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/institution/witness_reader.py — read the one bit a machine cannot produce.

INSTITUTION #0 (WITNESS STAGE) publishes counts. Whether a count was USED is a
fact about a human, and it arrives as a Telegram reply:

    USED <reason>          a number changed something you did
    NOTHING                you read it and it changed nothing
    COUNTERMANDED <reason> you acted against what it suggested

WHY NOT experiments/needs/approve_reader.py. That reader exists and works, and it
parses exactly "OK <id>" and applies exactly two action types; its docstring calls
that a HARD BOUNDARY. Widening it so this experiment could share it would trade a
security property for a convenience, and the property is the more valuable of the
two. So the dispatcher routes to it instead of widening it.

AN EARLIER VERSION OF THIS FILE POLLED getUpdates ITSELF, and that was wrong.
Giving it its own offset file aimed at the wrong mechanism: getUpdates
acknowledges SERVER-SIDE PER BOT TOKEN, so the offset FILE was never the shared
thing and two readers on one token cannot both work. CORTEX_Approvals runs every
minute; it won every race and dropped the reply unrecorded. poll() now raises and
names experiments/institution/telegram_dispatcher.py, which makes the one fetch.
parse_reply() and apply_to_latest() below are what it calls.

WHAT IS NEVER GUESSED. A reply that does not begin with one of the three words is
recorded as `unparsed` with its text and changes no ledger line. "Yes", "did it",
a thumbs-up emoji: all unparsed. The whole value of this bit is that it was
stated, and inferring it would be the system marking its own homework.

  venv\\Scripts\\python.exe experiments/institution/witness_reader.py          # poll and apply
  venv\\Scripts\\python.exe experiments/institution/witness_reader.py --selftest
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]

CHANNEL = REPO / "memory" / "notify_channel.json"
OFFSET = REPO / "memory" / "institution_offset.json"
LEDGER = REPO / "experiments" / "institution" / "ledger.jsonl"
UNPARSED = REPO / "memory" / "institution_witness.jsonl"

VERDICTS = ("USED", "NOTHING", "COUNTERMANDED")
NEEDS_REASON = ("USED", "COUNTERMANDED")


def parse_reply(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(verdict, reason, refusal). Exactly one shape is accepted.

    The first word must be one of the three, upper-case-insensitively, and USED
    and COUNTERMANDED must carry a reason. Everything else returns a refusal
    string and no verdict — never a default, never a best guess.
    """
    if text is None:
        return None, None, "no text"
    stripped = text.strip()
    if not stripped:
        return None, None, "empty message"
    head, _, tail = stripped.partition(" ")
    verdict = head.strip().upper()
    if verdict not in VERDICTS:
        return None, None, ("first word %r is not one of %s" % (head.strip(), ", ".join(VERDICTS)))
    reason = tail.strip() or None
    if verdict in NEEDS_REASON and not reason:
        return None, None, "%s requires a reason and none was given" % verdict
    if verdict == "NOTHING" and reason:
        # A reason on NOTHING is not an error; it is extra information and is kept.
        pass
    return verdict, reason, None


def _cfg() -> dict:
    return json.loads(CHANNEL.read_text(encoding="utf-8"))


def _tg(token: str, method: str, **params):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _read_offset() -> int:
    if OFFSET.exists():
        try:
            return int(json.loads(OFFSET.read_text(encoding="utf-8"))["offset"])
        except (ValueError, KeyError, json.JSONDecodeError):
            return 0
    return 0


def _write_offset(value: int) -> None:
    OFFSET.parent.mkdir(parents=True, exist_ok=True)
    OFFSET.write_text(json.dumps({"offset": value}), encoding="utf-8")


def _record_unparsed(update_id: int, text: str, why: str) -> None:
    UNPARSED.parent.mkdir(parents=True, exist_ok=True)
    with UNPARSED.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "update_id": update_id, "text": text, "status": "unparsed", "why": why,
        }, ensure_ascii=False) + "\n")


def apply_to_latest(verdict: str, reason: Optional[str], ledger: Path = LEDGER) -> int:
    """Write the witness onto every line of the most recent run. Returns lines changed.

    The whole run, not one line: the reply is about the message, and the message
    carried every commitment. A witness bit attached to one arbitrary line would
    be a claim about which line the human meant.
    """
    if not ledger.exists():
        return 0
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        return 0
    newest = max(r["ts"] for r in rows)
    changed = 0
    for r in rows:
        if r["ts"] == newest:
            r["witness"] = verdict
            r["witness_reason"] = reason
            changed += 1
    ledger.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                      encoding="utf-8")
    return changed


def poll() -> dict:
    """REFUSED. There must be exactly one reader of this bot token.

    This function polled getUpdates with its own offset file, and on
    18 Sep 2026 it lost every race to CORTEX_Approvals, which runs every
    minute. getUpdates ACKs SERVER-SIDE PER TOKEN: whichever reader polls
    first deletes the other's messages. A separate offset file does not help,
    because the offset file was never the shared thing.

    Emil's "NOTHING" was consumed and dropped within sixty seconds, because
    approve_reader matches only OK/NO and records nothing else.

    It raises rather than returning an empty result, because an empty result
    is exactly what the broken version returned and it read as "no reply yet".
    parse_reply() and apply_to_latest() remain and are what the dispatcher
    calls."""
    raise RuntimeError(
        "witness_reader.poll() is retired: two readers cannot share one bot "
        "token, because getUpdates acknowledges server-side per token. Use "
        "experiments/institution/telegram_dispatcher.py, which makes ONE fetch "
        "and routes OK/NO to approve_reader and USED/NOTHING/COUNTERMANDED here.")


def _poll_retired_body() -> dict:
    cfg = _cfg()
    token, chat_id = cfg["token"], str(cfg["chat_id"])
    offset = _read_offset()
    data = _tg(token, "getUpdates", offset=offset + 1, timeout=0)
    if not data.get("ok"):
        return {"ok": False, "why": "getUpdates not ok"}
    applied, unparsed, foreign, highest = 0, 0, 0, offset
    for upd in data.get("result", []):
        highest = max(highest, int(upd["update_id"]))
        msg = upd.get("message") or upd.get("channel_post") or {}
        sender_chat = str((msg.get("chat") or {}).get("id", ""))
        if sender_chat != chat_id:
            # Only the configured chat is honoured. Nobody else can witness.
            foreign += 1
            continue
        verdict, reason, refusal = parse_reply(msg.get("text"))
        if verdict is None:
            _record_unparsed(int(upd["update_id"]), msg.get("text") or "", refusal or "?")
            unparsed += 1
            continue
        applied += apply_to_latest(verdict, reason)
    if highest > offset:
        _write_offset(highest)
    return {"ok": True, "applied_lines": applied, "unparsed": unparsed,
            "from_other_chats_ignored": foreign, "offset": highest}


def selftest() -> dict:
    cases = [
        ("USED reprioritised the DRC row", ("USED", "reprioritised the DRC row", None)),
        ("NOTHING", ("NOTHING", None, None)),
        ("nothing", ("NOTHING", None, None)),
        ("COUNTERMANDED the rise is a coding artefact",
         ("COUNTERMANDED", "the rise is a coding artefact", None)),
        ("USED", (None, None, "USED requires a reason and none was given")),
        ("yes", (None, None, None)),
        ("", (None, None, "empty message")),
        ("ok 1234", (None, None, None)),
    ]
    out = {"parser": {}, "ok": True}
    for text, want in cases:
        got = parse_reply(text)
        ok = got[0] == want[0] and (want[1] is None or got[1] == want[1])
        out["parser"][text or "(empty)"] = {"verdict": got[0], "reason": got[1],
                                            "refusal": got[2], "as_expected": ok}
        out["ok"] = out["ok"] and ok
    out["offset_file"] = str(OFFSET)
    out["offset_is_its_own"] = str(OFFSET) != str(REPO / "memory" / "telegram_offset.json")
    out["channel"] = "LIVE" if CHANNEL.exists() else "INERT"
    out["ledger_lines"] = len(LEDGER.read_text(encoding="utf-8").splitlines()) \
        if LEDGER.exists() else 0
    return out


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        print(json.dumps(selftest(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(poll(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
