# -*- coding: utf-8 -*-
"""test/test_dying_searcher.py — C-FIX-1 Part 4B-b (2 Oct 2026): a searcher that dies
stops its browser; a profile that does not answer is named and recycled.

What 4B-a showed (read-only diagnosis, claude/reports/FIX_2026-10-02.md): one browser
profile can stop answering INSIDE the gateway while the gateway's own health answers;
only a gateway restart recovers it; `stop` can leave its Chrome running.

THE RULES (C-FIX-1 4B-b):
  (i)   a search result without an address is recorded LINK_WITHOUT_ADDRESS and skipped;
  (ii)  the agents' turn and the relabel stop every browser in a `finally`; a `stop`
        that times out ends that profile's Chrome by exact PID (found by its
        --remote-debugging-port) and logs PROFILE_CHROME_ENDED;
  (iii) a timeout for one profile while gateway health answers -> PROFILE_DEAD:<profile>;
        the recovery is a gateway restart, once per turn.
Browsers, gateway, processes and the killer are injected; nothing here touches
OpenClaw, Chrome or the network.
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
from core import agent_profiles as ap  # noqa: E402
from scripts import openclaw_search as oc  # noqa: E402

DDG = "https://duckduckgo.com/l/?uddg="


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


# ── (i) a link without an address ───────────────────────────────────────────
class Searcher:
    def __init__(self, links):
        self.links = links

    def search(self, q):
        return {"page": {"title": "r", "text": "results"}, "links": self.links, "raw": {}}

    def read(self, url):
        return {"page": {"title": "t", "text": "A page. Two.", "url": url}, "raw": {"ok": True}}


def _serve(links, tmp_path):
    rows = []
    r = oc.serve("N-1", "q", Searcher(links), lambda *a, **k: {"added": 1}, rows.append,
                 pages_dir=tmp_path / "pages")
    return r, rows


def test_a_result_without_an_address_is_recorded_and_skipped(tmp_path):
    r, rows = _serve([{"text": "a title, no href"}, {"url": "", "text": "empty"},
                      {"url": DDG + "https://site.example/a", "text": "ok"}], tmp_path)
    missing = [x for x in rows if x["event"] == "LINK_WITHOUT_ADDRESS"]
    assert len(missing) == 2 and missing[0]["need_id"] == "N-1" and missing[0]["text"] == "a title, no href"
    assert r["pages"] == 1


def test_only_links_without_an_address_stays_no_results_and_is_recorded(tmp_path):
    r, rows = _serve([{"text": "x"}], tmp_path)
    events = [x["event"] for x in rows]
    assert "LINK_WITHOUT_ADDRESS" in events and "NO_RESULTS" in events and r["pages"] == 0


def test_mutation_a_silent_filter_leaves_no_record(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "links_of", lambda s, need_id, ledger: [
        oc.unwrap(l.get("url", "")) for l in (s.get("links") or []) if l.get("url")])
    _r, rows = _serve([{"text": "a title, no href"}], tmp_path)
    assert not [x for x in rows if x["event"] == "LINK_WITHOUT_ADDRESS"]


# ── (ii) finding a profile's Chrome by its debugging port ────────────────────
class Proc:
    def __init__(self, pid, name, cmdline):
        self.info = {"pid": pid, "name": name, "cmdline": cmdline}


PROCS = [
    Proc(10, "chrome.exe", ["chrome.exe", "--remote-debugging-port=18800", "--user-data-dir=x"]),
    Proc(11, "chrome.exe", ["chrome.exe", "--type=renderer", "--remote-debugging-port=18800"]),
    Proc(12, "chrome.exe", ["chrome.exe", "--remote-debugging-port=188001"]),
    Proc(13, "chrome.exe", ["chrome.exe", "--remote-debugging-port=18801"]),
    Proc(14, "node.exe", ["node.exe", "--remote-debugging-port=18800"]),
]


def test_the_profiles_chrome_is_its_main_process_on_exactly_that_port():
    assert oc.chrome_pids_for_port(18800, PROCS) == [10]
    assert oc.chrome_pids_for_port(18801, PROCS) == [13]
    assert oc.chrome_pids_for_port(18802, PROCS) == []


def test_mutation_a_prefix_match_would_take_another_profiles_chrome():
    loose = [p.info["pid"] for p in PROCS if any(a.startswith("--remote-debugging-port=18800")
                                                for a in p.info["cmdline"])]
    assert 12 in loose and 12 not in oc.chrome_pids_for_port(18800, PROCS)


class Stubborn:
    """A browser whose `stop` times out (4B-a: the profile is wedged in the gateway)."""

    def __init__(self, profile, log, cdp_port=None):
        self.profile, self.log, self.cdp_port = profile, log, cdp_port

    def stop(self):
        self.log.append(("stop", self.profile))
        raise oc.ProfileTimeout(f"openclaw browser stop timed out after 60s ({self.profile})")


def test_a_stop_that_times_out_ends_that_profiles_chrome_by_pid():
    rows, killed, log = [], [], []
    out = oc.stop_browser(Stubborn("openclaw", log, cdp_port=18800), rows.append, profile="openclaw",
                          procs=PROCS, kill=killed.append)
    assert killed == [10] and "ended" in out
    row = [x for x in rows if x["event"] == "PROFILE_CHROME_ENDED"][0]
    assert row["profile"] == "openclaw" and row["pid"] == 10 and row["port"] == 18800
    assert "--remote-debugging-port=18800" in row["cmdline"]


def test_a_stop_that_answers_kills_nothing():
    class Fine:
        cdp_port = 18800

        def stop(self):
            pass
    killed = []
    assert oc.stop_browser(Fine(), [].append, profile="openclaw", procs=PROCS, kill=killed.append) == "stopped"
    assert killed == []


def test_no_port_known_means_nothing_is_killed_and_that_is_recorded(monkeypatch):
    monkeypatch.setattr(oc, "cdp_port", lambda profile, browser=None: None)
    rows, killed = [], []
    oc.stop_browser(Stubborn("x", []), rows.append, profile="x", procs=PROCS, kill=killed.append)
    assert killed == [] and [x for x in rows if x["event"] == "PROFILE_CHROME_NOT_FOUND"]


def test_mutation_without_the_end_a_timed_out_stop_leaves_chrome_running(monkeypatch):
    monkeypatch.setattr(oc, "end_profile_chrome", lambda *a, **k: [])
    killed = []
    oc.stop_browser(Stubborn("openclaw", [], cdp_port=18800), [].append, profile="openclaw", procs=PROCS,
                    kill=killed.append)
    assert killed == []


# ── the agents' turn ────────────────────────────────────────────────────────
class Browser:
    def __init__(self, profile, state):
        self.profile, self.s, self.cdp_port, self.timed_out = profile, state, 18800, False

    def alive(self):
        self.timed_out = self.s["wedged"].get(self.profile, False)
        return not self.timed_out and self.s["running"]

    def start(self):
        self.s["log"].append(("start", self.profile))
        self.s["running"] = True

    def stop(self):
        self.s["log"].append(("stop", self.profile))
        if self.s.get("stop_times_out"):
            raise oc.ProfileTimeout("stop timed out")

    def search(self, q):
        if self.s.get("boom"):
            raise RuntimeError("something nobody expected")
        return {"page": {"title": "r", "text": "r"}, "links": [{"url": DDG + "https://site.example/a"}], "raw": {}}

    def read(self, url):
        return {"page": {"title": "t", "text": "A page. Two.", "url": url}, "raw": {"ok": True}}


class Gateway:
    def __init__(self, state, unwedges=True):
        self.s, self.unwedges, self.restarts = state, unwedges, 0

    def healthy(self):
        return True

    def restart(self):
        self.restarts += 1
        self.s["log"].append(("restart",))
        if self.unwedges:
            self.s["wedged"].clear()
            self.s["running"] = False


@pytest.fixture
def t(tmp_path, monkeypatch):
    from core import turn
    monkeypatch.setattr(turn, "STATE", tmp_path / "turn.json")
    por = tmp_path / "portion.json"
    por.write_text(json.dumps({k: {"value": v, "why": "t"} for k, v in (
        ("verify_per_turn", 10), ("maintenance_cells_per_turn", 1), ("embed_min_free_gb", 1.5),
        ("extractor_min_free_gb", 2.0))}), encoding="utf-8")
    needs = [{"id": f"EN-{i}", "origin": "engine", "kind": "FIND", "status": "OPEN", "question": f"q{i}",
              "created_utc": "2026-10-01T00:00:00Z"} for i in range(2)]
    (tmp_path / "needs.json").write_text(json.dumps({"needs": needs}), encoding="utf-8")
    prof = tmp_path / "agents"
    ap.generate(prof)
    state = {"log": [], "wedged": {}, "running": True, "ended": []}
    paths = {k: tmp_path / f"{k}.x" for k in ("refused", "log", "briefings", "grounded", "obs_log", "shown")}
    paths.update({"needs": tmp_path / "needs.json", "ledger": tmp_path / "ledger.jsonl",
                  "forward_glob": str(tmp_path / "none" / "*.json"), "atoms_root": tmp_path / "atoms"})

    def go(gw):
        from scripts import turn_agents as ta
        return ta.run(browser_for=lambda p: Browser(p, state), ingest=lambda *a, **k: {"added": 2},
                      bn_paths=paths, ledger_path=tmp_path / "ledger.jsonl", result_path=tmp_path / "result.json",
                      turns_log=tmp_path / "turns_log.jsonl",
                      profiles_dir=prof, learned_dir=tmp_path / "learned", atom_sub={},
                      feeds=lambda: {}, restore=lambda: {}, maintenance=lambda n, s: {"worked": 0, "rows": []},
                      pages_dir=tmp_path / "pages", records_dir=tmp_path / "records", portion_path=por,
                      store_read=lambda q: [], gateway=gw,
                      end_chrome=lambda profile, port, ledger: state["ended"].append((profile, port)) or [99])

    def ledger():
        return [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    return {"go": go, "s": state, "ledger": ledger}


def test_an_unexpected_error_still_stops_every_browser(t):
    t["s"]["boom"] = True
    with pytest.raises(RuntimeError, match="nobody expected"):
        t["go"](Gateway(t["s"]))
    assert ("stop", "openclaw") in t["s"]["log"]


def test_a_stop_that_times_out_in_the_turn_ends_chrome_by_pid(t):
    t["s"]["stop_times_out"] = True
    r = t["go"](Gateway(t["s"]))
    assert ("openclaw", 18800) in t["s"]["ended"] and "ended" in r["browsers_stopped"]["openclaw"]


def test_a_wedged_profile_is_named_and_recycled_by_one_gateway_restart(t):
    t["s"]["wedged"]["openclaw"] = True
    gw = Gateway(t["s"])
    r = t["go"](gw)
    assert gw.restarts == 1 and r["cause"] is None and len(r["per_need"]) == 2
    row = [x for x in t["ledger"]() if x["event"] == "PROFILE_DEAD"][0]
    assert row["profile"] == "openclaw"


def test_still_wedged_after_the_one_restart_ends_the_turn_profile_dead(t):
    t["s"]["wedged"]["openclaw"] = True
    gw = Gateway(t["s"], unwedges=False)
    r = t["go"](gw)
    assert gw.restarts == 1 and r["exit"] == 2 and r["cause"] == "PROFILE_DEAD:openclaw"
    assert ("stop", "openclaw") in t["s"]["log"]


def test_mutation_a_browser_that_is_merely_not_running_is_started_not_recycled(t):
    t["s"]["running"] = False
    gw = Gateway(t["s"])
    r = t["go"](gw)
    assert gw.restarts == 0 and ("start", "openclaw") in t["s"]["log"] and r["cause"] is None


# ── the relabel ─────────────────────────────────────────────────────────────
def test_the_relabel_stops_its_browser_even_when_it_fails(monkeypatch):
    log = []

    class B:
        profile, cdp_port = "openclaw", 18800

        def stop(self):
            log.append("stop")

    def boom(*a, **k):
        raise RuntimeError("relabel failed")
    monkeypatch.setattr(oc, "OpenClawBrowser", lambda *a, **k: B())
    monkeypatch.setattr(oc, "relabel_pages", boom)
    monkeypatch.setattr(sys, "argv", ["openclaw_search.py", "--relabel", "BN-1"])
    with pytest.raises(RuntimeError, match="relabel failed"):
        oc.main()
    assert log == ["stop"]


# ── the live net covers the driver where it now lives (scripts/openclaw_browser.py) ──
def test_the_live_net_stops_the_moved_driver_from_reaching_openclaw(_no_live):
    from scripts import openclaw_browser as ob
    with pytest.raises(AssertionError, match="live OpenClaw CLI"):
        ob.Gateway().healthy()
    assert "openclaw CLI" in _no_live
    _no_live.clear()
