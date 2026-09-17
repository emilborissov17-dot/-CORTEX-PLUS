"""The second observer: re-read every claim's source and see whether it still says that.

Diagnosis this exists for, 2026-08-29. The system is built out of things that REPORT,
not things that CHECK. A step writes a record; nothing compares the record with the
event. phase_tracker called step_ok() before the step ran, so 133 phase reports were
structurally incapable of naming a failure. A cockpit panel rendered a file nothing
writes. A flag was "enabled" for six hours with no wire behind it. None of these are
subtle - nothing was POSITIONED to see them, because every observer here is the thing
being observed.

This is positioned outside. It takes records that name their sources and re-derives
them. It never trusts a stored value; it re-reads the file the value claims to come from.

The honest headline is not how many claims agree. It is how many claims CANNOT BE
CHECKED AT ALL - the ones that carry no source. A system whose stated value is
verification should know that number and watch it fall.

READ-ONLY. Writes nothing without --write.
"""

from __future__ import annotations
import argparse, datetime as dt, json, pathlib, sys

BASE = pathlib.Path(__file__).resolve().parents[1]
OUT = BASE / "memory" / "claim_verification_latest.json"
METHOD_VERSION = "verify_claims/1"
REL_TOL = 1e-6

AGREES = "AGREES"
DIFFERS = "DIFFERS"          # the source moved, or the claim was never true
FILE_GONE = "SOURCE_FILE_GONE"
KEY_GONE = "SOURCE_KEY_GONE"
UNSOURCED = "NO_SOURCE"      # the claim names nothing - the real finding
UNREADABLE = "SOURCE_UNREADABLE"
# The claim named a scalar; the source now holds a container. The claim may still be
# true - what changed is that its ADDRESS no longer means what it meant. Calling that
# a contradiction would be as wrong as calling it agreement.
SHAPE = "SOURCE_SHAPE_CHANGED"

CHECKABLE = (AGREES, DIFFERS)


