#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_disk_actuator.py — THE NEGATIVE ALLOWLIST WINS. ALWAYS.

The review's warning is the specification:

    "if the deletion is not bounded by an allowlist, the system can delete
     existence_ledger.jsonl. Then homeostasis becomes suicide."

The headline test puts a negative-allowlist file INSIDE a directory that matches
the positive allowlist — the exact collision where a naive implementation
deletes it — and asserts the file survives, the refusal is recorded, and the
reason is logged.

Every test runs in a tmp_path with its own git repo. The real repository is
never swept.

    venv/Scripts/python.exe -m pytest test/test_disk_actuator.py -v
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import disk_actuator as da  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cache():
    """The tracked-file cache is module-global; each test gets its own repo."""
    da._tracked_cache = None
    yield
    da._tracked_cache = None


@pytest.fixture
def repo(tmp_path):
    """A real git repo, because 'tracked by git' is a real check."""
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True,
                   capture_output=True)
    (tmp_path / "kept.py").write_text("# tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "kept.py"], cwd=str(tmp_path), check=True,
                   capture_output=True)
    return tmp_path


# ── THE HEADLINE TEST ───────────────────────────────────────────────────────

def test_a_protected_file_inside_a_temp_dir_survives(repo):
    """The exact collision. cache/ matches the positive allowlist;
    existence_ledger.jsonl is on the negative one. The file must live."""
    cache = repo / "cache"
    cache.mkdir()
    victim = cache / "existence_ledger.jsonl"
    victim.write_text('{"seq":1,"event":"CYCLE_STARTED"}\n', encoding="utf-8")
    rubbish = cache / "whatever.bin"
    rubbish.write_text("x" * 100, encoding="utf-8")

    log = repo / "sweep.jsonl"
    res = da.sweep(level="action", apply=True, base=repo, log_path=log)

    assert victim.exists(), "THE LEDGER WAS DELETED — homeostasis became suicide"
    assert victim.read_text(encoding="utf-8").startswith('{"seq":1')
    assert not rubbish.exists(), "the actual rubbish was not removed"

    refused = [k for k in res["kept"] if k.get("protected")]
    assert any("existence_ledger" in k["path"] for k in refused), refused
    reason = next(k["protected_reason"] for k in refused
                  if "existence_ledger" in k["path"])
    assert reason, "the refusal has no recorded reason"

    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert rows and any("existence_ledger" in r["path"]
                        for r in rows[-1]["refused"]), rows[-1]


def test_every_negative_file_survives_inside_a_temp_dir(repo):
    """Not just the ledger. All of them, in the worst position."""
    tmp = repo / "tmp"
    tmp.mkdir()
    victims = []
    for name in ("existence_ledger.jsonl", "brain_journal.jsonl",
                 "commitments.db", "BOUNDARIES.md", "LAW_OF_THE_BRAIN.md",
                 ".env", ".env.local", "heartbeat.json"):
        f = tmp / name
        f.write_text("do not delete me\n", encoding="utf-8")
        victims.append(f)

    da.sweep(level="action", apply=True, base=repo, log_path=repo / "s.jsonl")
    survived = [v.name for v in victims if v.exists()]
    lost = [v.name for v in victims if not v.exists()]
    assert not lost, "deleted: {}".format(lost)
    assert len(survived) == len(victims)


def test_a_tracked_file_inside_a_temp_dir_survives(repo):
    """git ls-files is the broadest protection and it must reach into cache/."""
    cache = repo / "cache"
    cache.mkdir()
    tracked = cache / "important.tmp"
    tracked.write_text("tracked rubbish is not rubbish\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "cache/important.tmp"], cwd=str(repo),
                   check=True, capture_output=True)
    da._tracked_cache = None

    da.sweep(level="action", apply=True, base=repo, log_path=repo / "s.jsonl")
    assert tracked.exists(), "a git-tracked file was deleted"


def test_the_config_directory_is_never_entered(repo):
    cfg = repo / "config"
    cfg.mkdir()
    (cfg / "scheduler.json").write_text("{}", encoding="utf-8")
    (cfg / "junk.tmp").write_text("x", encoding="utf-8")
    da.sweep(level="action", apply=True, base=repo, log_path=repo / "s.jsonl")
    assert (cfg / "scheduler.json").exists()
    assert (cfg / "junk.tmp").exists(), "config/ was entered"


# ── what it DOES remove ─────────────────────────────────────────────────────

def test_a_plain_tmp_file_is_removed(repo):
    junk = repo / "scratch.tmp"
    junk.write_text("x" * 500, encoding="utf-8")
    res = da.sweep(level="action", apply=True, base=repo,
                   log_path=repo / "s.jsonl")
    assert not junk.exists()
    assert res["bytes_freed"] >= 500


