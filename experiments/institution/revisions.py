#!/usr/bin/env python3
"""
experiments/institution/revisions.py — append-only revisions beside a forward row
(C4 B, 26 Sep 2026; Emil's instruction, Kimi R61).

A registered row's bytes never change: its seal, its signature and RF5 all hash
them. A revision is one JSON line appended to forward/<row>.revisions.jsonl, dated
before the window opens (2026-10-01), keeping the original beside the restated
value. The file is sealed like a resolutions file (root over its bytes + previous
Merkle root + writer, appended to memory/merkle_roots.jsonl).

TWO KINDS, AND WHO MUST SIGN (Emil):
  restatement      a baseline restated or a label added - publishes without a
                   signature;
  semantics        changes how the row resolves (F-002's assumption and its
                   ASSUMPTION_BROKEN outcome) - Emil signs the revision hash;
  signed_wording   changes wording Emil signed (the dignity sentence) - Emil signs.
A revision written before kinds existed (F-001 r1, addressee, 25 Sep) needs a
signature only if its field is a key of the signed row.

A revision that needs a signature is NOT IN FORCE until Emil replies
"SIGN <row> R<n> <revision_sha256>" (experiments/needs/approve_reader.apply_signature);
until then the page says "pending" and the resolver ignores it.

    venv\\Scripts\\python.exe experiments/institution/revisions.py --plan        # compute, print, write nothing
    venv\\Scripts\\python.exe experiments/institution/revisions.py --apply-c4b   # append the C4 B revisions (idempotent)
    venv\\Scripts\\python.exe experiments/institution/revisions.py --seal F-001
    venv\\Scripts\\python.exe experiments/institution/revisions.py --request-signatures
    venv\\Scripts\\python.exe experiments/institution/revisions.py --publish-ready
    venv\\Scripts\\python.exe experiments/institution/revisions.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FORWARD_DIR = HERE / "forward"
SIGNATURES = HERE / "signatures.jsonl"
CONSTANTS = REPO / "config" / "ucdp_constants.json"
ROWS = ("F-001", "F-002", "F-003", "F-004")

EXEMPT_KINDS = ("restatement",)
SIGNED_KINDS = ("semantics", "signed_wording")
KINDS = EXEMPT_KINDS + SIGNED_KINDS
ASSUMPTION_BROKEN = "ASSUMPTION_BROKEN"

DIGNITY_SENTENCE = (
    "A death recorded here is one breach of one specific, signed, pre-registered commitment "
    "— row, dyad, threshold, and source all named before the fact. We count breaches because "
    "dignity admits no score; the count is evidence against the commitment, never a measure "
    "of dignity, and changing the count by changing row, dyad, threshold, or source — without "
    "re-registering — is itself a violation.")

# F-002 only: the months before UCDP's SFA string existed are not the successor
# regime (the row's own note: "The 20 zero months 2023-06..2025-01 are before the
# SFA string existed").
SUCCESSOR_SINCE = {"F-002": "2025-02"}

F002_ASSUMPTION = {
    "risk": "SFA = successor of RSF (Emil, not UCDP)",
    "outcome_if_broken": ASSUMPTION_BROKEN,
    "broken_if": ("UCDP codes state-based events in the window with side_a 'Government of Sudan' "
                  "to a dyad other than the registered one whose side_b names RSF or SFA"),
    "registered_dyad_new_id": 18621,
    "side_a": "Government of Sudan",
    "side_b_patterns": ["RSF", "SFA"],
    "country": "Sudan",
    "country_gwno": 625,
}


class RevisionRefused(ValueError):
    """A revision that may not be written. Nothing was appended."""


# ── reading ──────────────────────────────────────────────────────────────────

def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def rev_hash(rev: dict) -> str:
    return hashlib.sha256(canonical(rev)).hexdigest()


def log_path(row_id: str, forward_dir: Path | None = None) -> Path:
    return Path(forward_dir or FORWARD_DIR) / f"{row_id}.revisions.jsonl"


def load(row_id: str, forward_dir: Path | None = None) -> list:
    try:
        text = log_path(row_id, forward_dir).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def row_of(row_id: str, forward_dir: Path | None = None) -> dict:
    return json.loads((Path(forward_dir or FORWARD_DIR) / f"{row_id}.json").read_text(encoding="utf-8"))


def needs_signature(rev: dict, row: dict) -> bool:
    kind = rev.get("kind")
    if kind is not None:
        return kind not in EXEMPT_KINDS          # an unknown kind is signed, not waved through
    return str(rev.get("field", "")).split(".", 1)[0].split("[", 1)[0] in row


def signature_for(row_id: str, rev: dict, signatures: Path | None = None) -> dict | None:
    try:
        lines = Path(signatures or SIGNATURES).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    want = rev_hash(rev)
    for line in reversed(lines):
        if not line.strip():
            continue
        s = json.loads(line)
        if (s.get("row_id") == row_id and s.get("signer") == "Emil" and s.get("channel")
                and s.get("date") and s.get("revision") == rev.get("revision")
                and s.get("revision_sha256") == want):
            return s
    return None


def pending(row_id: str, forward_dir: Path | None = None, signatures: Path | None = None) -> list:
    row = row_of(row_id, forward_dir)
    return [r for r in load(row_id, forward_dir)
            if needs_signature(r, row) and not signature_for(row_id, r, signatures)]


def in_force(row_id: str, forward_dir: Path | None = None, signatures: Path | None = None) -> list:
    row = row_of(row_id, forward_dir)
    return [r for r in load(row_id, forward_dir)
            if not needs_signature(r, row) or signature_for(row_id, r, signatures)]


def assumption(row_id: str, forward_dir: Path | None = None, signatures: Path | None = None) -> dict | None:
    """The in-force assumption of a row (signed), or None. The resolver and RF7 read
    this, never the unsigned line."""
    got = [r["value"] for r in in_force(row_id, forward_dir, signatures) if r.get("field") == "assumption"]
    return got[-1] if got else None


# ── arithmetic ───────────────────────────────────────────────────────────────

def laplace(k: int, n: int) -> float:
    """(k+1)/(n+2): the rule of succession. Never 0 or 1 on finite data."""
    if n < 0 or not 0 <= k <= n:
        raise ValueError(f"k={k}, n={n}")
    return (k + 1) / (n + 2)


def months_count(by_month: dict, threshold: float, since: str | None = None) -> tuple[int, int]:
    months = sorted(m for m in by_month if since is None or m >= since)
    return sum(1 for m in months if float(by_month[m]) >= threshold), len(months)


def threshold() -> float:
    return float(json.loads(CONSTANTS.read_text(encoding="utf-8"))["battle_related_deaths_threshold"])


def baseline_restatement(row: dict, thr: float) -> dict:
    b = row["baseline"]["b_p_not_kept_post_commitment"]
    since = SUCCESSOR_SINCE.get(row["id"])
    k, n = months_count(b["by_month"], thr, since)
    months = sorted(m for m in b["by_month"] if since is None or m >= since)
    if since is None and (k, n) != (b["months_at_or_above_25"], b["months"]):
        raise RevisionRefused(f"{row['id']}: recount {k}/{n} != the row's "
                              f"{b['months_at_or_above_25']}/{b['months']}")
    return {"kind": "restatement", "field": "baseline.b_p_not_kept_post_commitment",
            "value": {"rule": "(k+1)/(n+2)", "k": k, "n": n, "p_not_kept_laplace": round(laplace(k, n), 4),
                      "window": f"{months[0]} .. {months[-1]}", "threshold": thr,
                      **({"regime": f"successor only, from {since} (SFA coded from then)"} if since else {})},
            "original": {k2: b[k2] for k2 in ("window", "months_at_or_above_25", "months", "p_not_kept")},
            "note": "baseline_b restated with Laplace; the original is kept; the row's bytes are unchanged"}


def c4b_revisions(row: dict, thr: float) -> list:
    out = [baseline_restatement(row, thr)]
    if row["id"] == "F-004":
        out.append({"kind": "restatement", "field": "label", "value": "SENTINEL",
                    "original": row.get("label"),
                    "note": "every month of both baselines is above the threshold; the row is a sentinel, "
                            "and INSTITUTION_0.md reports the hit rate with and without it"})
    if row["id"] == "F-002":
        out.append({"kind": "semantics", "field": "assumption", "value": F002_ASSUMPTION,
                    "original": None,
                    "note": f"new outcome {ASSUMPTION_BROKEN} if the October 2026 events are coded to a "
                            f"different dyad"})
    out.append({"kind": "signed_wording", "field": "sentences[1]", "value": DIGNITY_SENTENCE,
                "original": row["sentences"][1], "note": "the dignity sentence, replaced"})
    return out


# ── writing ──────────────────────────────────────────────────────────────────

def append(row_id: str, rev: dict, forward_dir: Path | None = None, today: date | None = None) -> dict:
    """Append one revision, or raise RevisionRefused and write nothing."""
    fdir = Path(forward_dir or FORWARD_DIR)
    row_file = fdir / f"{row_id}.json"
    before = hashlib.sha256(row_file.read_bytes()).hexdigest()
    row = json.loads(row_file.read_bytes().decode("utf-8"))
    if rev.get("kind") not in KINDS:
        raise RevisionRefused(f"kind {rev.get('kind')!r} is not one of {KINDS}")
    day = (today or datetime.now().astimezone().date()).isoformat()
    if day >= row["condition"]["date_start_from"]:
        raise RevisionRefused(f"{row_id}: a revision dated {day} is not before the window "
                              f"{row['condition']['date_start_from']}")
    existing = load(row_id, fdir)
    for e in existing:
        if e.get("field") == rev.get("field") and canonical(e.get("value")) == canonical(rev.get("value")):
            raise RevisionRefused(f"{row_id}: revision r{e.get('revision')} already says this")
    rec = {"row_id": row_id, "revision": len(existing) + 1, "date": day, **rev}
    with log_path(row_id, fdir).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if hashlib.sha256(row_file.read_bytes()).hexdigest() != before:
        raise RuntimeError(f"{row_id}: the row's bytes changed while a revision was appended")
    return rec


def seal(row_id: str, forward_dir: Path | None = None, roots_log: Path | None = None) -> dict:
    from experiments.institution import resolve_forward_rows as rr
    return rr.seal_resolutions(log_path(row_id, forward_dir), roots_log, kind="institution0_revision")


def apply_c4b(forward_dir: Path | None = None, today: date | None = None,
              kinds: tuple | None = None) -> dict:
    """Append every C4 B revision not already on file; returns {row: [appended]}.
    kinds=("restatement",) appends only what publishes without a signature, so the
    published file never carries an unsigned change."""
    thr = threshold()
    out = {}
    for rid in ROWS:
        row = row_of(rid, forward_dir)
        added = []
        for rev in c4b_revisions(row, thr):
            if kinds is not None and rev["kind"] not in kinds:
                continue
            try:
                added.append(append(rid, rev, forward_dir, today))
            except RevisionRefused as e:
                if "already says this" not in str(e):
                    raise
        out[rid] = added
    return out


# ── signatures and publishing ────────────────────────────────────────────────

def sign_request(row_id: str, forward_dir: Path | None = None, signatures: Path | None = None) -> str:
    """ONE Telegram message per row: every revision still waiting for Emil, its hash,
    and the exact reply. Returns alarm_human's status; "nothing pending" if none."""
    waiting = pending(row_id, forward_dir, signatures)
    if not waiting:
        return "nothing pending"
    lines = [f"{row_id}: {len(waiting)} revision(s) change what you signed. Each is in force only "
             f"after your reply. The row's bytes are unchanged."]
    for r in waiting:
        shown = r["value"] if isinstance(r["value"], str) else json.dumps(r["value"], ensure_ascii=False)
        lines += ["", f"R{r['revision']} [{r['kind']}] {r['field']}:", shown[:900],
                  f"revision_sha256: {rev_hash(r)}", "Reply exactly:",
                  f"SIGN {row_id} R{r['revision']} {rev_hash(r)}"]
    import supervisor
    return supervisor.alarm_human(f"SIGN REQUEST {row_id} revisions", "\n".join(lines),
                                  dedup_key="sign-rev:" + ",".join(rev_hash(r)[:16] for r in waiting),
                                  trigger="MANUAL", level=supervisor.NOTICE, cls="sign_request")


