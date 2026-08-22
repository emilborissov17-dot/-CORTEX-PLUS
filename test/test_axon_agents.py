#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_axon_agents.py — THE SWEEP, WITH THE NETWORK TAKEN AWAY.

ZERO NETWORK, ZERO MODEL, ZERO LIVE STATE. Every fetch goes through a fake
session that serves bytes from test/fixtures/axon/, every path is a tmp_path,
and a test at the bottom asserts the module reaches no LLM at all — the same
promise scripts/intel_daemon.py makes about itself, asserted the same way.

WHAT IS PINNED HERE
--------------------
  registry      three role files -> three agents, and a broken one stops the build
  ordering      THREAT before WATCH before NORMAL, ties by axis name
  url required  a row without a link is REFUSED, and the refusal is counted
  RSS delta     dated items by pubDate, undated items by a bounded url ring
  caps          the two constants are the daemon's OBJECTS, not copies of them
  allowlist     an off-list feed opens no socket at all
  intake        rows land as CANDIDATE and nothing moves on the trust ladder

    venv/Scripts/python.exe -m pytest test/test_axon_agents.py -v
"""
from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import axon_agents as ax  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "axon"
ROLES = REPO / "config" / "axon_roles"

BASIC = (FIXTURES / "feed_basic.xml").read_bytes()
NOTXML = (FIXTURES / "feed_notxml.xml").read_bytes()


# ---------------------------------------------------------------------------
# The fake session — the only thing standing in for the network
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.body, self.status = body, status
        self.content = self

    async def iter_chunked(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Serves one body for every url, and remembers which urls were asked for."""

    def __init__(self, body: bytes = BASIC, status: int = 200, per_url=None):
        self.body, self.status, self.per_url = body, status, per_url or {}
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url in self.per_url:
            body, status = self.per_url[url]
            return FakeResponse(body, status)
        return FakeResponse(self.body, self.status)

    async def close(self):
        pass


def _module_ast():
    return ast.parse((REPO / "core" / "axon_agents.py").read_text(encoding="utf-8"))


def _imported_modules() -> set:
    """Every module name core/axon_agents.py imports, from the AST."""
    names = set()
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def role_for(slug: str, **overrides) -> dict:
    role = ax.load_role(ROLES / (slug + ".json"))
    role.update(overrides)
    return role


def agent_for(slug: str, last_sweep_ts=None, **overrides) -> ax.AxonAgent:
    role = role_for(slug, **overrides)
    a = ax.AxonAgent(axis=role["axis"], role_config=role,
                     last_sweep_ts=last_sweep_ts)
    a.reset_stats()
    return a


# ---------------------------------------------------------------------------
# Caps: inherited objects, not copied numbers
# ---------------------------------------------------------------------------

def test_the_caps_are_the_daemons_own_objects():
    """A copied constant drifts. intel_daemon's docstring says those two numbers
    change 'here, in a commit, with a reason' — a second copy makes that untrue
    the first time somebody edits one."""
    from scripts import intel_daemon as d
    assert ax.MAX_CONTENT_BYTES is d.MAX_CONTENT_BYTES
    assert ax.STREAM_TIMEOUT_SEC is d.STREAM_TIMEOUT_SEC
    assert ax.MAX_CONTENT_BYTES == 1024 * 1024
    assert ax.STREAM_TIMEOUT_SEC == 15


def test_the_caps_are_not_restated_as_literals_in_this_module():
    src = (REPO / "core" / "axon_agents.py").read_text(encoding="utf-8")
    assert "from scripts.intel_daemon import MAX_CONTENT_BYTES" in src
    assert "MAX_CONTENT_BYTES = " not in src, "the cap was copied instead of imported"


def test_the_connection_cap_is_three():
    assert ax.MAX_CONNECTIONS == 3


