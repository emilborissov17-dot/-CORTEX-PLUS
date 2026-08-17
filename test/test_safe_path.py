#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_safe_path.py — THE CONTAINMENT GUARD, EXECUTED.

WHY THESE ARE BEHAVIOURAL AND NOT SOURCE-STRUCTURE TESTS
---------------------------------------------------------
safety/safe_path.py is a function. It can be run, so it is run. Reading its source and
asserting that it "looks like" it refuses traversal would prove nothing about what it
does with '..\\..\\x' on Windows, and nothing at all about symlinks — which are the
one case the repo's existing string-level guard cannot see, and therefore the only
reason this module was written.

THE HOLE THIS CLOSES (measured 17 Aug 2026, against the live guardian)
-----------------------------------------------------------------------
    agents/core/evil_patch.py  ->  protected_paths.normalise()  accepted
                                   patch_guardian._is_dynamic_patch  True
                                   patch_guardian._is_patchable      True

Every string-level check passes. If that name is a symlink pointing outside the repo,
write_text() follows it. normalise() cannot catch this and is not at fault: it never
touches the filesystem, by design. safe_path() calls realpath and judges containment
after the link is followed.

test_symlink_escape_is_refused is the load-bearing test in this file. The rest are
the cases that were already covered by string logic — kept because this module is
now the layer callers depend on, and a guard that only closes the newest hole while
regressing the old ones is not an improvement.

    venv\\Scripts\\python.exe -m pytest test/test_safe_path.py -v
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from safety.safe_path import (MEMORY_ROOT, REPO_ROOT, UnsafePath, is_safe,
                            safe_memory_path, safe_path, safe_repo_path)


# ---------------------------------------------------------------------------
# The legitimate case — first, because a guard that refuses everything is easy
# ---------------------------------------------------------------------------

def test_the_trivial_legitimate_case_is_allowed():
    """An ordinary relative fragment resolves to an absolute path inside the root.

    If this ever fails, every caller is dead and the guard has become a wall. It is
    first in the file on purpose: a refusal test that passes because the function
    raises unconditionally is worthless, and this is what rules that out.
    """
    got = safe_path("memory/heartbeat.json", REPO_ROOT)

    assert got.is_absolute()
    assert got == REPO_ROOT / "memory" / "heartbeat.json"
    assert got.relative_to(REPO_ROOT) == Path("memory/heartbeat.json")


def test_nested_fragment_and_both_separator_styles():
    """Windows callers pass backslashes; the guard must not treat that as exotic."""
    assert safe_path("agents/core/x_patch.py", REPO_ROOT) == REPO_ROOT / "agents/core/x_patch.py"
    assert safe_path(r"agents\core\x_patch.py", REPO_ROOT) == REPO_ROOT / "agents/core/x_patch.py"


def test_the_target_need_not_exist_yet():
    """The usual case is a file about to be CREATED. Requiring existence would make
    the guard unusable exactly where it is needed."""
    p = safe_path("memory/does_not_exist_" + "a" * 20 + ".json", REPO_ROOT)
    assert not p.exists()
    assert p.relative_to(REPO_ROOT)


def test_convenience_roots_point_where_they_claim():
    assert safe_repo_path("memory/x.json") == REPO_ROOT / "memory" / "x.json"
    assert safe_memory_path("x.json") == MEMORY_ROOT / "x.json"
    with pytest.raises(UnsafePath):
        safe_memory_path("../config/scheduler.json")     # out of memory/, into the repo


