"""
experiments/institution/forward_witness.py — the MeTTa forward witness on a forward row
(task #9b, 25 Sep 2026; rules as Emil wrote them).

RF1 commitment_id exists in config/commitments.json and is confirmed.
RF2 registered > commitment date, and window_start > registered.
RF3 the window is one full calendar month; stage-1 resolve_by > window_end; the FINAL
    source is a coverage rule, not a version number.
RF4 the row's threshold equals the UCDP constant read from config/ucdp_constants.json
    (this code holds no literal threshold).
RF5 sha256(row bytes) == seal.row_sha256 == signature.row_sha256.
RF6 baselines (a) and (b), recomputed from the local UCDP release files named by the
    row's as_of, match the row.
RF7 (task #30, resolution mode only) resolution.filter == row.condition byte-for-byte:
    the canonical JSON bytes of the two are equal. A resolution mode run without a
    resolution cannot evaluate RF7 -> REFUSE.

The Python reference is the spec; hyperon (forward_witness_worker.py in venv312_metta)
is the second opinion, and engines_agree is recorded per rule. Rule: any rule not
evaluated - a missing input, an absent signature, a silent engine - is a REFUSE,
never "no contradiction". Output: memory/metta_forward_<row>.json.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FORWARD_DIR = HERE / "forward"
SIGNATURES = HERE / "signatures.jsonl"
COMMITMENTS = REPO / "config" / "commitments.json"
CONSTANTS = REPO / "config" / "ucdp_constants.json"
OUT_DIR = REPO / "memory"
WORKER = HERE / "forward_witness_worker.py"
SIDECAR_PY = REPO / "venv312_metta" / "Scripts" / "python.exe"
RULES = ("RF1", "RF2", "RF3", "RF4", "RF5", "RF6")
RESOLUTION_RULES = RULES + ("RF7",)


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def rf7_facts(row: dict, resolution: dict | None) -> dict | None:
    if not isinstance(resolution, dict) or "filter" not in resolution or "condition" not in row:
        return None
    return {"filter_sha256": hashlib.sha256(canonical(resolution["filter"])).hexdigest(),
            "condition_sha256": hashlib.sha256(canonical(row["condition"])).hexdigest()}
_THR = re.compile(r"\s*(<|>=)\s*(\d+(?:\.\d+)?)\s*")


def _d(s: str) -> int:
    return int(str(s)[:10].replace("-", ""))


def latest_signature(row_id: str, path: Path | None = None) -> dict | None:
    try:
        lines = Path(path or SIGNATURES).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    rows = [json.loads(l) for l in lines if l.strip()]
    rows = [r for r in rows if r.get("row_id") == row_id and r.get("signer") == "Emil"
            and r.get("channel") and r.get("date") and r.get("row_sha256")]
    return rows[-1] if rows else None


def _sources_upto(as_of: str):
    from core import ucdp_client as uc
    want = str(as_of).split(":", 1)[-1]
    out = []
    for name, url, kind in uc.SOURCES:
        ver = name[len("GEDEvent_v"):-len(".csv")].replace("_", ".")
        out.append((name, ver))
        if ver == want:
            return out
    return None


def recompute_baselines(row: dict, threshold: float, data_dir: Path | None = None) -> dict | None:
    from core import ucdp_client as uc
    b = row["baseline"]
    srcs = _sources_upto(b["as_of"])
    if srcs is None:
        return None
    ddir = Path(data_dir or uc.DATA_DIR)
    by_id = {}
    for name, _v in srcs:
        for r in uc._read_csv(ddir / name):
            by_id[r["id"]] = r
    c = row["condition"]
    from experiments.institution import forward_rows as fr
    sel = [r for r in by_id.values() if fr.matches(r, c)]
    a_lo, a_hi = [s.strip() for s in b["a_mean_monthly_best_pre_commitment"]["window"].split("..")]
    total = sum(float(r["best"]) for r in sel if a_lo <= r["date_start"][:10] <= a_hi)
    m = re.match(r"\s*(\d{4})-(\d{2})\s*\.\.\s*(\d{4})-(\d{2})", b["b_p_not_kept_post_commitment"]["window"])
    y, mo, y2, mo2 = map(int, m.groups())
    months = []
    while (y, mo) <= (y2, mo2):
        months.append(f"{y:04d}-{mo:02d}")
        mo += 1
        if mo == 13:
            y, mo = y + 1, 1
    sums = {k: 0.0 for k in months}
    for r in sel:
        k = r["date_start"][:7]
        if k in sums:
            sums[k] += float(r["best"])
    hits = sum(1 for k in months if sums[k] >= threshold)
    return {"as_of": b["as_of"], "total": int(round(total)), "mean_x100": int(round(total / 12 * 100)),
            "hits": hits, "months": len(months), "p_x10000": int(round(hits / len(months) * 10000))}


def facts_for(row_id: str, forward_dir: Path | None = None, signatures: Path | None = None,
              data_dir: Path | None = None) -> dict:
    """{rule: facts | None}. None = the rule cannot be evaluated (a missing input)."""
    fdir = Path(forward_dir or FORWARD_DIR)
    row_bytes = (fdir / f"{row_id}.json").read_bytes()
    row = json.loads(row_bytes.decode("utf-8"))
    f: dict = {}
    # RF1
    try:
        reg = json.loads(COMMITMENTS.read_text(encoding="utf-8"))
        hit = [c for c in reg["commitments"] if c["id"] == row["commitment"]["register_id"]]
        f["RF1"] = {"found": bool(hit),
                    "status_prefix": (str(hit[0].get("status", "")).split("_")[0] if hit else "")}
    except Exception:  # noqa: BLE001
        f["RF1"] = None
    # RF2
    c = row["condition"]
    try:
        f["RF2"] = {"registered": _d(row["registered"]), "commitment_date": _d(row["commitment"]["date"]),
                    "window_start": _d(c["date_start_from"])}
    except Exception:  # noqa: BLE001
        f["RF2"] = None
    # RF3
    try:
        ws, we = date.fromisoformat(c["date_start_from"]), date.fromisoformat(c["date_start_to"])
        r = row["resolution"]
        fsrc = str(r["final"]["source"])
        f["RF3"] = {"ws_y": ws.year, "ws_m": ws.month, "ws_d": ws.day, "we_y": we.year, "we_m": we.month,
                    "we_d": we.day, "days_in_month": calendar.monthrange(we.year, we.month)[1],
                    "window_end": _d(c["date_start_to"]),
                    "stage1_late_by": _d(r["provisional"]["source_late_if_no_release_by"]),
                    "stage1_rule_is_release_plus_14": r["provisional"]["resolve_by"] == "release date + 14 days",
                    "final_is_coverage_rule": ("coverage includes" in fsrc
                                               and not re.fullmatch(r"\s*(UCDP\s+)?GED\s+[\d.]+\s*", fsrc))}
    except Exception:  # noqa: BLE001
        f["RF3"] = None
    # RF4
    threshold = None
    try:
        threshold = json.loads(CONSTANTS.read_text(encoding="utf-8"))["battle_related_deaths_threshold"]
        k, n = _THR.fullmatch(c["kept_if"]), _THR.fullmatch(c["not_kept_if"])
        if k and n and k.group(1) == "<" and n.group(1) == ">=":
            f["RF4"] = {"row_kept_threshold": int(float(k.group(2))),
                        "row_not_kept_threshold": int(float(n.group(2))),
                        "config_threshold": int(threshold)}
        else:
            f["RF4"] = None
    except Exception:  # noqa: BLE001
        f["RF4"] = None
    # RF5
    sig = latest_signature(row_id, signatures)
    try:
        seal = json.loads((fdir / f"{row_id}.seal.json").read_text(encoding="utf-8"))
        f["RF5"] = ({"sha_file": hashlib.sha256(row_bytes).hexdigest(), "sha_seal": seal["row_sha256"],
                     "sha_signature": sig["row_sha256"]} if sig else None)
    except Exception:  # noqa: BLE001
        f["RF5"] = None
    # RF6
    try:
        rec = recompute_baselines(row, threshold, data_dir) if threshold is not None else None
        b = row["baseline"]
        a, bb = b["a_mean_monthly_best_pre_commitment"], b["b_p_not_kept_post_commitment"]
        f["RF6"] = None if rec is None else {
            "as_of_row": b["as_of"], "as_of_data": rec["as_of"],
            "total_row": int(a["total_best"]), "total_recomputed": rec["total"],
            "mean_x100_row": int(round(a["mean_per_month"] * 100)), "mean_x100_recomputed": rec["mean_x100"],
            "hits_row": int(bb["months_at_or_above_25"]), "hits_recomputed": rec["hits"],
            "months_row": int(bb["months"]), "months_recomputed": rec["months"],
            "p_x10000_row": int(round(bb["p_not_kept"] * 10000)), "p_x10000_recomputed": rec["p_x10000"]}
    except Exception:  # noqa: BLE001
        f["RF6"] = None
    return f


def python_reference(rule: str, f: dict) -> bool | None:
    if f is None:
        return None
    if rule == "RF1":
        return f["found"] is True and f["status_prefix"] == "confirmed"
    if rule == "RF2":
        return f["registered"] > f["commitment_date"] and f["window_start"] > f["registered"]
    if rule == "RF3":
        return (f["ws_d"] == 1 and f["ws_y"] == f["we_y"] and f["ws_m"] == f["we_m"]
                and f["we_d"] == f["days_in_month"] and f["stage1_late_by"] > f["window_end"]
                and f["stage1_rule_is_release_plus_14"] is True and f["final_is_coverage_rule"] is True)
    if rule == "RF4":
        return f["row_kept_threshold"] == f["config_threshold"] == f["row_not_kept_threshold"]
    if rule == "RF5":
        return f["sha_file"] == f["sha_seal"] == f["sha_signature"]
    if rule == "RF6":
        return all(f[k + "_row"] == f[k + ("_data" if k == "as_of" else "_recomputed")]
                   for k in ("as_of", "total", "mean_x100", "hits", "months", "p_x10000"))
    if rule == "RF7":
        return f["filter_sha256"] == f["condition_sha256"]
    raise KeyError(rule)


def hyperon(facts: dict, timeout: int = 120) -> dict:
    if not SIDECAR_PY.exists():
        return {"ok": False, "error": f"sidecar absent: {SIDECAR_PY}"}
    try:
        p = subprocess.run([str(SIDECAR_PY), str(WORKER)], input=json.dumps({"facts": facts}),
                           capture_output=True, text=True, timeout=timeout)
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def witness(row_id: str, write: bool = True, engine=hyperon, mode: str = "row",
            resolution: dict | None = None, **paths) -> dict:
    """mode "row": RF1-RF6. mode "resolution": RF1-RF7 on the row + that resolution."""
    fdir = Path(paths.get("forward_dir") or FORWARD_DIR)
    facts = facts_for(row_id, fdir, paths.get("signatures"), paths.get("data_dir"))
    rule_set = RULES
    if mode == "resolution":
        rule_set = RESOLUTION_RULES
        row = json.loads((fdir / f"{row_id}.json").read_text(encoding="utf-8"))
        facts["RF7"] = rf7_facts(row, resolution)
    eng = engine(facts)
    rules, contradictions, not_evaluated = {}, [], []
    for r in rule_set:
        py = python_reference(r, facts.get(r))
        hy = (eng.get("results") or {}).get(r, "not_evaluated") if eng.get("ok") else "not_evaluated"
        agree = (py is not None and hy != "not_evaluated" and py == hy)
        rules[r] = {"python": py, "hyperon": hy, "agree": agree, "facts": facts.get(r)}
        if py is None or hy == "not_evaluated":
            not_evaluated.append(r)
        elif py is False or hy is False:
            contradictions.append(r)
    engines_agree = all(v["agree"] for v in rules.values())
    verdict = "PASS" if not contradictions and not not_evaluated and engines_agree else "REFUSE"
    why = ("" if verdict == "PASS" else
           "; ".join(x for x in (f"not evaluated: {','.join(not_evaluated)}" if not_evaluated else "",
                                 f"contradicted: {','.join(contradictions)}" if contradictions else "",
                                 "engines disagree" if not engines_agree and not not_evaluated else "") if x))
    out = {"ts": datetime.now(timezone.utc).isoformat(), "row_id": row_id, "mode": mode,
           "row_sha256": hashlib.sha256((fdir / f"{row_id}.json").read_bytes()).hexdigest(),
           "rules": rules, "contradictions": contradictions, "not_evaluated": not_evaluated,
           "engines_agree": engines_agree,
           "hyperon": {"ok": bool(eng.get("ok")), "version": eng.get("hyperon_version"),
                       "error": eng.get("error"), "programs": eng.get("programs")},
           "verdict": verdict, "why": why}
    if write:
        suffix = "" if mode == "row" else ".resolution"
        p = Path(paths.get("out_dir") or OUT_DIR) / f"metta_forward_{row_id}{suffix}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(REPO))
    rid = sys.argv[sys.argv.index("--row") + 1] if "--row" in sys.argv else "F-001"
    res = witness(rid)
    print(json.dumps({k: res[k] for k in ("row_id", "row_sha256", "verdict", "why", "engines_agree",
                                          "contradictions", "not_evaluated")}, indent=2))
    for r, v in res["rules"].items():
        print(f"  {r}: python={v['python']} hyperon={v['hyperon']} agree={v['agree']}")
