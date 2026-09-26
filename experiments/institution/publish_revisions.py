#!/usr/bin/env python3
"""
experiments/institution/publish_revisions.py — the actions on Institution 0 revisions:
Emil's SIGN request per row (Telegram, class sign_request) and publishing through
notary.may_act (revision form) when nothing is pending. Split from revisions.py
(C4 B, 26 Sep 2026) so the passage gate that reads revisions.py never imports
the supervisor or the publisher.

    venv\\Scripts\\python.exe experiments/institution/publish_revisions.py --request-signatures
    venv\\Scripts\\python.exe experiments/institution/publish_revisions.py --publish-ready
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.institution.revisions import (  # noqa: E402
    FORWARD_DIR, ROWS, log_path, pending, rev_hash)


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
    files = {f"institution0/{log.name}": log.read_bytes().decode("utf-8"),   # the sealed bytes, exactly
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


def main(argv: list) -> int:
    if "--request-signatures" in argv:
        for rid in ROWS:
            print(f"  {rid}: {sign_request(rid)}")
        return 0
    if "--publish-ready" in argv:
        for rid in ROWS:
            print(f"  {rid}: {publish_if_ready(rid)}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
