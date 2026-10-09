# -*- coding: utf-8 -*-
"""core/symbols.py — the brain proposes expressions for the text it was shown
(C-TURN-1 Part 3c; C-BRAIN-1 Part 2: one call per sentence, TEXT B verbatim).

For at most 20 statements per brain turn, cortex-l1b-3b (through core.brain.think,
schema-bound, temperature 0) is asked TEXT B (core/brain_texts.py) once per
sentence and answers {"head", "args"}. Checks, all by code, and nothing else:
  1. HEAD: one word (a MeTTa symbol);
  2. SPAN: every argument is a literal span of the sentence, or a number in it;
  3. WHOLE: no argument is the whole sentence (TEXT B forbids it; the span check
     alone lets it through — C-BRAIN-1 Part 1 trial);
  4. PARSE: the repo's hyperon parses the expression (core.space.hyperon_engine).
The head is free: config/space_vocabulary.json only SUGGESTS heads; an unknown
head is accepted and counted in memory/space/new_relations.jsonl.
Accepted   -> memory/space/proposed.metta as (proposed "<statement id>" "cortex-l1b-3b" <expr>),
              ONCE: a proposal whose line is already in that file is not written again, and is
              counted as "already" (9 Oct 2026). Until then every brain turn appended its
              proposals blindly: by 9 Oct the file held 397 lines for 13 distinct statements, one
              line repeated 39 times, the shape proposed/3 crossed the arity-3 budget of 390, and
              core.space.derive refused the brain's turn (ENGINE_BUDGET, guard state RED, brain
              turn 164 exit 2). The file is a SET of proposals, not a log of proposing; what the
              3B was shown each turn is a separate question. tools/dedup_proposed.py repairs a
              file written by the old code.
Refused    -> memory/space/proposed_refused.jsonl with the reason.
NONE       -> head "NONE": the sentence states nothing; counted, nothing written.
UNREADABLE -> a schema-invalid reply, recorded with its raw text; no expression
              is invented.

    venv\\Scripts\\python.exe -m core.symbols --selftest
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
SPACE = REPO / "memory" / "space"
PATHS = {"proposed": SPACE / "proposed.metta", "refused": SPACE / "proposed_refused.jsonl",
         "new_relations": SPACE / "new_relations.jsonl", "log": SPACE / "symbols_log.jsonl",
         "vocabulary": REPO / "config" / "space_vocabulary.json",
         "ledger": REPO / "memory" / "vertical_ledger.jsonl"}
MODEL = "cortex-l1b-3b:latest"
MAX_PER_TURN = 20
FURNITURE_REGIONS = ("furniture",)     # 82C В1: never an input to a symbol proposal

class PathMissing(KeyError):
    pass


def _p(paths, k):
    if paths is None:
        return PATHS[k]
    if k not in paths:
        raise PathMissing(f"paths given without {k!r}")
    return paths[k]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _append(p, row: dict) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with Path(p).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"ts": _now(), **row}, ensure_ascii=False) + "\n")


_NUM = re.compile(r"-?\d+(?:[.,]\d+)*")


def _numbers_in(sentence: str) -> set:
    out = set()
    for m in _NUM.findall(sentence):
        try:
            out.add(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def span_problem(expr, sentence: str) -> Optional[str]:
    """None if every argument is a literal span of the sentence or a number in it."""
    if not isinstance(expr, list) or len(expr) < 2 or not isinstance(expr[0], str):
        return "not (head argument ...)"
    nums = _numbers_in(sentence)
    for a in expr[1:]:
        if isinstance(a, list):
            return "a nested expression is not a span"
        if isinstance(a, float):
            if a not in nums:
                return f"the number {a:g} is not in the sentence"
            continue
        if not str(a).strip() or str(a) not in sentence:
            return f"argument {str(a)!r} is not a span of the sentence"
    return None


def _engine_parses(expr_text: str, engine: Callable) -> Optional[str]:
    from core import space as sp
    try:
        engine(f"!(quote {expr_text})")
        return None
    except sp.SpaceEngineFailed as exc:
        return f"the engine did not parse it: {exc}"


def whole_sentence(expr, sentence: str) -> Optional[str]:
    """TEXT B: "Never use the whole sentence as an argument." """
    strip = lambda x: re.sub(r"[\s.!?;:,]+$", "", re.sub(r"\s+", " ", str(x)).strip())  # noqa: E731
    return ("an argument is the whole sentence"
            if any(isinstance(a, str) and strip(a) == strip(sentence) for a in expr[1:]) else None)


def head_problem(head) -> Optional[str]:
    from core import space as sp
    return None if isinstance(head, str) and sp._SYMBOL.fullmatch(head) else f"the head {head!r} is not one word"


def _think(prompt: str, evidence: str, schema: dict) -> Optional[dict]:
    from core import brain
    return brain.think("symbols for what I was shown", prompt, evidence=evidence, json_schema=schema,
                       exact=True, model_override=MODEL, kind="symbols")


def _known_counts(paths) -> dict:
    out = {}
    nr = Path(_p(paths, "new_relations"))
    if nr.exists():
        for line in nr.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[row["head"]] = row["count"]
    return out


def existing_proposals(path) -> set:
    """The (proposed …) lines already in the file, as a set. A missing or unreadable file is an
    EMPTY set: nothing is known, so nothing is suppressed."""
    try:
        return {l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines()
                if l.startswith("(proposed ")}
    except (OSError, ValueError):
        return set()


def propose(items: list, think: Optional[Callable] = None, engine: Optional[Callable] = None, paths=None) -> dict:
    """items: [{"id": statement id, "text": sentence}] (at most MAX_PER_TURN are used).
    TEXT B once per sentence. -> per-call record with the raw reply. A proposal identical to one
    already in proposed.metta is counted in "already" and not written a second time."""
    from core import brain_needs as bn
    from core import brain_texts as T
    from core import space as sp
    engine = engine or sp.hyperon_engine
    items = [i for i in items if i.get("id") and i.get("text")][:MAX_PER_TURN]
    out = {"asked": len(items), "accepted": [], "refused": [], "none": [], "unreadable": [], "already": [],
           "new_heads": {}, "calls": []}
    if not items:
        return out
    seen = existing_proposals(_p(paths, "proposed"))
    vocab = json.loads(Path(_p(paths, "vocabulary")).read_text(encoding="utf-8")).get("suggested_heads", [])
    heads = ", ".join(vocab)
    known = _known_counts(paths)
    t0 = time.time()
    for it in items:
        sid, sentence = it["id"], it["text"]
        if it.get("region") in FURNITURE_REGIONS:
            # 82C В1: page furniture is never an input to a symbol, whatever hands it over
            row = {"statement": sid, "expression": None, "reason": f"region {it.get('region')!r} is page furniture"}
            out["refused"].append(row)
            _append(_p(paths, "refused"), row)
            out["calls"].append({"statement": sid, "sentence": sentence, "raw": None, "sec": None,
                                 "outcome": "REFUSED: page furniture"})
            continue
        try:
            r = (think or _think)(T.TEXT_B.format(heads=heads, sentence=sentence), "", T.SCHEMA_B)
        except Exception as exc:                                         # noqa: BLE001
            r = {"unreadable": f"{type(exc).__name__}: {exc}", "raw": None}
        d, raw, why = bn.bound(r, T.SCHEMA_B)
        call = {"statement": sid, "sentence": sentence, "raw": raw, "sec": (r or {}).get("sec")}
        out["calls"].append(call)
        if d is None:
            row = {"event": "UNREADABLE", "what": "symbols", "statement": sid, "why": why, "raw": raw}
            _append(_p(paths, "log"), row)
            _append(_p(paths, "ledger"), row)
            out["unreadable"].append(row)
            call["outcome"] = "UNREADABLE"
            continue
        if d["head"] == "NONE":
            out["none"].append(sid)
            call["outcome"] = "NONE"
            continue
        expr = [d["head"]] + [float(a) if isinstance(a, (int, float)) and not isinstance(a, bool) else a
                              for a in d["args"]]
        why = (head_problem(expr[0]) or span_problem(expr, sentence) or whole_sentence(expr, sentence)
               or _engine_parses(sp.render(expr), engine))
        if why:
            row = {"statement": sid, "expression": raw, "reason": why}
            out["refused"].append(row)
            _append(_p(paths, "refused"), row)
            call["outcome"] = f"REFUSED: {why}"
            continue
        head = expr[0]
        if head not in vocab:
            known[head] = known.get(head, 0) + 1
            out["new_heads"][head] = known[head]
            _append(_p(paths, "new_relations"), {"head": head, "count": known[head], "statement": sid})
        line = f'(proposed "{sid}" "{MODEL.split(":")[0]}" {sp.render(expr)})'
        if line in seen:
            # the same proposal for the same statement is no new expression: it is not written
            out["already"].append({"statement": sid, "expression": sp.render(expr), "head": head})
            call["outcome"] = "ALREADY PROPOSED"
            continue
        pp = Path(_p(paths, "proposed"))
        pp.parent.mkdir(parents=True, exist_ok=True)
        with pp.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"; proposed-by {MODEL} for statement {sid} at {_now()}\n{line}\n")
        seen.add(line)
        out["accepted"].append({"statement": sid, "expression": sp.render(expr), "head": head})
        call["outcome"] = "ACCEPTED"
    out["sec"] = round(time.time() - t0, 1)
    _append(_p(paths, "log"), {"event": "PROPOSED", "asked": len(items), "accepted": len(out["accepted"]),
                               "refused": len(out["refused"]), "none": len(out["none"]),
                               "unreadable": len(out["unreadable"]), "already": len(out["already"]),
                               "new_heads": out["new_heads"]})
    return out


def selftest() -> dict:
    res = {"integrations": {
        "config/space_vocabulary.json": "LIVE" if PATHS["vocabulary"].exists() else "INERT (missing)",
        "memory/space/proposed.metta": "LIVE" if PATHS["proposed"].exists() else "INERT (nothing proposed yet)",
    }}
    tb = REPO / "scripts" / "turn_brain.py"
    res["integrations"]["the brain's turn proposes symbols"] = (
        "LIVE" if tb.exists() and "symbols.propose(" in tb.read_text(encoding="utf-8") else "INERT")
    res["checks"] = {"a span outside the sentence is refused": span_problem(["x", "Mars"], "Goma is in Kivu") is not None,
                     "a span inside is accepted": span_problem(["located-in", "Goma", "Kivu"], "Goma is in Kivu") is None}
    res["ok"] = all(res["checks"].values())
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    print(__doc__)
