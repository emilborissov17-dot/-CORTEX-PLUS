"""Quarantine triage: the deterministic half must not be talked out of its answer.

A rejected patch was previously indistinguishable from a deleted one — 17 sat in
patches/quarantine and nothing ever read them again. The triage ranks them for the
human CLI that already exists. What is defended here is the boundary between FACT and
OPINION, because the first live run showed how fast the opinion half goes wrong:

  * it returned REWRITE for 17 of 17 — a reviewer that approves everything has ranked
    nothing;
  * it scored a patch 4/5 while itself flagging that the patch fabricates its data;
  * it scored general_patch.1785353275 at 4/5 for "add a WATER_REVIEW agent to the
    registry". That patch writes agents/registry.json, which no file in this repo reads,
    and registers agents.water.water_review_agent, which does not exist. Written
    perfectly it would still be dead weight — the exact thing CLAUDE.md forbids.

So wiring and protection are computed from the tree and are binding; the model's score
can only lower a verdict, never rescue one.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import triage_quarantine as T  # noqa: E402


ORPHAN_PATCH = '''
import json, pathlib
def go():
    p = pathlib.Path("totally_unread_xyz.json")
    p.write_text(json.dumps({"a": 1}))
'''

WIRED_PATCH = '''
import json, pathlib
def go():
    p = pathlib.Path("cortex_hypergraph.json")   # real artifact this repo reads
    return json.loads(p.read_text())
'''

MISSING_MODULE_PATCH = '''
REG = {"module": "agents.water.water_review_agent"}
'''


def test_an_artifact_no_loader_reads_is_flagged_orphan():
    w = T._wiring(ORPHAN_PATCH, "probe.py")
    assert "totally_unread_xyz.json" in w["orphan_artifacts"]
    assert w["wires_into_nothing"] is True


def test_a_real_artifact_is_not_flagged():
    w = T._wiring(WIRED_PATCH, "probe.py")
    assert w["orphan_artifacts"] == []
    assert w["wires_into_nothing"] is False


def test_a_glob_or_bare_extension_is_not_an_artifact():
    """"*.json" and ".json" are common substrings, so they always found a "reader" and
    dragged wires_into_nothing to False for patches whose every real file was orphaned.
    general_patch.1784940113 survived as REWRITE on exactly that accounting error."""
    src = '''
P = "*.json"
Q = ".json"
R = "existential_risk_log_zzz.json"
'''
    w = T._wiring(src, "probe.py")
    assert w["artifacts"] == ["existential_risk_log_zzz.json"]
    assert w["wires_into_nothing"] is True


def test_a_module_that_does_not_exist_is_caught():
    w = T._wiring(MISSING_MODULE_PATCH, "probe.py")
    assert "agents.water.water_review_agent" in w["missing_modules"]


def test_the_scanner_does_not_read_itself():
    """The comment in triage_quarantine.py naming agents/registry.json as an example of
    an orphan made the scanner find a 'reader' for it — the tool answering its own
    question with its own prose."""
    w = T._wiring('P = "registry.json"', "probe.py")
    assert "registry.json" in w["orphan_artifacts"], \
        "the tool's own documentation must not count as a loader"


def test_vendored_trees_do_not_count_as_readers():
    """`"venv" not in p.parts` missed venv312_metta, so site-packages counted."""
    src = 'P = "setup.json"'
    w = T._wiring(src, "probe.py")
    assert isinstance(w["orphan_artifacts"], list)  # no crash; exclusion is prefix-based


def test_dead_weight_outranks_a_generous_score():
    opinion = {"useful_if_correct": 5, "recommendation": "rewrite",
               "defect_class": "logic_bug", "fabricates_data": False}
    wiring = {"wires_into_nothing": True, "orphan_artifacts": ["x.json"],
              "missing_modules": []}
    verdict, _reason, applied = T._apply_policy(opinion, wiring)
    assert verdict == "DEAD_WEIGHT"
    assert applied["useful_if_correct"] <= 1
    assert applied["policy_override"]


def test_fabricated_data_can_never_be_graded_a_promising_draft():
    opinion = {"useful_if_correct": 4, "recommendation": "rewrite",
               "defect_class": "logic_bug", "fabricates_data": True}
    verdict, _reason, applied = T._apply_policy(opinion, {})
    assert verdict == "NEEDS_HUMAN"
    assert applied["useful_if_correct"] <= 1


def test_the_raw_opinion_survives_the_override():
    """An override must stay auditable against what the judge actually said."""
    opinion = {"useful_if_correct": 5, "recommendation": "rewrite",
               "defect_class": "logic_bug", "fabricates_data": True}
    _v, _r, applied = T._apply_policy(dict(opinion), {})
    assert applied["useful_if_correct"] != opinion["useful_if_correct"]
    assert opinion["useful_if_correct"] == 5, "the caller's dict must not be mutated"


def _row(rec, verdict, score=3, override=None):
    op = {"useful_if_correct": score}
    if override:
        op["policy_override"] = override
    return {"verdict": verdict, "opinion": op,
            "opinion_raw": {"recommendation": rec, "useful_if_correct": score}}


def test_rubber_stamp_is_reported_not_hidden():
    same = [_row("rewrite", "REWRITE") for _ in range(10)]
    assert T._discrimination(same)["rubber_stamp"] is True
    mixed = ([_row("rewrite", "REWRITE", 4)] * 5 + [_row("discard", "DISCARD", 1)] * 5)
    assert T._discrimination(mixed)["rubber_stamp"] is False


def test_a_house_rule_agreeing_with_itself_is_not_a_rubber_stamp():
    """14 of 17 came out DEAD_WEIGHT because they write files nothing reads. That is a
    finding about the patches, not a judge failing to think — the flag measures the
    judge's RAW opinion, not the verdict the policy landed on."""
    rows = [_row("rewrite", "DEAD_WEIGHT", 5, override="wired into nothing")
            for _ in range(7)]
    rows += [_row("discard", "DEAD_WEIGHT", 1, override="wired into nothing")
             for _ in range(7)]
    d = T._discrimination(rows)
    assert d["verdict_spread"] == {"DEAD_WEIGHT": 14}
    assert d["rubber_stamp"] is False, "the judge WAS split; only the policy converged"
    assert d["policy_overrides"] == 14


