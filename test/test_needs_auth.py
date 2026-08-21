#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_needs_auth.py — A QUIET SKIP IS INVISIBLE.

WHAT WAS WRONG
---------------
config/dead_sources.json records sources gated behind a credential, and the
cycle skips them quietly — deliberately, so a missing key does not fail every
run. That is correct, and it is exactly why nothing ever happened about them:

    ucdp_api   NEEDS_AUTH since 2026-07-13   UCDP_ACCESS_TOKEN
    eia_api    NEEDS_AUTH since 2026-08-15   EIA_API_KEY

The registry's own evidence line for EIA says it: "fetch_eia() връщаше {} без
ключ, БЕЗ да го обяви. Секцията energy стоеше празна в снимката и въпреки това
се броеше сред '20 източника'." The only thing between the axis and its data
was two minutes on a registration form, and nobody was told.

THE THREE PROOFS
-----------------
  * EIA produces exactly one message
  * a re-run produces zero
  * a key dropped into .env activates the source with no restart and no code

The third is the UCDP precedent, and it is already visible on this machine:
UCDP_ACCESS_TOKEN is in .env, so ucdp_api reads ACTIVE while eia_api reads
WAITING. Nothing flipped a switch.

    venv\\Scripts\\python.exe -m pytest test/test_needs_auth.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core import needs_auth as na

REPO = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def registry(tmp_path):
    p = tmp_path / "dead_sources.json"
    p.write_text(json.dumps({
        "_README": ["not a source"],
        "eia_api": {"status": "NEEDS_AUTH", "env_key": "EIA_API_KEY",
                    "since": "2026-08-15",
                    "note": "Безплатен ключ: https://www.eia.gov/opendata/register.php ."},
        "gone_forever": {"status": "DEAD", "since": "2026-01-01"},
    }), encoding="utf-8")
    return p


