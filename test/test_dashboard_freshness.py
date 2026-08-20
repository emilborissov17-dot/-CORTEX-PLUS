#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_dashboard_freshness.py — NEVER APPROVE AGAINST A PAGE OLDER THAN THE DATA.

WHAT WENT WRONG (measured 20 August 2026)
------------------------------------------
`cortex_approval_server.py` served `output/cortex_dashboard_live.html` at route "/",
injecting the approval panel into it, with no check of any kind on the file's age.

That file is not a live render. Nothing in the cycle writes it — grepping the tree for
"dashboard_generator" across *.py returns only that module's own docstring, and
hypercortex_runner.py / fast_cycle_runner.py / run_daily.py never mention a dashboard.
It is produced by hand, by running cortex_dashboard_generator.py as __main__.

So it drifts:

    output/cortex_dashboard_live.html   Apr 13 17:29
    output/cortex_scores_latest.json    Aug 20 04:33

Four months, under a filename containing the word "live". The page carries its own
generation timestamp — stamped whenever it was last hand-run — so it reads as current
while showing scores from another season. That was the surface an operator looked at
while deciding whether to approve a self-modification proposal.

WHY THIS IS A TEST AND NOT A COMMENT
-------------------------------------
The gate is four lines and deleting it changes nothing visible. The server still
starts, "/" still returns 200, the page still renders, the buttons still work. The only
difference is which scores the operator was looking at when they clicked Approve — and
that difference is invisible at runtime, forever, until it matters once.

THE NEGATIVE CONTROL
---------------------
test_a_dashboard_older_than_the_scores_is_refused asserts DASHBOARD_MARKER is ABSENT
from the response. That marker is the body of the fixture dashboard. If the gate is
removed, index() falls through to the serve path, the marker appears, and this test
fails. A test that only checked "the stale page mentions a timestamp" would still pass
against a served stale dashboard — this one cannot.

Proven in both directions before commit: with the gate present the refusal test passes
and the serve test passes; with the staleness branch deleted, the refusal test fails
and the serve test still passes.

WHAT THIS FILE DOES NOT DO
---------------------------
It does not test cortex_dashboard_generator.py, whose arithmetic is knowingly broken
and deliberately untouched (a separate decision). It asserts only which page the
approval server hands back, given two files with known mtimes.

    venv\\Scripts\\python.exe -m pytest test/test_dashboard_freshness.py -v
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

import cortex_approval_server as srv

REPO = Path(__file__).resolve().parents[1]

# The body of the fixture dashboard. Its presence in a response means the real
# dashboard was served; its absence means it was withheld. This is the whole negative
# control.
DASHBOARD_MARKER = "REAL-DASHBOARD-BODY-6f2ac1"
FIXTURE_DASHBOARD = f"<html><body><h1>{DASHBOARD_MARKER}</h1></body></html>"

# A fixed instant. The expected timestamp strings are computed from the epoch seconds
# directly and never from the server's own formatter — if _fmt() broke, these
# assertions would catch it rather than agree with it.
BASE_EPOCH = 1_754_000_000
HOUR = 3600


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")


