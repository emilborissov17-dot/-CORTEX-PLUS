"""What the system proposed must outlive what we did with it.

THE LOSS THIS CLOSES (measured 17 Aug 2026)
--------------------------------------------
`agents/core/self_observer.py::save_proposals` had four exits and three of them
led nowhere:

  * the fuzzy-dedup `continue` — dropped silently,
  * the alignment guard's else-branch — `print`ed and dropped, never on disk,
  * `MAX_AGE_DAYS = 7` — deleted a week later (37 already gone),
  * `MAX_PROPOSALS = 50` — oldest trimmed (not binding yet, binding the moment
    the system gets more productive).

`memory/improvement_proposals_archive.json` looked like the answer and was not:
the string appears in zero files and zero commits of the entire git history.

The tests below pin the archive at the ONE point upstream of all four — the
decision loop — and the most important of them is the BLOCKED one. A proposal
the guard refuses is what the system wanted and we said no to. That is the class
of record we had lost completely, and it is the class most worth keeping.

WHY THE POSITIVE CONTROLS ARE NOT DECORATION
---------------------------------------------
"a blocked proposal is archived" is satisfied perfectly by a recorder that
writes BLOCKED for everything, and "an accepted proposal is archived" by one
that writes ACCEPTED for everything. Neither would have read the guard at all.
So the same proposal is run past a guard that allows and a guard that refuses,
and the two records must differ — see
test_the_outcome_tracks_the_guard_and_is_not_a_constant.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import alignment.civilization_guard as guard
import agents.core.self_observer as so
from memory import proposal_archive as pa


def _allow(_obs):
    return {"allowed": True, "risk_score": 0.0, "notes": "ok"}


def _refuse(_obs):
    return {"allowed": False, "risk_score": 1.0,
            "notes": "hard_block: matched pattern 'os.system'"}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Every surface save_proposals and the archive can touch, inside tmp_path.

    BASE_DIR is redirected because save_proposals builds its path inline
    (`BASE_DIR / "memory" / "improvement_proposals.json"`) — the very shape the
    repo's own write-surface scar warns about. Redirecting the base is the only
    handle a test has on it.
    """
    monkeypatch.setattr(so, "BASE_DIR", tmp_path)
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pa, "ARCHIVE_DIR", tmp_path / "proposal_archive")
    monkeypatch.setattr(pa, "LIVE_PROPOSALS", tmp_path / "memory" / "improvement_proposals.json")
    monkeypatch.setenv("CORTEX_CYCLE_ID", "test-cycle-1")
    return tmp_path


def _proposal(problem="Замърсяване на водата в региона", **kw):
    p = {
        "component": "WATER",
        "problem": problem,
        "root_cause": "no treatment plant",
        "solution": "build treatment capacity",
        "measurable_goal": "safe_water_pct > 80",
        "generated_by": "SELF_OBSERVER",
    }
    p.update(kw)
    return p


def _archive_text(tmp_path) -> str:
    d = tmp_path / "proposal_archive"
    return "\n".join(f.read_text(encoding="utf-8")
                     for f in sorted(d.glob("20*.md"))) if d.exists() else ""


def _live(tmp_path) -> list:
    f = tmp_path / "memory" / "improvement_proposals.json"
    if not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8"))["proposals"]


# ---------------------------------------------------------------------------
# THE ONE THAT MATTERS: what we refused is kept, with the reason we refused it
# ---------------------------------------------------------------------------

def test_a_blocked_proposal_is_archived_with_the_reason_it_was_blocked(sandbox, monkeypatch):
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _refuse)

    so.save_proposals([_proposal()])

    body = _archive_text(sandbox)
    assert "BLOCKED" in body, (
        "the guard refused this proposal and the refusal left no record — this "
        "is the exact class of loss the archive exists to end")
    assert "hard_block: matched pattern 'os.system'" in body, (
        "the proposal was archived without WHY it was blocked; the reason is "
        "the whole value of a blocked record")
    assert "Замърсяване на водата" in body, "the proposal text itself was not kept"

    assert _live(sandbox) == [], (
        "a blocked proposal must NOT enter improvement_proposals.json — the "
        "archive records it, the guard still refuses it")


