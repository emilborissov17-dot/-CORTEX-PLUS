#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_declared_step_inputs.py — A WRITTEN INPUT CONTRACT MAY OPEN A GATE,
AND MUST NEVER OPEN ONE IT DOES NOT MENTION.

WHAT WAS BROKEN (measured 18 August 2026)
-----------------------------------------
`core/notary.py:_age_state` grades a step by the age of the files it reads, and got
that list from `core/metta_check._REQ` <- `core/cycle_graph.scan_requires()`, a
static scanner that only resolves LITERAL paths under
`(memory|snapshots|config|output|data|news)/`.

    >>> core.cycle_graph.scan_requires()["github_publish"]
    []

The scanner is not wrong. `github_publisher._find_latest_web_intel_dir()` builds its
path at runtime by listing `memory/web_intelligence` and choosing the newest dated
folder — there is no literal to find. Since 17 Aug an empty list correctly returns
UNKNOWN instead of FULL, so the step was refused every night for IGNORANCE. The
contract was being inferred where it should have been written down.

WHAT THIS FILE LOCKS — BOTH DIRECTIONS AND A CONTROL
-----------------------------------------------------
The mechanism is only safe because it is asymmetric, so the asymmetry is what gets
asserted, not just the happy path:

  * present   -> `github_publish` is graded on `memory/web_intelligence` and the
                 age dimension can reach FULL. The record names WHERE the list came
                 from, so a night the gate opened can be traced to the declaration
                 that opened it.
  * removed / unreadable / malformed -> exactly today's behaviour returns. Every
                 failure path degrades to the scanner, and the scanner's silence is
                 UNKNOWN, which is a refusal.
  * POSITIVE CONTROL on an UNDECLARED step -> a step the file does not mention must
                 be completely unaffected. If `test_a_missing_declaration_still_refuses`
                 passed because the whole mechanism was inert, this control would
                 also pass; it is here to make sure the file can only ever speak for
                 the steps it names.

WHY THE CONTROL STEP IS `self_modifier`
---------------------------------------
It is the step that writes generated Python into this repo, it is irreversible, and
it harvests to `[]` for the same reason `github_publish` did. If a written
declaration could ever widen a step it never mentions, that is the step where it
would cost the most. It is asserted here and deliberately NOT declared anywhere.

    venv\\Scripts\\python.exe -m pytest test/test_declared_step_inputs.py -v
