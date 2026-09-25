#!/usr/bin/env python3
"""
experiments/institution/register_forward_row.py — seal, gate and publish one forward row.

    venv\\Scripts\\python.exe experiments/institution/register_forward_row.py --row F-001 --seal
    venv\\Scripts\\python.exe experiments/institution/register_forward_row.py --row F-001 --publish
    venv\\Scripts\\python.exe experiments/institution/register_forward_row.py --selftest

--seal     schema check, then a root over the exact bytes of forward/<row>.json + the
           previous root + the writer (merkle_memory.writer_identity), appended to
           memory/merkle_roots.jsonl and checked with verify_root_chain(); the seal is
           kept beside the row as forward/<row>.seal.json.
--publish  core.notary.may_act("github_publish") first. A refusal is recorded as
           `suppressed` with the notary's words and the run stops - there is no
           bypass. Otherwise institution0/<row>.json (seal + row) and
           institution0/INSTITUTION_0.md go through github_publisher; `delivered` with
           the commit shas, or `deferred` with the error.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from experiments.institution import forward_rows as fr  # noqa: E402

ROOTS_LOG = REPO / "memory" / "merkle_roots.jsonl"
STATE = REPO / "cortex_memory" / "state.json"


def _prev_root() -> str | None:
    try:
        lines = [l for l in ROOTS_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            return json.loads(lines[-1])["root"]
    except FileNotFoundError:
        pass
    try:
        return json.loads(STATE.read_text(encoding="utf-8")).get("merkle_root")
    except Exception:  # noqa: BLE001
        return None


def seal_row(row_id: str) -> dict:
    import merkle_memory as mm
    path = fr.FORWARD_DIR / f"{row_id}.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    problems = fr.schema_problems(row)
    if problems:
        raise SystemExit(f"[F] {row_id}: schema refused: {problems}")
    prev = _prev_root()
    s = fr.seal(path, prev, mm.writer_identity())
    s.update({"row_id": row_id, "file": path.relative_to(REPO).as_posix(),
              "ts": datetime.now(timezone.utc).isoformat()})
    ROOTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ROOTS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"root": s["root"], "ts": s["ts"], "cycle_id": f"institution0:{row_id}",
                             "kind": "institution0_forward_row", "file": s["file"],
                             "row_sha256": s["row_sha256"], "leaf_count": 1,
                             "prev_root": prev, "writer": s["writer"]}, ensure_ascii=False) + "\n")
    (fr.FORWARD_DIR / f"{row_id}.seal.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    v = fr.verify(path, s)
    chain = mm.verify_root_chain(ROOTS_LOG)
    print(f"[F] {row_id}: root {s['root']} prev {prev} verify={v['ok']} chain={chain}")
    return s


def page(row: dict, s: dict) -> str:
    c, r, b = row["condition"], row["resolution"], row["baseline"]
    lines = [
        "# Institution 0 — forward rows", "",
        *[f"> {t}" for t in row["sentences"]], "",
        f"## {row['id']} — {row['commitment']['title']} ({row['commitment']['date']})", "",
        f"Registered {row['registered']} by {row['registered_by']}. Liveness: {row['liveness']}.",
        f"Lane I-1: {row['lane']['I-1']}.", "",
        "**Condition (UCDP GED).** "
        f"type_of_violence = {c['type_of_violence']} ({c['type_of_violence_means']}); "
        f"dyad \"{c['dyad_name']}\" (dyad_new_id {c['dyad_new_id']}); "
        f"adm_1 in {', '.join(repr(a) for a in c['adm_1'])}; "
        f"date_start {c['date_start_from']} .. {c['date_start_to']}; metric {c['metric']}; "
        f"KEPT if {c['kept_if']}, NOT KEPT if {c['not_kept_if']}.", "",
        "**Resolution.** Appended, never overwritten; OPEN until FINAL.",
        f"- PROVISIONAL: {r['provisional']['source']} (expected {r['provisional']['expected']}); "
        f"resolve by {r['provisional']['resolve_by']}; SOURCE_LATE if no release by "
        f"{r['provisional']['source_late_if_no_release_by']}.",
        f"- FINAL: {r['final']['source']} ({r['final']['expected']}); resolve by "
        f"{r['final']['resolve_by']}; SOURCE_LATE if no such release by "
        f"{r['final']['source_late_if_no_release_by']}.", "",
        f"**Baseline (as_of {b['as_of']}).** Pre-commitment {b['a_mean_monthly_best_pre_commitment']['window']}: "
        f"mean {b['a_mean_monthly_best_pre_commitment']['mean_per_month']} fatalities/month "
        f"({b['a_mean_monthly_best_pre_commitment']['note']}). Post-commitment "
        f"{b['b_p_not_kept_post_commitment']['window']}: "
        f"{b['b_p_not_kept_post_commitment']['months_at_or_above_25']} of "
        f"{b['b_p_not_kept_post_commitment']['months']} months at or above 25 -> p_not_kept = "
        f"{b['b_p_not_kept_post_commitment']['p_not_kept']}.", "",
        "## Retrospective rows (method validation, as_of ucdp:26.0.8)", "",
        row["retrospective"]["method"], "",
        "| commitment | party | events | months with event | civilian deaths | verdict |",
        "|---|---|---:|---:|---:|---|",
        *[f"| {x['commitment']} | {x['party']} | {x['events']} | {x['months_with_event']} | "
          f"{x['civilian_deaths']} | {x['verdict']}{' (' + x['label'] + ')' if x.get('label') else ''} |"
          for x in row["retrospective"]["rows"]], "",
        "## Seal", "",
        f"Merkle root `{s['root']}` over the exact bytes of `{s['file']}` "
        f"(sha256 `{s['row_sha256']}`, {s['row_bytes']} bytes) + previous root "
        f"`{s['prev_root']}` + writer {json.dumps(s['writer'])}.", "",
        "## Citation", "",
        f"- Provisional source: {row['citation']['provisional_source']}",
        f"- Final source: {row['citation']['final_source']}", "",
    ]
    return "\n".join(lines)


def publish(row_id: str) -> int:
    path = fr.FORWARD_DIR / f"{row_id}.json"
    s = json.loads((fr.FORWARD_DIR / f"{row_id}.seal.json").read_text(encoding="utf-8"))
    v = fr.verify(path, s)
    if not v["ok"]:
        fr.record_publish(row_id, "suppressed", f"seal does not verify: {v['why']}")
        print(f"[F] {row_id}: SUPPRESSED - seal does not verify: {v['why']}")
        return 3
    from core.notary import may_act
    ok, why = may_act("github_publish")
    if not ok:
        fr.record_publish(row_id, "suppressed", f"notary.may_act refused: {why}",
                          {"root": s["root"]})
        print(f"[F] {row_id}: SUPPRESSED by the notary - {why}")
        return 3
    row = json.loads(path.read_text(encoding="utf-8"))
    files = {f"institution0/{row_id}.json": json.dumps({"seal": s, "row": row}, ensure_ascii=False, indent=2) + "\n",
             "institution0/INSTITUTION_0.md": page(row, s)}
    try:
        import github_publisher as gp
        written = gp.publish_institution0(files, f"institution0: register forward row {row_id} (root {s['root'][:12]})")
    except Exception as e:  # noqa: BLE001
        fr.record_publish(row_id, "deferred", f"{type(e).__name__}: {e}", {"root": s["root"], "notary": why})
        print(f"[F] {row_id}: DEFERRED - {type(e).__name__}: {e}")
        return 4
    fr.record_publish(row_id, "delivered", "published", {
        "root": s["root"], "notary": why,
        "files": [w.get("path") for w in written], "commit_shas": [w.get("commit_sha") for w in written]})
    for w in written:
        print(f"[F] {row_id}: delivered {w.get('path')} commit {w.get('commit_sha')} HTTP {w.get('status')}")
    return 0


def selftest() -> int:
    print("register_forward_row.py --selftest")
    for name in ("F-001",):
        p = fr.FORWARD_DIR / f"{name}.json"
        if not p.exists():
            print(f"  INERT  {p} absent"); continue
        print(f"  LIVE   {p.relative_to(REPO)} schema problems: {fr.schema_problems(json.loads(p.read_text(encoding='utf-8')))}")
        sp = fr.FORWARD_DIR / f"{name}.seal.json"
        print(f"  {'LIVE ' if sp.exists() else 'INERT'}  seal {sp.relative_to(REPO)}"
              + (f" verify={fr.verify(p, json.loads(sp.read_text(encoding='utf-8')))}" if sp.exists() else ""))
    for mod in ("merkle_memory", "github_publisher", "core.notary"):
        try:
            __import__(mod); print(f"  LIVE   {mod}")
        except Exception as e:  # noqa: BLE001
            print(f"  INERT  {mod} ({type(e).__name__}: {e})")
    return 0


def main(argv: list) -> int:
    if "--selftest" in argv:
        return selftest()
    row_id = argv[argv.index("--row") + 1] if "--row" in argv else None
    if not row_id:
        print("[F] refusing: no --row"); return 2
    if "--seal" in argv:
        seal_row(row_id)
    if "--publish" in argv:
        return publish(row_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
