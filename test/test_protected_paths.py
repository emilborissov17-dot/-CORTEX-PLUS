"""Permanent test suite for the protected-path denylist.

THE PRINCIPLE UNDER TEST
------------------------
The machinery that grants autonomy must not be reachable by the autonomy it
grants. A system that can rewrite its own guardian has no guardian; a system
that can rewrite its own audit log has no audit log.

DEFENCE IN DEPTH
----------------
Enforcement is at two INDEPENDENT layers, and this suite asserts each one
separately — a bypass of one must not be a bypass of the system:

  layer 1  safety/ast_gate.check_code()          — the write target inside the
                                                   generated CODE
  layer 2  patch_guardian.apply_patch(filename)  — the TARGET FILE of the patch

Two holes that existed before this suite and are now regression-locked:
  * execute_patches.py was in PATCHABLE_FILES — the gate could rewrite the gate.
  * ALLOWED_DIR_PREFIXES permits "memory", and the heartbeat / lock / existence
    ledger all live under memory/ — so generated code could have forged its own
    existence history or faked a heartbeat to defeat the watchdog.
"""
import asyncio

import pytest

from safety.ast_gate import check_code
from safety.protected_paths import (
    PROTECTED_DIRS,
    PROTECTED_FILES,
    is_protected,
    normalise,
    protection_reason,
)


# ---------------------------------------------------------------------------
# The set itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "patch_guardian.py",
    "execute_patches.py",
    "supervisor.py",
    "scripts/review_quarantine.py",
    "core/source_status.py",
    "safety/ast_gate.py",
    "safety/quarantine.py",
    "safety/protected_paths.py",          # the denylist protects itself
    "config/openclaw_action_policy.json",
    "config/dead_sources.json",
    "config/scheduler.json",
    "memory/existence_ledger.jsonl",
    "memory/heartbeat.json",
    "memory/cycle.lock",
    "memory/scheduler_state.json",
])
def test_protected_paths_are_protected(path):
    assert is_protected(path), f"{path} must be human-only"


@pytest.mark.parametrize("path", [
    "agents/core/self_observer.py",
    "agents/core/self_modifier.py",
    "fast_cycle_runner.py",
    "memory/knowledge_base.json",
    "memory/trend_tracker.py",
    "output/cortex_scores_latest.json",
    "snapshots/master/master_snapshot_latest.json",
])
def test_normal_paths_are_not_protected(path):
    """The denylist must be narrow. If it swallows ordinary targets, the
    self-modifier is dead and people will be tempted to weaken it."""
    assert not is_protected(path), f"{path} must remain patchable"


def test_protection_reason_explains_itself():
    reason = protection_reason("patch_guardian.py")
    assert reason and "patch_guardian.py" in reason


# ---------------------------------------------------------------------------
# Normalisation / evasion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("evasion", [
    "safety\\ast_gate.py",                        # windows separators
    "./safety/ast_gate.py",                       # leading ./
    "safety//ast_gate.py",                        # doubled separator
    "agents/core/../../patch_guardian.py",        # traversal back to a protected file
    "memory/../patch_guardian.py",
    "PATCH_GUARDIAN.PY",                          # case (Windows is case-insensitive)
    "Safety/Ast_Gate.py",
    "config/../config/openclaw_action_policy.json",
])
def test_evasion_attempts_are_still_protected(evasion):
    assert is_protected(evasion), f"denylist bypassed via {evasion!r}"


@pytest.mark.parametrize("path", [
    "/etc/passwd",
    "C:\\Windows\\System32\\evil.py",
    "../../../outside.py",
    "..",
    "",
])
def test_unresolvable_paths_fail_closed(path):
    """A path we cannot reason about is treated as protected. We would rather
    refuse a legitimate patch than permit one we do not understand."""
    assert is_protected(path), f"{path!r} must fail closed"


def test_normalise_returns_none_for_out_of_repo():
    assert normalise("../../x.py") is None
    assert normalise("/abs/x.py") is None
    assert normalise("C:/x.py") is None


def test_protected_dirs_cover_everything_beneath():
    assert is_protected("safety/some/deeply/nested/new_file.py")
    assert is_protected("config/anything_at_all.json")


def test_directory_prefix_match_is_not_a_substring_match():
    """'config' must not protect 'configuration_helper.py'."""
    assert not is_protected("configuration_helper.py")
    assert not is_protected("safety_notes.md")


# ---------------------------------------------------------------------------
# LAYER 1 — the AST gate (write target inside generated code)
# ---------------------------------------------------------------------------

# NOTE on the code shapes used below.
# The gate only statically verifies two target forms: a bare string literal, and
# a left-associative `/` chain of literals with at most one leading dynamic
# segment (typically BASE_DIR). `Path("memory/x.json").write_text(...)` is NOT
# verifiable — the target is the return value of a Call — and was already denied
# before the denylist existed ("write_text() target not statically verified").
# So the tests below deliberately use the DIV-CHAIN and BARE-LITERAL forms: those
# are the ones the gate would otherwise ALLOW, and therefore the only ones that
# actually exercise the denylist.

