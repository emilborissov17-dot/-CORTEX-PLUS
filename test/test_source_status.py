"""Permanent test suite for dead/gated data sources (item 5).

Covers:
  - core/source_status.py — the DEAD / NEEDS_AUTH registry
  - fetch_ucdp   — must skip quietly without a token, and use the CORRECT
                   resource name + version when a token is present
  - fetch_sea_level — must point at the current CU Boulder file path

No test makes a network call: the HTTP layer is stubbed everywhere.
"""
import json

import pytest

import core.source_status as ss
import core.global_indicators as gi


@pytest.fixture(autouse=True)
def clean_announcements():
    ss.reset_announcements()
    yield
    ss.reset_announcements()


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Point the registry at a throwaway config file."""
    def _write(entries):
        p = tmp_path / "dead_sources.json"
        p.write_text(json.dumps(entries), encoding="utf-8")
        monkeypatch.setattr(ss, "DEAD_SOURCES_PATH", p)
        monkeypatch.setattr(ss, "BASE", tmp_path)  # so .env lookup is isolated
        return p
    return _write


# ---------------------------------------------------------------------------
# Registry semantics
# ---------------------------------------------------------------------------


def test_unregistered_source_is_never_skipped(registry):
    registry({})
    assert ss.skip_reason("some_live_api") is None
    assert ss.is_skipped("some_live_api") is False


def test_dead_source_is_always_skipped(registry):
    registry({"gone_api": {"status": "DEAD", "since": "2026-01-01",
                           "reason": "shut down by the publisher"}})
    reason = ss.skip_reason("gone_api")
    assert reason is not None
    assert "DEAD since 2026-01-01" in reason
    assert ss.is_skipped("gone_api") is True


def test_needs_auth_without_credential_is_skipped(registry, monkeypatch):
    registry({"gated": {"status": "NEEDS_AUTH", "since": "2026-07-13",
                        "env_key": "SOME_TOKEN"}})
    monkeypatch.delenv("SOME_TOKEN", raising=False)

    reason = ss.skip_reason("gated")
    assert reason is not None
    assert "SOME_TOKEN" in reason, "must tell the operator which var to set"


def test_needs_auth_WITH_credential_is_live_again(registry, monkeypatch):
    """The whole point of NEEDS_AUTH vs DEAD: supplying the token re-enables it."""
    registry({"gated": {"status": "NEEDS_AUTH", "since": "2026-07-13",
                        "env_key": "SOME_TOKEN"}})
    monkeypatch.setenv("SOME_TOKEN", "secret-value")

    assert ss.skip_reason("gated") is None
    assert ss.is_skipped("gated") is False
    assert ss.credential_for("gated") == "secret-value"


def test_credential_is_read_from_dotenv_when_not_in_env(registry, tmp_path, monkeypatch):
    registry({"gated": {"status": "NEEDS_AUTH", "since": "2026-07-13",
                        "env_key": "SOME_TOKEN"}})
    monkeypatch.delenv("SOME_TOKEN", raising=False)
    (tmp_path / ".env").write_text("SOME_TOKEN=from-dotenv\n", encoding="utf-8")

    assert ss.credential_for("gated") == "from-dotenv"


def test_unknown_status_fails_open(registry):
    """A typo in the config must not silently disable a working source."""
    registry({"weird": {"status": "PROBABLY_FINE", "since": "2026-01-01"}})
    assert ss.skip_reason("weird") is None


def test_missing_registry_file_means_everything_is_live(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "DEAD_SOURCES_PATH", tmp_path / "nope.json")
    assert ss.skip_reason("anything") is None


def test_corrupt_registry_fails_open(tmp_path, monkeypatch):
    p = tmp_path / "dead_sources.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(ss, "DEAD_SOURCES_PATH", p)
    assert ss.skip_reason("anything") is None, "a broken config must not kill all sources"


def test_skip_is_announced_only_once(registry, capsys):
    registry({"gone": {"status": "DEAD", "since": "2026-01-01", "reason": "x"}})

    ss.is_skipped("gone")
    ss.is_skipped("gone")
    ss.is_skipped("gone")

    assert capsys.readouterr().out.count("skipped") == 1, \
        "a dead source must not spam the log once per call"


def test_underscore_keys_are_not_sources(registry):
    """_README in the config file must not be mistaken for a source entry."""
    registry({"_README": ["notes"], "real": {"status": "DEAD", "since": "2026-01-01"}})
    assert ss.get_status("_README") is None


# ---------------------------------------------------------------------------
# The real registered entry
# ---------------------------------------------------------------------------


def test_ucdp_is_registered_in_the_real_config():
    entry = ss.get_status("ucdp_api")
    assert entry is not None, "UCDP must be declared in config/dead_sources.json"
    assert entry["status"] == "NEEDS_AUTH"
    assert entry["env_key"] == "UCDP_ACCESS_TOKEN"
    assert entry["since"], "a dead/gated source must record WHEN it died"


# ---------------------------------------------------------------------------
# fetch_ucdp — the actual bug (404 on every version, every cycle)
# ---------------------------------------------------------------------------


def test_fetch_ucdp_makes_no_http_call_without_a_token(monkeypatch):
    """THE regression: it used to fire 4 doomed requests per cycle."""
    called = []
    monkeypatch.setattr(gi, "_get", lambda *a, **kw: called.append(a) or None)
    monkeypatch.setattr(gi, "is_skipped", lambda key: True)

    assert gi.fetch_ucdp() == {}
    assert called == [], "no HTTP call may be made for a NEEDS_AUTH source without a token"


def test_fetch_ucdp_uses_correct_resource_and_version_with_a_token(monkeypatch):
    """With a token it must hit /ucdpprioconflict/26.1 — not /conflict/25.1."""
    seen = {}

    def fake_get(url, timeout=20, params=None, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        return {"TotalCount": 55}

    monkeypatch.setattr(gi, "_get", fake_get)
    monkeypatch.setattr(gi, "is_skipped", lambda key: False)
    monkeypatch.setattr(gi, "credential_for", lambda key: "tok")

    got = gi.fetch_ucdp()

    assert got["active_armed_conflicts"] == 55
    assert "ucdpprioconflict" in seen["url"], "wrong resource name was the 404 cause"
    assert "/conflict/" not in seen["url"], "the old, wrong resource name is back"
    assert "26.1" in seen["url"], "26.1 is the current version"
    assert seen["headers"] == {"x-ucdp-access-token": "tok"}


def test_fetch_ucdp_returns_empty_when_api_gives_nothing(monkeypatch):
    monkeypatch.setattr(gi, "_get", lambda *a, **kw: None)
    monkeypatch.setattr(gi, "is_skipped", lambda key: False)
    monkeypatch.setattr(gi, "credential_for", lambda key: "tok")
    assert gi.fetch_ucdp() == {}


# ---------------------------------------------------------------------------
# fetch_sea_level — the dated-URL 404
# ---------------------------------------------------------------------------


def test_sea_level_urls_are_the_current_ones():
    """The dated /sites/default/files/<YYYY-MM>/ paths are gone for good."""
    assert gi._SEA_LEVEL_URLS, "there must be at least one sea level URL"
    primary = gi._SEA_LEVEL_URLS[0]
    assert "2026_rel1" in primary, "primary must be the current release"
    for url in gi._SEA_LEVEL_URLS:
        assert "/sites/default/files/" not in url, \
            "the dated Drupal upload paths 404 — they must not come back"


def test_sea_level_parses_the_real_file_format(monkeypatch):
    """Two columns: <year_fraction> <mm>, comments start with '#'."""
    sample = (
        "# Date      2026_rel1 w/ seasonal signals and GIA removed (mm)\n"
        "1992.9594981674402      -16.668\n"
        "2026.100765507717      95.331\n"
    )
    monkeypatch.setattr(gi, "_get", lambda *a, **kw: sample)

    got = gi.fetch_sea_level()

    assert got["sea_level_rise_mm"] == 95.3      # last row, rounded
    assert got["sea_level_year_fraction"] == 2026.101
    assert got["sea_level_baseline"] == "1993"


def test_sea_level_falls_back_to_older_release(monkeypatch):
    """If the newest release URL dies, try the previous one before giving up."""
    calls = []

    def fake_get(url, timeout=20, params=None, headers=None):
        calls.append(url)
        if "2026_rel1" in url:
            return None                      # simulate the new release 404ing
        return "# hdr\n2025.5   90.0\n"

    monkeypatch.setattr(gi, "_get", fake_get)

    got = gi.fetch_sea_level()

    assert got["sea_level_rise_mm"] == 90.0
    assert len(calls) == 2, "must have tried the newest release first"


def test_sea_level_returns_empty_when_all_urls_dead(monkeypatch):
    monkeypatch.setattr(gi, "_get", lambda *a, **kw: None)
    assert gi.fetch_sea_level() == {}
