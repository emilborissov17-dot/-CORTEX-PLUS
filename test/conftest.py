"""Shared fixtures for the test suite — and the canary that guards them.

The sentence that used to stand here read:

    "Every test in this suite runs against an isolated tmp_path sandbox and
     never reads or writes the real repo's memory/, patches/, or data/ trees."

On 16 August 2026 that sentence was false, and had been for some time. A test in
test_supervisor.py wrote a fabricated system-failure event into the real
memory/night_events.jsonl, called the real local model, sent a REAL Telegram alarm
to the human's phone about a failure that never happened, and then stamped the real
memory/alarm_sent.json — which, because the dedup key is `date:subject[:40]`,
SUPPRESSED that day's genuine alarm on a day the system was already at an exhausted
restart budget. A test disarmed the alarm that exists to wake a human when the
system dies.

The docstring was not lying. It was a claim nobody checked. That is the whole
lesson, and it is why the claim is now a TEST instead of a paragraph.

  Kimi, 16 Aug 2026:
    „Този тест не се интересува КАК е писано. Той се интересува КЪДЕ е писано.
     Той хваща os.replace, subprocess, sqlite3, mmap, и всичко останало, което
     AST скенерът не вижда. Той е ИНВАРИАНТЕН към метода на писане."

`_live_state_canary` below fingerprints the real memory/ and config/ trees before
the session and again after it. If anything under them was created, deleted or
modified, the session fails and names the files. It does not care whether the write
went through write_text, an append via open(), os.replace, shutil.move, a
subprocess's stdout handle, or sqlite — only that live state moved.
"""
import os
import sys
from pathlib import Path

import pytest

# Trees the suite must never modify. snapshots/ and data/ are deliberately NOT
# walked: snapshots/self_archive alone is tens of gigabytes and hundreds of
# thousands of files, and the cost of stat-ing it every session would make this
# canary the thing people disable. memory/ and config/ are where the state that
# can hurt someone lives — the alarm stamp, the night log, the ledger, the
# heartbeat, the schedule. If a test ever needs to be caught writing to
# snapshots/, add it here and accept the walk.
# "logs" joined on 12 Sep 2026, and the omission had a price. logs/supervisor.log
# is the only narrative record of why a cycle was killed, and it was outside every
# guard in this file: 720+ synthetic KILL POLICY lines had accumulated in it,
# including 432 for step='x', which is not a step in any table in this repo. A
# passport column built on that file made web_intelligence look like the most-
# killed step in the system; the existence ledger says it has never been killed.
_GUARDED_TREES = ("memory", "config", "logs")
_IGNORE_PARTS = {"__pycache__", ".pytest_cache", ".git"}
# A ceiling, so a runaway tree cannot silently make the canary skip work. If it is
# ever hit, the fixture SAYS SO rather than quietly measuring less than it claims.
_MAX_FILES = 20000


def _fingerprint(root: Path):
    """(path -> (size, mtime_ns)) for every file under the guarded trees.

    Deliberately stat-only. Reading contents would be stronger but slower, and —
    more importantly — reading changes st_atime, which is the trap Kimi flagged:
    a canary whose own observation disturbs what it observes. st_mtime_ns and size
    move only on a real write.
    """
    seen, capped = {}, False
    for tree in _GUARDED_TREES:
        base = root / tree
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if any(part in _IGNORE_PARTS for part in p.parts):
                continue
            if not p.is_file():
                continue
            if len(seen) >= _MAX_FILES:
                capped = True
                break
            try:
                st = p.stat()
                seen[str(p)] = (st.st_size, st.st_mtime_ns)
            except OSError:
                pass
    return seen, capped


