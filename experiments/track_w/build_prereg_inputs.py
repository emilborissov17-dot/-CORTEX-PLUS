#!/usr/bin/env python3
"""
experiments/track_w/build_prereg_inputs.py — the two computed inputs of the D1-W
pre-registration DRAFT (1 Oct 2026). It fits nothing, forecasts nothing, scores
nothing.

  1. THE FROZEN COUNTRY LIST (prereg point 2). From UCDP GED 26.1
     (data/external/ucdp/ged261-csv.zip): type_of_violence == 1, best-estimate
     fatalities summed per (country_id, month of date_start); a month COUNTS when
     that sum is >= 1; a country is frozen in when it has >= 40 counting months
     from 1989-01 on. Written into prereg_w.json with the per-country month
     counts and the sha256 of the list.

  2. experiments/track_w/release_dates.json (leak guards G1, G2). One row per
     UCDP GED version (annual and Candidate) and per VIEWS vintage, each with a
     release date AND the file/URL that states it - or "UNPROVEN".

REFUSAL IS THE SAFE OUTPUT. A missing input file or column raises SystemExit
(exit 2) and writes nothing. There is no fallback to another file and NO DATE IS
EVER INFERRED: an HTTP Last-Modified header, a file mtime, a run name and a
month-only date are not release dates, and a version that has nothing better is
written as UNPROVEN, which excludes it. A date is written only if that exact
string is a cell of the publisher's table in the saved snapshot, and
check_release_dates() re-verifies that against the snapshot bytes before
anything is written - a date that is not literally in the proof file aborts the
run.

Usage:
  venv\\Scripts\\python.exe experiments/track_w/build_prereg_inputs.py            # write both
  venv\\Scripts\\python.exe experiments/track_w/build_prereg_inputs.py --dry      # print, write nothing
  venv\\Scripts\\python.exe experiments/track_w/build_prereg_inputs.py --selftest
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EXT = REPO / "data" / "external"
GED_ZIP = EXT / "ucdp" / "ged261-csv.zip"
UCDP_PAGES = [EXT / "ucdp" / "downloads_index.html", EXT / "ucdp" / "olddw.html"]
CAND_URLS = EXT / "ucdp" / "cand_urls.txt"
VIEWS_ROOT = EXT / "views" / "api_root.json"
VIEWS_WIKI = EXT / "views" / "wiki_Available-datasets.md"
VIEWS_WIKI_URL = "https://raw.githubusercontent.com/wiki/prio-data/views_api/Available-datasets.md"
VIEWS_WIKI_PAGE = "https://github.com/prio-data/views_api/wiki/Available-datasets"
PREREG_JSON = HERE / "prereg_w.json"
RELEASE_DATES = HERE / "release_dates.json"

TYPE_STATE_BASED = "1"
MIN_MONTH = "1989-01"
MIN_MONTHS = 40
MIN_MONTH_FATALITIES = 1
REQUIRED_COLS = ("id", "type_of_violence", "best", "date_start", "country", "country_id")
UNPROVEN = "UNPROVEN"
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

csv.field_size_limit(2**31 - 1)


class Refused(SystemExit):
    def __init__(self, why: str):
        super().__init__(2)
        self.why = why

    def __str__(self) -> str:
        return f"REFUSED: {self.why}"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _need(p: Path) -> Path:
    if not p.is_file():
        raise Refused(f"missing input {p.relative_to(REPO).as_posix()}")
    return p


# ── 1. the frozen country list ───────────────────────────────────────────────
def ged_rows(zpath: Path):
    _need(zpath)
    zf = zipfile.ZipFile(zpath)
    members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
    if len(members) != 1:
        raise Refused(f"expected exactly one csv in {zpath.name}, got {members}")
    with io.TextIOWrapper(zf.open(members[0]), encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLS if c not in (rd.fieldnames or [])]
        if missing:
            raise Refused(f"{zpath.name} lacks columns {missing}")
        yield from rd


def country_months(rows) -> tuple[dict, dict]:
    """(country_id -> {YYYY-MM: summed best}, country_id -> sorted names) for
    state-based events from MIN_MONTH on. An unparseable `best` is a refusal,
    not a skipped row: a silently dropped event changes a month's sum."""
    sums: dict = defaultdict(lambda: defaultdict(float))
    names: dict = defaultdict(set)
    for r in rows:
        if r["type_of_violence"].strip() != TYPE_STATE_BASED:
            continue
        month = r["date_start"][:7]
        if month < MIN_MONTH:
            continue
        try:
            best = float(r["best"])
        except ValueError:
            raise Refused(f"event id {r['id']}: best={r['best']!r} is not a number")
        sums[r["country_id"]][month] += best
        names[r["country_id"]].add(r["country"])
    return sums, {k: sorted(v) for k, v in names.items()}


