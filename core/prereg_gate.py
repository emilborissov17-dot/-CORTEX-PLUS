"""
core/prereg_gate.py — the passage class `human_signed_preregistration` (task #9b, 25 Sep 2026).

Ratified by Emil in chat on 2026-09-25, read from config/passage_rules.json
"classes". It lets ONE step (github_publish) on ONE kind of target
(experiments/institution/forward/*) reach level_2 when all five checks hold:

  signature    a row in experiments/institution/signatures.jsonl: signer=Emil, channel,
               date, row_sha256 == sha256 of the row file's bytes;
  seal         the seal verifies, the Merkle root chain verifies (ok=True), and
               seal.row_sha256 == signature.row_sha256;
  prev_step    declared explicitly (PREV_NONE allowed for the first row);
  metta        the MeTTa forward witness evaluated RF1-RF6 with 0 contradictions;
  unevaluated  any rule not evaluated, any missing input, or a silent engine refuses.

Each check is its own function in CHECKS, so each has a mutation test
(test/test_prereg_gate.py). Nothing here grants a level on its own: core/notary.may_act
consults it only after its ordinary vector has refused, and never above a ceiling.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOTS_LOG = REPO / "memory" / "merkle_roots.jsonl"
CLASS = "human_signed_preregistration"


def applies(cls: dict, step: str, target) -> bool:
    if not cls or not target or step != cls.get("step"):
        return False
    rel = Path(str(target))
    try:
        rel = rel.resolve().relative_to(REPO)
    except Exception:  # noqa: BLE001 - a relative path stays as given
        pass
    return fnmatch.fnmatch(rel.as_posix(), cls["target_glob"])


def context(target, prev_step, witness=None, signatures=None, roots_log=None) -> dict:
    from experiments.institution import forward_rows as fr
    from experiments.institution import forward_witness as fw
    row_path = Path(str(target))
    if not row_path.is_absolute():
        row_path = REPO / row_path
    row_id = row_path.stem
    ctx = {"row_id": row_id, "row_path": row_path, "prev_step": prev_step,
           "roots_log": Path(roots_log or ROOTS_LOG), "fr": fr}
    ctx["row_sha256"] = hashlib.sha256(row_path.read_bytes()).hexdigest()
    ctx["signature"] = fw.latest_signature(row_id, signatures)
    try:
        ctx["seal"] = json.loads((row_path.parent / f"{row_id}.seal.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        ctx["seal"] = None
    ctx["witness"] = witness if witness is not None else fw.witness(
        row_id, forward_dir=row_path.parent, signatures=signatures)
    return ctx


def check_signature(ctx) -> tuple:
    s = ctx["signature"]
    if not s:
        return False, f"no signature row for {ctx['row_id']} (signer=Emil) in signatures.jsonl"
    if s.get("row_sha256") != ctx["row_sha256"]:
        return False, (f"signature row_sha256 {str(s.get('row_sha256'))[:16]} != sha256 of the row "
                       f"file bytes {ctx['row_sha256'][:16]}")
    return True, f"signed by {s['signer']} via {s['channel']} on {s['date']}"


def check_seal(ctx) -> tuple:
    seal, sig = ctx["seal"], ctx["signature"]
    if not seal:
        return False, "no seal beside the row"
    v = ctx["fr"].verify(ctx["row_path"], seal)
    if not v["ok"]:
        return False, f"seal does not verify: {v['why']}"
    import merkle_memory as mm
    chain = mm.verify_root_chain(ctx["roots_log"])
    if not chain["ok"]:
        return False, f"Merkle root chain does not verify: {chain['why']}"
    if not sig or seal.get("row_sha256") != sig.get("row_sha256"):
        return False, "seal.row_sha256 != signature.row_sha256 (or no signature)"
    return True, f"seal {seal['root'][:16]} verifies; chain ok ({chain['rows']} rows)"


def check_prev_step(ctx) -> tuple:
    from core import notary
    p = ctx["prev_step"]
    if p is None or p == "" or p == notary.PREV_UNKNOWN:
        return False, "prev_step not declared"
    return True, "PREV_NONE (first row)" if p == notary.PREV_NONE else f"prev_step {p!r}"


def check_metta(ctx) -> tuple:
    w = ctx["witness"]
    if w.get("contradictions"):
        return False, f"MeTTa contradicted {','.join(w['contradictions'])}"
    if w.get("verdict") != "PASS":
        return False, f"MeTTa witness verdict {w.get('verdict')}: {w.get('why')}"
    return True, "RF1-RF6: 0 contradictions, engines agree"


def check_unevaluated(ctx) -> tuple:
    w = ctx["witness"]
    if not (w.get("hyperon") or {}).get("ok"):
        return False, f"hyperon silent: {(w.get('hyperon') or {}).get('error')}"
    if w.get("not_evaluated"):
        return False, f"not evaluated: {','.join(w['not_evaluated'])}"
    if not w.get("engines_agree"):
        return False, "engines disagree"
    return True, "every rule evaluated by both engines"


CHECKS = (("signature", check_signature), ("seal", check_seal), ("prev_step", check_prev_step),
          ("metta", check_metta), ("unevaluated", check_unevaluated))


def evaluate(cls: dict, step: str, target, prev_step, ceiling=None, **kw) -> dict:
    """{"applies", "ok", "level", "passed": [...], "failed": [(check, why)]}."""
    out = {"class": CLASS, "applies": applies(cls, step, target), "ok": False,
           "level": (cls or {}).get("level"), "passed": [], "failed": []}
    if not out["applies"]:
        return out
    if ceiling is not None and ceiling < cls["level"]:
        out["failed"].append(("ceiling", f"step capped at {ceiling}"))
        return out
    try:
        ctx = context(target, prev_step, **kw)
    except Exception as e:  # noqa: BLE001 - a missing input is a refusal
        out["failed"].append(("inputs", f"{type(e).__name__}: {e}"))
        return out
    for name, fn in CHECKS:
        try:
            ok, why = fn(ctx)
        except Exception as e:  # noqa: BLE001
            ok, why = False, f"check raised {type(e).__name__}: {e}"
        (out["passed"] if ok else out["failed"]).append((name, why))
    out["ok"] = not out["failed"] and len(out["passed"]) == len(CHECKS)
    out["witness"] = {k: ctx["witness"].get(k) for k in ("verdict", "why", "engines_agree",
                                                          "contradictions", "not_evaluated")}
    return out