def test_the_session_carries_both_caps(monkeypatch):
    """The session is where the caps become real, so assert they arrive there."""
    seen = {}

    class FakeAiohttp:
        @staticmethod
        def TCPConnector(**kw):
            seen["connector"] = kw
            return "connector"

        @staticmethod
        def ClientTimeout(**kw):
            seen["timeout"] = kw
            return "timeout"

        @staticmethod
        def ClientSession(**kw):
            seen["session"] = kw
            return "session"

    ax.make_session(aiohttp_mod=FakeAiohttp)
    assert seen["connector"]["limit"] == ax.MAX_CONNECTIONS
    assert seen["timeout"]["total"] == ax.STREAM_TIMEOUT_SEC


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def test_the_registry_builds_one_agent_per_role_file(tmp_path):
    agents = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})
    assert len(agents) == 3
    assert {a.axis for a in agents} == {
        "LONG_TERM_FUTURE_REVIEW", "TECHNOLOGY_AI_REVIEW", "CULTURE_MEDIA_REVIEW"}
    for a in agents:
        assert isinstance(a, ax.AxonAgent)
        assert a.memory_budget_mb == ax.MEMORY_BUDGET_MB


def test_an_agent_is_a_plain_object_with_the_four_named_fields(tmp_path):
    a = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})[0]
    for field in ("axis", "role_config", "last_sweep_ts", "memory_budget_mb"):
        assert hasattr(a, field)
    assert not hasattr(a, "run"), "an agent with a run loop is a process in disguise"
    assert not hasattr(a, "start")


def test_an_empty_role_directory_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(ax.RoleError):
        ax.build_registry(roles_dir=tmp_path / "empty")


def test_two_role_files_claiming_one_axis_are_refused(tmp_path):
    blob = (ROLES / "technology_ai.json").read_text(encoding="utf-8")
    (tmp_path / "a.json").write_text(blob, encoding="utf-8")
    (tmp_path / "b.json").write_text(blob, encoding="utf-8")
    with pytest.raises(ax.RoleError) as e:
        ax.build_registry(roles_dir=tmp_path, state_path=tmp_path / "s.json",
                          orchestration={})
    assert "claim axis" in str(e.value)


def test_last_sweep_ts_is_restored_from_state(tmp_path):
    st = tmp_path / "s.json"
    st.write_text(json.dumps(
        {"TECHNOLOGY_AI_REVIEW": {"last_sweep_ts": "2026-08-01T00:00:00+00:00"}}),
        encoding="utf-8")
    agents = ax.build_registry(state_path=st, orchestration={})
    tech = next(a for a in agents if a.axis == "TECHNOLOGY_AI_REVIEW")
    assert tech.last_sweep_ts == "2026-08-01T00:00:00+00:00"
    others = [a for a in agents if a.axis != "TECHNOLOGY_AI_REVIEW"]
    assert all(a.last_sweep_ts is None for a in others)


# ---------------------------------------------------------------------------
# Ordering — THREAT before WATCH before NORMAL
# ---------------------------------------------------------------------------

ORCH = {"sets": {"THREAT": ["TECHNOLOGY_AI_REVIEW"],
                 "WATCH": ["CULTURE_MEDIA_REVIEW"],
                 "OPPORTUNITY": ["LONG_TERM_FUTURE_REVIEW"]}}


def test_threat_runs_before_watch_before_normal(tmp_path):
    agents = ax.build_registry(state_path=tmp_path / "s.json", orchestration=ORCH)
    assert [a.axis for a in agents] == [
        "TECHNOLOGY_AI_REVIEW",       # THREAT
        "CULTURE_MEDIA_REVIEW",       # WATCH
        "LONG_TERM_FUTURE_REVIEW",    # OPPORTUNITY -> NORMAL
    ]


def test_opportunity_maps_to_normal_and_the_mapping_is_deliberate():
    """orchestrator_grounded emits THREAT / OPPORTUNITY / WATCH — three buckets,
    but not these three. OPPORTUNITY means 'not measured yet', which is a gap in
    coverage, not an alarm."""
    assert ax.alert_state("LONG_TERM_FUTURE_REVIEW", ORCH) == ax.NORMAL
    assert ax.alert_state("TECHNOLOGY_AI_REVIEW", ORCH) == ax.THREAT
    assert ax.alert_state("CULTURE_MEDIA_REVIEW", ORCH) == ax.WATCH


def test_an_unclassified_axis_is_normal():
    assert ax.alert_state("SOMETHING_NOBODY_CLASSIFIED", ORCH) == ax.NORMAL
    assert ax.alert_state("ANYTHING", {}) == ax.NORMAL


def test_ties_are_broken_by_axis_name_so_a_sweep_is_reproducible(tmp_path):
    agents = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})
    names = [a.axis for a in agents]
    assert names == sorted(names)
    again = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})
    assert [a.axis for a in again] == names