# ── THE SECOND LEAK, found on the live machine at 08:36 UTC on 16 Aug 2026 ──────
#
# After the alarm leak was closed, the suite still took 6m45s on the real machine
# and still moved live files. The mtimes name the culprit exactly:
#
#     08:35:46  diagnosis_history.jsonl, diagnosis_latest.json,
#               llm_provenance.jsonl, brain_journal.jsonl
#     08:36:32  brain_step_log.jsonl, brain_stance.json, divergence_log.jsonl
#
# (08:39:02 files are the live pulse and watchdog on their own 5-minute cadence —
# not the suite. The two clusters above sit inside the run window and nowhere near
# a tick boundary.)
#
# The seam is memory/heartbeat.py::beat(). It is the ONE common gate all ~50 cycle
# steps pass through, which is precisely why the brain was hooked into it — "мозък
# на всяка стъпка". The consequence nobody drew: every hb.beat(...) in every test
# also fires
#     core.brain.attend()        -> a real local-model call (COLD_TIMEOUT 300s)
#                                   + appends to brain_step_log.jsonl, brain_stance
#     core.metta_check.compare() -> appends to divergence_log.jsonl
#     core.notary.attest()       -> appends to the attestation chain
#
# So test-fabricated steps were being written into the record the system uses to
# JUDGE ITS OWN BRAIN. That is worse than slow: the ritual ratio, the divergence
# log and the notary chain are evidence, and evidence with invented rows in it is
# not evidence. A guard that measures a contaminated log will report health it
# cannot have observed.
#
# Mocked, not stubbed (Kimi's rule): each hook is replaced by a recorder, so the
# call still happens, still lands in HOOK_CALLS, and a test may assert on it — only
# its ability to reach a model and to write live files is removed.
HOOK_CALLS = []

#
# ── THE THIRD LEAK, found on 21 Aug 2026: the same hole, one hook later ────────
#
# core/phase_tracker.on_beat was hung off beat() on 20 Aug and never added here.
# The result was exactly the leak this list exists to stop, wearing a new hat:
# every hb.beat() in a test opened a phase, and the NEXT one closed it — writing
# a real local-model debrief into the live tree as
#
#     memory/phase_debriefs/dead-1/D_SCORE.rejected.json
#     memory/phase_debriefs/manual-run-1/G_LEARN.rejected.json
#
# under cycle ids invented by test_supervisor.py and
# test_cycle_seals_its_own_completion.py. Three directories of fabricated
# debriefs sat in live memory, the suite spent nine and a half minutes waiting
# on a language model, and core/self_mirror.py — which reads the newest debrief
# directory — was reading test garbage as if it were the cycle's own record.
#
# The lesson is not "we forgot one". It is that a list of neutralised hooks is a
# denylist, and a denylist silently stops covering anything added after it. The
# guard against that is test_no_live_debriefs.py, which asserts that EVERY hook
# reachable from beat() is either neutralised here or provably harmless.
_NEUTRALISED = (
    ("core.brain", "attend", lambda *a, **k: None),
    ("core.metta_check", "compare", lambda *a, **k: None),
    ("core.notary", "attest", lambda *a, **k: None),
    ("core.self_diagnosis", "diagnose", lambda *a, **k: {"cause": "MOCKED_IN_TESTS"}),
    ("core.phase_tracker", "on_beat", lambda *a, **k: None),
    # ADDED 13 Sep 2026 with core/halt.py. beat() now asks the survival gate
    # and raises VoluntaryHalt when the machine is starved. That is right in
    # a cycle and wrong in a unit test: test_beat_writes_step_and_pid failed
    # the moment the real machine dropped under the gate, which says nothing
    # about beat() and everything about the room it was run in. The halt has
    # its own tests, which call it directly.
    ("core.halt", "check", lambda *a, **k: None),
)


@pytest.fixture(autouse=True)
def _no_live_side_effects(monkeypatch):
    """Cut the three side-effecting hooks that hang off heartbeat.beat().

    autouse, because the whole point is that no test author has to know that
    writing a heartbeat talks to a language model. They did not know. Neither
    did I.

    raising=False on purpose: in a container where `core` is absent these imports
    fail and the hooks were never live anyway. The fixture must not turn a missing
    optional module into a red suite — that would train people to delete it.
    """
    import importlib

    HOOK_CALLS.clear()
    for mod_name, attr, fake in _NEUTRALISED:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue

        def _make(_name, _fake):
            def _recorded(*a, **k):
                HOOK_CALLS.append((_name, a[:1]))
                return _fake(*a, **k)
            return _recorded

        monkeypatch.setattr(mod, attr, _make(f"{mod_name}.{attr}", fake),
                            raising=False)


