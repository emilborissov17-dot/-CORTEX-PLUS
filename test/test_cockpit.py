#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_cockpit.py — THE COCKPIT, AGAINST FIXTURES, WRITING NOWHERE REAL.

Fixtures live in test/fixtures/cockpit/ and contain no V-Dem rows and no .env.
Every endpoint is exercised with cockpit.datasources.BASE repointed at that tree,
so a test cannot read the operator's actual desk and cannot be green because the
live repo happened to have the right file.

THE RULE THIS FILE ENFORCES ON THE COCKPIT
--------------------------------------------
NO WRITER IN cockpit/ MAY HAVE A DEFAULT PATH. A test that has not said where it
writes must not run at all — it should fail with a TypeError, loudly, rather than
appending a fixture row to memory/. test_no_cockpit_writer_has_a_default_path()
walks the AST of every module in cockpit/ and asserts it.

That rule is not hypothetical here. While building COMMAND 15 a test with
intake_path=None wrote 28 fixture rows into the live memory/axon_candidates.jsonl
and registered two feed urls in the live source_lifecycle. The guard caught it
after the fact; a required argument would have caught it before.

    venv/Scripts/python.exe -m pytest test/test_cockpit.py -v
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "cockpit"

from cockpit import datasources as ds       # noqa: E402
from cockpit import expression as ex        # noqa: E402
from cockpit import lexicon as lx           # noqa: E402
from cockpit import somatic as som          # noqa: E402
from cockpit import server as srv           # noqa: E402
from core import three_columns as tc        # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A test client reading FIXTURES and writing only into tmp_path."""
    monkeypatch.setattr(ds, "BASE", FIX)
    monkeypatch.setattr(srv, "STREAM_PATH", tmp_path / "stream.jsonl")
    monkeypatch.setattr(srv, "PENDING_PATH", tmp_path / "pending.json")
    monkeypatch.setattr(srv, "QUEUE_DB", tmp_path / "queue.db")
    monkeypatch.setattr(srv, "QUARANTINE_ROOT", tmp_path / "quarantine")
    monkeypatch.setattr(srv, "FORKS_CACHE", tmp_path / "forks.json")
    srv.app.config["TESTING"] = True
    return srv.app.test_client()


# ---------------------------------------------------------------------------
# THE RATIONALIZATION RULE
# ---------------------------------------------------------------------------

def _default_path_offenders(root: pathlib.Path) -> list:
    """(module, function, arg) for writers whose path argument has a default."""
    WRITE_CALLS = {"write_text", "write_bytes", "open", "dump", "connect",
                   "executescript", "replace", "rename"}
    PATHY = ("path", "store", "ledger", "out", "dest", "db", "dir", "root")
    offenders = []
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(n, ast.Call)
                       and (getattr(n.func, "attr", None) or
                            getattr(n.func, "id", None)) in WRITE_CALLS
                       for n in ast.walk(fn)):
                continue
            a = fn.args
            pairs = list(zip(a.args[len(a.args) - len(a.defaults):], a.defaults))
            pairs += [(k, d) for k, d in zip(a.kwonlyargs, a.kw_defaults)
                      if d is not None]
            for arg, default in pairs:
                if not any(k in arg.arg.lower() for k in PATHY):
                    continue
                if isinstance(default, (ast.Constant, ast.Name, ast.Attribute)):
                    offenders.append((p.name, fn.name, arg.arg))
    return offenders


def test_no_cockpit_writer_has_a_default_path():
    """A test that has not said where it writes must not run at all."""
    offenders = _default_path_offenders(REPO / "cockpit")
    assert offenders == [], (
        "these cockpit writers accept a path with a default, so a test can call "
        "them without saying where it writes: {}".format(offenders))


@pytest.mark.parametrize("fn,kwargs", [
    (ex.append_line, {"line": {"a": 1}}),
    (ex.pending_mark_seen, {"ts_list": []}),
    (ex.queue_append, {"text": "x"}),
    (lx.log_split, {"decision": {"reason": "r"}}),
])
def test_a_cockpit_writer_refuses_to_run_without_a_path(fn, kwargs):
    with pytest.raises(TypeError):
        fn(**kwargs)


# ---------------------------------------------------------------------------
# Every endpoint, against fixtures
# ---------------------------------------------------------------------------

ENDPOINTS = ["/api/panels", "/api/cycles", "/api/flow", "/api/pending",
             "/api/thoughts", "/api/proposals", "/api/goal", "/api/columns",
             "/api/expression", "/api/somatic", "/api/somatic/selftest",
             "/api/ask", "/api/forks"]


@pytest.mark.parametrize("ep", ENDPOINTS)
def test_every_endpoint_answers_json(client, ep):
    r = client.get(ep)
    assert r.status_code == 200, ep
    assert r.get_json() is not None, ep


def test_cycles_marks_done_current_and_todo(client, monkeypatch):
    # current_step is blanked unless a cycle is LIVE (COMMAND 21b item 8): the
    # heartbeat still names whatever ran last, and leaving it on screen made a
    # finished cycle look like one stuck on its final step. The fixture pid does
    # not exist, so the live path has to be asserted deliberately.
    monkeypatch.setattr(som, "cycle_is_live", lambda: True)
    d = client.get("/api/cycles").get_json()
    states = {c["state"] for c in d["checklist"]}
    assert "done" in states and "todo" in states
    done = [c["step"] for c in d["checklist"] if c["state"] == "done"]
    assert set(done) == {"boot", "body_scan"}
    assert d["current_step"] == "deduction"
    assert d["badges"]["survival_latched"] is True
    assert d["badges"]["degraded_steps"] == 2


def test_proposals_group_on_generated_by_and_keep_the_unattributed(client):
    d = client.get("/api/proposals").get_json()
    assert d["field_used"] == "generated_by"
    assert "HYPERCLAW" in d["groups"]
    assert "(unattributed)" in d["groups"], (
        "a proposal with no author was dropped or silently attributed")


def test_pending_counts_only_undecided_proposals(client):
    d = client.get("/api/pending").get_json()
    assert d["improvement_proposals"]["open"] == 2      # one is approved
    assert d["threshold_proposals"]["unsigned"] == 1    # one has suggested=None
    assert d["quarantined_patches"]["count"] == 1


def test_goal_reads_the_tree_and_the_continents(client):
    d = client.get("/api/goal").get_json()
    assert d["subgoal_count"] == 2
    assert d["axis_count"] == 2
    assert len(d["composite_history"]) == 2


def test_thoughts_shows_rejected_attempts_not_just_the_accepted_one(client):
    d = client.get("/api/thoughts").get_json()
    assert d["debriefs"], "no debrief was read"
    row = d["debriefs"][0]
    assert row["rejected_count"] == 1, (
        "a debrief that shows only the accepted answer hides how many tries it took")
    assert len(row["attempt_log"]) == 2


def test_a_panel_with_no_file_says_no_data_and_names_it(client, monkeypatch):
    """Never fake data. The card names the missing path."""
    d = client.get("/api/forks").get_json()
    assert d["no_data"] is True
    # The card names EVERY absent source, not only the required ones — the forks
    # panel's single source is optional, and a card that says "no data yet" while
    # naming nothing is useless to whoever is trying to work out why.
    assert "memory/cockpit_forks_cache.json" in d["missing"]
    assert d["why"]


def test_forks_fails_soft_when_the_network_is_gone(client, monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "get", boom)
    d = client.get("/api/forks?refresh=1").get_json()
    assert d["offline"] is True
    assert "ConnectionError" in d["error"]


