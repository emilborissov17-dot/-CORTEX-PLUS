#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/institution/telegram_witness.py — the morning message, and the ask.

INSTITUTION #0 (WITNESS STAGE) sends one message per morning. The message is not
a notification; it is the half of the experiment that a machine cannot do. Every
number in it came from UCDP, and the one thing UCDP cannot say is whether any of
it was USED — whether a human took a number and did something with it. That bit
comes back as a reply, and without it this is a counter, not an institution.

So every message ends with the same three words and the instruction to pick one:

    USED / NOTHING / COUNTERMANDED + reason

`experiments/institution/witness_reader.py` reads the reply. It does NOT go
through experiments/needs/approve_reader.py: that reader refuses everything that
is not "OK <id>" and applies exactly two action types, and its refusal boundary
is a feature. Loosening it so this experiment could share it would trade a
security property for a convenience.

The token is read from memory/notify_channel.json (gitignored) and never printed,
never logged, never passed on a command line.

  venv\\Scripts\\python.exe experiments/institution/telegram_witness.py --dry-run
  venv\\Scripts\\python.exe experiments/institution/telegram_witness.py --send
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CHANNEL = REPO / "memory" / "notify_channel.json"
LEDGER = REPO / "experiments" / "institution" / "ledger.jsonl"
NAME = "institution #0 (witness stage)"

REPLY_INSTRUCTION = (
    "Reply with exactly one of:\n"
    "  USED <reason>          — a number here changed something you did\n"
    "  NOTHING                — you read it and it changed nothing\n"
    "  COUNTERMANDED <reason> — you acted against what it suggested\n"
    "A reason is required for USED and COUNTERMANDED. Anything else is logged "
    "as unparsed and guessed at by nobody.")


def latest_lines(ledger: Path = LEDGER) -> list[dict]:
    """Every line from the most recent run, by ts."""
    if not ledger.exists():
        raise SystemExit("no ledger at %s — run tools/institution0_morning.py --write" % ledger)
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        raise SystemExit("ledger is empty")
    newest = max(r["ts"] for r in rows)
    return [r for r in rows if r["ts"] == newest]


def render(lines: list[dict]) -> str:
    """The message. Plain text: Telegram's markdown would eat the underscores in
    the actor strings, and an actor string that renders wrong is the one thing
    here that must stay exact."""
    commits = [r for r in lines if r.get("kind") == "commitment"]
    ctx = next((r for r in lines if r.get("kind") == "context"), None)
    head = commits[0] if commits else ctx
    out = [NAME.upper(),
           "month %s   as_of %s   source %s (%s)"
           % (head["anchor_month"], head["as_of"], head["source"], head["reporter_class"]),
           "UCDP one-sided violence against civilians. Counts, not causes.",
           ""]
    for r in commits:
        out.append("%s — %s (%s)" % (r["place"], r["commitment_title"], r["commitment_date"]))
        out.append("  register: %s" % r["register_status"])
        for a in r["actors"]:
            if a["link"] == "unverified":
                tag = "  [link UNVERIFIED, counted separately]"
            else:
                tag = ""
            ratio = "n/a" if a["ratio"] is None else "%.2f" % a["ratio"]
            p90 = "n/a" if a["null_p90"] is None else "%.2f" % a["null_p90"]
            out.append("  %-32s %2d events  prior3 %s (mean %.2f)  ratio %s vs own p90 %s -> %s%s"
                       % (a["side_a"], a["ucdp_events_osv_last_month"],
                          a["ucdp_events_osv_prior_3"], a["mean_prior_3"], ratio, p90,
                          a["verdict"], tag))
            out.append("      civilian deaths %d | pre-commitment rate %s/mo | forecast %s p=%s (%s)"
                       % (a["ucdp_deaths_civilians_last_month"],
                          a["pre_commitment_monthly_rate"], a["forecast"], a["p"],
                          a["forecast_version"]))
        u = r["actor_unknown"]
        out.append("  %-32s %2d events  prior3 %s  (charged to nobody)"
                   % (u["side_a"], u["ucdp_events_osv_last_month"], u["ucdp_events_osv_prior_3"]))
        out.append("")
    if ctx and ctx.get("place"):
        out.append("CONTEXT — largest rise anywhere, watched or not:")
        out.append("  %s  %d events vs mean %.2f  ratio %.2f > own p90 %.2f"
                   % (ctx["place"], ctx["ucdp_events_osv_last_month"], ctx["mean_prior_3"],
                      ctx["ratio"], ctx["null_p90"]))
        out.append("  top actor %s | commitment_id %s"
                   % (ctx["top_actor"], ctx["commitment_id"]))
        out.append("")
    elif ctx:
        out.append("CONTEXT — %s" % ctx.get("note"))
        out.append("")
    out.append("NOT a causal claim. Attribution is UCDP's, not ours. Forecast is "
               "persistence (v0), here to be beaten.")
    out.append("")
    out.append(REPLY_INSTRUCTION)
    return "\n".join(out)


def send(text: str) -> dict:
    cfg = json.loads(CHANNEL.read_text(encoding="utf-8"))
    token, chat_id = cfg["token"], cfg["chat_id"]
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text,
                                   "disable_web_page_preview": "true"}).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token,
                                 data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.loads(r.read().decode("utf-8", "replace"))
    # Return only what is safe to print: ok, message_id, date. Never the token.
    res = payload.get("result") or {}
    return {"ok": payload.get("ok"), "message_id": res.get("message_id"),
            "date": res.get("date"), "chars": len(text)}


def main(argv: list[str]) -> int:
    text = render(latest_lines())
    if "--send" in argv:
        print(json.dumps(send(text), ensure_ascii=False, indent=2))
        print("--- message as sent ---")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
