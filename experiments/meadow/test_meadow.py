"""Permanent test suite for the meadow — the mechanics, never the thought.

WHAT THESE TESTS MAY AND MAY NOT DO
-----------------------------------
They test that the SLICE is built correctly (raw, wide, rotated, honest about empty
sources), that the notebook is written VERBATIM and APPEND-ONLY, that COMMIT parses a
hypothesis or an honest 'none', and that isolation holds (writes only under the meadow,
imports no live pipeline).

They must NEVER assert anything about the QUALITY of the DIVERGE text. There is no
check.py for the meadow and there must never be one; a test that graded the notebook
would be exactly the judgement the meadow exists to be free of. So the LLM is a fake
that returns canned strings, and the tests only ever check that those strings are
routed and stored faithfully — not whether they are any good.
"""
import ast
import json
from pathlib import Path

import pytest

import meadow as md


# ---------------------------------------------------------------------------
# A throwaway fake-repo with a little of every real source
# ---------------------------------------------------------------------------

@pytest.fixture
def fake(tmp_path):
    """Build a minimal but real-shaped repo slice under tmp, and Sources pointing at
    it. Nothing here touches the real repo's news/, snapshots/, memory/ or output/."""
    (tmp_path / "news").mkdir()
    (tmp_path / "news" / "news_latest.json").write_text(json.dumps({
        "date": "2026-07-14",
        "results": {
            "TECHNOLOGY_AI_REVIEW": {
                "sources_count": {"rss": 2},          # a counts dict — must be ignored
                "rss": [
                    {"title": "AI model beats benchmark", "snippet": "A new model...",
                     "url": "http://x/1", "source": "RSS"},
                    {"title": "Chip shortage eases", "snippet": "Supply improves...",
                     "url": "http://x/2", "source": "RSS"},
                ],
                "arxiv": [{"title": "On scaling laws", "summary": "We study...",
                           "url": "http://arxiv/1", "source": "arXiv"}],
            },
            "WATER_REVIEW": {
                "rss": [{"title": "Drought widens", "snippet": "Reservoirs low...",
                         "url": "http://x/3", "source": "RSS"},
                        {"title": "AI model beats benchmark", "snippet": "dup title",
                         "url": "http://x/dup", "source": "RSS"}],  # duplicate title
            },
        },
    }), encoding="utf-8")

    tc = tmp_path / "memory" / "transcript_cache"
    tc.mkdir(parents=True)
    (tc / "old.json").write_text(json.dumps({
        "video_id": "OLD", "transcript": "an older transcript", "cached_at": "2026-07-10T00:00:00Z",
        "transcript_method": "web"}), encoding="utf-8")
    (tc / "new.json").write_text(json.dumps({
        "video_id": "NEW", "transcript": "the newest transcript about hunger",
        "cached_at": "2026-07-14T08:00:00Z", "transcript_method": "web"}), encoding="utf-8")

    out = tmp_path / "output"
    (out / "wb_cache").mkdir(parents=True)
    (out / "wellbeing_all_countries.json").write_text(json.dumps({
        "countries": [
            {"iso2": "AT", "name": "Austria", "region": "ECS", "income": "HIC",
             "zone": "Dignified Life", "flourishing": 0.87, "deprivation": 0.13,
             "strain": 0.30, "confidence": "MEDIUM", "completeness": "16/17 real"},
            {"iso2": "KE", "name": "Kenya", "region": "SSA", "income": "LMC",
             "zone": "Strained", "flourishing": 0.41, "deprivation": 0.55,
             "strain": 0.62, "confidence": "LOW", "completeness": "9/17 real"},
        ],
    }), encoding="utf-8")
    (out / "wb_cache" / "AT.json").write_text(json.dumps({
        "raw": {"SP.DYN.LE00.IN": 81.9, "SI.POV.GINI": 31.2, "EN.ATM.CO2E.PC": None,
                "IT.NET.USER.ZS": 91.9, "ZZ.UNKNOWN.CODE": 5}}), encoding="utf-8")

    snaps = tmp_path / "snapshots"
    # REAL_DATA, shape A (direct metrics)
    d = snaps / "planet" / "energy"; d.mkdir(parents=True)
    (d / "energy_snapshot_latest.json").write_text(json.dumps({
        "axis": "ENERGY_REVIEW", "source_type": "REAL_DATA", "data_quality": "REAL_WB",
        "metrics": {"renewable_energy_pct": 29.5, "access_to_electricity_pct": 90.1}}),
        encoding="utf-8")
    # REAL_DATA, shape B (nested metrics under metrics.metrics)
    d2 = snaps / "civilization" / "economy_work"; d2.mkdir(parents=True)
    (d2 / "economy_work_snapshot_latest.json").write_text(json.dumps({
        "axis": "ECONOMY_WORK_REVIEW", "source_type": "REAL_DATA",
        "metrics": {"axis": "ECONOMY_WORK_REVIEW", "source": "WB", "data_quality": "6/7",
                    "metrics": {"gdp_growth_pct": 1.2, "unemployment_pct": 5.6}}}),
        encoding="utf-8")
    # LLM_GENERATED — must be EXCLUDED from the REAL_DATA summary
    d3 = snaps / "cosmos" / "long_term_future"; d3.mkdir(parents=True)
    (d3 / "long_term_future_snapshot_latest.json").write_text(json.dumps({
        "axis": "LONG_TERM_FUTURE_REVIEW", "source_type": "LLM_GENERATED",
        "metrics": {}}), encoding="utf-8")

    mem = tmp_path / "memory"
    (mem / "goal_score_history.json").write_text(json.dumps([
        {"timestamp": "2026-07-12T03:00:00+00:00",
         "scores": {"ENERGY_REVIEW": 58.0, "LONG_TERM_FUTURE_REVIEW": 44.0}},
        {"timestamp": "2026-07-13T03:00:00+00:00",
         "scores": {"ENERGY_REVIEW": 60.0, "ECONOMY_WORK_REVIEW": 51.0,
                    "LONG_TERM_FUTURE_REVIEW": 45.0}},
    ]), encoding="utf-8")
    (mem / "existence_ledger.jsonl").write_text(
        json.dumps({"seq": 1, "ts": "2026-07-14T06:00:00+00:00", "event": "CYCLE_STARTED",
                    "cycle_id": "c1", "trigger": "CATCHUP"}) + "\n" +
        json.dumps({"seq": 2, "ts": "2026-07-14T06:20:00+00:00", "event": "CYCLE_DIED",
                    "cycle_id": "c1", "last_step": "web_intelligence"}) + "\n" +
        json.dumps({"seq": 3, "ts": "2026-01-01T00:00:00+00:00", "event": "CYCLE_STARTED",
                    "cycle_id": "old"}) + "\n",              # far outside the window
        encoding="utf-8")
    (mem / "cycle_logs").mkdir()

    return md.Sources(
        news_latest=tmp_path / "news" / "news_latest.json",
        snapshots_dir=snaps,
        goal_history=mem / "goal_score_history.json",
        ledger_file=mem / "existence_ledger.jsonl",
        cycle_log_dir=mem / "cycle_logs",
        transcript_cache=tc,
        countries_file=out / "wellbeing_all_countries.json",
        wb_cache_dir=out / "wb_cache",
        notebook_dir=tmp_path / "meadow_out" / "notebook",
        committed_dir=tmp_path / "meadow_out" / "committed",
    )


