# -*- coding: utf-8 -*-
"""experiments/pulse/local_model.py — the local model over Ollama HTTP, and the JSON
it returns (C-FIX-1, 2 Oct 2026).

MOVED, NOT REWRITTEN: these four names lived in experiments/browser_scout/
autonomous_scout.py, a web collector deleted by C-FIX-1 (R43: only OpenClaw reaches
the web). Their live users never scouted anything — experiments/pulse/pulse_continuum.py
(the creative tick) and experiments/selfcode/selfcode_loop.py import only the model
call and the JSON extractor. The code below is the code that was there.
"""
from __future__ import annotations

import json
import os

_OLLAMA = os.environ.get("CORTEX_OLLAMA_URL", "http://localhost:11434")
# The warm core (25 Sep 2026): any other local model evicts it on a 4 GB card.
_MODEL  = os.environ.get("CORTEX_LOCAL_MODEL", "cortex-l1b-3b:latest")


def _local(prompt: str, timeout: int = 120, num_predict: int = 300) -> str:
    """Sovereign local model over Ollama HTTP. Raises on failure (caller handles)."""
    import requests
    # keep_alive=0 — UNLOAD IMMEDIATELY (30 Aug 2026). MEASURED, not guessed:
    # ollama serve holds 2,031 MB flat, a model runner adds 6,263 MB, the machine
    # has 13.9 GB, and the cycle's homeostasis gate needs 2 GB free to start. This
    # function is called by experiments/pulse/pulse_continuum.py:428,580 — which
    # CORTEX_Pulse fires EVERY FIVE MINUTES. It sent no keep_alive at all, so
    # Ollama applied its 5-minute server default and the next pulse re-touched
    # the model before it expired: a model that never unloads, by accident. The
    # 03:00 cycle refused twice in eighteen hours with 1.0-1.2 GB free.
    #
    # THIS IS A FAMILY, NOT AN INCIDENT, and that is why the citation is here:
    # core/reaction.py:143 already records this exact defect — "passed no
    # keep_alive at all, so a timed-out reaction left the model" — found, fixed
    # and written down. It then recurred in this file, which nobody was checking.
    # A defect that is documented once and repeats is a defect the documentation
    # did not prevent.
    #
    # THE ENVIRONMENT VARIABLE IS SET TOO, AND THEY HAVE DIFFERENT JOBS.
    # OLLAMA_KEEP_ALIVE=0 (user scope) governs any caller that FORGETS to send
    # one — it is the net under the next unknown case, and it is irrelevant to
    # the 41 call_local_llm sites that override it per request. This line is the
    # opposite: it states the intent AT THE SITE and does not depend on the
    # machine's environment, so a clone, a container or a reset profile behaves
    # the same. The variable defends against the unknown; the constant fixes the
    # known.
    #
    # THE COST, NAMED SO NOBODY REDISCOVERS IT: every call now reloads the model.
    # For a five-minutely background probe that is the entire point. Six other
    # callers share this function — goal_impact.py, semantic_scout.py,
    # shadow_test_semantic.py and selfcode_loop.py — all DORMANT per
    # docs/EXPERIMENT_AUTOPSY_2026-08-29.md, so nothing live pays it today. A
    # future tight loop through _local() would, and should set its own value
    # rather than raise this one.
    r = requests.post(f"{_OLLAMA}/api/chat", timeout=timeout, json={
        "model": _MODEL, "stream": False,
        # the one policy: the core stays (-1), anything else unloads (0)
        "keep_alive": -1 if _MODEL == "cortex-l1b-3b:latest" else 0,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.1, "num_predict": num_predict}})
    r.raise_for_status()
    return ((r.json().get("message") or {}).get("content") or "").strip()


def _json_from(text: str):
    """Last {...} block the model emitted (think-block safe)."""
    depth, start, best = 0, -1, None
    for i, c in enumerate(text):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                best = text[start:i + 1]
    if not best:
        raise ValueError("no JSON object in model output")
    return json.loads(best)
