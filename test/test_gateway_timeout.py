# -*- coding: utf-8 -*-
"""test/test_gateway_timeout.py — C-GW-2 (8 Oct 2026): a "gateway timeout" on a browser
call is a dead gateway, even while `gateway health` answers; the stop reaches the phone.

What happened (memory/turns_log.jsonl, memory/vertical_ledger.jsonl): on 5 Oct 18:09-18:27
UTC and on 7 Oct 07:49-08:06 UTC three agents' turns in a row ended SEARCHER_DEAD because
`openclaw browser start` answered "gateway timeout after 30000ms" while `gateway health`
said ok; the turn restarted nothing, the loop's health check (a real start) failed the same
way every 300 s, and the baton stood for 36 h and then 21 h. The alarm for the stop went
with cls="TURN_STUCK", which Telegram does not carry: nobody was told.

THE RULES:
  (i)   the CLI's words "gateway timeout" on status or start -> GATEWAY_TIMEOUT row, ONE
        gateway restart per turn (the same one as C-GW-1 / C-FIX-1), then the call again;
        a second timeout ends the turn GATEWAY_DEAD, never SEARCHER_DEAD;
  (ii)  a browser that is merely not running is started, not recycled (unchanged);
  (iii) the loop's health check for GATEWAY_DEAD and SEARCHER_DEAD is a real start; a
        gateway timeout there gets one restart per check and one more start;
  (iv)  the stop's alarm goes with cls="alarm" and a dedup key that carries the seq.
Gateway, browsers and the alarm are injected; nothing here touches OpenClaw, Chrome or
the network.
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
GT = ("openclaw browser start failed: {'type': 'cli_error', 'message': 'gateway timeout after 30000ms\\n"
      "Gateway target: ws://127.0.0.1:18789\\nSource: local loopback'}")


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


# ── the driver names the CLI's words ────────────────────────────────────────
class _P:
    def __init__(self, rc, out):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def test_the_clis_gateway_timeout_is_raised_by_name(monkeypatch):
    from scripts import openclaw_browser as ob
    monkeypatch.setattr(ob, "openclaw_cmd", lambda: ["node", "x.mjs"])
    monkeypatch.setattr(ob.subprocess, "run", lambda *a, **k: _P(1, json.dumps({"ok": False, "error": GT})))
    b = ob.OpenClawBrowser()
    with pytest.raises(ob.GatewayTimeout):
        b._call("start")
    assert b.alive() is False and b.gateway_timed_out is True and b.timed_out is False


def test_any_other_failure_is_not_a_gateway_timeout(monkeypatch):
    from scripts import openclaw_browser as ob
    monkeypatch.setattr(ob, "openclaw_cmd", lambda: ["node", "x.mjs"])
    monkeypatch.setattr(ob.subprocess, "run", lambda *a, **k: _P(1, json.dumps({"ok": False, "error": "no profile"})))
    b = ob.OpenClawBrowser()
    with pytest.raises(ob.OpenClawFailed) as ei:
        b._call("status")
    assert not isinstance(ei.value, ob.GatewayTimeout)
    assert b.alive() is False and b.gateway_timed_out is False


# ── the agents' turn ────────────────────────────────────────────────────────
class Browser:
    """`wedged_gw` = the gateway times out for browser calls; a restart clears it when
    the injected Gateway says so. `running` = OpenClaw's status."""

    def __init__(self, profile, state):
        self.profile, self.s, self.cdp_port = profile, state, 18800
        self.timed_out = self.gateway_timed_out = False

    def alive(self):
        self.timed_out = False
        # status_answers: OpenClaw's status still answers ("running": false) while START times out
        self.gateway_timed_out = bool(self.s["wedged_gw"]) and not self.s.get("status_answers")
        return (not self.gateway_timed_out) and self.s["running"]

    def start(self):
        self.s["log"].append(("start", self.profile))
        if self.s["wedged_gw"]:
            raise oc.GatewayTimeout(GT)
        self.s["running"] = True

    def stop(self):
        self.s["log"].append(("stop", self.profile))

    def search(self, q):
        return {"page": {"title": "r", "text": "r"}, "links": [{"url": DDG + "https://site.example/a"}], "raw": {}}

    def read(self, url):
        return {"page": {"title": "t", "text": "A page. Two.", "url": url}, "raw": {"ok": True}}