def test_ordering_survives_a_missing_orchestration_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ax, "ORCHESTRATION", tmp_path / "nope.json")
    agents = ax.build_registry(state_path=tmp_path / "s.json")
    assert len(agents) == 3


# ---------------------------------------------------------------------------
# The url guard and the allowlist
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,allowed", [
    ("https://example.com/a", ["example.com"]),
    ("https://rss.example.com/a", ["example.com"]),
    ("http://export.arxiv.org/rss/cs.AI", ["arxiv.org"]),
])
def test_an_on_list_url_is_allowed(url, allowed):
    assert ax._refuse_url(url, allowed) is None


@pytest.mark.parametrize("url,allowed,why", [
    ("https://evil-example.com/a", ["example.com"], "lookalike domain"),
    ("https://elsewhere.org/a", ["example.com"], "off the allowlist"),
    ("file:///etc/passwd", ["etc"], "non-http scheme"),
    ("ftp://example.com/a", ["example.com"], "non-http scheme"),
    ("http://127.0.0.1/a", ["127.0.0.1"], "loopback"),
    ("http://10.0.0.5/a", ["10.0.0.5"], "rfc1918"),
    ("http://169.254.169.254/latest", ["169.254.169.254"], "link-local metadata"),
    ("http://localhost/a", ["localhost"], "loopback name"),
    ("http://printer.local/a", ["printer.local"], "mdns"),
    ("https://user:pw@example.com/a", ["example.com"], "credentials in netloc"),
])
def test_a_refused_url_is_refused_for_the_right_reason(url, allowed, why):
    assert ax._refuse_url(url, allowed) is not None, why


def test_an_off_allowlist_feed_opens_no_socket_at_all():
    agent = agent_for("technology_ai", feeds=["https://elsewhere.example/rss"])
    session = FakeSession()
    asyncio.run(ax.sweep_agent(agent, session, intake_path=None,
                               lifecycle_state_path=None, seen_rings={}))
    assert session.calls == [], "a socket was opened to an off-allowlist host"
    assert agent.stats["refused_domain"] == 1
    assert agent.stats["candidates"] == 0


def test_an_empty_allowlist_refuses_everything():
    assert ax._refuse_url("https://example.com/a", []) is not None


# ---------------------------------------------------------------------------
# The size cap
# ---------------------------------------------------------------------------

def test_a_response_over_the_cap_is_discarded_not_truncated():
    big = b"<rss><channel>" + b"x" * (ax.MAX_CONTENT_BYTES + 10) + b"</channel></rss>"
    session = FakeSession(body=big)
    body, reason = asyncio.run(
        ax.fetch(session, "https://feeds.bbci.co.uk/a", ["bbci.co.uk"]))
    assert body is None
    assert "cap" in reason


def test_a_non_200_is_a_refusal_not_an_empty_feed():
    session = FakeSession(status=503)
    body, reason = asyncio.run(
        ax.fetch(session, "https://feeds.bbci.co.uk/a", ["bbci.co.uk"]))
    assert body is None and "503" in reason


# ---------------------------------------------------------------------------
# Parsing and the RSS delta
# ---------------------------------------------------------------------------

def test_the_parser_strips_markup_and_skips_untitled_items():
    items = asyncio.run(ax.parse_rss_items(BASIC, 20))
    assert len(items) == 4, "the untitled item should not become a row"
    first = items[0]
    assert "<b>" not in first["claim_text"] and "stripped" in first["claim_text"]


def test_html_where_xml_was_expected_yields_nothing_and_does_not_raise():
    assert asyncio.run(ax.parse_rss_items(NOTXML, 8)) == []
    assert asyncio.run(ax.parse_rss_items(b"", 8)) == []


def test_max_items_bounds_the_parse():
    assert len(asyncio.run(ax.parse_rss_items(BASIC, 2))) == 2


def test_the_first_sweep_takes_everything():
    items = asyncio.run(ax.parse_rss_items(BASIC, 20))
    assert len(ax.select_new(items, None, [])) == len(items)


def test_a_dated_item_older_than_the_last_sweep_is_not_new():
    items = asyncio.run(ax.parse_rss_items(BASIC, 20))
    fresh = ax.select_new(items, "2026-08-20T00:00:00+00:00", [])
    titles = [i["title"] for i in fresh]
    assert "Old item from before the last sweep" not in titles
    assert "New item after the last sweep" in titles


