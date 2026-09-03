# -*- coding: utf-8 -*-
"""
merkle_memory.py — the three integrity failures found on 3 Sep 2026.

G1  The next cycle number came from state.json total_cycles + 1. state.json is a
    mutable file and was reset on 28 Aug: the counter went back while all 56 cycle
    directories survived, so the nights of 1-3 Sep OVERWROTE cycle_000017/18/19,
    which held July cycles. That is data loss, not a numbering cosmetic.

G2  hashes.json["essence.md"] could never match essence.md: the hash was taken at
    step 6 and the file was rewritten at step 7, four lines later. Two of the three
    abstraction hashes verified; the third was structurally always yesterday's.

G3  verify_cycle() existed from the beginning and its only caller was the module's
    own __main__ demo. Every night a hash was written and never checked.

No network, no cycle. The archive fixtures are tmp_path directories.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import merkle_memory as MM  # noqa: E402


def _archive(tmp_path: Path, nums) -> Path:
    root = tmp_path / "archive"
    root.mkdir(parents=True, exist_ok=True)
    for n in nums:
        (root / f"cycle_{n:06d}").mkdir()
    return root


# ── G1: the number comes from the archive, never from a mutable counter ───────

def test_the_live_bug_a_reset_counter_must_not_reuse_a_live_directory(tmp_path):
    """THE EXACT LIVE STATE, 3 Sep 2026: 56 directories on disk, total_cycles 19.
    The old code returned 20 and would have overwritten cycle_000020's July
    content that night. It must return 57."""
    root = _archive(tmp_path, range(1, 57))
    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    mm._state = {"total_cycles": 19}

    assert mm._next_cycle_num(archive=root) == 57


def test_an_empty_archive_starts_at_one(tmp_path):
    root = _archive(tmp_path, [])
    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    mm._state = {"total_cycles": 0}
    assert mm._next_cycle_num(archive=root) == 1


def test_a_gap_in_the_numbering_does_not_walk_the_counter_backwards(tmp_path):
    """A deleted directory leaves a hole. max()+1 still clears every live one —
    filling the hole would overwrite nothing, but it would make two cycles share
    a number in the training data downstream."""
    root = _archive(tmp_path, [1, 2, 3, 40, 41])
    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    mm._state = {"total_cycles": 3}
    assert mm._next_cycle_num(archive=root) == 42


def test_a_counter_ahead_of_the_archive_still_wins(tmp_path):
    """The rule is max(disk, state), not "disk always". If the archive was pruned
    but the counter remembers more cycles, the counter is the survivor of the two
    and must not be walked back onto a number that history already used."""
    root = _archive(tmp_path, [1, 2, 3])
    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    mm._state = {"total_cycles": 90}
    assert mm._next_cycle_num(archive=root) == 91


def test_a_stray_name_in_the_archive_is_not_a_number(tmp_path):
    root = _archive(tmp_path, [1, 2])
    (root / "cycle_notanumber").mkdir()
    (root / "merkle_root.txt").write_text("x", encoding="utf-8")
    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    mm._state = {"total_cycles": 0}
    assert mm._next_cycle_num(archive=root) == 3


def test_the_live_archive_next_write_is_fifty_seven():
    """Against the REAL cortex_memory/ on this machine — the check that actually
    protects tonight's 03:04 cycle."""
    mm = MM.MerkleMemory()
    nums = mm._archived_cycle_nums()
    assert max(nums) == 56, f"the live archive moved: max is {max(nums)}"
    assert mm._next_cycle_num() == 57
    assert mm._state.get("total_cycles") == 56, \
        "state.json was not reconciled to the archive"


# ── G2: essence.md is hashed in its final form ────────────────────────────────

def test_essence_is_written_before_it_is_hashed():
    """Source-order guard. The bug was four lines apart and invisible in any
    output: the file simply never matched its own recorded hash."""
    src = (REPO / "merkle_memory.py").read_text(encoding="utf-8")
    write_at = src.index("ESSENCE_FILE.write_text(essence")
    hash_at = src.index("self._update_abs_hashes()", src.index("def commit"))
    assert write_at < hash_at, \
        "essence.md is hashed before it is written — hashes.json can never match"


