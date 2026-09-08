#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/self_improve_pipeline.py — requirer -> implementer -> judge, BY HAND ONLY.

    local brain  ->  SPEC        core/self_improve/requirer.py
    cloud ladder ->  DIFF        core/self_improve/implementer.py
    deterministic -> VERDICT     core/earning.verify()

EXPERIMENTAL, on branch experimental/self-mod. This is NOT in the cycle:

  * nothing imports it — fast_cycle_runner.py does not know it exists;
  * it runs only when a human types the command below;
  * it APPLIES NOTHING. It prints a diff. It does not write to the working tree,
    does not stage, does not commit, does not touch any tracked file;
  * it writes only under experiments/self_improve/, and only with --write;
  * the verdict it prints GRANTS NOTHING. core/earning.py is inert by
    construction — config/earning_classes.json is LOCKED with no signed class,
    and core/notary.py does not import it. A PASS here is a statement about
    evidence, and nothing consumes it.

WHAT IT IS FOR
---------------
Answering one question, end to end, on demand: if the local brain writes the
spec and the cloud writes the patch, does the deterministic judge accept the
result? Today the answer is always FAIL — global_cap is LOCKED — and that is the
correct answer, printed rather than hidden.

FORBIDDEN FALLBACKS, NAMED
  * do NOT apply the diff, even if the verdict is PASS. Applying is a human
    decision made somewhere else.
  * do NOT write into memory/ or snapshots/. The pipeline asserts its own output
    directory is under experiments/ before writing anything.
  * do NOT continue past a refusal to make the run "complete". A spec that
    carries code, or a diff out of scope, ENDS the run — that refusal is the
    result.

    venv\\Scripts\\python.exe tools/self_improve_pipeline.py --selftest
    venv\\Scripts\\python.exe tools/self_improve_pipeline.py --dry-run
    venv\\Scripts\\python.exe tools/self_improve_pipeline.py            # live models
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "experiments" / "self_improve" / "runs"

# Anything the pipeline must never write into, asserted before it writes at all.
PRODUCTION = ("memory", "snapshots", "cortex_memory", "config", "agents",
              "core", "output", "news", "data")


class PipelineRefused(Exception):
    """A stage refused. The run ends; that refusal is the result."""


def _assert_experimental(path: Path) -> Path:
    """A write outside experiments/ is a bug, not a preference."""
    rel = path.resolve().relative_to(REPO) if str(path.resolve()).startswith(str(REPO)) \
        else Path(str(path))
    parts = rel.parts
    if not parts or parts[0] != "experiments":
        raise PipelineRefused(
            f"refusing to write to {rel} — this pipeline writes only under "
            f"experiments/. Production trees ({', '.join(PRODUCTION)}) are "
            f"off-limits to an experimental run.")
    return path


def run_once(observation: dict, brain=None, coder=None, class_id: str = "example_axis_key_fix",
             classes_path: Path | None = None) -> dict:
    """One end-to-end pass. Returns the record; raises PipelineRefused on a stage
    refusal, because a refusal IS the result and must not be smoothed over."""
    from core.self_improve import requirer as R
    from core.self_improve import implementer as I
    from core import earning as E

    record = {"ts": datetime.now(timezone.utc).isoformat(),
              "observation": str(observation.get("problem", ""))[:200]}

    # 1. the brain writes a spec, and never code
    try:
        spec = R.require(observation, brain=brain)
    except (R.SpecContainsCode, R.SpecInvalid) as exc:
        raise PipelineRefused(f"requirer refused: {exc}") from exc
    record["spec"] = spec

    # 2. the specialist writes a patch, inside the spec's allowlist
    try:
        built = I.implement(spec, model=coder)
    except (I.PatchOutOfScope, I.PatchUnusable) as exc:
        raise PipelineRefused(f"implementer refused: {exc}") from exc
    record["diff"] = built["diff"]
    record["changed_files"] = built["changed_files"]

    # 3. the deterministic judge. It grants nothing; it says whether the
    #    evidence would have cleared the class's bar.
    policy = E.load_classes(path=classes_path)
    class_def = (policy.get("classes") or {}).get(class_id)
    decision, reason = E.verify(
        built["changed_files"], class_def,
        {"exit_code": 0, "timed_out": False},
        {"measured": None, "source": built["diff"],
         "levels_before": {}, "levels_after": {}},
        class_id=class_id, policy=policy,
        # The revocation ledger stays in the experimental tree: a hand-run
        # experiment must not append to the record the real verifier reads.
        revocations_path=OUT_DIR / "revocations.jsonl",
    )
    record["verdict"] = decision
    record["reason"] = reason
    record["policy_locked"] = bool(policy.get("locked"))
    return record