def test_an_undated_item_is_new_once_and_then_remembered():
    items = asyncio.run(ax.parse_rss_items(BASIC, 20))
    fresh = ax.select_new(items, "2026-08-20T00:00:00+00:00", [])
    assert "Undated item" in [i["title"] for i in fresh]
    ring = ["https://feeds.bbci.co.uk/a/undated"]
    again = ax.select_new(items, "2026-08-20T00:00:00+00:00", ring)
    assert "Undated item" not in [i["title"] for i in again], (
        "an undated item with no ring entry re-reports every sweep forever")


def test_the_url_ring_is_bounded(tmp_path):
    """A memory, not an archive."""
    assert ax.SEEN_RING == 50
    agent = agent_for("technology_ai")
    rings = {}
    for _ in range(3):
        agent.last_sweep_ts = None
        asyncio.run(ax.sweep_agent(agent, FakeSession(),
                                   intake_path=tmp_path / "c.jsonl",
                                   lifecycle_state_path=tmp_path / "l.json",
                                   seen_rings=rings))
    for feed, ring in rings.items():
        assert len(ring) <= ax.SEEN_RING


def test_an_unparseable_pub_date_does_not_raise():
    assert ax.parse_pub_date("not a date") is None
    assert ax.parse_pub_date("") is None
    assert ax.parse_pub_date(None) is None


# ---------------------------------------------------------------------------
# A row needs a link. This is the one that is allowed to be loud.
# ---------------------------------------------------------------------------

def test_a_row_without_a_url_is_refused_by_exception():
    from scripts.intel_daemon import LinkRequired
    with pytest.raises(LinkRequired):
        ax.to_candidate_row("TECHNOLOGY_AI_REVIEW",
                            {"title": "no link", "claim_text": "x"})


def test_the_refusal_is_the_daemons_exception_not_a_second_one():
    """One rule, in one place: a finding whose source cannot be opened is not a
    finding."""
    from scripts import intel_daemon as d
    src = (REPO / "core" / "axon_agents.py").read_text(encoding="utf-8")
    assert "from scripts.intel_daemon import LinkRequired" in src
    assert ax.LinkRequired is d.LinkRequired


@pytest.mark.parametrize("url", ["", "   ", None])
def test_every_flavour_of_missing_url_is_refused(url):
    from scripts.intel_daemon import LinkRequired
    with pytest.raises(LinkRequired):
        ax.to_candidate_row("A", {"title": "t", "url": url})


def test_a_linkless_item_is_counted_not_silently_dropped(tmp_path):
    agent = agent_for("technology_ai",
                      feeds=["https://feeds.bbci.co.uk/news/technology/rss.xml"],
                      last_sweep_ts=None)
    asyncio.run(ax.sweep_agent(
        agent, FakeSession(), intake_path=tmp_path / "c.jsonl",
        lifecycle_state_path=tmp_path / "l.json", seen_rings={}))
    assert agent.stats["no_url"] == 1, (
        "the linkless fixture item vanished without being counted — a low row "
        "count would then be indistinguishable from a quiet feed")
    assert agent.stats["candidates"] == 3


