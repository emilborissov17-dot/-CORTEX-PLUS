"""
test/test_llm_one_door.py — no model endpoint is called except through core/llm_door.py.

24 Sep 2026 (Emil, 19 Sep: ONE DOOR). Phase 1 of task #19 found 12 call sites in the
cycle's code that reached a model without going through the ladder, 11 of them with
no provenance. They now call core.llm_door.post / core.llm_door.call.

This is an AST check on code, never on prose: a Call to post/get/urlopen/request/_open
whose URL — the argument itself, or the value the argument's name was assigned in
the same function — points at a model endpoint. Exempt by construction: the call
inside a lambda handed to llm_door.call, and /api/tags or /api/ps (listing, no
generation). Everything else exempt is named below with its reason.

CYCLE_PATHS may hold no violation at all. Outside them, OUT_OF_SCOPE_DEBT names every
file that is known not to be converted yet — a line there is a debt, not a
dispensation, and any file NOT named there fails the test.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOOR = "core/llm_door.py"
CYCLE_PATHS = ("core/", "agents/", "memory/", "fast_cycle_runner.py", "supervisor.py")
SKIP_DIRS = {"venv", "venv312_metta", "venv_train", "test", ".git", "node_modules", "__pycache__"}

LLM = re.compile(r"11434|_OLLAMA_URL|OLLAMA_URL\b|OLLAMA_GENERATE|OLLAMA_CHAT|api\.groq\.com|GROQ_API_URL|GROQ_URL|openrouter\.ai|OPENROUTER_API_URL|"
                 r"generativelanguage|GEMINI_API_URL|NVIDIA_API_URL|integrate\.api\.nvidia|"
                 r"/api/chat|/api/generate|/api/embed", re.I)
LISTING = re.compile(r"/api/tags|/api/ps|MODELS_URL|_PS\b|OLLAMA_PS")
HTTP_ATTRS = {"post", "get", "urlopen", "request"}
# the called object must be an HTTP client, not a dict or os.environ
HTTP_CLIENT = re.compile(r"^(requests|_rq|_req|rq|req|urllib|urllib\.request|_open|opener|session|_session|http)\b")

# (file, function) -> why it is not a model call through the door
NOT_A_GENERATION = {
    ("core/model_window.py", "_set_keep_alive"): "loads/unloads a model (empty messages) - residency control",
    ("core/aggressive_cleanup.py", "release_ollama"): "keep_alive=0 unload - residency control",
    ("core/interval_head.py", "embed"): "embedding, not generation",
    ("core/interval_head.py", "_selftest"): "embedding endpoint ping",
    ("memory/autonomic_pulse.py", "_measure"): "connectivity GET of api.groq.com, no prompt",
}

OUT_OF_SCOPE_DEBT: dict = {
    'experiments/browser_scout/autonomous_scout.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'experiments/dreams/dream.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'experiments/kimi_duel/consult.py': "3 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'experiments/kimi_duel/duel.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'experiments/prophecy/goal_prophecy.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'experiments/pulse/self_sense.py': "2 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'experiments/selfcode/selfcode_loop.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'scripts/_cuda_churn_probe.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'scripts/_probe_models.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'scripts/test_local_brain.py': "2 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'tools/first_bet.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'tools/transfer_test.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'training/l1_ollama_holdout.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
    'youtube_intel.py': "1 direct call(s); outside the cycle, not converted (task #19 b, 24 Sep 2026)",
}


def _files():
    for p in REPO.rglob("*.py"):
        rel = p.relative_to(REPO).as_posix()
        if set(rel.split("/")[:-1]) & SKIP_DIRS or rel == DOOR:
            continue
        yield rel, p


def _violations(rel: str, path: Path) -> list:
    try:
        src = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(src)
    except Exception:
        return []
    parents = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[ch] = node

    def enclosing(node, kinds):
        while node in parents:
            node = parents[node]
            if isinstance(node, kinds):
                return node
        return None

    def in_door_lambda(node):
        lam = enclosing(node, (ast.Lambda,))
        while lam is not None:
            call = parents.get(lam)
            if isinstance(call, ast.Call) and "llm_door.call" in (ast.get_source_segment(src, call.func) or ""):
                return True
            lam = enclosing(lam, (ast.Lambda,))
        return False

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
        if name not in HTTP_ATTRS and name != "_open":
            continue
        ftext = ast.get_source_segment(src, f) or ""
        if "llm_door" in ftext:
            continue
        if not (name in ("urlopen", "_open") or HTTP_CLIENT.search(ftext)):
            continue
        arg = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "url"), None)
        if arg is None:
            continue
        text = ast.get_source_segment(src, arg) or ""
        fn = enclosing(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if isinstance(arg, ast.Name) and fn is not None:
            for a in ast.walk(fn):
                if isinstance(a, ast.Assign) and any(isinstance(t, ast.Name) and t.id == arg.id for t in a.targets):
                    text += " " + (ast.get_source_segment(src, a.value) or "")
        if not LLM.search(text) or LISTING.search(text):
            continue
        if in_door_lambda(node):
            continue
        fname = fn.name if fn is not None else "<module>"
        if (rel, fname) in NOT_A_GENERATION:
            continue
        out.append(f"{rel}:{node.lineno} in {fname}(): {text.strip()[:80]}")
    return out


def test_every_model_call_goes_through_the_door():
    inside, outside = [], {}
    for rel, path in _files():
        v = _violations(rel, path)
        if not v:
            continue
        if rel.startswith(CYCLE_PATHS):
            inside += v
        else:
            outside[rel] = v
    assert not inside, ("model calls in the cycle's code that bypass core/llm_door.py:\n  "
                        + "\n  ".join(inside))
    new = {k: v for k, v in outside.items() if k not in OUT_OF_SCOPE_DEBT}
    assert not new, ("model calls outside the cycle's paths, not in OUT_OF_SCOPE_DEBT:\n  "
                     + "\n  ".join(f"{k}: {v}" for k, v in new.items()))


def test_the_exemptions_still_exist():
    """A named exemption whose function is gone is a stale line - it must be removed."""
    for (rel, fname), why in NOT_A_GENERATION.items():
        p = REPO / rel
        assert p.exists(), f"exempt file gone: {rel} ({why})"
        names = {n.name for n in ast.walk(ast.parse(p.read_text(encoding="utf-8-sig")))
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert fname in names, f"exempt function gone: {rel}:{fname} ({why})"