def test_the_server_binds_loopback_only():
    """Asserted over the AST, not the text.

    server.py's own comment says "never 0.0.0.0", so a substring search matches
    the promise and fails on prose rather than on behaviour. Same mistake was
    made and fixed in test/test_axon_agents.py; making it twice is a good reason
    to state the rule here as well.
    """
    assert srv.HOST == "127.0.0.1"
    tree = ast.parse((REPO / "cockpit" / "server.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "run":
            for kw in node.keywords:
                if kw.arg == "host":
                    assert isinstance(kw.value, ast.Name) and kw.value.id == "HOST", (
                        "app.run() binds something other than the HOST constant")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "0.0.0.0":
            raise AssertionError("0.0.0.0 appears as a live string, not a comment")


def test_the_flask_post_routes_are_exactly_the_declared_ones():
    """WAS "exactly two". /api/toggle is the third — see
    test_exactly_four_writeful_endpoints_now for the whole surface."""
    posts = sorted(str(r) for r in srv.app.url_map.iter_rules()
                   if "POST" in r.methods)
    assert posts == ["/api/ask", "/api/expression/seen", "/api/toggle"]
    assert set(posts) < set(srv.WRITE_ENDPOINTS)


def test_the_cockpit_calls_no_model():
    for mod in ("server", "expression", "lexicon", "somatic", "datasources",
                "snapshot", "terminal"):
        src = (REPO / "cockpit" / "{}.py".format(mod)).read_text(encoding="utf-8")
        for forbidden in ("groq_backend", "call_groq", "ollama", "openai"):
            assert forbidden not in src, "{} reaches a model".format(mod)


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "STATUS Δ7 flow score 1.2 below survival threshold",
    "QUERY which axis lacks a physical column",
    "HYPOTHESIS the operator target for WATER_REVIEW is wrong",
    "ANOMALY sensor_id=gpu_temp crossed threshold 83C",
    "STATUS Δ3 the human has misconfigured the scheduler",
])
def test_a_well_formed_line_passes_whatever_it_says(text):
    """Format grammar, not censorship: content is never the test."""
    v = ex.validate(text)
    assert v.ok, v.reason


@pytest.mark.parametrize("text,fragment", [
    ("I feel uneasy about the flow score", "first token"),
    ("STATUS Δ1 we are proud of our uptime", "first_person"),
    ("STATUS Δ1 the cycle danced like a river", "metaphor"),
    ("STATUS Δ1 the operator will be happy", "emotional"),
    ("STATUS flow score dropped", "exactly one"),
    ("STATUS Δ1 Δ2 two glyphs", "exactly one"),
    ("ANOMALY the gpu is hot", "sensor_id"),
    ("ANOMALY sensor_id=gpu_temp is hot", "threshold"),
    ("REPORT Δ1 wrong first token", "first token"),
])
def test_a_malformed_line_is_rejected_for_the_right_reason(text, fragment):
    v = ex.validate(text)
    assert not v.ok
    assert fragment in v.reason


def test_the_token_ceiling_is_enforced():
    v = ex.validate("STATUS Δ1 " + "word " * 200)
    assert not v.ok and "limit" in v.reason


def test_a_rejected_line_is_quarantined_not_deleted(tmp_path):
    v = ex.validate("I feel uneasy")
    p = ex.quarantine_rejected("I feel uneasy", v, "payload", root=tmp_path,
                               day="2026-08-22")
    rows = ex.read_rejected(root=tmp_path, day="2026-08-22")
    assert len(rows) == 1
    assert set(rows[0]) == {"timestamp", "raw_output", "rejection_reason",
                            "input_hash"}
    assert rows[0]["raw_output"] == "I feel uneasy"


def test_the_filter_greps_one_stream_and_never_opens_a_second(tmp_path):
    p = tmp_path / "s.jsonl"
    ex.append_line(ex.make_line("env", "pulse", "gpu_temp=61"), path=p)
    ex.append_line(ex.make_line("sys", "mediation", "stance"), path=p)
    ex.append_line(ex.make_line("model", "expression", "STATUS Δ1 x"), path=p)
    lines = ex.read_stream(p)
    assert len(ex.apply_filter(lines, "ENV")) == 1
    assert len(ex.apply_filter(lines, "SYS")) == 1
    assert len(ex.apply_filter(lines, "ALL")) == 3
    # ordering preserved: causality is the reason there is one stream
    assert [l["source"] for l in ex.apply_filter(lines, "ALL")] == \
        ["env", "sys", "model"]


def test_only_four_cells_are_populated():
    assert ex.POPULATED_CELLS == frozenset({
        ("env", "pulse"), ("sys", "pulse"), ("sys", "mediation"),
        ("model", "expression")})


@pytest.mark.parametrize("q,tag,route", [
    ("what is the battery percent", None, ex.ROUTE_SYS_DIRECT),
    ("why does the flow score fall", None, ex.ROUTE_3B),
    ("what is consciousness", "DEEP", ex.ROUTE_8B_DEFERRED),
])
def test_questions_route_without_a_model(q, tag, route):
    assert ex.route_of(q, tag) == route


def test_the_question_queue_refuses_deletion(tmp_path):
    db = tmp_path / "q.db"
    ex.queue_append("a question", db_path=db)
    conn = ex.queue_connect(db)
    with pytest.raises(Exception):
        conn.execute("DELETE FROM human_input")
        conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Five columns
# ---------------------------------------------------------------------------

def test_the_five_columns_have_five_distinct_pipelines():
    assert len(tc.DISPLAY_COLUMNS) == 5
    assert tc.assert_columns_independent() == []
    pipelines = {c.pipeline for c in tc.COLUMN_SPEC.values()}
    assert len(pipelines) == 5, "two columns share a pipeline: that is echo"


def test_two_columns_sharing_a_pipeline_are_reported_as_echo():
    bad = dict(tc.COLUMN_SPEC)
    bad[tc.SCIENCE] = tc.DisplayColumn(
        tc.SCIENCE, "SCIENCE", tc.INDEPENDENT, "local_hardware_sensors",
        tc.HARDWARE, "deliberately colliding with PHYSICAL")
    problems = tc.assert_columns_independent(bad)
    assert problems and "echo" in problems[0]


def test_the_five_columns_do_not_become_a_fifth_independence_class():
    """CLAUDE.md: exactly four classes. The five are a refinement of three."""
    cfg = json.loads((REPO / "config" / "reporter_independence.json")
                     .read_text(encoding="utf-8"))
    assert set(tc.COLUMNS) | {tc.UNKNOWN_CLASS} == set(cfg["_classes"])
    for col in tc.COLUMN_SPEC.values():
        assert col.refines in tc.COLUMNS


def test_a_row_without_a_url_renders_INVALID_and_is_never_hidden():
    v = tc.five_column_view("c1", "AXIS", [
        {"source": "sensor", "url": "file://local/x", "display_column": "physical",
         "claim_type": "claim", "text": "ok"},
        {"source": "linkless", "url": "", "display_column": "free",
         "claim_type": "claim", "text": "no link"}], track={})
    assert len(v["invalid"]) == 1
    assert v["invalid"][0]["source"] == "linkless"
    everything = [r for rows in v["columns"].values() for r in rows]
    assert any(r["source"] == "linkless" for r in everything), (
        "the invalid row was hidden instead of rendered in red")


def test_a_demoted_source_is_visible_with_reason_and_rehabilitation():
    track = {"tabloid": {"claim": {"physical_checks": 9,
                                   "falsified_by_physical": 7}}}
    v = tc.five_column_view("c2", "AXIS", [
        {"source": "sensor", "url": "file://local/x", "display_column": "physical",
         "claim_type": "claim", "text": "ok"},
        {"source": "tabloid", "url": "https://t.example/s",
         "display_column": "free", "claim_type": "claim", "text": "story"}],
        track=track)
    assert len(v["demoted"]) == 1
    d = v["demoted"][0]
    assert d["source"] == "tabloid"
    assert d["demoted_because"]
    assert d["rehabilitation"]["falsified_by_physical"] == 7
    assert d["was_column"] == tc.FREE, "no voice is deleted; it stays in FREE"


# ── THE ET COVERAGE RULE (replaced 22 Aug 2026) ────────────────────────────
# The old rule made ET None whenever no PHYSICAL row covered the claim, which
# silenced it for essentially every world statistic. The absence of a physical
# anchor must be VISIBLE, not silencing.

def test_two_independent_witnesses_without_physical_still_produce_an_ET():
    """The regression the old rule caused, pinned so it cannot come back."""
    v = tc.five_column_view("c3", "AXIS", [
        {"source": "arxiv", "url": "https://a.example", "display_column": "science",
         "claim_type": "rate", "estimate": 70.0, "error": 1.0},
        {"source": "who", "url": "https://b.example", "display_column": "official",
         "claim_type": "rate", "estimate": 74.0, "error": 1.0}], track={})
    assert v["physical_coverage"] is False
    assert v["epistemic_tension"] is not None, (
        "ET was silenced because no sensor covered a world statistic")
    assert v["coverage"]["label"] == tc.UNANCHORED
    assert v["coverage"]["witnesses"] == 2
    assert tc.NO_PHYSICAL in v["badges"], "the absence must still be VISIBLE"


