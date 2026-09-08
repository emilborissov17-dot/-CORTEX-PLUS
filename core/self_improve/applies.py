#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/self_improve/applies.py — GIT DECIDES WHETHER THE PATCH DESCRIBES REALITY.

THE PRINCIPLE
--------------
NO MODEL OUTPUT REACHES THE NEXT STAGE UNVERIFIED. Every field the model emits
has a mechanical net behind it. This is the net for the biggest field of all —
the diff body — and it is the only one that can catch confabulated CONTENT
rather than a confabulated path.

WHY GIT AND NOT A REGEX
------------------------
The checks before this one ask shape questions: is there a hunk header, do the
paths exist, are they inside the allowlist. A patch can pass every one of them
and still describe a file that does not look like that. Measured on 2026-09-08,
after the path grounding landed: the model correctly targeted
agents/core/self_observer.py and then proposed removing

    def self_observe(prompt):        <- not in the file
    class SelfObserver:              <- not in the file
    llm_call(...)                    <- not in the file

Real path, invented contents. Only something that reads the actual bytes can
tell, and `git apply --check` is exactly that: a deterministic, non-model judge
of "does this describe reality". It is the same tool that would have to succeed
before the patch could ever be applied, so passing it is necessary — not merely
encouraging.

    bare    @@                -> No valid patches in input   (cannot parse)
    ranged  @@ -1,1 +1,1 @@   -> patch does not apply         (parses, wrong content)

IT IS A SANDBOX BECAUSE --check NEVER WRITES
---------------------------------------------
Verified on this repo: `git status --porcelain` is byte-identical before and
after. --check parses the patch and tests it against the tree without touching a
single file, so no worktree needs to be created and torn down for every attempt —
which matters because the retry loop runs this up to four times per patch.

The reference is the WORKING TREE, deliberately, not HEAD. The patch has to
describe the file as it actually is right now; a clean worktree checked out from
HEAD would miss every uncommitted change and could fail a patch that is correct.

    venv\\Scripts\\python.exe core/self_improve/applies.py --selftest
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The named refusal, so a reader of the record can tell THIS failure from a bad
# path or an out-of-scope hunk without parsing prose.
CODE = "REFUSED_PATCH_DOES_NOT_APPLY"


def check_applies(diff: str, repo: Path | None = None,
                  timeout: float = 30.0) -> tuple:
    """(ok, error). git's own verdict on whether the diff fits the real files.

    NEVER RAISES. A check that cannot run returns ok=False with the reason,
    because "git was unavailable" and "the patch is good" must never collapse
    into the same answer — that is the failure this whole module exists to stop,
    one level up.
    """
    if not (diff or "").strip():
        return False, "empty diff"

    root = Path(repo or REPO)
    try:
        # BYTES, NOT TEXT, AND THIS IS A WINDOWS BUG I WROTE AND THEN HIT.
        # subprocess with text=True writes stdin in universal-newline mode, so
        # on Windows every "\n" in the diff became "\r\n" before git saw it.
        # git then reported, for a patch that was perfectly correct:
        #     error: while searching for:
        #     #!/usr/bin/env python3?
        # — the "?" being the CR it had been handed. A content net that mangles
        # the content before checking it would have refused every valid patch
        # this pipeline ever produced, and blamed the model for it.
        proc = subprocess.run(
            ["git", "apply", "--check", "--verbose", "-"],
            input=diff.encode("utf-8"), cwd=str(root),
            capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return False, "git is not on PATH — the patch could not be verified"
    except subprocess.TimeoutExpired:
        return False, f"git apply --check timed out after {timeout}s"
    except Exception as exc:                                     # noqa: BLE001
        return False, f"git apply --check failed to run: {type(exc).__name__}: {exc}"

    if proc.returncode == 0:
        return True, ""

    def _dec(b) -> str:
        return (b or b"").decode("utf-8", errors="replace").strip()

    err = _dec(proc.stderr) or _dec(proc.stdout)
    return False, err or f"git apply --check exited {proc.returncode}"


def refusal(error: str) -> str:
    """The named, quotable refusal — carrying git's own words.

    The error text goes back to the model verbatim in the retry loop, so it must
    not be summarised here: "patch does not apply" tells a model nothing,
    "while searching for: <the lines it expected>" tells it exactly what the file
    really contains.
    """
    return (f"{CODE}: git will not apply this patch to the real files.\n"
            f"{error}\n"
            f"The paths are real and inside the allowlist, so this is a CONTENT "
            f"failure: the diff describes a file that does not look like that. "
            f"A patch that cannot be applied cannot be judged, only believed.")


def _selftest() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    print("core/self_improve/applies.py --selftest")

    ok, err = check_applies("")
    print(f"  empty diff            : {'refused' if not ok else 'ACCEPTED — wrong'}")

    ghost = ("--- a/agents/core/self_observer.py\n"
             "+++ b/agents/core/self_observer.py\n"
             "@@ -1,1 +1,1 @@\n-def self_observe(prompt):\n+def self_observe(p):\n")
    ok2, err2 = check_applies(ghost)
    print(f"  a confabulated diff   : "
          f"{'refused' if not ok2 else 'ACCEPTED — the net is open'}")
    if not ok2:
        print(f"      git said: {err2.splitlines()[0][:80]}")

    import hashlib
    before = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO),
                            capture_output=True, text=True).stdout
    check_applies(ghost)
    after = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO),
                           capture_output=True, text=True).stdout
    clean = hashlib.sha256(before.encode()).digest() == \
        hashlib.sha256(after.encode()).digest()
    print(f"  --check wrote nothing : {'LIVE' if clean else 'BROKEN — it wrote'}")

    good = all((not ok, not ok2, clean))
    print(f"  RESULT: {'OK' if good else 'BROKEN'}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(_selftest())
