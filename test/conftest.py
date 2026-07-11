"""Shared fixtures for the AST-gate / quarantine-pipeline test suite.

Every test in this suite runs against an isolated tmp_path sandbox and
never reads or writes the real repo's memory/, patches/, or data/ trees.
"""
import os
import sys
from pathlib import Path

import pytest

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