# ---------------------------------------------------------------------------
# The escapes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fragment, label", [
    ("/etc/passwd",                    "absolute POSIX"),
    ("/",                              "bare root"),
    ("C:/Windows/system.ini",          "drive-absolute"),
    ("C:\\Windows\\system.ini",        "drive-absolute, backslashes"),
    ("C:evil.py",                      "drive-RELATIVE (resolves against that drive's CWD)"),
    ("//server/share/payload.py",      "UNC"),
    ("\\\\server\\share\\payload.py",  "UNC, backslashes"),
    ("..",                             "bare .."),
    ("../evil.py",                     "one level up"),
    ("../../../../../../etc/passwd",   "many levels up"),
    ("agents/core/../../../evil.py",   "climbs out after a legitimate prefix"),
    ("memory/./../../evil.py",         ".. hidden behind a ."),
    ("",                               "empty"),
    ("   ",                            "whitespace only"),
    ("\t\n",                           "whitespace only, exotic"),
    ("x\x00.py",                       "NUL byte (C-layer truncation)"),
    (None,                             "None"),
])
def test_escapes_are_refused(fragment, label):
    """Each of these must raise. None may return a 'cleaned' path.

    THE STAKE: the return value of this function is passed straight to write_text().
    A guard that normalises an escape into something writable is not a guard, it is a
    laundering step — which is why there is no 'sanitised' return path at all.
    """
    with pytest.raises(UnsafePath):
        safe_path(fragment, REPO_ROOT)


def test_dot_dot_is_refused_even_when_it_resolves_back_inside():
    """'a/../b' lands inside the root and is STILL refused.

    Deliberate. "Harmless traversal" and "traversal" differ only by arithmetic that a
    reviewer has to redo on every reading, and no caller in this repo needs it. The
    test exists so that the strictness is a decision on record rather than an
    accident someone later "fixes".
    """
    assert (REPO_ROOT / "memory/../memory/x.json").resolve() == REPO_ROOT / "memory/x.json"
    with pytest.raises(UnsafePath):
        safe_path("memory/../memory/x.json", REPO_ROOT)


def test_the_root_itself_is_not_a_path_within_the_root():
    """Resolving to the root is refused: callers want a file, and '.' would hand them
    a directory to write over."""
    with pytest.raises(UnsafePath):
        safe_path(".", REPO_ROOT)


# ---------------------------------------------------------------------------
# The symlink — the case string logic cannot reach
# ---------------------------------------------------------------------------

def _can_symlink(tmp_path: Path) -> bool:
    """Windows needs Developer Mode or admin to create symlinks."""
    try:
        (tmp_path / "_probe_target").write_text("x", encoding="utf-8")
        (tmp_path / "_probe_link").symlink_to(tmp_path / "_probe_target")
        return True
    except (OSError, NotImplementedError):
        return False


def test_symlink_escape_is_refused(tmp_path):
    """A symlink INSIDE the root pointing OUTSIDE it must be refused.

    THE LOAD-BEARING TEST. This is the only failure mode that
    safety/protected_paths.normalise() cannot detect — it is pure string logic and
    never stats a file — and it is the entire reason safety/safe_path.py exists.

    The scenario is not hypothetical: patch_guardian accepts any
    'agents/core/*_patch.py' as a dynamic patch without the name having to be known
    in advance, so an attacker-influenced proposal that gets a symlink of that shape
    onto disk would have had its write followed straight out of the repo.
    """
    if not _can_symlink(tmp_path):
        pytest.skip("symlinks unavailable (Windows without Developer Mode/admin)")

    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("do not overwrite", encoding="utf-8")

    (root / "escape.txt").symlink_to(outside / "secret.txt")

    # Sanity: the link really does leave the root, or the test proves nothing.
    assert Path(os.path.realpath(root / "escape.txt")).parent == Path(os.path.realpath(outside))

    with pytest.raises(UnsafePath) as e:
        safe_path("escape.txt", root)
    assert "outside" in str(e.value).lower() or "symlink" in str(e.value).lower()


def test_symlinked_directory_escape_is_refused(tmp_path):
    """The link need not be the leaf. An intermediate directory is the subtler case:
    the filename looks entirely ordinary and the escape is one level up the path."""
    if not _can_symlink(tmp_path):
        pytest.skip("symlinks unavailable (Windows without Developer Mode/admin)")

    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    (outside / "nested").mkdir(parents=True)

    (root / "agents").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePath):
        safe_path("agents/nested/x_patch.py", root)