# ── WHY THERE ARE TWO CANARIES AND ONLY ONE OF THEM MAY FAIL A RUN ─────────────
#
# The first version of this file had a single filesystem canary: fingerprint
# memory/ and config/ before and after the session, fail if anything moved. It was
# Kimi's design and its virtue is real — it is INVARIANT TO THE METHOD of writing,
# so it sees os.replace, subprocess, sqlite and everything an AST scan cannot.
#
# It fired on its very first run on the live machine, and it was WRONG:
#
#     MODIFIED: memory\collector_runs.log
#     MODIFIED: memory\collector_seen.json
#
# Neither is written by any test. They belong to the CORTEX_Collector scheduled
# task, which started at 11:58 and was still streaming output at 12:01 — inside the
# 3.59 seconds the suite took. This machine also runs the supervisor every five
# minutes and the pulse continuously. Background writes under memory/ are not an
# anomaly here; they are the normal condition.
#
# A filesystem-only canary therefore CANNOT tell "a test wrote this" from "another
# process wrote this while the suite happened to be running". Left as a hard
# failure it would go red at random, and a guard that cries wolf gets switched off
# — which is a worse outcome than not having written it, because it would be
# switched off precisely when it finally caught something real.
#
# So the duty is split by what each method can actually prove:
#
#   _no_live_writes  (FAILS the run)  — intercepts the write primitives INSIDE this
#       process. It cannot see other processes at all, so it has no false positives
#       by construction. It is the one that would have caught the 11:20 alarm leak.
#
#   _live_state_canary  (WARNS only)  — the filesystem diff. Kept because it is the
#       only thing that can see a write from a subprocess a test spawned. Demoted to
#       a warning because on a live machine it cannot attribute what it sees, and it
#       says so in its own output rather than pretending.
#
# Honest residual risk, stated rather than hidden: a test that spawns a subprocess
# which writes to live state produces a WARNING, not a failure, and could be missed
# by a reader skimming the output. Closing that would need process-level tracing,
# which is not worth its cost today. If it ever bites, this comment is the record
# that we chose it.

_LIVE_WRITES = []


def _is_live(target) -> str:
    """Return the offending path as a string if it lands in a guarded tree."""
    try:
        p = Path(target)
        if not p.is_absolute():
            p = Path.cwd() / p
        p = p.resolve()
    except Exception:
        return ""
    for tree in _GUARDED_TREES:
        base = (REPO_ROOT / tree).resolve()
        try:
            p.relative_to(base)
            return str(p)
        except ValueError:
            continue
    return ""


