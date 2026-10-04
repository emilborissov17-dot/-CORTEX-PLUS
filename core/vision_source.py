# -*- coding: utf-8 -*-
"""core/vision_source.py — the ONE path of the vision text (C-VISION-4, Emil 4 Oct 2026: "път").

Decided: core/civilization_vision.txt is the canonical file and every reader goes through
load_vision(). A missing, unreadable or empty file RAISES VisionMissing. There is no default
text: a missing vision must not stand in for the real one in a canon, a prompt or a README
(DEFECT-B). The readers that used to look at the repo root or notes/ and swallow the miss are
the reason this module exists.

    venv/Scripts/python.exe core/vision_source.py --selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

VISION_PATH = Path(__file__).resolve().parent / "civilization_vision.txt"


class VisionMissing(RuntimeError):
    pass


def load_vision() -> str:
    try:
        text = VISION_PATH.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise VisionMissing(f"the vision text cannot be read at {VISION_PATH}: {exc}") from exc
    if not text:
        raise VisionMissing(f"the vision text at {VISION_PATH} is empty")
    return text


def _selftest() -> int:
    print(f"VISION_PATH: {VISION_PATH}")
    try:
        text = load_vision()
    except VisionMissing as exc:
        print(f"INERT: {exc}")
        return 1
    print(f"LIVE: {len(text)} characters")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(load_vision())