DAY = "2026-07-14"


def fake_llm(diverge_text="I notice hunger in the transcript and the drought news.",
             commit_text='NONE'):
    """A stand-in brain. Returns diverge_text for the DIVERGE call and commit_text for
    the COMMIT call, told apart by a marker only the COMMIT prompt contains."""
    def _llm(prompt, max_tokens=1024):
        return commit_text if "YOUR NOTEBOOK ENTRY" in prompt else diverge_text
    return _llm


# ---------------------------------------------------------------------------
# (a) NEWS — flattened, deduped, unfiltered
# ---------------------------------------------------------------------------

def test_news_flattens_all_axes_and_sources(fake):
    import random
    items = md.gather_news(fake, random.Random(1), n=20)
    titles = {i["title"] for i in items}
    assert "AI model beats benchmark" in titles
    assert "On scaling laws" in titles       # arxiv list, different source key
    assert "Drought widens" in titles        # a different axis entirely


def test_news_dedupes_by_title_and_ignores_count_dicts(fake):
    import random
    items = md.gather_news(fake, random.Random(1), n=20)
    titles = [i["title"] for i in items]
    assert titles.count("AI model beats benchmark") == 1, "duplicate title not deduped"
    # sources_count is a dict of ints, not items — it must not become news.
    assert all(isinstance(i["title"], str) and i["title"] for i in items)


# ---------------------------------------------------------------------------
# (b) TRANSCRIPTS — newest first, verbatim
# ---------------------------------------------------------------------------

def test_transcripts_take_the_newest_first(fake):
    recs = md.gather_transcripts(fake, n=1)
    assert len(recs) == 1
    assert recs[0]["video_id"] == "NEW", "did not pick the newest by cached_at"