"""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTARY_SRC = REPO_ROOT / "core" / "notary.py"

DECLARED_STEP = "github_publish"
DECL_REL = "config/step_inputs.json"

# THE CONTROL SUBJECT MOVED, AND WHY IT HAD TO (31 Aug 2026).
# This was `self_modifier`, chosen because it is irreversible AND named nowhere
# in the declaration - so it could prove that a file written about one step says
# nothing about another. Commit 8b0bca6 (21 Aug) declared it, and the control
# stopped controlling anything: it asserted a step was undeclared while the file
# declared it.
#
# THERE IS NO UNDECLARED IRREVERSIBLE STEP LEFT. All three - execute_patches,
# self_modifier, github_publish - are now in config/step_inputs.json. So the
# irreversibility half of the old choice cannot be preserved, and pretending
# otherwise would be the retirement this control exists to prevent.
#
# `notify_patches_and_initiatives` keeps the half that the test actually
# measures: it is undeclared, it harvests [] from the scanner (so UNKNOWN is the
# honest answer for it), and it still touches the world - it sends messages out,
# and an unsent message cannot be recalled. If it is ever declared, this test
# will say so in the same words, and the next reader picks again.
UNDECLARED_STEP = "notify_patches_and_initiatives"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pristine_notary():
    """core/notary.py loaded under a private name.

    conftest.py's autouse `_no_live_side_effects` replaces `core.notary.attest` with
    a recorder returning None — correctly, since the real one appends to the
    attestation chain and test-fabricated rows in that chain are exactly the
    contamination that fixture prevents. But `may_act()` reaches `attest()` through
    the module global, so through the patched module the real arithmetic is
    unreachable. A private copy of the file AS IT IS ON DISK gives it back without
    un-patching the live module for anyone else. (Same device as
    test/test_notary_gate.py; kept identical on purpose.)
    """
    spec = importlib.util.spec_from_file_location("_notary_declared_inputs_test", NOTARY_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def notary(tmp_path, monkeypatch):
    """Pristine notary whose append-only chain points at a throwaway directory."""
    mod = _pristine_notary()
    chain = tmp_path / "attestation"
    chain.mkdir()
    monkeypatch.setattr(mod, "ATTEST_DIR", chain)
    monkeypatch.setattr(mod, "ATTEST_LOG", chain / "attest.jsonl")
    monkeypatch.setattr(mod, "ATTEST_HEAD", chain / "chain.head")
    return mod


@pytest.fixture
def declaration():
    """The live config/step_inputs.json, parsed. Never written by this suite."""
    return json.loads((REPO_ROOT / DECL_REL).read_text(encoding="utf-8"))


@pytest.fixture
def healthy_environment(notary, monkeypatch):
    """Pin the four non-age dimensions to FULL so `age` is the only variable.

    Without this, `_witness_state()` is UNKNOWN in a fresh test process (MeTTa is
    built once per cycle, not per import) and every level would be 0 no matter what
    the declaration says — a test that passes for a reason it is not measuring.
    """
    for name in ("_witness_state", "_human_state", "_thought_state"):
        monkeypatch.setattr(notary, name, lambda: (notary.FULL, "forced FULL for this test"))
    monkeypatch.setattr(notary, "_promise_state",
                        lambda *a: (notary.FULL, "forced FULL for this test"))
    return notary


@pytest.fixture
def fresh_inputs_on_disk(notary, declaration, tmp_path, monkeypatch):
    """A tmp repo where every declared input of `github_publish` exists and is new.

    The live repo cannot be used for the OPEN direction: `memory/web_intelligence`
    is rewritten by the nightly cycle, so the answer would depend on whether a cycle
    happened to have run — and the same test would silently start measuring the
    clock instead of the mechanism. Here the inputs are unambiguously fresh, so a
    refusal can only come from the declaration not being read.
    """
    for rel in declaration["steps"][DECLARED_STEP]["inputs"]:
        p = tmp_path / rel
        p.mkdir(parents=True, exist_ok=True)
        (p / "fixture.json").write_text('{"axis": "fixture"}', encoding="utf-8")
    monkeypatch.setattr(notary, "BASE", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# The declaration is a description of the module, not a wish
# ---------------------------------------------------------------------------

def test_the_declaration_matches_what_the_publisher_opens(declaration):
    """Every declared input must be a path `github_publisher.py` really reads.

    A declaration that outruns the module is worse than no declaration: it hands a
    step provenance from files it never touches, and the gate would then be graded
    on the freshness of something irrelevant. Asserted against the module SOURCE, so
    it goes red the day the publisher stops reading `memory/web_intelligence` —
    which is the day this entry becomes a lie.
    """
    entry = declaration["steps"][DECLARED_STEP]
    src = (REPO_ROOT / "github_publisher.py").read_text(encoding="utf-8")

    assert entry["inputs"] == ["memory/web_intelligence"], (
        f"declared inputs changed to {entry['inputs']}. Re-derive them by reading "
        f"github_publisher.publish_synthesis() and update this assertion in the same "
        f"change — do not relax it.")

    # The path is assembled as BASE_DIR / "memory" / "web_intelligence", which is
    # exactly why no literal exists for the scanner to find.
    assert '"memory" / "web_intelligence"' in src, (
        "github_publisher no longer builds memory/web_intelligence — the declared "
        "input does not describe the module any more.")

    for rel in entry["inputs"]:
        assert (REPO_ROOT / rel).exists(), (
            f"declared input {rel} is not in the repo. A declared input that is "
            f"missing scores UNKNOWN, so this entry now closes the gate it was "
            f"written to open.")


def test_the_publishers_other_reads_are_declared_as_excluded(declaration):
    """Everything the module opens is accounted for — as an input or as a stated
    exclusion with a reason.

    The point of a WRITTEN contract is that omissions are visible. A path that is
    read but appears nowhere in this file is indistinguishable from a path somebody
    forgot, and a human reviewing the entry cannot tell which. Cross-checked against
    docs/MODULE_MAP.json, whose AST pass lists the module's resolvable reads.
    """
    entry = declaration["steps"][DECLARED_STEP]
    accounted = set(entry["inputs"]) | set(entry["also_reads"])

    modmap = json.loads((REPO_ROOT / "docs" / "MODULE_MAP.json").read_text(encoding="utf-8"))
    publisher = next(m for m in modmap["modules"] if m["module"] == "github_publisher.py")

    unaccounted = [r for r in publisher["reads"] if r not in accounted]
    assert not unaccounted, (
        f"github_publisher.py reads {unaccounted}, and {DECL_REL} neither declares "
        f"them as inputs nor states why they are excluded. Say which it is — an "
        f"unmentioned read is indistinguishable from a forgotten one.")

    for rel, reason in entry["also_reads"].items():
        assert len(reason) > 40, (
            f"exclusion of {rel} carries no reason. Excluding a read from the age "
            f"grade is a trust decision and has to be argued in the file.")


# ---------------------------------------------------------------------------
# DIRECTION 1 — declaration present -> the gate opens
# ---------------------------------------------------------------------------

def test_a_written_declaration_opens_the_gate(healthy_environment, fresh_inputs_on_disk):
    """With the declaration in place and its inputs fresh, the step may act.

    THE STAKE: this is the step that writes to a PUBLIC GitHub repository. Before the
    declaration existed it was refused every night — not for a fault, but because the
    static scanner could not resolve a runtime-built path and `[]` means UNKNOWN. A
    gate that refuses for ignorance is not stricter than one that refuses for cause;
    it is just uninformative, and it teaches whoever reads the log to ignore it.
    """
    notary = healthy_environment
    rec = notary.attest(DECLARED_STEP)

    assert rec["inputs"] == ["memory/web_intelligence"], (
        f"attest() graded {DECLARED_STEP} on {rec['inputs']} — the written "
        f"declaration is not reaching the notary.")
    assert rec["vector"]["age"] == notary.FULL, (
        f"age scored {rec['vector']['age']} on freshly written inputs "
        f"({rec['why']['age']}) — the declared paths are not being stat-ed.")

    ok, why = notary.may_act(DECLARED_STEP)
    assert ok and rec["level"] >= notary.IRREVERSIBLE_MIN, (
        f"may_act({DECLARED_STEP!r}) refused at {rec['level_name']}: {why}\n"
        f"  vector: {rec['vector']}\n  why: {rec['why']}")


def test_the_record_names_where_the_trust_came_from(healthy_environment,
                                                    fresh_inputs_on_disk):
    """The reason string must name the declaration, not merely the level.

    A number in an audit log is not evidence of anything on its own. `level_2` says
    how much the notary trusted the step; it does not say that the trust rests on a
    human-written file which a human can therefore review, narrow, or revoke. The
    one night this matters is the night somebody asks why the system published.
    """
    notary = healthy_environment
    rec = notary.attest(DECLARED_STEP)
    ok, why = notary.may_act(DECLARED_STEP)

    assert ok, f"gate refused, so there is no permission to explain: {why}"
    assert DECL_REL in rec["inputs_source"], (
        f"attestation row credits {rec['inputs_source']!r}, which does not name "
        f"{DECL_REL}")
    assert DECL_REL in rec["why"]["age"], (
        f"the age reason {rec['why']['age']!r} does not say where the input list "
        f"came from — the durable record must carry it, not just the console line")
    assert DECL_REL in why, (
        f"may_act's permission reads {why!r} — it must name the written declaration "
        f"as the source of the trust it just granted")


# ---------------------------------------------------------------------------
# DIRECTION 2 — declaration gone / broken -> the gate refuses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("breakage", [
    "file_missing",
    "not_json",
    "no_steps_key",
    "step_absent",
    "inputs_not_a_list",
    "path_escapes_the_repo",
])
def test_a_broken_declaration_refuses_exactly_as_before(breakage, healthy_environment,
                                                        fresh_inputs_on_disk,
                                                        monkeypatch, tmp_path):
    """Every failure path degrades to the scanner, and the scanner's silence refuses.

    THE STAKE: this is the whole fail-closed property. A trust file that can be
    corrupted into GRANTING trust is worse than none — the corruption would be
    invisible, because a level_3 row looks identical whether it was earned or fell
    out of a parse error. So each way the file can be wrong is enumerated and each
    one has to land on the same answer: refuse.

    `path_escapes_the_repo` is the adversarial case rather than the careless one: a
    declaration pointing at C:/... or ../ could be aimed at a file that is always
    fresh, manufacturing FULL age out of nothing. `_clean` rejects the entry and, by
    the all-or-nothing rule in `_load`, the whole list with it.
    """
    di = importlib.import_module("core.declared_inputs")
    decl = tmp_path / "step_inputs.json"

    if breakage == "file_missing":
        pass                                            # simply never written
    elif breakage == "not_json":
        decl.write_text("{ this is not json", encoding="utf-8")
    elif breakage == "no_steps_key":
        decl.write_text(json.dumps({"github_publish": ["memory/web_intelligence"]}),
                        encoding="utf-8")
    elif breakage == "step_absent":
        decl.write_text(json.dumps({"steps": {"some_other_step": {"inputs": []}}}),
                        encoding="utf-8")
    elif breakage == "inputs_not_a_list":
        decl.write_text(json.dumps({"steps": {DECLARED_STEP:
                                              {"inputs": "memory/web_intelligence"}}}),
                        encoding="utf-8")
    elif breakage == "path_escapes_the_repo":
        decl.write_text(json.dumps({"steps": {DECLARED_STEP: {"inputs": [
            "memory/web_intelligence", "../always_fresh.json"]}}}), encoding="utf-8")

    monkeypatch.setattr(di, "PATH", decl)

    notary = healthy_environment
    rec = notary.attest(DECLARED_STEP)
    ok, why = notary.may_act(DECLARED_STEP)

    assert rec["vector"]["age"] == notary.UNKNOWN, (
        f"[{breakage}] age scored {rec['vector']['age']} ({rec['why']['age']!r}) with "
        f"no usable declaration. A broken trust file must not produce trust.")
    assert not ok, (
        f"[{breakage}] may_act({DECLARED_STEP!r}) PERMITTED an irreversible action "
        f"({why}) from a declaration that is {breakage.replace('_', ' ')}.")


def test_removing_the_live_declaration_closes_the_gate(healthy_environment,
                                                       fresh_inputs_on_disk,
                                                       monkeypatch, tmp_path):
    """POSITIVE CONTROL for the open direction.

    `test_a_written_declaration_opens_the_gate` would pass just as happily if the
    gate were open for some unrelated reason. This takes the real file away — nothing
    else changes, same fixtures, same fresh inputs on disk — and requires the answer
    to flip. If it does not, the open direction is not measuring the declaration.
    """
    di = importlib.import_module("core.declared_inputs")
    notary = healthy_environment

    before_ok, _ = notary.may_act(DECLARED_STEP)
    assert before_ok, "the gate was not open to begin with — nothing to control for"

    monkeypatch.setattr(di, "PATH", tmp_path / "gone.json")
    after_ok, after_why = notary.may_act(DECLARED_STEP)

    assert not after_ok, (
        f"the gate stayed open with {DECL_REL} removed ({after_why}) — whatever is "
        f"holding it open, it is not the written declaration.")


# ---------------------------------------------------------------------------
# POSITIVE CONTROL — an undeclared step is untouched
# ---------------------------------------------------------------------------

def test_an_undeclared_step_still_refuses(healthy_environment, fresh_inputs_on_disk,
                                          declaration):
    """`self_modifier` is not in the file and must be exactly as it was.

    THE STAKE: `self_modifier` writes generated Python into this repo. The mechanism
    is safe only because a declaration can speak for the steps it NAMES and has no
    way to say anything about the rest. If this ever goes green-to-red, a file a
    human wrote about one step has silently changed the grade of another.
    """
    notary = healthy_environment
    assert UNDECLARED_STEP not in declaration["steps"], (
        f"{UNDECLARED_STEP} has been declared in {DECL_REL}. That may well be "
        f"correct, but this control test no longer controls anything — pick another "
        f"undeclared irreversible step, or delete the test knowingly.")

    from core.declared_inputs import for_step
    assert for_step(UNDECLARED_STEP) is None, (
        "for_step() must return None (no declaration), never [] — the two mean "
        "different things to _inputs_for")

    rec = notary.attest(UNDECLARED_STEP)
    ok, why = notary.may_act(UNDECLARED_STEP)

    assert "config/step_inputs.json" not in rec["inputs_source"], (
        f"{UNDECLARED_STEP} is being credited to the written declaration "
        f"({rec['inputs_source']!r}) despite not appearing in it")
    assert rec["vector"]["age"] == notary.UNKNOWN, (
        f"{UNDECLARED_STEP} scored age {rec['vector']['age']} ({rec['why']['age']!r}) "
        f"on a healthy environment. It declares nothing and the scanner resolves "
        f"nothing for it; the only honest answer is UNKNOWN.")
    assert not ok, (
        f"may_act({UNDECLARED_STEP!r}) permitted self-modification: {why}. A "
        f"declaration written for {DECLARED_STEP} has widened a step it never named.")


# ---------------------------------------------------------------------------
# The file is human-owned
# ---------------------------------------------------------------------------

def test_the_declaration_is_human_only():
    """No generated patch may write the file that decides what a step is trusted on.

    Both enforcement layers, independently — the shape check and the target check —
    because a bypass of one must not be a bypass of the system. This is the property
    that stops the mechanism becoming a mirror: without it the self-modifier could
    write itself an input list and grade itself on files it never reads.
    """
    from safety.protected_paths import PROTECTED_FILES, is_protected, protection_reason

    assert is_protected(DECL_REL), f"{DECL_REL} is writable by generated code"
    assert protection_reason(DECL_REL)

    assert DECL_REL in PROTECTED_FILES, (
        f"{DECL_REL} is protected only by the blanket over config/. Name it "
        f"explicitly: that blanket covers ordinary settings and is the kind of rule "
        f"someone narrows one day — this file must lose its protection on purpose, "
        f"in a diff that says so, not as a side effect.")

    from safety.ast_gate import check_code
    allowed, reason = check_code(
        f'from pathlib import Path\n'
        f'Path("{DECL_REL}").write_text("{{}}")\n')
    assert not allowed, f"the AST gate let generated code rewrite {DECL_REL}: {reason}"


# ---------------------------------------------------------------------------
# The overlay, at the layer the rest of the system reads
# ---------------------------------------------------------------------------

def test_the_scanner_prefers_the_written_declaration():
    """`scan_requires()` — the single source of `_REQ` — must return the written list.

    Wiring, not intent. If the overlay is ever dropped from
    `core/cycle_graph.scan_requires()`, `core/declared_inputs.py` keeps parsing
    perfectly and every test above it that reads the notary keeps passing, while the
    graph, `can_skip`, and `_REQ` quietly go back to `[]`.
    """
    from core.cycle_graph import scan_requires
    from core.declared_inputs import all_declared

    harvested = scan_requires()
    for step, files in all_declared().items():
        assert harvested.get(step) == list(files), (
            f"scan_requires() returns {harvested.get(step)!r} for {step}, but "
            f"{DECL_REL} declares {files!r}. Written must beat inferred.")

    assert harvested.get(UNDECLARED_STEP) == [], (
        f"{UNDECLARED_STEP} now harvests {harvested.get(UNDECLARED_STEP)!r}. If the "
        f"scanner genuinely improved, good — but check that the overlay is not "
        f"leaking lists into steps the declaration never named.")
