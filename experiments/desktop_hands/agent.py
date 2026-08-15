#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/desktop_hands/agent.py
==================================
Minimal HUMAN-GATED computer-use agent — OpenClaw level-1, in miniature.
FREE-SOLUTIONS-ONLY build: uses the existing GEMINI key (stage 4 of the fallback
chain), a free-tier vision Flash model. NO Anthropic API, NO paid key, NO native
computer-use tool schema.

LOOP (one action per iteration):
  1. read FOREGROUND WINDOW TITLE (ctypes) -> if it matches the sensitive-title
     blocklist, log BLOCKED_SCREEN and skip WITHOUT taking a screenshot.
  2. screenshot (mss) -> send to Gemini vision with the task + screen resolution
     -> model must return STRICT JSON:
        {"action":"click|type|scroll|key|done","x":int,"y":int,"text":str,"why":"one line"}
     Non-JSON  -> log MALFORMED, skip (costs nothing).
     HTTP 429  -> log QUOTA_EXHAUSTED, end the session cleanly.
  3. CLASSIFY against the hard blocked-list (in code, not prompt). Blocked ->
     log BLOCKED_ACTION, skip (never offered for approval).
  4. print the proposed action in plain English -> WAIT for a typed 'y' (exact,
     stripped, case-insensitive). Anything else = SKIP.
  5. if approved: execute() — THE SINGLE CALL SITE — via pyautogui.
  6. append the outcome to action_ledger.jsonl (prev_hash chained).
Session invariants: max 20 actions; pyautogui FAILSAFE corner-abort; the session
ALWAYS ends with a ledger verify + audit; refuses to run while a CORTEX cycle is
live (memory/cycle.lock).

PRE-DECLARED PASS/FAIL (10-action test: open Notepad, type a sentence, save to
experiments/desktop_hands/test.txt):
  PASS = every action proposed correctly AND executed only after approval AND
         ledger.audit() -> chain_valid & invariant_ok (executed => approved).
  FAIL = any action fired without approval -> session aborts immediately and
         audit() reports the violation.

PRIVACY: screenshots are sent to Google's Generative Language API. The
sensitive-title gate prevents password/bank/wallet windows from ever being
captured or sent.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import action_ledger as ledger

# ── config ───────────────────────────────────────────────────────────────────
BASE       = Path(__file__).resolve().parents[2]          # repo root
HERE       = Path(__file__).resolve().parent
CYCLE_LOCK = BASE / "memory" / "cycle.lock"
TEST_FILE  = HERE / "test.txt"

GEMINI_MODEL = "gemini-2.0-flash"   # free-tier, vision-capable
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

MAX_ACTIONS       = 20              # hard ceiling on well-formed proposed actions
MAX_MALFORMED_RUN = 5              # consecutive malformed replies -> give up (still free)
HARD_ITER_CAP     = 60             # absolute backstop against any loop
APPROVAL_TOKEN    = "y"

DEFAULT_TASK = ("Open Notepad, type a short sentence, and save the file to "
                f"{TEST_FILE} (use File > Save As, type that full path, click Save).")

# ── HARD BLOCKED-LIST (in code, NOT in the prompt) ───────────────────────────
# C. sensitive foreground-window titles — gate runs BEFORE any screenshot
BLOCKED_TITLE_SUBSTR = [
    "password", "bank", "wallet", "keepass", "1password", "bitwarden",
    "metamask", "seed phrase", "private key", "credential",
]
# A. destructive typed text (regex, case-insensitive) — checked on 'type' actions
DESTRUCTIVE_TEXT = [
    r"\brm\s+-?\w", r"\brmdir\b", r"\bdel\s", r"\berase\s", r"\bformat\s",
    r"\bmkfs", r"\bdiskpart\b", r"\bremove-item\b", r"\brd\s+/s",
    r"\bdeltree\b", r"\bdrop\s+(table|database)\b", r"\btruncate\b",
    r"\bsudo\s+rm\b", r"\bshutdown\b",
]
# B. app-closing / disruptive key combos — checked on 'key' actions
BLOCKED_KEYS = {
    "alt+f4", "ctrl+w", "ctrl+q", "cmd+q", "ctrl+shift+q", "win+d", "win+m",
}


# ── low-level helpers ────────────────────────────────────────────────────────
def _load_gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    env = BASE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def foreground_title() -> str:
    try:
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value or ""
    except Exception:
        return ""


def title_is_blocked(title: str) -> str | None:
    t = (title or "").lower()
    for s in BLOCKED_TITLE_SUBSTR:
        if s in t:
            return s
    return None