@pytest.fixture(autouse=True)
def _blackbox_to_tmp(monkeypatch, tmp_path):
    """Redirect the flight recorder into tmp_path for every test.

    ADDED 5 Sep 2026 with core/blackbox.py. _run() now records one line per step,
    so ANY test that exercises _run() writes memory/blackbox.jsonl and trips
    _no_live_writes below. That guard's own instruction is the right one — "fix the
    FIXTURE, redirect the path into tmp_path" — and doing it here covers every
    future test instead of each one remembering.

    Failing open on purpose: if the module cannot be imported the test proceeds, the
    same way the recorder itself never blocks the cycle.
    """
    try:
        from core import blackbox as _bb
        monkeypatch.setattr(_bb, "LOG_PATH", str(tmp_path / "blackbox.jsonl"))
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _llm_provenance_to_tmp(monkeypatch, tmp_path):
    """Redirect core/llm_door.py's provenance file into tmp_path for every test.

    ADDED 24 Sep 2026 with the one door. Its first suite run appended 26 mocked
    rows (latency 0.0) to the LIVE memory/llm_provenance.jsonl: the door writes
    through core.durable.append_json, which _no_live_writes below does not see,
    and the tests that used to redirect brain.PROVENANCE were redirecting a path
    nothing writes any more. The rows were removed by hand; this keeps it so.
    """
    try:
        from core import llm_door as _door
        monkeypatch.setattr(_door, "PROVENANCE", tmp_path / "llm_provenance.jsonl")
        # and the two other files the door keeps (task #19 c, d): measured
        # timeouts (absent -> the seed) and the per-night dead-leg state
        monkeypatch.setattr(_door, "TIMEOUTS", tmp_path / "llm_timeouts.json")
        monkeypatch.setattr(_door, "LEG_STATE", tmp_path / "llm_leg_state.json")
        monkeypatch.setattr(_door, "_ok_cache", {})
        monkeypatch.setattr(_door, "_alive", set())
        monkeypatch.setattr(_door, "_warm", set())
        # task #8: inside a cycle the door asks Ollama's /api/ps what is resident.
        # No test may reach the real server for that: by default nothing is
        # resident; a test that needs the warm core says so itself.
        monkeypatch.setattr(_door, "_resident", lambda base: set())
        monkeypatch.setattr(_door, "_ps_cache", {})
        # 25 Sep: the door restores the warm core after a non-core local call
        # outside a cycle, and the supervisor loads it before a spawn. Neither may
        # reach the real Ollama from a test; tests of those paths say so.
        from core import model_window as _mwin
        # 25 Sep 2026, the lesson that cost a cycle its core: a test that calls
        # heartbeat.beat() renews the small-model lease through the REAL
        # _set_keep_alive, which LOADS qwen2.5:3b into the live Ollama (keep_alive
        # 4200) - it evicted cortex-l1b-3b in the middle of the 08:54 cycle. No
        # test may touch Ollama's residency: load/unload and /api/ps are stubbed.
        monkeypatch.setattr(_mwin, "_set_keep_alive", lambda *a, **k: False)
        monkeypatch.setattr(_mwin, "resident_models", lambda url=None: set())
        monkeypatch.setattr(_mwin, "restore_core", lambda after_model, url=None: None)
        monkeypatch.setattr(_mwin, "ensure_core",
                            lambda url=None: {"model": "core", "resident_before": True,
                                              "reloaded": False, "seconds": 0.0})
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _daily_tier_to_tmp(monkeypatch, tmp_path):
    """No test may read the LIVE daily tier. Autouse, for every test.

    ADDED 12 Sep 2026, in the same hour as the fixture below and for the same
    reason — which is the point worth recording. core/consolidation.py gained
    read_daily_tier(), and run() reads memory/daily_tier.jsonl when no path is
    given. Five tests in test_consolidation.py build a SEALED world under
    tmp_path/archive and assert on what comes out of it; they immediately started
    seeing 4 hypotheses out of the real file instead of the 0 their fixture
    describes. A test that constructs a world and is silently handed the real one
    is not testing anything it claims to.

    The general shape, twice in one day: a module-level constant pointing at live
    state is reachable from every test unless something redirects it. The tests
    were right and the new code was wrong to default past them.
    """
    try:
        from core import consolidation as _con
        monkeypatch.setattr(_con, "DAILY_TIER", tmp_path / "daily_tier.jsonl")
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _canon_invariants_to_tmp(monkeypatch, tmp_path):
    """No test may write into the LIVE canon. Autouse, for every test.

    ADDED 12 Sep 2026, after a test did exactly that. memory/canon_invariants.json
    held {"lesson": "c", "evidence": "carried forward by 3 consecutive cycle reviews
    (c1..c1)"} — "c1" is a fixture's cycle_id, so the writer was a test. The canon is
    not just another artifact: core/canon.as_frame() renders it into
    memory/active_canon_frame.txt and core/brain.py:227 loads that file as the SPIRIT
    block of EVERY prompt. A test's leftover was being carried into every thought the
    system had, labelled "Consolidated invariants (learned, stable)".

    WHY A FIXTURE AND NOT ONLY THE LENGTH FLOOR in consolidate_invariant: the floor
    stops a DEGENERATE lesson, not a plausible one. A test promoting "keep the anchor
    steady when the wind turns" three times would pass the floor and still poison the
    live canon. The two guards cover different halves, and neither is redundant.

    _no_live_writes below would not have caught it either: it watches write
    primitives for paths under memory/, but core/canon.py writes through
    Path.write_text on a module-level constant, and the earlier fixtures in this file
    exist because the same shape of gap keeps recurring. Redirect the constant.
    """
    try:
        from core import canon as _canon
        monkeypatch.setattr(_canon, "INVARIANTS", tmp_path / "canon_invariants.json")
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _supervisor_log_to_tmp(monkeypatch, tmp_path):
    """No test may write into the LIVE supervisor log. Autouse, for every test.

    ADDED 12 Sep 2026, the fourth instance of the same shape: a module-level
    constant pointing at live state is reachable from every test unless something
    redirects it. supervisor.LOG_PATH is that constant, and supervisor.log() is
    called from decide() whenever a step is past its ceiling — so every test that
    drives a stale heartbeat wrote a KILL POLICY line into the real file.

    THE COST OF NOT HAVING THIS. 720+ fixture lines: web_intelligence x144,
    trend_tracker x144, step='x' x432. Counting kills from that file makes
    web_intelligence the most-killed step in the system, when the ledger has never
    killed it once. And the same file holds ZERO lines for daily_analysis, which
    the ledger killed six times — so as a source it was wrong in both directions
    at once.

    Some tests already patch LOG_PATH by hand (test_supervisor.py:462 and :775,
    test_cycle_reaper.py:68, test_cycle_log_survives_kill.py:52). That is exactly
    the trouble: it worked, so nobody noticed that the tests which did NOT do it
    were writing to the real log. Doing it here means no test author has to know.

    Failing open, like its neighbours: in an environment where supervisor cannot be
    imported there was nothing to redirect anyway.
    """
    try:
        import supervisor as _sup
        monkeypatch.setattr(_sup, "LOG_PATH", tmp_path / "supervisor.log")
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _no_live_writes(monkeypatch, request):
    """Intercept the write primitives and fail the test that used one on live state.

    Recorded and asserted at teardown rather than raised at the call site — and
    that choice is itself a lesson from 16 Aug. The first attempt to guard the
    alarm raised inside the write; the raise was swallowed by alarm_human's
    `except Exception: pass`, the test went green, and the network call had still
    happened. Anything that can be caught will be caught by fail-open code. A list
    no exception handler can reach cannot be.
    """
    import builtins
    import os as _os
    import shutil as _shutil

    _open, _wt, _wb = builtins.open, Path.write_text, Path.write_bytes
    _replace, _rename = _os.replace, _os.rename
    _move, _copy2 = _shutil.move, _shutil.copy2

    def _note(target, how):
        bad = _is_live(target)
        if bad:
            _LIVE_WRITES.append((request.node.name, how, bad))

    def open_(file, mode="r", *a, **k):
        if any(c in str(mode) for c in ("w", "a", "x", "+")):
            _note(file, "open")
        return _open(file, mode, *a, **k)

    def wt(self, *a, **k):
        _note(self, "Path.write_text")
        return _wt(self, *a, **k)

    def wb(self, *a, **k):
        _note(self, "Path.write_bytes")
        return _wb(self, *a, **k)

    def replace_(src, dst, *a, **k):
        _note(dst, "os.replace")
        return _replace(src, dst, *a, **k)

    def rename_(src, dst, *a, **k):
        _note(dst, "os.rename")
        return _rename(src, dst, *a, **k)

    def move_(src, dst, *a, **k):
        _note(dst, "shutil.move")
        return _move(src, dst, *a, **k)

    def copy2_(src, dst, *a, **k):
        _note(dst, "shutil.copy2")
        return _copy2(src, dst, *a, **k)

    monkeypatch.setattr(builtins, "open", open_)
    monkeypatch.setattr(Path, "write_text", wt)
    monkeypatch.setattr(Path, "write_bytes", wb)
    monkeypatch.setattr(_os, "replace", replace_)
    monkeypatch.setattr(_os, "rename", rename_)
    monkeypatch.setattr(_shutil, "move", move_)
    monkeypatch.setattr(_shutil, "copy2", copy2_)

    mine_before = len(_LIVE_WRITES)
    yield
    mine = _LIVE_WRITES[mine_before:]
    if mine:
        lines = "\n".join(f"  {how} -> {path}" for _t, how, path in mine)
        raise AssertionError(
            f"THIS TEST WROTE TO LIVE STATE:\n{lines}\n\n"
            "On 16 Aug 2026 this exact class of leak sent a fabricated emergency "
            "alarm to the human's phone and then suppressed the day's real one, and "
            "wrote invented steps into the log the system uses to judge its own "
            "brain.\nFix the FIXTURE — redirect the path into tmp_path. If the write "
            "is genuinely intended, it does not belong in a test.")


