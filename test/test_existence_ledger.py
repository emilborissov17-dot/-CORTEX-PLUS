"""Permanent test suite for the existence ledger.

The ledger is the system's record of its own continuous existence — and it is
written by the supervisor, about a cycle that (when killed) cannot vouch for
itself. So the properties that matter are:

  * append-only and tamper-EVIDENT (hash chain)
  * survives a torn write (power loss mid-append)
  * records WHY a kill happened, not merely that it did
  * never inflates the cycle count (that is MerkleMemory's job, and confusing
    the two would poison the system's self-model)
"""
import json

import pytest

from memory import existence_ledger as el


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(el, "LEDGER_PATH", tmp_path / "existence_ledger.jsonl")
    yield


# ---------------------------------------------------------------------------
# Append + chain
# ---------------------------------------------------------------------------

def test_first_event_chains_to_genesis():
    e = el.append(el.CYCLE_STARTED, cycle_id="c1", pid=1)
    assert e["seq"] == 1
    assert e["prev_hash"] == el.GENESIS_HASH
    assert len(e["hash"]) == 64


def test_events_chain_to_each_other():
    a = el.append(el.CYCLE_STARTED, cycle_id="c1")
    b = el.append(el.CYCLE_FINISHED, cycle_id="c1")

    assert b["prev_hash"] == a["hash"]
    assert b["seq"] == 2


def test_verify_accepts_an_honest_chain():
    el.append(el.CYCLE_STARTED, cycle_id="c1")
    el.append(el.CYCLE_FINISHED, cycle_id="c1")
    el.append(el.CYCLE_STARTED, cycle_id="c2")

    v = el.verify()
    assert v["valid"] is True
    assert v["events"] == 3
    assert v["broken_at"] is None


def test_verify_detects_an_edited_middle_event():
    """THE property: you cannot quietly rewrite your own history."""
    el.append(el.CYCLE_STARTED, cycle_id="c1")
    el.append(el.CYCLE_KILLED, cycle_id="c1")
    el.append(el.CYCLE_STARTED, cycle_id="c2")

    # Tamper: turn the kill into a clean finish.
    lines = el.LEDGER_PATH.read_text(encoding="utf-8").splitlines()
    ev = json.loads(lines[1])
    ev["event"] = el.CYCLE_FINISHED
    lines[1] = json.dumps(ev, ensure_ascii=False)
    el.LEDGER_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    v = el.verify()
    assert v["valid"] is False
    assert v["broken_at"] == 2


def test_verify_detects_a_deleted_event():
    """Deleting an inconvenient kill must break the chain."""
    el.append(el.CYCLE_STARTED, cycle_id="c1")
    el.append(el.CYCLE_KILLED, cycle_id="c1")
    el.append(el.CYCLE_STARTED, cycle_id="c2")

    lines = el.LEDGER_PATH.read_text(encoding="utf-8").splitlines()
    del lines[1]
    el.LEDGER_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert el.verify()["valid"] is False


def test_verify_detects_a_rehashed_but_reordered_chain():
    el.append(el.CYCLE_STARTED, cycle_id="c1")
    el.append(el.CYCLE_FINISHED, cycle_id="c1")

    lines = el.LEDGER_PATH.read_text(encoding="utf-8").splitlines()
    el.LEDGER_PATH.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")

    assert el.verify()["valid"] is False


def test_empty_ledger_is_valid():
    v = el.verify()
    assert v["valid"] is True
    assert v["head_hash"] == el.GENESIS_HASH


def test_torn_final_line_does_not_destroy_the_ledger():
    """Power loss mid-append. The chain BEFORE the torn line is still intact and
    must remain readable and verifiable."""
    el.append(el.CYCLE_STARTED, cycle_id="c1")
    el.append(el.CYCLE_FINISHED, cycle_id="c1")

    with el.LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 3, "event": "CYCLE_ST')   # torn

    assert len(el.read_all()) == 2
    assert el.verify()["valid"] is True