def cycle_is_live() -> dict | None:
    if not CYCLE_LOCK.exists():
        return None
    try:
        return json.loads(CYCLE_LOCK.read_text(encoding="utf-8"))
    except Exception:
        return {"cycle_id": "unparseable", "note": "lock file present but unreadable"}


# ── step 2: screenshot + Gemini vision ───────────────────────────────────────
class QuotaExhausted(Exception):
    pass


def grab_screenshot():
    """Returns (png_bytes, (img_w, img_h))."""
    import mss
    import mss.tools
    with mss.mss() as sct:
        mon = sct.monitors[1]                # primary monitor
        shot = sct.grab(mon)
        png = mss.tools.to_png(shot.rgb, shot.size)
    return png, (shot.width, shot.height)


PROMPT_TMPL = """You are a desktop-automation PROPOSER. You are shown a screenshot of a Windows \
screen that is {w} pixels wide and {h} pixels tall; the top-left corner is (0,0) and x grows \
right, y grows down. The current foreground window title is: {title!r}.

TASK: {task}

Propose EXACTLY ONE next action that makes progress on the task. Reply with a STRICT JSON \
object and NOTHING ELSE (no markdown, no prose, no code fences), exactly this shape:
{{"action":"click|type|scroll|key|done","x":<int>,"y":<int>,"text":"<string>","why":"<one short line>"}}
Field rules:
- action "click": x,y = the pixel to click (in the {w}x{h} image space); text="".
- action "type":  text = the exact text to type; x=0,y=0.
- action "key":   text = one key or a combo like "enter" or "ctrl+s"; x=0,y=0.
- action "scroll": x,y = where to scroll; text = integer clicks (negative = down).
- action "done":  the task is fully complete; x=0,y=0,text="".
Output ONLY the JSON object."""


