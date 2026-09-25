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
    # Listed because its only requests.post targets 127.0.0.1:11434 and must be
    # refused by the conftest net (_no_ollama_writes) before any socket opens -
    # test_a_requests_post_to_ollama_raises_in_tests fails if that stops.
    "test_no_ollama_writes_from_tests.py",
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

# The negative lookahead excludes a URL: a one-letter scheme like "u://x"
# matched a drive-letter pattern and was reported as one. Measured 19 Sep
# 2026 on test_statements_segmentation.py:135, url="u://x". A real Windows
# path is "C:/" or "C:" + backslash, never "C://".
DRIVE = re.compile("['\"]" "[A-Za-z]:[/" '\\\\' "]" "(?![/" '\\\\' "])")

# The files whose SUBJECT is drive-absolute paths. They must contain them.
DRIVE_LETTERS_ARE_THE_POINT = {
    "safety/safe_path.py",
    "safety/protected_paths.py",
    "test/test_safe_path.py",
    "test/test_protected_paths.py",
    "test/test_guardian_diagnosis.py",       # a captured Windows traceback
    # A Windows-only SENSOR: the Windows Firewall log is at exactly this path
    # and nowhere else, and read_firewall_drops() takes an override for tests.
    "core/receptors.py",
    # Launches Chrome by its Windows install paths; both candidates are tried.
    "test/cdp.py",
    "experiments/pulse/pulse_daemon.py",     # psutil.disk_usage(REPO.anchor or "C:\\")
    "test/test_ci_contract.py",              # this file
    # The drive letter is the ATTACK, not a path this code uses: the schema gate
    # must refuse "C:\Windows\system32" as a value for a relative-path field,
    # and testing that requires writing a Windows absolute path down.
    "test/test_openclaw_schema_gate.py",
}

# THE LINE-LEVEL EXEMPTION, added 20 Sep 2026 — and the reason it is per LINE.
#
# DRIVE_LETTERS_ARE_THE_POINT above exempts a whole FILE, which is right for
# safety/safe_path.py, where drive letters are the subject of every line. It is
# wrong for a test file that writes one string of test DATA and is otherwise
# ordinary code: exempting the file hands a permanent licence to the next
# hardcoded path anybody adds to it, and that is the rule being weakened to
# accommodate five lines rather than five lines being accounted for.
#
# So a line may carry its own exemption, and must state WHY on the line itself:
#
#     assert M._version_flag("C:/x/ffmpeg.exe") == "-version"  # drive-letter-is-data: ...
#
# The reason is not decoration. A bare marker is refused (test_a_marker_without
# _a_reason_is_not_an_exemption), so the cheapest way to silence this test is
# still to write down why the string is data — which is exactly the moment a
# person notices it is not.
#
# WHAT THIS CANNOT CHECK, stated plainly: nothing here can tell a string that is
# data from a path that is opened. The marker records a HUMAN's claim, on the
# line, in the diff. What it does buy is that the claim is visible, attached to
# the one line it excuses, and impossible to make silently.
EXEMPT = re.compile(r"#\s*drive-letter-is-data:\s*(\S.*)$")


def _offending(line: str) -> bool:
    """One line's verdict, factored out so it can be tested directly rather than
    only through a scan of the whole repo."""
    if not DRIVE.search(line) or line.strip().startswith("#"):
        return False
    return not EXEMPT.search(line)


# Aligned with pytest.ini norecursedirs on 19 Sep 2026. venv_train, Broker-bot
# and _ARCHIVE were missing, so this scanned a vendored virtualenv and reported
# numpy's own build paths as OUR hardcoded drive letters.
SKIP_PARTS = {"venv", "venv_train", "venv312_metta", "__pycache__", ".git",
              ".claude", "OLD", "LEGACY", "_to_delete_gitlock", "quarantine",
              "Broker-bot", "_ARCHIVE", "node_modules"}


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
            if _offending(line):
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "hardcoded drive letters make a path mean different things on different "
        "platforms:\n" + "\n".join(offenders)
        + "\n\nIf the path is EXECUTED, make it platform-neutral — Path(base.anchor) "
          "is the filesystem root on both. If the string is DATA the test never "
          "opens, say so on the line: `# drive-letter-is-data: <why>`. Do not add "
          "the file to DRIVE_LETTERS_ARE_THE_POINT unless drive letters are what "
          "the whole file is about.")


def test_a_line_without_the_marker_is_still_an_offender():
    """The rule itself, on one line, so the scan above cannot be the only thing
    holding it. If the marker ever matched too eagerly this goes red."""
    assert _offending('    p = Path("C:/Windows/System32/x.tmp")')
    assert _offending("    p = Path('Z:/nonexistent/dir/hb.json')")


def test_a_marked_line_is_exempt():
    assert not _offending(
        '    x = "C:/x/deno.exe"  # drive-letter-is-data: a stub return value')


def test_a_marker_without_a_reason_is_not_an_exemption():
    """THE FORBIDDEN SHORTCUT. A bare marker would make silencing this test
    cheaper than explaining the line, and an exemption nobody had to justify is
    the rule weakened one line at a time. Every one of these still fails."""
    for bare in ('    x = "C:/a"  # drive-letter-is-data',
                 '    x = "C:/a"  # drive-letter-is-data:',
                 '    x = "C:/a"  # drive-letter-is-data:    ',
                 '    x = "C:/a"  # drive-letter'):
        assert _offending(bare), bare


def test_every_marker_in_the_repo_sits_on_a_real_drive_letter():
    """A marker on a line with no drive letter is a licence planted in advance:
    it silences nothing today and quietly excuses whatever is added to that line
    tomorrow. It is also how the census of exemptions stops being true."""
    stray = []
    for f in REPO.rglob("*.py"):
        if any(p in SKIP_PARTS for p in f.parts):
            continue
        rel = str(f.relative_to(REPO)).replace("\\", "/")
        if rel == "test/test_ci_contract.py":          # the examples above
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8",
                                             errors="ignore").splitlines(), 1):
            if EXEMPT.search(line) and not DRIVE.search(line):
                stray.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not stray, (
        "these lines carry a drive-letter exemption and have no drive letter on "
        "them. Remove the marker:\n" + "\n".join(stray))
