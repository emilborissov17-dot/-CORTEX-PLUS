# -*- coding: utf-8 -*-
"""
training/l1_ollama_holdout.py — WHERE did the L1 skill get lost? (12 Sep 2026)

Kaggle said: after LoRA, 197/200 right and 47/50 twins flip with the number.
The machine said (hand test, one line, "degrees"): cortex-l1-3b answers OVER for 39 and
OVER for 37 — no flip. Three explanations, and each one has a different cure:

  A. the export broke it  (4-bit -> 16-bit merge -> GGUF q4_k_m, Ollama template)
  B. the long real prompt breaks it  (brain.think wraps the question in BODY, five
     self-state rows full of numbers, SPIRIT, MEMORY, the language pin twice)
  C. it learned the FORM of the lessons, not the skill  (the hand test was worded
     differently from every lesson)

This separates them by asking the SAME holdout questions three ways:

  exact   the holdout prompt exactly as in Kaggle, via Ollama /api/chat
          -> if this is ~0.98 / ~47 flips, the export is fine (not A)
  brain   the same QUESTION + MATERIAL through core.brain.think(model_override=...),
          the door every real call uses
          -> if exact is good and this is bad, the long prompt is the culprit (B)
  (the hand test and the probe cover C: new wording, real cases)

Every verdict is checked by arithmetic (meta.truth written when the file was made).
Usage:
  venv\\Scripts\\python.exe training\\l1_ollama_holdout.py --n 60 cortex-l1-3b qwen2.5:3b
  -> one JSON line per (model, mode) and memory/l1_ollama_holdout.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
HOLD = REPO / "training" / "l1_numbers_holdout.jsonl"
OUT = REPO / "memory" / "l1_ollama_holdout.json"
OLLAMA = "http://127.0.0.1:11434"
SCHEMA = {"verdict": "exactly one word: OVER if the value is on the bad side of the line, UNDER if it is not",
          "reason": "one sentence, from the material"}


def verdict_of(text) -> str | None:
    if isinstance(text, dict):
        text = json.dumps(text)
    m = re.search(r'"?verdict"?\s*:\s*"?(OVER|UNDER)', str(text or ""), re.IGNORECASE)
    return m.group(1).upper() if m else None


def split_prompt(content: str) -> tuple[str, str]:
    """QUESTION and MATERIAL back out of a lesson prompt."""
    q = content.split("QUESTION: ", 1)[1].split("\n\nMATERIAL:", 1)[0].strip()
    mat = content.split("MATERIAL:\n", 1)[1].split("\n\nAnswer ONLY", 1)[0]
    return q, mat


def ask_exact(model: str, content: str) -> str | None:
    import requests
    r = requests.post(f"{OLLAMA}/api/chat", timeout=180, json={
        "model": model, "stream": False, "messages": [{"role": "user", "content": content}],
        "options": {"temperature": 0.0, "num_predict": 120}})
    r.raise_for_status()
    return verdict_of((r.json().get("message") or {}).get("content"))


def ask_brain(model: str, content: str) -> str | None:
    from core import brain
    q, mat = split_prompt(content)
    have = brain.models()               # Ollama lists "cortex-l1-3b:latest"; an exact-name miss falls back to the 8B
    name = model if model in have else (f"{model}:latest" if f"{model}:latest" in have else model)
    out = brain.think("probe: read two numbers", q, evidence=mat, schema=SCHEMA, kind="counterfactual_probe",
                      remember_it=False, fast=False, temperature=0.0, model_override=name)
    if isinstance(out, dict) and out.get("_model") and str(out["_model"]).split("local:", 1)[-1] != name:
        return "FALLBACK"
    return verdict_of(out)


def score(rows: list, answers: list) -> dict:
    right = sum(1 for r, a in zip(rows, answers) if a == r["meta"]["truth"])
    by = {}
    for r, a in zip(rows, answers):
        m = r["meta"]
        by.setdefault((m["case"], m["line"], m["direction"]), []).append((m["truth"], a))
    twins = [p for p in by.values() if len(p) >= 2 and p[0][0] != p[1][0]]
    flips = sum(1 for p in twins if p[0][1] in ("OVER", "UNDER") and p[1][1] in ("OVER", "UNDER") and p[0][1] != p[1][1])
    return {"n": len(rows), "answered": sum(a in ("OVER", "UNDER") for a in answers),
            "fallback": answers.count("FALLBACK"), "accuracy": round(right / max(1, len(rows)), 3),
            "twins": len(twins), "twins_flipped": flips,
            "said_over_share": round(answers.count("OVER") / max(1, len(answers)), 3)}


def pick_rows(n: int) -> list:
    """Complete twin pairs first, so a small n still measures flips."""
    rows = [json.loads(line) for line in HOLD.open(encoding="utf-8")]
    by = {}
    for r in rows:
        m = r["meta"]
        by.setdefault((m["case"], m["line"], m["direction"]), []).append(r)
    pairs = [p[:2] for p in by.values() if len(p) >= 2 and p[0]["meta"]["truth"] != p[1]["meta"]["truth"]]
    out = [r for p in pairs for r in p][:n]
    return out


def dump_real_prompt(path: Path | None = None) -> dict:
    """The REAL wrapper brain.think puts around a question, block by block, so the next
    lessons (L1b) can be written in the shape the brain actually receives — not a stand-in.
    Built from brain.think's own helpers; nothing is sent to any model."""
    from core import brain
    blocks = {"head": "You are the brain of CORTEX++ — not an assistant, but the system itself, thinking.\n"
                      "ROLE NOW: probe: read two numbers",
              "body": brain._body(), "self_state": brain._self_state(), "spirit": brain._spirit(),
              "memory": brain._memory("counterfactual_probe"), "language_pin": brain.LANGUAGE_PIN,
              "limits": ("LIMITS ON THE ACTION (not on the thought): free or local solutions only; do not edit "
                         f"{', '.join(brain.POLICY['protected_files'])} yourself — for those, propose to the human.\n"
                         "Think from the material, not in generalities. If the material is not enough for a "
                         "conclusion, say so.")}
    blocks["chars"] = {k: len(v) for k, v in blocks.items() if isinstance(v, str)}
    blocks["chars_total"] = sum(blocks["chars"].values())
    path = path or (REPO / "memory" / "l1_real_prompt_blocks.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blocks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"dumped": str(path), "chars": blocks["chars"], "chars_total": blocks["chars_total"]}))
    return blocks


def main(argv: list) -> dict:
    if "--dump-prompt" in argv:
        return dump_real_prompt()
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 60
    skip = {argv[argv.index(f) + 1] for f in ("--n", "--only") if f in argv}
    models = [a for a in argv if not a.startswith("--") and a not in skip] or ["cortex-l1-3b", "qwen2.5:3b"]
    modes = ["exact", "brain"] if "--only" not in argv else [argv[argv.index("--only") + 1]]
    rows = pick_rows(n)
    report = {"n_rows": len(rows), "results": []}
    for model in models:
        for mode in modes:
            ask = ask_exact if mode == "exact" else ask_brain
            answers = []
            for r in rows:
                try:
                    answers.append(ask(model, r["messages"][0]["content"]))
                except Exception as exc:          # a dead call is counted, never guessed
                    answers.append(None)
                    print(f"  [{model}/{mode}] error: {type(exc).__name__}: {exc}")
            res = {"model": model, "mode": mode, **score(rows, answers)}
            print(json.dumps(res))
            report["results"].append(res)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    main(sys.argv[1:])