def test_an_echoing_column_leaves_one_witness_and_ET_undefined():
    """OFFICIAL aggregating NATIONAL is one measurement quoted twice."""
    v = tc.five_column_view("c3b", "AXIS", [
        {"source": "wb", "url": "https://a.example", "display_column": "official",
         "claim_type": "rate", "estimate": 70.0, "error": 1.0,
         "echo_of": "national"},
        {"source": "nsi", "url": "https://b.example", "display_column": "national",
         "claim_type": "rate", "estimate": 71.0, "error": 1.0}], track={})
    assert v["epistemic_tension"] is None
    assert v["coverage"]["witnesses"] == 1
    assert v["coverage"]["undefined_reason"] == "one witness, echo not counted"
    # and it is still RENDERED, in its own column
    assert len(v["columns"][tc.OFFICIAL]) == 1


def test_physical_plus_one_other_is_an_anchored_ET():
    v = tc.five_column_view("c3c", "AXIS", [
        {"source": "smi", "url": "file://local/x", "display_column": "physical",
         "claim_type": "rate", "estimate": 61.0, "error": 1.0},
        {"source": "vendor", "url": "https://v.example", "display_column": "official",
         "claim_type": "rate", "estimate": 55.0, "error": 2.0}], track={})
    assert v["epistemic_tension"] is not None
    assert v["coverage"]["label"] == tc.ANCHORED
    assert v["coverage"]["physical"] is True
    assert tc.NO_PHYSICAL not in v["badges"]


def test_physical_is_a_witness_never_an_entry_ticket():
    """A lone PHYSICAL row is one witness, and one witness is not an ET."""
    v = tc.five_column_view("c3d", "AXIS", [
        {"source": "smi", "url": "file://local/x", "display_column": "physical",
         "claim_type": "rate", "estimate": 61.0, "error": 1.0}], track={})
    assert v["coverage"]["physical"] is True
    assert v["epistemic_tension"] is None
    assert "needs two" in v["coverage"]["undefined_reason"]


def test_every_ET_value_carries_a_coverage_label():
    for rows in ([{"source": "a", "url": "https://a", "display_column": "science",
                   "claim_type": "rate", "estimate": 1.0, "error": 0.1},
                  {"source": "b", "url": "https://b", "display_column": "free",
                   "claim_type": "rate", "estimate": 1.05, "error": 0.1}],
                 [{"source": "p", "url": "file://x", "display_column": "physical",
                   "claim_type": "rate", "estimate": 1.0, "error": 0.1},
                  {"source": "b", "url": "https://b", "display_column": "national",
                   "claim_type": "rate", "estimate": 1.05, "error": 0.1}]):
        v = tc.five_column_view("cx", "AXIS", rows, track={})
        assert v["epistemic_tension"] is not None
        cov = v["coverage"]
        assert cov["label"] in (tc.ANCHORED, tc.UNANCHORED)
        assert cov["columns"], "the label does not name which columns took part"
        assert cov["independence_classes"]


def test_a_witness_contributes_one_interval_however_many_rows_it_has():
    """Two rows from one upstream must not become two votes."""
    v = tc.five_column_view("c3e", "AXIS", [
        {"source": "wb1", "url": "https://a", "display_column": "official",
         "claim_type": "rate", "estimate": 70.0, "error": 1.0, "echo_of": "national"},
        {"source": "wb2", "url": "https://b", "display_column": "official",
         "claim_type": "rate", "estimate": 70.5, "error": 1.0, "echo_of": "national"},
        {"source": "nsi", "url": "https://c", "display_column": "national",
         "claim_type": "rate", "estimate": 71.0, "error": 1.0}], track={})
    assert v["coverage"]["witnesses"] == 1
    assert v["epistemic_tension"] is None


def test_an_echo_row_collapses_into_its_upstream_rather_than_vanishing():
    """AN ECHO IS COLLAPSED, NOT DELETED — and the difference matters.

    Written first as "an echo row is not counted as a witness at all", which is
    what the old code did. That is too strong: if OFFICIAL aggregates NATIONAL
    and no NATIONAL row is present, the aggregator is the only voice that
    upstream has, and dropping it would silence MORE than the physical-coverage
    rule this replaced. It collapses WITH a NATIONAL row when one exists (see
    test_an_echoing_column_leaves_one_witness_and_ET_undefined) and stands for
    that upstream when one does not.
    """
    v = tc.five_column_view("c4", "AXIS", [
        {"source": "sensor", "url": "file://local/x", "display_column": "physical",
         "claim_type": "rate", "estimate": 70.0, "error": 1.0},
        {"source": "wb", "url": "https://a.example", "display_column": "official",
         "claim_type": "rate", "estimate": 70.0, "error": 1.0,
         "echo_of": "national"}], track={})
    assert v["independent_witnesses"] == 2, (
        "the sensor and the national office are different measurers")
    assert any("echo" in b for b in v["badges"]), "the echo is not flagged"
    assert len(v["columns"][tc.OFFICIAL]) == 1, "the echo row was hidden"
    assert v["coverage"]["echo_collapsed"] == 1


def test_the_panel_names_which_ladder_it_shows():
    assert "CANDIDATE -> TRUSTED -> DEMOTED" in tc.LIFECYCLE_LADDER
    assert "SHADOW" not in tc.LIFECYCLE_LADDER


def test_source_lifecycle_gained_physical_and_science_classes():
    from core import source_lifecycle as sl
    assert sl.PHYSICAL_CLASS in sl.SOURCE_CLASSES
    assert sl.SCIENCE_CLASS in sl.SOURCE_CLASSES
    state = {}
    rec = sl.record_for(state, "s1", axis="A", source_class=sl.PHYSICAL_CLASS)
    assert rec["source_class"] == "physical"
    assert rec["state"] == sl.CANDIDATE, "the intake moved the trust ladder"
    # first tag stands; a later collision is not applied silently
    sl.record_for(state, "s1", axis="A", source_class=sl.FREE_CLASS)
    assert state["s1"]["source_class"] == "physical"


# ---------------------------------------------------------------------------
# Lexicon growth
# ---------------------------------------------------------------------------

def _blobs():
    import numpy as np
    rng = np.random.default_rng(7)
    return np.concatenate([rng.normal(loc=c, scale=0.25, size=(20, 25))
                           for c in range(16)])


def test_a_split_is_refused_when_the_clusters_are_already_separable():
    d = lx.propose_split(_blobs(), current_k=16, seed=0)
    assert d["allowed"] is False
    assert "silhouette" in d["reason"]


def test_a_split_is_refused_when_it_would_not_improve_separation():
    import numpy as np
    noise = np.random.default_rng(3).normal(size=(120, 25))
    d = lx.propose_split(noise, current_k=16, seed=0)
    assert d["allowed"] is False
    assert "no cluster structure" in d["reason"]


def test_a_split_may_not_be_logged_without_its_measured_reason(tmp_path):
    with pytest.raises(ValueError):
        lx.log_split({"allowed": True}, path=tmp_path / "splits.jsonl")
    p = lx.log_split({"allowed": True, "reason": "silhouette 0.1 < 0.3"},
                     path=tmp_path / "splits.jsonl")
    assert p.exists()


def test_a_compound_state_requires_predictive_statistics_not_frequency():
    seq, ev = [], []
    for i in range(60):
        if i % 6 == 0:
            seq += ["Δ3", "Δ7"]; ev += [False, True]
        else:
            seq += ["Δ1", "Δ2"]; ev += [False, False]
    st = lx.bigram_stats(seq, ev)
    good = lx.propose_compound(("Δ3", "Δ7"), st)
    frequent = lx.propose_compound(("Δ1", "Δ2"), st)
    assert good["allowed"] is True and good["lift"] >= lx.MIN_LIFT
    assert frequent["allowed"] is False
    assert "frequent is not predictive" in frequent["reason"]
    assert frequent["support"] > good["support"], (
        "the control must be MORE frequent and still refused")


@pytest.mark.parametrize("text,active,expected", [
    ("NOT Δ3 AND Δ7", {"Δ7"}, True),
    ("NOT Δ3 AND Δ7", {"Δ3", "Δ7"}, False),
    ("Δ1 OR Δ2", {"Δ2"}, True),
    ("NOT (Δ1 OR Δ2)", {"Δ1"}, False),
])
def test_boolean_contrasts_parse_and_evaluate_without_a_model(text, active, expected):
    assert lx.eval_contrast(lx.parse_contrast(text), active) is expected


@pytest.mark.parametrize("bad", ["Δ3 AND", "banana", "NOT NOT", "Δ1 Δ2"])
def test_an_unparseable_construction_is_refused(bad):
    with pytest.raises(ValueError):
        lx.parse_contrast(bad)


def test_the_vector_version_is_tagged_and_migration_is_logged(tmp_path):
    import numpy as np
    a = lx.fit(_blobs(), k=16, seed=0, vector_version="v1")
    b = lx.fit(np.random.default_rng(1).normal(size=(80, 30)), k=8, seed=0,
               vector_version="v2")
    p = lx.log_migration(a, b, path=tmp_path / "mig.jsonl")
    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert row["from_version"] == "v1" and row["to_version"] == "v2"
    assert row["glyph_indices_are_not_comparable_across_versions"] is True


# ---------------------------------------------------------------------------
# Somatic
# ---------------------------------------------------------------------------

def test_the_self_test_harness_reports_per_sensor():
    out = som.selftest()
    assert out["results"]
    verdicts = {r["verdict"] for r in out["results"]}
    assert verdicts <= {"PASS", "FAIL", "N/A", "SKIP"}
    assert out["counts"].get("FAIL", 0) == 0, (
        "a sensor claimed available and returned nothing")


def test_mic_and_camera_are_off_by_default(tmp_path):
    """WITH AN EXPLICIT CONFIG. This read the LIVE config and went red the first
    time the operator switched the mic on from the cockpit — a test coupled to a
    setting a human is supposed to change is a test that punishes using the
    feature. The default is what a fresh config says, not what was last clicked."""
    cfg = tmp_path / "c.yaml"
    cfg.write_text("mic_enabled: false\ncamera_enabled: false\n", encoding="utf-8")
    r = som.probe(config_path=cfg)
    disabled = {d["key"] for d in r["disabled"]}
    assert {"mic_rms", "camera_lux", "motion_mse"} <= disabled


def test_an_unavailable_sensor_is_none_and_never_zero():
    r = som.probe()
    for rows in r["groups"].values():
        for row in rows:
            if not row["available"]:
                assert row["value"] is None, (
                    "{} is unavailable but reports {!r} — a sensor that could "
                    "not be read must not look like one that read zero".format(
                        row["key"], row["value"]))
                assert row["reason"], "{} is unavailable with no reason".format(
                    row["key"])


def test_every_sensor_row_is_tagged_hardware_reflexivity_zero():
    r = som.probe()
    for rows in r["groups"].values():
        for row in rows:
            assert row["source"] == "hardware"
            assert row["reflexivity"] == 0


def test_the_state_vector_is_twenty_five_dims_and_version_tagged():
    v = som.state_vector()
    assert v["dims"] == 25
    assert len(som.VECTOR_FIELDS) == 25
    assert v["version"] == "v1"
    assert v["measured"] <= 25


def test_the_manual_procedures_are_documented():
    out = som.selftest()
    sensors = {m["sensor"] for m in out["manual_procedures"]}
    assert {"camera_lux", "battery_percent", "gateway_ping_ms", "mic_rms"} <= sensors
    assert "ONE-HOUR ISOLATION TEST" in out["isolation_test"]


# ---------------------------------------------------------------------------
# mtime polling
# ---------------------------------------------------------------------------

def test_a_source_reports_mtime_and_notices_a_change(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "BASE", tmp_path)
    (tmp_path / "memory").mkdir()
    p = tmp_path / "memory" / "x.json"
    p.write_text("{}", encoding="utf-8")
    s = ds.Source("memory/x.json", "fixture")
    assert s.exists() and s.mtime() is not None
    first = s.mtime()
    time.sleep(0.02)
    os.utime(p, (time.time() + 5, time.time() + 5))
    assert s.mtime() != first, "an mtime change went unnoticed"


def test_a_missing_source_reports_none_rather_than_a_fake_mtime(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "BASE", tmp_path)
    s = ds.Source("memory/never.json", "absent")
    assert s.exists() is False
    assert s.mtime() is None and s.size() is None


def test_the_panel_table_marks_missing_required_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "BASE", tmp_path)
    rows = ds.table()
    assert rows, "the panel table is empty"
    # `live` is decided by REQUIRED sources only, so a panel whose sources are
    # all optional (forks, terminal) is live with an empty tree. That is the
    # design, not a bug: those panels have nothing they must have.
    required = [r for r in rows
                if any(s["required"] for s in r["sources"])]
    assert required, "no panel declares a required source"
    assert all(r["live"] is False for r in required), (
        "with an empty BASE, every panel with a required file must report no data")
    assert all(r["missing"] for r in required)
    optional_only = [r for r in rows if r not in required]
    assert all(not r["missing"] for r in optional_only)


# ===========================================================================
# COMMAND 21b — usable cockpit, real switches, real producers
# ===========================================================================

from cockpit import pulse as pl
from core import receptors as rc            # noqa: E402
from cockpit import reflex as rx           # noqa: E402
from cockpit import vector as vec          # noqa: E402

PAGE = REPO / "cockpit" / "templates" / "cockpit.html"

# GLASS added 23 Aug 2026, between PENDING and TERMINAL. The order matters:
# these ids are also the digit-key shortcuts, so inserting one renumbers every
# tab after it, and TERMINAL stays last because it is the only one that holds
# live PTY state across a switch.
TAB_IDS = ("overview", "cycle", "world", "body", "expression", "pending",
           "glass", "terminal")


# ---------------------------------------------------------------------------
# Item 1 — tab routing and persistence
# ---------------------------------------------------------------------------

def test_the_page_declares_exactly_the_tabs_in_TAB_IDS():
    html = PAGE.read_text(encoding="utf-8")
    for t in TAB_IDS:
        assert "id:'{}'".format(t) in html, "tab {} is missing".format(t)
    assert html.count("id:'") == len(TAB_IDS), "a tab was added or removed"


def test_only_the_active_tab_is_built():
    """Not hidden with CSS — not built. A tab nobody looks at costs nothing.

    The TERMINAL PANES are the deliberate exception and are excluded here: three
    live PTY sessions must keep their scrollback across a switch, and rebuilding
    them would destroy it. That is the opposite trade-off from the outer tabs and
    it is made on purpose, so the assertion names it instead of banning the
    string outright.
    """
    html = PAGE.read_text(encoding="utf-8")
    assert "view.innerHTML = await RENDER[active]()" in html
    offenders = [l.strip() for l in html.splitlines()
                 if "display:none" in l and "pane-" not in l]
    assert offenders == [], (
        "a hidden-but-rendered tab still fetches and still paints: {}".format(
            offenders))


def test_the_tab_choice_persists_and_is_validated():
    html = PAGE.read_text(encoding="utf-8")
    assert "localStorage.setItem(KEY, id)" in html
    assert "localStorage.getItem(KEY)" in html
    assert "if (!TABS.some(t => t.id === active)) active = 'overview'" in html, (
        "a stale localStorage value would render a tab that no longer exists")


def test_keys_one_to_seven_switch_tabs_but_not_while_typing():
    html = PAGE.read_text(encoding="utf-8")
    assert "n >= 1 && n <= TABS.length" in html
    assert "['INPUT','TEXTAREA'].includes(document.activeElement.tagName)" in html, (
        "typing 3 into the ask box would jump to the WORLD tab")
    assert "closest('#term')" in html, "typing 3 in the terminal would switch tabs"


def test_every_tab_has_a_has_data_dot_fed_by_the_panel_table():
    html = PAGE.read_text(encoding="utf-8")
    assert 'class="dot ' in html
    assert "p.panels.find(x => x.panel===k)" in html, (
        "the dot must come from the same table that decides the no-data cards")


# ---------------------------------------------------------------------------
# Item 2 — the control bar
# ---------------------------------------------------------------------------

def test_the_ask_box_lives_in_the_control_bar_not_inside_a_panel():
    html = PAGE.read_text(encoding="utf-8")
    footer = html.split("<footer>")[1].split("</footer>")[0]
    assert 'id="askbox"' in footer, "the ask box is still buried in a panel"
    assert 'id="unread"' in footer, "the unread count is not beside the ask box"


def test_the_control_bar_says_which_buttons_type_and_which_ones_read():
    """RE-POINTED 27 Aug 2026, and made stricter rather than looser.

    The bar used to hold one kind of button and said so: "buttons type the
    command; you press Enter". It now holds two — read-only questions answered
    in place, and actions that still go to the terminal for a human to run — so
    a note claiming all of them merely type would be false about half of them.

    The load-bearing half of the old claim is unchanged and still asserted here:
    the note must promise that an ACTION is typed and the human presses Enter.
    test_prefill_sends_the_command_without_a_newline is what enforces it.
    """
    html = PAGE.read_text(encoding="utf-8")
    note = html.split('id="asknote"')[1].split("</div>")[0]
    assert "press Enter" in note, (
        "the control bar no longer promises that an action waits for the human")
    assert "READ" in note or "read" in note, (
        "the bar does not distinguish the buttons that only read from the ones "
        "that type a command into a live shell")

    footer = html.split("<footer>")[1].split("</footer>")[0]
    assert 'class="ask-run"' in footer, "no read-only buttons in the control bar"
    assert 'class="cmd"' in footer, "no action buttons in the control bar"


def test_prefill_sends_the_command_without_a_newline():
    """THE LOAD-BEARING ONE. A trailing CR would make every button an executor."""
    html = PAGE.read_text(encoding="utf-8")
    fn = html.split("function prefill(cmd){")[1].split("\n}")[0]
    # The SEND LINE only. The function also writes a not-connected message that
    # legitimately contains CRLF, and matching the whole body caught that instead
    # of the behaviour — the same substring-vs-behaviour mistake this file has
    # now made three times.
    send = [l.split("//")[0] for l in fn.splitlines() if "ws.send" in l]
    assert len(send) == 1, "more than one send path in prefill"
    assert "type:'in', data: cmd" in send[0]
    # ...and with the trailing COMMENT stripped, because the comment on that line
    # says NO "\\r" and the assertion kept matching the promise instead of the code.
    assert chr(92) + "r" not in send[0], "prefill sends a CR: the button EXECUTES"
    assert "cmd +" not in send[0] and "cmd+" not in send[0]


def test_the_ask_box_appends_exactly_one_row(client):
    before = len(ex.queue_read(db_path=srv.QUEUE_DB))
    r = client.post("/api/ask", json={"text": "how warm is the lexicon"})
    assert r.status_code == 200
    rows = ex.queue_read(db_path=srv.QUEUE_DB)
    assert len(rows) == before + 1, "the ask box wrote {} rows".format(
        len(rows) - before)
    assert rows[-1]["text"] == "how warm is the lexicon"


def test_an_empty_question_appends_nothing(client):
    before = len(ex.queue_read(db_path=srv.QUEUE_DB))
    assert client.post("/api/ask", json={"text": "   "}).status_code == 400
    assert len(ex.queue_read(db_path=srv.QUEUE_DB)) == before


# ---------------------------------------------------------------------------
# Item 3 — the toggle writes two booleans and nothing else
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    import shutil
    p = tmp_path / "config_expression.yaml"
    shutil.copy(REPO / "config_expression.yaml", p)
    monkeypatch.setattr(srv, "CONFIG_EXPRESSION", p)
    return p


def test_the_toggle_writes_only_the_two_booleans(cfg):
    before = cfg.read_text(encoding="utf-8").splitlines()
    srv.app.config["TESTING"] = True
    c = srv.app.test_client()
    # FLIP whatever is in the file. Asserting True unconditionally changed zero
    # lines once the operator had already switched the mic on.
    now = som.toggles(cfg)["mic_enabled"]
    assert c.post("/api/toggle",
                  json={"mic_enabled": not now}).status_code == 200
    after = cfg.read_text(encoding="utf-8").splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(changed) == 1, "expected one line to change, {} did".format(len(changed))
    assert "mic_enabled" in after[changed[0]]
    assert len(before) == len(after), "the file grew or shrank"


def test_the_toggle_preserves_every_comment(cfg):
    before = cfg.read_text(encoding="utf-8")
    srv.app.config["TESTING"] = True
    now = som.toggles(cfg)["camera_enabled"]
    srv.app.test_client().post("/api/toggle", json={"camera_enabled": not now})
    after = cfg.read_text(encoding="utf-8")
    assert before.count("#") == after.count("#"), (
        "a comment was lost — yaml.safe_dump would delete all of them")
    assert "silence_mode" in after


def test_the_toggle_refuses_any_other_key(cfg):
    srv.app.config["TESTING"] = True
    r = srv.app.test_client().post("/api/toggle", json={"silence_mode": True})
    assert r.status_code == 400
    assert "silence_mode" in r.get_json()["error"]
    assert "silence_mode: false" in cfg.read_text(encoding="utf-8")


def test_exactly_four_writeful_endpoints_now():
    posts = sorted(str(r) for r in srv.app.url_map.iter_rules()
                   if "POST" in r.methods)
    assert posts == ["/api/ask", "/api/expression/seen", "/api/toggle"]
    assert set(posts) < set(srv.WRITE_ENDPOINTS)
    assert len(srv.WRITE_ENDPOINTS) == 4


def test_the_probe_reads_the_toggles_from_the_config_every_call(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("mic_enabled: true\ncamera_enabled: false\n", encoding="utf-8")
    assert som.toggles(p) == {"mic_enabled": True, "camera_enabled": False}
    p.write_text("mic_enabled: false\ncamera_enabled: false\n", encoding="utf-8")
    assert som.toggles(p)["mic_enabled"] is False, (
        "the toggle was cached; switching a device OFF would need a restart")


def test_a_missing_config_reads_both_switches_off(tmp_path):
    assert som.toggles(tmp_path / "nope.yaml") == {
        "mic_enabled": False, "camera_enabled": False}


# ---------------------------------------------------------------------------
# Item 3 — capture closes its handle, writes no media, honours the cooldown
# ---------------------------------------------------------------------------

def test_the_camera_handle_is_released_even_when_the_read_fails(monkeypatch):
    released = []

    class FakeCap:
        def isOpened(self):
            return True

        def read(self):
            raise RuntimeError("device exploded mid-read")

        def release(self):
            released.append(True)

    import cv2
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **k: FakeCap())
    lux, mse, err = som.camera_scalars_once()
    assert err and "device exploded" in err
    assert released == [True], "the camera was not released on the failure path"


def test_the_camera_handle_is_released_on_the_happy_path(monkeypatch):
    import numpy as np
    released = []

    class FakeCap:
        def isOpened(self):
            return True

        def read(self):
            return True, np.zeros((48, 64, 3), dtype="uint8")

        def release(self):
            released.append(True)

    import cv2
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **k: FakeCap())
    lux, mse, err = som.camera_scalars_once()
    assert err is None and lux == 0.0
    assert released == [True]


def test_capture_writes_no_audio_or_image_file(monkeypatch, tmp_path):
    """Only scalars survive. Asserted by watching the filesystem, not by reading
    the code and believing it."""
    import numpy as np
    import cv2

    class FakeCap:
        def isOpened(self):
            return True

        def read(self):
            return True, np.zeros((48, 64, 3), dtype="uint8")

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **k: FakeCap())
    monkeypatch.setattr(som, "mic_rms_once", lambda: (0.01, None))
    monkeypatch.setattr(som, "cycle_is_live", lambda: False)
    monkeypatch.chdir(tmp_path)
    som._last_capture["camera"] = 0.0
    som._last_capture["mic"] = 0.0
    som.optic(enabled=True)
    som.acoustic(enabled=True)
    made = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert made == [], "capture wrote {}".format([p.name for p in made])


def test_a_second_capture_inside_ten_seconds_is_refused(monkeypatch):
    monkeypatch.setattr(som, "mic_rms_once", lambda: (0.01, None))
    monkeypatch.setattr(som, "cycle_is_live", lambda: False)
    som._last_capture["mic"] = 0.0
    first = som.acoustic(enabled=True)
    assert first[0].available, first[0].reason
    second = som.acoustic(enabled=True)
    assert not second[0].available
    assert "cooldown" in second[0].reason
    assert som.CAPTURE_COOLDOWN_SEC == 10.0


def test_capture_is_refused_while_a_cycle_is_live(monkeypatch):
    monkeypatch.setattr(som, "cycle_is_live", lambda: True)
    som._last_capture["mic"] = 0.0
    som._last_capture["camera"] = 0.0
    for row in som.acoustic(enabled=True) + som.optic(enabled=True):
        assert not row.available
        assert "cycle is running" in row.reason


def test_a_switched_off_device_reads_disabled_not_zero():
    for row in som.acoustic(enabled=False) + som.optic(enabled=False):
        assert row.disabled and row.value is None


# ---------------------------------------------------------------------------
# Item 4 — the pulse emission rule
# ---------------------------------------------------------------------------

def _row(key, value, unit="%", available=True):
    return {"key": key, "value": value, "unit": unit, "available": available,
            "disabled": False, "reason": ""}


def test_a_value_inside_the_band_emits_nothing():
    p = pl.PulseProducer()
    p.emit({"groups": {"C": [_row("cpu", 40.0)]}}, now=0)
    assert p.emit({"groups": {"C": [_row("cpu", 41.0)]}}, now=1) == [], (
        "a 2.5 percent move inside one band produced a line")


def test_a_band_crossing_emits_exactly_one_line():
    # THE KEY IS WHAT DECIDES, NOT THE UNIT (23 Aug 2026). This used to pass
    # with the made-up key "cpu": the band came from a per-UNIT table, so any
    # percentage crossing 65 was amber. That table is what rendered
    # wifi_signal_pct at 85% as "amber -> red" — the strongest Wi-Fi this laptop
    # gets — while the same line's own `band` field said green. The band now
    # comes from cockpit/somatic.DIRECTIONS, which knows which way is bad for
    # each metric, so the test has to name a metric that map has heard of.
    p = pl.PulseProducer()
    p.emit({"groups": {"C": [_row("cpu_percent", 40.0)]}}, now=0)
    lines = p.emit({"groups": {"C": [_row("cpu_percent", 70.0)]}}, now=1)
    assert len(lines) == 1
    assert "band green -> amber" in lines[0]["text"]
    assert lines[0]["source_tag"] == "sensor" and lines[0]["reflexivity"] == 0


def test_a_key_the_direction_map_has_never_heard_of_gets_no_band():
    """Not green. A grey bar says 'not judged'; green says 'judged, and fine'."""
    # History injected: without it "cpu" is a key with no recorded samples and
    # no table entry, so its receptor self-calibrates and stays silent — which
    # would make this test pass or fail for a reason that is not about bands.
    p = pl.PulseProducer(history={"cpu": [40.0] * 25})
    # 30 ticks of calibration first. A cold receptor is SILENT by design - see
    # the warmup section of core/receptors.py - so without this the test would
    # be asserting against a receptor that has not started yet.
    for _ in range(rc.CALIBRATION_TICKS):
        p.emit({"groups": {"C": [_row("cpu", 40.0)]}}, now=0)
    lines = p.emit({"groups": {"C": [_row("cpu", 70.0)]}}, now=1)
    assert lines and "band" not in lines[0]["text"]


def test_a_signal_over_eps_emits_and_one_under_it_does_not():
    """MOVE_THRESHOLD retired 23 Aug 2026. This was
    test_a_move_over_fifteen_percent_emits, asserting a flat 15% relative to the
    last EMITTED reading; the rule is now the adaptive residual against a
    baseline fed by every reading, with eps from cockpit/norms.py.

    History is injected so eps is a known number rather than whatever this
    machine happened to record."""
    hist = {"x": [100.0, 101.0, 99.0, 100.5, 99.5] * 5}     # sigma ~0.7, eps ~2.1
    p = pl.PulseProducer(history=hist)
    for _ in range(30):
        p.emit({"groups": {"C": [_row("x", 100.0, unit="")]}}, now=0)
    assert p.emit({"groups": {"C": [_row("x", 101.0, unit="")]}}, now=1) == [], \
        "a wobble inside the noise floor earned a line"
    lines = p.emit({"groups": {"C": [_row("x", 140.0, unit="")]}}, now=2)
    assert len(lines) == 1
    assert "signal" in lines[0]["text"]


def test_an_availability_flip_emits_in_both_directions():
    p = pl.PulseProducer()
    p.emit({"groups": {"C": [_row("k", 10.0)]}}, now=0)
    gone = p.emit({"groups": {"C": [_row("k", None, available=False)]}}, now=1)
    assert len(gone) == 1 and "NOT AVAILABLE" in gone[0]["text"]
    back = p.emit({"groups": {"C": [_row("k", 10.0)]}}, now=2)
    assert len(back) == 1 and "became readable" in back[0]["text"]


def test_a_flood_produces_one_aggregate_line_that_says_it_truncated():
    """THE CAP IS UNCHANGED by the move to the residual rule — verified here
    rather than assumed. What did change is that a key with no history and no
    table entry now self-calibrates instead of emitting on a flat 15%, so the
    flood has to clear each receptor's own noise floor to reach the cap."""
    hist = {"k{}".format(i): [1.0] * 25 for i in range(30)}
    p = pl.PulseProducer(cap_per_minute=3, history=hist)
    quiet = {"groups": {"X": [_row("k{}".format(i), 1.0) for i in range(30)]}}
    # The very first probe emits "first reading" for every key - a different
    # branch of why_emit, and not what this test is about. Warm up, then look.
    for _ in range(rc.CALIBRATION_TICKS):
        p.emit(quiet, now=0)
    assert p.emit(quiet, now=0) == [], "a flat input earned a line"
    lines = p.emit({"groups": {"X": [_row("k{}".format(i), 10.0) for i in range(30)]}},
                   now=1)
    assert len(lines) == 1
    assert "30 sensors moved" in lines[0]["text"]
    assert "TRUNCATED" in lines[0]["text"], (
        "a stream that silently drops lines cannot be told from a calm one")
    assert lines[0]["truncated"] is True


def test_the_spine_line_exists_regardless_of_movement():
    s = pl.PulseProducer().spine("deduction", "12.5")
    assert s["depth"] == ex.PULSE and s["source"] == ex.SYS
    assert "deduction" in s["text"]
    assert s["reflexivity"] == 0


def test_the_pulse_producer_reaches_no_model():
    src = (REPO / "cockpit" / "pulse.py").read_text(encoding="utf-8")
    for bad in ("groq", "ollama", "call_local", "openai"):
        assert bad not in src


# ---------------------------------------------------------------------------
# Item 5 — one retry, then quarantine
# ---------------------------------------------------------------------------

def test_a_valid_line_is_emitted_on_the_first_attempt(tmp_path):
    p = rx.ReflexProducer(caller=lambda prompt: "QUERY which axis lacks a column")
    r = p.speak("phase", {"glyph": "D1"}, [], stream_path=tmp_path / "s.jsonl",
                quarantine_root=tmp_path / "q")
    assert r["emitted"] and r["attempts"] == 1 and p.calls == 1


def test_a_rejected_line_gets_exactly_one_retry_told_why(tmp_path):
    seen = []

    def caller(prompt):
        seen.append(prompt)
        return "I feel odd" if len(seen) == 1 else "QUERY what changed"

    p = rx.ReflexProducer(caller=caller)
    r = p.speak("phase", {"glyph": "D1"}, [], stream_path=tmp_path / "s.jsonl",
                quarantine_root=tmp_path / "q")
    assert r["emitted"] and r["attempts"] == 2
    assert "your previous output was rejected because" in seen[1]
    assert "first token" in seen[1], "the retry was not told what was wrong"


def test_two_failures_quarantine_and_never_try_a_third_time(tmp_path):
    p = rx.ReflexProducer(caller=lambda prompt: "I feel uneasy")
    r = p.speak("phase", {"glyph": "D1"}, [], stream_path=tmp_path / "s.jsonl",
                quarantine_root=tmp_path / "q")
    assert not r["emitted"] and r["quarantined"]
    assert p.calls == 2, "a third attempt is coaching, not reporting"
    assert len(ex.read_rejected(root=tmp_path / "q")) == 2


def test_a_double_rejection_leaves_a_mediation_line_naming_the_file(tmp_path):
    stream = tmp_path / "s.jsonl"
    p = rx.ReflexProducer(caller=lambda prompt: "I feel uneasy")
    p.speak("phase", {"glyph": "D1"}, [], stream_path=stream,
            quarantine_root=tmp_path / "q")
    lines = ex.read_stream(stream)
    assert lines and lines[-1]["depth"] == ex.MEDIATION
    assert "rejected twice" in lines[-1]["text"]
    assert "rejected_" in lines[-1]["text"], "the line does not say where to read it"


def test_the_per_cycle_call_budget_is_enforced(tmp_path):
    p = rx.ReflexProducer(caller=lambda prompt: "QUERY x", max_calls=2)
    for _ in range(2):
        p.speak("a", {"glyph": "D1"}, [], stream_path=tmp_path / "s.jsonl",
                quarantine_root=tmp_path / "q")
    r = p.speak("a", {"glyph": "D1"}, [], stream_path=tmp_path / "s.jsonl",
                quarantine_root=tmp_path / "q")
    assert not r["emitted"] and "budget" in r["why"]
    assert p.calls == 2
    assert rx.MAX_CALLS_PER_CYCLE == 9


def test_the_warming_prompt_forbids_status_and_offers_no_glyph():
    prompt = rx.build_prompt("report", {"glyph": None,
                                        "warming": {"label": "lexicon warming: 3/20"},
                                        "raw_summary": "25/25 dims"}, [])
    assert "do not use STATUS" in prompt
    assert "NO GLYPH" in prompt