# ---------------------------------------------------------------------------
# (c) COUNTRIES — rotated, per-country raw indicators, labels mapped
# ---------------------------------------------------------------------------

def test_countries_attach_labelled_raw_indicators(fake):
    import random
    rows = md.gather_countries(fake, random.Random(0), n=2, k_ind=9)
    at = [r for r in rows if r["country"]["iso2"] == "AT"][0]
    labels = at["indicators"]
    assert "Life expectancy yr" in labels, "known WB code was not mapped to its label"
    assert "ZZ.UNKNOWN.CODE" in labels, "an unmapped code must be shown raw, not dropped"
    assert None not in labels.values(), "a null indicator must be filtered out"
    assert "CO2 per capita tons" not in labels, "the null CO2 value must not appear"


def test_country_rotation_is_deterministic_per_seed(fake):
    b1, _ = md.assemble_bundle(fake, DAY)
    b2, _ = md.assemble_bundle(fake, DAY)
    assert b1 == b2, "same day must draw the same slice (seed is the date)"


# ---------------------------------------------------------------------------
# (d) REAL_DATA axis summary — both shapes, LLM excluded
# ---------------------------------------------------------------------------

def test_real_axes_normalises_both_snapshot_shapes(fake):
    axes = md.real_data_axes(fake)
    assert axes["ENERGY_REVIEW"]["metrics"]["renewable_energy_pct"] == 29.5      # shape A
    assert axes["ECONOMY_WORK_REVIEW"]["metrics"]["gdp_growth_pct"] == 1.2       # shape B
    # Shape B's wrapper keys must not leak into the real metrics.
    assert "source" not in axes["ECONOMY_WORK_REVIEW"]["metrics"]


def test_llm_generated_axes_are_excluded_from_the_summary(fake):
    axes = md.real_data_axes(fake)
    assert "LONG_TERM_FUTURE_REVIEW" not in axes, "an LLM_GENERATED axis leaked into (d)"


def test_axis_history_is_filtered_to_real_axes(fake):
    axes = md.real_data_axes(fake)
    traj = md.axis_history(fake, set(axes))
    assert traj["ENERGY_REVIEW"] == [58.0, 60.0]
    assert "LONG_TERM_FUTURE_REVIEW" not in traj, "LLM axis trajectory must not appear"


# ---------------------------------------------------------------------------
# (e) DIARY — own ledger, windowed, verbatim
# ---------------------------------------------------------------------------

def test_diary_windows_to_today_and_yesterday_and_flags_death(fake):
    diary = md.gather_diary(fake, DAY)
    evseq = [e["seq"] for e in diary["events"]]
    assert 1 in evseq and 2 in evseq, "in-window events missing"
    assert 3 not in evseq, "an event far outside the window leaked in"
    assert len(diary["deaths"]) == 1, "the CYCLE_DIED in the window was not flagged"


# ---------------------------------------------------------------------------
# The bundle — labelled, honest about empty sources
# ---------------------------------------------------------------------------

def test_bundle_labels_each_section_and_marks_the_predigested_one(fake):
    bundle, meta = md.assemble_bundle(fake, DAY)
    assert "(a) NEWS, raw" in bundle
    assert "(b) TRANSCRIPTS, raw" in bundle
    assert "(c) COUNTRIES" in bundle
    assert "already digested by you" in bundle, "the pre-digested part must be labelled"
    assert "(e) YOUR OWN DAY" in bundle
    assert meta["seed"] == int(DAY.replace("-", ""))


def test_empty_source_is_named_not_silently_skipped(fake, tmp_path):
    fake.transcript_cache = tmp_path / "does_not_exist"
    bundle, meta = md.assemble_bundle(fake, DAY)
    assert "no transcripts were cached" in bundle
    assert "transcripts" in meta["sources_empty"]


# ---------------------------------------------------------------------------
# COMMIT parsing — a hypothesis, or an honest 'none'
# ---------------------------------------------------------------------------

def test_commit_none_is_a_legitimate_answer():
    assert md.parse_commitment("NONE") is None
    assert md.parse_commitment("none of these are ready yet, honestly") is None


def test_commit_parses_a_full_hypothesis():
    raw = json.dumps({"claim": "renewables track internet access", "driver_axis": "ENERGY_REVIEW",
                      "affected_axis": "TECHNOLOGY_AI_REVIEW", "direction": "same",
                      "lag_cycles": 3, "evidence_cited": "the country rows",
                      "prediction": "energy score rises next", "falsified_if": "it falls"})
    h = md.parse_commitment(raw)
    assert h["claim"].startswith("renewables")
    assert h["lag_cycles"] == 3
    assert set(h) == set(md.COMMIT_KEYS)


