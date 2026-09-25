"""
experiments/needs/channel.py — what we know about the human channel, read-only.

Split out of approve_reader.py on 25 Sep 2026 (task #29): core.notary reads the
channel's state, and importing approve_reader for it pulled the notary into
core.source_registration and from there to core.llm_door - a path from the model
to the gate for irreversible actions. This module imports nothing from the repo.
approve_reader writes the record (its _mark_channel); this module only reads it.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHANNEL_STATE = REPO / "memory" / "human_channel_state.json"
UNKNOWN_CHANNEL = "unknown"


def channel_state() -> dict:
    """Какво ЗНАЕМ за канала. `unknown` когато не сме гледали или не сме могли.

    Отделено от channel_alive() на 17 авг 2026, защото „не проверено" и
    „проверено и мъртво" се връщаха като едно и също нещо — по-точно, „не
    проверено" се връщаше като ПО-ДОБРОТО от двете. Виж channel_alive().
    """
    try:
        d = json.loads(CHANNEL_STATE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"state": UNKNOWN_CHANNEL, "why": "няма запис — каналът НЕ Е проверяван"}
    except Exception as e:
        return {"state": UNKNOWN_CHANNEL,
                "why": f"записът за канала е нечетим: {type(e).__name__}"}
    if not isinstance(d, dict) or not d.get("state"):
        return {"state": UNKNOWN_CHANNEL, "why": "записът няма поле state"}
    return d