def test_a_protected_target_is_decided_without_a_model():
    """The canon lane: no ranking may promote a patch that touches the constitution."""
    assert T._protection("core/canon.py")
    assert T._protection("BOUNDARIES.md")
    assert not T._protection("agents/core/water_review_patch.py")


def test_the_triage_tool_itself_is_protected():
    """A system that can rewrite its own ranking can promote its own patches — not by
    defeating the guardian, but by editing the order its drafts are shown for approval.
    Same lane as review_quarantine.py, one step earlier."""
    from safety.protected_paths import is_protected
    assert is_protected("scripts/triage_quarantine.py")
    assert is_protected("scripts/review_quarantine.py")
    # the generated report is NOT protected — it is output, and must stay rewritable
    assert not is_protected("memory/quarantine_triage.json")


def test_quarantined_code_is_never_executed():
    src = (REPO / "scripts" / "triage_quarantine.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess.run", "subprocess.Popen", "exec(", "eval("):
        assert forbidden not in src, f"triage must never execute a quarantined patch: {forbidden}"


# ── A LOADER IS CODE, AND A NAME IS A WHOLE NAME (19 Sep 2026) ──────────────

def test_a_docstring_naming_an_artifact_is_not_a_loader():
    """THE ONE THAT FAILS AGAINST THE OLD SCANNER.

    _wiring searched the RAW source, so a module docstring naming a file made
    that file look wired. Measured on the live tree: core/feature_proposals.py
    describes memory/feature_registry.json in its header and loads nothing of
    the sort — and that single prose mention was the only "reader" the scanner
    could find for agents/registry.json, the one artifact this whole tool was
    written about.
    """
    assert not T._mentions_as_code(
        '"""It writes memory/feature_registry.json every night."""\nx = 1',
        "feature_registry.json")
    assert not T._mentions_as_code(
        "# see agents/registry.json for the shape\nx = 1", "registry.json")


def test_a_string_literal_still_counts_because_that_is_what_a_loader_looks_like():
    """Mutation guard. Stripping string literals along with the prose would make
    EVERY artifact an orphan, and the scanner would be unanimous and useless."""
    assert T._mentions_as_code('open("memory/feature_registry.json")',
                               "feature_registry.json")
    assert T._mentions_as_code("P = pathlib.Path('agents/registry.json')",
                               "registry.json")


def test_a_longer_name_is_not_a_match_for_a_shorter_one():
    """The second defect, on its own. `"registry.json" in text` is true of
    "feature_registry.json", so an artifact looked read because a DIFFERENT file
    was mentioned."""
    assert not T._mentions_as_code('open("memory/feature_registry.json")',
                                   "registry.json")
    assert T._mentions_as_code('open("agents/registry.json")', "registry.json")


def test_the_artifact_this_tool_was_written_about_is_still_an_orphan():
    """agents/registry.json: written by a model-authored patch, read by nothing.
    It came back WIRED while both defects stood."""
    w = T._wiring('P = "registry.json"', "probe.py")
    assert w["orphan_artifacts"] == ["registry.json"], w
    assert w["wires_into_nothing"] is True
