# -*- coding: utf-8 -*-
"""core/symbols.py — the brain proposes expressions for the text it was shown
(C-TURN-1 Part 3c).

For at most 20 statements per brain turn, cortex-l1b-3b (through core.brain.think)
proposes one expression each, e.g. (located-in "Goma" "Nord Kivu"). Two checks,
both by code, and nothing else:
  1. SPAN: every argument is a literal span of the statement's sentence, or a
     number that appears in it;
  2. PARSE: the repo's hyperon parses the expression (core.space.hyperon_engine).
The head is free: config/space_vocabulary.json only SUGGESTS heads; an unknown
head is accepted and counted in memory/space/new_relations.jsonl.
Accepted  -> memory/space/proposed.metta as (proposed "<statement id>" "cortex-l1b-3b" <expr>),
             in the space on the next turn, told apart from base by the label.
Refused   -> memory/space/proposed_refused.jsonl with the reason.
SILENCE   -> an empty or unparseable reply is recorded with its raw text; no
             expression is invented.

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
         "vocabulary": REPO / "config" / "space_vocabulary.json"}
MODEL = "cortex-l1b-3b:latest"
MAX_PER_TURN = 20

QUESTION = (
    "For each numbered sentence below, propose ONE expression that states what it says, in the form "
    "(head \"argument\" \"argument\" ...). Every argument must be copied EXACTLY from that sentence, or be a "
    "number that appears in it. Suggested heads (you may use another): {heads}. "
    'Answer ONLY with JSON: {{"proposals": [{{"statement": "<the id in brackets>", "expression": "(...)"}}]}}')


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


def _think(question: str, evidence: str) -> dict:
    from core import brain
    return brain.think("symbols for what I was shown", question, evidence=evidence, schema=None,
                       model_override=MODEL, kind="symbols")


def propose(items: list, think: Optional[Callable] = None, engine: Optional[Callable] = None, paths=None) -> dict:
    """items: [{"id": statement id, "text": sentence}] (at most MAX_PER_TURN are used)."""
    from core import space as sp
    engine = engine or sp.hyperon_engine
    items = [i for i in items if i.get("id") and i.get("text")][:MAX_PER_TURN]
    if not items:
        return {"asked": 0, "accepted": [], "refused": [], "silence": None, "new_heads": {}}
    vocab = json.loads(Path(_p(paths, "vocabulary")).read_text(encoding="utf-8")).get("suggested_heads", [])
    by_id = {i["id"]: i["text"] for i in items}
    evidence = "\n".join(f"[{i['id']}] {i['text']}" for i in items)
    t0 = time.time()
    try:
        r = (think or _think)(QUESTION.format(heads=", ".join(vocab)), evidence)
    except Exception as exc:                                         # noqa: BLE001
        r = {"text": None, "error": f"{type(exc).__name__}: {exc}"}
    raw = (r or {}).get("text")
    sec = (r or {}).get("sec", round(time.time() - t0, 1))
    props = None
    if raw:
        s = raw.strip()
        i, j = s.find("{"), s.rfind("}")
        try:
            d = json.loads(s[i:j + 1]) if i >= 0 and j > i else None
            props = d.get("proposals") if isinstance(d, dict) else None
        except ValueError:
            props = None
    if not isinstance(props, list):
        sil = {"event": "SILENCE", "raw": raw, "why": "empty reply" if not raw else "reply is not parseable JSON",
               "asked": len(items)}
        _append(_p(paths, "log"), sil)
        return {"asked": len(items), "accepted": [], "refused": [], "silence": sil, "new_heads": {}, "sec": sec,
                "raw": raw}
    accepted, refused, new_heads = [], [], {}
    known_counts = {}
    nr = Path(_p(paths, "new_relations"))
    if nr.exists():
        for line in nr.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                known_counts[row["head"]] = row["count"]
    for pr in props:
        sid = (pr or {}).get("statement") if isinstance(pr, dict) else None
        sid = str(sid or "").strip("[] ")
        text = (pr or {}).get("expression") if isinstance(pr, dict) else None
        why = None
        if sid not in by_id:
            why = f"statement {sid!r} was not one of those shown"
        elif not isinstance(text, str) or not text.strip().startswith("("):
            why = "the expression is not (head ...)"
        else:
            try:
                expr = sp.parse(text.strip())
            except (IndexError, ValueError):
                expr, why = None, "the expression does not parse as an s-expression"
            if why is None:
                why = span_problem(expr, by_id[sid]) or _engine_parses(sp.render(expr), engine)
        if why:
            row = {"statement": sid, "expression": text, "reason": why}
            refused.append(row)
            _append(_p(paths, "refused"), row)
            continue
        head = expr[0]
        if head not in vocab:
            known_counts[head] = known_counts.get(head, 0) + 1
            new_heads[head] = known_counts[head]
            _append(nr, {"head": head, "count": known_counts[head], "statement": sid})
        line = f'(proposed "{sid}" "{MODEL.split(":")[0]}" {sp.render(expr)})'
        pp = Path(_p(paths, "proposed"))
        pp.parent.mkdir(parents=True, exist_ok=True)
        with pp.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"; proposed-by {MODEL} for statement {sid} at {_now()}\n{line}\n")
        accepted.append({"statement": sid, "expression": sp.render(expr), "head": head})
    _append(_p(paths, "log"), {"event": "PROPOSED", "asked": len(items), "accepted": len(accepted),
                               "refused": len(refused), "new_heads": new_heads})
    return {"asked": len(items), "accepted": accepted, "refused": refused, "silence": None, "new_heads": new_heads,
            "sec": sec, "raw": raw}


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
