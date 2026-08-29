#!/usr/bin/env python3
"""tools/make_seed.py — THE NAMED COMMAND behind the one exception to the
never-stage rule.

WHY THIS EXISTS (ITEM 12(a), 29 August 2026)
--------------------------------------------
memory/axis_history.json was TRACKED. A file a running cycle rewrites every
night was restorable-over by a checkout, and on 2026-08-28 a `git reset --hard`
did exactly that to 86 tracked files. The measurement history was among them.

Untracking it stops the destruction and creates a second problem: a fresh clone
then builds from zero, with no history at all. Kimi, ruling: "An absolute rule
that forces fresh clones to build from zero is unreproducible by design. The
root cause is live accumulating data in version control; untracking stops the
destruction, and the seed preserves reproducibility without staging runtime
churn."

So the live file leaves version control and a SEED enters it: one dated,
provenanced, verifiable snapshot that a clone can start from and that no cycle
ever writes back to. The live file accumulates; the seed is regenerated
deliberately, by running this command, by a person who then reads the diff.

WHAT A SEED IS NOT. It is not a backup, it is not authoritative, and nothing in
the running system reads it. If the seed and the live file disagree, the live
file is right — it is the one the cycles have been writing to. The seed exists
so that a machine with no history can begin, not so that a machine with history
can be corrected.

THE BOUNDARY IS ENFORCED ELSEWHERE, ON PURPOSE. Kimi's objection to its own
ruling: "An enumerated exception is still a hole. A future developer could
commit a 50MB file to data/seed/, call it a seed, and the rule would not stop
them without additional size or format enforcement." test/test_seed_boundary.py
is that enforcement, and it runs against the DIRECTORY, not against this script —
a check that only ran when this command ran would be no check at all, because
the 50MB file arrives by a different route.

HOUSE RULE: dry-runs unless given --write.

    venv/Scripts/python.exe tools/make_seed.py            # shows what it would do
    venv/Scripts/python.exe tools/make_seed.py --write    # writes the pair
    venv/Scripts/python.exe tools/make_seed.py --verify   # checks what is there
    venv/Scripts/python.exe tools/make_seed.py --selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
SEED_DIR = BASE / "data" / "seed"
METHOD_VERSION = "make_seed/1"

# WHAT MAY BE SEEDED, and the list is short on purpose. A registry with one
# entry is not over-engineering: it is the difference between "the seed
# mechanism covers axis_history" and "somebody may seed anything they like".
# Adding a row here is a decision a reader can see in a diff.
SEEDABLE = {
    "axis_history": {
        "source": "memory/axis_history.json",
        "why": ("The measurement series the whole compass rests on. Untracked "
                "2026-08-29 (ITEM 12a) because a tracked file a cycle rewrites "
                "nightly can be destroyed by a checkout — and was, on "
                "2026-08-28."),
    },
}


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _git_commit() -> str:
    """The commit this seed was generated at. UNKNOWN is a legitimate answer and
    is recorded as such — a provenance record that guesses is worse than one that
    admits it could not tell."""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(BASE),
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "UNKNOWN"


def _describe(payload) -> dict:
    """Count what is in the file WITHOUT assuming its shape beyond dict-of-lists.

    Reported so a human can compare the seed against the live file by eye, which
    is the check that actually gets done. A count nobody can reproduce by hand is
    not provenance.
    """
    axes, points, latest = 0, 0, ""
    if isinstance(payload, dict):
        axes = len(payload)
        for series in payload.values():
            if isinstance(series, list):
                points += len(series)
                for pt in series:
                    if isinstance(pt, dict):
                        ts = str(pt.get("date") or pt.get("ts") or "")
                        if ts > latest:
                            latest = ts
    return {"axis_count": axes, "point_count": points,
            "latest_point_date": latest or None}


def build(name: str) -> tuple[bytes, dict]:
    """Returns (seed bytes, provenance dict). Reads only."""
    spec = SEEDABLE[name]
    src = BASE / spec["source"]
    raw = src.read_bytes()
    payload = json.loads(raw.decode("utf-8-sig"))

    # THE SEED IS THE SOURCE, RE-SERIALISED, NOT A TRANSFORMATION OF IT. Anything
    # cleverer — pruning, rounding, "just the recent points" — makes the seed a
    # second opinion about the data, and then two files disagree and nobody knows
    # which is wrong.
    seed_bytes = (json.dumps(payload, indent=2, ensure_ascii=False)
                  .encode("utf-8"))

    prov = {
        "method": METHOD_VERSION,
        "seed": f"{name}.seed.json",
        "source_path": spec["source"],
        "source_sha256": _sha256(raw),
        "source_bytes": len(raw),
        "seed_sha256": _sha256(seed_bytes),
        "seed_bytes": len(seed_bytes),
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "generated_at_commit": _git_commit(),
        "why": spec["why"],
        "authority": ("NOT AUTHORITATIVE. The live file at source_path is. If "
                      "the two disagree, the live file is right — it is the one "
                      "the cycles write. This exists so a clone with no history "
                      "can begin, not so a machine with history can be "
                      "corrected."),
        **_describe(payload),
    }
    return seed_bytes, prov


def verify(name: str) -> dict:
    """Check a seed pair on disk against itself. Reads only, returns findings.

    Deliberately does NOT compare against the live source: the live file moves
    every night, so a seed that had to match it would be red by morning. What
    must hold is that the provenance describes the seed BESIDE IT.
    """
    seed_p = SEED_DIR / f"{name}.seed.json"
    prov_p = SEED_DIR / f"{name}.seed.provenance"
    bad = []
    if not seed_p.exists():
        return {"ok": False, "problems": [f"{seed_p.name} is missing"]}
    if not prov_p.exists():
        return {"ok": False, "problems": [f"{prov_p.name} is missing"]}
    seed_bytes = seed_p.read_bytes()
    prov = json.loads(prov_p.read_text(encoding="utf-8-sig"))

    if prov.get("seed_sha256") != _sha256(seed_bytes):
        bad.append(f"provenance seed_sha256 {prov.get('seed_sha256')} does not "
                   f"match the file beside it ({_sha256(seed_bytes)})")
    if prov.get("seed_bytes") != len(seed_bytes):
        bad.append(f"provenance seed_bytes {prov.get('seed_bytes')} != actual "
                   f"{len(seed_bytes)}")
    got = _describe(json.loads(seed_bytes.decode("utf-8-sig")))
    for k, v in got.items():
        if prov.get(k) != v:
            bad.append(f"provenance {k} = {prov.get(k)!r} but the seed holds {v!r}")
    return {"ok": not bad, "problems": bad, "provenance": prov, "counts": got}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="actually write; without it this is a dry run")
    ap.add_argument("--verify", action="store_true",
                    help="check the seeds already on disk and exit")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--name", default=None, help="one entry from SEEDABLE")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    names = [a.name] if a.name else sorted(SEEDABLE)
    for n in names:
        if n not in SEEDABLE:
            print(f"  {n} is not in SEEDABLE. Known: {sorted(SEEDABLE)}")
            return 2

    if a.verify:
        rc = 0
        for n in names:
            v = verify(n)
            print(f"{METHOD_VERSION}  verify {n}: {'OK' if v['ok'] else 'FAILED'}")
            for p in v.get("problems", []):
                print(f"    ! {p}")
            if v["ok"]:
                c = v["counts"]
                print(f"    {c['axis_count']} axes, {c['point_count']} points, "
                      f"latest {c['latest_point_date']}")
            rc |= 0 if v["ok"] else 1
        return rc

    for n in names:
        seed_bytes, prov = build(n)
        print(f"{METHOD_VERSION}  {n}")
        print(f"  source        {prov['source_path']}  "
              f"{prov['source_bytes']} bytes")
        print(f"  source sha256 {prov['source_sha256']}")
        print(f"  contents      {prov['axis_count']} axes, "
              f"{prov['point_count']} points, latest {prov['latest_point_date']}")
        print(f"  seed          data/seed/{n}.seed.json  "
              f"{prov['seed_bytes']} bytes")
        print(f"  seed sha256   {prov['seed_sha256']}")
        print(f"  at commit     {prov['generated_at_commit']}")
        if not a.write:
            print("  DRY RUN — nothing written. Pass --write.")
            continue
        SEED_DIR.mkdir(parents=True, exist_ok=True)
        (SEED_DIR / f"{n}.seed.json").write_bytes(seed_bytes)
        (SEED_DIR / f"{n}.seed.provenance").write_text(
            json.dumps(prov, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote data/seed/{n}.seed.json and {n}.seed.provenance")
    return 0


def selftest() -> int:
    """Reports which integrations are LIVE and which are INERT in THIS repo."""
    import tempfile
    checks, failed = [], 0

    def want(ok, why, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, why, detail))

    global BASE, SEED_DIR
    real_base, real_dir = BASE, SEED_DIR
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "memory").mkdir()
        payload = {"A": [{"date": "2026-01-01"}, {"date": "2026-03-04"}],
                   "B": [{"date": "2026-02-02"}]}
        (root / "memory" / "axis_history.json").write_text(
            json.dumps(payload), encoding="utf-8")
        BASE, SEED_DIR = root, root / "data" / "seed"

        seed_bytes, prov = build("axis_history")
        want(prov["axis_count"] == 2 and prov["point_count"] == 3,
             "the provenance counts axes and points, not bytes only",
             f"{prov['axis_count']}/{prov['point_count']}")
        want(prov["latest_point_date"] == "2026-03-04",
             "and the latest date is the maximum across ALL axes, not the last "
             "one read", prov["latest_point_date"])
        want(prov["source_sha256"] == _sha256(
            (root / "memory" / "axis_history.json").read_bytes()),
            "the source digest is of the file as it is on disk")
        want(json.loads(seed_bytes.decode("utf-8")) == payload,
             "the seed round-trips the source unchanged — a seed that "
             "transforms is a second opinion")

        want(main(["--name", "axis_history"]) == 0
             and not (SEED_DIR / "axis_history.seed.json").exists(),
             "DRY BY DEFAULT: no --write, no file (house rule)")

        main(["--name", "axis_history", "--write"])
        want((SEED_DIR / "axis_history.seed.json").exists()
             and (SEED_DIR / "axis_history.seed.provenance").exists(),
             "--write produces the PAIR, never a seed on its own")
        want(verify("axis_history")["ok"],
             "and the pair it wrote verifies against itself")

        p = SEED_DIR / "axis_history.seed.json"
        p.write_bytes(p.read_bytes() + b"\n")
        v = verify("axis_history")
        want(not v["ok"] and any("sha256" in s for s in v["problems"]),
             "a seed edited after generation FAILS verify — the provenance is a "
             "seal, not a label", str(v["problems"])[:80])

    BASE, SEED_DIR = real_base, real_dir

    for ok, why, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {why}")
        if not ok and detail:
            print(f"         got {detail}")
    print("\n  integrations, in THIS repo:")
    for n, spec in sorted(SEEDABLE.items()):
        src = BASE / spec["source"]
        print(f"    source {spec['source']:<32} "
              f"{'LIVE (' + str(src.stat().st_size) + ' bytes)' if src.exists() else 'INERT — missing'}")
        s = SEED_DIR / f"{n}.seed.json"
        print(f"    seed   data/seed/{n}.seed.json{'':<9} "
              f"{'LIVE' if s.exists() else 'INERT — not generated yet'}")
    t = BASE / "test" / "test_seed_boundary.py"
    print(f"    boundary test {'LIVE' if t.exists() else 'INERT — THE EXCEPTION IS UNGUARDED'}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