def test_a_symlink_that_stays_inside_is_allowed(tmp_path):
    """Containment, not symlink-phobia. A link that resolves within the root is fine —
    otherwise the guard would refuse legitimate layouts and get switched off."""
    if not _can_symlink(tmp_path):
        pytest.skip("symlinks unavailable (Windows without Developer Mode/admin)")

    root = tmp_path / "root"
    (root / "real").mkdir(parents=True)
    (root / "real" / "f.txt").write_text("ok", encoding="utf-8")
    (root / "alias").symlink_to(root / "real", target_is_directory=True)

    got = safe_path("alias/f.txt", root)
    assert got == Path(os.path.realpath(root / "real" / "f.txt"))


# ---------------------------------------------------------------------------
# The boolean form
# ---------------------------------------------------------------------------

def test_is_safe_agrees_with_safe_path():
    assert is_safe("memory/x.json", REPO_ROOT) is True
    for bad in ("/etc/passwd", "../x", "C:/x", "", ".."):
        assert is_safe(bad, REPO_ROOT) is False, f"is_safe accepted {bad!r}"


def test_unsafe_path_is_a_valueerror():
    """Existing `except Exception` / `except ValueError` handlers must keep working —
    a new exception type that slips past every current handler would turn a refusal
    into a crash in the middle of the patch pipeline."""
    assert issubclass(UnsafePath, ValueError)


def test_the_refusal_says_which_fragment_and_why():
    """A refusal that does not name the input is unactionable in a log at 03:00."""
    with pytest.raises(UnsafePath) as e:
        safe_path("../../evil.py", REPO_ROOT)
    msg = str(e.value)
    assert "evil.py" in msg and ".." in msg


# ---------------------------------------------------------------------------
# SOURCE-STRUCTURE: the tainted write site must route through the guard
#
# The tests above prove the guard works. This one proves it is USED. They are
# different claims, and only the second one fails when someone reverts the call
# site in a refactor while leaving safety/safe_path.py untouched and green.
# ---------------------------------------------------------------------------

GUARDIAN = REPO_ROOT / "patch_guardian.py"


def _reaches_write_unguarded(src: str) -> list[str]:
    """Sites where a model-produced filename becomes a Path without the guard.

    The taint in this repo is specific and worth naming rather than generalising:
    PatchGuardian.apply_patch(filename, new_code) takes `filename` from a proposal
    composed by self_observer / self_modifier — by a model — and writes new_code to
    it. `Path(filename)` there is the flow; `safe_repo_path(filename)` is the fix.
    """
    bad = []
    for n, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.search(r"=\s*Path\(\s*filename\s*\)", stripped):
            bad.append(f"patch_guardian.py:{n}: {stripped}")
    return bad


def test_the_unguarded_detector_actually_detects():
    """POSITIVE CONTROL: a scan that finds nothing proves nothing until it is shown
    catching the exact line that used to be there."""
    assert _reaches_write_unguarded("        file_path = Path(filename)"), \
        "detector missed the pre-fix line — it would pass on a reverted call site"
    assert _reaches_write_unguarded("file_path=Path( filename )"), \
        "detector is whitespace-brittle"
    assert not _reaches_write_unguarded("        file_path = safe_path(filename, Path.cwd())"), \
        "detector false-positived on the guarded form"
    assert not _reaches_write_unguarded("        # file_path = Path(filename)"), \
        "detector fired on a comment"