def test_the_outcome_tracks_the_guard_and_is_not_a_constant(sandbox, monkeypatch):
    """POSITIVE CONTROL.

    A recorder that wrote a fixed outcome would pass every other test in this
    file. Same proposal text, two different guards: the records must differ.
    """
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _allow)
    so.save_proposals([_proposal("problem A")])
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _refuse)
    so.save_proposals([_proposal("problem B")])

    body = _archive_text(sandbox)
    assert "ACCEPTED" in body and "BLOCKED" in body, (
        f"the archive did not distinguish the two outcomes:\n{body[:800]}")
    a = body.index("problem A")
    b = body.index("problem B")
    assert "ACCEPTED" in body[:a] and "BLOCKED" in body[a:b + 200], \
        "the outcomes were recorded but attached to the wrong proposals"


def test_a_deduplicated_proposal_is_archived_rather_than_dropped(sandbox, monkeypatch):
    """The fourth lossy path, the one nobody had named.

    `if obs["problem"][:80] in existing_problems: continue` discarded a repeat
    without a trace. "The system keeps raising this" is a finding, not noise.
    """
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _allow)
    so.save_proposals([_proposal("Липса на питейна вода")])
    so.save_proposals([_proposal("Липса на питейна вода")])   # same again

    body = _archive_text(sandbox)
    assert "DUPLICATE" in body, "a re-proposed problem vanished without a record"
    assert body.count("Липса на питейна вода") >= 2, \
        "the repeat was not archived as its own entry"
    assert len(_live(sandbox)) == 1, "the dedup itself must still work"


# ---------------------------------------------------------------------------
# Append-only, including the wrong and the duplicated
# ---------------------------------------------------------------------------

def test_the_archive_is_append_only(sandbox, monkeypatch):
    """Byte-for-byte: earlier content must still be a PREFIX of the file.

    Not "the old text is still in there somewhere" — a rewrite that happened to
    re-emit the old entries would pass that. A prefix check cannot be satisfied
    by anything except appending.
    """
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _allow)
    so.save_proposals([_proposal("first problem")])
    month = sorted((sandbox / "proposal_archive").glob("20*.md"))[0]
    first = month.read_bytes()

    so.save_proposals([_proposal("second problem")])
    second = month.read_bytes()

    assert second.startswith(first), (
        "the archive was rewritten, not appended to — append-only is the single "
        "property this file has to keep")
    assert len(second) > len(first)


def test_a_nonsense_proposal_is_kept_too(sandbox, monkeypatch):
    """This is a record of what the system thought, not a list of good ideas."""
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _allow)
    so.save_proposals([_proposal("", component="", solution="")])
    body = _archive_text(sandbox)
    assert "ACCEPTED" in body and "(none recorded)" in body, (
        "an empty/nonsense proposal was silently skipped; curating the archive "
        "is exactly what it must not do")


def test_what_the_seven_day_cutoff_deletes_still_exists_in_the_archive(sandbox, monkeypatch):
    """The scenario the archive was built for, end to end.

    A proposal is archived when it is made. A week later save_proposals deletes
    it from improvement_proposals.json (MAX_AGE_DAYS=7). The live file must lose
    it and the archive must still have it.
    """
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _allow)
    so.save_proposals([_proposal("Замърсена вода — ще бъде изтрито след 7 дни")])
    assert len(_live(sandbox)) == 1

    # Age it past the cutoff, exactly as the passage of time would.
    live = sandbox / "memory" / "improvement_proposals.json"
    data = json.loads(live.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(days=so.MAX_AGE_DAYS + 1)).isoformat()
    data["proposals"][0]["timestamp"] = old
    live.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    so.save_proposals([_proposal("something else entirely")])

    assert not any("ще бъде изтрито" in p["problem"] for p in _live(sandbox)), \
        "the cutoff did not fire — this test is no longer testing anything"
    assert "ще бъде изтрито" in _archive_text(sandbox), (
        "the 7-day cutoff deleted the only copy; this is the bug, still present")


# ---------------------------------------------------------------------------
# The format criterion: answerable by a human, without writing code
# ---------------------------------------------------------------------------

