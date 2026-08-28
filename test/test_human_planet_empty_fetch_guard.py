"""An empty fetch is not REAL_DATA — for the HUMAN and PLANET snapshot agents.

PROVENANCE OF THIS REQUIREMENT, stated because it is unusual.
------------------------------------------------------------
The requirement is RECOVERED; the implementation it describes is GONE. On
2026-08-28 a `git reset --hard` overwrote 86 tracked files that carried
uncommitted modifications, among them these two agents. The source is not
recoverable — no decompiler supports CPython 3.14 bytecode — but the compiled
caches predate the reset and their string constants are readable, so what the
lost change REQUIRED survives even though how it was written does not.

From agents/human/__pycache__/human_snapshots_agent_qwen.cpython-314.pyc,
compiled 2026-08-17 14:16:18:

    'provider returned no data and nothing to carry forward'
    ': empty fetch — CARRIED FORWARD -> '
    'REAL_DATA_CARRIED'
    '_carried'

From agents/planet/__pycache__/planet_snapshots_agent_qwen.cpython-314.pyc,
same timestamp:

    ': empty fetch and nothing to carry forward — writing an honestly empty snapshot'
    ' metric(s) instead of erasing the axis'
    ': empty fetch — CARRIED FORWARD '
    '[PLANET_SNAPSHOT][WARN] '

These tests are written FROM those strings and the code that satisfies them is
NEW WORK dated 2026-08-28. Nothing here was reassembled from bytecode: a file
built out of recovered string constants would be new code wearing a dead file's
name, and calling that "recovered" is assertion dressed as verification.

WHY IT MATTERS TODAY, and why this went first
----------------------------------------------
This is not a restoration, it is a LIVE REGRESSION.
test_axis_snapshot_carry::test_every_axis_agent_guards_the_empty_fetch has been
failing since the reset because the human agent writes an empty fetch as
REAL_DATA. A snapshot labelled REAL_DATA whose payload is empty is the exact
measurement-honesty defect this repo keeps finding: absence recorded as an
observation. The civilization and cosmos agents kept their guard because their
modifications had been committed; these two had not been, for eleven days.
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

AGENTS = {
    "human": REPO / "agents" / "human" / "human_snapshots_agent_qwen.py",
    "planet": REPO / "agents" / "planet" / "planet_snapshots_agent_qwen.py",
}


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_an_empty_fetch_is_never_written_as_real_data(name):
    """The hole itself: `raw` falsy, straight into a REAL_DATA snapshot."""
    src = AGENTS[name].read_text(encoding="utf-8")
    assert "if not raw:" in src, (
        f"{name} agent writes an empty fetch as REAL_DATA — empty is not success")


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_there_is_a_carry_forward_path(name):
    """Recovered: 'CARRIED FORWARD'. Never overwrite a good value with nothing."""
    src = AGENTS[name].read_text(encoding="utf-8")
    assert "carry_forward" in src, f"{name} agent has no carry-forward path"
    assert "CARRIED FORWARD" in src, (
        f"{name} agent carries forward without SAYING it carried forward — a "
        f"silent carry is indistinguishable from a fresh read")


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_a_carried_snapshot_is_labelled_as_carried(name):
    """Recovered: 'REAL_DATA_CARRIED'. A carried value is real, but it is not new,
    and a reader must be able to tell one from the other."""
    src = AGENTS[name].read_text(encoding="utf-8")
    assert "REAL_DATA_CARRIED" in src, (
        f"{name} agent must not label a carried value plain REAL_DATA")


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_nothing_to_carry_is_said_out_loud(name):
    """Recovered: 'provider returned no data and nothing to carry forward' and
    'empty fetch and nothing to carry forward — writing an honestly empty
    snapshot'. The dead end is the case that must not pass silently."""
    src = AGENTS[name].read_text(encoding="utf-8")
    assert "nothing to carry forward" in src, (
        f"{name} agent does not name the case where there is no prior value")


def test_the_planet_agent_counts_what_it_carried():
    """Recovered: ' metric(s) instead of erasing the axis'. The count is the
    evidence that a carry preserved something rather than papering over a gap."""
    src = AGENTS["planet"].read_text(encoding="utf-8")
    assert "instead of erasing the axis" in src
    assert "[PLANET_SNAPSHOT][WARN]" in src, (
        "a carry is a WARNing, not routine output")


def test_the_human_guard_runs_before_its_write():
    """Order is the whole fix. A guard after _write has already lied to disk.

    Scoped to main() on purpose: _carry_forward's docstring quotes the very
    payload it exists to prevent, and a whole-file search matches the quotation.
    """
    src = AGENTS["human"].read_text(encoding="utf-8")
    main = src.index("def main(")
    assert src.index("if not raw:", main) < src.index('"source_type": "REAL_DATA"', main)


def test_the_planet_guard_lives_in_the_writer_so_it_covers_every_call_site():
    """PLANET has five REAL_DATA write sites, not one. Guarding them one at a
    time is how the sixth gets added without one — so the check sits inside
    write_axis_snapshot, which is by construction before the file is written."""
    src = AGENTS["planet"].read_text(encoding="utf-8")
    writer = src.index("def write_axis_snapshot")
    guard = src.index("if not raw and", writer)
    disk = src.index("out_path.write_text", writer)
    assert writer < guard < disk, (
        "the planet guard must be inside write_axis_snapshot and before the "
        "write_text that puts the snapshot on disk")


def test_the_planet_dead_end_writes_an_honest_empty_not_an_invented_one():
    """Recovered: 'writing an honestly empty snapshot'. PLANET does not fall
    through to the LLM here — an empty dict that SAYS it is empty is worth more
    to a scorer than a plausible one."""
    src = AGENTS["planet"].read_text(encoding="utf-8")
    assert "REAL_DATA_EMPTY" in src
    assert "empty_why" in src, "an empty snapshot must say why it is empty"
