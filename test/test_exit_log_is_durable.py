"""The exit code survives the next cycle.

memory/cycle_exit.json is a single slot: every reaped cycle overwrites the last.
On 27 Aug 2026 it held one record — exit_code 0, the run that had finished four
hours earlier — and that was the ONLY exit code left anywhere on the machine.
Nine cycles had been reaped since 23 Aug. Eight of their exit codes were gone.

The reaper exists to answer one question ("how did it end, as an integer") and
it was answering it for exactly one cycle at a time. memory/cycle_exits.jsonl is
the append-only copy. The old slot is unchanged, because supervisor.py and
core/cycle_report.py read that exact path for "the latest".
"""
from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from memory import cycle_reaper as reaper       # noqa: E402
import supervisor as sup                        # noqa: E402


def _reap_a_process(tmp_path, code, cycle_id):
    """Reap a real short-lived process into a sandbox. Returns the record."""
    probe = subprocess.Popen(
        [sys.executable, "-c", f"import sys,time; time.sleep(0.1); sys.exit({code})"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    return reaper.reap(probe.pid, cycle_id=cycle_id,
                       exit_record=tmp_path / "cycle_exit.json",
                       exit_log=tmp_path / "cycle_exits.jsonl",
                       night_log=tmp_path / "night_events.jsonl",
                       settle_sec=0.1)


def test_three_cycles_leave_three_records_not_one(tmp_path):
    """THE HEADLINE. The slot keeps the last; the log keeps them all."""
    for i, code in enumerate((0, 3, 9)):
        rec = _reap_a_process(tmp_path, code, f"c-{i}")
        assert rec["exit_log_written"] is True

    slot = json.loads((tmp_path / "cycle_exit.json").read_text(encoding="utf-8"))
    assert slot["cycle_id"] == "c-2", "the slot must still hold only the latest"
    assert slot["exit_code"] == 9

    rows = [json.loads(l) for l
            in (tmp_path / "cycle_exits.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    assert [r["cycle_id"] for r in rows] == ["c-0", "c-1", "c-2"]
    assert [r["exit_code"] for r in rows] == [0, 3, 9], (
        "the durable log lost an exit code — this is the whole defect")


def test_the_old_path_keeps_its_shape_for_the_readers_that_use_it(tmp_path):
    """supervisor and cycle_report read cycle_exit.json. Do not move it."""
    rec = _reap_a_process(tmp_path, 0, "c-shape")
    slot = json.loads((tmp_path / "cycle_exit.json").read_text(encoding="utf-8"))
    for key in ("ts", "cycle_id", "pid", "exit_code", "exit_code_hex",
                "exit_code_source", "ended_by", "waited_sec", "state"):
        assert key in slot, f"cycle_exit.json lost the field {key!r}"
    assert slot["state"] == "RECORDED"
    assert rec["exit_record_written"] is True


def test_a_failure_to_append_does_not_cost_the_slot(tmp_path):
    """Each sink is written independently — that is the module's contract."""
    blocked = tmp_path / "not_a_dir"
    blocked.write_text("i am a file", encoding="utf-8")
    probe = subprocess.Popen(
        [sys.executable, "-c", "import sys,time; time.sleep(0.1); sys.exit(0)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    rec = reaper.reap(probe.pid, cycle_id="c-blocked",
                      exit_record=tmp_path / "cycle_exit.json",
                      exit_log=blocked / "cycle_exits.jsonl",
                      night_log=tmp_path / "night_events.jsonl",
                      settle_sec=0.1)
    assert rec["exit_record_written"] is True, (
        "a broken durable log must not cost the slot")
    assert rec["exit_log_written"] is not True
    assert (tmp_path / "cycle_exit.json").exists()


def test_the_supervisor_passes_the_durable_path_down(tmp_path, monkeypatch):
    """The reaper is DETACHED — a path it is not given is a path it defaults to,
    and the default would be the real file during a test."""
    captured = {}

    class FakePopen:
        def __init__(self, argv, **kw):
            captured["argv"] = argv
            self.pid = 4242

    monkeypatch.setattr(sup, "CYCLE_EXIT_PATH", tmp_path / "cycle_exit.json")
    monkeypatch.setattr(sup, "CYCLE_EXIT_LOG", tmp_path / "cycle_exits.jsonl")
    monkeypatch.setattr(sup.subprocess, "Popen", FakePopen)
    sup._spawn_reaper(sys.executable, 999, "c-1")

    argv = captured["argv"]
    assert "--exit-log" in argv
    assert str(tmp_path / "cycle_exits.jsonl") in argv
    assert "--exit-record" in argv
    assert str(tmp_path / "cycle_exit.json") in argv


def test_the_selftest_cannot_write_to_the_real_durable_log():
    """ast, because this is a claim about a CALL, and the 16 Aug 2026 scar was
    exactly a test writing a fabrication into a real record.

    The first run of this change did exactly that: it appended a synthetic
    'selftest / ended_by=death' row to memory/cycle_exits.jsonl.
    """
    tree = ast.parse((REPO / "memory" / "cycle_reaper.py").read_text(encoding="utf-8-sig"))
    selftest = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "selftest")
    reap_calls = [n for n in ast.walk(selftest)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id == "reap"]
    assert reap_calls, "selftest no longer calls reap()"
    for call in reap_calls:
        kwargs = {k.arg for k in call.keywords}
        for sink in ("exit_record", "exit_log", "night_log"):
            assert sink in kwargs, (
                f"selftest calls reap() without redirecting {sink} — it would "
                f"write into the real memory/ record")


def test_no_test_spawns_the_reaper_without_redirecting_the_durable_log():
    """A sink not named on the command line is the LIVE file.

    The reaper is DETACHED, so monkeypatch cannot reach it — argv is the only
    way in. Adding EXIT_LOG made four existing tests append fabricated records
    ('test-cycle', 'CYCLE-B', ended_by=death) to the real
    memory/cycle_exits.jsonl, because they passed --exit-record and --night-log
    and let the third sink default.
    """
    offenders = []
    for path in sorted((REPO / "test").glob("*.py")):
        src = path.read_text(encoding="utf-8-sig")
        if "memory.cycle_reaper" not in src:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            flat = " ".join(ast.unparse(a) for a in node.args)
            if "memory.cycle_reaper" not in flat:
                continue
            if "--exit-record" in flat and "--exit-log" not in flat:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "these spawn the reaper with --exit-record but no --exit-log, so the "
        f"durable record lands in the real memory/: {offenders}")


def test_every_write_surface_is_a_module_constant():
    """The module's own rule: no path built inside a function body."""
    for name in ("EXIT_RECORD", "EXIT_LOG", "NIGHT_LOG"):
        assert hasattr(reaper, name), f"{name} is not a module constant"
    assert reaper.EXIT_LOG.name == "cycle_exits.jsonl"
    assert reaper.EXIT_RECORD.name == "cycle_exit.json"
    assert reaper.EXIT_LOG != reaper.EXIT_RECORD