def _write(path: Path, text: str, epoch: int) -> Path:
    path.write_text(text, encoding="utf-8")
    os.utime(path, (epoch, epoch))
    return path


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A test client whose dashboard and scores paths point into tmp_path.

    Nothing under output/ is read or written by these tests.
    """
    monkeypatch.setattr(srv, "DASHBOARD_FILE", tmp_path / "cortex_dashboard_live.html")
    monkeypatch.setattr(srv, "SCORES_FILE", tmp_path / "cortex_scores_latest.json")
    srv.app.config.update(TESTING=True)
    return srv.app.test_client()


def _get(client) -> str:
    response = client.get("/")
    assert response.status_code == 200
    return response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# (a) The two directions
# ---------------------------------------------------------------------------

def test_a_dashboard_newer_than_the_scores_is_served(client, tmp_path):
    """POSITIVE CONTROL: a fresh dashboard must actually reach the operator.

    Without this, a gate that refused everything unconditionally would look correct.
    """
    _write(tmp_path / "cortex_dashboard_live.html", FIXTURE_DASHBOARD, BASE_EPOCH + HOUR)
    _write(tmp_path / "cortex_scores_latest.json", "{}", BASE_EPOCH)

    body = _get(client)

    assert DASHBOARD_MARKER in body, "a dashboard newer than the scores was withheld"
    assert "approval-panel" in body, "the approval panel was not injected"
    assert "STALE" not in body


def test_a_dashboard_older_than_the_scores_is_refused(client, tmp_path):
    """NEGATIVE CONTROL: delete the gate and this test goes red.

    The marker assertion is the load-bearing one. The timestamp assertions only
    describe the refusal page; the marker proves the stale page was not served.
    """
    _write(tmp_path / "cortex_dashboard_live.html", FIXTURE_DASHBOARD, BASE_EPOCH)
    _write(tmp_path / "cortex_scores_latest.json", "{}", BASE_EPOCH + HOUR)

    body = _get(client)

    assert DASHBOARD_MARKER not in body, (
        "THE STALE DASHBOARD WAS SERVED. The freshness gate in "
        "cortex_approval_server.index() is gone or no longer fires: a page older than "
        "output/cortex_scores_latest.json reached the operator with the approval panel "
        "injected into it. That is the exact defect this file exists to stop."
    )
    assert "STALE DASHBOARD" in body

    # Both timestamps, verbatim, so the operator can see the gap rather than be told
    # about it.
    assert _iso(BASE_EPOCH) in body, "the dashboard's own timestamp is not on the page"
    assert _iso(BASE_EPOCH + HOUR) in body, "the scores timestamp is not on the page"

    # The operator can still judge proposals; only the stale scores are withheld.
    assert "approval-panel" in body


# ---------------------------------------------------------------------------
# (b) The boundary and the bypass
# ---------------------------------------------------------------------------

def test_equal_mtimes_are_not_stale(client, tmp_path):
    """The same instant is not "older". A dashboard generated from exactly these
    scores must not be refused on a tie."""
    _write(tmp_path / "cortex_dashboard_live.html", FIXTURE_DASHBOARD, BASE_EPOCH)
    _write(tmp_path / "cortex_scores_latest.json", "{}", BASE_EPOCH)

    assert DASHBOARD_MARKER in _get(client)


def test_a_missing_scores_file_does_not_open_the_gate(client, tmp_path):
    """Deleting the scores file must not become the way past the check.

    With nothing to compare against, freshness is unverifiable — and an unverifiable
    page is precisely the one not to approve against.
    """
    _write(tmp_path / "cortex_dashboard_live.html", FIXTURE_DASHBOARD, BASE_EPOCH)

    body = _get(client)

    assert DASHBOARD_MARKER not in body, (
        "removing output/cortex_scores_latest.json served the dashboard unchecked"
    )
    assert "cannot be verified" in body
    assert "MISSING" in body


# ---------------------------------------------------------------------------
# (c) The fallback names an entry point that exists
# ---------------------------------------------------------------------------

def test_the_missing_dashboard_message_names_the_real_entry_point(client, tmp_path):
    """It used to say "run hypercortex_runner.py first". That file does not generate
    the dashboard and never did — grep it for "dashboard" and there are no hits."""
    body = _get(client)

    assert "cortex_dashboard_generator.py" in body
    assert "hypercortex_runner.py first" not in body


def test_no_instruction_tells_the_operator_to_run_hypercortex_runner():
    """Source-level guard: the wrong instruction must not come back anywhere in this
    file, including in a message the fixtures above never reach."""
    source = (REPO / "cortex_approval_server.py").read_text(encoding="utf-8")

    # The file may NAME hypercortex_runner.py while explaining that it is NOT the
    # generator — that is what the corrected message does. What must never reappear is
    # an instruction to run it in order to get a dashboard.
    for line in source.splitlines():
        if "hypercortex_runner" not in line:
            continue
        lowered = line.lower()
        assert not any(verb in lowered for verb in ("пусни", "run it", "start it")), (
            "the server tells the operator to run hypercortex_runner.py to get a "
            f"dashboard, which it does not generate: {line.strip()}"
        )
