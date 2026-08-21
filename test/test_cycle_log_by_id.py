# -*- coding: utf-8 -*-
"""
test/test_cycle_log_by_id.py — A REPORT MUST NOT DESCRIBE A DIFFERENT CYCLE.

TWO HALVES OF ONE DEFECT, both live on 21 Aug 2026.

WRITING. A cycle started by hand wrote its output to a console. Since 17 Aug the
runner is spawned DETACHED_PROCESS and has no console at all, so
`venv\\Scripts\\python.exe fast_cycle_runner.py` — which is step 3 of the alarm
the supervisor sends when it gives up — produced no log. The run a human started
BECAUSE the automatic one failed was the one that left nothing to read.

READING. core/cycle_report._latest_log() returned the newest file in
memory/cycle_logs/ by mtime. That directory held, that afternoon:

    cycle_2026-08-21_172402.log     the cycle killed at 14:24
    cycle_2026-08-21_174401.log     its replacement

"Newest by mtime" is not "mine". A report built from the wrong file is wrong
with the confidence of a fact, and nothing in its output would say so.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import cycle_log as cl        # noqa: E402

CID = "2026-08-21T17:44:01.649875+03:00"
OTHER = "2026-08-21T17:24:02.000000+03:00"


# --------------------------------------------------------------------------- #
# The name is derived from the id, by the supervisor's own formula
# --------------------------------------------------------------------------- #

def test_the_log_name_is_derived_from_the_cycle_id():
    assert cl.stamp_of(CID) == "2026-08-21_174401"
    assert cl.path_for(CID).name == "cycle_2026-08-21_174401.log"


def test_the_two_writers_agree_on_the_name():
    """If they disagreed, every supervisor-started cycle would be reported
    ABSENT by a reader looking straight at its log."""
    import supervisor
    assert (supervisor.cycle_log_path(datetime.fromisoformat(CID)).name
            == cl.path_for(CID).name)


def test_an_unparseable_cycle_id_derives_no_name_at_all():
    """Inventing a name for an id that is not a timestamp would let two
    unrelated runs collide on one file."""
    assert cl.stamp_of("manual-run") is None
    assert cl.path_for("manual-run") is None
    assert cl.describe("manual-run")["status"] == cl.ABSENT


# --------------------------------------------------------------------------- #
# ABSENT is an answer, and a neighbour is never a substitute
# --------------------------------------------------------------------------- #

def test_a_neighbours_log_is_never_returned(tmp_path):
    (tmp_path / "cycle_2026-08-21_172402.log").write_text("the killed cycle",
                                                          encoding="utf-8")
    assert cl.find_for(CID, tmp_path) is None
    d = cl.describe(CID, tmp_path)
    assert d["status"] == cl.ABSENT
    assert "cycle_2026-08-21_174401.log" in d["why"], (
        "ABSENT does not say which log is missing")


def test_its_own_log_is_found_even_when_it_is_not_the_newest(tmp_path):
    mine = tmp_path / "cycle_2026-08-21_174401.log"
    mine.write_text("mine", encoding="utf-8")
    newer = tmp_path / "cycle_2026-08-21_180000.log"
    newer.write_text("someone else's, written later", encoding="utf-8")
    import os
    import time
    os.utime(newer, (time.time() + 60, time.time() + 60))
    assert cl.find_for(CID, tmp_path) == mine


def test_the_report_says_ABSENT_rather_than_reading_another_cycle(monkeypatch,
                                                                  tmp_path):
    from core import cycle_report as cr

    logs = tmp_path / "memory" / "cycle_logs"
    logs.mkdir(parents=True)
    (logs / "cycle_2026-08-21_172402.log").write_text(
        "[FAST_CYCLE] started at 2026-08-21T14:24:02\n[STEP] web_intelligence\n",
        encoding="utf-8")

    monkeypatch.setattr(cl, "LOG_DIR", logs)
    monkeypatch.setattr(cr, "BASE", tmp_path)
    monkeypatch.setattr(cr, "_current_cycle_id", lambda: CID)

    out = cr.build()
    assert str(out.get("log_status")) == cl.ABSENT
    assert "ABSENT" in out["error"]
    assert CID in out["error"], "the error does not say whose log is missing"
    assert "web_intelligence" not in json.dumps(out, ensure_ascii=False), (
        "the report read the OTHER cycle's log")


def test_with_no_cycle_id_at_all_the_newest_is_still_allowed(monkeypatch,
                                                             tmp_path):
    """Only when there is nothing to match on. That is a different claim from
    'this cycle's log' and the caller has been told it."""
    from core import cycle_report as cr
    logs = tmp_path / "memory" / "cycle_logs"
    logs.mkdir(parents=True)
    only = logs / "cycle_2026-08-21_172402.log"
    only.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cr, "BASE", tmp_path)
    monkeypatch.setattr(cr, "_current_cycle_id", lambda: None)
    assert cr._latest_log(None) == only


# --------------------------------------------------------------------------- #
# The tee, and its idempotency under the supervisor
# --------------------------------------------------------------------------- #

def test_a_hand_started_cycle_tees_its_own_log(tmp_path, capsys):
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        rec = cl.tee_stdio(CID, tmp_path)
        assert rec["teeing"] is True, rec
        print("[FAST_CYCLE] hello from a hand-started cycle")
        sys.stderr.write("a warning\n")
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
    body = (tmp_path / "cycle_2026-08-21_174401.log").read_text(encoding="utf-8")
    assert "hello from a hand-started cycle" in body
    assert "a warning" in body, "stderr was not teed"


def test_the_tee_refuses_when_the_supervisor_already_owns_the_file(tmp_path):
    """The supervisor opens this exact path with mode 'w' BEFORE spawning the
    runner. Teeing on top of that writes every line twice into one file."""
    (tmp_path / "cycle_2026-08-21_174401.log").write_text("", encoding="utf-8")
    rec = cl.tee_stdio(CID, tmp_path)
    assert rec["teeing"] is False
    assert "double" in rec["why"]


def test_the_tee_never_raises_and_never_costs_the_cycle(tmp_path):
    """Losing the log must not cost the run — the same trade
    supervisor.spawn_cycle() makes when it falls back to DEVNULL."""
    rec = cl.tee_stdio("not-a-timestamp", tmp_path)
    assert rec["teeing"] is False
    assert rec["path"] is None
    blocked = tmp_path / "wall"
    blocked.write_text("I am a file, not a directory", encoding="utf-8")
    rec2 = cl.tee_stdio(CID, blocked / "nested")
    assert rec2["teeing"] is False


def test_the_runner_actually_calls_the_tee():
    """An import nothing calls is the failure mode this repo is aimed at."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "from core.cycle_log import tee_stdio" in src
    assert "_tee(_cycle_id)" in src, (
        "the tee is imported but never called with the cycle's own id")
