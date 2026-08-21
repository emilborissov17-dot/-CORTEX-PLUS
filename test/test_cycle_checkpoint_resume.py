"""Fault injection: kill a runner mid-cycle, restart with --resume, prove it does
not re-run what already finished.

WHY A SUBPROCESS AND A REAL KILL
---------------------------------
The claim being tested is about what survives a process ceasing to exist. A test
that simulates that with an exception has not tested it: an exception unwinds the
stack, runs `finally` blocks, flushes buffers and calls atexit handlers — every one
of which is a chance to write the checkpoint that the real crash would NOT have
written. So there are two deaths here and neither is polite:

  * os._exit(137) inside the step — the process vanishes mid-step. No finally, no
    flush, no atexit. This is deterministic, so it is the one that carries the
    per-step assertions.
  * Popen.kill() from the parent while the child sleeps in a step — on Windows this
    is TerminateProcess, which the child cannot catch, block or defer. This is the
    real watchdog kill, reproduced.

NO REAL CYCLE IS STARTED. The harness below walks a list of fake step names and
writes only under tmp_path. It never imports fast_cycle_runner, never touches the
repo's memory/ tree, and never talks to a model.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

STEPS = ["boot", "body_scan", "canon_load", "dependency_check", "scoring", "seal"]
CYCLE_ID = "2026-08-21T17:00:16.626331+00:00"


# The harness: a runner-shaped process that is ONLY the checkpoint contract —
# walk the steps, record each completion, and be killable at a named step.
HARNESS = textwrap.dedent(
    '''
    import os, sys, time
    from pathlib import Path

    repo, base, cycle_id, steps_csv, die_at, hang_at, resume = sys.argv[1:8]
    sys.path.insert(0, repo)
    from core.cycle_checkpoint import record_step_complete, latest, decide_resume

    base = Path(base)
    steps = steps_csv.split(",")
    runlog = base / "runlog.txt"

    checkpoint = latest(base=base)
    decision = decide_resume(cycle_id, steps, checkpoint,
                             cycle_finished=False, enabled=(resume == "resume"))
    (base / "decision.txt").write_text(
        str(decision.start_index) + "|" + decision.reason, encoding="utf-8")

    for i in range(decision.start_index, len(steps)):
        step = steps[i]
        with runlog.open("a", encoding="utf-8") as fh:
            fh.write(step + "\\n")
            fh.flush()
            os.fsync(fh.fileno())

        if step == die_at:
            os._exit(137)          # no finally, no flush, no atexit
        if step == hang_at:
            time.sleep(600)        # wait to be killed from outside

        record_step_complete(cycle_id, step, i, base=base)

    (base / "finished.txt").write_text("ok", encoding="utf-8")
    '''
)


def _harness_path(tmp_path: Path) -> Path:
    p = tmp_path / "harness_runner.py"
    p.write_text(HARNESS, encoding="utf-8")
    (tmp_path / "memory").mkdir(exist_ok=True)
    return p


def _run(tmp_path: Path, *, die_at="", hang_at="", resume=False, timeout=60):
    return subprocess.run(
        [sys.executable, str(_harness_path(tmp_path)), str(REPO_ROOT),
         str(tmp_path), CYCLE_ID, ",".join(STEPS), die_at, hang_at,
         "resume" if resume else "no-resume"],
        capture_output=True, text=True, timeout=timeout,
    )


def _ran(tmp_path: Path):
    log = tmp_path / "runlog.txt"
    if not log.exists():
        return []
    return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]


# ---------------------------------------------------------------------------

def test_hard_exit_mid_cycle_then_resume_skips_completed_steps(tmp_path):
    """The whole point, in one test."""
    from core.cycle_checkpoint import latest

    first = _run(tmp_path, die_at="dependency_check")
    assert first.returncode == 137, first.stderr
    assert _ran(tmp_path) == ["boot", "body_scan", "canon_load", "dependency_check"]

    # dependency_check STARTED but never completed, so it is not checkpointed.
    ck = latest(base=tmp_path)
    assert ck["last_completed_step"] == "canon_load"
    assert ck["cycle_id"] == CYCLE_ID

    (tmp_path / "runlog.txt").unlink()          # so run 2's log is only run 2

    second = _run(tmp_path, resume=True)
    assert second.returncode == 0, second.stderr
    assert (tmp_path / "finished.txt").exists()

    ran = _ran(tmp_path)
    assert ran == ["dependency_check", "scoring", "seal"], ran
    for done in ("boot", "body_scan", "canon_load"):
        assert done not in ran, f"{done} was re-run despite being checkpointed"


def test_external_kill_while_step_hangs_then_resume(tmp_path):
    """The watchdog's kill, not a cooperative one. TerminateProcess on Windows."""
    from core.cycle_checkpoint import latest

    proc = subprocess.Popen(
        [sys.executable, str(_harness_path(tmp_path)), str(REPO_ROOT),
         str(tmp_path), CYCLE_ID, ",".join(STEPS), "", "dependency_check",
         "no-resume"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    # Wait for the process to actually reach the hanging step before killing it,
    # rather than sleeping a guessed interval and hoping.
    log = tmp_path / "runlog.txt"
    for _ in range(600):
        if log.exists() and "dependency_check" in log.read_text(encoding="utf-8"):
            break
        try:
            proc.wait(timeout=0.1)
            pytest.fail("harness exited before reaching the hanging step")
        except subprocess.TimeoutExpired:
            continue
    else:
        proc.kill()
        pytest.fail("harness never reached the hanging step")

    proc.kill()
    proc.wait(timeout=30)
    assert proc.returncode != 0

    assert latest(base=tmp_path)["last_completed_step"] == "canon_load"

    (tmp_path / "runlog.txt").unlink()
    second = _run(tmp_path, resume=True)
    assert second.returncode == 0, second.stderr
    assert _ran(tmp_path) == ["dependency_check", "scoring", "seal"]


def test_resume_is_off_by_default(tmp_path):
    """A checkpoint on disk changes NOTHING unless --resume is passed."""
    _run(tmp_path, die_at="scoring")
    (tmp_path / "runlog.txt").unlink()

    second = _run(tmp_path, resume=False)
    assert second.returncode == 0, second.stderr
    assert _ran(tmp_path) == STEPS, "default run must walk every step from 0"

    start, reason = (tmp_path / "decision.txt").read_text(encoding="utf-8").split("|", 1)
    assert start == "0"
    assert "OFF by default" in reason


# ── the refusals ───────────────────────────────────────────────────────────

def test_checkpoint_from_another_cycle_is_refused():
    from core.cycle_checkpoint import decide_resume

    d = decide_resume(CYCLE_ID, STEPS,
                      {"cycle_id": "some-older-cycle", "last_completed_step": "scoring"},
                      cycle_finished=False, enabled=True)
    assert not d.resume and d.start_index == 0
    assert "another cycle" in d.reason


def test_finished_cycle_is_not_resumed():
    from core.cycle_checkpoint import decide_resume

    d = decide_resume(CYCLE_ID, STEPS,
                      {"cycle_id": CYCLE_ID, "last_completed_step": "scoring"},
                      cycle_finished=True, enabled=True)
    assert not d.resume and d.start_index == 0
    assert "CYCLE_FINISHED" in d.reason


def test_artifact_check_can_veto_a_resume():
    """core/phase_resume.py's EXISTS+BELONGS refusal, injected."""
    from core.cycle_checkpoint import decide_resume

    d = decide_resume(CYCLE_ID, STEPS,
                      {"cycle_id": CYCLE_ID, "last_completed_step": "canon_load"},
                      cycle_finished=False, enabled=True,
                      artifact_check=lambda step: "snapshots/master/x.json is stale")
    assert not d.resume and d.start_index == 0
    assert "stale" in d.reason


def test_unknown_step_name_is_refused():
    from core.cycle_checkpoint import decide_resume

    d = decide_resume(CYCLE_ID, STEPS,
                      {"cycle_id": CYCLE_ID, "last_completed_step": "a_step_we_deleted"},
                      cycle_finished=False, enabled=True)
    assert not d.resume and d.start_index == 0


def test_all_steps_done_but_never_sealed_leaves_nothing_to_run():
    from core.cycle_checkpoint import decide_resume

    d = decide_resume(CYCLE_ID, STEPS,
                      {"cycle_id": CYCLE_ID, "last_completed_step": "seal"},
                      cycle_finished=False, enabled=True)
    assert d.resume and d.start_index == len(STEPS)
    assert "never sealed" in d.reason


# ── durability ─────────────────────────────────────────────────────────────

def test_latest_falls_back_to_the_log_when_the_pointer_is_corrupt(tmp_path):
    from core.cycle_checkpoint import latest, record_step_complete

    (tmp_path / "memory").mkdir(exist_ok=True)
    record_step_complete(CYCLE_ID, "boot", -1, base=tmp_path)
    record_step_complete(CYCLE_ID, "body_scan", 0, base=tmp_path)

    (tmp_path / "memory" / "cycle_resume.json").write_text("{not json",
                                                           encoding="utf-8")
    assert latest(base=tmp_path)["last_completed_step"] == "body_scan"


def test_a_torn_final_line_does_not_lose_the_record(tmp_path):
    from core.cycle_checkpoint import latest, record_step_complete

    (tmp_path / "memory").mkdir(exist_ok=True)
    record_step_complete(CYCLE_ID, "boot", -1, base=tmp_path)
    record_step_complete(CYCLE_ID, "body_scan", 0, base=tmp_path)

    log = tmp_path / "memory" / "cycle_resume.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"cycle_id": "half-a-line", "last_comp')
    (tmp_path / "memory" / "cycle_resume.json").unlink()

    assert latest(base=tmp_path)["last_completed_step"] == "body_scan"


def test_completed_steps_filters_by_cycle_id(tmp_path):
    from core.cycle_checkpoint import completed_steps, record_step_complete

    (tmp_path / "memory").mkdir(exist_ok=True)
    record_step_complete("older", "boot", -1, base=tmp_path)
    record_step_complete(CYCLE_ID, "boot", -1, base=tmp_path)
    record_step_complete(CYCLE_ID, "body_scan", 0, base=tmp_path)

    assert completed_steps(CYCLE_ID, base=tmp_path) == ["boot", "body_scan"]
    assert completed_steps("older", base=tmp_path) == ["boot"]


def test_the_checkpoint_does_not_write_to_the_existence_ledger(tmp_path):
    """Additive means additive: the ledger is untouched by a checkpoint write."""
    from core.cycle_checkpoint import record_step_complete

    (tmp_path / "memory").mkdir(exist_ok=True)
    record_step_complete(CYCLE_ID, "boot", -1, base=tmp_path)

    written = {p.name for p in (tmp_path / "memory").iterdir()}
    assert written == {"cycle_resume.jsonl", "cycle_resume.json"}, written
