#!/usr/bin/env python3
"""
experiments/institution/deliver.py - the one Institution 0 push, and its verdict.

Kept OUT of forward_rows.py (27 Sep 2026): forward_rows is read by the passage gate
(core.prereg_gate), and this module imports supervisor, whose import graph reaches
the LLM door. test_llm_text keeps core.notary off that path.

    venv/Scripts/python.exe experiments/institution/deliver.py --selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from experiments.institution import forward_rows as fr  # noqa: E402


def deliver(row_id: str, files: dict, message: str, expected: dict | None = None,
            detail: dict | None = None, reason: str = "published", ledger: Path | None = None) -> dict:
    """The one Institution 0 push: github_publisher.publish_institution0, which reads
    every file back and hashes it. Returns the ledger row it wrote:
      delivered - every file read back hashes to its seal (or to the bytes sent);
      failed    - pushed, but a read-back does not verify; an alarm-class alarm goes
                  to the human and the row is never counted as delivered;
      deferred  - the push itself (or the local pre-check) raised."""
    detail = dict(detail or {})
    import github_publisher as gp
    try:
        written = gp.publish_institution0(files, message, expected=expected)
    except gp.PublishMismatch as e:
        import supervisor
        lines = [f"{m['path']}: {m['why']}" for m in e.mismatches]
        alarm = supervisor.alarm_human(f"INSTITUTION 0 PUBLISH FAILED {row_id}",
                                       "Published bytes do not verify against their seal:\n" + "\n".join(lines),
                                       dedup_key=f"i0_publish_failed:{row_id}:{message}", cls="alarm")
        return fr.record_publish(row_id, "failed", "published bytes do not verify: " + "; ".join(lines), {
            **detail, "mismatches": e.mismatches, "alarm": alarm,
            "files": [w.get("path") for w in e.written],
            "commit_shas": [w.get("commit_sha") for w in e.written]}, ledger=ledger)
    except Exception as e:  # noqa: BLE001
        return fr.record_publish(row_id, "deferred", f"{type(e).__name__}: {e}", detail, ledger=ledger)
    return fr.record_publish(row_id, "delivered", reason, {
        **detail, "files": [w.get("path") for w in written],
        "commit_shas": [w.get("commit_sha") for w in written],
        "fetched_sha256": {w["path"]: w.get("fetched_sha256") for w in written}}, ledger=ledger)


def selftest() -> int:
    print("deliver.py --selftest")
    for mod in ("github_publisher", "supervisor"):
        try:
            m = __import__(mod)
            print(f"  LIVE   {mod}")
        except Exception as e:  # noqa: BLE001
            print(f"  INERT  {mod} ({type(e).__name__}: {e})")
            continue
        if mod == "github_publisher":
            for name in ("publish_institution0", "verify_published", "PublishMismatch"):
                print(f"  {'LIVE ' if hasattr(m, name) else 'INERT'}  github_publisher.{name}")
    print(f"  {'LIVE ' if 'failed' in fr.PUBLISH_OUTCOMES else 'INERT'}  ledger outcome 'failed' in {fr.PUBLISH_OUTCOMES}")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else 2)
