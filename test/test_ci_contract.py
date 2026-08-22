# -*- coding: utf-8 -*-
"""
test/test_ci_contract.py — THE CI FLAGS MUST KEEP MEANING SOMETHING.

This repository has already shipped a CI step that reported a green check it had
not earned: it ran `pytest tests/` — a directory git does not carry — so on a
fresh checkout pytest exited "file or directory not found", and a trailing
`|| true` swallowed that exit code along with every real failure behind it. The
job could not go red for any reason and was reporting success over four
failures.

So the pipeline gets tests of its own. Not "does CI pass" — that is the
pipeline's job — but "do the switches in the pipeline still connect to
anything":

  * `-m "not network"` must deselect a non-empty set, or it is decoration
  * every module that makes a live outbound request must carry the marker, or
    the flag is a lie about which tests reach the network
  * no `|| true` anywhere in the workflow
  * the matrix is the two OSes CONTRIBUTING.md claims it is
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"
TESTDIR = REPO / "test"


# --------------------------------------------------------------------------- #
# The network marker
# --------------------------------------------------------------------------- #

def _modules_with_live_requests() -> set:
    """Test modules that call requests.get/post at module or function level.

    Crude on purpose: a name-based scan cannot be fooled by a marker, which is
    the direction that matters. A module that mocks the call still gets flagged
    and must say so — see the allowlist below, which names each one and why.
    """
    hits = set()
    call = re.compile(r"\brequests\.(get|post|put|delete)\s*\(")
    for f in sorted(TESTDIR.glob("test_*.py")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not call.search(stripped):
                continue
            hits.add(f.name)
    return hits


# Modules that NAME requests.get/post but never reach a host. Each is listed
# with the reason, so that adding to this set is a decision rather than a
# convenience.
MOCKED_NOT_LIVE = {
    # Captures requests.post to prove alarm_human's send path is exercised
    # without a network; NOTIFY_CHANNEL is redirected into tmp_path so there are
    # no credentials to send with even if it tried.
    "test_supervisor.py",
    "test_phase_telegram.py",
    # Poisons requests.post to prove the backend policy refuses BEFORE the call.
    "test_backend_policy.py",
    # Script-style; run as a subprocess by test_script_suite.py.
    "test_needs_approvals.py",
}


def test_the_network_marker_is_registered():
    ini = (REPO / "pytest.ini").read_text(encoding="utf-8")
    assert "markers" in ini
    assert "network:" in ini, "the marker is used but not declared"


def test_the_network_marker_deselects_a_non_empty_set():
    """`-m "not network"` matching nothing is a flag that does nothing, and it
    would keep passing forever without anyone noticing."""
    marked = [f.name for f in sorted(TESTDIR.glob("test_*.py"))
              if "pytest.mark.network" in f.read_text(encoding="utf-8",
                                                      errors="ignore")]
    assert marked, ("no test carries @pytest.mark.network, so the CI flag "
                    "-m 'not network' deselects nothing and is decoration")


def test_every_module_that_calls_out_carries_the_marker():
    unmarked = []
    for name in _modules_with_live_requests() - MOCKED_NOT_LIVE:
        text = (TESTDIR / name).read_text(encoding="utf-8", errors="ignore")
        if "pytest.mark.network" not in text:
            unmarked.append(name)
    assert not unmarked, (
        f"these modules call requests.* but are not marked `network`, so CI "
        f"believes it excluded them and does not: {unmarked}. Mark them, or "
        f"add them to MOCKED_NOT_LIVE with the reason they never reach a host.")


# --------------------------------------------------------------------------- #
# The workflow itself
# --------------------------------------------------------------------------- #

def test_no_step_swallows_its_own_exit_code():
    """`|| true` is how this repo shipped a job that could not fail.
    continue-on-error keeps the JOB from blocking while the STEP still reports
    what it found; the two are not the same thing."""
    body = CI.read_text(encoding="utf-8")
    offenders = [line.strip() for line in body.splitlines()
                 if not line.strip().startswith("#")           # the comment
                 and ("|| true" in line or "|| exit 0" in line)  # explaining why
                 ]                                              # is not the bug
    assert not offenders, offenders


def test_the_matrix_is_the_two_operating_systems_we_claim():
    body = CI.read_text(encoding="utf-8")
    assert "windows-latest" in body
    assert "ubuntu-latest" in body
    assert 'python-version: "3.12"' in body


def test_the_test_job_uses_the_network_flag():
    body = CI.read_text(encoding="utf-8")
    assert '-m "not network"' in body, (
        "the pipeline does not use the marker this file exists to protect")


def test_ci_installs_from_requirements_rather_than_a_hand_list():
    """The old workflow ran `pip install pytest requests feedparser psutil` — a
    second, drifting dependency list beside requirements.txt. The whole point of
    the 21 Aug rewrite of that file is that there is now one."""
    body = CI.read_text(encoding="utf-8")
    assert "pip install -r requirements.txt" in body
    assert not re.search(r"pip install (?!-r|ruff|--)", body), (
        "a hand-written package list is back in the workflow")


def test_the_workflow_names_the_directory_that_exists():
    """`pytest tests/` — plural — is the exact step that reported a green check
    over a directory git does not carry."""
    body = CI.read_text(encoding="utf-8")
    assert "pytest tests/" not in body
    assert not (REPO / "tests").exists(), (
        "an empty tests/ directory is back; the suite is test/")


# --------------------------------------------------------------------------- #
# No drive letters outside the code that refuses them
# --------------------------------------------------------------------------- #

DRIVE = re.compile(r"""['"][A-Za-z]:[/\\]""")

# The files whose SUBJECT is drive-absolute paths. They must contain them.
DRIVE_LETTERS_ARE_THE_POINT = {
    "safety/safe_path.py",
    "safety/protected_paths.py",
    "test/test_safe_path.py",
    "test/test_protected_paths.py",
    "test/test_guardian_diagnosis.py",       # a captured Windows traceback
    "experiments/pulse/pulse_daemon.py",     # psutil.disk_usage(REPO.anchor or "C:\\")
    "test/test_ci_contract.py",              # this file
    # The drive letter is the ATTACK, not a path this code uses: the schema gate
    # must refuse "C:\Windows\system32" as a value for a relative-path field,
    # and testing that requires writing a Windows absolute path down.
    "test/test_openclaw_schema_gate.py",
}

SKIP_PARTS = {"venv", "venv312_metta", "__pycache__", ".git", ".claude",
              "OLD", "LEGACY", "_to_delete_gitlock", "quarantine"}


def test_no_hardcoded_drive_letters_in_code():
    """Finding 4 of the 21 Aug fork test: Path("Z:/nonexistent/dir/hb.json") is
    an unwritable absolute path on Windows and an ordinary RELATIVE path on
    Linux, where the test it guarded passed while exercising the opposite
    behaviour from the one its name claims."""
    offenders = []
    for f in REPO.rglob("*.py"):
        if any(p in SKIP_PARTS for p in f.parts):
            continue
        rel = str(f.relative_to(REPO)).replace("\\", "/")
        if rel in DRIVE_LETTERS_ARE_THE_POINT:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8",
                                             errors="ignore").splitlines(), 1):
            if DRIVE.search(line) and not line.strip().startswith("#"):
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "hardcoded drive letters make a path mean different things on different "
        "platforms:\n" + "\n".join(offenders))
