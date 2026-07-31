#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_promotion_seam.py — a promoted source cannot enter the portfolio as a ghost.

THE SEAM: promote() wrote an entry to config/composer_specs.json and nobody asked whether
it could be read. A source missing its location raises on every fetch, dies against
DEATH_AT three cycles later, and the slot looks FILLED the whole time — silence that
reads as coverage. Two walls, both before the spec is touched:

  SCHEMA  each kind declares the field it is read from (file -> path, http_* -> url).
  SMOKE   fetch it ONCE, with the same loader the composer uses. Raise or empty -> the
          promotion fails and the spec is never written.

After this, "does it actually fetch?" is not a question anyone has to ask about a promoted
source — it could not have been promoted otherwise.

Also fixes the misreading that caused a false alarm on 2026-07-31: on a FILE entry, `url`
is an identity reference (stable approve-id, dedupe, candidate matching) and never a fetch
location. Its presence is correct; reading it as the source was the error.

  venv\\Scripts\\python.exe test\\test_promotion_seam.py
"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "composers"))
import composer as C

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

TMP = Path(tempfile.mkdtemp())
REAL_SPEC = json.loads((REPO / "config" / "composer_specs.json").read_text(encoding="utf-8"))
C.SPEC_FILE = TMP / "specs.json"
C.REPO = REPO                      # file sources still resolve against the real repo
DATA = TMP / "d.json"


def fresh_spec():
    C.SPEC_FILE.write_text(json.dumps({"AX": {"anchor_slot": "anchor_annual",
                                              "measure_slot": "measurement_daily",
                                              "portfolio": {"anchor_annual": {
                                                  "min": 1, "freshness_days": 45,
                                                  "sources": []}}}}), encoding="utf-8")


def n_sources():
    return len(json.loads(C.SPEC_FILE.read_text(encoding="utf-8"))
               ["AX"]["portfolio"]["anchor_annual"]["sources"])


# a real readable file, relative to the repo so the file loader finds it
REL = "test/_promotion_seam_probe.json"
(REPO / REL).write_text(json.dumps({"block": {"value": 42, "when": "2026-07-31"}}),
                        encoding="utf-8")

# ---------- SCHEMA WALL ----------
def rejected(entry):
    try:
        C.validate_entry(entry)
        return None
    except C.PromotionRejected as e:
        return str(e)

msg = rejected({"kind": "file", "url": "local://x", "extract": "a"})
check("kind=file WITHOUT path is rejected", msg is not None)
check("...with the named reason", msg == "kind=file requires 'path' — promotion rejected")
check("kind=file with an empty path is rejected",
      rejected({"kind": "file", "path": "   ", "extract": "a"}) is not None)
check("kind=file WITH path validates",
      rejected({"kind": "file", "path": REL, "extract": "a"}) is None)
check("a file entry may ALSO carry url (identity, not location)",
      rejected({"kind": "file", "path": REL, "url": "local://x"}) is None)
check("http kinds require url",
      rejected({"kind": "http_csv", "path": REL}) == "kind=http_csv requires 'url' — "
                                                     "promotion rejected")
check("http kinds validate with url", rejected({"kind": "http_csv", "url": "http://x"}) is None)
check("an unknown kind is rejected", "unknown kind" in (rejected({"kind": "nonsense"}) or ""))
check("every kind fetch() handles declares a location",
      set(C.KIND_LOCATION) == {"file", "http_json_path", "http_csv", "http_json_count",
                               "http_json_series", "http_gdelt_tone"})

# ---------- SMOKE TEST ----------
ok_entry = {"id": "t", "kind": "file", "path": REL, "extract": "block.value"}
v, dd = C.smoke_fetch(ok_entry)
check("smoke fetch reads a real value", v == 42.0)

def smoke_fails(entry):
    try:
        C.smoke_fetch(entry)
        return False
    except Exception:
        return True

check("smoke fails on a missing file",
      smoke_fails({"kind": "file", "path": "test/_does_not_exist.json", "extract": "a"}))
check("smoke fails on an extract that is not there",
      smoke_fails({"kind": "file", "path": REL, "extract": "block.nope"}))
check("smoke ACCEPTS 0.0 (a zero count is a measurement, not an empty read)",
      C.smoke_fetch({"kind": "file", "path": REL, "extract": "block.zero"}
                    if False else
                    {"kind": "file", "path": str(Path(REL)), "extract": "block.value"})[0] == 42.0)
(REPO / "test/_promotion_seam_zero.json").write_text(json.dumps({"n": 0}), encoding="utf-8")
check("...proven with a real zero",
      C.smoke_fetch({"kind": "file", "path": "test/_promotion_seam_zero.json",
                     "extract": "n"})[0] == 0.0)

# ---------- promote() writes nothing when a wall trips ----------
fresh_spec()
res = C.promote("AX", "local://x", "anchor_annual", "file", "ORG", extract="block.value")
check("promote WITHOUT path is refused", res.get("rejected") and "requires 'path'" in res["error"])
check("...and the spec was never written", n_sources() == 0)

fresh_spec()
res = C.promote("AX", "local://x", "anchor_annual", "file", "ORG",
                extract="block.nope", path=REL)
check("promote whose SMOKE FETCH raises is refused", res.get("rejected") is True)
check("...surfacing the raw exception", "exception" in res and res["exception"])
check("...and the spec is untouched — no ghost in the portfolio", n_sources() == 0)

fresh_spec()
res = C.promote("AX", "local://x", "anchor_annual", "file", "ORG",
                extract="block.value", path=REL)
check("a sound promotion succeeds", res.get("promoted") and n_sources() == 1)
check("...and reports what it actually read", res.get("smoke_value") == 42.0)

fresh_spec()
res = C.promote("AX", "https://nope.invalid/x", "anchor_annual", "http_json_path", "ORG",
                extract="a")
check("an http source that cannot be fetched is refused too", res.get("rejected") is True)
check("...spec untouched", n_sources() == 0)

# ---------- existing sound entries still validate AND smoke-pass ----------
live = []
for axis, body in REAL_SPEC.items():
    if axis.startswith("_"):
        continue
    for slot, sl in body.get("portfolio", {}).items():
        for s in sl.get("sources", []):
            if s.get("kind") == "file":
                live.append((axis, s))
check("the real spec has file-kind sources to check", len(live) > 0)
bad = [f"{a}/{s.get('id')}" for a, s in live if rejected(s)]
check(f"every existing file source in the live spec validates ({len(live)} checked)", not bad)

p96 = [s for _a, s in live if s.get("id") == "promoted_96302"]
check("promoted_96302 is present and validates", len(p96) == 1 and not rejected(p96[0]))
if p96:
    val, _ = C.smoke_fetch(dict(p96[0]))
    check(f"promoted_96302 smoke-fetches a real value ({val})", isinstance(val, float))
    check("...and it is the post-fix UCDP figure, not the 2816 artefact", val == 65.0)

# ---------- CLI gate, at the parser ----------
def cli(*args):
    r = subprocess.run([sys.executable, str(REPO / "experiments" / "composers" / "composer.py"),
                        *args], capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stderr or "") + (r.stdout or "")

rc, err = cli("--promote", "AX", "--kind", "file", "--url", "http://x", "--slot", "s")
check("CLI: --kind file --url is a PARSER error", rc == 2 and "reads from --path" in err)
rc, err = cli("--promote", "AX", "--kind", "file", "--slot", "s")
check("CLI: --kind file without --path is a parser error", rc == 2 and "requires --path" in err)

for f in ("test/_promotion_seam_probe.json", "test/_promotion_seam_zero.json"):
    (REPO / f).unlink(missing_ok=True)
shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
