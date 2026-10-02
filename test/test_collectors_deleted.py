# -*- coding: utf-8 -*-
"""test/test_collectors_deleted.py — the old collectors are deleted; only OpenClaw
reaches the web (C-FIX-1 Part 2, 2 Oct 2026, Emil R43: "Delete them outright. News,
data, information, podcasts, YouTube, radio — only through OpenClaw.").

What a refusal looks like here: a consumer of a deleted collector's output reads
NOTHING and names NO_AGENT_INPUT. The forbidden fallback is reading the stale file
the collector left behind as if it were today's.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402

DELETED = [
    "web_intelligence_agent.py", "youtube_intel.py", "youtube_worker.py", "media_intel_worker.py",
    "media_intel_scheduler.py", "podcast_source.py", "scripts/intel_daemon.py", "core/axon_agents.py",
    "scripts/axon_sweep.py", "core/data_scout.py", "core/market_news.py",
    "experiments/browser_scout/autonomous_scout.py", "experiments/browser_scout/scout.py",
    "experiments/browser_scout/collector_memory.py", "experiments/browser_scout/goal_impact_collector.py",
    "experiments/browser_scout/goal_impact.py", "experiments/browser_scout/semantic_scout.py",
    "experiments/browser_scout/shadow_test_semantic.py", "experiments/browser_scout/_diag_goal_impact.py",
    "agents/internet/internet_agent.py", "tools/fill_pantry.py", "collectors_runner.py",
    "core/collectors_manifest.py", "experiments/collector/run_collector.ps1",
    "experiments/collector/run_collector.vbs", "experiments/collector/register_collector_task.cmd",
]
MODULES = {Path(f).stem for f in DELETED if f.endswith(".py")}
SKIP_DIRS = {"venv", "venv312_metta", "venv_train", ".git", "node_modules", "_to_delete_gitlock", "Broker-bot",
             ".claude", "__pycache__", "memory", "output", "snapshots", "logs", "patches"}


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


def imports_of_deleted(source: str) -> list:
    """Module names from MODULES that `source` imports (any form)."""
    out = []
    for n in ast.walk(ast.parse(source)):
        names = []
        if isinstance(n, ast.Import):
            names = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            names = [n.module or ""] + [f"{n.module}.{a.name}" for a in n.names]
        for name in names:
            parts = set(str(name).split("."))
            out += sorted(parts & MODULES)
    return sorted(set(out))


def _sources():
    for p in REPO.rglob("*.py"):
        rel = p.relative_to(REPO)
        if any(part in SKIP_DIRS or part.startswith("venv") for part in rel.parts[:-1]):
            continue
        yield rel.as_posix(), p.read_text(encoding="utf-8-sig", errors="replace")


# ── 2e: the deleted names do not exist and nothing imports them ─────────────
def test_the_deleted_files_do_not_exist():
    assert [f for f in DELETED if (REPO / f).exists()] == []


def test_nothing_imports_a_deleted_collector():
    bad = {}
    for rel, src in _sources():
        try:
            hits = imports_of_deleted(src)
        except SyntaxError:
            continue
        if hits:
            bad[rel] = hits
    assert bad == {}


def test_mutation_an_import_of_a_deleted_collector_is_seen():
    assert imports_of_deleted("import web_intelligence_agent\n") == ["web_intelligence_agent"]
    assert imports_of_deleted("from core.data_scout import run\n") == ["data_scout"]
    assert imports_of_deleted("from experiments.browser_scout import scout\n") == ["scout"]


def test_the_cycle_beats_none_of_the_removed_steps():
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    beats = {n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "beat" and n.args and isinstance(n.args[0], ast.Constant)}
    assert not beats & {"web_intelligence", "browser_scout", "data_scout"}
    assert "global_indicators" in beats, "the beat parser no longer reads the cycle"


def test_the_supervisor_has_no_collectors_stage():
    import supervisor as sup
    assert not any(hasattr(sup, n) for n in ("COLLECTORS_START", "_spawn_collectors", "_collectors_state",
                                             "COLLECTORS_RUNNER"))


def test_the_morning_task_runs_no_pantry_filler():
    bat = (REPO / "tools" / "prophecy_morning.bat").read_text(encoding="utf-8")
    assert 'call :step "fill_pantry"' not in bat


# ── 2d: a consumer of a deleted collector's output reads nothing and names why ─
def test_the_feed_reader_does_not_read_the_scouts_stale_list(tmp_path, monkeypatch):
    from scripts import data_feed_reader as w
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"sources": [{"id": "s1", "axis": "A", "url": "https://x.example/a", "path": "v"}]}),
                    encoding="utf-8")
    stale = tmp_path / "discovered.json"
    stale.write_text(json.dumps({"A": {"sources": [{"status": "active", "format": "json", "kind": "http_json_path",
                                                   "url": "https://y.example/b", "extract": "v"}]}}), encoding="utf-8")
    monkeypatch.setattr(w, "DISCOVERED", stale)
    sources, _ = w.all_sources(seed)
    assert [s["id"] for s in sources] == ["s1"], "the deleted scout's list was read as today's"
    sources, _ = w.all_sources(seed, stale)
    assert len(sources) == 2, "a list passed explicitly must still be read"
    assert w.NO_AGENT_INPUT.startswith("NO_AGENT_INPUT")


def test_market_news_is_refused_by_name():
    from tools import market_bet as mb
    with pytest.raises(mb.NewsUnavailable, match="NO_AGENT_INPUT"):
        mb.fetch_news("SPY")


def test_github_publish_publishes_nothing_from_the_deleted_tree(monkeypatch, capsys):
    import github_publisher as gp
    pushed = []
    monkeypatch.setattr(gp, "_push_file", lambda *a, **k: pushed.append(a))
    monkeypatch.setattr(gp, "_find_latest_web_intel_dir",
                        lambda: (_ for _ in ()).throw(AssertionError("the stale tree was looked up")))
    gp.publish_cycle()
    assert pushed == [] and "NO_AGENT_INPUT" in capsys.readouterr().out


def test_the_self_observer_reads_no_stale_web_intelligence():
    """Structural: importing the module reads memory/ at import time, so its
    function is checked on the AST — it opens no file and returns an empty dict."""
    tree = ast.parse((REPO / "agents" / "core" / "self_observer.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_web_intelligence")
    calls = {getattr(c.func, "attr", None) or getattr(c.func, "id", None) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not calls & {"read_text", "open", "loads", "exists"}, calls
    rets = [r for r in ast.walk(fn) if isinstance(r, ast.Return)]
    assert rets and all(isinstance(r.value, ast.Dict) and not r.value.keys for r in rets)
    assert "NO_AGENT_INPUT" in ast.unparse(fn)


def test_the_creative_tick_imports_its_model_from_local_model_not_a_collector():
    src = (REPO / "experiments" / "pulse" / "pulse_continuum.py").read_text(encoding="utf-8")
    mods = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) and n.module}
    assert "local_model" in mods and "autonomous_scout" not in mods


# ── 2c: the deleted collectors' axis queries are seed topics of the agents ───
def test_regenerating_the_profiles_keeps_the_seed_topics(tmp_path):
    from core import agent_profiles as ap
    ap.generate(tmp_path)
    p = tmp_path / "A1.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["seed_topics"] = [{"topic": "climate change CO2 emissions", "axis": "X", "from": "test", "placed": "test"}]
    p.write_text(json.dumps(d), encoding="utf-8")
    ap.generate(tmp_path)
    assert json.loads(p.read_text(encoding="utf-8"))["seed_topics"][0]["topic"] == "climate change CO2 emissions"


def test_mutation_without_keeping_them_a_regeneration_drops_the_seeds(tmp_path, monkeypatch):
    from core import agent_profiles as ap
    monkeypatch.setattr(ap, "KEEP_BY_HAND", ("openclaw_agent", "browser_profile", "skills", "plugins"))
    ap.generate(tmp_path)
    p = tmp_path / "A1.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["seed_topics"] = [{"topic": "x"}]
    p.write_text(json.dumps(d), encoding="utf-8")
    ap.generate(tmp_path)
    assert "seed_topics" not in json.loads(p.read_text(encoding="utf-8"))


def test_the_live_profiles_carry_the_seed_topics_of_all_axes():
    seeds = []
    for f in (REPO / "config" / "agents").glob("*.json"):
        seeds += json.loads(f.read_text(encoding="utf-8")).get("seed_topics") or []
    axes = {s["axis"] for s in seeds}
    assert len(axes) >= 24 and all(s.get("topic") and s.get("from") and s.get("placed") for s in seeds)
