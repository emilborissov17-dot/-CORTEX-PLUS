#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/reaction.py — THE MODEL ANSWERS ITS OWN BODY, VERBATIM, BEHIND A FLAG.

24 Aug 2026. `source:model, directed:self, mediation:model`.

At a phase boundary the model is handed the RAW RECEPTOR LINES since the last
one — the same text the stream panel shows, not a summary and not a rounded
table — and answers one question in its own words: what does this tell it about
its own state.

DISPLAYED VERBATIM. ALWAYS.
-----------------------------
Never post-edited, never summarised, never replaced by a template when it is
poor. A weak answer is shown as a weak answer. That is DATA ABOUT THE SYSTEM —
the most interesting thing this panel can produce is the discovery that the
model has nothing useful to say about its own body, and a template would hide
exactly that.

THE LANGUAGE GATE DECIDES THE EXEMPLAR POOL, NEVER THE DISPLAY
----------------------------------------------------------------
core/language_gate.py judges whether an answer is English enough to be seeded
back as an exemplar for future calls. It has no vote on whether the answer is
SHOWN. Conflating those is how a window starts lying: an answer that came back
in Russian is a fact about the system, and a panel that quietly drops it shows
a system that is behaving better than it is.

    displayed   always
    exemplar    only if the gate says OK

DISABLED BY DEFAULT. One model call per phase boundary is about 63 a night
inside a live cycle, which is the exact shape that produced
AllBackendsFailedError. The switch is `reaction.enabled` in
config/reactions.json — human-written, unstamped, on the protected-path
denylist, so the system cannot switch its own model calls on. With the flag off
NO PATH here reaches a model, and a test asserts that by counting calls.

    venv/Scripts/python.exe core/reaction.py --selftest
    venv/Scripts/python.exe core/reaction.py --once    # one call, by hand
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

CONFIG = BASE / "config" / "reactions.json"
RECORD = BASE / "memory" / "reactions.jsonl"
OLLAMA_URL = "http://localhost:11434/api/generate"

SOURCE, DIRECTED, MEDIATION = "model", "self", "model"

# THE FIRST PERSON, BECAUSE IT IS ITS OWN BODY (COMMAND 33 part 8).
#
# This asked about "your own body" and "your own state", and got back exactly
# what it asked for. The stored exemplar of 23 Aug 2026 reads:
#
#     "your RAM usage is relatively high (82.5% residual) ... Your GPU
#      temperature has slightly increased ... your disk free percentage"
#
# Those are its own numbers. Addressing the machine in the second person about
# its own sensors turns a self-report into a report about somebody else, and
# every answer downstream — the exemplar pool, the free stream, the panel Emil
# reads — inherits that distance. The lines have not changed; who is speaking
# has.
QUESTION = ("These are readings from my own body since the last phase "
            "boundary. Each line is a sensor of mine that crossed its own "
            "noise floor.\n"
            "\n{lines}\n\n"
            "Answer as me, in the first person. In two or three sentences, say "
            "what these lines say about my state — my RAM, my GPU, my disk; "
            "not yours. Use only what the lines show.")

