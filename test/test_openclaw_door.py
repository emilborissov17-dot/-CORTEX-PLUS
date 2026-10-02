# -*- coding: utf-8 -*-
"""test/test_openclaw_door.py — one door to the world (C-FIX-1 Part 3, 2 Oct 2026).

Every read from the network goes through OpenClaw's browser (core/openclaw_door.py);
a closed door is LOUD. The browser and the gateway are injected; nothing here
touches the network or OpenClaw.

THE RULE (Emil R43, 2 Oct 2026): a closed door must be loud and must write nothing;
the forbidden fallback is requests / urllib.
"""
from __future__ import annotations

import ast
import base64
import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import openclaw_door as door  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    from core import turn
    monkeypatch.setattr(turn, "state", lambda path=None: {"holder": "AGENTS"})
    monkeypatch.setattr(door, "_STATE", {"browser": None, "gateway": None, "gateway_restarts": 0})
    yield attempts
    _live_net.check(attempts)


class Clock:
    def __init__(self):
        self.hosts = []

    def wait(self, host):
        self.hosts.append(host)
        return 0.0


def public(*a, **k):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


class Browser:
    def __init__(self, payload: bytes = b'{"ok": 1}', status=200, ctype="application/json", alive=True):
        self.payload, self.status, self.ctype, self._alive = payload, status, ctype, alive
        self.tab, self.visited = "t1", []

    def alive(self):
        return self._alive

    def start(self):
        pass

    def _goto(self, url):
        self.visited.append(url)

    def _call(self, *args):
        assert args[0] == "evaluate"
        return {"result": json.dumps({"status": self.status, "type": self.ctype, "url": self.visited[-1],
                                      "b64": base64.b64encode(self.payload).decode("ascii")})}


class Gateway:
    def __init__(self, healthy=True, revive=True):
        self._h, self.revive, self.restarts = healthy, revive, 0

    def healthy(self):
        return self._h

    def restart(self):
        self.restarts += 1
        if self.revive:
            self._h = True


def get(url, browser, gateway=None):
    return door.get_bytes(url, browser=browser, gateway=gateway or Gateway(), resolve=public, clock=Clock())


# ── 3a: the door ────────────────────────────────────────────────────────────
def test_the_bytes_come_from_inside_openclaws_page():
    b = Browser(b"hello")
    r = get("https://data.example.org/x.json", b)
    assert r["bytes"] == b"hello" and r["status"] == 200 and b.visited == ["https://data.example.org/x.json"]


def test_the_fetch_standard_still_rules_the_door():
    from core import fetch_standard as fs
    with pytest.raises(fs.FetchRefused):
        door.get_bytes("http://127.0.0.1:8080/x", browser=Browser(), gateway=Gateway(), clock=Clock())
    with pytest.raises(fs.FetchRefused):
        door.get_bytes("file:///etc/passwd", browser=Browser(), gateway=Gateway(), resolve=public, clock=Clock())


def test_no_fetch_in_the_brains_turn(monkeypatch):
    from core import fetch_standard as fs
    from core import turn
    monkeypatch.setattr(turn, "state", lambda path=None: {"holder": "BRAIN"})
    with pytest.raises(fs.FetchRefused, match="BRAIN"):
        get("https://data.example.org/x", Browser())


def test_a_dead_gateway_is_restarted_once_and_still_dead_is_door_closed():
    gw = Gateway(healthy=False, revive=False)
    with pytest.raises(door.DoorClosed) as e:
        get("https://data.example.org/x", Browser(alive=False), gw)
    assert e.value.cause.startswith("GATEWAY_DEAD") and gw.restarts == 1


def test_a_dead_browser_with_a_live_gateway_is_door_closed_searcher_dead():
    with pytest.raises(door.DoorClosed) as e:
        get("https://data.example.org/x", Browser(alive=False), Gateway(healthy=True))
    assert e.value.cause.startswith("SEARCHER_DEAD")


def test_door_closed_is_not_an_exception_a_reader_can_swallow():
    assert not issubclass(door.DoorClosed, Exception)
    with pytest.raises(door.DoorClosed):
        try:
            raise door.DoorClosed("GATEWAY_DEAD: x")
        except Exception:                                         # noqa: BLE001  what a reader does
            pytest.fail("a reader's `except Exception` caught a closed door")


def test_mutation_as_an_exception_a_reader_would_swallow_it():
    class Swallowable(Exception):
        pass
    swallowed = False
    try:
        raise Swallowable("GATEWAY_DEAD")
    except Exception:                                             # noqa: BLE001
        swallowed = True
    assert swallowed, "the net above would not distinguish a BaseException from an Exception"


# ── the requests-shaped face ─────────────────────────────────────────────────
def test_the_face_encodes_params_and_parses_json(monkeypatch):
    seen = []
    monkeypatch.setattr(door, "get_bytes", lambda url, **k: seen.append(url) or
                        {"status": 200, "bytes": b'[{"page": 1}]', "content_type": "application/json", "final_url": url})
    r = door.http.get("https://api.example.org/v2/x", params={"format": "json", "mrv": 5})
    assert seen == ["https://api.example.org/v2/x?format=json&mrv=5"] and r.json() == [{"page": 1}]


def test_urlopen_raises_urllibs_http_error_with_code_and_body(monkeypatch):
    import urllib.error
    monkeypatch.setattr(door, "get_bytes", lambda url, **k: {"status": 404, "bytes": b"not released",
                                                            "content_type": "text/plain", "final_url": url})
    with pytest.raises(urllib.error.HTTPError) as e:
        door.http.urlopen(door.http.Request("https://ucdpapi.example/x"))
    assert e.value.code == 404 and e.value.read() == b"not released"