class Gateway:
    def __init__(self, state, unwedges=True):
        self.s, self.unwedges, self.restarts = state, unwedges, 0

    def healthy(self):
        return True                      # what the machine said on 5 and 7 Oct

    def restart(self):
        self.restarts += 1
        self.s["log"].append(("restart",))
        if self.unwedges:
            self.s["wedged_gw"] = False


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
    state = {"log": [], "wedged_gw": True, "running": False}
    paths = {k: tmp_path / f"{k}.x" for k in ("refused", "log", "briefings", "grounded", "obs_log")}
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
                      store_read=lambda q: [], gateway=gw, end_chrome=lambda profile, port, ledger: [])

    def ledger():
        return [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    return {"go": go, "s": state, "ledger": ledger}


def test_a_gateway_timeout_with_healthy_health_gets_one_restart_and_the_turn_goes_on(t):
    gw = Gateway(t["s"])
    r = t["go"](gw)
    assert gw.restarts == 1 and r["cause"] is None and len(r["per_need"]) == 2
    rows = t["ledger"]()
    gt = [x for x in rows if x["event"] == "GATEWAY_TIMEOUT"]
    assert gt and gt[0]["health"] == "answers" and gt[0]["where"] == "status"
    rs = [x for x in rows if x["event"] == "GATEWAY_RESTARTED"][0]
    assert rs["why"].startswith("GATEWAY_TIMEOUT:status:")
    # the timeout was seen on status, so no start was wasted before the restart
    assert [x for x in t["s"]["log"] if x == ("start", "openclaw")] == [("start", "openclaw")]


def test_still_timing_out_after_the_one_restart_ends_the_turn_gateway_dead_not_searcher_dead(t):
    gw = Gateway(t["s"], unwedges=False)
    r = t["go"](gw)
    assert gw.restarts == 1 and r["exit"] == 2
    assert r["cause"].startswith("GATEWAY_DEAD") and "SEARCHER_DEAD" not in r["cause"]
    assert ("stop", "openclaw") in t["s"]["log"]


def test_a_timeout_on_start_alone_with_status_answering_gets_the_one_restart(t):
    """The 7 Oct shape: status says not running, `start` answers "gateway timeout"."""
    t["s"]["status_answers"] = True
    gw = Gateway(t["s"])
    r = t["go"](gw)
    assert gw.restarts == 1 and r["cause"] is None and len(r["per_need"]) == 2
    rows = t["ledger"]()
    assert [x["where"] for x in rows if x["event"] == "GATEWAY_TIMEOUT"] == ["start"]
    starts = [x for x in t["s"]["log"] if x == ("start", "openclaw")]
    assert len(starts) == 2                      # once before the restart, once after


def test_a_timeout_on_start_that_survives_the_restart_is_gateway_dead(t):
    t["s"]["status_answers"] = True
    gw = Gateway(t["s"], unwedges=False)
    r = t["go"](gw)
    assert gw.restarts == 1 and r["cause"].startswith("GATEWAY_DEAD") and "start" in r["cause"]


def test_a_browser_that_is_merely_not_running_is_started_without_a_restart(t):
    t["s"]["wedged_gw"] = False
    gw = Gateway(t["s"])
    r = t["go"](gw)
    assert gw.restarts == 0 and ("start", "openclaw") in t["s"]["log"] and r["cause"] is None


def test_mutation_without_the_rule_the_turn_is_searcher_dead_with_no_restart(t, monkeypatch):
    # the machine's behaviour before C-GW-2: the driver never names the gateway timeout
    monkeypatch.setattr(Browser, "alive", lambda self: False)

    def start(self):
        self.s["log"].append(("start", self.profile))
        raise oc.OpenClawFailed(GT)
    monkeypatch.setattr(Browser, "start", start)
    gw = Gateway(t["s"])
    r = t["go"](gw)
    assert gw.restarts == 0 and r["cause"].startswith("SEARCHER_DEAD")


# ── the loop's health check ─────────────────────────────────────────────────
class _OC:
    """An injected scripts.openclaw_search: Gateway and OpenClawBrowser over one state."""
    OpenClawFailed, GatewayTimeout = oc.OpenClawFailed, oc.GatewayTimeout

    def __init__(self, state):
        s = self.s = state
        mod = self

        class G:
            def healthy(self_):
                return s["health"]

            def restart(self_):
                s["restarts"] += 1
                if s["unwedges"]:
                    s["wedged_gw"] = False

        class B:
            def start(self_):
                s["starts"] += 1
                if s["wedged_gw"]:
                    raise mod.GatewayTimeout(GT)

            def alive(self_):
                return not s["wedged_gw"]

            def stop(self_):
                s["stops"] += 1
        self.Gateway, self.OpenClawBrowser = G, B


def _state(**kw):
    d = {"health": True, "wedged_gw": True, "unwedges": True, "restarts": 0, "starts": 0, "stops": 0}
    d.update(kw)
    return d


@pytest.mark.parametrize("cause", ["GATEWAY_DEAD: the OpenClaw gateway times out", "SEARCHER_DEAD: x"])
def test_the_health_check_restarts_the_gateway_once_on_a_timeout_and_starts_again(cause):
    from scripts import turns_loop as tl
    rows, s = [], _state()
    assert tl.health_for(cause, oc=_OC(s), log=rows.append) is True
    assert s["restarts"] == 1 and s["starts"] == 2 and s["stops"] == 2
    assert [r["event"] for r in rows] == ["GATEWAY_TIMEOUT", "GATEWAY_RESTARTED"]
    assert rows[1]["by"] == "health check"


def test_the_health_check_says_false_when_the_timeout_survives_the_restart():
    from scripts import turns_loop as tl
    rows, s = [], _state(unwedges=False)
    assert tl.health_for("GATEWAY_DEAD: x", oc=_OC(s), log=rows.append) is False
    assert s["restarts"] == 1 and s["starts"] == 2
    assert rows[-1]["event"] == "BROWSER_START_FAILED"


def test_a_gateway_whose_health_fails_is_not_restarted_by_the_check():
    from scripts import turns_loop as tl
    s = _state(health=False)
    assert tl.health_for("SEARCHER_DEAD: x", oc=_OC(s), log=[].append) is False
    assert s["restarts"] == 0 and s["starts"] == 0


def test_gateway_dead_is_never_passed_by_health_alone():
    from scripts import turns_loop as tl
    s = _state(unwedges=False)
    assert tl.health_for("GATEWAY_DEAD: x", oc=_OC(s), log=[].append) is False     # health True, start times out


def test_an_unknown_cause_has_no_health_check():
    from scripts import turns_loop as tl
    assert tl.health_for("SOMETHING_ELSE", oc=_OC(_state()), log=[].append) is None


# ── the alarm reaches the phone ─────────────────────────────────────────────
def test_the_stop_alarm_goes_as_class_alarm_with_the_seq_in_its_key(monkeypatch):
    import supervisor
    from scripts import turns_loop as tl
    got = {}

    def fake(subject, detail, dedup_key=None, trigger=None, *, level=None, cls=None):
        got.update(subject=subject, detail=detail, dedup_key=dedup_key, cls=cls, level=level)
        return "delivered"
    monkeypatch.setattr(supervisor, "alarm_human", fake)
    assert tl._live_alarm("SEARCHER_DEAD: OpenClaw browser profile openclaw is not running", seq=108) == "delivered"
    assert got["cls"] == "alarm" and got["level"] == supervisor.ALARM
    assert got["dedup_key"].startswith("LOOP_STOPPED_SAME_CAUSE:108:") and "seq 108" in got["detail"]
    assert supervisor.telegram_refusal(got["cls"]) is None


def test_mutation_the_old_class_was_refused_by_the_phone():
    import supervisor
    assert supervisor.telegram_refusal("TURN_STUCK") is not None