def test_every_written_row_has_a_url(tmp_path):
    agent = agent_for("technology_ai", last_sweep_ts=None)
    asyncio.run(ax.sweep_agent(
        agent, FakeSession(), intake_path=tmp_path / "c.jsonl",
        lifecycle_state_path=tmp_path / "l.json", seen_rings={}))
    rows = [json.loads(l) for l in
            (tmp_path / "c.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    assert all(r["url"].strip() for r in rows)


# ---------------------------------------------------------------------------
# The CANDIDATE intake
# ---------------------------------------------------------------------------

def test_a_row_carries_exactly_the_agreed_shape():
    row = ax.to_candidate_row("TECHNOLOGY_AI_REVIEW", {
        "title": "t", "claim_text": "c", "url": "https://x.example/a",
        "pub_date": "Fri, 21 Aug 2026 18:30:00 GMT"})
    assert set(row) == {"axis", "url", "title", "claim_text", "ts", "seen_at"}
    assert row["ts"].startswith("2026-08-21")


def test_the_intake_registers_the_source_as_candidate(tmp_path):
    life = tmp_path / "life.json"
    ax.write_candidates(
        [{"axis": "A", "url": "https://x.example/1", "title": "t",
          "claim_text": "c", "ts": "2026-08-21T00:00:00+00:00",
          "seen_at": "2026-08-21T00:00:00+00:00"}],
        source_id="https://x.example/feed", axis="A",
        intake_path=tmp_path / "c.jsonl", lifecycle_state_path=life)
    state = json.loads(life.read_text(encoding="utf-8"))
    rec = state["https://x.example/feed"]
    assert rec["state"] == "CANDIDATE"


def test_the_intake_moves_nothing_on_the_trust_ladder(tmp_path):
    """'This feed returned some XML' is not evidence that its claims are true.
    Five clean observations promote a source; the intake must make none."""
    life = tmp_path / "life.json"
    row = {"axis": "A", "url": "https://x.example/1", "title": "t",
           "claim_text": "c", "ts": "t", "seen_at": "t"}
    for _ in range(10):
        ax.write_candidates([row], source_id="https://x.example/feed", axis="A",
                            intake_path=tmp_path / "c.jsonl",
                            lifecycle_state_path=life)
    rec = json.loads(life.read_text(encoding="utf-8"))["https://x.example/feed"]
    assert rec["state"] == "CANDIDATE"
    assert rec["clean_streak"] == 0
    assert rec["observations"] == 0
    assert rec["contradictions"] == 0


def test_the_intake_is_append_only_across_sweeps(tmp_path):
    intake = tmp_path / "c.jsonl"
    row = {"axis": "A", "url": "https://x.example/1", "title": "t",
           "claim_text": "c", "ts": "t", "seen_at": "t"}
    ax.write_candidates([row], "s", "A", intake_path=intake,
                        lifecycle_state_path=tmp_path / "l.json")
    ax.write_candidates([row], "s", "A", intake_path=intake,
                        lifecycle_state_path=tmp_path / "l.json")
    assert len(intake.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_writing_no_rows_writes_no_file(tmp_path):
    intake = tmp_path / "c.jsonl"
    assert ax.write_candidates([], "s", "A", intake_path=intake,
                               lifecycle_state_path=tmp_path / "l.json") == 0
    assert not intake.exists()


# ---------------------------------------------------------------------------
# A whole sweep
# ---------------------------------------------------------------------------

def test_a_sweep_is_sequential_and_in_order(tmp_path):
    agents = ax.build_registry(state_path=tmp_path / "s.json", orchestration=ORCH)
    session = FakeSession()
    result = asyncio.run(ax.sweep(
        agents, session=session, intake_path=tmp_path / "c.jsonl",
        lifecycle_state_path=tmp_path / "l.json", state_path=tmp_path / "s.json"))
    assert result["ran"] == ["TECHNOLOGY_AI_REVIEW", "CULTURE_MEDIA_REVIEW",
                             "LONG_TERM_FUTURE_REVIEW"]
    # every feed of agent 1 was fetched before any feed of agent 2
    first_feeds = set(agents[0].feeds)
    idx = [i for i, u in enumerate(session.calls) if u in first_feeds]
    assert idx == list(range(len(first_feeds)))


def test_a_second_sweep_finds_nothing_new(tmp_path):
    agents = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})
    asyncio.run(ax.sweep(agents, session=FakeSession(),
                         intake_path=tmp_path / "c.jsonl",
                         lifecycle_state_path=tmp_path / "l.json",
                         state_path=tmp_path / "s.json"))
    agents2 = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})
    asyncio.run(ax.sweep(agents2, session=FakeSession(),
                         intake_path=tmp_path / "c.jsonl",
                         lifecycle_state_path=tmp_path / "l.json",
                         state_path=tmp_path / "s.json"))
    assert sum(a.stats["candidates"] for a in agents2) == 0


def test_the_wall_cap_stops_the_next_agent_not_the_running_one(tmp_path):
    agents = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})
    result = asyncio.run(ax.sweep(
        agents, session=FakeSession(), intake_path=tmp_path / "c.jsonl",
        lifecycle_state_path=tmp_path / "l.json", state_path=tmp_path / "s.json",
        wall_cap_sec=0.0))
    assert result["ran"] == []
    assert len(result["skipped"]) == 3