@pytest.fixture(autouse=True)
def _reset_cycle_scoped_state():
    """Cycle-scoped module state does not survive a cycle. Nor a test.

    core/step_budget.py demotes the cloud tier after three empty tiers IN ONE
    CYCLE, and the demotion is deliberately module-global and sticky — a cycle
    is one process, and the runner clears it at boot. In a test session there is
    no boot: one test that drives three empty clouds silently demotes the cloud
    for every test that follows, and five tests in this suite started failing
    for that reason and passing in isolation. Boot is simulated here.
    """
    try:
        from core import step_budget as _sb
        _sb.reset_cycle()
    except Exception:
        pass
    # backend_policy disables legs and blocks the cloud process-wide; a test that
    # drove failures used to leave the ladder local-only for every later test,
    # which then reached the REAL local model (24 Sep 2026).
    try:
        from core import backend_policy as _bp
        _bp.reset_for_tests()
    except Exception:
        pass
    yield
    try:
        from core import step_budget as _sb
        _sb.reset_cycle()
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def _live_state_canary():
    """Filesystem diff over memory/ and config/. WARNS — never fails. See above."""
    before, capped = _fingerprint(REPO_ROOT)
    if capped:
        print(f"\n[canary] partial: stopped at {_MAX_FILES} files this run.")
    yield
    after, _ = _fingerprint(REPO_ROOT)

    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    if not (created or deleted or changed):
        return

    print("\n" + "=" * 74)
    print("[canary] files under memory/ or config/ changed during this session:")
    for label, group in (("MODIFIED", changed), ("CREATED", created), ("DELETED", deleted)):
        for f in group:
            print(f"  {label}: {f}")
    print("\nThis is NOT necessarily the suite's doing and is NOT a failure. This "
          "machine\nruns the supervisor every 5 minutes, the collector every 4 "
          "hours and the pulse\ncontinuously; any of them can write here mid-run. "
          "In-process writes are caught\nby _no_live_writes, which DOES fail. Read "
          "this list only when something here\nlooks like it came from a test — a "
          "fabricated pid, a step name from a fixture.")
    print("=" * 74)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("CORTEX_BASE", str(REPO_ROOT))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway fake-repo skeleton under pytest's tmp_path.

    Mirrors the subset of the real repo's directory layout that
    self_modifier / execute_patches / PatchGuardian / safety.quarantine
    read and write, so tests can point the real modules at it instead
    of the actual project tree.
    """
    (tmp_path / "agents" / "core").mkdir(parents=True)
    (tmp_path / "memory").mkdir()
    (tmp_path / "patches" / "quarantine").mkdir(parents=True)
    (tmp_path / "data" / "patch_guardian" / "backups").mkdir(parents=True)
    (tmp_path / "data" / "patch_guardian" / "results").mkdir(parents=True)
    monkeypatch.setenv("CORTEX_BASE", str(tmp_path))
    return tmp_path
