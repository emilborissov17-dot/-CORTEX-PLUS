#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/free_stream.py — WHAT THE MODEL SAID, BEFORE ANYONE JUDGED IT.

Every other path a model's words take through this system is validated. The
language gate reads them, the purity census counts them, the exemplar flag
decides whether they were fit to show. That is right for anything the system
acts on. It also means there is nowhere in this repo you can read what the
model actually said — only what survived being checked.

This is that place. One file per COMPLETED reaction call, the raw answer, no
gate, no verdict, no score. It is deliberately not evidence: nothing reads it
but the cockpit, and there is an AST test that keeps it that way.

WHY IT IS EXEMPT FROM THE PURITY CENSUS, BY NAME. The census measures whether
model output that the system RELIES ON is clean. Counting unvalidated text
against that floor would mean one of two bad things: either the free stream gets
quietly gated after all — which is the one thing it must not be — or the purity
ratio starts describing text nobody validated and the floor stops meaning what
it says. So core/language_gate.py names the kind and skips it, and says why
there rather than here.

    venv/Scripts/python.exe core/free_stream.py            # DRY RUN
    venv/Scripts/python.exe core/free_stream.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

FREE_DIR = BASE / "expression" / "free"
KIND = "free_expression"
MAX_FILES = 500
_STAMP = re.compile(r"^\d{8}T\d{6}\d{6}")


def _now():
    return datetime.now(timezone.utc)


def write(text: str, meta: Optional[dict] = None, directory=None,
          now=None, write: bool = False) -> dict:
    """One file, the raw answer, unvalidated. Never raises.

    DRY RUN BY DEFAULT, like everything else that can leave a trace: three
    live-state breaches happened on 27 Aug and two of them were a module doing
    its real job when someone only meant to look at it.
    """
    now = now or _now()
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    d = pathlib.Path(directory or FREE_DIR)
    rec = {"kind": KIND, "ts": now.isoformat(), "stamp": stamp,
           "chars": len(text or ""), "written": False,
           "path": str(d / (stamp + ".txt")),
           # SAID IN THE RECORD ITSELF, because a reader who finds one of these
           # files needs to know nothing checked it before they do.
           "validated": False,
           "note": "unvalidated model expression — no language gate, no "
                   "purity verdict, no exemplar flag"}
    if not (text or "").strip():
        rec["why"] = "the model said nothing; an empty file is not expression"
        return rec
    if not write:
        rec["why"] = "dry run: nothing was written"
        return rec
    try:
        d.mkdir(parents=True, exist_ok=True)
        header = "\n".join(
            ["# {}".format(now.isoformat()),
             "# unvalidated model expression — nothing judged this",
             "# " + json.dumps(meta or {}, ensure_ascii=False), ""])
        pathlib.Path(rec["path"]).write_text(header + text.rstrip() + "\n",
                                             encoding="utf-8")
        rec["written"] = True
        rec["pruned"] = prune(directory=d)
    except Exception as exc:                                # noqa: BLE001
        rec["why"] = "{}: {}".format(type(exc).__name__, exc)
    return rec


def read(n: int = 20, directory=None) -> list:
    """Newest first. Never raises.

    Newest first because this is a stream, not an archive: the question a
    reader has when they open it is what it just said, not what it said in
    July.
    """
    try:
        files = sorted((p for p in pathlib.Path(directory or FREE_DIR).glob("*.txt")
                        if _STAMP.match(p.name)),
                       key=lambda p: p.name, reverse=True)[:max(0, int(n))]
    except Exception:
        return []
    out = []
    for p in files:
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except Exception:                                   # noqa: BLE001
            continue
        lines = body.splitlines()
        meta = {}
        text = []
        for line in lines:
            if line.startswith("# {"):
                try:
                    meta = json.loads(line[2:])
                except Exception:                           # noqa: BLE001
                    pass
            elif not line.startswith("#"):
                text.append(line)
        out.append({"name": p.name, "ts": _ts_of(p.name), "meta": meta,
                    "text": "\n".join(text).strip(), "validated": False})
    return out


def _ts_of(name: str) -> str:
    try:
        return datetime.strptime(name[:21], "%Y%m%dT%H%M%S%f").replace(
            tzinfo=timezone.utc).isoformat()
    except Exception:                                       # noqa: BLE001
        return ""


def prune(keep: int = MAX_FILES, directory=None) -> int:
    """Oldest out beyond `keep`. Returns how many went.

    A directory that only grows is a directory somebody eventually deletes in
    one go, and then the stream has no history at all.
    """
    try:
        files = sorted((p for p in pathlib.Path(directory or FREE_DIR).glob("*.txt")
                        if _STAMP.match(p.name)), key=lambda p: p.name)
    except Exception:                                       # noqa: BLE001
        return 0
    gone = 0
    for p in files[:-keep] if len(files) > keep else []:
        try:
            p.unlink()
            gone += 1
        except Exception:                                   # noqa: BLE001
            pass
    return gone


def _selftest() -> int:
    import tempfile
    print("core/free_stream.py --selftest")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    d = pathlib.Path(tempfile.mkdtemp())
    r = write("hello", directory=d)
    check("dry run writes nothing", r["written"] is False and not list(d.glob("*")))

    t0 = datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 27, 11, 0, 0, tzinfo=timezone.utc)
    write("older", {"n": 1}, directory=d, now=t0, write=True)
    write("newer", {"n": 2}, directory=d, now=t1, write=True)
    rows = read(directory=d)
    check("two files, newest first", [x["text"] for x in rows] == ["newer", "older"])
    check("the metadata survives the round trip", rows[0]["meta"] == {"n": 2})
    check("and every row says it was never validated",
          all(x["validated"] is False for x in rows))

    check("an empty answer is not a file",
          write("   ", directory=d, write=True)["written"] is False)

    for i in range(6):
        write("x{}".format(i), directory=d,
              now=datetime(2026, 8, 28, 0, 0, i, tzinfo=timezone.utc), write=True)
    prune(keep=3, directory=d)
    check("pruning keeps the newest 3", len(list(d.glob("*.txt"))) == 3)
    check("and keeps the NEWEST ones",
          read(directory=d)[0]["text"] == "x5")

    # INTEGRATIONS, LIVE OR INERT IN THIS REPO
    try:
        from core.language_gate import PURITY_EXEMPT_KINDS
        check("language_gate exempts {!r} by name LIVE".format(KIND),
              KIND in PURITY_EXEMPT_KINDS)
    except Exception as exc:                                # noqa: BLE001
        check("language_gate exemption INERT ({})".format(exc), False)
    src = (BASE / "core" / "reaction.py").read_text(encoding="utf-8-sig")
    check("core/reaction.py writes the free stream {}"
          .format("LIVE" if "free_stream" in src else "INERT"),
          "free_stream" in src)
    srv = (BASE / "cockpit" / "server.py").read_text(encoding="utf-8-sig")
    check("the cockpit serves it {}".format("LIVE" if "free_stream" in srv
                                            else "INERT"),
          "free_stream" in srv)

    print("  RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    rows = read(5)
    print("DRY RUN — nothing was written.\n")
    print(json.dumps({"dir": str(FREE_DIR), "exists": FREE_DIR.exists(),
                      "files": len(list(FREE_DIR.glob("*.txt")))
                      if FREE_DIR.exists() else 0,
                      "newest": [r["name"] for r in rows]}, indent=2))