def test_the_recorded_essence_hash_matches_the_file_after_a_hash_update(tmp_path,
                                                                       monkeypatch):
    """The property itself, not the line order: run the two steps in the fixed
    order and the recorded hash must describe the file on disk."""
    ab = tmp_path / "abstractions"
    ab.mkdir()
    ess, tr, pr = ab / "essence.md", ab / "trends.json", ab / "self_profile.json"
    hashes = ab / "hashes.json"
    tr.write_text('{"a": 1}', encoding="utf-8")
    pr.write_text('{"b": 2}', encoding="utf-8")
    monkeypatch.setattr(MM, "ESSENCE_FILE", ess)
    monkeypatch.setattr(MM, "TRENDS_FILE", tr)
    monkeypatch.setattr(MM, "PROFILE_FILE", pr)
    monkeypatch.setattr(MM, "ABS_HASHES", hashes)

    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    ess.write_text("# tonight's essence\n", encoding="utf-8")   # step 7
    mm._update_abs_hashes()                                     # step 8

    rec = json.loads(hashes.read_text(encoding="utf-8"))
    on_disk = hashlib.sha256(
        ess.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    assert rec["essence.md"] == on_disk


def test_a_stale_hash_is_what_the_old_order_produced(tmp_path, monkeypatch):
    """Negative control: hash first, write second — and the record is wrong. If
    this ever stops failing to match, the guard above is not testing anything."""
    ab = tmp_path / "abstractions"
    ab.mkdir()
    ess, hashes = ab / "essence.md", ab / "hashes.json"
    ess.write_text("yesterday\n", encoding="utf-8")
    monkeypatch.setattr(MM, "ESSENCE_FILE", ess)
    monkeypatch.setattr(MM, "TRENDS_FILE", ab / "nope_trends.json")
    monkeypatch.setattr(MM, "PROFILE_FILE", ab / "nope_profile.json")
    monkeypatch.setattr(MM, "ABS_HASHES", hashes)

    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    mm._update_abs_hashes()                       # the OLD order: hash first
    ess.write_text("today\n", encoding="utf-8")   # ...then overwrite

    rec = json.loads(hashes.read_text(encoding="utf-8"))
    on_disk = hashlib.sha256(
        ess.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    assert rec["essence.md"] != on_disk, "the negative control no longer reproduces"


# ── G3: the seal is verified, and a failure is named ──────────────────────────

def _seal(root: Path, num: int, cycle_id="c1", ts="t", count=2, goal=0.5,
          corrupt=False):
    d = root / f"cycle_{num:06d}"
    d.mkdir(parents=True)
    (d / "signals.json").write_text(json.dumps(
        {"cycle_id": cycle_id, "timestamp": ts, "count": count}), encoding="utf-8")
    (d / "results.json").write_text(json.dumps({"goal_score": goal}),
                                    encoding="utf-8")
    h = hashlib.sha256(json.dumps(
        {"cycle_id": cycle_id, "ts": ts, "signals_count": count,
         "goal_score": goal}, sort_keys=True).encode("utf-8")).hexdigest()
    (d / "hash.txt").write_text("deadbeef" if corrupt else h, encoding="utf-8")
    return d


def test_a_correctly_sealed_cycle_verifies(tmp_path, monkeypatch):
    root = tmp_path / "archive"
    _seal(root, 57)
    monkeypatch.setattr(MM, "ARCHIVE", root)
    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    assert mm.verify_cycle(57)["ok"] is True


def test_a_tampered_cycle_fails_verification(tmp_path, monkeypatch):
    """The whole point: an edited archive must not pass."""
    root = tmp_path / "archive"
    _seal(root, 57, corrupt=True)
    monkeypatch.setattr(MM, "ARCHIVE", root)
    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    assert mm.verify_cycle(57)["ok"] is False


def test_a_missing_cycle_fails_rather_than_passing_quietly(tmp_path, monkeypatch):
    root = tmp_path / "archive"
    root.mkdir()
    monkeypatch.setattr(MM, "ARCHIVE", root)
    mm = MM.MerkleMemory.__new__(MM.MerkleMemory)
    v = mm.verify_cycle(57)
    assert v["ok"] is False and v["error"]


def test_the_verify_step_is_wired_into_the_cycle_and_all_three_maps():
    """WIRE_FIRST: a verifier nothing calls is the state this task existed to end."""
    import core.cycle_map as cm
    assert cm.produces("merkle_verify") == ["memory/merkle_verify_latest.json"]
    assert cm.is_backbone("merkle_verify"), \
        "the audit-chain check must not be skippable by opinion"

    phases = json.loads((REPO / "config" / "cycle_phases.json")
                        .read_text(encoding="utf-8"))
    g = phases["phases"]["G_LEARN"]
    names = [s["name"] for s in g["steps"]]
    assert "merkle_verify" in names
    assert "memory/merkle_verify_latest.json" in g["produces"]
    # it must run AFTER the commit it verifies
    assert names.index("merkle_verify") > names.index("merklememory_commit")

    runner = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert 'beat("merkle_verify", "24.1")' in runner
    assert runner.index('beat("merklememory_commit"') < \
        runner.index('beat("merkle_verify"')


def test_the_loss_is_on_the_permanent_record():
    """The overwrite is not recoverable. What is owed is that it is written down
    where it cannot be quietly edited away."""
    from memory import existence_ledger as EL
    rows = [e for e in EL.read_all()
            if e.get("event") == "ARCHIVE_OVERWRITTEN_BY_RESET_COUNTER"]
    assert rows, "the July overwrite is not recorded in the existence ledger"
    e = rows[-1]
    assert e["lost_cycles"] == ["cycle_000017", "cycle_000018", "cycle_000019"]
    assert e["recoverable"] is False
    assert EL.verify()["valid"], "the ledger chain is broken"