# ---------------------------------------------------------------------------
# Kill reasons — the requirement: WHY, not just THAT
# ---------------------------------------------------------------------------

def test_kill_records_why_not_just_that():
    el.record_kill(
        cycle_id="c1", pid=4242, step="internet_agent", step_index="4",
        heartbeat_age_sec=2820.0, ceiling_sec=2700, restart_number=1,
    )

    ev = el.head()
    assert ev["event"] == el.CYCLE_KILLED
    r = ev["reason"]
    assert r["wedged_step"] == "internet_agent"
    assert r["heartbeat_age_sec"] == 2820.0
    assert r["ceiling_sec"] == 2700
    assert r["exceeded_by_sec"] == 120.0, "must say by how much the ceiling was blown"
    assert ev["restart_number"] == 1


def test_kill_reason_survives_missing_fields():
    """A kill with no readable heartbeat (no proof of life at all) still records
    what it can, rather than refusing to record the death."""
    ev = el.record_kill(cycle_id="c1", pid=1, step=None,
                        heartbeat_age_sec=None, ceiling_sec=900)
    r = ev["reason"]
    assert r["wedged_step"] is None
    assert r["exceeded_by_sec"] is None


def test_kills_by_step_is_groupable():
    """'Which step kills me?' must be answerable by GROUP BY, not guesswork."""
    for _ in range(3):
        el.record_kill(cycle_id="c", pid=1, step="internet_agent",
                       heartbeat_age_sec=3000, ceiling_sec=2700)
    el.record_kill(cycle_id="c", pid=1, step="web_intelligence",
                   heartbeat_age_sec=4000, ceiling_sec=3600)

    s = el.summary()
    assert s["kills_by_step"] == {"internet_agent": 3, "web_intelligence": 1}
    assert list(s["kills_by_step"])[0] == "internet_agent", "most frequent first"


# ---------------------------------------------------------------------------
# Deaths — witnessed after the fact, distinct from deliberate kills
# ---------------------------------------------------------------------------

def test_record_death_stores_the_last_step():
    ev = el.record_death(cycle_id="c1", pid=4321, last_step="web_intelligence",
                         detail="stale lock, no CYCLE_FINISHED")
    assert ev["event"] == el.CYCLE_DIED
    assert ev["cycle_id"] == "c1"
    assert ev["last_step"] == "web_intelligence"
    assert ev["detail"] == "stale lock, no CYCLE_FINISHED"


def test_record_death_falls_back_to_unknown_when_no_step_survived():
    """A cycle that died before its first beat has no last step; the death is still
    recorded, as 'unknown', rather than refused."""
    ev = el.record_death(cycle_id="c1", pid=4321, last_step=None)
    assert ev["last_step"] == "unknown"


def test_a_death_is_not_a_kill():
    """CYCLE_DIED and CYCLE_KILLED are different events and must not be conflated:
    one was deliberate and measured, the other discovered after the fact."""
    el.record_death(cycle_id="c1", pid=1, last_step="x")
    s = el.summary()
    assert s["total_deaths"] == 1
    assert s["total_kills"] == 0, "a death must never be counted as a kill"


def test_deaths_are_groupable_by_step():
    """'Which step do I die in?' — the same GROUP-BY question as kills."""
    for _ in range(2):
        el.record_death(cycle_id="c", pid=1, last_step="web_intelligence")
    el.record_death(cycle_id="c", pid=1, last_step="scoring_engine")

    s = el.summary()
    assert s["deaths_by_step"] == {"web_intelligence": 2, "scoring_engine": 1}
    assert list(s["deaths_by_step"])[0] == "web_intelligence", "most frequent first"


def test_record_death_keeps_the_chain_valid():
    el.append(el.CYCLE_STARTED, cycle_id="c1")
    el.record_death(cycle_id="c1", pid=1, last_step="x")
    assert el.verify()["valid"] is True


