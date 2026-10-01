# -*- coding: utf-8 -*-
"""test/test_fetch_standard.py — the fetch standard for OPEN sources (C-OC-3 Part 2).

One test per rule and one MUTATION per rule: the mutation removes the rule and
shows the forbidden request would then go out. No network: a fake session and a
fake resolver stand in for both. Parking state lives under tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import fetch_standard as fs  # noqa: E402

PUBLIC = lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))]           # noqa: E731
PRIVATE = lambda host, port: [(2, 1, 6, "", ("10.0.0.7", 0))]               # noqa: E731


class Resp:
    def __init__(self, status=200, body=b"{}", headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}
        self.encoding = "utf-8"

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    def close(self):
        pass


class Session:
    def __init__(self, *responses):
        self.responses, self.sent = list(responses), []
        import requests
        self.cookies = requests.cookies.RequestsCookieJar()
        self.trust_env = True

    def request(self, method, url, **kw):
        self.sent.append({"method": method, "url": url, "headers": dict(kw["headers"]),
                          "cookies": dict(self.cookies), "kw": kw})
        return self.responses.pop(0)


class NoWait(fs.HostClock):
    def __init__(self):
        self.slept = []
        super().__init__(now=lambda: 0.0, sleep=self.slept.append)


def _get(url, *responses, resolve=PUBLIC, **kw):
    sess = Session(*responses or (Resp(),))
    out = fs.get(url, session=sess, resolve=resolve, clock=NoWait(), **kw)
    return out, sess


# ── GET only ────────────────────────────────────────────────────────────────
def test_only_get_goes_out():
    _out, sess = _get("https://example.org/a")
    assert [s["method"] for s in sess.sent] == ["GET"]
    with pytest.raises(fs.FetchRefused):
        _get("https://example.org/a", method="POST")


def test_mutation_without_the_method_rule_a_post_would_go_out():
    """Mutate the module source: drop the method guard and the hard-coded GET."""
    import types
    src = Path(fs.__file__).read_text(encoding="utf-8")
    guard = '    if method != "GET":\n        raise FetchRefused(f"method {method} is not GET")\n'
    assert guard in src and 'session.request("GET", url' in src
    mutated = src.replace(guard, "").replace('session.request("GET", url', "session.request(method, url")
    mod = types.ModuleType("fs_mutant")
    mod.__file__ = fs.__file__
    exec(compile(mutated, "fs_mutant", "exec"), mod.__dict__)
    sess = Session(Resp())
    mod.get("https://example.org/a", method="POST", session=sess, resolve=PUBLIC,
            clock=mod.HostClock(now=lambda: 0.0, sleep=lambda s: None))
    assert sess.sent[0]["method"] == "POST"


def test_the_signature_takes_no_body_auth_or_cookies():
    import inspect
    assert not {"data", "json", "auth", "cookies", "files"} & set(inspect.signature(fs.get).parameters)


# ── no credentials, cookies or auth headers ─────────────────────────────────
@pytest.mark.parametrize("h", ["Authorization", "Cookie", "Proxy-Authorization"])
def test_credential_headers_are_refused(h):
    with pytest.raises(fs.FetchRefused):
        _get("https://example.org/a", headers={h: "x"})


def test_mutation_without_the_header_rule_an_auth_header_goes_out(monkeypatch):
    monkeypatch.setattr(fs, "FORBIDDEN_HEADERS", ())
    _out, sess = _get("https://example.org/a", headers={"Authorization": "Bearer x"})
    assert sess.sent[0]["headers"]["Authorization"] == "Bearer x"


def test_credentials_in_the_url_are_refused():
    assert fs.url_problem("https://user:pw@example.org/", PUBLIC) == "credentials in the url"


def test_a_set_cookie_is_never_sent_back():
    first = Resp(302, b"", {"location": "https://example.org/b"})
    sess = Session(first, Resp())
    sess.cookies.set("sid", "abc")                                    # as if the server had set one
    fs.get("https://example.org/a", session=sess, resolve=PUBLIC, clock=NoWait())
    assert all(not s["cookies"] for s in sess.sent)
    assert sess.trust_env is False


def test_mutation_without_clearing_a_cookie_would_be_sent(monkeypatch):
    sess = Session(Resp())
    sess.cookies.set("sid", "abc")
    monkeypatch.setattr(sess.cookies, "clear", lambda *a, **k: None)
    fs.get("https://example.org/a", session=sess, resolve=PUBLIC, clock=NoWait())
    assert sess.sent[0]["cookies"] == {"sid": "abc"}


# ── no private, loopback or LAN address ─────────────────────────────────────
@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost/", "http://192.168.1.10/",
                                 "http://10.1.2.3/", "http://[::1]/", "http://169.254.169.254/",
                                 "http://printer.local/"])
def test_private_loopback_and_lan_literals_are_refused(url):
    with pytest.raises(fs.FetchRefused):
        _get(url)


def test_a_public_name_that_resolves_to_a_lan_address_is_refused():
    with pytest.raises(fs.FetchRefused, match="resolves to"):
        _get("https://innocent.example/", resolve=PRIVATE)


def test_a_redirect_into_the_lan_is_refused_on_the_hop():
    with pytest.raises(fs.FetchRefused):
        _get("https://example.org/a", Resp(302, b"", {"location": "http://127.0.0.1/admin"}))


def test_mutation_without_the_address_rule_the_lan_is_fetched(monkeypatch):
    monkeypatch.setattr(fs, "url_problem", lambda url, resolve=None: None)
    out, sess = _get("http://192.168.1.10/")
    assert sess.sent[0]["url"] == "http://192.168.1.10/" and out["status"] == 200


# ── body <= 5 MB ────────────────────────────────────────────────────────────
def test_a_body_over_the_limit_is_refused_while_streaming():
    with pytest.raises(fs.FetchRefused, match="exceeds"):
        _get("https://example.org/a", Resp(200, b"x" * 101), max_bytes=100)


def test_a_declared_length_over_the_limit_is_refused_before_reading():
    with pytest.raises(fs.FetchRefused):
        _get("https://example.org/a", Resp(200, b"", {"content-length": str(fs.MAX_BYTES + 1)}))


def test_mutation_without_the_size_rule_the_oversize_body_is_kept():
    out, _ = _get("https://example.org/a", Resp(200, b"x" * 101), max_bytes=10**9)
    assert out["bytes"] == 101
    assert fs.MAX_BYTES == 5 * 1024 * 1024


# ── timeout 30 s ────────────────────────────────────────────────────────────
def test_the_timeout_is_passed_and_capped():
    _out, sess = _get("https://example.org/a", timeout=30)
    assert sess.sent[0]["kw"]["timeout"] == 30
    with pytest.raises(fs.FetchRefused):
        _get("https://example.org/a", timeout=31)


def test_mutation_without_the_cap_a_long_timeout_goes_out(monkeypatch):
    monkeypatch.setattr(fs, "TIMEOUT_S", 10**6)
    _out, sess = _get("https://example.org/a", timeout=600)
    assert sess.sent[0]["kw"]["timeout"] == 600


# ── one request per host per 2 s ────────────────────────────────────────────
def test_the_second_request_to_a_host_waits_two_seconds():
    t = {"now": 100.0}
    slept = []
    clock = fs.HostClock(now=lambda: t["now"], sleep=slept.append)
    clock.wait("a.org")
    t["now"] = 100.5
    clock.wait("a.org")
    clock.wait("b.org")
    assert slept == [1.5]


def test_mutation_without_the_host_clock_nothing_waits():
    slept = []
    clock = fs.HostClock(interval=0.0, now=lambda: 0.0, sleep=slept.append)
    clock.wait("a.org"); clock.wait("a.org")
    assert slept == [] and fs.HOST_INTERVAL_S == 2.0


def test_get_uses_the_clock_per_host_on_every_hop():
    seen = []

    class Rec(fs.HostClock):
        def wait(self, host):
            seen.append(host)
            return 0.0
    sess = Session(Resp(302, b"", {"location": "https://b.org/x"}), Resp())
    fs.get("https://a.org/", session=sess, resolve=PUBLIC, clock=Rec())
    assert seen == ["a.org", "b.org"]


# ── parking ─────────────────────────────────────────────────────────────────
def test_three_consecutive_failures_park_and_one_success_resets(tmp_path):
    p = tmp_path / "park.json"
    for _ in range(2):
        fs.record("s", ok=False, err="boom", path=p)
    assert not fs.is_parked("s", p)
    fs.record("s", ok=True, path=p)
    for _ in range(2):
        fs.record("s", ok=False, err="boom", path=p)
    assert not fs.is_parked("s", p), "the success did not reset the streak"
    fs.record("s", ok=False, err="boom", path=p)
    assert fs.is_parked("s", p)


def test_mutation_parking_after_one_failure_would_park_early(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "PARK_AFTER", 1)
    fs.record("s", ok=False, err="x", path=tmp_path / "p.json")
    assert fs.is_parked("s", tmp_path / "p.json")


def test_the_worker_skips_a_parked_source_unless_a_need_names_it(tmp_path, monkeypatch):
    from scripts import data_feed_reader as w
    import core.source_lifecycle as life
    monkeypatch.setattr(life, "observe", lambda sid, **kw: {"state": "CANDIDATE"})
    park = tmp_path / "park.json"
    for _ in range(3):
        fs.record("dead", ok=False, err="x", path=park)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"sources": [{"id": "dead", "url": "https://x.org", "path": "v"}],
                                "timeout_sec": 5}), encoding="utf-8")
    calls = []

    def getter(url, timeout):
        calls.append(url)
        return 200, {"v": 1}, None, '{"v": 1}'
    kw = dict(queue_dir=tmp_path / "q", getter=getter, dry_run=True, discovered_path=tmp_path / "n.json",
              lifecycle_state={}, ledger=tmp_path / "l.jsonl", parking=park)
    r = w.run(seed, **kw)
    assert r["parked"][0]["source_id"] == "dead" and calls == []
    r = w.run(seed, wanted={"dead"}, **kw)
    assert calls == ["https://x.org"] and not r["parked"] and not fs.is_parked("dead", park)


def test_selftest_reports_and_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(fs, "PARKING", tmp_path / "none.json")
    r = fs.selftest()
    assert r["ok"] and r["integrations"]["worker fetches through fetch_standard.get"] == "LIVE"
    assert not list(tmp_path.iterdir())


@pytest.fixture(autouse=True)
def _baton_in_tmp(tmp_path, monkeypatch):
    from core import turn
    monkeypatch.setattr(turn, "STATE", tmp_path / "turn.json")


def test_no_fetch_happens_in_the_brains_turn(tmp_path):
    from core import turn
    turn.take(turn.BRAIN)
    sess = Session(Resp())
    with pytest.raises(fs.FetchRefused, match="baton is BRAIN"):
        fs.get("https://example.org/a", session=sess, resolve=PUBLIC, clock=NoWait())
    assert sess.sent == [], "a request went out in the brain's turn"


def test_mutation_without_the_baton_check_the_fetch_would_go_out(tmp_path, monkeypatch):
    from core import turn
    turn.take(turn.BRAIN)
    monkeypatch.setattr(turn, "state", lambda path=None: {"holder": None})
    out, sess = _get("https://example.org/a")
    assert sess.sent and out["status"] == 200


def test_the_agents_turn_may_fetch(tmp_path):
    from core import turn
    turn.take(turn.AGENTS)
    out, sess = _get("https://example.org/a")
    assert out["status"] == 200
