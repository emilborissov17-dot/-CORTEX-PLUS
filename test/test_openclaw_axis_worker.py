#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_openclaw_axis_worker.py — WHAT COMES BACK FROM OUTSIDE IS A NUMBER OR A REFUSAL.

WHY
----
This worker is the only thing in CORTEX that reaches the outside world for an
axis number. agents/axis/axis_feed.py guards against a MODEL writing prose
where a measurement belongs; this guards one step further out, against a remote
service answering with a string, a null, an error object or an HTML error page
— and that landing in the queue looking like something somebody measured.

config/openclaw_sources.json is the ALLOWLIST. Nothing outside it is fetched,
so widening what CORTEX touches is a human edit, not a runtime decision.

RUN ONCE ON THE MACHINE, 20 August 2026:

    [DMZ] OK      usgs_quakes_m45_24h      DEEP_TIME_RISKS_REVIEW       24.0 events_24h
    [DMZ] OK      open_meteo_surface_temp  CLIMATE_GLOBAL_RISK_REVIEW   25.9 celsius
    [DMZ] OK      celestrak_launched_30d   SPACE_INFRASTRUCTURE_REVIEW  243.0 objects_30d
    [DMZ] REFUSED deliberately_broken_path at 'total': cannot descend into int (24)

Three real numbers, one named refusal. The broken entry is in the allowlist ON
PURPOSE so the refusal path runs every time, not only under test.

NO TEST HERE TOUCHES THE NETWORK. Every case injects a fake getter; the live
run above is the evidence that the real path works, and it was done by hand.

    venv\\Scripts\\python.exe -m pytest test/test_openclaw_axis_worker.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from scripts.openclaw_axis_worker import (Refused, as_number, fetch_one,
                                          load_sources, run, walk)

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCES = REPO / "config" / "openclaw_sources.json"


def getter_returning(payload, status=200, err=None):
    def _get(url, timeout):
        return status, payload, err
    return _get


SRC = {"id": "s1", "axis": "AX", "key": "k", "url": "https://example.invalid/x",
       "path": "count", "unit": "u", "org": "O"}


# ---------------------------------------------------------------------------
# (a) THE NEGATIVE CONTROL — a broken path refuses, with a reason
# ---------------------------------------------------------------------------

def test_a_path_that_walks_into_a_number_is_refused():
    """The live case: 'count.total.missing' against {'count': 24}."""
    with pytest.raises(Refused) as caught:
        walk({"count": 24}, "count.total.missing")

    reason = str(caught.value)
    assert "total" in reason, "the refusal must name the segment that broke"
    assert "int" in reason, "and what was there instead"


def test_a_missing_key_refusal_lists_what_was_there():
    """'no key X' sends the reader to the API docs; listing the keys sends them
    to the right line of the config."""
    with pytest.raises(Refused) as caught:
        walk({"count": 24, "maxAllowed": 20000}, "total")
    assert "count" in str(caught.value) and "maxAllowed" in str(caught.value)


def test_the_refusal_is_written_down_with_its_reason(tmp_path):
    """A source that has quietly rotted must look different from one nobody
    asked."""
    src = {**SRC, "path": "count.total.missing"}
    result = run(sources_path=_sources_file(tmp_path, [src]),
                 queue_dir=tmp_path / "q",
                 getter=getter_returning({"count": 24}))

    assert result["feeds"] == []
    assert len(result["refusals"]) == 1

    rows = _read(tmp_path / "q" / "external_refusals.jsonl")
    assert len(rows) == 1
    assert rows[0]["status"] == "REFUSED"
    assert rows[0]["source_id"] == "s1"
    assert rows[0]["url"] == SRC["url"], "the refusal keeps the url it failed on"
    assert "cannot descend into int" in rows[0]["reason"]
    assert not (tmp_path / "q" / "external_feeds.jsonl").exists(), (
        "a refused source must not also write a feed"
    )


# ---------------------------------------------------------------------------
# (b) Everything else that is not a number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["24", "HIGH", None, [1, 2], {"a": 1}, True])
def test_a_non_numeric_value_is_refused(value):
    with pytest.raises(Refused):
        as_number(value, "where")


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_a_non_finite_number_is_refused(value):
    with pytest.raises(Refused):
        as_number(value, "where")


def test_a_string_that_looks_like_a_number_is_still_a_string(tmp_path):
    """APIs return "24" constantly. Coercing it would let a formatting change
    upstream become a silent unit change here."""
    result = run(sources_path=_sources_file(tmp_path, [SRC]),
                 queue_dir=tmp_path / "q",
                 getter=getter_returning({"count": "24"}))
    assert result["feeds"] == []
    assert "expected a number, got str" in result["refusals"][0]["reason"]