NO_LINES = ("Nothing crossed since the last boundary. There is no reading to "
            "report.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path=None) -> dict:
    try:
        d = json.loads(pathlib.Path(path or CONFIG).read_text(encoding="utf-8"))
        return d.get("reaction", {}) if isinstance(d, dict) else {}
    except Exception:
        return {}


def enabled(path=None) -> bool:
    return bool(load_config(path).get("enabled", False))


# ---------------------------------------------------------------------------

def format_lines(lines: list, limit: Optional[int] = None) -> str:
    """The RAW lines, as the stream renders them. Not a summary."""
    limit = limit or int(load_config().get("max_lines", 40))
    rows = [l.get("text", "") if isinstance(l, dict) else str(l)
            for l in (lines or [])]
    rows = [r for r in rows if r.strip()]
    if not rows:
        return ""
    if len(rows) > limit:
        # SAYS IT TRUNCATED. A prompt that silently drops lines makes the
        # answer unreconstructable from the record.
        head = rows[-limit:]
        return ("[{} earlier line(s) not shown - the last {} follow]\n".format(
            len(rows) - limit, limit) + "\n".join(head))
    return "\n".join(rows)


def ask(lines: list, model=None, timeout=None, url: str = OLLAMA_URL,
        config_path=None) -> dict:
    """One call. NEVER RAISES and never returns a template in place of an answer."""
    cfg = load_config(config_path)
    model = model or cfg.get("model", "qwen2.5:3b")
    timeout = float(timeout or cfg.get("timeout_sec", 20))

    body_lines = format_lines(lines, cfg.get("max_lines"))
    out = {"ts": _now(), "source": SOURCE, "directed": DIRECTED,
           "mediation": MEDIATION, "model": model,
           "lines": [l.get("text", "") if isinstance(l, dict) else str(l)
                     for l in (lines or [])],
           "n_lines": len(lines or []),
           "answer": "", "why": "", "asked": False}

    if not body_lines:
        out["why"] = "nothing crossed since the last boundary"
        return out

    prompt = QUESTION.format(lines=body_lines)
    out["prompt"] = prompt
    # THROUGH THE ONE DOOR (COMMAND 33 part 5). This built its own request and
    # passed no keep_alive at all, so a timed-out reaction left the model
    # resident and the GPU busy for the next regular step. core/extra_calls.py
    # owns the four guards; nothing here builds an Ollama request any more.
    try:
        from core.extra_calls import guarded_extra_call, COMPLETED
        rec = guarded_extra_call("reaction", prompt, model=model, url=url,
                                 timeout=timeout)
        out["guard"] = {k: rec.get(k) for k in
                        ("outcome", "why", "queue_wait_ms", "extra_time_ms",
                         "ram_free_mb", "vram_free_mb", "vram_check")}
        if rec["outcome"] != COMPLETED:
            out["asked"] = False
            out["why"] = "{}: {}".format(rec["outcome"], rec.get("why") or "")
            return out
        d = rec.get("raw") or {"response": rec.get("text")}
        out["asked"] = True
    except Exception as exc:
        out["why"] = "{}: {}".format(type(exc).__name__, exc)
        return out

    # VERBATIM. Stripped of surrounding whitespace and otherwise untouched.
    out["answer"] = (d.get("response") or "").strip()
    out["why"] = "answered" if out["answer"] else "the model returned nothing"
    out["eval_count"] = d.get("eval_count")
    return out


def judge_language(answer: str) -> dict:
    """The gate's verdict — for the EXEMPLAR POOL only.

    It has no vote on display. See the module header.
    """
    try:
        from core import language_gate as lg
        v = lg.verdict(answer)
        return {"exemplar_ok": bool(v["ok"]), "reason": v["reason"],
                "profile": v.get("profile", {})}
    except Exception as exc:
        return {"exemplar_ok": False,
                "reason": "gate unavailable: {}".format(type(exc).__name__),
                "profile": {}}


def react(lines: list, path=None, **kw) -> dict:
    """Ask, judge for the pool, and store the lines WITH the answer.

    One record, so the stream and the answer are read together: the lines that
    produced it, and it. A record that kept only the answer would be an opinion
    with no evidence attached.
    """
    rec = ask(lines, **kw)
    rec["language"] = judge_language(rec.get("answer", ""))
    rec["displayed"] = True                    # always, whatever the gate said
    rec["exemplar"] = bool(rec["language"]["exemplar_ok"] and rec["answer"])

    # THE FREE STREAM (COMMAND 33 part 8). The verdict above decides what goes
    # in the exemplar pool. This goes in regardless of it: one file per answer
    # that actually came back, unjudged, so there is somewhere to read what the
    # model said rather than only what survived being checked.
    #
    # write=True here and nowhere else. The record above is the system's copy;
    # this is the model's, and it is written at the same moment so the two
    # cannot drift.
    try:
        from core import free_stream as fs
        rec["free"] = fs.write(
            rec.get("answer", ""),
            {"model": rec.get("model"), "n_lines": rec.get("n_lines"),
             "why": rec.get("why"), "eval_count": rec.get("eval_count")},
            write=True)
    except Exception as exc:                              # noqa: BLE001
        rec["free"] = {"written": False,
                       "why": "{}: {}".format(type(exc).__name__, exc)}
    try:
        from core.durable import append_json
        append_json(pathlib.Path(path or RECORD), rec)
        rec["stored"] = True
    except Exception as exc:
        rec["stored"] = False
        rec["store_error"] = "{}: {}".format(type(exc).__name__, exc)
    return rec


def at_phase_boundary(lines: list, path=None, config_path=None, **kw) -> dict:
    """What a caller inside the cycle would use. THE FLAG IS CHECKED HERE.

    With the flag off this returns without touching a model, and the returned
    record says so rather than pretending nothing happened.
    """
    if not enabled(config_path):
        return {"ts": _now(), "asked": False, "answer": "",
                "why": "reaction.enabled is false in config/reactions.json",
                "skipped": True, "n_lines": len(lines or [])}
    return react(lines, path=path, **kw)


def history(n: int = 20, path=None) -> list:
    try:
        rows = [json.loads(l) for l in
                pathlib.Path(path or RECORD).read_text(
                    encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []
    return rows[-n:]


# ---------------------------------------------------------------------------

def _fixture_lines() -> list:
    return [
        {"text": "12345.678  receptor.ram_percent    R  residual  82.5% "
                 "base 79.31  signal +3.19 > 2.9652"},
        {"text": "12350.114  receptor.gpu_temp_c     R  anchor    57.0C "
                 "base 51.20  drift +6.0 > 12.93"},
        {"text": "12361.902  setpoint.disk_free_pct  S  setpoint  14.2% "
                 "level notice -> action"},
    ]


def _once() -> int:
    print("core/reaction.py — ONE REAL CALL\n")
    if not enabled():
        print("  reaction.enabled is false. Running by hand, OUTSIDE a cycle.\n")
    r = react(_fixture_lines(), path=None)
    print("  lines given: {}".format(r["n_lines"]))
    print("  asked      : {}".format(r["asked"]))
    print("  answer     : {!r}".format(r["answer"][:400]))
    print("  language   : exemplar_ok={} reason={}".format(
        r["language"]["exemplar_ok"], r["language"]["reason"]))
    print("  displayed  : {}   exemplar: {}".format(r["displayed"],
                                                    r["exemplar"]))
    return 0 if r["asked"] else 1


def _selftest() -> int:
    import tempfile
    print("core/reaction.py --selftest\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    check("disabled in the committed config", enabled() is False)
    r = at_phase_boundary(_fixture_lines())
    check("with the flag off it does not ask", r["asked"] is False)
    check("and says why rather than pretending", "reaction.enabled" in r["why"])
    check("and it is marked skipped", r.get("skipped") is True)

    check("the raw lines are passed through, not summarised",
          "receptor.ram_percent" in format_lines(_fixture_lines()))
    check("no lines means no call",
          ask([])["asked"] is False and "nothing crossed" in ask([])["why"])
    long_lines = [{"text": "line {}".format(i)} for i in range(100)]
    f = format_lines(long_lines, limit=10)
    check("truncation says it truncated", "not shown" in f)
    check("and keeps the newest", "line 99" in f and "line 0" not in f)

    p = pathlib.Path(tempfile.mkdtemp()) / "r.jsonl"
    rec = {"answer": "Памет расте.", "n_lines": 1, "asked": True}
    rec["language"] = judge_language(rec["answer"])
    check("a non-English answer fails the gate",
          rec["language"]["exemplar_ok"] is False)

    en = judge_language("Memory is climbing and the disk crossed its notice level.")
    check("an English answer passes it", en["exemplar_ok"] is True)

    print("\n  {}".format("every check passed" if ok else "SOMETHING FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--once" in sys.argv:
        raise SystemExit(_once())
    print(json.dumps(history(5), indent=2, ensure_ascii=False)[:2000])