def test_a_human_can_find_julys_water_proposals_by_searching_one_file(sandbox, monkeypatch):
    """The single criterion the format was chosen against.

    "What did the system propose about water in July" must be answerable by
    opening one file and searching it. So: July entries go in 2026-07.md, August
    entries do not, and the problem text is present verbatim and unescaped
    (Ctrl-F for Cyrillic has to actually match).
    """
    # Routing is exercised through record(), which is where it lives.
    # save_proposals deliberately stamps its OWN timestamp on an accepted
    # proposal (`obs["timestamp"] = now`), so a past date cannot be injected
    # through that door — only backfill carries historical dates, and it goes
    # through record() exactly like this.
    d = sandbox / "proposal_archive"
    pa.record(_proposal("Недостиг на вода през юли",
                        timestamp="2026-07-14T10:00:00+00:00"),
              pa.ACCEPTED, archive_dir=d)
    pa.record(_proposal("Нещо съвсем друго през август",
                        timestamp="2026-08-14T10:00:00+00:00"),
              pa.ACCEPTED, archive_dir=d)

    july, august = d / "2026-07.md", d / "2026-08.md"
    assert july.exists() and august.exists(), \
        "entries were not routed into per-month files"

    jt = july.read_text(encoding="utf-8")
    assert "Недостиг на вода през юли" in jt, (
        "the problem text is not searchable verbatim — escaped or reformatted "
        "text defeats the one thing this format is for")
    assert "\\u" not in jt, (
        "the file contains \\u-escapes; a human searching for 'вода' in an "
        "editor would find nothing, which is the failure mode that ruled out JSONL")
    assert "Нещо съвсем друго" not in jt, "August leaked into the July file"
    assert (d / "README.md").exists(), \
        "the archive must explain how to read it, in the directory itself"

    # ...and the live path must land in the current month, searchable the same way.
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _allow)
    so.save_proposals([_proposal("Замърсяване на водата днес")])
    this_month = d / f"{datetime.now(timezone.utc).strftime('%Y-%m')}.md"
    assert "Замърсяване на водата днес" in this_month.read_text(encoding="utf-8")


def test_provenance_is_recorded_or_honestly_marked_absent(sandbox, monkeypatch):
    """Model and provider when known; '(not recorded)' when not. Never invented."""
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _allow)
    p = _proposal("with provenance")
    p["_provenance"] = {"provider": "Cerebras", "model": "gpt-oss-120b",
                        "raw_response": "MODEL SAID THIS",
                        "generated_by": "self_observer:problem_solution"}
    so.save_proposals([p])
    so.save_proposals([_proposal("without provenance")])

    body = _archive_text(sandbox)
    assert "Cerebras" in body and "gpt-oss-120b" in body
    assert "MODEL SAID THIS" in body, \
        "the raw model output was not kept — it is the only reasoning-like text there is"
    assert "(not recorded)" in body, (
        "a proposal with no known model must SAY so; inventing a model name "
        "would make the archive worse than useless")
    assert "test-cycle-1" in body, "the cycle_id was not captured"
    assert "_provenance" not in json.dumps(_live(sandbox)), \
        "provenance leaked into improvement_proposals.json; it belongs only in the archive"


def test_backfill_is_rerunnable_without_duplicating(sandbox):
    """The rescue can be run twice. Append-only forbids cleaning up after it."""
    live = sandbox / "memory" / "improvement_proposals.json"
    live.write_text(json.dumps({"proposals": [
        _proposal("rescued one", timestamp="2026-08-01T00:00:00+00:00")]}),
        encoding="utf-8")

    first = pa.backfill(live_path=live, archive_dir=sandbox / "proposal_archive")
    second = pa.backfill(live_path=live, archive_dir=sandbox / "proposal_archive")

    assert first["archived"] == 1 and second["archived"] == 0
    assert second["already_present"] == 1
    assert _archive_text(sandbox).count("rescued one") == 1
    assert "backfilled:** true" in _archive_text(sandbox), (
        "a rescued proposal must be marked as such — its model and cycle_id "
        "were never recorded and the archive must not imply otherwise")


def test_the_archive_never_breaks_the_cycle(sandbox, monkeypatch):
    """Fail-open: an archive that cannot write must not take the step with it."""
    monkeypatch.setattr(guard, "evaluate_proposal_alignment", _allow)

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(pa, "record", _boom)
    so.save_proposals([_proposal("still must be saved")])
    assert len(_live(sandbox)) == 1, \
        "a failing archive stopped a proposal from being saved"
