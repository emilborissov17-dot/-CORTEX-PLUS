# -*- coding: utf-8 -*-
"""ITEM 43.1 — a backend-identity field either carries a real identity or does not exist.

THE DEFECT. On 2026-08-29 all three cloud tiers were unavailable and nine agents
fell through to local qwen2.5:3b — 29 calls in one cycle. Every axis snapshot
written that night carried a field literally named "model" whose value was a
COMPILE-TIME CONSTANT: "WORLD_BANK_API", "QWEN_PLANET_SNAPSHOT_AGENT",
"CLIMATE_GLOBAL_RISK_MULTI_REAL_DATA". A reader who opens such a snapshot sees a
model field and believes it records what answered. It records nothing. That is
worse than an absent field: absence prompts a question, a constant answers it
wrongly.

Kimi: "Standardize on a provenance object {backend, model, degraded} rather than
cosmos's flat source_type - adopt cosmos's honesty pattern but add the
backend/degradation dimension that source_type lacks."

WHY THESE TESTS READ SOURCE AND NOT SNAPSHOTS. The standing rule is that tests
never touch live state; snapshots/ is rewritten every cycle, so a test asserting
over the files on disk would pass or fail by the calendar. The claim being tested
is about WRITERS, and writers are source. Every assertion here is AST over the
writer modules.
"""
from __future__ import annotations

import ast
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# The modules that persist an axis payload. Named explicitly rather than
# discovered, so adding a fourth writer is a visible decision in a diff and not
# something a glob quietly starts or stops covering.
WRITERS = (
    "agents/planet/planet_snapshots_agent_qwen.py",
    "agents/cosmos/cosmos_snapshots_agent_qwen.py",
    "_refresh_three_axes.py",
)

# Field names that ASSERT WHO COMPUTED THIS. A constant here is a false claim.
#
# "data_source" is deliberately NOT in this set, and the distinction is the
# whole argument: "WORLD_BANK_API" as a *data source* is true, constant by
# construction, and stays true forever — the World Bank API really is where
# those numbers come from. The same string under a key called "model" claims a
# model identity it does not have. The defect was never the constant; it was the
# constant sitting under a name that makes a different claim.
IDENTITY_KEYS = {"model", "backend", "llm", "provider", "answered_by",
                 "model_used", "llm_backend"}


def _writers():
    out = []
    for rel in WRITERS:
        p = BASE / rel
        assert p.exists(), f"{rel} is missing — WRITERS is stale"
        out.append((rel, ast.parse(p.read_text(encoding="utf-8", errors="replace"))))
    return out


def _constant_identity_claims(rel: str, tree: ast.AST):
    """Every place this module puts a LITERAL into an identity-claiming field.

    Three shapes, because the defect wore all three and a check that caught only
    the first would have reported the file clean:
      1. a dict literal          {"model": "WORLD_BANK_API"}
      2. a .get() default        payload.get("model", "QWEN_PLANET_SNAPSHOT_AGENT")
      3. a subscript assignment  payload["model"] = "CLIMATE_..."
    """
    found = []
    for node in ast.walk(tree):
        # 1. dict literal
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value in IDENTITY_KEYS
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)):
                    found.append((rel, k.lineno, k.value, v.value, "dict literal"))
        # 2. .get("model", "CONST")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in IDENTITY_KEYS
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)):
            found.append((rel, node.lineno, node.args[0].value,
                          node.args[1].value, ".get() default"))
        # 3. payload["model"] = "CONST"
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if (isinstance(t, ast.Subscript)
                        and isinstance(t.slice, ast.Constant)
                        and t.slice.value in IDENTITY_KEYS):
                    found.append((rel, node.lineno, t.slice.value,
                                  node.value.value, "subscript assignment"))
    return found


# ── (a) THE TEST THAT MUST FAIL ON HEAD ────────────────────────────────────