def _load(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except FileNotFoundError:
        return None, FILE_GONE
    except Exception as e:
        return None, f"{UNREADABLE}: {type(e).__name__}"


_MISSING = object()


def _walk(doc, key: str):
    """Dotted path, with [n] for list indices. Returns _MISSING rather than guessing."""
    cur = doc
    for part in str(key).split("."):
        while part.endswith("]") and "[" in part:
            part, idx = part[:part.rindex("[")], part[part.rindex("[") + 1:-1]
            if part:
                if not isinstance(cur, dict) or part not in cur:
                    return _MISSING
                cur = cur[part]
            if not isinstance(cur, list):
                return _MISSING
            try:
                cur = cur[int(idx)]
            except (ValueError, IndexError):
                return _MISSING
            part = ""
        if not part:
            continue
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        scale = max(abs(a), abs(b), 1.0)
        return abs(a - b) <= REL_TOL * scale
    return a == b


def verify_claim(claim: dict, root: pathlib.Path) -> dict:
    """claim = {file, key, value, ...}. Anything without file+key is UNSOURCED."""
    f, k = claim.get("file"), claim.get("key")
    out = {"file": f, "key": k, "claimed": claim.get("value")}
    if not f or k is None:
        out["verdict"] = UNSOURCED
        out["why"] = "the record states a value and names nothing that could contradict it"
        return out
    doc, err = _load(root / f)
    if err:
        out["verdict"] = err if err == FILE_GONE else UNREADABLE
        out["why"] = err
        return out
    found = _walk(doc, k)
    if found is _MISSING:
        out["verdict"] = KEY_GONE
        out["why"] = f"'{k}' is not in {f} any more"
        return out
    out["found"] = found
    want = claim.get("value")
    if isinstance(found, (dict, list)) and not isinstance(want, (dict, list)):
        out["verdict"] = SHAPE
        flat = json.dumps(found, ensure_ascii=False, default=str)
        out["still_present"] = json.dumps(want, ensure_ascii=False, default=str).strip('"') in flat
        out["why"] = ("the source became a container; the claimed value is "
                      + ("still inside it" if out["still_present"] else "not inside it"))
        return out
    out["verdict"] = AGREES if _same(found, want) else DIFFERS
    return out


def _claims_in(obj, trail="") -> list[dict]:
    """Any dict carrying file+key+value is a claim, wherever it sits. Also picks up
    the premises[] shape already used by memory/deductions_latest.json."""
    found = []
    if isinstance(obj, dict):
        if "file" in obj and "key" in obj and "value" in obj:
            found.append(dict(obj, _at=trail))
        for k, v in obj.items():
            found += _claims_in(v, f"{trail}.{k}" if trail else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += _claims_in(v, f"{trail}[{i}]")
    return found


def verify_file(path: pathlib.Path, root: pathlib.Path) -> list[dict]:
    doc, err = _load(path)
    if err or doc is None:
        return []
    rows = []
    for c in _claims_in(doc):
        r = verify_claim(c, root)
        r["record"] = path.relative_to(root).as_posix()
        r["at"] = c.get("_at")
        rows.append(r)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(BASE))
    ap.add_argument("--glob", default="memory/*_latest.json",
                    help="which records to check; repeatable via comma")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()

    root = pathlib.Path(a.root).resolve()
    rows, seen = [], set()
    for pat in a.glob.split(","):
        for p in sorted(root.glob(pat.strip())):
            # A file matching two globs is one file. Counting it twice inflated every
            # verdict on the first real run.
            rp = p.resolve()
            if p.is_file() and rp not in seen:
                seen.add(rp)
                rows += verify_file(p, root)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    checkable = sum(counts.get(v, 0) for v in CHECKABLE)

    print(f"{METHOD_VERSION}  {root}")
    print(f"  claims found {len(rows)}")
    for v in (AGREES, DIFFERS, SHAPE, KEY_GONE, FILE_GONE, UNREADABLE, UNSOURCED):
        if counts.get(v):
            print(f"    {v:<20} {counts[v]}")
    if rows:
        share = 100.0 * checkable / len(rows)
        print(f"\n  {share:.1f}% of claims could be checked at all "
              f"({checkable} of {len(rows)}). The rest name no source.")
    else:
        print("\n  NO CLAIMS CARRY A SOURCE. Nothing here can be checked - that is the finding,"
              "\n  not an empty result.")
    for r in rows:
        if r["verdict"] == DIFFERS:
            print(f"  DIFFERS  {r['record']} :: {r['at']}\n"
                  f"           claims {r['claimed']!r}, {r['file']}::{r['key']} now says {r.get('found')!r}")
    if a.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({
            "method": METHOD_VERSION,
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "claims": len(rows), "counts": counts,
            "checkable_share": (checkable / len(rows)) if rows else None,
            "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  wrote {OUT}")
    else:
        print("\n  (read only - pass --write to record memory/claim_verification_latest.json)")
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
        (root / "memory" / "composed_indicators.json").write_text(json.dumps({
            "CLIMATE": {"anchor": 427.59, "org": "NOAA"},
            "list": [{"v": 1}, {"v": 2}]}), encoding="utf-8")

        def v(c):
            return verify_claim(c, root)["verdict"]

        want(v({"file": "memory/composed_indicators.json", "key": "CLIMATE.anchor",
                "value": 427.59}) == AGREES, "a claim its source still supports AGREES")
        want(v({"file": "memory/composed_indicators.json", "key": "CLIMATE.anchor",
                "value": 400.0}) == DIFFERS,
             "a claim its source contradicts DIFFERS - the whole point")
        want(v({"file": "memory/composed_indicators.json", "key": "CLIMATE.gone",
                "value": 1}) == KEY_GONE, "a vanished key is named, not treated as a mismatch")
        want(v({"file": "memory/nope.json", "key": "a", "value": 1}) == FILE_GONE,
             "a vanished file is named")
        want(v({"value": 42}) == UNSOURCED,
             "a value that names no source is UNSOURCED, never AGREES")
        want(v({"file": "memory/composed_indicators.json", "key": "list[1].v",
                "value": 2}) == AGREES, "list indices resolve")
        # floats must not fail on representation
        want(v({"file": "memory/composed_indicators.json", "key": "CLIMATE.anchor",
                "value": 427.5900000001}) == AGREES,
             "float noise is not a contradiction")
        # and a real difference must not hide behind the tolerance
        want(v({"file": "memory/composed_indicators.json", "key": "CLIMATE.anchor",
                "value": 427.61}) == DIFFERS, "a real difference survives the tolerance")
        # the negative control that matters most
        (root / "memory" / "x_latest.json").write_text(json.dumps(
            {"conclusions": [{"premises": [
                {"file": "memory/composed_indicators.json", "key": "CLIMATE.anchor", "value": 427.59},
                {"file": "memory/composed_indicators.json", "key": "CLIMATE.anchor", "value": 1.0}]}]}),
            encoding="utf-8")
        rows = verify_file(root / "memory" / "x_latest.json", root)
        want(len(rows) == 2 and {r["verdict"] for r in rows} == {AGREES, DIFFERS},
             "premises inside a real record are found and judged individually",
             str([r["verdict"] for r in rows]))
        empty = verify_file(root / "memory" / "composed_indicators.json", root)
        want(verify_claim({"file": "memory/composed_indicators.json", "key": "CLIMATE",
                           "value": "NOAA"}, root)["verdict"] == SHAPE,
             "a source that became a container is SHAPE_CHANGED, not a contradiction")
        want(verify_claim({"file": "memory/composed_indicators.json", "key": "CLIMATE",
                           "value": "NOAA"}, root)["still_present"] is True,
             "and it says whether the claimed value is still inside")
        want(empty == [],
             "a file with no sourced claims yields nothing to check, and says so by being empty")

    for ok, why, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {why}")
        if not ok and detail:
            print(f"         {detail}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
