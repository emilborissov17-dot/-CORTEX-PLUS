"""
experiments/institution/forward_rows.py — Institution 0 forward rows (task #9, 25 Sep 2026).

A forward row is registered BEFORE its window is observed: a condition in UCDP GED
terms, the releases that resolve it, and the dates by which they must. This module
holds the four things a row needs and nothing else:

  schema_problems(row)  the fields a row must carry, and the two rules that make it
                        resolvable: the window is exactly one calendar month, and
                        the FINAL source is a COVERAGE RULE ("the first UCDP GED
                        annual release whose coverage includes 2026-10"), never a
                        version number alone - GED 26.1 covers 1989-2025 and could
                        never hold the window;
  seal(path, ...)       sha256 over the exact bytes of the row file + the previous
                        Merkle root + the writer; verify() recomputes it;
  append_resolution()   one JSON line per resolution, opened "a" - there is no
                        rewrite path; status() is OPEN until a FINAL line exists;
  record_publish()      the publish ledger: delivered | deferred | suppressed.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORWARD_DIR = HERE / "forward"
PUBLISH_LEDGER = HERE / "publish_ledger.jsonl"

REQUIRED = ("id", "commitment", "registered", "registered_by", "liveness", "condition",
            "resolution", "baseline", "sentences", "citation", "lane", "retrospective")
CONDITION_KEYS = ("source", "type_of_violence", "dyad_name", "dyad_new_id", "adm_1",
                  "date_start_from", "date_start_to", "metric", "kept_if", "not_kept_if")
STAGES = ("PROVISIONAL", "FINAL")
OUTCOMES = ("KEPT", "NOT_KEPT", "SOURCE_LATE", "ASSUMPTION_BROKEN")
PUBLISH_OUTCOMES = ("delivered", "deferred", "suppressed")
_VERSION_ONLY = re.compile(r"\s*(UCDP\s+)?GED(\s+Candidate)?\s+\d+(\.\d+)*\s*", re.I)


def schema_problems(row: dict) -> list:
    """Every missing or malformed piece, named. [] means the row is well-formed."""
    out = []
    if not isinstance(row, dict):
        return ["row: not an object"]
    for k in REQUIRED:
        if k not in row:
            out.append(f"{k}: missing")
    c = row.get("condition") or {}
    for k in CONDITION_KEYS:
        if k not in c:
            out.append(f"condition.{k}: missing")
    try:
        lo = date.fromisoformat(c["date_start_from"])
        hi = date.fromisoformat(c["date_start_to"])
        if not (lo.day == 1 and (lo.year, lo.month) == (hi.year, hi.month)
                and hi.day == calendar.monthrange(hi.year, hi.month)[1]):
            out.append("condition window: not exactly one calendar month")
    except Exception as e:  # noqa: BLE001
        out.append(f"condition window: unreadable ({type(e).__name__})")
    r = row.get("resolution") or {}
    for stage in ("provisional", "final"):
        s = r.get(stage) or {}
        for k in ("source", "resolve_by", "source_late_if_no_release_by"):
            if not s.get(k):
                out.append(f"resolution.{stage}.{k}: missing")
        if "release date + 14 days" not in str(s.get("resolve_by", "")):
            out.append(f"resolution.{stage}.resolve_by: must be 'release date + 14 days'")
    fsrc = str((r.get("final") or {}).get("source", ""))
    if _VERSION_ONLY.fullmatch(fsrc) or "coverage includes" not in fsrc:
        out.append("resolution.final.source: must be a coverage rule, not a version number")
    if r.get("status") != "OPEN" and "resolution" in row:
        out.append("resolution.status: a registered row starts OPEN")
    if r.get("append_only") is not True:
        out.append("resolution.append_only: must be true")
    return out


def matches(ev: dict, condition: dict) -> bool:
    """One UCDP event against a row's condition - the ONE filter the resolver and the
    witness's RF6 share. adm_1 "ALL" means the whole of condition["country"]; "ALL"
    without a country is refused (ValueError), never read as "anywhere"."""
    if str(ev["type_of_violence"]) != str(condition["type_of_violence"]):
        return False
    if str(ev["dyad_new_id"]) != str(condition["dyad_new_id"]):
        return False
    adm = condition["adm_1"]
    if adm == "ALL":
        if not condition.get("country"):
            raise ValueError("adm_1 ALL needs condition.country")
        return ev["country"] == condition["country"]
    return ev["adm_1"] in set(adm)


def _digest(row_bytes: bytes, prev_root, writer) -> str:
    h = hashlib.sha256()
    h.update(b"row\0" + len(row_bytes).to_bytes(8, "big") + row_bytes)
    h.update(b"prev_root\0" + str(prev_root or "").encode("utf-8"))
    h.update(b"writer\0" + json.dumps(writer, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def seal(path: Path, prev_root, writer: dict) -> dict:
    b = Path(path).read_bytes()
    return {"root": _digest(b, prev_root, writer), "prev_root": prev_root, "writer": writer,
            "row_sha256": hashlib.sha256(b).hexdigest(), "row_bytes": len(b)}


def verify(path: Path, sealed: dict) -> dict:
    b = Path(path).read_bytes()
    got = _digest(b, sealed.get("prev_root"), sealed.get("writer"))
    if got != sealed.get("root"):
        return {"ok": False, "why": f"root {got[:16]} != sealed {str(sealed.get('root'))[:16]} "
                                    f"({len(b)} bytes vs {sealed.get('row_bytes')})"}
    return {"ok": True, "why": ""}


def append_resolution(log: Path, row_id: str, stage: str, outcome: str, as_of: str,
                      value: float, note: str = "") -> dict:
    if stage not in STAGES:
        raise ValueError(f"stage {stage!r} is not one of {STAGES}")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome {outcome!r} is not one of {OUTCOMES}")
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "row_id": row_id, "stage": stage,
           "outcome": outcome, "as_of": as_of, "value": value, "note": note}
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with Path(log).open("a", encoding="utf-8", newline="\n") as fh:     # sealed bytes: LF only
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def status(row_id: str, log: Path) -> str:
    try:
        lines = Path(log).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return "OPEN"
    finals = [json.loads(l) for l in lines if l.strip()]
    finals = [r for r in finals if r.get("row_id") == row_id and r.get("stage") == "FINAL"]
    return "RESOLVED" if finals else "OPEN"


def record_publish(row_id: str, outcome: str, reason: str, detail: dict | None = None,
                   ledger: Path | None = None) -> dict:
    if outcome not in PUBLISH_OUTCOMES:
        raise ValueError(f"publish outcome {outcome!r} is not one of {PUBLISH_OUTCOMES}")
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "row_id": row_id,
           "outcome": outcome, "reason": reason, **(detail or {})}
    p = Path(ledger or PUBLISH_LEDGER)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec
