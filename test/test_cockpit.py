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


def test_cycles_marks_done_current_and_todo(client):
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


def test_exactly_two_flask_post_routes_and_they_are_the_declared_ones():
    posts = sorted(str(r) for r in srv.app.url_map.iter_rules()
                   if "POST" in r.methods)
    assert posts == ["/api/ask", "/api/expression/seen"]
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


def test_mic_and_camera_are_off_by_default():
    r = som.probe()
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