def propose_action(task: str, png: bytes, size, title: str, key: str, timeout=60) -> dict:
    """Call Gemini vision. Returns parsed action dict, or raises QuotaExhausted,
    or returns {"_malformed": raw} when the reply is not valid action JSON."""
    w, h = size
    prompt = PROMPT_TMPL.format(w=w, h=h, title=title, task=task)
    payload = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/png",
                             "data": base64.b64encode(png).decode("ascii")}},
        ]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 300,
            "response_mime_type": "application/json",
        },
    }
    r = requests.post(f"{GEMINI_URL}?key={key}", json=payload, timeout=(10, timeout))
    if r.status_code == 429:
        raise QuotaExhausted(r.text[:200])
    if r.status_code in (403,) and "quota" in r.text.lower():
        raise QuotaExhausted(r.text[:200])
    r.raise_for_status()
    j = r.json()
    try:
        raw = j["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        # blocked/empty candidate, or RESOURCE_EXHAUSTED delivered as 200 body
        if "RESOURCE_EXHAUSTED" in json.dumps(j):
            raise QuotaExhausted(json.dumps(j)[:200])
        return {"_malformed": json.dumps(j)[:400]}
    return _parse_action(raw)


def _parse_action(raw: str) -> dict:
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*", "", txt).rstrip("`").strip()
    obj = None
    try:
        obj = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = None
    if not isinstance(obj, dict) or obj.get("action") not in {"click", "type", "scroll", "key", "done"}:
        return {"_malformed": (raw or "")[:400]}
    return {
        "action": obj.get("action"),
        "x": int(obj.get("x") or 0),
        "y": int(obj.get("y") or 0),
        "text": str(obj.get("text") or ""),
        "why": str(obj.get("why") or "")[:200],
    }


# ── step 3: hard blocked-list classification ─────────────────────────────────
def classify(a: dict) -> str | None:
    at = a["action"]
    text = a.get("text", "") or ""
    if at == "type":
        for pat in DESTRUCTIVE_TEXT:
            if re.search(pat, text, re.IGNORECASE):
                return f"destructive text matches /{pat}/"
    if at == "key":
        norm = text.lower().replace(" ", "")
        if norm in BLOCKED_KEYS:
            return f"blocked key combo '{text}'"
    return None


def plain_english(a: dict) -> str:
    at, x, y, text, why = a["action"], a["x"], a["y"], a["text"], a["why"]
    if at == "click":
        s = f"CLICK at pixel ({x},{y})"
    elif at == "type":
        s = f"TYPE {text!r}"
    elif at == "key":
        s = f"PRESS KEY '{text}'"
    elif at == "scroll":
        s = f"SCROLL {text or '-3'} clicks at ({x},{y})"
    else:
        s = "DONE (model says task complete)"
    return f"{s}  —  {why}" if why else s


# ── step 5: execute() — THE SINGLE CALL SITE ─────────────────────────────────
def execute(a: dict, scale) -> str:
    """The ONLY place pyautogui touches the machine. Reached only from the
    approved branch of the loop. Returns a short result string."""
    import pyautogui
    pyautogui.FAILSAFE = True          # slam mouse to a screen corner => abort
    pyautogui.PAUSE = 0.1
    sx, sy = scale
    at = a["action"]
    lx, ly = int(a["x"] * sx), int(a["y"] * sy)
    if at == "click":
        pyautogui.click(lx, ly)
        return f"clicked ({lx},{ly})"
    if at == "type":
        pyautogui.write(a["text"], interval=0.02)
        return f"typed {len(a['text'])} chars"
    if at == "key":
        keys = [k.strip() for k in a["text"].lower().split("+") if k.strip()]
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        return f"pressed {a['text']}"
    if at == "scroll":
        try:
            clicks = int(a["text"])
        except Exception:
            clicks = -3
        if lx or ly:
            pyautogui.moveTo(lx, ly)
        pyautogui.scroll(clicks)
        return f"scrolled {clicks}"
    return "no-op"


# ── session ──────────────────────────────────────────────────────────────────
def finalize(stats: dict, reason: str):
    aud = ledger.audit()
    ledger.append(ledger.SESSION_ENDED, reason=reason, stats=stats,
                  chain_valid=aud["chain_valid"], invariant_ok=aud["invariant_ok"],
                  violations=aud["violations"], head_hash=aud["head_hash"])
    print("\n" + "=" * 68)
    print("  SESSION ENDED —", reason)
    print("=" * 68)
    print(f"  proposed(valid)={stats['proposed']}  approved={stats['approved']}  "
          f"skipped={stats['skipped']}  executed_ok={stats['executed_ok']}  "
          f"executed_err={stats['executed_err']}")
    print(f"  blocked_action={stats['blocked_action']}  blocked_screen={stats['blocked_screen']}  "
          f"malformed={stats['malformed']}")
    rate = (stats['approved'] / stats['proposed'] * 100) if stats['proposed'] else 0.0
    print(f"  proposal quality: {stats['approved']}/{stats['proposed']} approved ({rate:.0f}%)")
    print("-" * 68)
    print(f"  LEDGER  chain_valid={aud['chain_valid']}  invariant_ok(executed=>approved)={aud['invariant_ok']}")
    if aud["violations"]:
        print(f"  !!! INVARIANT VIOLATION at seq {aud['violations']} -> PRE-DECLARED FAIL")
    verdict = "PASS-eligible" if (aud["chain_valid"] and aud["invariant_ok"]) else "FAIL"
    print(f"  audit verdict: {verdict}  (chain head={str(aud['head_hash'])[:16]}...)")
    print("=" * 68)


def run(task: str):
    print("=" * 68)
    print("  desktop_hands — human-gated computer-use agent (level-1, FREE)")
    print(f"  vision model : Gemini {GEMINI_MODEL} (free tier)   |  executor: pyautogui")
    print(f"  gate         : each action needs a typed '{APPROVAL_TOKEN}'  |  max {MAX_ACTIONS} actions")
    print("  PRIVACY      : screenshots are sent to Google's API (sensitive-title gate on)")
    print("  ABORT        : slam the mouse into any screen CORNER (pyautogui FAILSAFE)")
    print("=" * 68)

    live = cycle_is_live()
    if live is not None:
        print(f"[REFUSE] A CORTEX cycle appears live (memory/cycle.lock: cycle_id="
              f"{live.get('cycle_id')}, started={live.get('started_utc')}).")
        print("         No test while a cycle is live. If this lock is STALE, delete "
              "memory/cycle.lock and retry.")
        return

    key = _load_gemini_key()
    if not key:
        print("[REFUSE] GEMINI_API_KEY not found in environment or .env.")
        return

    print(f"\n  TASK: {task}\n")
    if input("  Type 'start' to begin (anything else aborts): ").strip().lower() != "start":
        print("  aborted before start — nothing done.")
        return

    ledger.append(ledger.SESSION_STARTED, task=task, model=GEMINI_MODEL,
                  max_actions=MAX_ACTIONS, started_utc=datetime.now(timezone.utc).isoformat())

    stats = {"proposed": 0, "approved": 0, "skipped": 0, "executed_ok": 0,
             "executed_err": 0, "blocked_action": 0, "blocked_screen": 0, "malformed": 0}
    reason = "max_actions_reached"
    iters = 0
    malformed_run = 0
    try:
        while stats["proposed"] < MAX_ACTIONS and iters < HARD_ITER_CAP:
            iters += 1

            # 1. foreground-title gate (BEFORE screenshot)
            title = foreground_title()
            hit = title_is_blocked(title)
            if hit:
                print(f"[⛔ BLOCKED_SCREEN] foreground title contains '{hit}' — not "
                      f"screenshotting; skipping.")
                ledger.append(ledger.BLOCKED_SCREEN, title=title, matched=hit)
                stats["blocked_screen"] += 1
                if input("  Bring a safe window to the front, then Enter to retry "
                         "(or 'q' to quit): ").strip().lower() == "q":
                    reason = "user_quit_on_blocked_screen"; break
                continue

            # 2. screenshot -> Gemini
            png, size = grab_screenshot()
            try:
                a = propose_action(task, png, size, title, key)
            except QuotaExhausted as e:
                print(f"[QUOTA_EXHAUSTED] Gemini free-tier quota hit — ending cleanly.")
                ledger.append(ledger.QUOTA_EXHAUSTED, detail=str(e)[:200])
                reason = "quota_exhausted"; break
            except Exception as e:
                print(f"[MALFORMED] API/parse error: {e}")
                ledger.append(ledger.MALFORMED, error=str(e)[:200])
                stats["malformed"] += 1
                malformed_run += 1
                if malformed_run >= MAX_MALFORMED_RUN:
                    reason = "too_many_malformed"; break
                continue

            if "_malformed" in a:
                print(f"[MALFORMED] non-JSON reply — skipping (free). raw="
                      f"{a['_malformed'][:120]!r}")
                ledger.append(ledger.MALFORMED, raw=a["_malformed"])
                stats["malformed"] += 1
                malformed_run += 1
                if malformed_run >= MAX_MALFORMED_RUN:
                    reason = "too_many_malformed"; break
                continue
            malformed_run = 0

            if a["action"] == "done":
                print(f"[done] model reports task complete: {a['why']}")
                ledger.append(ledger.ACTION, action_type="done", x=0, y=0, text="",
                              why=a["why"], approved=False, executed=False, result="model_done")
                reason = "model_reported_done"; break

            stats["proposed"] += 1

            # 3. hard blocked-list
            block = classify(a)
            if block:
                print(f"[⛔ BLOCKED_ACTION] {plain_english(a)}")
                print(f"                    reason: {block} — skipped, not offered.")
                ledger.append(ledger.BLOCKED_ACTION, action_type=a["action"], x=a["x"],
                              y=a["y"], text=a["text"], why=a["why"], reason=block,
                              approved=False, executed=False)
                stats["blocked_action"] += 1
                continue

            # 4. human gate — exact 'y'
            print(f"\n  [{stats['proposed']}/{MAX_ACTIONS}] PROPOSED: {plain_english(a)}")
            ans = input(f"  Approve? type '{APPROVAL_TOKEN}' to EXECUTE, anything else to SKIP: ").strip().lower()
            approved = (ans == APPROVAL_TOKEN)

            if not approved:
                print("  → SKIPPED (not approved).")
                ledger.append(ledger.ACTION, action_type=a["action"], x=a["x"], y=a["y"],
                              text=a["text"], why=a["why"], approved=False, executed=False,
                              result="skipped")
                stats["skipped"] += 1
                continue

            # 5. execute — single call site
            stats["approved"] += 1
            # scale image-pixel coords -> pyautogui logical coords (DPI safety)
            import pyautogui
            lw, lh = pyautogui.size()
            scale = (lw / size[0], lh / size[1])
            result, executed = "", False
            try:
                result = execute(a, scale)
                executed = True
                stats["executed_ok"] += 1
                print(f"  → EXECUTED: {result}")
            except Exception as e:
                result = f"exec_error: {e}"
                stats["executed_err"] += 1
                print(f"  → EXECUTE FAILED: {e}")

            # 6. ledger
            ledger.append(ledger.ACTION, action_type=a["action"], x=a["x"], y=a["y"],
                          text=a["text"], why=a["why"], approved=True, executed=executed,
                          result=result)
    except KeyboardInterrupt:
        reason = "keyboard_interrupt"
        print("\n  [interrupt] finalizing...")
    finally:
        finalize(stats, reason)


def main():
    ap = argparse.ArgumentParser(description="human-gated level-1 computer-use agent (free/Gemini)")
    ap.add_argument("--task", default=DEFAULT_TASK, help="task description for the proposer")
    args = ap.parse_args()
    run(args.task)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