def _delivered_roots(row_id: str) -> set:
    from experiments.institution import forward_rows as fr
    try:
        lines = Path(fr.PUBLISH_LEDGER).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return set()
    return {json.loads(l).get("revisions_root") for l in lines if l.strip()
            and json.loads(l).get("row_id") == row_id and json.loads(l).get("outcome") == "delivered"}


def publish(row_id: str, forward_dir: Path | None = None) -> dict:
    """The revisions file, its seal and the updated INSTITUTION_0.md, through
    notary.may_act (class human_signed_preregistration, revision form)."""
    from experiments.institution import forward_rows as fr
    from experiments.institution import register_forward_row as reg
    fdir = Path(forward_dir or FORWARD_DIR)
    log = log_path(row_id, fdir)
    sealp = fdir / f"{row_id}.revisions.seal.json"
    s = json.loads(sealp.read_text(encoding="utf-8"))
    row_root = json.loads((fdir / f"{row_id}.seal.json").read_text(encoding="utf-8"))["root"]
    from core.notary import may_act
    ok, why = may_act("github_publish", row_root, target=log)
    if not ok:
        fr.record_publish(row_id, "suppressed", f"notary.may_act refused the revisions: {why}",
                          {"revisions_root": s["root"]})
        return {"outcome": "suppressed", "why": why}
    files = {f"institution0/{log.name}": log.read_text(encoding="utf-8"),
             f"institution0/{sealp.name}": sealp.read_text(encoding="utf-8"),
             "institution0/INSTITUTION_0.md": reg.page_all()}
    try:
        import github_publisher as gp
        written = gp.publish_institution0(files, f"institution0: revisions of {row_id} (root {s['root'][:12]})")
    except Exception as e:  # noqa: BLE001
        fr.record_publish(row_id, "deferred", f"{type(e).__name__}: {e}", {"revisions_root": s["root"]})
        return {"outcome": "deferred", "why": f"{type(e).__name__}: {e}"}
    fr.record_publish(row_id, "delivered", "revisions published", {
        "revisions_root": s["root"], "notary": why, "files": [w.get("path") for w in written],
        "commit_shas": [w.get("commit_sha") for w in written]})
    return {"outcome": "delivered", "notary": why, "commits": [w.get("commit_sha") for w in written]}


