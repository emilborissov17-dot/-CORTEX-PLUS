#!/usr/bin/env python3
"""
experiments/institution/resolve_forward_rows.py — resolves OPEN forward rows (task #30 part 1).

For every experiments/institution/forward/<row>.json whose resolutions file has no
FINAL line, the first unresolved stage (PROVISIONAL, then FINAL) is checked:

  released + covers the window  -> the row's condition computed exactly as written
                                   (same filter fields, sum(best)) from that release;
                                   one resolution line appended: RESOLVED
  released, window not covered  -> {verdict: NOT_APPLICABLE, reason} appended
  not released, past late date  -> {verdict: SOURCE_LATE} appended
  not released, before it       -> nothing written; WAITING with the next expected date
  anything else (network error, unknown version shape, missing field)
                                -> ERROR, nothing written (fail closed)

"Released" is asked of the authenticated UCDP API (core/ucdp_client.api_get: token,
daily counter, cap, provenance). Measured on 2026-09-25: an unreleased version answers
HTTP 400 "Invalid object name 'GEDEvent_v26_0_10'"; only that answer means "not
released" - every other error is an ERROR.

Coverage is read from the version string, the only place UCDP states it: a monthly
Candidate "YY.0.M" holds month M of 20YY (incremental; measured on 26.0.7 and 26.0.8),
an annual GED "YY.1" holds 1989-01-01 .. (20YY-1)-12-31 (GED 26.1 codebook).

Every resolution line carries `filter` = a copy of the row's condition, so RF7 can
compare them byte for byte. After an append the resolutions file is sealed (root over
its bytes + previous root + writer, appended to memory/merkle_roots.jsonl) and, with
--publish, goes through notary.may_act - class human_signed_preregistration in its
resolution form - before github_publisher.

    venv\\Scripts\\python.exe experiments/institution/resolve_forward_rows.py [--publish]
    venv\\Scripts\\python.exe experiments/institution/resolve_forward_rows.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.institution import forward_rows as fr  # noqa: E402

ROOTS_LOG = REPO / "memory" / "merkle_roots.jsonl"
STAGES = (("PROVISIONAL", "provisional"), ("FINAL", "final"))


class ResolverError(RuntimeError):
    """Fail closed: the resolver cannot say what the source says."""


# ── the UCDP side ────────────────────────────────────────────────────────────

class UcdpClient:
    """released(version) / events(version, condition) through core.ucdp_client.api_get."""

    def __init__(self):
        from core import ucdp_client as uc
        self.uc, self.requests = uc, 0

    def released(self, version: str) -> bool:
        self.requests += 1
        try:
            self.uc.api_get(version, page=0, pagesize=1)
            return True
        except self.uc.UcdpUnavailable as e:
            if getattr(e, "status", None) == 400 and "Invalid object name" in str(getattr(e, "body", "")):
                return False
            raise ResolverError(f"release check for {version} failed: {e}") from e

    def events(self, version: str, condition: dict) -> list:
        return self._paged(version, {"Dyad": condition["dyad_new_id"],
                                     "TypeOfViolence": condition["type_of_violence"]})

    def events_any(self, version: str, query: dict) -> list:
        """Every event of the query (no dyad filter) - the assumption check needs
        the dyads the row did NOT register."""
        return self._paged(version, query)

    def _paged(self, version: str, query: dict) -> list:
        rows, page = [], 0
        while True:
            self.requests += 1
            try:
                p = self.uc.api_get(version, page=page, pagesize=1000, query=query)
            except self.uc.UcdpUnavailable as e:
                raise ResolverError(f"events of {version} failed: {e}") from e
            rows += p["Result"]
            if page + 1 >= int(p["TotalPages"]):
                return rows
            page += 1


def stage_version(row: dict, stage: str) -> str:
    """The UCDP version a stage names: the Candidate version in the PROVISIONAL
    source, or - for the FINAL coverage rule - the first annual release whose
    coverage includes the window's year."""
    src = row["resolution"][stage.lower()]["source"]
    if stage == "PROVISIONAL":
        m = re.search(r"\b(\d{2}\.0\.\d{1,2})\b", src)
        if not m:
            raise ResolverError(f"PROVISIONAL source names no Candidate version: {src!r}")
        return m.group(1)
    m = re.search(r"coverage includes (\d{4})-(\d{2})", src)
    if not m:
        raise ResolverError(f"FINAL source is not a coverage rule: {src!r}")
    return f"{int(m.group(1)) - 2000 + 1}.1"


def covers(version: str, window: str) -> bool:
    """window = 'YYYY-MM'. Raises on a version shape nobody has measured."""
    y, mo = int(window[:4]), int(window[5:7])
    m = re.fullmatch(r"(\d{2})\.0\.(\d{1,2})", version)
    if m:
        return (2000 + int(m.group(1)), int(m.group(2))) == (y, mo)
    m = re.fullmatch(r"(\d{2})\.1", version)
    if m:
        return y <= 2000 + int(m.group(1)) - 1
    raise ResolverError(f"coverage of UCDP version {version!r} is not known")


