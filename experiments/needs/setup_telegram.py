#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/needs/setup_telegram.py — one-shot Telegram push setup.

You do two things in Telegram first:
  1. @BotFather -> /newbot -> copy the bot TOKEN
  2. open your new bot, press Start / send it any message (so it can see your chat_id)

Then run (on the CORTEX machine, venv python):
  venv\\Scripts\\python.exe experiments\\needs\\setup_telegram.py <BOT_TOKEN>

It resolves your chat_id from the bot's updates, writes memory/notify_channel.json
(the gitignored config needs_report.py reads), and sends a test push so you see it
land on your phone. No phone number needed — Telegram uses the chat_id it assigns.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CFG = REPO / "memory" / "notify_channel.json"


def _http():
    import requests  # requests-first: urllib 403s behind the proxy on this box
    return requests


def resolve_chat_id(token: str):
    r = _http().get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
    data = r.json()
    if not data.get("ok"):
        raise SystemExit(f"Telegram rejected the token: {data.get('description')}")
    updates = data.get("result", [])
    ids = []
    for u in updates:
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            ids.append((chat["id"], chat.get("first_name") or chat.get("title") or ""))
    if not ids:
        raise SystemExit(
            "No messages seen yet. Open your bot in Telegram, press Start / send it "
            "any message, then run this again.")
    # newest wins
    chat_id, who = ids[-1]
    return str(chat_id), who


def send_test(token: str, chat_id: str):
    txt = ("CORTEX push is live. From now the organism sends here what it needs "
           "(high-severity + candidates awaiting your approval). Advisory only.")
    r = _http().post(f"https://api.telegram.org/bot{token}/sendMessage",
                     json={"chat_id": chat_id, "text": txt}, timeout=20)
    ok = r.json().get("ok")
    if not ok:
        raise SystemExit(f"Test message failed: {r.text[:200]}")


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        raise SystemExit("usage: setup_telegram.py <BOT_TOKEN>")
    token = sys.argv[1].strip()
    chat_id, who = resolve_chat_id(token)
    print(f"resolved chat_id: {chat_id}  ({who})")
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps({"channel": "telegram", "token": token,
                               "chat_id": chat_id}, indent=2), encoding="utf-8")
    print(f"wrote {CFG}")
    send_test(token, chat_id)
    print("test push sent — check your phone. Setup complete.")


if __name__ == "__main__":
    main()