def frozen_list(sums: dict, names: dict) -> list:
    out = []
    for cid, by_month in sums.items():
        counting = sorted(m for m, s in by_month.items() if s >= MIN_MONTH_FATALITIES)
        if len(counting) >= MIN_MONTHS:
            out.append({"country_id": int(cid), "country": names[cid],
                        "months_with_ge1_state_based_fatality": len(counting),
                        "first_month": counting[0], "last_month": counting[-1]})
    out.sort(key=lambda r: (-r["months_with_ge1_state_based_fatality"], r["country_id"]))
    return out


def list_hash(lst: list) -> str:
    """sha256 of the canonical JSON of the list (sort_keys, no whitespace, UTF-8)."""
    return sha256_bytes(json.dumps(lst, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False).encode("utf-8"))


# ── 2. release dates ─────────────────────────────────────────────────────────
def ged_versions(pages: list, cand_urls: Path) -> list:
    annual = set()
    for p in pages:
        annual |= set(re.findall(r"ged(\d+)-csv\.zip", _need(p).read_text(encoding="utf-8", errors="replace")))
    rows = []
    for code in sorted(annual, key=lambda c: (int(c[:-1]), int(c[-1]))):
        ver = f"{code[:-1]}.{code[-1]}"
        rows.append({"kind": "UCDP_GED_annual", "version": ver,
                     "file_url": f"https://ucdp.uu.se/downloads/ged/ged{code}-csv.zip"})
    for url in _need(cand_urls).read_text(encoding="utf-8").split():
        m = re.search(r"GEDEvent_v([\d_]+)\.csv$", url)
        if not m:
            raise Refused(f"unparseable candidate URL {url!r}")
        rows.append({"kind": "UCDP_GED_candidate", "version": m.group(1).replace("_", "."), "file_url": url})
    for r in rows:
        r.update({"release_date": UNPROVEN,
                  "proof": None,
                  "why_unproven": ("no release date is stated on https://ucdp.uu.se/downloads/ or "
                                   "https://ucdp.uu.se/downloads/olddw.html (saved as data/external/ucdp/"
                                   "downloads_index.html and olddw.html). The HTTP Last-Modified header "
                                   "is a proxy for upload time, not a release date, and is not used.")})
    return rows


def wiki_table(text: str) -> dict:
    """dataset -> release-date cell, from the '# Conflict prediction datasets'
    section only (the 'Next planned' and 'Input data' sections are not vintages
    that exist)."""
    out, section = {}, None
    for line in text.splitlines():
        if line.startswith("#"):
            section = line.strip("# ").strip()
            continue
        if section != "Conflict prediction datasets" or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] in ("Dataset", "") or set(cells[0]) <= set("- "):
            continue
        out[cells[0]] = cells[5]
    return out


def views_vintages(root: Path, wiki: Path) -> list:
    runs = json.loads(_need(root).read_text(encoding="utf-8")).get("runs")
    if not isinstance(runs, list) or not runs:
        raise Refused(f"{root.name} carries no 'runs' list")
    wiki_bytes = _need(wiki).read_bytes()
    table = wiki_table(wiki_bytes.decode("utf-8"))
    proof = {"file": wiki.relative_to(REPO).as_posix(), "sha256": sha256_bytes(wiki_bytes),
             "url": VIEWS_WIKI_URL, "page": VIEWS_WIKI_PAGE,
             "strength": "publisher's own statement in a mutable GitHub wiki; not a machine-verified embargo"}
    rows = []
    for run in sorted(runs):
        cell = table.get(run)
        row = {"kind": "VIEWS_vintage", "version": run,
               "file_url": f"https://api.viewsforecasting.org/{run}"}
        if cell is not None and _ISO_DAY.match(cell):
            try:
                date.fromisoformat(cell)
            except ValueError:
                cell_ok = False
            else:
                cell_ok = True
        else:
            cell_ok = False
        if cell_ok:
            row.update({"release_date": cell, "proof": proof})
        else:
            row.update({"release_date": UNPROVEN, "proof": None,
                        "stated_in_wiki": cell,
                        "why_unproven": ("absent from the wiki's 'Conflict prediction datasets' table"
                                         if cell is None else
                                         f"the wiki states {cell!r}, which is not a calendar day")})
        rows.append(row)
    return rows


def check_release_dates(rows: list, base: Path = REPO) -> None:
    """THE NET behind 'do not guess a date'. Every row that carries a date must
    name a proof file whose bytes hash to the recorded sha256 AND contain that
    dataset's table row with that exact date cell. Raises; never returns False."""
    cache = {}
    for r in rows:
        d = r.get("release_date")
        if d == UNPROVEN:
            if r.get("proof") is not None:
                raise Refused(f"{r['version']}: UNPROVEN but carries a proof")
            continue
        if not (isinstance(d, str) and _ISO_DAY.match(d)):
            raise Refused(f"{r['version']}: release_date {d!r} is neither a day nor UNPROVEN")
        pf = (r.get("proof") or {}).get("file")
        if not pf:
            raise Refused(f"{r['version']}: a date with no proof file")
        if pf not in cache:
            b = (base / pf).read_bytes()
            cache[pf] = (sha256_bytes(b), wiki_table(b.decode("utf-8")))
        sha, table = cache[pf]
        if sha != r["proof"].get("sha256"):
            raise Refused(f"{r['version']}: proof file {pf} no longer hashes to the recorded sha256")
        if table.get(r["version"]) != d:
            raise Refused(f"{r['version']}: date {d} is not the table cell in {pf} "
                          f"(cell is {table.get(r['version'])!r})")