def compute(rows: list, condition: dict) -> tuple[float, int]:
    """sum(best) and the number of events, with the row's own filter fields."""
    lo, hi = condition["date_start_from"], condition["date_start_to"]
    sel = [r for r in rows if fr.matches(r, condition) and lo <= str(r["date_start"])[:10] <= hi]
    return float(sum(float(r["best"]) for r in sel)), len(sel)


def assumption_evidence(rows: list, condition: dict, a: dict) -> dict:
    """{dyad_new_id: {dyad_name, events, best}} for window events with the
    assumption's side_a, whose side_b names one of its patterns, coded to a dyad
    OTHER than the registered one. Empty = the assumption holds."""
    lo, hi = condition["date_start_from"], condition["date_start_to"]
    out: dict = {}
    for r in rows:
        if str(r.get("dyad_new_id")) == str(a["registered_dyad_new_id"]):
            continue
        if str(r.get("type_of_violence")) != str(condition["type_of_violence"]):
            continue
        if not lo <= str(r.get("date_start"))[:10] <= hi:
            continue
        if str(r.get("side_a")) != a["side_a"]:
            continue
        if not any(p in str(r.get("side_b", "")) for p in a["side_b_patterns"]):
            continue
        d = out.setdefault(str(r["dyad_new_id"]), {"dyad_name": r.get("dyad_name"), "events": 0, "best": 0.0})
        d["events"] += 1
        d["best"] += float(r.get("best") or 0)
    return out


def verdict_for(value: float, condition: dict) -> str:
    kept = re.fullmatch(r"\s*<\s*(\d+(?:\.\d+)?)\s*", condition["kept_if"])
    not_kept = re.fullmatch(r"\s*>=\s*(\d+(?:\.\d+)?)\s*", condition["not_kept_if"])
    if not kept or not not_kept or float(kept.group(1)) != float(not_kept.group(1)):
        raise ResolverError("the row's kept_if / not_kept_if are not one threshold")
    return "KEPT" if value < float(kept.group(1)) else "NOT_KEPT"


# ── one row ──────────────────────────────────────────────────────────────────

def _resolved_stages(log: Path) -> set:
    try:
        return {json.loads(l).get("stage") for l in log.read_text(encoding="utf-8").splitlines() if l.strip()}
    except FileNotFoundError:
        return set()


def _append(log: Path, rec: dict) -> None:
    with log.open("a", encoding="utf-8", newline="\n") as fh:     # sealed bytes: LF only
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def resolve_row(row_path: Path, client, today: date | None = None, roots_log: Path | None = None,
                publish: bool = False) -> dict:
    today = today or datetime.now().astimezone().date()
    row_path = Path(row_path)
    out = {"row_id": row_path.stem, "action": None, "stage": None, "next_expected": None,
           "appended": None, "requests": 0}
    try:
        row = json.loads(row_path.read_text(encoding="utf-8"))
        problems = fr.schema_problems(row)
        if problems:
            raise ResolverError(f"row schema: {problems}")
        log = row_path.parent / f"{row['id']}.resolutions.jsonl"
        if fr.status(row["id"], log) != "OPEN":
            out["action"] = "CLOSED"
            print(f"[R] {row['id']}: CLOSED (a FINAL resolution exists)")
            return out
        done = _resolved_stages(log)
        stage, key = next((s, k) for s, k in STAGES if s not in done)
        spec = row["resolution"][key]
        cond = row["condition"]
        window = cond["date_start_from"][:7]
        version = stage_version(row, stage)
        out["stage"] = stage
        base = {"row_id": row["id"], "stage": stage, "source": spec["source"],
                "computed_at": datetime.now(timezone.utc).isoformat(), "filter": cond}
        if client.released(version):
            if not covers(version, window):
                rec = {**base, "verdict": "NOT_APPLICABLE", "release_id": version, "released": True,
                       "reason": f"UCDP {version} does not cover the window {window}"}
                out["action"] = "NOT_APPLICABLE"
            else:
                rows = client.events(version, cond)
                value, n = compute(rows, cond)
                rec = {**base, "release_id": version, "released": True, "as_of": f"ucdp:{version}", "value": value,
                       "verdict": verdict_for(value, cond), "events_count": n,
                       "request_count": client.requests}
                # A SIGNED assumption (revisions.py) is checked on the same release.
                # The filter stays the row's condition - RF7 compares them - and
                # the other dyad goes into the evidence, never into the count.
                from experiments.institution import revisions as rv
                a = rv.assumption(row["id"], row_path.parent)
                if a is not None:
                    ev = assumption_evidence(client.events_any(version, {
                        "Country": a["country_gwno"], "TypeOfViolence": cond["type_of_violence"]}), cond, a)
                    rec["assumption"] = a
                    rec["assumption_evidence"] = ev
                    rec["request_count"] = client.requests
                    if ev:
                        rec["verdict"] = rv.ASSUMPTION_BROKEN
                out["action"] = "RESOLVED"
        else:
            late = date.fromisoformat(spec["source_late_if_no_release_by"])
            if today > late:
                rec = {**base, "verdict": "SOURCE_LATE", "release_id": version, "released": False,
                       "reason": f"UCDP {version} not released by {late}"}
                out["action"] = "SOURCE_LATE"
            else:
                m = re.search(r"\d{4}-\d{2}-\d{2}", spec.get("expected", ""))
                out["next_expected"] = m.group(0) if m else spec.get("expected")
                out["action"], out["requests"] = "WAITING", client.requests
                print(f"[R] {row['id']}: WAITING - {stage} source UCDP {version} not released; "
                      f"next expected {out['next_expected']}; SOURCE_LATE after {late} "
                      f"({client.requests} UCDP request(s))")
                return out
        _append(log, rec)
        out["appended"], out["requests"] = rec, client.requests
        print(f"[R] {row['id']}: {out['action']} {stage} -> {rec['verdict']} "
              f"(release {rec.get('release_id')}, value {rec.get('value')}, "
              f"{client.requests} UCDP request(s))")
        out["seal"] = seal_resolutions(log, roots_log)
        if publish:
            out["publish"] = publish_resolutions(row["id"], log)
        return out
    except Exception as e:  # noqa: BLE001 - fail closed: say so, write nothing more
        out["action"], out["error"] = "ERROR", f"{type(e).__name__}: {e}"
        out["requests"] = getattr(client, "requests", 0)
        print(f"[R] {out['row_id']}: ERROR - {out['error']}")
        return out


