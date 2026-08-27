"""A cockpit whose WRITES land in a sandbox, for the render sweep to drive.

WHY THIS FILE EXISTS, and it is not a nicety. The first run of the sweep clicked
ask, the mic toggle and the unread counter against the operator's own repo, and
left four "sweep probe" rows in memory/human_input_queue.db — a table with a
DELETE trigger, so removing them meant dropping and rebuilding the trigger. A
test has no business leaving a question in a real queue or the microphone
switched on.

Backing the files up and restoring them afterwards is not enough: the run was
killed by a timeout before its teardown, and the damage survived. So the fix is
structural. Every WRITE surface is redirected into a temporary directory before
Flask starts; the READS still come from the real repo, because a sweep against
fabricated data would prove nothing about the panels.

    venv/Scripts/python.exe test/sweep_server.py <port> <sandbox-dir>
"""
from __future__ import annotations

import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cockpit import server as srv          # noqa: E402
from cockpit import expression as ex       # noqa: E402

# name -> (module holding it, real path). Everything the cockpit can write.
WRITE_SURFACES = (
    ("PENDING_PATH", srv),
    ("QUEUE_DB", srv),
    ("HISTORY_PATH", srv),
    ("FORKS_CACHE", srv),
    ("TERMINAL_LOG", srv),
    ("CONFIG_EXPRESSION", srv),
)


# Deliberately NOT seeded: the mark-as-seen ledger. On the operator's machine
# every expression line is already read, so `unread` is 0 and the two controls
# that only exist when something is unread — the unread list and its dismiss
# button — could never be exercised. Starting the sandbox with an empty ledger
# makes all 24 expression lines unread, so the sweep can press them.
#
# This is the only place the sandbox deliberately DIFFERS from the real repo,
# and it differs by omission rather than by fabricating data: every line the
# page shows is a real line the system wrote.
NOT_SEEDED = ("PENDING_PATH",)


def redirect(sandbox: pathlib.Path) -> dict:
    """Point every write surface into `sandbox`, seeded from the real file."""
    sandbox.mkdir(parents=True, exist_ok=True)
    moved = {}
    for name, mod in WRITE_SURFACES:
        real = pathlib.Path(getattr(mod, name))
        fake = sandbox / real.name
        if real.exists() and not fake.exists() and name not in NOT_SEEDED:
            # seeded, so the page shows what the operator would see; written to
            # here, so nothing it does reaches the real file
            shutil.copy2(real, fake)
        setattr(mod, name, fake)
        moved[name] = str(fake)
    return moved


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    port = int(argv[0])
    sandbox = pathlib.Path(argv[1])
    moved = redirect(sandbox)

    # A last, loud check: nothing the server may write may still point into the
    # repo. If this ever fires, the sweep must not start.
    for name, path in moved.items():
        assert sandbox in pathlib.Path(path).parents, (
            f"{name} still points at {path} — the sweep would write to the "
            f"operator's repo")
    assert pathlib.Path(ex.__file__).exists()

    print("sweep server: writes redirected to", sandbox, flush=True)
    srv.app.run(host="127.0.0.1", port=port, threaded=True,
                debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