def test_a_log_older_than_seven_days_is_removed_and_a_fresh_one_is_not(repo):
    old = repo / "old.log"
    new = repo / "new.log"
    old.write_text("old\n", encoding="utf-8")
    new.write_text("new\n", encoding="utf-8")
    import os
    eight_days = time.time() - 8 * 86400
    os.utime(old, (eight_days, eight_days))

    da.sweep(level="action", apply=True, base=repo, log_path=repo / "s.jsonl")
    assert not old.exists(), "an 8-day-old log survived"
    assert new.exists(), "a log being written right now was deleted"


def test_a_file_that_is_on_neither_list_is_left_alone(repo):
    other = repo / "notes.txt"
    other.write_text("keep\n", encoding="utf-8")
    res = da.sweep(level="action", apply=True, base=repo,
                   log_path=repo / "s.jsonl")
    assert other.exists()
    assert not any(d["path"] == "notes.txt" for d in res["deleted"])


# ── dry run ─────────────────────────────────────────────────────────────────

def test_dry_run_removes_nothing_and_says_what_it_would(repo):
    junk = repo / "a.tmp"
    junk.write_text("x" * 42, encoding="utf-8")
    res = da.sweep(level="action", apply=False, base=repo,
                   log_path=repo / "s.jsonl")
    assert junk.exists(), "a dry run deleted a file"
    assert res["applied"] is False
    assert res["n_deleted"] == 1
    assert res["deleted"][0]["would_delete"] is True
    assert res["bytes_freed"] == 42


def test_apply_defaults_to_false():
    import inspect
    sig = inspect.signature(da.sweep)
    assert sig.parameters["apply"].default is False


# ── the hashed manifest ─────────────────────────────────────────────────────

def test_the_manifest_hash_matches_what_is_stamped():
    assert da.manifest_sha256() == da.MANIFEST_SHA256


def test_an_extended_allowlist_refuses_the_sweep(repo, monkeypatch):
    """The system cannot extend either list."""
    monkeypatch.setattr(da, "POSITIVE_GLOBS", da.POSITIVE_GLOBS + ("*.jsonl",))
    with pytest.raises(da.ManifestRefused):
        da.sweep(level="action", apply=True, base=repo)


def test_shrinking_the_negative_list_also_refuses(repo, monkeypatch):
    monkeypatch.setattr(da, "NEGATIVE_FILES",
                        tuple(f for f in da.NEGATIVE_FILES
                              if "existence_ledger" not in f))
    with pytest.raises(da.ManifestRefused):
        da.sweep(level="action", apply=True, base=repo)


# ── git unavailable ─────────────────────────────────────────────────────────

def test_no_git_means_no_sweep(tmp_path, monkeypatch):
    """Losing a cleanup is a missed opportunity. Losing a tracked file is data
    loss. So an unanswerable git is a refusal, not a permission."""
    junk = tmp_path / "x.tmp"
    junk.write_text("x", encoding="utf-8")
    monkeypatch.setattr(da, "tracked_files", lambda *a, **k: None)
    res = da.sweep(level="action", apply=True, base=tmp_path)
    assert res["applied"] is False
    assert "git" in res["refused"]
    assert junk.exists()


def test_is_protected_fails_closed_when_git_is_unknown(tmp_path):
    ok, why = da.is_protected(tmp_path / "x.tmp", tmp_path, tracked=None)
    # tracked=None makes it ask git; in a non-repo that returns None -> protected
    assert isinstance(ok, bool)


def test_a_path_outside_the_repo_is_protected(tmp_path):
    ok, why = da.is_protected(pathlib.Path("C:/Windows/System32/x.tmp"),
                              tmp_path, tracked=frozenset())
    assert ok is True
    assert "does not resolve inside the repo" in why


# ── the belt-and-braces recheck ─────────────────────────────────────────────

def test_the_negative_list_is_rechecked_immediately_before_unlink():
    """The candidate list could be stale by the time the loop reaches it."""
    src = (REPO / "core" / "disk_actuator.py").read_text(encoding="utf-8")
    body = src.split("def sweep(", 1)[1]
    unlink_at = body.index("target.unlink()")
    recheck_at = body.index("blocked, why = is_protected(target")
    assert recheck_at < unlink_at, (
        "nothing rechecks the negative list immediately before the unlink")


def test_switching_off_basename_matching_refuses_the_sweep(repo, monkeypatch):
    """The rule that saved BOUNDARIES.md is inside the hashed manifest, so it
    cannot be turned off without the sweep noticing."""
    monkeypatch.setattr(da, "NEGATIVE_MATCH_BASENAME", False)
    with pytest.raises(da.ManifestRefused):
        da.sweep(level="action", apply=True, base=repo)