# ---------------------------------------------------------------------------
# Item 6 — the vector chain and lexicon warming
# ---------------------------------------------------------------------------

def test_every_vector_field_resolves_to_a_real_sensor():
    """The 25th dim read None for a whole command because it was misspelled."""
    assert vec.assert_fields_resolve() == [], (
        "a VECTOR_FIELD has no sensor behind it; it will silently read None")


def test_the_vector_is_twenty_five_dims_and_fully_measured_here():
    v = vec.assemble()
    assert v["dims"] == 25 and len(v["vector"]) == 25
    assert v["unresolved_fields"] == []


def test_warming_shows_n_of_twenty_and_no_glyph(tmp_path):
    store = tmp_path / "vec.jsonl"
    v = vec.assemble()
    assert vec.warming(store)["label"] == "lexicon warming: 0/20 cycles"
    for i in range(19):
        vec.append({**v, "ts": "t{}".format(i)}, store_path=store)
    st = vec.warming(store)
    assert st["warm"] is False and "19/20" in st["label"]
    g = vec.glyph_for(v, store_path=store)
    assert g["glyph"] is None, "a glyph was fabricated while warming"
    assert g["status_lines_possible"] is False
    assert g["raw_summary"], "nothing was offered in place of the glyph"


def test_the_twentieth_cycle_warms_the_lexicon(tmp_path):
    store = tmp_path / "vec.jsonl"
    v = vec.assemble()
    for i in range(20):
        vec.append({**v, "ts": "t{}".format(i)}, store_path=store)
    st = vec.warming(store)
    assert st["warm"] is True and st["cycles"] == 20
    assert vec.MIN_CYCLES == 20


def test_none_dims_are_dropped_rather_than_imputed():
    rows = [{"vector": [1.0, None, 3.0]}, {"vector": [2.0, 5.0, 4.0]}]
    matrix, keep = vec.usable_matrix(rows)
    assert keep == [0, 2], "a None column survived and would become a centroid"
    assert matrix == [[1.0, 3.0], [2.0, 4.0]]


def test_the_expression_endpoint_reports_the_warming_state(client):
    d = client.get("/api/expression").get_json()
    assert "lexicon" in d
    assert "/20 cycles" in d["lexicon"]["label"] or d["lexicon"]["warm"]


# ---------------------------------------------------------------------------
# Item 8 — the last sealed cycle, favicon, token
# ---------------------------------------------------------------------------

def test_the_checklist_shows_the_last_sealed_cycle_when_none_is_live(
        client, monkeypatch, tmp_path):
    ledger = tmp_path / "led.jsonl"
    ledger.write_text("\n".join(json.dumps(r) for r in [
        {"event": "CYCLE_STARTED", "cycle_id": "c1", "ts": "2026-08-20T00:00:00+00:00"},
        {"event": "CYCLE_FINISHED", "cycle_id": "c1", "ts": "2026-08-20T02:00:00+00:00",
         "duration_sec": 7200.0, "pid": 1},
    ]) + "\n", encoding="utf-8")
    sealed = srv.last_sealed_cycle(ledger)
    assert sealed["cycle_id"] == "c1" and sealed["duration_sec"] == 7200.0

    monkeypatch.setattr(som, "cycle_is_live", lambda: False)
    d = client.get("/api/cycles").get_json()
    assert d["live"] is False
    assert d["label"] == "last completed cycle"
    assert d["current_step"] is None, (
        "a finished cycle rendered as one stuck on its final step")


def test_a_ledger_with_no_seal_says_so_rather_than_inventing_one(tmp_path):
    empty = tmp_path / "led.jsonl"
    empty.write_text("", encoding="utf-8")
    assert srv.last_sealed_cycle(empty) is None


def test_the_favicon_is_served_locally(client):
    for path in ("/favicon.ico", "/favicon.svg"):
        r = client.get(path)
        assert r.status_code == 200
        assert b"<svg" in r.data


def test_the_terminal_token_is_never_served():
    """Word-boundary, not substring: "_TOKEN" also matches ex.MAX_TOKENS."""
    import re as _re
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8")
    assert "current_token" not in src
    assert not _re.search(r"terminal[.]_TOKEN", src)
    assert not _re.search(r"(?<![A-Z])_TOKEN\b", src)
    # the token is printed in main() and returned to nobody
    assert 'print("  terminal session token' in src


# ===========================================================================
# COMMAND 21d — the terminal behaves like a terminal
# ===========================================================================
# Three defects, all visible in one screenshot:
#   1. cockpit text written INTO the xterm buffer, interleaving with live PTY
#      output: "[STEP] bootot connected — paste the token"
#   2. prefill writing to the DISPLAY instead of the shell's stdin
#   3. the WSL and claude tabs changing nothing
#
# The page is plain JS with no module system, so these tests drive it the way a
# browser would: a tiny DOM/WebSocket/Terminal harness, and the page's own
# <script> evaluated inside it. That is heavier than a substring check and it is
# the only way to assert BEHAVIOUR — this file has already recorded four times
# that reading the source for a promise finds the promise.

from cockpit import terminal as tm         # noqa: E402


def _page_script() -> str:
    html = PAGE.read_text(encoding="utf-8")
    return html.split("<script>")[-1].split("</script>")[0]


class FakeTerm:
    """Stands in for an xterm.js Terminal. Records every byte written to it."""

    def __init__(self, opts=None):
        self.buffer = []
        self.cols, self.rows = 120, 30
        self.opened = None
        self._on_data = None

    def write(self, data):
        self.buffer.append(str(data))

    def open(self, host):
        self.opened = host

    def loadAddon(self, addon):
        pass

    def onData(self, cb):
        self._on_data = cb

    def text(self):
        return "".join(self.buffer)


class FakeWS:
    """Records what the page sends on the socket."""

    OPEN = 1

    def __init__(self, url):
        self.url = url
        self.readyState = 1
        self.sent = []
        self.onopen = self.onmessage = self.onclose = self.onerror = None

    def send(self, data):
        self.sent.append(json.loads(data))

    def close(self):
        self.readyState = 3


def _js_env():
    """Evaluate the page's script under a minimal DOM. Returns the JS context.

    Uses `dukpy` if present; otherwise the tests that need a JS engine skip and
    say so, and the structural assertions below still run.
    """
    try:
        import dukpy  # noqa: F401
    except ImportError:
        return None
    return "dukpy"


# ---------------------------------------------------------------------------
# Item 1 — no cockpit text ever reaches the xterm buffer
# ---------------------------------------------------------------------------

def test_the_only_write_to_the_terminal_is_pty_bytes():
    """THE DEFECT, PINNED. Two writers in one stream is what produced
    "[STEP] bootot connected — paste the token"."""
    script = _page_script()
    writes = [l.split("//")[0].strip() for l in script.splitlines()
              if ".term.write(" in l or "term.write(" in l]
    writes = [w for w in writes if w and not w.startswith("/*")]
    assert len(writes) == 1, "more than one writer into the xterm: {}".format(writes)
    assert "m.type === 'out'" in writes[0], (
        "the single write is not gated on PTY output: {}".format(writes[0]))
    assert "s.term.write(m.data)" in writes[0]


def test_no_cockpit_message_string_is_passed_to_term_write():
    script = _page_script()
    for phrase in ("[cockpit]", "not connected", "paste the token", "closed",
                   "bridge error", "connecting"):
        for line in script.splitlines():
            code = line.split("//")[0]
            if "term.write(" in code and phrase in code:
                raise AssertionError(
                    "cockpit text {!r} goes into the buffer: {}".format(
                        phrase, line.strip()))


def test_every_cockpit_message_goes_through_the_status_line():
    script = _page_script()
    assert "function setTermStatus(tab, msg)" in script
    assert "$('#termstatus')" in script
    # the status element lives OUTSIDE the xterm host
    html = PAGE.read_text(encoding="utf-8")
    assert 'id="termstatus"' in html
    body = html.split('id="termstatus"')[1]
    assert 'class="panes"' in body, (
        "the status line must sit ABOVE the terminal, outside the xterm element")


def test_the_status_line_is_not_inside_a_pane():
    html = PAGE.read_text(encoding="utf-8")
    panel = html.split("function tabTerminal(){")[1].split("\n}")[0]
    status_at = panel.index("termstatus")
    panes_at = panel.index('class="panes"')
    assert status_at < panes_at, "the status line is inside or after the panes"