def publish_if_ready(row_id: str, forward_dir: Path | None = None) -> dict:
    """Publish when nothing is pending and this sealed state was not delivered yet.
    The dispatcher calls it when a revision signature lands."""
    fdir = Path(forward_dir or FORWARD_DIR)
    if not log_path(row_id, fdir).exists():
        return {"outcome": "none", "why": "no revisions"}
    waiting = pending(row_id, fdir)
    if waiting:
        return {"outcome": "waiting", "why": "unsigned: " + ", ".join(f"R{r['revision']}" for r in waiting)}
    sealp = fdir / f"{row_id}.revisions.seal.json"
    if not sealp.exists():
        return {"outcome": "waiting", "why": "not sealed"}
    if json.loads(sealp.read_text(encoding="utf-8"))["root"] in _delivered_roots(row_id):
        return {"outcome": "already", "why": "this sealed state was delivered"}
    return publish(row_id, fdir)


# ── the page ─────────────────────────────────────────────────────────────────

def hit_rate(rows: list, forward_dir: Path | None = None, exclude_label: str | None = None) -> tuple:
    """(hits, resolved). A hit: the baseline's call - NOT_KEPT if its Laplace
    p_not_kept >= 0.5, else KEPT - equals the newest KEPT/NOT_KEPT resolution."""
    fdir = Path(forward_dir or FORWARD_DIR)
    hits = resolved = 0
    for row in rows:
        forced = in_force(row["id"], fdir)
        label = next((r["value"] for r in reversed(forced) if r.get("field") == "label"), row.get("label"))
        if exclude_label and label == exclude_label:
            continue
        try:
            res = [json.loads(l) for l in (fdir / f"{row['id']}.resolutions.jsonl").read_text(
                encoding="utf-8").splitlines() if l.strip()]
        except FileNotFoundError:
            res = []
        res = [r for r in res if r.get("verdict") in ("KEPT", "NOT_KEPT")]
        if not res:
            continue
        lap = next((r["value"]["p_not_kept_laplace"] for r in reversed(forced)
                    if r.get("field") == "baseline.b_p_not_kept_post_commitment"), None)
        p = lap if lap is not None else row["baseline"]["b_p_not_kept_post_commitment"]["p_not_kept"]
        call = "NOT_KEPT" if p >= 0.5 else "KEPT"
        resolved += 1
        hits += int(call == res[-1]["verdict"])
    return hits, resolved