# ---------------------------------------------------------------------------
# has_finished — telling a died cycle from a cleanly-finished one
# ---------------------------------------------------------------------------

def test_has_finished_true_only_for_a_sealed_cycle():
    el.append(el.CYCLE_STARTED, cycle_id="c1")
    el.append(el.CYCLE_FINISHED, cycle_id="c1")
    el.append(el.CYCLE_STARTED, cycle_id="c2")     # started, not finished

    assert el.has_finished("c1") is True
    assert el.has_finished("c2") is False, "a started-but-not-finished cycle did not finish"
    assert el.has_finished("never-seen") is False


def test_has_finished_is_false_without_a_cycle_id():
    """A corrupt lock gives no cycle_id to match: we cannot prove it finished, so
    we must not claim it did."""
    el.append(el.CYCLE_FINISHED, cycle_id="c1")
    assert el.has_finished(None) is False
    assert el.has_finished("") is False


# ---------------------------------------------------------------------------
# Summary — "what is my life like?"
# ---------------------------------------------------------------------------

def test_summary_of_an_empty_life():
    s = el.summary()
    assert s["exists"] is False


def test_summary_counts_existence():
    el.append(el.CYCLE_STARTED, cycle_id="c1")
    el.append(el.CYCLE_FINISHED, cycle_id="c1")
    el.append(el.CYCLE_STARTED, cycle_id="c2")
    el.record_kill(cycle_id="c2", pid=1, step="x", heartbeat_age_sec=1000, ceiling_sec=900)
    el.append(el.MISSED_SKIPPED, scheduled_for="2026-07-12T03:00:00Z")

    s = el.summary()
    assert s["exists"] is True
    assert s["total_cycles_started"] == 2
    assert s["total_cycles_finished"] == 1
    assert s["total_kills"] == 1
    assert s["total_missed_skipped"] == 1
    assert s["chain_valid"] is True


def test_summary_reports_a_broken_chain():
    el.append(el.CYCLE_STARTED, cycle_id="c1")
    lines = el.LEDGER_PATH.read_text(encoding="utf-8").splitlines()
    ev = json.loads(lines[0]); ev["cycle_id"] = "tampered"
    el.LEDGER_PATH.write_text(json.dumps(ev) + "\n", encoding="utf-8")

    assert el.summary()["chain_valid"] is False


# ---------------------------------------------------------------------------
# Separation from MerkleMemory
# ---------------------------------------------------------------------------

def test_ledger_does_not_touch_merkle_cycle_state():
    """The ledger must NEVER call MerkleMemory.commit(): that would register a
    fake cycle, inflate total_cycles, and push goal_score=0.0 into the trend
    vectors — poisoning the self-model with the system's own supervision."""
    import ast

    text = open(el.__file__, encoding="utf-8").read()

    # Assert on the AST, not on the text. The docstring legitimately DISCUSSES
    # MerkleMemory.commit() — it exists to explain why this module must never
    # call it — so a substring check would fire on the very comment that
    # documents the rule.
    tree = ast.parse(text)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert "merkle" not in a.name.lower(), f"ledger imports {a.name}"
        elif isinstance(node, ast.ImportFrom):
            assert "merkle" not in (node.module or "").lower(), \
                f"ledger imports from {node.module}"
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                assert fn.attr != "commit", \
                    "the ledger must never call .commit() — that would register a fake cycle"


def test_head_hash_is_stable_and_advances():
    h0 = el.head_hash()
    assert h0 == el.GENESIS_HASH

    el.append(el.CYCLE_STARTED, cycle_id="c1")
    h1 = el.head_hash()
    assert h1 != h0

    el.append(el.CYCLE_FINISHED, cycle_id="c1")
    assert el.head_hash() != h1


def test_ledger_path_is_in_the_protected_denylist():
    """The audit trail must not be forgeable by a self-generated patch."""
    from safety.protected_paths import is_protected
    assert is_protected("memory/existence_ledger.jsonl")