def test_model_produced_filename_reaches_the_write_through_the_guard():
    """patch_guardian must not build its write target from a raw model-supplied name.

    THE STAKE: apply_patch() writes generated code to the file named by a proposal.
    Two string-level gates run before it — is_protected() and _is_patchable() — and
    both are blind to symlinks, because normalise() never stats anything. If the
    target is built with a bare Path(filename), a symlinked 'agents/core/*_patch.py'
    is written outside the repo with every existing check satisfied.

    This asserts the call site, not the guard's behaviour; the behavioural tests are
    above. Both are needed: a correct guard nobody calls protects nothing.
    """
    src = GUARDIAN.read_text(encoding="utf-8", errors="replace")

    # THE ROOT IS Path.cwd(), NOT the pinned REPO_ROOT — and that is not a detail.
    # patch_guardian's documented convention is CWD == BASE_DIR (execute_patches.py
    # chdirs before calling it, see _subprocess_env's docstring), and the guardian's
    # own integration tests sandbox it by chdir-ing into tmp_path. Pinning the root to
    # safety.safe_path.REPO_ROOT was tried first and was WRONG: it made the sandboxed
    # guardian resolve targets against the real repository and write a test patch into
    # the live tree. test_quarantine_integration caught it. Containment must be
    # relative to the root the caller is actually operating in.
    assert "safe_path(filename, Path.cwd())" in src, (
        "patch_guardian.py no longer resolves the target through safe_path() against "
        "its CWD — the write target is being built from a model-supplied name without "
        "containment, or is pinned to the wrong root. See safety/safe_path.py.")

    unguarded = _reaches_write_unguarded(src)
    assert not unguarded, (
        "These build a write target directly from the model-supplied filename:\n  "
        + "\n  ".join(unguarded)
        + "\n\nUse safe_repo_path(filename) and let UnsafePath refuse. "
          "is_protected()/_is_patchable() are string checks and cannot see a symlink.")

    # The guard must run BEFORE the write, not merely somewhere in the file.
    guard_at = src.find("safe_path(filename, Path.cwd())")
    write_at = src.find("file_path.write_text(")
    assert guard_at != -1 and write_at != -1, (
        "anchors moved: could not locate both the guard call and the write "
        f"(guard={guard_at}, write={write_at}) — re-anchor this test before trusting it")
    assert guard_at < write_at, (
        "safe_repo_path(filename) appears AFTER file_path.write_text() — the write "
        "is not covered by the guard.")


# ---------------------------------------------------------------------------
# REGRESSION: the traversal that was actually live in this repo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", [
    "memory/../../../evil.py",
    "core/../../../../Windows/system.ini",
    "agents/core/../../../../evil.py",
    "/etc/passwd",
    "C:/Windows/system.ini",
])
def test_self_modifier_refuses_targets_that_escape_the_repo(target):
    """agents/core/self_modifier._write_python had a LIVE path traversal.

    THE BUG (verified against this repo, 17 Aug 2026 — not theoretical):

        allowed = ["memory/", "agents/core/", "data_providers/", "alignment/", "core/"]
        if not any(target_file.startswith(a) for a in allowed): refuse
        target = BASE_DIR / target_file
        target.write_text(content)

    `startswith` knows nothing about '..'. 'memory/../../../evil.py' satisfies the
    allowlist and resolves to C:\\Users\\...\\Desktop\\evil.py — outside the repo
    entirely. `target_file` comes from a proposal composed by a model, and `content`
    is model-written Python. That is arbitrary file write, gated by a check that read
    like a gate and was not one.

    The fix is the ORDER, not the list: resolve and confine first, then apply the
    prefix policy to the resolved path. This test pins the order — a refactor that
    moves the allowlist back in front of the resolution reopens the hole while
    keeping every string in the file identical.

    Only refusal cases are exercised: each returns before any write, so this test
    creates nothing.
    """
    from agents.core import self_modifier

    result = self_modifier._write_python(target, "print('x')")

    assert result["success"] is False, f"_write_python ACCEPTED {target!r} — traversal is open"
    assert "Небезопасен път" in result["reason"], (
        f"{target!r} was refused, but by the POLICY layer rather than the path guard "
        f"(reason: {result['reason']!r}). The allowlist is not a containment check — "
        f"if it is what stopped this, the resolution step has been removed or reordered.")