def page_lines(row: dict, forward_dir: Path | None = None) -> list:
    """The revisions part of one row's section on INSTITUTION_0.md."""
    revs = load(row["id"], forward_dir)
    if not revs:
        return []
    out = ["**Revisions** (append-only, beside the row; the row's bytes are unchanged).", ""]
    for r in revs:
        signed = (not needs_signature(r, row)) or signature_for(row["id"], r) is not None
        state = ("in force" if not needs_signature(r, row) else
                 "in force, signed by Emil" if signed else "PENDING Emil's signature - not in force")
        v = r["value"]
        if r.get("field") == "baseline.b_p_not_kept_post_commitment":
            o = r["original"]
            shown = (f"p_not_kept restated with Laplace {v['rule']} = ({v['k']}+1)/({v['n']}+2) = "
                     f"{v['p_not_kept_laplace']} over {v['window']}"
                     + (f", {v['regime']}" if v.get("regime") else "")
                     + f"; original {o['p_not_kept']} ({o['months_at_or_above_25']}/{o['months']}, {o['window']}) kept")
        elif isinstance(v, str):
            shown = f"{r['field']} = {v}"
        else:
            shown = f"{r['field']} = " + json.dumps(v, ensure_ascii=False)
        out.append(f"- R{r['revision']} ({r['date']}, {r.get('kind', 'unclassified')}, {state}; "
                   f"sha256 `{rev_hash(r)[:16]}`): {shown}")
    return out + [""]