def test_no_writer_puts_a_constant_into_an_identity_field():
    """RUN THIS AGAINST HEAD BEFORE THE FIX. If it passes there, the test is
    wrong and the test is what gets fixed — not the claim."""
    bad = []
    for rel, tree in _writers():
        bad += _constant_identity_claims(rel, tree)
    assert not bad, (
        "these writers stamp a COMPILE-TIME CONSTANT into a field that claims "
        "to say what produced the value:\n  "
        + "\n  ".join(f"{r}:{ln}  {k!r} = {v!r}   ({how})"
                      for r, ln, k, v, how in bad)
        + "\nA constant that reads as provenance is worse than an absent field. "
          "Either carry the real identity (core.answered_by.stamp()) or remove "
          "the field.")


def test_every_writer_stamps_real_provenance():
    """The other half. Removing the false field without adding the true one
    would satisfy the test above and leave the system exactly as blind."""
    missing = []
    for rel, tree in _writers():
        # ALIAS-AWARE, AND IT HAD TO BE FIXED TO BECOME SO. The first version of
        # this check looked for a call to the literal name `stamp`, and reported
        # all three writers unwired while every one of them called
        # `_prov_stamp()` — the same alias blindness that made orphan_scan
        # understate live wiring by 77 entrypoints until commit 9b85408. A test
        # that reads only the ORIGINAL name cannot see an aliased import; the
        # binding is a PAIR, (original, local), and the local name is what
        # appears at the call site.
        local_names = {"stamp"}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(
                    ("provenance", "answered_by")):
                for a in n.names:
                    if a.name == "stamp":
                        local_names.add(a.asname or a.name)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and ((isinstance(n.func, ast.Name) and n.func.id in local_names)
                      or (isinstance(n.func, ast.Attribute)
                          and n.func.attr == "stamp"))]
        if not calls:
            missing.append(rel)
    assert not missing, (
        "these writers persist an axis payload without calling "
        "core.answered_by.stamp():\n  " + "\n  ".join(missing))


def test_cosmos_keeps_source_type():
    """cosmos's source_type is HONEST and says something provenance does not —
    REAL_DATA vs REAL_DATA_CARRIED vs LLM_GENERATED is a claim about the value's
    origin, where the stamp is a claim about the step. Adding one must not cost
    the other."""
    src = (BASE / "agents/cosmos/cosmos_snapshots_agent_qwen.py").read_text(
        encoding="utf-8", errors="replace")
    for token in ("REAL_DATA", "REAL_DATA_CARRIED", "LLM_GENERATED"):
        assert token in src, f"cosmos lost {token} — source_type must survive"


# ── (b) THREE DISTINCT OUTCOMES, ONE ASSERTION EACH ────────────────────────

class _FakeContract:
    """Stands in for an open StepContract. Only the two attributes stamp()
    reads are needed, and using the real class would require a live cycle."""
    def __init__(self, degraded=None, count=0):
        self.degraded = degraded
        self.degraded_count = count


def _with_contract(c):
    import core.step_contract as sc
    from core.answered_by import stamp
    saved = sc._CURRENT
    try:
        sc._CURRENT = c
        return stamp()
    finally:
        sc._CURRENT = saved


def test_inside_a_degraded_step_the_stamp_says_degraded_true():
    s = _with_contract(_FakeContract(
        "answered by local_3b (qwen2.5:3b) after the cloud tier was abandoned "
        "at its slice of B=3416s", 3))
    assert (s["degraded"] is True and s["backend"] == "local_3b"
            and s["model"] == "qwen2.5:3b"), s


def test_inside_a_clean_step_the_stamp_says_degraded_false():
    s = _with_contract(_FakeContract(None, 0))
    assert s["degraded"] is False and s["backend"] is None, s


def test_outside_any_step_the_stamp_says_none_and_not_false():
    """THE ASSERTION THIS WHOLE ITEM EXISTS FOR. 'Nothing degraded' and 'nobody
    was watching' are different facts, and a bool cannot hold both."""
    s = _with_contract(None)
    assert s["degraded"] is None and s["why"] == "no open step contract", s


def test_an_unparseable_reason_does_not_invent_a_backend():
    """groq_backend emits a second reason shape ('no tier answered within
    B=...'). A parser that guessed would manufacture the very false provenance
    this file removes."""
    s = _with_contract(_FakeContract("no tier answered within B=900s (exhausted)"))
    assert s["degraded"] is True and s["backend"] is None and s["model"] is None, s
    assert s["why"].startswith("no tier answered"), s