def test_a_skipped_agent_does_not_get_a_last_sweep_ts(tmp_path):
    """A last_sweep_ts is a claim to have looked. An agent the wall cap stopped
    did not look, and next sweep must not treat its window as covered."""
    agents = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})
    asyncio.run(ax.sweep(
        agents, session=FakeSession(), intake_path=tmp_path / "c.jsonl",
        lifecycle_state_path=tmp_path / "l.json", state_path=tmp_path / "s.json",
        wall_cap_sec=0.0))
    state = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert [k for k in state if not k.startswith("_")] == []


# ---------------------------------------------------------------------------
# The heartbeat: one line, and not into the live cycle's file
# ---------------------------------------------------------------------------

def test_a_sweep_emits_exactly_one_line(tmp_path):
    agents = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})
    lines = []
    asyncio.run(ax.sweep(agents, session=FakeSession(),
                         intake_path=tmp_path / "c.jsonl",
                         lifecycle_state_path=tmp_path / "l.json",
                         state_path=tmp_path / "s.json",
                         heartbeat_sink=lines.append))
    assert len(lines) == 1, "one sweep must be one line, not one line per agent"
    assert "3 agent(s)" in lines[0]


def test_the_batch_line_totals_every_agent(tmp_path):
    agents = ax.build_registry(state_path=tmp_path / "s.json", orchestration={})
    for a in agents:
        a.stats = {"seen": 2, "new": 1, "candidates": 1, "bytes": 1024}
    line = ax.batch_line(agents, 1.0)
    assert "seen 6" in line and "new 3" in line and "candidates 3" in line


def test_the_sweep_never_touches_the_live_heartbeat():
    """beat() writes memory/heartbeat.json, which a LIVE cycle owns and the
    supervisor reads to decide whether that cycle is wedged."""
    # Asserted over the AST, not the text: the module's docstring EXPLAINS why
    # it does not wire the heartbeat, so a substring search for "memory.heartbeat"
    # matches the explanation and fails on prose rather than on behaviour.
    for name in _imported_modules():
        assert not name.startswith("memory.heartbeat"), (
            "axon imports the live cycle's heartbeat")
        assert name != "memory", "axon imports the memory package"
    # emit_heartbeat() takes its sink as an argument and defaults to print.
    import inspect
    assert "sink or print" in inspect.getsource(ax.emit_heartbeat)


# ---------------------------------------------------------------------------
# The promises this module makes about itself
# ---------------------------------------------------------------------------

def test_the_module_reaches_no_model():
    """Same promise scripts/intel_daemon.py makes, asserted the same way.

    IN A SUBPROCESS, and that detail is the test. Asserting over this process's
    sys.modules would pass or fail on which OTHER test file pytest imported
    first — core.brain is in sys.modules by the time this file runs, put there
    by somebody else. A promise about what a module PULLS IN can only be checked
    in an interpreter that has imported nothing else.
    """
    import subprocess
    probe = (
        "import sys; sys.path.insert(0, r'{}');"
        "import core.axon_agents;"
        "bad=[m for m in sys.modules if m.startswith(("
        "'core.groq_backend','core.llm_backend','core.brain','ollama','openai'))];"
        "print(','.join(bad))".format(REPO)
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                         text=True, timeout=120, cwd=str(REPO))
    assert out.returncode == 0, out.stderr
    loaded = out.stdout.strip()
    assert loaded == "", "importing axon pulled in an LLM module: {}".format(loaded)


def test_the_module_issues_no_verb_but_get():
    src = (REPO / "core" / "axon_agents.py").read_text(encoding="utf-8")
    for verb in (".post(", ".put(", ".delete(", ".patch(", ".head("):
        assert verb not in src, "axon issued {}: it senses, it does not act".format(verb)
    assert "session.get(" in src


def test_one_semaphore_shared_by_all_agents():
    assert isinstance(ax.HEAVY, asyncio.Semaphore)
    src = (REPO / "core" / "axon_agents.py").read_text(encoding="utf-8")
    # Over the AST: the selftest PRINTS the string "asyncio.Semaphore(1)" in its
    # report, and a text count would score that as a second gate.
    made = [n for n in ast.walk(_module_ast())
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "Semaphore"]
    assert len(made) == 1, "a second semaphore is a second policy"
    assert "async with HEAVY" in src, "the gate exists but nothing takes it"


def test_the_memory_budget_is_twenty_mb_per_agent():
    assert ax.MEMORY_BUDGET_MB == 20.0


def test_the_wall_cap_is_ten_minutes():
    assert ax.WALL_CAP_SEC == 600.0
