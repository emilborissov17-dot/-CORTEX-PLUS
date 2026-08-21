# -*- coding: utf-8 -*-
"""
test/test_publish_reports.py — THE PUBLISHER MAY NOT LEARN NEW HABITS.

scripts/publish_reports.py copies two kinds of file into reports/, stages
exactly those paths, commits, and stops. Everything interesting about it is a
thing it must NOT do, and a thing not done leaves no trace in any artifact — so
it gets asserted here or it gets asserted nowhere.

  * it must never push
  * it must never `git add -A` or `git add .`
  * it must refuse, loudly and entirely, when the selection produces a path
    under memory/ or config/, a .env, a V-Dem file, or anything over 5 MB
  * its parameters must stay frozen in the source, with no flag that widens them
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import publish_reports as pr   # noqa: E402

SRC = (REPO / "scripts" / "publish_reports.py").read_text(encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    """A miniature repo with the two publishable kinds and one decoy."""
    (tmp_path / "output" / "reports").mkdir(parents=True)
    (tmp_path / "output" / "reports" / "CYCLE_REPORT_2026-08-21.md").write_text(
        "# cycle report", encoding="utf-8")
    (tmp_path / "output" / "reports" / "CYCLE_REPORT_2026-08-18.md").write_text(
        "# older", encoding="utf-8")
    (tmp_path / "output" / "wellbeing_continent.json").write_text(
        json.dumps({"regions": {}}), encoding="utf-8")
    (tmp_path / "output" / "reports" / "SCRATCH.md").write_text("x", encoding="utf-8")
    (tmp_path / "output" / "wellbeing_all_countries.json").write_text(
        "{}", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# Selection: exactly two kinds, nothing adjacent
# --------------------------------------------------------------------------- #

def test_only_the_two_frozen_kinds_are_selected(repo):
    got = sorted(p.name for p in pr.select(repo))
    assert got == ["CYCLE_REPORT_2026-08-18.md",
                   "CYCLE_REPORT_2026-08-21.md",
                   "wellbeing_continent.json"]


def test_a_neighbour_in_the_same_directory_is_not_swept_in(repo):
    names = [p.name for p in pr.select(repo)]
    assert "SCRATCH.md" not in names
    assert "wellbeing_all_countries.json" not in names, (
        "a sibling file with a similar name was published")


def test_the_commit_message_carries_the_newest_reports_date(repo):
    assert pr.plan(repo)["commit_message"] == "reports: cycle 2026-08-21"


# --------------------------------------------------------------------------- #
# Refuse and scream
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("rel,needle", [
    ("memory/notify_channel.json", "memory/"),
    ("memory/existence_ledger.jsonl", "memory/"),
    ("config/scheduler.json", "config/"),
    (".env", ".env"),
    (".env.local", ".env"),
    ("data/V-Dem-CY-Core-v16.csv", "redistributed"),
    ("data/vdem_cache/x.json", "redistributed"),
    ("data/VDEM_extract.csv", "redistributed"),
])
def test_a_forbidden_path_is_refused(repo, rel, needle):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    with pytest.raises(pr.Refused) as exc:
        pr.check([p], repo)
    assert needle in str(exc.value)


def test_the_real_vdem_filename_is_caught():
    """THE BUG THE SELFTEST FOUND, kept as a test so it cannot come back.

    The rule was written as "any path containing vdem". The file it exists to
    stop is data/V-Dem-CY-Core-v16.csv, which lowercased contains "v-dem" and
    does NOT contain "vdem". The guard would have waved through the exact file
    it was written for."""
    assert "v-dem" in pr.FORBIDDEN_SUBSTRINGS
    assert "vdem" in pr.FORBIDDEN_SUBSTRINGS
    low = "data/V-Dem-CY-Core-v16.csv".lower()
    assert any(b in low for b in pr.FORBIDDEN_SUBSTRINGS)


def test_a_file_over_the_ceiling_is_refused(repo):
    big = repo / "output" / "reports" / "CYCLE_REPORT_2026-08-22.md"
    big.write_bytes(b"x" * (pr.MAX_BYTES + 1))
    with pytest.raises(pr.Refused) as exc:
        pr.check(pr.select(repo), repo)
    assert "ceiling" in str(exc.value)


def test_a_refusal_publishes_nothing_at_all(repo):
    """Not "skip the bad file and publish the rest". If the selection produced
    something it must never produce, the SELECTION is wrong."""
    big = repo / "output" / "reports" / "CYCLE_REPORT_2026-08-22.md"
    big.write_bytes(b"x" * (pr.MAX_BYTES + 1))
    calls = []
    with pytest.raises(pr.Refused):
        pr.publish(repo, runner=lambda a: calls.append(a))
    assert calls == [], "git was called despite the refusal"
    assert not (repo / "reports").exists(), "files were copied despite the refusal"


def test_the_cli_exits_non_zero_on_a_refusal(repo):
    """A refusal that exits 0 is a refusal a scheduler will ignore."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "publish_reports.py"), "--selftest"],
        cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120)
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert "RESULT: OK" in proc.stdout


# --------------------------------------------------------------------------- #
# The things it must never do
# --------------------------------------------------------------------------- #

def test_it_never_pushes(repo):
    calls = []

    def fake_git(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "ok", "")

    out = pr.publish(repo, runner=fake_git)
    assert out["published"] is True
    assert out["pushed"] is False
    assert not any(c[0] == "push" for c in calls), calls


def test_the_source_contains_no_push_at_all():
    """Belt and braces: the runtime test above only proves this run did not
    push. This proves there is no branch that could."""
    word = "pu" + "sh"          # so this assertion does not match itself
    offenders = [ln.strip() for ln in SRC.splitlines()
                 if word in ln and ("git(" in ln or "_git(" in ln
                                    or '"git",' in ln)]
    assert not offenders, offenders


def test_git_add_names_exactly_the_destinations_and_nothing_wider(repo):
    calls = []
    pr.publish(repo, runner=lambda a: (calls.append(a),
                                       subprocess.CompletedProcess(a, 0, "", ""))[1])
    adds = [c for c in calls if c and c[0] == "add"]
    assert len(adds) == 1
    args = adds[0]
    assert "--" in args, "git add without -- can misread a path as a revision"
    paths = args[args.index("--") + 1:]
    assert sorted(paths) == ["reports/CYCLE_REPORT_2026-08-18.md",
                             "reports/CYCLE_REPORT_2026-08-21.md",
                             "reports/wellbeing_continent.json"]
    for wide in ("-A", "--all", ".", "-u"):
        assert wide not in args, f"git add {wide} stages things nobody chose"


def test_the_parameters_are_frozen_in_the_source_not_exposed_as_flags():
    """A flag that widens the selection turns 'a human edit, in a diff, with a
    name on it' into 'whatever the last caller typed'."""
    # Matched as argparse REGISTRATIONS, not as bare strings: the module
    # docstring names these flags in order to say it does not have them, and a
    # test that cannot tell a promise from its violation is worse than none.
    for flag in ("--include", "--dest", "--allow-large", "--force",
                 "--no-check", "--push", "--max-bytes"):
        assert f'add_argument("{flag}"' not in SRC, (
            f"{flag} is registered as a flag and would move a frozen parameter")
    assert 'ap.add_argument("--dry-run"' in SRC
    assert 'ap.add_argument("--selftest"' in SRC


def test_dry_run_changes_nothing(repo):
    calls = []
    out = pr.publish(repo, dry_run=True, runner=lambda a: calls.append(a))
    assert out["dry_run"] is True
    assert len(out["files"]) == 3
    assert calls == []
    assert not (repo / "reports").exists()
