"""Integration tests for the quarantine-instead-of-delete pipeline, across
self_modifier, execute_patches, PatchGuardian, and review_quarantine.py.

Each test runs inside the `sandbox` tmp_path fixture (see conftest.py) via
monkeypatching the target modules' base-directory globals (or os.chdir for
patch_guardian.py, which resolves its paths relative to CWD). None of these
tests read or write the real repo's agents/core/, patches/, memory/, or
data/ trees.
"""
import asyncio
import json

import execute_patches
import scripts.review_quarantine as review_quarantine
from agents.core.self_modifier import _ensure_main_guard
from patch_guardian import PatchGuardian
from safety.quarantine import quarantine as q_fn

import agents.core.self_modifier as self_modifier


def test_self_modifier_ast_gate_quarantine(sandbox, monkeypatch):
    """self_modifier._write_python() denies via AST gate -> quarantines content (never written live)."""
    monkeypatch.setattr(self_modifier, "BASE_DIR", sandbox)

    target = "agents/core/qftest1_patch.py"
    live_path = sandbox / target

    # Avoids the literal substrings banned by the older FORBIDDEN_PATTERNS
    # string check ("subprocess.run"/".Popen"/".call") so this specifically
    # exercises the AST gate (rule 1: banned import), not the pattern-guard layer.
    bad_code = (
        "#!/usr/bin/env python3\n"
        "import subprocess\n"
        "subprocess.check_output(['echo', 'hi'])\n"
    )
    proposal = {"component": "qftest1", "problem": "test problem", "solution": "test solution"}

    result = self_modifier._write_python(target, bad_code, proposal)

    quarantine_dir = sandbox / "patches" / "quarantine"
    matches = list(quarantine_dir.glob("qftest1_patch.*.py"))
    sidecar_ok = False
    if matches:
        sidecar = matches[0].parent / f"{matches[0].name}.json"
        if sidecar.exists():
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            sidecar_ok = (
                meta.get("source_proposal", {}).get("component") == "qftest1"
                and "subprocess" in meta.get("deny_reason", "")
                and meta.get("verdict", {}).get("gate") == "ast_gate"
            )

    assert not result["success"]
    assert "AST gate" in result["reason"]
    assert not live_path.exists()
    assert len(matches) == 1
    assert sidecar_ok


def test_self_modifier_benign_patch_passes(sandbox, monkeypatch):
    """Benign patch still passes through self_modifier._write_python() normally."""
    monkeypatch.setattr(self_modifier, "BASE_DIR", sandbox)

    target = "agents/core/qftest2_patch.py"
    live_path = sandbox / target

    good_code = (
        "#!/usr/bin/env python3\n"
        "import os, pathlib\n"
        "BASE_DIR = pathlib.Path(os.environ['CORTEX_BASE'])\n"
        "(BASE_DIR / 'memory' / 'qftest2_marker.txt').write_text('ok', encoding='utf-8')\n"
    )
    result = self_modifier._write_python(target, good_code, {"component": "qftest2"})

    assert result["success"]
    assert live_path.exists()


def test_execute_patches_recheck_quarantines_bypass(sandbox, monkeypatch):
    """A patch that bypasses self_modifier (written directly) still gets caught
    by execute_patches.py's independent AST-gate re-check and quarantined."""
    monkeypatch.setattr(execute_patches, "BASE", sandbox)

    target_path = sandbox / "agents" / "core" / "qftest3_patch.py"
    bad_code = (
        "#!/usr/bin/env python3\n"
        "if __name__ == '__main__':\n"
        "    import os\n"
        "    os.system('echo bypassed')\n"
    )
    target_path.write_text(bad_code, encoding="utf-8")

    env = {"PYTHONPATH": str(sandbox), "CORTEX_BASE": str(sandbox)}
    ok_result, stdout, stderr = execute_patches._guardian_supervised_run(target_path, env)

    quarantine_dir = sandbox / "patches" / "quarantine"
    matches = list(quarantine_dir.glob("qftest3_patch.*.py"))
    sidecar_ok = False
    if matches:
        sidecar = matches[0].parent / f"{matches[0].name}.json"
        if sidecar.exists():
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            sidecar_ok = meta.get("verdict", {}).get("stage") == "execute_patches_recheck"

    assert not ok_result
    assert "AST_GATE" in stderr
    assert not target_path.exists()
    assert len(matches) == 1
    assert sidecar_ok