# ── write ────────────────────────────────────────────────────────────────────
def _dump(obj) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")   # LF only


def build(dry: bool = False) -> dict:
    sums, names = country_months(ged_rows(GED_ZIP))
    lst = frozen_list(sums, names)
    rel = ged_versions(UCDP_PAGES, CAND_URLS) + views_vintages(VIEWS_ROOT, VIEWS_WIKI)
    check_release_dates(rel)
    unproven = [f"{r['kind']} {r['version']}" for r in rel if r["release_date"] == UNPROVEN]
    if not dry:
        RELEASE_DATES.write_bytes(_dump({
            "_what": "Release date per data version for leak guards G1 (GED) and G2 (VIEWS). "
                     "UNPROVEN versions are EXCLUDED: no origin may read them.",
            "_built_by": "experiments/track_w/build_prereg_inputs.py",
            "rows": rel}))
        doc = json.loads(PREREG_JSON.read_text(encoding="utf-8")) if PREREG_JSON.exists() else {}
        doc["frozen_country_list"] = {
            "criterion": (f"UCDP GED 26.1, type_of_violence == {TYPE_STATE_BASED}, best summed per "
                          f"(country_id, month of date_start); a month counts when the sum >= "
                          f"{MIN_MONTH_FATALITIES}; country kept when it has >= {MIN_MONTHS} counting "
                          f"months from {MIN_MONTH} on"),
            "source_file": GED_ZIP.relative_to(REPO).as_posix(),
            "source_sha256": sha256_file(GED_ZIP),
            "count": len(lst),
            "list_sha256": list_hash(lst),
            "list_sha256_is_over": "json.dumps(countries, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')",
            "countries": lst}
        PREREG_JSON.write_bytes(_dump(doc))
    return {"count": len(lst), "list_sha256": list_hash(lst), "countries": lst,
            "release_rows": len(rel), "unproven": unproven}


# ── selftest: integrations, and the negative controls ─────────────────────────
def selftest() -> dict:
    res = {"integrations": {}, "controls": {}}
    for p in [GED_ZIP, *UCDP_PAGES, CAND_URLS, VIEWS_ROOT, VIEWS_WIKI]:
        res["integrations"][p.relative_to(REPO).as_posix()] = "LIVE" if p.is_file() else "INERT (missing)"

    def refuses(fn) -> bool:
        try:
            fn()
        except Refused:
            return True
        return False

    good = {"kind": "VIEWS_vintage", "version": "fatalities003_2026_07_t01",
            "release_date": "2026-08-26", "proof": None}
    if VIEWS_WIKI.is_file():
        b = VIEWS_WIKI.read_bytes()
        good["proof"] = {"file": VIEWS_WIKI.relative_to(REPO).as_posix(), "sha256": sha256_bytes(b)}
        res["controls"]["true date accepted"] = not refuses(lambda: check_release_dates([good]))
        res["controls"]["guessed date refused"] = refuses(
            lambda: check_release_dates([{**good, "release_date": "2026-08-01"}]))
        res["controls"]["tampered proof hash refused"] = refuses(
            lambda: check_release_dates([{**good, "proof": {**good["proof"], "sha256": "0" * 64}}]))
        res["controls"]["month-only date refused"] = refuses(
            lambda: check_release_dates([{**good, "release_date": "2026-08"}]))
    res["controls"]["date without proof refused"] = refuses(
        lambda: check_release_dates([{**good, "proof": None}]))
    res["controls"]["missing input refused"] = refuses(lambda: _need(REPO / "no" / "such.file"))
    rows = [{"type_of_violence": "1", "date_start": "2000-01-05", "best": "x", "id": "9",
             "country": "A", "country_id": "1"}]
    res["controls"]["unparseable best refused"] = refuses(lambda: country_months(rows))
    s, n = country_months([{"type_of_violence": t, "date_start": f"{y}-{m:02d}-01", "best": "1",
                            "id": "0", "country": "A", "country_id": "1"}
                           for t in ("1", "2") for y in (1988, 2000, 2001, 2002, 2003) for m in range(1, 13)])
    res["controls"]["pre-1989 months and non-state-based rows excluded"] = (
        len(s["1"]) == 48 and frozen_list(s, n)[0]["months_with_ge1_state_based_fatality"] == 48)
    res["ok"] = all(res["controls"].values())
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    try:
        out = build(dry="--dry" in sys.argv)
    except Refused as e:
        print(str(e))
        sys.exit(2)
    print(json.dumps({k: v for k, v in out.items() if k != "countries"}, indent=2, ensure_ascii=False))
