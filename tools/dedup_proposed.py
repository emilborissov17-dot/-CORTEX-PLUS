# -*- coding: utf-8 -*-
"""tools/dedup_proposed.py — repair memory/space/proposed.metta written by the old blind append
(9 Oct 2026, C-PROPOSED-1).

WHAT HAPPENED. core.symbols.propose appended a proposal every brain turn without looking at what
the file already held. Read on the machine 9 Oct 04:47Z: 397 (proposed …) lines for 13 distinct
statements and 13 distinct expressions — 384 byte-identical repeats, one line 39 times. The shape
proposed/3 reached 397, the arity-3 budget is 390, and core.space.derive refused brain turn 164
(ENGINE_BUDGET; guard state RED; exit 2, "hyperon did not run"). The brain stopped thinking
because of its own duplicates. core/symbols.py now writes a proposal only once; this repairs the
file that is already on disk.

WHAT IT DOES. Keeps each distinct (proposed …) line ONCE, in the order it first appeared, with the
"; proposed-by …" comment line that introduced it (the first one). Everything else is dropped. The
file is never edited in place: the original is copied to <file>.<utc>.bak beside it first, the new
text is written, and the result is read back and checked (every distinct line present, exactly one
occurrence each, no line invented). Nothing but memory/space/ is touched.

REFUSALS, loud, nothing written: a missing file; a file with no (proposed …) line; a read-back that
does not match what was written. Already deduplicated is not an error — it reports "nothing to do".

    venv\\Scripts\\python.exe tools\\dedup_proposed.py --dry-run
    venv\\Scripts\\python.exe tools\\dedup_proposed.py
    venv\\Scripts\\python.exe tools\\dedup_proposed.py --path <file>
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROPOSED = REPO / "memory" / "space" / "proposed.metta"
MARK = "(proposed "
COMMENT = "; proposed-by "


class RefusedRepair(RuntimeError):
    pass


def plan(text: str) -> dict:
    """-> {"keep": [(comment or None, line)], "lines": n, "distinct": n, "dropped": n}. The comment
    kept for a line is the one that introduced it the FIRST time."""
    lines = text.splitlines()
    props = [l for l in lines if l.startswith(MARK)]
    if not props:
        raise RefusedRepair(f"no {MARK}…) line in the file: nothing to repair, nothing written")
    keep: list = []
    seen: set = set()
    pending = None
    for l in lines:
        if l.startswith(COMMENT):
            pending = l
            continue
        if not l.startswith(MARK):
            pending = None
            continue
        if l not in seen:
            seen.add(l)
            keep.append((pending, l))
        pending = None
    return {"keep": keep, "lines": len(props), "distinct": len(seen), "dropped": len(props) - len(seen)}


def render(keep: list) -> str:
    out = []
    for comment, line in keep:
        if comment:
            out.append(comment)
        out.append(line)
    return "\n".join(out) + "\n"


def repair(path=None, dry_run: bool = False, now=None) -> dict:
    p = Path(path or PROPOSED)
    if not p.exists():
        raise RefusedRepair(f"{p} does not exist: nothing written")
    text = p.read_text(encoding="utf-8")
    pl = plan(text)
    res = {"path": str(p), "lines_before": pl["lines"], "distinct": pl["distinct"], "dropped": pl["dropped"],
           "backup": None, "written": False}
    if pl["dropped"] == 0:
        res["note"] = "nothing to do: every proposal is already unique"
        return res
    if dry_run:
        res["note"] = "dry run: nothing written"
        return res
    stamp = (now or (lambda: time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())))()
    bak = p.with_name(p.name + f".{stamp}.bak")
    bak.write_bytes(p.read_bytes())
    res["backup"] = str(bak)
    p.write_text(render(pl["keep"]), encoding="utf-8", newline="\n")
    back = [l for l in p.read_text(encoding="utf-8").splitlines() if l.startswith(MARK)]
    want = [l for _c, l in pl["keep"]]
    if back != want:
        p.write_bytes(bak.read_bytes())                 # put the original back, then refuse loudly
        raise RefusedRepair(f"read-back differs from what was written ({len(back)} vs {len(want)} "
                            f"proposals); the original was restored from {bak.name}")
    res["written"] = True
    res["lines_after"] = len(back)
    return res


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[argv.index("--path") + 1] if "--path" in argv else None
    try:
        r = repair(path, dry_run="--dry-run" in argv)
    except RefusedRepair as exc:
        print(f"REFUSED: {exc}")
        return 2
    print(f"proposals before {r['lines_before']}, distinct {r['distinct']}, dropped {r['dropped']}"
          + (f", after {r['lines_after']}, backup {Path(r['backup']).name}" if r["written"] else "")
          + (f" — {r['note']}" if r.get("note") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