def test_credentials_are_refused_by_the_face():
    from core import fetch_standard as fs
    with pytest.raises(fs.FetchRefused):
        door.http.get("https://x.example/a", headers={"Authorization": "Bearer t"})


# ── 3b/3c: each reader parses the same bytes, taken from the door ────────────
@pytest.fixture
def through_door(monkeypatch):
    """The door returns fixture bytes; `requests` and urllib are tripwires."""
    import urllib.request
    served = {}

    def fake(url, **k):
        for key, (body, ctype) in served.items():
            if key in url:
                return {"status": 200, "bytes": body, "content_type": ctype, "final_url": url}
        raise AssertionError(f"unexpected url {url}")

    def tripwire(*a, **k):
        raise AssertionError("a reader fell back to requests/urllib")
    monkeypatch.setattr(door, "get_bytes", fake)
    monkeypatch.setattr(urllib.request, "urlopen", tripwire)
    try:
        import requests as _real
        monkeypatch.setattr(_real, "get", tripwire)
        monkeypatch.setattr(_real.Session, "request", tripwire)
    except ImportError:
        pass
    return served


def test_usgs_quakes_parses_the_count_from_the_door(through_door):
    from core import usgs_quakes as uq
    through_door["earthquake.usgs.gov"] = (b'{"count": 7, "maxAllowed": 20000}', "application/json")
    assert uq.fetch_count(date(2026, 9, 30)) == 7


def test_a_world_bank_provider_parses_the_series_from_the_door(through_door):
    sys.path.insert(0, str(REPO / "data_providers" / "civilization"))
    import economy_work_provider as p
    body = json.dumps([{"page": 1}, [{"date": "2024", "value": 3.1}, {"date": "2023", "value": 2.7}]]).encode()
    through_door["api.worldbank.org"] = (body, "application/json")
    assert p._wb_latest("NY.GDP.MKTP.KD.ZG") == 3.1


def test_global_indicators_get_parses_json_and_text_from_the_door(through_door):
    from core import global_indicators as gi
    through_door["gml.example"] = (b"1 2 3", "text/plain")
    through_door["json.example"] = (b'{"a": 1}', "application/json; charset=utf-8")
    assert gi._get("https://gml.example/co2.txt", attempts=1) == "1 2 3"
    assert gi._get("https://json.example/x", attempts=1) == {"a": 1}


def test_fx_fetch_parses_rates_from_the_door(through_door):
    sys.path.insert(0, str(REPO / "daily_signals"))
    import fx_fetch
    through_door["open.er-api.com"] = (json.dumps({"result": "success",
                                                   "time_last_update_utc": "Thu, 02 Oct 2026 00:02:31 +0000",
                                                   "rates": {"RUB": 81.5, "ARS": 1380.0}}).encode(),
                                       "application/json")
    rows = fx_fetch.fetch()
    assert [(r["pair"], r["rate"]) for r in rows] == [("USD/RUB", 81.5), ("USD/ARS", 1380.0)]
    assert rows[0]["date"] == "Thu, 02 Oct 2026"


def test_mutation_a_reader_on_requests_hits_the_tripwire(through_door):
    import requests
    with pytest.raises(AssertionError, match="fell back"):
        requests.get("https://api.worldbank.org/x")


# ── a closed door is loud and writes nothing ────────────────────────────────
def test_the_feed_reader_stops_by_name_and_writes_nothing(tmp_path, monkeypatch):
    from scripts import data_feed_reader as w
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"sources": [{"id": "s1", "axis": "A", "url": "https://x.example/a", "path": "v",
                                             "unit": "u"}]}), encoding="utf-8")
    from core import fetch_standard as fs

    def closed(url, timeout=None, **k):
        raise door.DoorClosed("GATEWAY_DEAD: the OpenClaw gateway does not answer after one restart")
    monkeypatch.setattr(fs, "get", closed)
    q = tmp_path / "queue"
    r = w.run(sources_path=seed, queue_dir=q, lifecycle_state={}, ledger=tmp_path / "l.jsonl",
              ingest=lambda *a, **k: {"added": 0}, parking=tmp_path / "p.json")
    assert r["door_closed"].startswith("GATEWAY_DEAD") and r["cards"] == []
    assert not q.exists() or not any(q.iterdir()), "something was written through a closed door"


def test_the_cycle_catches_a_closed_door_by_name_before_exception():
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run")
    handlers = [h for t in ast.walk(fn) if isinstance(t, ast.Try) for h in t.handlers]
    names = [ast.unparse(h.type) if h.type is not None else "" for h in handlers]
    assert "_DoorClosed" in names
    assert names.index("_DoorClosed") < max(i for i, n in enumerate(names) if n == "Exception")


def test_a_token_header_is_refused_by_name_never_sent_or_dropped(monkeypatch):
    from core import fetch_standard as fs
    sent = []
    monkeypatch.setattr(door, "get_bytes", lambda url, **k: sent.append(url))
    req = door.http.Request("https://ucdpapi.pcr.uu.se/api/gedevents/26.0.8")
    req.add_header("x-ucdp-access-token", "t")
    with pytest.raises(fs.FetchRefused, match="x-ucdp-access-token"):
        door.http.urlopen(req)
    assert sent == []


def test_mutation_without_the_hints_the_token_header_would_pass(monkeypatch):
    monkeypatch.setattr(door, "CREDENTIAL_HINTS", ())
    assert door._credential_header("x-ucdp-access-token") is False
