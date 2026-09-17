"""How much of what this system produces is about the world, and how much about itself.

On 2026-08-28 the self-observation on disk outweighed the perception of the world by
more than twenty to one: pulse_stream 6.6 MB, expression_stream 2.9 MB, divergence_log
1.6 MB, brain_journal and llm_provenance about 1 MB each, somatic_history 842 KB -
against 616 KB holding every axis, every point, five months of the world.

Introspection is not the defect. It is part of the honesty. But a system whose stated
purpose is claims about the WORLD, producing twenty times more bytes about ITSELF, has
let the instrument become the subject. This turns that into a number so it can be
argued with, and moved.

It never guesses. Every file is classified by config/attention_map.json, which a human
writes. Anything unlisted is reported as UNCLASSIFIED - never silently binned - because
a ratio computed from a guess would be exactly the kind of confident number this
project exists to refuse.

READ-ONLY. It writes nothing unless --write is given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
MAP = BASE / "config" / "attention_map.json"
OUT = BASE / "memory" / "attention_ratio_latest.json"
METHOD_VERSION = "attention_ratio/1"

# Three sides, not two. Splitting "world" was forced by the files themselves:
# memory/knowledge_base.json holds the model's prose about each axis - a claim ABOUT
# the world that never came FROM it. Folding that in with NOAA readings would hide the
# one distinction this whole project is built on.
MEASURED = "world_measured"   # a number that came from outside this machine, with a source
ASSERTED = "world_asserted"   # the model's opinion about the world, however well written
SELF = "self"                 # a claim about this machine
PLUMBING = "plumbing"         # caches, indexes, locks - neither side
SIDES = (MEASURED, ASSERTED, SELF, PLUMBING)


def load_map() -> dict:
    """{'world': [globs], 'self': [globs], 'plumbing': [globs]}. Absent means we cannot
    compute a ratio, and we say so rather than inventing one."""
    try:
        return json.loads(MAP.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _rows(p: pathlib.Path) -> int | None:
    """Lines in a .jsonl - the closest thing to 'how many claims'. None when not countable."""
    if p.suffix != ".jsonl":
        return None
    try:
        with p.open("rb") as fh:
            return sum(1 for _ in fh)
    except Exception:
        return None


def measure(root: pathlib.Path, amap: dict, scan_dirs=("memory", "snapshots", "news", "logs")):
    buckets = {k: [] for k in SIDES}
    buckets["unclassified"] = []
    buckets["conflict"] = []
    for d in scan_dirs:
        base = root / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            # ALL matching sides, not the first. First-match-wins is how one glob,
            # snapshots/**/*.json, quietly swallowed 13.58 MB of this machine's own
            # snapshots and counted them as measurement of the world - inverting the
            # headline from 0.69 to 2.39. A file two sides both claim is a defect in
            # the map, and it is now reported as one instead of resolved by luck.
            matched = [name for name in SIDES
                       if any(pathlib.PurePosixPath(rel).match(pat)
                              for pat in amap.get(name, []))]
            if len(matched) > 1:
                side = "conflict"
            elif matched:
                side = matched[0]
            else:
                side = "unclassified"
            try:
                size = p.stat().st_size
            except OSError:
                continue
            entry = {"path": rel, "bytes": size, "rows": _rows(p)}
            if side == "conflict":
                entry["claimed_by"] = matched
            buckets[side].append(entry)
    return buckets


def summarise(buckets: dict) -> dict:
    def tot(k):
        return sum(f["bytes"] for f in buckets[k]), sum(f["rows"] or 0 for f in buckets[k])
    mb, mr = tot(MEASURED)
    ab, ar = tot(ASSERTED)
    sb, sr = tot(SELF)
    pb, _ = tot(PLUMBING)
    ub, _ = tot("unclassified")
    cb, _ = tot("conflict")

    # Both ratios divide by MEASURED on purpose. Measurement is the only thing here
    # that came from outside; everything else is this machine talking. If the
    # denominator is zero the system is not monitoring anything, and that is the
    # finding, not a division error.
    self_per = round(sb / mb, 2) if mb else None
    asserted_per = round(ab / mb, 2) if mb else None

    if cb:
        # A contested file is counted on NEITHER side. Placing it by guess is how the
        # ratio lied the first time.
        verdict = (f"CONTESTED MAP - {len(buckets['conflict'])} files ({cb:,} B) are "
                   f"claimed by more than one side and are excluded from both. Fix the "
                   f"map before quoting either ratio.")
    elif not (mb or ab or sb):
        verdict = "NO MAP - config/attention_map.json is missing; no ratio can be computed"
    elif mb == 0:
        verdict = "NO MEASURED BYTES - nothing here came from outside the machine"
    else:
        verdict = (f"{self_per} bytes about itself and {asserted_per} bytes of opinion "
                   f"for every byte measured from the world")
    return {
        "method": METHOD_VERSION,
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "world_measured_bytes": mb, "world_measured_rows": mr,
        "world_asserted_bytes": ab, "world_asserted_rows": ar,
        "self_bytes": sb, "self_rows": sr,
        "plumbing_bytes": pb,
        "unclassified_bytes": ub,
        "unclassified_files": len(buckets["unclassified"]),
        "conflict_bytes": cb,
        "conflict_files": len(buckets["conflict"]),
        "self_per_measured_byte": self_per,
        "asserted_per_measured_byte": asserted_per,
        "verdict": verdict,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(BASE))
    ap.add_argument("--top", type=int, default=8, help="show the N largest on each side")
    ap.add_argument("--write", action="store_true", help="write memory/attention_ratio_latest.json")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    root = pathlib.Path(args.root).resolve()
    amap = load_map()
    if not amap:
        print(f"{METHOD_VERSION}: config/attention_map.json is absent.")
        print("No ratio is reported. A human classifies the files; this tool does not guess.")
        return 0

    buckets = measure(root, amap)
    s = summarise(buckets)

    print(f"{METHOD_VERSION}  {root}")
    print(f"  world MEASURED {s['world_measured_bytes']:>12,} B  {s['world_measured_rows']:>8,} rows")
    print(f"  world ASSERTED {s['world_asserted_bytes']:>12,} B  {s['world_asserted_rows']:>8,} rows")
    print(f"  self           {s['self_bytes']:>12,} B  {s['self_rows']:>8,} rows")
    print(f"  plumbing       {s['plumbing_bytes']:>12,} B")
    if s["conflict_files"]:
        print(f"  CONTESTED {s['conflict_bytes']:,} B in {s['conflict_files']} files claimed"
              " by two sides at once - excluded from both until the map is fixed")
        for f in sorted(buckets["conflict"], key=lambda f: -f["bytes"])[:args.top]:
            print(f"      {f['bytes']:>12,}  {f['path']}  claimed by {'+'.join(f['claimed_by'])}")
    if s["unclassified_files"]:
        print(f"  UNCLASSIFIED {s['unclassified_bytes']:,} B in {s['unclassified_files']} files"
              " - a human must place these before the ratio means anything")
        for f in sorted(buckets["unclassified"], key=lambda f: -f["bytes"])[:args.top]:
            print(f"      {f['bytes']:>12,}  {f['path']}")
    print(f"\n  {s['verdict']}")
    for side in (SELF, ASSERTED, MEASURED):
        print(f"\n  largest {side}:")
        for f in sorted(buckets[side], key=lambda f: -f["bytes"])[:args.top]:
            print(f"      {f['bytes']:>12,}  {f['path']}")

    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  wrote {OUT}")
    else:
        print("\n  (read only - pass --write to record memory/attention_ratio_latest.json)")
    return 0


def selftest() -> int:
    import tempfile
    checks, failed = [], 0

    def want(ok, why, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, why, detail))

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "memory").mkdir()
        (root / "memory" / "axis_history.json").write_text("x" * 100, encoding="utf-8")
        (root / "memory" / "knowledge_base.json").write_text("o" * 200, encoding="utf-8")
        # newline="" so Windows does not translate LF to CRLF and change the byte count
        with open(root / "memory" / "pulse_stream.jsonl", "w", encoding="utf-8", newline="") as fh:
            fh.write("a\nb\nc\n")
        (root / "memory" / "mystery.json").write_text("y" * 50, encoding="utf-8")
        amap = {MEASURED: ["memory/axis_history.json"],
                ASSERTED: ["memory/knowledge_base.json"],
                SELF: ["memory/pulse_stream.jsonl"]}

        b = measure(root, amap)
        s = summarise(b)
        want(s["world_measured_bytes"] == 100, "measured bytes counted",
             str(s["world_measured_bytes"]))
        want(s["world_asserted_bytes"] == 200,
             "opinion about the world is counted apart from measurement of it",
             str(s["world_asserted_bytes"]))
        want(s["self_rows"] == 3, "jsonl rows counted as claims", str(s["self_rows"]))
        want(s["unclassified_files"] == 1,
             "an unmapped file is UNCLASSIFIED, never silently binned",
             str(s["unclassified_bytes"]))
        want(s["self_per_measured_byte"] == 0.06, "self ratio computed",
             str(s["self_per_measured_byte"]))
        want(s["asserted_per_measured_byte"] == 2.0, "opinion ratio computed",
             str(s["asserted_per_measured_byte"]))

        # the defect that inverted the headline: two sides claiming one file
        both = summarise(measure(root, {MEASURED: ["memory/*.jsonl"],
                                        SELF: ["memory/pulse_stream.jsonl"]}))
        want(both["conflict_files"] == 1 and "CONTESTED" in both["verdict"],
             "a file two sides both claim is reported, never assigned by glob order",
             both["verdict"])

        # negative control: with no map at all, no number is invented
        s2 = summarise(measure(root, {}))
        want(s2["self_per_measured_byte"] is None and "NO MAP" in s2["verdict"],
             "with no map, no ratio is invented", s2["verdict"])

        # measurement of zero is named, never divided by
        s3 = summarise(measure(root, {SELF: ["memory/pulse_stream.jsonl"],
                                      ASSERTED: ["memory/knowledge_base.json"]}))
        want(s3["self_per_measured_byte"] is None and "NO MEASURED" in s3["verdict"],
             "zero measured bytes is named, not divided by", s3["verdict"])

        # opinion must NOT be able to stand in for measurement
        want(s3["world_asserted_bytes"] == 200 and s3["world_measured_bytes"] == 0,
             "a pile of opinion does not make the measured side non-zero",
             str(s3["verdict"]))

    for ok, why, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {why}")
        if not ok:
            print(f"         got {detail}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