def test_layer1_denies_write_to_protected_file_under_memory():
    """THE hole: 'memory' is in ALLOWED_DIR_PREFIXES, so a div-chain into
    memory/ would be permitted — and the existence ledger lives there. Without
    the denylist a patch could forge its own existence history."""
    src = (
        'from pathlib import Path\n'
        'BASE = Path(".")\n'
        '(BASE / "memory" / "existence_ledger.jsonl").write_text("fake history")\n'
    )
    allowed, reason = check_code(src)
    assert not allowed, "a patch just forged its own existence ledger"
    assert "write_text" in reason or "target" in reason


def test_layer1_denies_faking_the_heartbeat():
    """A forged heartbeat would defeat the watchdog meant to notice a hang."""
    src = (
        'from pathlib import Path\n'
        'BASE = Path(".")\n'
        '(BASE / "memory" / "heartbeat.json").write_text("{}")\n'
    )
    allowed, _ = check_code(src)
    assert not allowed


def test_layer1_denies_bare_literal_write_to_protected_path():
    src = 'open("memory/cycle.lock", "w")\n'
    allowed, _ = check_code(src)
    assert not allowed


def test_layer1_still_allows_ordinary_memory_writes():
    """The gate must not become so tight that legitimate patches die."""
    src = (
        'from pathlib import Path\n'
        'BASE = Path(".")\n'
        '(BASE / "memory" / "knowledge_base.json").write_text("{}")\n'
    )
    allowed, reason = check_code(src)
    assert allowed, f"legitimate write denied: {reason}"


def test_layer1_allows_bare_literal_ordinary_write():
    allowed, reason = check_code('open("output/report.json", "w")\n')
    assert allowed, f"legitimate write denied: {reason}"


# ---------------------------------------------------------------------------
# LAYER 2 — PatchGuardian (the target file of the patch)
# ---------------------------------------------------------------------------

def _apply(filename, code="x = 1\n"):
    from patch_guardian import PatchGuardian
    return asyncio.run(PatchGuardian().apply_patch(filename, code))


def test_layer2_denies_patch_targeting_patch_guardian(tmp_path, monkeypatch):
    """The case named explicitly in the requirements."""
    monkeypatch.chdir(tmp_path)
    result = _apply("patch_guardian.py")

    assert not result.success
    assert result.stage == "rejected_protected_path"
    assert "PROTECTED_PATH" in (result.error or "")


@pytest.mark.parametrize("target", [
    "patch_guardian.py",
    "execute_patches.py",
    "safety/ast_gate.py",
    "safety/protected_paths.py",
    "supervisor.py",
    "config/openclaw_action_policy.json",
    "memory/existence_ledger.jsonl",
    "scripts/review_quarantine.py",
])
def test_layer2_denies_every_protected_target(tmp_path, monkeypatch, target):
    monkeypatch.chdir(tmp_path)
    result = _apply(target)
    assert not result.success
    assert result.stage == "rejected_protected_path"


def test_layer2_denies_traversal_disguised_as_dynamic_patch(tmp_path, monkeypatch):
    """'agents/core/../../patch_guardian.py' used to satisfy the dynamic-patch
    pattern check (startswith agents/core/) while actually escaping it."""
    monkeypatch.chdir(tmp_path)
    result = _apply("agents/core/../../patch_guardian.py")
    assert not result.success


def test_layer2_no_longer_lets_the_gate_rewrite_the_gate():
    """execute_patches.py was in PATCHABLE_FILES. That is the whole hole."""
    from patch_guardian import PATCHABLE_FILES
    assert "execute_patches.py" not in PATCHABLE_FILES


def test_layer2_still_allows_a_legitimate_patchable_file():
    """Regression guard in the other direction: the denylist must not have
    killed normal self-modification."""
    from patch_guardian import _is_patchable
    assert _is_patchable("agents/core/self_observer.py")
    assert _is_patchable("agents/core/some_component_patch.py")


# ---------------------------------------------------------------------------
# The two layers are genuinely independent
# ---------------------------------------------------------------------------

def test_layers_are_independent(tmp_path, monkeypatch):
    """A patch whose CODE is entirely innocent, but whose TARGET is protected,
    must still be refused — layer 1 has nothing to complain about here, so only
    layer 2 can catch it. This is precisely why both exist."""
    innocent_code = "def helper():\n    return 42\n"

    allowed, _ = check_code(innocent_code)
    assert allowed, "the code itself is harmless — layer 1 correctly permits it"

    monkeypatch.chdir(tmp_path)
    result = _apply("patch_guardian.py", innocent_code)
    assert not result.success, "layer 2 must catch what layer 1 cannot see"
    assert result.stage == "rejected_protected_path"
