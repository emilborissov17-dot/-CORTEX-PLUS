# -*- coding: utf-8 -*-
"""test/test_brain_needs_review.py — the brain is told what came back for its
needs and judges them (C-NEED-1 Part 3c, kept when the Python finder was deleted
on Emil's R34). A need is marked served with core.brain_needs.mark_served — the
call any searcher makes; there is no searcher in these tests.
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

FIVE = ["CIVILIZATIONAL_STABILITY", "HEALTHY_ENVIRONMENTS", "KNOWLEDGE_UNDERSTANDING", "SAFETY", "SUSTAINABLE_RESOURCES"]
NEED = {"question": "How many refugees returned to Syria in 2026?", "why_subgoal": "SAFETY",
        "about": {"place": "Syria", "actor": "UNHCR", "period": "2026"}, "kind": "FIND",
        "would_change": "I would lower the refugee threat"}


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


def _ok(d):
    return {"data": d, "raw": json.dumps(d), "model": "stub", "sec": 0.1}


def _verdict(verdict, why="w", nq=None):
    """think(prompt, evidence, schema) answering TEXT C with one verdict."""
    return lambda pr, ev, sc: _ok({"verdict": verdict, "narrower_question": nq, "why": why})


def _emit(p, needs):
    full = [{"from_line": "L1", "expects": "e", **n} for n in needs]
    return bn.run(think=lambda q, ev, sc: _ok({"needs": full}), paths=p,
                  busy=lambda: None, read=lambda q, k: [], space_run=lambda: [], linked={})


def _needs(p):
    return json.loads(p["needs"].read_text(encoding="utf-8"))["needs"]


def _ledger(p):
    return [json.loads(l) for l in p["ledger"].read_text(encoding="utf-8").splitlines()]


def _served(p):
    _emit(p, [NEED])
    nid = _needs(p)[0]["id"]
    bn.mark_served(nid, NEED["question"], 1, 1, 2, p)
    return nid


def _own(nid, n=1, first="2026-10-09T05:00:00Z"):
    """Linked statements for the need, as linked_statements() returns them (C-SHOWN-1: with
    their ingestion time, unsorted). Without any, review() has nothing new to show and asks
    the 3B nothing — that is the rule, tested on its own below."""
    return {nid: [{"type": "statement", "text": f"fetched for this need {i}", "id": f"s-own-{i}",
                   "linked": True, "region": "main", "ingested_at": first} for i in range(n)]}


def test_a_new_need_is_emitted_open_and_no_longer_says_there_is_no_searcher(p):
    # C-GW-1 step 3: the NO_SEARCHER row ("OpenClaw search not built yet") was false since C-TURN-1
    _emit(p, [NEED])
    nid = _needs(p)[0]["id"]
    rows = [r for r in _ledger(p) if r.get("need_id") == nid]
    assert [r["event"] for r in rows] == ["EMITTED"] and _needs(p)[0]["status"] == "OPEN"


def test_mark_served_counts_and_never_changes_the_status(p):
    nid = _served(p)
    n = _needs(p)[0]
    assert (n["searched"], n["gained_statements"], n["status"]) == (1, 2, "OPEN")


def test_satisfied_is_recorded_with_the_items_shown(p):
    nid = _served(p)
    rv = bn.review(think=_verdict("SATISFIED", "it answers it"), paths=p, linked={},
                   read=lambda q, k: [{"type": "statement", "text": "UNHCR: 1.2 million returned in 2026."}])
    assert rv["verdicts"] == [{"id": nid, "verdict": "SATISFIED", "recorded": True}]
    assert "1.2 million" in rv["calls"][0]["shown"] and _needs(p)[0]["status"] == "SATISFIED"
    assert [r["event"] for r in _ledger(p) if r.get("need_id") == nid][-2:] == ["SHOWN", "SATISFIED"]


def test_still_open_with_a_narrower_question_keeps_the_need_and_adds_a_child(p):
    nid = _served(p)
    bn.review(think=_verdict("STILL_OPEN", "nothing came back", "Returns to Syria from Turkey, 2026?"), paths=p,
              read=lambda q, k: [], linked=_own(nid))
    n = [x for x in _needs(p) if x["id"] == nid][0]
    assert n["status"] == "STILL_OPEN" and n["question"] == NEED["question"]
    assert [x["question"] for x in _needs(p) if x.get("parent") == nid] == ["Returns to Syria from Turkey, 2026?"]


def test_wrong_question_closes_it(p):
    nid = _served(p)
    bn.review(think=_verdict("WRONG_QUESTION", "the axis counts stock"), paths=p, read=lambda q, k: [], linked=_own(nid))
    assert _needs(p)[0]["status"] == "WRONG_QUESTION"


def test_a_garbled_review_changes_nothing_and_is_recorded(p):
    nid = _served(p)
    rv = bn.review(think=lambda pr, ev, sc: {"unreadable": "not JSON", "raw": "looks fine to me"}, paths=p,
                   read=lambda q, k: [], linked=_own(nid))
    assert rv["calls"][0]["raw"] == "looks fine to me" and _needs(p)[0]["status"] == "OPEN"


def test_a_verdict_outside_the_three_is_not_recorded(p):
    nid = _served(p)
    rv = bn.review(think=_verdict("PROBABLY", "?"), paths=p, read=lambda q, k: [], linked=_own(nid))
    assert rv["verdicts"][0]["recorded"] is False and _needs(p)[0]["status"] == "OPEN"
    assert rv["verdicts"][0]["why_not"].startswith("schema-invalid")


def test_an_unserved_need_is_not_shown_for_review(p):
    _emit(p, [NEED])
    nid = _needs(p)[0]["id"]
    rv = bn.review(think=_verdict("SATISFIED"), paths=p, read=lambda q, k: [], linked=_own(nid))
    assert rv["shown"] == 0


def test_re_asking_a_wrong_question_reopens_it_and_keeps_its_history(p):
    nid = _served(p)
    bn.review(think=_verdict("WRONG_QUESTION", "too general"), paths=p, read=lambda q, k: [], linked=_own(nid))
    _emit(p, [NEED])
    n = [x for x in _needs(p) if x["id"] == nid][0]
    assert n["status"] == "OPEN" and [v["verdict"] for v in n["verdicts"]] == ["WRONG_QUESTION"]
    assert len(n["reopened"]) == 1 and n["searched"] == 1
    assert [r["event"] for r in _ledger(p) if r.get("need_id") == nid][-1] == "REOPENED"


def test_no_finder_module_exists_and_nothing_imports_one():
    import ast
    gone = "openclaw" + "_finder"                      # the deleted module's name, assembled
    assert not (REPO / "scripts" / f"{gone}.py").exists()
    for f in list((REPO / "core").glob("*.py")) + list((REPO / "scripts").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        assert gone not in names and not any(gone in m for m in mods), f.name


def test_a_need_with_its_own_statements_is_never_shown_the_store_read(p):
    """C-SHOWN-1 (Perplexity 82B В2): the store-wide read is a fallback for a need with NO
    linked statements, not a filler beside them. Before 9 Oct it filled the free slots."""
    nid = _served(p)
    rv = bn.review(think=_verdict("STILL_OPEN"), paths=p, linked=_own(nid, 2),
                   read=lambda q, k: [{"type": "statement", "text": "an unrelated transcript fragment", "id": "s-x"}])
    shown = rv["items"][nid]
    assert [i["id"] for i in shown] == ["s-own-0", "s-own-1"] and all(i["shown_as"] == "LINKED" for i in shown)
    assert rv["per_need"][nid]["context_count"] == 0


def test_the_newest_unseen_statements_are_shown_and_the_same_ones_never_twice(p):
    """82 В2.1 and В2.2: unseen only, newest by ingestion time first. The defect this replaces
    showed the FIRST five ever ingested, every turn, for a week."""
    nid = _served(p)
    linked = {nid: [{"type": "statement", "text": "old", "id": "s-old", "linked": True, "region": "main",
                     "ingested_at": "2026-10-01T15:22:23Z"},
                    {"type": "statement", "text": "new", "id": "s-new", "linked": True, "region": "main",
                     "ingested_at": "2026-10-09T05:00:00Z"}]}
    rv = bn.review(think=_verdict("STILL_OPEN"), paths=p, linked=linked, read=lambda q, k: [], k=1)
    assert [i["id"] for i in rv["items"][nid]] == ["s-new"]
    rv = bn.review(think=_verdict("STILL_OPEN"), paths=p, linked=linked, read=lambda q, k: [], k=1)
    assert [i["id"] for i in rv["items"][nid]] == ["s-old"]           # the record of what was shown holds
    rv = bn.review(think=_verdict("STILL_OPEN"), paths=p, linked=linked, read=lambda q, k: [], k=1)
    assert rv["items"][nid] == [] and rv["per_need"][nid]["reviewed_no_new_context"] is True


def test_a_need_with_no_linked_statements_gets_the_store_read_labelled_as_context(p):
    nid = _served(p)
    calls = []
    rv = bn.review(think=lambda pr, ev, sc: calls.append(pr) or _ok({"verdict": "STILL_OPEN", "why": "w",
                                                                     "narrower_question": None}),
                   paths=p, linked={},
                   read=lambda q, k: [{"type": "statement", "text": "a fragment from the store", "id": "s-x"}])
    assert [i["id"] for i in rv["items"][nid]] == ["s-x"]
    assert rv["items"][nid][0]["shown_as"] == "CONTEXT" and rv["per_need"][nid]["context_count"] == 1
    assert "[CONTEXT_RETRIEVED]" in calls[0] and "[LINKED_STATEMENT]" not in calls[0]


def test_nothing_new_means_the_model_is_not_asked_at_all(p):
    """82B: 'няма нови данни' is not a verdict and not a closure; it is no input to review, so
    the 3B is not called and the need is left exactly as it was."""
    nid = _served(p)
    calls = []
    rv = bn.review(think=lambda pr, ev, sc: calls.append(pr) or _ok({"verdict": "SATISFIED", "why": "w",
                                                                     "narrower_question": None}),
                   paths=p, linked={}, read=lambda q, k: [])
    assert calls == [] and rv["items"][nid] == [] and rv["shown"] == 0 and rv["no_new"] == 1
    assert _needs(p)[0]["status"] == "OPEN" and not _needs(p)[0].get("verdicts")
    assert [r["event"] for r in _ledger(p) if r.get("event") == "NO_NEW_FOR_NEED"] == ["NO_NEW_FOR_NEED"]
    assert rv["per_need"][nid] == {"linked_count": 0, "context_count": 0, "already_shown": 0, "shown_ids": [],
                                   "furniture_dropped": 0, "context_pool": 0,
                                   "search_attempts": 1, "reviewed_no_new_context": True}


def test_linked_statements_indexes_records_by_need_id(monkeypatch):
    from core import knowledge as kn
    monkeypatch.setattr(kn, "region_index", lambda path=None: {})
    monkeypatch.setattr(kn, "statements", lambda store=None: [
        {"id": "s1", "sentence": "for the need", "need_id": "BN-1"},
        {"id": "s2", "sentence": "for nothing"}])
    assert bn.linked_statements() == {"BN-1": [{"type": "statement", "text": "for the need", "id": "s1", "linked": True,
                                                "region": "unknown", "ingested_at": None}]}


def test_a_linked_statement_carries_the_ingestion_time_of_its_record(monkeypatch):
    """The selection is BY ingestion time (82 В2.2), so the time has to travel with the item.
    Without this the newest-first order silently becomes store order again, which is the defect
    C-SHOWN-1 exists to remove: an item with no ingested_at sorts LAST among the unseen."""
    from core import knowledge as kn
    monkeypatch.setattr(kn, "region_index", lambda path=None: {})
    monkeypatch.setattr(kn, "statements", lambda store=None: [
        {"id": "s1", "sentence": "older", "need_id": "BN-1", "ingested_at": "2026-10-01T15:22:23Z"},
        {"id": "s2", "sentence": "newer", "need_id": "BN-1", "ingested_at": "2026-10-09T09:57:46Z"}])
    got = bn.linked_statements()["BN-1"]
    assert [it["ingested_at"] for it in got] == ["2026-10-01T15:22:23Z", "2026-10-09T09:57:46Z"]
    from core import shown as sh
    assert [it["id"] for it in sh.unseen(got, set(), 2)] == ["s2", "s1"]


# ── the failure paths of the record itself (R65 verifier, 9 Oct) ────────────

def test_a_record_that_exists_and_cannot_be_read_is_loud_not_an_empty_record(tmp_path):
    """A MISSING record means nothing has been shown; an UNREADABLE one means we no longer know.
    Read as the first, the second makes every need be shown everything it has already seen and
    re-recorded - the defect C-SHOWN-1 removes, wearing a plausible record as a disguise."""
    from core import shown as sh
    assert sh.shown_ids(tmp_path / "not-there.jsonl") == {}
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b'{"need_id": "BN-1", "statement_id": "s1", "kind": "LINKED"}\n\xff\xfe not utf-8\n')
    with pytest.raises(sh.ShownUnreadable):
        sh.shown_ids(bad)
    with pytest.raises(sh.ShownUnreadable):
        sh.shown_ids(tmp_path)                      # a directory is not an empty record either


def test_a_row_that_is_not_an_object_is_skipped_and_does_not_kill_the_turn(tmp_path):
    f = tmp_path / "shown.jsonl"
    f.write_text('[1, 2, 3]\n7\n"text"\n{"need_id": "BN-1", "statement_id": "s1"}\n{"bad": 1}\n{\n',
                 encoding="utf-8")
    from core import shown as sh
    assert sh.shown_ids(f) == {"BN-1": {"s1"}}


def test_an_item_with_no_label_is_refused_never_written_as_the_needs_own(tmp_path):
    """LINKED means "the need's own evidence". A missing or unknown label must not fall back to
    it: that is the very relabelling the M5 mutation exists to catch, done by default."""
    from core import shown as sh
    f = tmp_path / "shown.jsonl"
    with pytest.raises(ValueError, match="never assumed"):
        sh.record("BN-1", [{"id": "s1"}], path=f)
    with pytest.raises(ValueError):
        sh.record("BN-1", [{"id": "s1", "shown_as": "BANANA"}], path=f)
    assert sh.record("BN-1", [{"id": "s1", "shown_as": sh.CONTEXT}], path=f) == 1
    assert json.loads(f.read_text(encoding="utf-8").splitlines()[0])["kind"] == "CONTEXT"


def test_a_non_string_ingestion_time_sorts_last_like_a_missing_one(tmp_path):
    from core import shown as sh
    items = [{"id": "dated-old", "ingested_at": "2026-10-01T00:00:00Z"},
             {"id": "none", "ingested_at": None},
             {"id": "epoch", "ingested_at": 1760000000},
             {"id": "dated-new", "ingested_at": "2026-10-09T00:00:00Z"}]
    # the two dated ones first, newest first; then the two undated IN INPUT ORDER - an epoch
    # number is in the same bucket as a missing time, not between the dates and the missing one
    assert [it["id"] for it in sh.unseen(items, set(), None)] == ["dated-new", "dated-old", "none", "epoch"]
    assert [it["id"] for it in sh.unseen(items, set(), 3)] == ["dated-new", "dated-old", "none"]


def test_the_two_furniture_lists_are_the_same_list(tmp_path):
    """Two gates drop page furniture - the selection and the symbol step - and a region added to
    one and not the other would let furniture back in through the half that was forgotten."""
    from core import shown as sh
    from core import symbols as sym
    assert tuple(sh.DROP_REGIONS) == tuple(sym.FURNITURE_REGIONS) == ("furniture",)


# ── the two dead ends the verifier found in review() ────────────────────────

def test_a_need_served_only_page_furniture_gets_the_context_read_not_silence(p):
    """It HAS linked statements and none of them may be shown. Branching on what was fetched
    rather than on what is showable left it with neither its own items nor the fallback, and
    under the no-new rule it was then never reviewed again."""
    nid = _served(p)
    junk = {nid: [{"type": "statement", "text": t, "id": f"f-{i}", "linked": True,
                   "region": "furniture", "ingested_at": "2026-10-09T05:00:00Z"}
                  for i, t in enumerate(("Skip to content", "toggle navigation", "Home"))]}
    rv = bn.review(think=_verdict("STILL_OPEN"), paths=p, linked=junk,
                   read=lambda q, k: [{"type": "statement", "text": "a real sentence", "id": "c-1",
                                       "ingested_at": "2026-10-09T06:00:00Z"}])
    assert len(rv["calls"]) == 1 and "CONTEXT_RETRIEVED" in rv["calls"][0]["shown"]
    assert "Skip to content" not in rv["calls"][0]["shown"]
    pn = rv["per_need"][nid]
    assert (pn["furniture_dropped"], pn["context_count"], pn["reviewed_no_new_context"]) == (3, 1, False)


def test_an_unreadable_reply_leaves_the_items_unshown_so_they_come_back_next_turn(p):
    """Recorded BEFORE the call, an item the brain never read counted as shown; with nothing new
    left the need was then never reviewed again. The record says what was READ, not what was sent."""
    nid = _served(p)
    own = _own(nid)

    def raises(pr, ev, sc):
        raise RuntimeError("ollama is not answering")

    rv = bn.review(think=raises, paths=p, linked=own, read=lambda q, k: [])
    assert rv["verdicts"] == [{"id": nid, "verdict": None, "recorded": False,
                               "why_not": rv["verdicts"][0]["why_not"]}]
    assert not p["shown"].exists() or p["shown"].read_text(encoding="utf-8").strip() == ""
    rv2 = bn.review(think=_verdict("STILL_OPEN"), paths=p, linked=own, read=lambda q, k: [])
    assert [it["id"] for it in rv2["items"][nid]] == ["s-own-0"]
    assert rv2["per_need"][nid]["reviewed_no_new_context"] is False


def test_the_context_read_widens_with_what_was_already_shown(p):
    """The relevance read returns the TOP k matches, so a fixed pool of k * CONTEXT_CANDIDATES is
    used up after four turns and every later turn finds nothing new - with 679 438 statements in
    the store and none of them ever offered."""
    nid = _served(p)
    asked = []

    def read(q, k):
        asked.append(k)
        return [{"type": "statement", "text": f"c{i}", "id": f"c-{i}",
                 "ingested_at": "2026-10-0%dT00:00:00Z" % (1 + i % 9)} for i in range(k)]

    bn.review(think=_verdict("STILL_OPEN"), paths=p, linked={}, read=read)
    first = asked[-1]
    bn.review(think=_verdict("STILL_OPEN"), paths=p, linked={}, read=read)
    assert first == 5 * bn.CONTEXT_CANDIDATES and asked[-1] == first + 5


def test_only_statements_come_back_from_the_context_read(p):
    """core.knowledge.read also returns measurement atoms, whose id is a card key. Written into a
    field called statement_id, that is a name asserting something the code never checked."""
    nid = _served(p)
    rv = bn.review(think=_verdict("STILL_OPEN"), paths=p, linked={},
                   read=lambda q, k: [{"type": "measurement", "text": "a card", "id": "CARD-1"},
                                      {"type": "statement", "text": "a sentence", "id": "c-1",
                                       "ingested_at": "2026-10-09T00:00:00Z"}])
    assert [it["id"] for it in rv["items"][nid]] == ["c-1"]
    kinds = [json.loads(l) for l in p["shown"].read_text(encoding="utf-8").splitlines()]
    assert [(r["statement_id"], r["kind"]) for r in kinds] == [("c-1", "CONTEXT")]


def test_an_item_without_a_string_id_is_not_recorded_and_no_id_is_invented(tmp_path):
    from core import shown as sh
    f = tmp_path / "shown.jsonl"
    assert sh.record("BN-1", [{"shown_as": sh.LINKED}, {"id": 7, "shown_as": sh.LINKED},
                              {"id": None, "shown_as": sh.CONTEXT}], path=f) == 0
    assert not f.exists()
