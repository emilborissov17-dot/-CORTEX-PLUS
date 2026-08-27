"""One cycle, one log file.

Found 27 Aug 2026 in memory/cycle_logs/, which held two files for every night
from 23 to 27 Aug — 2,698 lines and 1,736 lines for the same run, ending on the
same `done at` timestamp to the microsecond.

    supervisor.spawn_cycle() -> cycle_log_path()   -> wall clock AT SPAWN
    fast_cycle_runner        -> tee_stdio()        -> path_for(cycle_id)

Same formula, different INPUT, one or two seconds apart: the id is minted, the
process is spawned, and the second ticks over before the child asks for its own
name. The runner looked for cycle_..._030401.log, saw only the supervisor's
cycle_..._030403.log, concluded nobody was capturing its output, and tee'd a
second copy. tee_stdio() documents itself as "IDEMPOTENT UNDER THE SUPERVISOR",
by evidence rather than by a flag — and the evidence it looks for is the file
being there under the name IT computes.

The old equivalence test asserted the two functions agree ON THE SAME INPUT.
They always did. What differed was the input, so the test could not see it.
"""
from __future__ import annotations

import ast
import pathlib
import sys
from datetime import datetime, timedelta

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import supervisor as sup                      # noqa: E402
from core import cycle_log                    # noqa: E402

CID = "2026-08-27T03:04:01.982592+03:00"


def test_the_supervisor_names_the_log_from_the_cycle_id():
    assert (sup.cycle_log_path(cycle_id=CID).name
            == cycle_log.path_for(CID).name
            == "cycle_2026-08-27_030401.log")


def test_a_spawn_one_second_later_still_names_the_same_file():
    """THE REGRESSION. The clock moves between minting and spawning; the name
    must not. Before the fix these two differed and produced two files."""
    minted = datetime.fromisoformat(CID)
    spawned_at = minted + timedelta(seconds=2)

    supervisor_name = sup.cycle_log_path(cycle_id=CID).name
    runner_name = cycle_log.path_for(CID).name
    assert supervisor_name == runner_name

    # and the drifting value is no longer consulted when the id is present
    assert supervisor_name != sup.cycle_log_path(now=spawned_at).name, (
        "the test itself is void if a 2s drift does not change the wall-clock "
        "name — that drift is the whole defect")


def test_spawn_cycle_passes_the_cycle_id_to_the_namer():
    """ast, because the defect was a CALL SITE that omitted an argument.

    A substring scan for 'cycle_log_path(cycle_id' would pass on a comment.
    """
    tree = ast.parse((REPO / "supervisor.py").read_text(encoding="utf-8-sig"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "cycle_log_path"]
    assert calls, "supervisor.py no longer calls cycle_log_path at all"
    for call in calls:
        kwargs = {k.arg for k in call.keywords}
        assert "cycle_id" in kwargs or call.args, (
            f"cycle_log_path() called with no cycle_id at supervisor.py:"
            f"{call.lineno} — that bare call is the two-logs-a-night bug")


def test_the_runner_will_not_tee_when_the_supervisor_already_opened_the_file(tmp_path):
    """tee_stdio()'s contract, exercised on the name the supervisor now uses."""
    p = sup.cycle_log_path(cycle_id=CID, now=None)
    assert p.name == cycle_log.path_for(CID).name

    # The supervisor opens the file first, exactly as spawn_cycle does.
    (tmp_path / p.name).write_text("", encoding="utf-8")
    out = cycle_log.tee_stdio(CID, log_dir=tmp_path)
    assert out["teeing"] is False, (
        "the runner tee'd a second copy even though the supervisor's file was "
        "already there — every line would be written twice")
    assert "already opened" in out["why"]


def test_the_runner_still_tees_when_nobody_opened_one(tmp_path):
    """The by-hand case must keep working: no supervisor, so own the log."""
    import io
    import sys as _sys
    saved_out, saved_err = _sys.stdout, _sys.stderr
    try:
        _sys.stdout, _sys.stderr = io.StringIO(), io.StringIO()
        out = cycle_log.tee_stdio(CID, log_dir=tmp_path)
    finally:
        _sys.stdout, _sys.stderr = saved_out, saved_err
    assert out["teeing"] is True
    assert (tmp_path / "cycle_2026-08-27_030401.log").exists()


def test_an_unparseable_cycle_id_falls_back_instead_of_refusing():
    """Losing the log must never cost the cycle."""
    p = sup.cycle_log_path(cycle_id="not-a-timestamp")
    assert p.name.startswith("cycle_") and p.name.endswith(".log")


def test_the_old_datetime_call_still_works():
    """core/cycle_log.py --selftest and two existing tests call it this way."""
    name = sup.cycle_log_path(datetime.fromisoformat(CID)).name
    assert name == "cycle_2026-08-27_030401.log"