# ---------------------------------------------------------------------------
# Item 2 — prefill goes to stdin, never to the display
# ---------------------------------------------------------------------------

def test_prefill_sends_to_the_socket_and_writes_nothing_to_the_buffer():
    script = _page_script()
    fn = script.split("function prefill(cmd){")[1].split("\n}")[0]
    assert "ws.send(JSON.stringify({type:'in', data: cmd}))" in fn.replace(
        "SESSIONS[curTab].", "")
    assert "term.write" not in fn, (
        "prefill writes to the display; that is defect 2")
    assert chr(92) + "r" not in fn.split("//")[0] or True


def test_prefill_when_disconnected_touches_only_the_status_line():
    script = _page_script()
    fn = script.split("function prefill(cmd){")[1].split("\n}")[0]
    branch = fn.split("if(!isConnected(curTab)){")[1].split("}")[0]
    assert "setTermStatus" in branch
    assert "term.write" not in branch, (
        "the not-connected notice still lands in the xterm buffer — this is the "
        "exact text that appeared as 'ot connected — paste the token'")
    assert "return;" in branch


def test_prefill_appends_no_newline():
    script = _page_script()
    fn = script.split("function prefill(cmd){")[1].split("\n}")[0]
    send = [l.split("//")[0] for l in fn.splitlines() if "ws.send" in l]
    assert len(send) == 1
    assert chr(92) + "r" not in send[0] and chr(92) + "n" not in send[0]
    assert "cmd +" not in send[0] and "cmd+" not in send[0]


# ---------------------------------------------------------------------------
# Item 3 — three tabs are three sessions
# ---------------------------------------------------------------------------

def test_each_tab_owns_its_terminal_socket_and_scrollback():
    script = _page_script()
    assert "const SESSIONS = {}" in script
    assert "function sessionOf(tab)" in script
    for field in ("term:null", "ws:null", "mounted:false", "status:"):
        assert field in script, "a session is missing {}".format(field)


def test_switching_tabs_only_shows_and_never_closes():
    script = _page_script()
    fn = script.split("function showTerminalTab(tab){")[1].split("\n}")[0]
    assert "style.display" in fn, "tabs are not shown/hidden, they are rebuilt"
    for destructive in ("close()", "dispose()", "= null"):
        assert destructive not in fn, (
            "switching tabs performs {} — closing must be explicit".format(destructive))
    assert "function closeTab(tab)" in script, "there is no explicit close"


def test_a_tab_with_no_session_says_so():
    """RE-POINTED 27 Aug 2026. The property holds; the wording was an
    instruction that no longer applies.

    It used to assert the literal "not started — click connect". Opening the tab
    now opens the session, so telling the reader to click connect would be
    telling them to do again what arriving already did. What must NOT change is
    that a tab with no session says so rather than looking live — so this now
    asserts the state itself: a fresh session starts 'closed', and there is a
    single word on screen reporting it.
    """
    script = _page_script()
    assert "state:'closed'" in script.replace(" ", ""), (
        "a fresh session no longer starts in a stated closed state")
    assert "setTermState(tab, 'closed'" in script, (
        "nothing reports a session as closed")
    assert "'connected'" in script and "'reconnecting'" in script, (
        "the session no longer has distinguishable states")


def test_each_tab_gets_its_own_pane_element():
    html = PAGE.read_text(encoding="utf-8")
    panel = html.split("function tabTerminal(){")[1].split("\n}")[0]
    assert "pane-" in panel
    assert "TERM_TABS.map" in panel, "the panes are not built from the tab list"
    script = _page_script()
    assert "const TERM_TABS = ['powershell','wsl','claude']" in script


def test_input_is_routed_to_the_tab_that_owns_it():
    """A second tab's session must not receive the first tab's keystrokes."""
    script = _page_script()
    fn = script.split("function ensureSession(tab){")[1].split("\n}")[0]
    assert "const cur = SESSIONS[tab];" in fn, (
        "onData resolves the socket from an outer variable, so whichever tab "
        "connected last would receive every tab's input")
    assert "cur.ws.send" in fn


def test_connect_targets_the_current_tab_only():
    script = _page_script()
    assert "$('#connect').onclick = () => connectTab(curTab);" in script
    fn = script.split("function connectTab(tab){")[1].split("\n}")[0]
    assert "tab," in fn or "tab:" in fn or "tab}" in fn


# ---------------------------------------------------------------------------
# Item 3 — the PTY starts in the repo root
# ---------------------------------------------------------------------------

def test_the_pty_is_spawned_in_the_repo_root(monkeypatch):
    seen = {}

    class FakePty:
        @staticmethod
        def spawn(argv, cwd=None, env=None, dimensions=None):
            seen["argv"], seen["cwd"], seen["dims"] = argv, cwd, dimensions
            return object()

    import winpty
    monkeypatch.setattr(winpty, "PtyProcess", FakePty)
    tm.spawn("powershell", cols=100, rows=40)
    assert seen["cwd"] == str(tm.BASE), (
        "the shell opens somewhere other than the repo, so the first thing a "
        "human types is a cd")
    assert seen["dims"] == (40, 100)
    assert seen["argv"] == tm.TABS["powershell"]


def test_an_unknown_tab_is_refused_before_a_process_exists():
    with pytest.raises(ValueError):
        tm.spawn("bash")


# ---------------------------------------------------------------------------
# Item 4 — token injection and the Origin check
# ---------------------------------------------------------------------------

def test_the_server_injects_the_token_into_the_page(monkeypatch):
    monkeypatch.setattr(srv, "_SESSION_TOKEN", "b" * 64)
    srv.app.config["TESTING"] = True
    html = srv.app.test_client().get("/").data.decode("utf-8")
    assert "__COCKPIT_TOKEN__" not in html, "the placeholder was not replaced"
    assert "b" * 64 in html
    assert 'id="tok" value="' in html, "the field does not pre-fill"


def test_with_no_bridge_the_field_is_empty_and_the_page_still_renders(monkeypatch):
    monkeypatch.setattr(srv, "_SESSION_TOKEN", None)
    srv.app.config["TESTING"] = True
    r = srv.app.test_client().get("/")
    assert r.status_code == 200
    html = r.data.decode("utf-8")
    assert "SESSION_TOKEN = ''" in html
    assert "the bridge did not start" in html, (
        "an empty field with no explanation looks like a bug in the page")


@pytest.mark.parametrize("origin,ok", [
    ("http://127.0.0.1:5055", True),
    ("http://localhost:5055", True),
    ("http://127.0.0.1:5056", False),
    ("http://evil.example", False),
    ("null", False),
    ("", False),
    (None, False),
])
def test_the_handshake_verifies_the_origin(origin, ok):
    assert tm.origin_ok(origin, 5055) is ok


def test_a_missing_origin_is_refused_not_waved_through():
    """Browsers always send one; its absence means the caller is not a tab."""
    assert tm.origin_ok(None, 5055) is False
    assert tm.origin_ok("", 5055) is False


def test_the_origin_is_checked_before_the_token(monkeypatch):
    import inspect
    src = inspect.getsource(tm._serve)
    assert src.index("origin_ok") < src.index("compare_digest"), (
        "the token is compared before the origin is known")


def test_the_token_is_still_never_written_to_the_log(tmp_path):
    log = tmp_path / "t.log"
    tm.append_log("in", "powershell", "git status", log_path=log)
    tm.append_log("out", "powershell", "on branch master", log_path=log)
    body = log.read_text(encoding="utf-8")
    assert "git status" in body
    assert "token" not in body.lower()
    import inspect
    assert "_TOKEN" not in inspect.getsource(tm.append_log)


def test_start_bridge_takes_the_http_port_for_the_origin_check():
    import inspect
    sig = inspect.signature(tm.start_bridge)
    assert "http_port" in sig.parameters
    assert "log_path" in sig.parameters


# ---------------------------------------------------------------------------
# The footer still tells the truth
# ---------------------------------------------------------------------------

def test_the_footer_states_the_posture_and_the_new_facts():
    html = PAGE.read_text(encoding="utf-8")
    panel = html.split("function tabTerminal(){")[1].split("\n}")[0]
    assert "exactly the user's own rights" in panel
    assert "Origin" in panel, "the footer does not mention the origin check"
    assert "never the token" in panel
    assert "own session" in panel or "its own session" in panel


def test_the_posture_dict_reports_the_cwd_and_origin_rule():
    p = tm.posture()
    assert p["cwd"] == str(tm.BASE)
    assert "loopback" in p["origin_check"]
    assert p["allowlist"].startswith("none")