def test_commit_ignores_a_half_formed_object():
    assert md.parse_commitment('{"driver_axis": "ENERGY_REVIEW"}') is None, \
        "an object with no claim must not be forced into a commitment"


# ---------------------------------------------------------------------------
# DIVERGE is written VERBATIM and APPEND-ONLY; nothing judges it
# ---------------------------------------------------------------------------

def test_notebook_stores_the_diverge_text_verbatim(fake):
    text = "raw thought: the drought news and the hunger transcript rhyme <weird chars &%>"
    md.run(DAY, dry_run=False, src=fake, llm=fake_llm(diverge_text=text))
    page = (fake.notebook_dir / f"{DAY}.md").read_text(encoding="utf-8")
    assert text in page, "the notebook did not store the model's words verbatim"


def test_notebook_is_append_only_across_reruns(fake):
    md.run(DAY, dry_run=False, src=fake, llm=fake_llm(diverge_text="first page thought"))
    md.run(DAY, dry_run=False, src=fake, llm=fake_llm(diverge_text="second page thought"))
    page = (fake.notebook_dir / f"{DAY}.md").read_text(encoding="utf-8")
    assert "first page thought" in page and "second page thought" in page, \
        "a re-run must ADD a page, never erase the earlier one"
    assert page.count("# meadow —") == 2


def test_no_check_module_exists_for_the_meadow():
    """The DIVERGE output is constitutionally unjudged: there must be no check.py."""
    assert not (Path(md.__file__).parent / "check.py").exists(), \
        "a check.py for the meadow would be the judgement the meadow forbids"


# ---------------------------------------------------------------------------
# COMMIT wiring — writes a file only on a real commitment
# ---------------------------------------------------------------------------

def test_committed_file_written_only_when_the_model_commits(fake):
    md.run(DAY, dry_run=False, src=fake, llm=fake_llm(commit_text="NONE"))
    assert not (fake.committed_dir / f"{DAY}.json").exists(), \
        "a 'none' answer must not write a committed hypothesis"

    good = json.dumps({"claim": "x leads y", "driver_axis": "ENERGY_REVIEW",
                       "affected_axis": "ECONOMY_WORK_REVIEW", "direction": "same",
                       "lag_cycles": 2, "evidence_cited": "e", "prediction": "p",
                       "falsified_if": "f"})
    md.run(DAY, dry_run=False, src=fake, llm=fake_llm(commit_text=good))
    cm = fake.committed_dir / f"{DAY}.json"
    assert cm.exists()
    obj = json.loads(cm.read_text(encoding="utf-8"))
    assert obj["hypothesis"]["claim"] == "x leads y"
    assert obj["date"] == DAY


# ---------------------------------------------------------------------------
# --dry-run writes NOTHING
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing(fake):
    md.run(DAY, dry_run=True, src=fake, llm=fake_llm())
    assert not fake.notebook_dir.exists() or not any(fake.notebook_dir.iterdir())
    assert not fake.committed_dir.exists() or not any(fake.committed_dir.iterdir())


# ---------------------------------------------------------------------------
# Isolation — writes only under the meadow; imports no live pipeline
# ---------------------------------------------------------------------------

def test_run_writes_only_under_the_meadow_out_dirs(fake, tmp_path):
    """A real run must create files ONLY under notebook_dir / committed_dir, never
    back into the news/snapshots/memory/output it read."""
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    good = json.dumps({"claim": "c", "driver_axis": "ENERGY_REVIEW",
                       "affected_axis": "ECONOMY_WORK_REVIEW", "direction": "same",
                       "lag_cycles": 1, "evidence_cited": "e", "prediction": "p",
                       "falsified_if": "f"})
    md.run(DAY, dry_run=False, src=fake, llm=fake_llm(commit_text=good))
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    new = after - before
    out_root = tmp_path / "meadow_out"
    assert new, "the run wrote nothing at all"
    for p in new:
        assert out_root in p.parents, f"the meadow wrote OUTSIDE its own dir: {p}"


def test_imports_no_live_pipeline_module():
    """Isolation: the only repo-internal import permitted is core.groq_backend, the
    shared brain. No scorer, agent, gate, tracker, memory.* or the cycle runner."""
    src = Path(md.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    repo_pkgs = {"memory", "agents", "snapshots", "core", "safety", "gates",
                 "trackers", "supervisor", "fast_cycle_runner", "web_intelligence_agent"}
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
    for mod in imported:
        top = mod.split(".")[0]
        if top in repo_pkgs:
            assert mod == "core.groq_backend", \
                f"meadow imports a live-path module it must not: {mod}"