def effective_sentences(row: dict, forward_dir: Path | None = None) -> list:
    s = list(row["sentences"])
    for r in in_force(row["id"], forward_dir):
        if r.get("field") == "sentences[1]":
            s[1] = r["value"]
    return s


# ── CLI ──────────────────────────────────────────────────────────────────────

def plan() -> None:
    thr = threshold()
    print(f"threshold (config/ucdp_constants.json) = {thr:g}")
    for rid in ROWS:
        row = row_of(rid)
        for rev in c4b_revisions(row, thr):
            if rev["field"].startswith("baseline"):
                v, o = rev["value"], rev["original"]
                print(f"  {rid}: Laplace ({v['k']}+1)/({v['n']}+2) = {v['p_not_kept_laplace']} over {v['window']}"
                      f"{' [' + v['regime'] + ']' if v.get('regime') else ''}  (original {o['p_not_kept']}"
                      f" = {o['months_at_or_above_25']}/{o['months']} over {o['window']})")
            else:
                print(f"  {rid}: {rev['kind']:<15} {rev['field']}"
                      f"{' -> SIGN' if needs_signature(rev, row) else ''}")


def selftest() -> int:
    print("revisions.py --selftest")
    ok = laplace(10, 13) == 11 / 15 and months_count({"a": 30, "b": 1}, 25) == (1, 2)
    print(f"  {'OK  ' if ok else 'FAIL'}  laplace and month count")
    for rid in ROWS:
        p = log_path(rid)
        print(f"  {'LIVE ' if p.exists() else 'INERT'}  {p.relative_to(REPO)}: {len(load(rid))} revision(s), "
              f"{len(pending(rid)) if p.exists() else 0} pending signature")
    for mod in ("merkle_memory", "github_publisher", "core.notary", "supervisor"):
        try:
            __import__(mod)
            print(f"  LIVE   {mod}")
        except Exception as e:  # noqa: BLE001
            print(f"  INERT  {mod} ({type(e).__name__}: {e})")
    return 0 if ok else 1


def main(argv: list) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--plan" in argv:
        plan()
        return 0
    if "--apply-c4b" in argv:
        only = EXEMPT_KINDS if "--restatements-only" in argv else None
        for rid, added in apply_c4b(kinds=only).items():
            print(f"  {rid}: appended {[f'R{r['revision']} {r['field']}' for r in added]}")
        return 0
    if "--seal" in argv:
        rid = argv[argv.index("--seal") + 1]
        s = seal(rid)
        print(f"  {rid}: revisions root {s['root']} prev {s['prev_root']}")
        return 0
    if "--request-signatures" in argv:
        for rid in ROWS:
            print(f"  {rid}: {sign_request(rid)}")
        return 0
    if "--seal-all" in argv:
        for rid in ROWS:
            if log_path(rid).exists():
                s = seal(rid)
                print(f"  {rid}: revisions root {s['root']} prev {s['prev_root']}")
        return 0
    if "--publish-ready" in argv:
        for rid in ROWS:
            print(f"  {rid}: {publish_if_ready(rid)}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