def test_a_non_200_response_is_refused(tmp_path):
    result = run(sources_path=_sources_file(tmp_path, [SRC]),
                 queue_dir=tmp_path / "q",
                 getter=getter_returning(None, status=503))
    assert "HTTP 503" in result["refusals"][0]["reason"]


def test_an_unreachable_host_is_refused_not_raised(tmp_path):
    result = run(sources_path=_sources_file(tmp_path, [SRC]),
                 queue_dir=tmp_path / "q",
                 getter=getter_returning(None, status=None,
                                         err="ConnectionError: no route"))
    assert "ConnectionError" in result["refusals"][0]["reason"]


def test_an_html_error_page_is_refused(tmp_path):
    """A 200 with an HTML body is the classic captive-portal / maintenance page."""
    result = run(sources_path=_sources_file(tmp_path, [SRC]),
                 queue_dir=tmp_path / "q",
                 getter=getter_returning(None, status=200,
                                         err="body is not JSON ('<html>...')"))
    assert "not JSON" in result["refusals"][0]["reason"]


# ---------------------------------------------------------------------------
# (c) The happy path
# ---------------------------------------------------------------------------

def test_a_real_number_becomes_a_feed_row(tmp_path):
    """POSITIVE CONTROL — a worker that refuses everything is not a worker."""
    result = run(sources_path=_sources_file(tmp_path, [SRC]),
                 queue_dir=tmp_path / "q",
                 getter=getter_returning({"count": 24}))

    assert len(result["feeds"]) == 1
    row = _read(tmp_path / "q" / "external_feeds.jsonl")[0]
    assert row["value"] == 24.0
    assert isinstance(row["value"], float)
    assert row["axis"] == "AX" and row["key"] == "k"
    assert row["org"] == "O" and row["unit"] == "u"
    assert row["status"] == "PRESENT"


@pytest.mark.parametrize("payload,path,expected", [
    ({"count": 40}, "count", 40.0),
    ({"current": {"temperature_2m": 25.9}}, "current.temperature_2m", 25.9),
    ([{"a": 1}, {"a": 2}, {"a": 3}], "#len", 3.0),
    ([{"v": 7}], "0.v", 7.0),
])
def test_the_path_syntax_resolves_the_shapes_the_allowlist_uses(payload, path,
                                                                expected):
    assert as_number(walk(payload, path), "w") == expected


def test_the_queue_is_a_ledger_not_a_snapshot(tmp_path):
    q = tmp_path / "q"
    sources = _sources_file(tmp_path, [SRC])
    run(sources_path=sources, queue_dir=q, getter=getter_returning({"count": 1}))
    run(sources_path=sources, queue_dir=q, getter=getter_returning({"count": 2}))
    rows = _read(q / "external_feeds.jsonl")
    assert [r["value"] for r in rows] == [1.0, 2.0], "the worker overwrote history"


def test_dry_run_writes_nothing(tmp_path):
    result = run(sources_path=_sources_file(tmp_path, [SRC]),
                 queue_dir=tmp_path / "q",
                 getter=getter_returning({"count": 24}), dry_run=True)
    assert len(result["feeds"]) == 1
    assert not (tmp_path / "q").exists()


# ---------------------------------------------------------------------------
# (d) The allowlist itself
# ---------------------------------------------------------------------------

def test_the_shipped_allowlist_is_well_formed():
    sources, timeout = load_sources()
    assert timeout > 0
    assert len(sources) >= 4
    for s in sources:
        for field in ("id", "axis", "key", "url", "path"):
            assert s.get(field), f"{s.get('id')} is missing {field}"
        assert s["url"].startswith("https://"), f"{s['id']} is not https"


def test_the_allowlist_keeps_one_deliberately_broken_entry():
    """It exercises the refusal path on every real run, not only under test.
    Delete it and refusals become something nobody sees until they matter."""
    sources, _ = load_sources()
    broken = [s for s in sources if "DELIBERATELY BROKEN" in (s.get("why") or "")]
    assert len(broken) == 1, "the deliberate refusal case is gone from the allowlist"
    assert broken[0]["path"].count(".") >= 2


def test_every_allowlisted_axis_exists_in_target_config():
    """A feed for an axis the goal does not have is a number nobody asked for."""
    from agents.axis.axis_feed import axes_from_config
    known = set(axes_from_config())
    for s in load_sources()[0]:
        assert s["axis"] in known, f"{s['id']} feeds unknown axis {s['axis']}"


# ---------------------------------------------------------------------------

def _sources_file(tmp_path, sources) -> pathlib.Path:
    p = tmp_path / "sources.json"
    p.write_text(json.dumps({"timeout_sec": 5, "sources": sources}),
                 encoding="utf-8")
    return p


def _read(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]
