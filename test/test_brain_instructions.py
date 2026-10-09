# -*- coding: utf-8 -*-
"""test/test_brain_instructions.py — C-BRAIN-1 Part 2: the brain's replies are
schema-bound, its instructions are the written ones, and a question is narrowed,
not repeated. The model is injected (think(prompt, evidence, schema)); every path
is under tmp_path; core.brain.think is driven with a stubbed HTTP door.

What a REFUSAL looks like here, and the forbidden fallback:
  * a schema-invalid reply is UNREADABLE, recorded with its raw text — never
    repaired, never replaced by a default need, verdict or expression;
  * a general need is a PARENT: never searched, never re-emitted;
  * a narrower question that repeats one already held is REPEAT, not added.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import brain_needs as bn  # noqa: E402
from core import brain_texts as T  # noqa: E402

FIVE = ["CIVILIZATIONAL_STABILITY", "HEALTHY_ENVIRONMENTS", "KNOWLEDGE_UNDERSTANDING", "SAFETY", "SUSTAINABLE_RESOURCES"]
GENERAL = {"question": "What actions can we take to avoid high-risk situations?", "why_subgoal": "SAFETY",
           "about": {"place": None, "actor": None, "period": None}, "kind": "EXPLAIN",
           "would_change": "I would act", "from_line": "none", "expects": "advice"}
SPECIFIC = {"question": "How many refugees returned to Syria in 2026?", "why_subgoal": "CIVILIZATIONAL_STABILITY",
            "about": {"place": "Syria", "actor": "UNHCR", "period": "2026"}, "kind": "FIND",
            "would_change": "I would lower the refugee threat", "from_line": "L1", "expects": "a UNHCR count"}


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


@pytest.fixture
def p(tmp_path, monkeypatch):
    from core import card_intake as ci
    from core import taxonomy as tx
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    monkeypatch.setattr(tx, "subgoal_names", lambda target_path=None: set(FIVE))
    (tmp_path / "grounded.json").write_text(json.dumps({"ranking": []}), encoding="utf-8")
    return {"needs": tmp_path / "needs.json", "refused": tmp_path / "refused.jsonl", "log": tmp_path / "log.jsonl",
            "ledger": tmp_path / "ledger.jsonl", "briefings": tmp_path / "briefings.jsonl",
            "shown": tmp_path / "shown_to_brain.jsonl",
            "grounded": tmp_path / "grounded.json", "forward_glob": str(tmp_path / "none" / "F-*.json"),
            "obs_log": tmp_path / "obs.jsonl", "atoms_root": tmp_path / "atoms"}


def ok(d):
    return {"data": d, "raw": json.dumps(d), "model": "stub", "sec": 0.1}


def model(needs=None, verdicts=None, calls=None):
    """needs: the reply to the needs QUESTION; verdicts: question -> TEXT C reply."""
    def think(prompt, evidence, schema):
        if calls is not None:
            calls.append({"prompt": prompt, "evidence": evidence, "schema": schema})
        if schema is bn.SCHEMA_NEEDS:
            return ok({"needs": needs or []})
        if schema is T.SCHEMA_C:
            for q, v in (verdicts or {}).items():
                if f"YOUR QUESTION: {q}\n" in prompt:
                    return v if ("data" in v or "unreadable" in v) else ok(v)
            return ok({"verdict": "STILL_OPEN", "narrower_question": None, "why": "nothing came back"})
        raise AssertionError("an unexpected schema was asked")
    return think


_AUTO = [0]


def fresh_linked(p):
    """One statement NEVER SHOWN BEFORE for each open brain need, as linked_statements() returns
    them. C-SHOWN-1 (Perplexity 82/82B): review() shows only what has not been shown for that
    need, so a turn with no new material asks the 3B nothing — these tests are about what the
    brain DOES with a verdict, so each run gives it something new. The empty case has its own
    tests in test/test_brain_needs_review.py."""
    _AUTO[0] += 1
    i = _AUTO[0]
    try:
        doc = json.loads(Path(p["needs"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {n["id"]: [{"type": "statement", "text": f"fetched for it {i}", "id": f"s-auto-{i}-{n['id']}",
                       "linked": True, "region": "main", "ingested_at": f"2026-10-09T0{i % 10}:00:00Z"}]
            for n in doc.get("needs", []) if n.get("origin") == "brain"}


def run(p, think, read=lambda q, k: [], linked=None):
    return bn.run(think=think, paths=p, busy=lambda: None, read=read, space_run=lambda: [],
                  linked=linked if linked is not None else fresh_linked(p))


def needs(p):
    return json.loads(p["needs"].read_text(encoding="utf-8"))["needs"]


def ledger(p):
    return [json.loads(l) for l in p["ledger"].read_text(encoding="utf-8").splitlines()] if p["ledger"].exists() else []


def by_q(p, q):
    return [n for n in needs(p) if n["question"] == q][0]


# ── the texts are the written ones ──────────────────────────────────────────
def test_text_c_formats_to_the_written_text_with_one_brace_each():
    s = T.TEXT_C.format(question="Q?", items='- "x"')
    assert '"narrower_question": null, "why": "it names the clashes, the date and the deaths"}' in s
    assert "{{" not in s and s.endswith("YOUR QUESTION: Q?\nWHAT CAME BACK:\n- \"x\"\nANSWER:\n")
    assert s.startswith("YOUR QUESTION and WHAT CAME BACK for it are below. Decide one of three:\n")


def test_text_b_formats_to_the_written_text():
    s = T.TEXT_B.format(heads="says, obs", sentence="A sentence.")
    assert 'ANSWER: {"head": "NONE", "args": []}' in s
    assert s.endswith("Suggested heads (you may use another): says, obs\nSENTENCE: A sentence.\nANSWER:\n")
    assert "Never use the whole sentence as an argument." in s


# ── 2a: think() passes the schema as format, at temperature 0 ───────────────
@pytest.fixture
def door(monkeypatch):
    from core import brain, llm_door
    sent = []

    class R:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": self.content}}
    reply = {"content": '{"verdict": "SATISFIED", "narrower_question": null, "why": "w"}'}

    def post(caller, backend, mdl, url, prompt_text=None, timeout=None, json=None, row_extra=None):
        sent.append({"model": mdl, "body": json, "timeout": timeout})
        return R(reply["content"])
    monkeypatch.setattr(llm_door, "post", post)
    monkeypatch.setattr(brain, "_pick_model", lambda: ("cortex-l1b-3b:latest", "http://ollama.invalid"))
    monkeypatch.setattr(brain, "models", lambda: ["cortex-l1b-3b:latest", "qwen2.5:3b"])
    monkeypatch.setattr(brain, "_guard_local", lambda m, why: m)
    return {"sent": sent, "reply": reply}


def test_think_sends_the_schema_as_format_at_temperature_zero_and_the_text_verbatim(door):
    from core import brain
    filled = T.TEXT_C.format(question="Q?", items="(nothing came back)")
    r = brain.think("did it answer", filled, json_schema=T.SCHEMA_C, exact=True,
                    model_override="cortex-l1b-3b:latest", remember_it=False, temperature=0.7)
    body = door["sent"][0]["body"]
    assert body["format"] == T.SCHEMA_C and body["options"]["temperature"] == 0
    assert body["messages"] == [{"role": "user", "content": filled}]
    assert r["data"]["verdict"] == "SATISFIED" and r["raw"].startswith('{"verdict"')


def test_a_schema_invalid_reply_is_unreadable_with_its_raw_text(door):
    from core import brain
    door["reply"]["content"] = '{"verdict": "PROBABLY", "narrower_question": null, "why": "w"}'
    r = brain.think("did it answer", "Q", json_schema=T.SCHEMA_C, exact=True,
                    model_override="cortex-l1b-3b:latest", remember_it=False)
    assert "data" not in r and r["unreadable"].startswith("schema-invalid") and "PROBABLY" in r["raw"]


def test_a_schema_bound_call_never_falls_back_to_another_model(door):
    from core import brain
    door["reply"]["content"] = ""
    r = brain.think("did it answer", "Q", json_schema=T.SCHEMA_C, exact=True,
                    model_override="cortex-l1b-3b:latest", remember_it=False)
    assert r is None and [s["model"] for s in door["sent"]] == ["cortex-l1b-3b:latest"]


def test_the_size_of_cortex_l1b_3b_is_3b_not_unknown():
    from core import brain
    import re
    ms = re.findall(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)b(?![a-z])", "cortex-l1b-3b:latest")
    assert ms == ["3"]
    src = Path(brain.__file__).read_text(encoding="utf-8")
    assert r'(?<![a-z0-9.])(\d+(?:\.\d+)?)b(?![a-z])' in src


def test_bound_rejects_data_that_does_not_fit_the_schema():
    d, raw, why = bn.bound({"data": {"verdict": "MAYBE"}, "raw": "x"}, T.SCHEMA_C)
    assert d is None and why.startswith("schema-invalid")
    d, raw, why = bn.bound(None, T.SCHEMA_C)
    assert d is None and why == "no reply"


def test_mutation_without_the_schema_net_bad_data_passes(monkeypatch):
    monkeypatch.setattr(bn, "_schema_problem", lambda d, schema: None)
    d, raw, why = bn.bound({"data": {"verdict": "MAYBE"}, "raw": "x"}, T.SCHEMA_C)
    assert d == {"verdict": "MAYBE"}


# ── 2a/2b: needs ────────────────────────────────────────────────────────────
def test_the_needs_question_is_schema_bound(p):
    calls = []
    run(p, model(needs=[SPECIFIC], calls=calls))
    assert [c["schema"] for c in calls] == [bn.SCHEMA_NEEDS]


def test_an_unreadable_needs_reply_is_recorded_unreadable_and_invents_nothing(p):
    run(p, lambda pr, ev, sc: {"unreadable": "schema-invalid: x", "raw": "I think we should", "sec": 1})
    assert not [n for n in needs(p) if n["origin"] == "brain"]
    row = [r for r in ledger(p) if r["event"] == "UNREADABLE"][0]
    assert row["what"] == "needs" and row["raw"] == "I think we should"


def test_a_general_need_becomes_a_parent_and_a_specific_one_does_not(p):
    run(p, model(needs=[GENERAL, SPECIFIC]))
    assert by_q(p, GENERAL["question"])["role"] == "parent"
    assert by_q(p, SPECIFIC["question"])["role"] == "direct"


def test_from_line_none_alone_makes_a_parent(p):
    run(p, model(needs=[{**SPECIFIC, "from_line": "none"}]))
    assert by_q(p, SPECIFIC["question"])["role"] == "parent"


def test_a_parent_is_never_re_emitted(p):
    run(p, model(needs=[GENERAL]))
    pid = by_q(p, GENERAL["question"])["id"]
    doc = json.loads(p["needs"].read_text(encoding="utf-8"))
    by_q_doc = [n for n in doc["needs"] if n["id"] == pid][0]
    by_q_doc["status"] = "WRONG_QUESTION"
    p["needs"].write_text(json.dumps(doc), encoding="utf-8")
    run(p, model(needs=[GENERAL]))
    assert by_q(p, GENERAL["question"])["status"] == "WRONG_QUESTION"
    assert [r["event"] for r in ledger(p) if r.get("need_id") == pid][-1] == "REPEAT"


def test_mutation_without_the_parent_guard_a_closed_parent_is_reopened(p, monkeypatch):
    monkeypatch.setattr(bn, "_is_parent", lambda n: False)
    run(p, model(needs=[GENERAL]))
    pid = by_q(p, GENERAL["question"])["id"]
    doc = json.loads(p["needs"].read_text(encoding="utf-8"))
    [n for n in doc["needs"] if n["id"] == pid][0]["status"] = "WRONG_QUESTION"
    p["needs"].write_text(json.dumps(doc), encoding="utf-8")
    run(p, model(needs=[GENERAL]))
    assert by_q(p, GENERAL["question"])["status"] == "OPEN"


def test_an_old_need_without_a_role_is_given_one(p):
    p["needs"].write_text(json.dumps({"needs": [{"id": "BN-old", "origin": "brain", "status": "OPEN",
                                                 "question": "What should we know?", "why_subgoal": "SAFETY",
                                                 "about": None, "from_line": "none"}]}), encoding="utf-8")
    run(p, model())
    assert by_q(p, "What should we know?")["role"] == "parent"
    assert any(r["event"] == "MADE_PARENT" and r["need_id"] == "BN-old" for r in ledger(p))


# ── 2d: the needs QUESTION only for a sub-goal with no open parent ──────────
def test_a_need_for_a_sub_goal_with_an_open_parent_is_refused(p):
    run(p, model(needs=[GENERAL]))
    other = {**SPECIFIC, "why_subgoal": "SAFETY", "question": "How many people died in floods in Kerala in 2025?"}
    r = run(p, model(needs=[other]))
    assert not [n for n in needs(p) if n["question"] == other["question"]]
    assert r["refused"][0]["reason"] == "sub-goal SAFETY already has an open parent"


def test_when_every_sub_goal_has_an_open_parent_the_question_is_not_asked(p):
    run(p, model(needs=[{**GENERAL, "why_subgoal": s, "question": f"What about {s}?"} for s in FIVE]))
    calls = []
    run(p, model(needs=[SPECIFIC], calls=calls))
    assert bn.SCHEMA_NEEDS not in [c["schema"] for c in calls]
    assert ledger(p)[-1]["event"] == "ASK_SKIPPED" or any(r["event"] == "ASK_SKIPPED" for r in ledger(p))


def test_the_brain_is_told_which_sub_goals_are_free(p):
    run(p, model(needs=[GENERAL]))
    calls = []
    run(p, model(calls=calls))
    ev = [c for c in calls if c["schema"] is bn.SCHEMA_NEEDS][0]["evidence"]
    assert "SUB-GOALS WITH NO OPEN PARENT: CIVILIZATIONAL_STABILITY, HEALTHY_ENVIRONMENTS" in ev
    assert "SAFETY" not in ev.split("SUB-GOALS WITH NO OPEN PARENT:")[1].splitlines()[0]


# ── 2c: review by TEXT C, one call per question ─────────────────────────────
def test_review_asks_text_c_once_per_question_verbatim(p):
    """C-SHOWN-1 (82B): each shown item now carries its source as a label — LINKED_STATEMENT for
    the need's own statements, CONTEXT_RETRIEVED for the store read a need with none of its own
    falls back to — so the 3B cannot read context as evidence for the need. TEXT C itself is
    unchanged and still asked once per question, verbatim."""
    run(p, model(needs=[GENERAL]))
    pid = by_q(p, GENERAL["question"])["id"]
    calls = []
    run(p, model(calls=calls), read=lambda q, k: [],
        linked={pid: [{"type": "statement", "text": "Wear a seatbelt.", "id": "s1", "linked": True,
                       "region": "main", "ingested_at": "2026-10-09T05:00:00Z"}]})
    cs = [c for c in calls if c["schema"] is T.SCHEMA_C]
    assert len(cs) == 1
    assert cs[0]["prompt"] == T.TEXT_C.format(question=GENERAL["question"],
                                              items='- [LINKED_STATEMENT] "Wear a seatbelt."')
    assert cs[0]["evidence"] == ""


def test_still_open_with_a_narrower_question_creates_a_child(p):
    run(p, model(needs=[GENERAL]))
    nq = "Which road crossings in Lagos had the most deaths in 2025?"
    run(p, model(verdicts={GENERAL["question"]: {"verdict": "STILL_OPEN", "narrower_question": nq, "why": "w"}}))
    par, ch = by_q(p, GENERAL["question"]), by_q(p, nq)
    assert ch["role"] == "child" and ch["parent"] == par["id"] and ch["status"] == "OPEN"
    assert ch["why_subgoal"] == "SAFETY" and par["status"] == "STILL_OPEN"
    assert any(r["event"] == "CHILD" and r["need_id"] == ch["id"] for r in ledger(p))


def test_a_child_that_repeats_is_recorded_repeat_and_not_added(p):
    run(p, model(needs=[GENERAL]))
    v = {GENERAL["question"]: {"verdict": "STILL_OPEN", "narrower_question": "  what ACTIONS can we take to avoid "
                                                                             "high-risk situations? ", "why": "w"}}
    run(p, model(verdicts=v))
    assert len([n for n in needs(p) if n["origin"] == "brain"]) == 1
    rep = [r for r in ledger(p) if r["event"] == "REPEAT"][0]
    assert rep["parent"] == by_q(p, GENERAL["question"])["id"]


def test_mutation_without_the_repeat_guard_the_repeat_is_added(p, monkeypatch):
    monkeypatch.setattr(bn, "_held_questions", lambda doc: set())
    run(p, model(needs=[GENERAL]))
    v = {GENERAL["question"]: {"verdict": "STILL_OPEN", "narrower_question": "what ACTIONS can we take to avoid "
                                                                             "high-risk situations?", "why": "w"}}
    run(p, model(verdicts=v))
    assert any(r["event"] == "CHILD" for r in ledger(p)) and not any(r["event"] == "REPEAT" for r in ledger(p))


def test_a_direct_need_that_is_narrowed_becomes_a_parent(p):
    run(p, model(needs=[SPECIFIC]))
    bn.mark_served(by_q(p, SPECIFIC["question"])["id"], "q", 1, 1, 1, p)
    nq = "How many refugees returned to Syria from Turkey in 2026?"
    run(p, model(verdicts={SPECIFIC["question"]: {"verdict": "STILL_OPEN", "narrower_question": nq, "why": "w"}}))
    assert by_q(p, SPECIFIC["question"])["role"] == "parent" and by_q(p, nq)["role"] == "child"


def test_satisfied_closes_a_parent_and_records_why(p):
    run(p, model(needs=[GENERAL]))
    run(p, model(verdicts={GENERAL["question"]: {"verdict": "SATISFIED", "narrower_question": None,
                                                 "why": "it lists them"}}))
    n = by_q(p, GENERAL["question"])
    assert n["status"] == "SATISFIED" and n["verdicts"][-1]["why"] == "it lists them"


def test_an_unreadable_review_leaves_the_need_and_is_counted(p):
    run(p, model(needs=[GENERAL]))
    bad = {"unreadable": "not JSON", "raw": "SATISFIED I guess"}
    run(p, model(verdicts={GENERAL["question"]: bad}))
    assert by_q(p, GENERAL["question"])["status"] == "OPEN"
    row = [r for r in ledger(p) if r["event"] == "UNREADABLE"][0]
    assert row["what"] == "review" and row["raw"] == "SATISFIED I guess"


def test_an_unsearched_direct_need_is_not_reviewed(p):
    run(p, model(needs=[SPECIFIC]))
    calls = []
    run(p, model(calls=calls))
    assert not [c for c in calls if c["schema"] is T.SCHEMA_C]


def test_only_the_needs_own_statements_are_shown_when_it_has_any(p):
    """C-SHOWN-1 (82B В2): the store read is the fallback for a need with NO linked statements;
    it no longer fills the free slots beside them. Before 9 Oct it did, and the same five
    items were shown every turn."""
    run(p, model(needs=[GENERAL]))
    pid = by_q(p, GENERAL["question"])["id"]
    rv = bn.review(model(), p, read=lambda q, k: [{"type": "statement", "text": "store item", "id": "s9"}],
                   linked={pid: [{"type": "statement", "text": "fetched for it", "id": "s1", "linked": True,
                                  "region": "main", "ingested_at": "2026-10-09T05:00:00Z"}]})
    assert [i["text"] for i in rv["items"][pid]] == ["fetched for it"]
    assert rv["per_need"][pid]["context_count"] == 0


# ── the agents never search a parent ───────────────────────────────────────
def test_searchable_excludes_parents():
    ns = [{"id": "a", "origin": "brain", "role": "parent", "status": "OPEN", "question": "q"},
          {"id": "b", "origin": "brain", "role": "child", "status": "OPEN", "question": "q"},
          {"id": "c", "origin": "engine", "status": "OPEN", "question": "q"}]
    assert [n["id"] for n in bn.searchable(ns)] == ["b", "c"]


def test_mutation_without_the_parent_filter_a_parent_is_searched(monkeypatch):
    monkeypatch.setattr(bn, "_is_parent", lambda n: False)
    ns = [{"id": "a", "origin": "brain", "role": "parent", "status": "OPEN", "question": "q"}]
    assert [n["id"] for n in bn.searchable(ns)] == ["a"]


def test_the_agents_turn_takes_its_needs_from_searchable():
    import ast
    src = (REPO / "scripts" / "turn_agents.py").read_text(encoding="utf-8")
    calls = {n.func.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)}
    assert "searchable" in calls


def test_a_general_brain_need_without_a_role_is_not_searchable():
    # 2 Oct 2026: roles were given only in the brain's turn, so the agents' turn that ran
    # first took the five old general needs as searchable and queried them verbatim
    old = {"id": "BN-old", "origin": "brain", "status": "OPEN", "question": "What should we know?",
           "about": None, "from_line": "none"}
    specific = {**old, "id": "BN-s", "about": {"place": "Syria", "actor": None, "period": "2026"}, "from_line": "L1"}
    assert [n["id"] for n in bn.searchable([old, specific])] == ["BN-s"]