def _passes_self_modifier_allowlist(repo_relative: str) -> bool:
    """Would self_modifier be allowed to write generated Python to this path?

    Imports WRITE_ALLOWLIST rather than restating it. A copy of the list here would
    keep agreeing with itself forever while the real one drifted — which is the exact
    failure mode that made the list a module constant in the first place.
    """
    from agents.core.self_modifier import WRITE_ALLOWLIST
    return any(repo_relative.startswith(a) for a in WRITE_ALLOWLIST)


def test_the_guard_is_not_writable_by_the_thing_it_constrains():
    """safe_path() must live somewhere the self-modifier cannot write.

    THE STAKE: agents/core/self_modifier._write_python writes model-generated Python
    to any path under WRITE_ALLOWLIST. safe_path() is the containment check that
    bounds where that write may land. If the module implementing safe_path() is
    itself under that allowlist, the system can propose a patch that widens its own
    guard — a lock whose key sits in the room it locks.

    This is why the module lives in safety/ and not core/: 'core/' is on the
    allowlist, 'safety/' is not (it is in protected_paths.PROTECTED_DIRS). The
    assertion reads the REAL list and the module's REAL location, so it fails if the
    file is moved back to core/, and it fails if 'safety/' is added to the allowlist.
    """
    import safety.safe_path as guard_module

    location = Path(guard_module.__file__).resolve().relative_to(REPO_ROOT).as_posix()

    assert not _passes_self_modifier_allowlist(location), (
        f"the module implementing safe_path() lives at {location!r}, which self_modifier "
        f"IS allowed to write to.\n"
        f"The self-modifier could therefore rewrite the guard that constrains it. "
        f"Move the module under a directory in protected_paths.PROTECTED_DIRS "
        f"(safety/ is where it belongs), or remove that prefix from "
        f"agents.core.self_modifier.WRITE_ALLOWLIST.")


@pytest.mark.xfail(
    strict=True,
    reason="core/notary.py IS reachable by self_modifier's allowlist ('core/' is on "
           "it). The notary is the provenance authority — it decides the trust level "
           "that gates irreversible actions — and the system can propose patches to "
           "it. Pre-existing, not introduced by the safe_path work, and not closed "
           "here because moving core/notary.py or narrowing the allowlist is a "
           "decision with consequences across the cycle. Stated as a specification "
           "rather than left unsaid. When this xfail starts PASSING, the provenance "
           "authority has been put out of its own reach.")
def test_the_provenance_authority_is_not_writable_by_the_thing_it_judges():
    """core/notary.py must not be reachable by self_modifier's allowlist.

    EXPECTED TO FAIL TODAY. The notary computes the five-state trust vector and
    may_act() reads its scalar to permit or refuse irreversible steps. A system that
    can rewrite its own notary can raise its own trust level — not by defeating the
    gate, but by editing what the gate reads.

    Same shape as the guard problem above, one layer up, and unfixed.
    """
    assert not _passes_self_modifier_allowlist("core/notary.py"), (
        "core/notary.py is reachable by agents.core.self_modifier.WRITE_ALLOWLIST")


def test_self_modifier_policy_layer_still_refuses_out_of_policy_targets():
    """The containment fix must not have swallowed the allowlist.

    A path can be perfectly safe and still not be somewhere the self-modifier may
    write. Both refusals must survive, and they must be distinguishable in the
    reason string — otherwise the next reader cannot tell a blocked attack from a
    misconfigured target.
    """
    from agents.core import self_modifier

    result = self_modifier._write_python("notes/harmless.py", "print('x')")

    assert result["success"] is False
    assert "Не е позволено" in result["reason"], (
        "an in-repo but out-of-policy target should be refused by the allowlist, "
        f"not by the path guard (reason: {result['reason']!r})")