@pytest.fixture
def empty_env(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("SOMETHING_ELSE=x\n", encoding="utf-8")
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    return p


def _capture():
    sent = []
    return sent, lambda source, text: sent.append({"source": source, "text": text})


# ---------------------------------------------------------------------------
# (a) THE FIRST TWO PROOFS
# ---------------------------------------------------------------------------

def test_eia_produces_exactly_one_message(tmp_path, registry, empty_env):
    sent, sender = _capture()
    result = na.run(registry_path=registry, env_path=empty_env,
                    stamp_path=tmp_path / "stamp.json", sender=sender)

    assert len(sent) == 1, f"{len(sent)} messages for one gated source"
    assert sent[0]["source"] == "eia_api"
    assert result["asked"] == ["eia_api"]


def test_a_re_run_produces_zero(tmp_path, registry, empty_env):
    """A daily nag for something that needs a human action is how a channel
    gets muted — and then the real alarm is muted with it."""
    stamp = tmp_path / "stamp.json"
    sent, sender = _capture()

    na.run(registry_path=registry, env_path=empty_env, stamp_path=stamp,
           sender=sender)
    second = na.run(registry_path=registry, env_path=empty_env, stamp_path=stamp,
                    sender=sender)

    assert len(sent) == 1, (
        f"\n  THE SAME REQUEST WENT OUT {len(sent)} TIMES.\n"
        f"  One message per source per WEEK. A second one the next cycle\n"
        f"  teaches the operator to ignore the channel.\n"
    )
    assert second["asked"] == []
    assert second["skipped"] == ["eia_api"]


def test_it_asks_again_after_a_week(tmp_path, registry, empty_env):
    """Silence forever is not the answer either — the key is still missing."""
    from datetime import datetime, timedelta, timezone
    stamp = tmp_path / "stamp.json"
    sent, sender = _capture()
    na.run(registry_path=registry, env_path=empty_env, stamp_path=stamp,
           sender=sender)

    old = (datetime.now(timezone.utc) - timedelta(days=na.ASK_EVERY_DAYS + 1))
    stamp.write_text(json.dumps({"eia_api": {"asked_at": old.isoformat()}}),
                     encoding="utf-8")

    na.run(registry_path=registry, env_path=empty_env, stamp_path=stamp,
           sender=sender)
    assert len(sent) == 2


# ---------------------------------------------------------------------------
# (b) THE THIRD PROOF — the key arrives and the source activates
# ---------------------------------------------------------------------------

def test_a_key_dropped_into_env_activates_the_source(tmp_path, registry,
                                                     monkeypatch):
    """No restart, no code. The reader checks the environment every run."""
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    env = tmp_path / ".env"
    stamp = tmp_path / "stamp.json"

    env.write_text("OTHER=1\n", encoding="utf-8")
    before = na.scan(registry, env)
    assert before[0]["state"] == na.WAITING

    # the human pastes the key while everything is still running
    env.write_text("OTHER=1\nEIA_API_KEY=abc123\n", encoding="utf-8")

    after = na.scan(registry, env)
    assert after[0]["state"] == na.ACTIVE, (
        "\n  THE KEY IS IN .env AND THE SOURCE IS STILL WAITING.\n"
        "  Activation must need no restart and no code — that is the UCDP\n"
        "  precedent and the whole promise the message makes.\n"
    )

    sent, sender = _capture()
    result = na.run(registry_path=registry, env_path=env, stamp_path=stamp,
                    sender=sender)
    assert sent == [], "it asked for a key that is already there"
    assert result["asked"] == []


def test_an_empty_value_does_not_count_as_a_key(tmp_path, registry, monkeypatch):
    """EIA_API_KEY= with nothing after it is not a credential."""
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("EIA_API_KEY=\n", encoding="utf-8")
    assert na.scan(registry, env)[0]["state"] == na.WAITING


def test_the_stamp_is_cleared_when_a_source_activates(tmp_path, registry,
                                                      monkeypatch):
    """So that if the key is ever removed, the ask starts again."""
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    env = tmp_path / ".env"
    stamp = tmp_path / "stamp.json"
    env.write_text("OTHER=1\n", encoding="utf-8")
    sent, sender = _capture()
    na.run(registry_path=registry, env_path=env, stamp_path=stamp, sender=sender)
    assert "eia_api" in json.loads(stamp.read_text(encoding="utf-8"))

    env.write_text("EIA_API_KEY=abc\n", encoding="utf-8")
    result = na.run(registry_path=registry, env_path=env, stamp_path=stamp,
                    sender=sender)
    assert result["activated"] == ["eia_api"]
    assert "eia_api" not in json.loads(stamp.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (c) The message carries what a person needs
# ---------------------------------------------------------------------------

def test_the_message_names_link_action_and_variable(registry, empty_env):
    row = na.scan(registry, empty_env)[0]
    text = na.message(row)

    assert "https://www.eia.gov/opendata/register.php" in text
    assert "EIA_API_KEY=" in text
    assert ".env" in text
    assert "няма нужда от рестарт" in text


def test_the_registration_link_is_extracted_from_whatever_field_holds_it():
    """The registry records the URL under different keys per source."""
    assert na._link({"note": "ключ: https://a.example/reg ."}) == \
        "https://a.example/reg"
    assert na._link({"how_to_reenable": "see https://b.example/apidocs/ then"}) == \
        "https://b.example/apidocs/"
    assert na._link({"status": "NEEDS_AUTH"}) is None


# ---------------------------------------------------------------------------
# (d) Scope: only gated sources, never the dead ones
# ---------------------------------------------------------------------------

def test_a_dead_source_is_never_asked_about(registry, empty_env):
    """DEAD means it no longer exists. No key will bring it back."""
    rows = na.scan(registry, empty_env)
    assert [r["source"] for r in rows] == ["eia_api"]


def test_a_gated_source_without_an_env_key_is_ignored(tmp_path, empty_env):
    """Nothing to tell the person to do."""
    p = tmp_path / "reg.json"
    p.write_text(json.dumps({"x": {"status": "NEEDS_AUTH"}}), encoding="utf-8")
    assert na.scan(p, empty_env) == []


# ---------------------------------------------------------------------------
# (e) The live machine
# ---------------------------------------------------------------------------

def test_the_live_registry_shows_ucdp_active_and_eia_waiting():
    """The UCDP precedent, on this machine: its token is in .env, so it reads
    ACTIVE with nothing having been switched."""
    rows = {r["source"]: r for r in na.scan()}
    assert rows["ucdp_api"]["state"] == na.ACTIVE
    assert rows["eia_api"]["state"] == na.WAITING
    assert rows["eia_api"]["age_days"] and rows["eia_api"]["age_days"] > 5


def test_the_waiting_sources_reach_the_cycle_report():
    waiting = na.for_cycle_report()
    assert any(r["source"] == "eia_api" for r in waiting)
    assert all(r["state"] == na.WAITING for r in waiting)


def test_the_runner_calls_it():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "core.needs_auth" in src, "a detector nobody runs asks nobody"