def render(record: dict) -> str:
    spec = record.get("spec") or {}
    lines = [
        "=" * 72,
        "SPEC  (local brain — no code, real axis)",
        "=" * 72,
    ]
    for field in ("problem", "root_cause", "desired_change", "success_metric",
                  "goal_axis", "allowed_paths"):
        lines.append(f"  {field:<16} {spec.get(field)}")
    lines += ["", "=" * 72,
              f"DIFF  (cloud ladder — {len(record.get('changed_files') or [])} file(s))",
              "=" * 72,
              (record.get("diff") or "").rstrip(),
              "", "=" * 72, "VERDICT  (core/earning.verify — GRANTS NOTHING)",
              "=" * 72,
              f"  {record.get('verdict')}: {record.get('reason')}"]
    if record.get("policy_locked"):
        lines.append("  NOTE: global_cap is LOCKED, so FAIL is the only possible "
                     "verdict today. That is the designed state, not a defect.")
    lines.append("  Nothing was applied. This pipeline prints; it does not patch.")
    return "\n".join(lines)


def _fixture_models():
    """A spec and a diff good enough to reach a verdict, for --dry-run and the
    selftest. No model is called."""
    from core.self_improve.requirer import real_axes

    axis = "WATER_REVIEW" if "WATER_REVIEW" in real_axes() else sorted(real_axes())[0]
    spec = {
        "problem": "The provider never resolves the series, so the axis defaults.",
        "root_cause": "The observation map has no entry for the series key.",
        "desired_change": "The provider resolves the series instead of defaulting.",
        "success_metric": "count of axes scoring from real data",
        "goal_axis": axis,
        "allowed_paths": ["data_providers/"],
    }
    diff = ("--- a/data_providers/water_provider.py\n"
            "+++ b/data_providers/water_provider.py\n"
            "@@ -1,3 +1,4 @@\n context\n+    OBS['water_withdrawal'] = 'wb_ER.H2O.FWTL.ZS'\n")
    return (lambda prompt, max_tokens=700: json.dumps(spec),
            lambda prompt, max_tokens=1400: diff)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true",
                    help="use fixture models; call nothing")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help="save the run under experiments/self_improve/runs/")
    ap.add_argument("--limit", type=int, default=1)
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    from core.self_improve import requirer as R

    brain = coder = None
    if args.dry_run:
        brain, coder = _fixture_models()

    obs = R.observations(limit=args.limit) or [
        {"problem": "no HIGH observation on the feed", "component": "unknown"}]

    rc = 0
    for observation in obs[:args.limit]:
        try:
            record = run_once(observation, brain=brain, coder=coder)
        except PipelineRefused as exc:
            print("=" * 72)
            print(f"REFUSED: {exc}")
            print("A refusal is the result of this run, not a step to continue "
                  "past. Nothing was applied.")
            rc = 1
            continue
        print(render(record))
        if args.write:
            _assert_experimental(OUT_DIR).mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out = OUT_DIR / f"run_{stamp}.json"
            out.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print(f"\n  saved -> {out.relative_to(REPO)}")
    return rc


def _selftest() -> int:
    print("tools/self_improve_pipeline.py --selftest")
    ok = True
    for label, mod in (("requirer", "core.self_improve.requirer"),
                       ("implementer", "core.self_improve.implementer"),
                       ("earning judge", "core.earning")):
        try:
            __import__(mod)
            print(f"  {label:<14}: LIVE ({mod})")
        except Exception as exc:                                 # noqa: BLE001
            print(f"  {label:<14}: INERT ({type(exc).__name__}: {exc})")
            ok = False

    runner = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    wired = "self_improve_pipeline" in runner or "self_improve" in runner
    print(f"  in the cycle  : "
          f"{'YES — NO LONGER ON DEMAND' if wired else 'no (on demand only)'}")
    ok = ok and not wired

    print(f"  writes under  : {OUT_DIR.relative_to(REPO)} (experiments/ only)")
    try:
        _assert_experimental(REPO / "memory" / "x.json")
        print("  a write to memory/ : NOT REFUSED — the guard is open")
        ok = False
    except PipelineRefused:
        print("  a write to memory/ : refused")

    brain, coder = _fixture_models()
    try:
        rec = run_once({"problem": "selftest"}, brain=brain, coder=coder)
        print(f"  end to end    : reached a verdict -> {rec['verdict']}")
        print(f"                  {rec['reason'][:70]}")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  end to end    : BROKEN ({type(exc).__name__}: {exc})")
        ok = False

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
