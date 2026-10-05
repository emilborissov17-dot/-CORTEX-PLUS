"""claude/reports/CLAUDE_ERRORS.jsonl - Claude's errors, public and append-only (Emil, 4 Oct 2026:
"I want your errors published publicly"). A row is never edited or removed: every committed version
of the file must be a prefix of the current one. Rows are added by Claude Code when a command stops on
EXPECTED != OBSERVED, by Claude when Emil corrects it, and by the verifier when it changes a command."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REL = "claude/reports/CLAUDE_ERRORS.jsonl"
KEYS = {"n", "date", "class", "what", "caught_by", "cost", "mechanism", "source"}
BY = {"emil", "claude_code", "verifier_subagent", "kimi", "nightly_reviewer", "twin"}


def rows(text):
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def test_every_row_is_complete_and_numbered_in_order():
    rs = rows((REPO / REL).read_text(encoding="utf-8"))
    assert rs, "the ledger is empty"
    for i, r in enumerate(rs, 1):
        assert set(r) == KEYS, (i, sorted(set(r) ^ KEYS))
        assert r["n"] == i, (i, r["n"])
        assert r["caught_by"] in BY, (i, r["caught_by"])
        assert all(str(r[k]).strip() for k in KEYS), i


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_no_committed_row_was_ever_changed_or_removed():
    log = subprocess.run(["git", "log", "--format=%H", "--", REL], cwd=REPO, capture_output=True, text=True)
    current = (REPO / REL).read_text(encoding="utf-8").splitlines()
    for sha in log.stdout.split():
        old = subprocess.run(["git", "show", f"{sha}:{REL}"], cwd=REPO, capture_output=True, text=True)
        if old.returncode != 0:
            continue
        lines = old.stdout.splitlines()
        assert current[:len(lines)] == lines, f"a row committed in {sha[:10]} was changed or removed"