def test_guardian_rollback_quarantines_not_deletes(sandbox, monkeypatch):
    """PatchGuardian.apply_patch() failure (bad import at execution time) quarantines
    the dynamic patch file instead of deleting it."""
    monkeypatch.chdir(sandbox)

    target = "agents/core/qftest4_patch.py"
    target_path = sandbox / target

    raw = (
        "#!/usr/bin/env python3\n"
        "import os, pathlib\n"
        "import definitely_does_not_exist_zzz_qftest4\n"
    )
    wrapped = _ensure_main_guard(raw)
    target_path.write_text(wrapped, encoding="utf-8")

    guardian = PatchGuardian()
    result = asyncio.run(guardian.apply_patch(target, wrapped))

    quarantine_dir = sandbox / "patches" / "quarantine"
    matches = list(quarantine_dir.glob("qftest4_patch.*.py"))

    assert not result.success
    assert result.stage == "rolled_back"
    assert not target_path.exists()
    assert len(matches) == 1


def test_review_quarantine_list_and_show(sandbox, monkeypatch, capsys):
    """review_quarantine.py's list and --show logic work against a quarantined entry."""
    monkeypatch.setattr(review_quarantine, "BASE_DIR", sandbox)
    monkeypatch.setattr(review_quarantine, "QUARANTINE_DIR", sandbox / "patches" / "quarantine")
    monkeypatch.setattr(review_quarantine, "REJECTED_DIR", sandbox / "patches" / "quarantine" / "rejected")

    fake_target = sandbox / "agents" / "core" / "qftest5_patch.py"
    fake_target.write_text("#!/usr/bin/env python3\nimport subprocess\n", encoding="utf-8")
    dest = q_fn(
        base_dir=sandbox,
        filename="agents/core/qftest5_patch.py",
        reason="test deny: subprocess",
        verdict={"gate": "test"},
        source_path=fake_target,
    )

    review_quarantine.cmd_list()
    list_out = capsys.readouterr().out
    assert "qftest5" in list_out
    assert "quarantined patch" in list_out

    review_quarantine.cmd_show(dest.name)
    show_out = capsys.readouterr().out
    assert "SIDECAR:" in show_out
    assert "subprocess" in show_out


def test_review_quarantine_reject_never_deletes(sandbox, monkeypatch):
    """--reject moves a quarantined patch to quarantine/rejected/, doesn't delete it."""
    monkeypatch.setattr(review_quarantine, "BASE_DIR", sandbox)
    monkeypatch.setattr(review_quarantine, "QUARANTINE_DIR", sandbox / "patches" / "quarantine")
    monkeypatch.setattr(review_quarantine, "REJECTED_DIR", sandbox / "patches" / "quarantine" / "rejected")

    fake_target = sandbox / "agents" / "core" / "qftest6_patch.py"
    fake_target.write_text("#!/usr/bin/env python3\nimport subprocess\n", encoding="utf-8")
    dest = q_fn(
        base_dir=sandbox,
        filename="agents/core/qftest6_patch.py",
        reason="test",
        verdict={"gate": "test"},
        source_path=fake_target,
    )

    review_quarantine.cmd_reject(dest.name)

    rejected_dir = sandbox / "patches" / "quarantine" / "rejected"
    moved_py = rejected_dir / dest.name
    moved_sidecar = rejected_dir / f"{dest.name}.json"

    assert moved_py.exists()
    assert moved_sidecar.exists()
    assert not dest.exists()