def seal_resolutions(log: Path, roots_log: Path | None = None,
                     kind: str = "institution0_resolution") -> dict:
    import merkle_memory as mm
    rl = Path(roots_log or ROOTS_LOG)
    prev = None
    try:
        lines = [l for l in rl.read_text(encoding="utf-8").splitlines() if l.strip()]
        prev = json.loads(lines[-1])["root"] if lines else None
    except FileNotFoundError:
        pass
    s = fr.seal(log, prev, mm.writer_identity())
    s.update({"file": log.name, "ts": datetime.now(timezone.utc).isoformat()})
    rl.parent.mkdir(parents=True, exist_ok=True)
    with rl.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"root": s["root"], "ts": s["ts"], "cycle_id": f"institution0:{log.name}",
                             "kind": kind, "file": log.name,
                             "row_sha256": s["row_sha256"], "leaf_count": 1, "prev_root": prev,
                             "writer": s["writer"]}, ensure_ascii=False) + "\n")
    (log.parent / (log.name.replace(".jsonl", ".seal.json"))).write_text(json.dumps(s, indent=2) + "\n",
                                                                        encoding="utf-8")
    return s


def publish_resolutions(row_id: str, log: Path) -> dict:
    from core.notary import may_act
    # prev_step is the row's own Merkle root (Emil, 26 Sep 2026): a resolution
    # follows the sealed row and names it.
    row_root = json.loads((log.parent / f"{row_id}.seal.json").read_text(encoding="utf-8"))["root"]
    ok, why = may_act("github_publish", row_root, target=log)
    if not ok:
        fr.record_publish(row_id, "suppressed", f"notary.may_act refused the resolution: {why}")
        return {"outcome": "suppressed", "why": why}
    seal = (log.parent / log.name.replace(".jsonl", ".seal.json")).read_text(encoding="utf-8")
    try:
        import github_publisher as gp
        written = gp.publish_institution0({f"institution0/{log.name}": log.read_bytes().decode("utf-8"),
                                           f"institution0/{log.name.replace('.jsonl', '.seal.json')}": seal},
                                          f"institution0: resolution for {row_id}")
    except Exception as e:  # noqa: BLE001
        fr.record_publish(row_id, "deferred", f"{type(e).__name__}: {e}", {"notary": why})
        return {"outcome": "deferred", "why": str(e)}
    fr.record_publish(row_id, "delivered", "resolution published", {
        "notary": why, "files": [w.get("path") for w in written],
        "commit_shas": [w.get("commit_sha") for w in written]})
    return {"outcome": "delivered", "notary": why}


def main(argv: list) -> int:
    if "--selftest" in argv:
        print("resolve_forward_rows.py --selftest")
        for p in sorted(fr.FORWARD_DIR.glob("F-*.json")):
            if p.name.count(".") == 1:
                row = json.loads(p.read_text(encoding="utf-8"))
                print(f"  {p.name}: schema {fr.schema_problems(row) or 'ok'}; "
                      f"status {fr.status(row['id'], p.parent / (row['id'] + '.resolutions.jsonl'))}; "
                      f"stage-1 version {stage_version(row, 'PROVISIONAL')}, "
                      f"stage-2 version {stage_version(row, 'FINAL')}")
        return 0
    client = UcdpClient()
    rc = 0
    for p in sorted(fr.FORWARD_DIR.glob("F-*.json")):
        if p.name.count(".") != 1:
            continue                          # seals and resolutions sit beside the rows
        out = resolve_row(p, client, publish="--publish" in argv)
        rc = max(rc, 3 if out["action"] == "ERROR" else 0)
    print(f"[R] UCDP requests this run: {client.requests}; today {client.uc.requests_today()} "
          f"of cap {client.uc.DAILY_CAP}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
