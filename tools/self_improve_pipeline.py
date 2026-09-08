#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/self_improve_pipeline.py — requirer -> implementer -> judge, BY HAND ONLY.

    local brain   ->  SPEC       core/self_improve/requirer.py
    cloud ladder  ->  DIFF       core/self_improve/implementer.py
    deterministic ->  MERITS     core/self_improve/merits.grade()     <- the work
    deterministic ->  PRODUCTION core/earning.verify()                <- the ceiling
    on PASS       ->  COMMIT     core/self_improve/forkadvance.py     <- in the fork

THE PRINCIPLE
--------------
No model output passes a stage unverified; the FORK advances by STANDARD,
production is gated by a human PR.

THE GATE IS SPLIT (8 Sep 2026)
-------------------------------
This file used to print one verdict, and that verdict was always FAIL for one
reason: global_cap is LOCKED. That is the right answer to "may this be granted
capability in production" and a NON-ANSWER to "is this patch any good" — so a
competent patch and a confabulated one ended identically, printed and thrown
away. A gate that returns the same answer to every input is not grading.

Now two questions are asked separately, and both are printed:

    MERITS      applies + in scope + tests pass + before/after, graded in a
                clean sandbox worktree. Evidence only; no ceiling is consulted.
    PRODUCTION  core.earning.verify(), which still says LOCKED, and which now
                gates ONE thing: the path to main.

On a PASS on merits, --advance COMMITS the patch to a per-run branch off
experimental/self-mod. The fork moves. Production does not.

EXPERIMENTAL, on branch experimental/self-mod. This is NOT in the cycle:

  * nothing imports it — fast_cycle_runner.py does not know it exists;
  * it runs only when a human types the command below;
  * it never touches the working tree. Patches are applied inside throwaway git
    worktrees; the human's checkout, branch and uncommitted changes are not read
    and not modified;
  * it NEVER commits to main or master. --advance commits only to
    experimental/self-mod-run-<id>, and only a human PR can move that toward
    main;
  * it writes only under experiments/self_improve/, and only with --write;
  * a PASS on merits GRANTS NOTHING. core/earning.py stays inert —
    config/earning_classes.json is LOCKED with no signed class and
    core/notary.py does not import it. A merit PASS is a statement about a
    patch, consumed by nothing but a branch name.

FORBIDDEN FALLBACKS, NAMED
  * do NOT commit anything that did not PASS on merits. "It nearly passed" is
    not a merit, and a branch full of near-misses is worse than no branch.
  * do NOT let the production ceiling decide a merit, or a merit decide
    production. That collapse is exactly what this commit undid.
  * do NOT write into memory/ or snapshots/. The pipeline asserts its own output
    directory is under experiments/ before writing anything.
  * do NOT continue past a refusal to make the run "complete". A spec that
    carries code, or a diff out of scope, ENDS the run — that refusal is the
    result.

    venv\\Scripts\\python.exe tools/self_improve_pipeline.py --selftest
    venv\\Scripts\\python.exe tools/self_improve_pipeline.py --dry-run
    venv\\Scripts\\python.exe tools/self_improve_pipeline.py            # live models
    venv\\Scripts\\python.exe tools/self_improve_pipeline.py --advance  # + fork commit
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

# The fixture patches a REAL file, so --dry-run and the tests exercise the
# same context path a live run takes.
FIXTURE_FILE = "data_providers/civilization/economy_work_provider.py"

# How many times the implementer may rewrite a patch against git's own
# error before the run is refused. Three is the brief's number and it is
# a ceiling, not a target: a loop that never gives up burns the ladder's
# budget on a model that cannot do the job.
MAX_PATCH_ATTEMPTS = 3

# Anything the pipeline must never write into, asserted before it writes at all.
PRODUCTION = ("memory", "snapshots", "cortex_memory", "config", "agents",
              "core", "output", "news", "data")


class PipelineRefused(Exception):
    """A stage refused. The run ends; that refusal is the result."""


CODE_TARGET_DIRTY = "REFUSED_TARGET_DIRTY"


def _refuse_if_target_is_dirty(spec: dict, base: str = "experimental/self-mod") -> None:
    """The implementer reads the WORKING TREE; the grader grades a clean checkout
    of the fork branch. When those differ for a target file, the patch is written
    against one tree and judged against another, and it fails with git's content
    error — which reads like the model confabulating when in fact the human had
    uncommitted edits.

    Refusing here, by name, keeps that from being misread as a model failure.
    The forbidden fallback is grading it anyway and blaming the diff.
    """
    import subprocess as _sp

    paths = [str(p) for p in (spec.get("allowed_paths") or [])]
    if not paths:
        return
    try:
        out = _sp.run(["git", "diff", "--name-only", base, "--", *paths],
                      cwd=str(REPO), capture_output=True, text=True, timeout=60).stdout
    except Exception:                                            # noqa: BLE001
        return
    dirty = [l.strip() for l in out.splitlines() if l.strip()]
    if dirty:
        raise PipelineRefused(
            f"{CODE_TARGET_DIRTY}: {dirty} differ between the working tree and "
            f"{base}. The implementer would be shown one version and the grader "
            f"would judge another, so a correct patch would fail on content. "
            f"Commit or stash those files before running.")


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


def append_diff(rel: str, added_line: str, context: int = 3) -> str:
    """A unified diff that appends one line to a REAL file, and really applies.

    Built from the file's own last lines, so it is true by construction and stays
    true when the file changes. The fixture used to be hand-written against a
    made-up context line; the git-apply net refused it, correctly — a fixture the
    content net rejects was fiction, and every test standing on it exercised a
    patch that could never have applied.

    The line arithmetic is the part that bites: splitlines() drops the trailing
    empty element that split("\\n") leaves, so the last content line is src[-1]
    and the hunk starts at len(src) - context + 1. Getting that wrong by one is
    what made three earlier attempts fail while git's own diff passed.
    """
    src = (REPO / rel).read_text(encoding="utf-8").splitlines()
    ctx = src[-context:]
    start = len(src) - len(ctx) + 1
    nl = chr(10)
    body = "".join(" " + c + nl for c in ctx)
    return (f"--- a/{rel}{nl}"
            f"+++ b/{rel}{nl}"
            f"@@ -{start},{len(ctx)} +{start},{len(ctx) + 1} @@{nl}"
            f"{body}+{added_line}{nl}")


def read_for_patch(rel: str, budget: int = 60000) -> str:
    """The WHOLE real file, or an explicitly-marked map of it. Never a blind cut.

    It used to hand over the first 6000 characters. agents/core/self_observer.py
    is 29016 characters, so the model saw the docstring and the imports and had
    to invent the other 80% — which is exactly what it did on 2026-09-08,
    proposing to remove a `class SelfObserver` and a `def self_observe` that are
    nowhere in the file. A patch cannot describe a file the writer has not seen.

    Every file this pipeline is likely to touch fits: the largest module in
    agents/core/ is 29k. Above the budget the file is NOT silently cut — the
    model gets a line-numbered index of every def/class, the head and the tail in
    full, and a loud marker naming exactly how many lines were withheld, so it
    knows it is working blind on that region and can say so rather than guess.
    """
    path = REPO / rel
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= budget:
        return f"--- {rel} (COMPLETE, {len(text)} chars) ---\n{text}"

    lines = text.splitlines()
    index = [f"{i:>5}: {ln}" for i, ln in enumerate(lines, 1)
             if ln.lstrip().startswith(("def ", "class ", "async def "))]
    head, tail = lines[:120], lines[-120:]
    omitted = len(lines) - len(head) - len(tail)
    nl = chr(10)
    return (
        f"--- {rel} (TOO LARGE: {len(text)} chars, {len(lines)} lines — "
        f"SHOWN IN PART) ---{nl}"
        f"DEFINITIONS IN THIS FILE (line: signature):{nl}"
        + nl.join(index) + nl * 2
        + f"FIRST {len(head)} LINES:{nl}" + nl.join(head) + nl * 2
        + f"[... {omitted} LINES WITHHELD — you have NOT seen them. Do not write "
          f"a hunk against this region; say so instead. ...]{nl}{nl}"
        + f"LAST {len(tail)} LINES:{nl}" + nl.join(tail) + nl)


def _read_allowed_files(spec: dict, budget: int = 60000) -> str:
    """The REAL content of the files the spec allows, for the implementer.

    Only files that EXIST are read; a spec naming a path that does not resolve
    contributes nothing rather than a fabricated placeholder. The requirer
    refuses such a spec outright, so this should be unreachable — the two guards
    fail in the same direction.
    """
    out, spent = [], 0
    for rel in (spec.get("allowed_paths") or []):
        if not (REPO / rel).is_file():
            continue
        try:
            chunk = read_for_patch(rel, budget=max(0, budget - spent))
        except Exception:
            continue
        if not chunk:
            break
        out.append(chunk)
        spent += len(chunk)
    return "\n\n".join(out)


def run_once(observation: dict, brain=None, coder=None, class_id: str = "example_axis_key_fix",
             classes_path: Path | None = None, advance: bool = False,
             run_id: str | None = None, run_tests: bool = True) -> dict:
    """One end-to-end pass. Returns the record; raises PipelineRefused on a stage
    refusal, because a refusal IS the result and must not be smoothed over."""
    from core.self_improve import requirer as R
    from core.self_improve import implementer as I
    from core import earning as E
    from core.self_improve import applies as A
    from core.self_improve import merits as M

    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = {"ts": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
              "observation": str(observation.get("problem", ""))[:200]}

    # 1. the brain writes a spec, and never code
    try:
        spec = R.require(observation, brain=brain)
    except (R.SpecContainsCode, R.SpecInvalid) as exc:
        raise PipelineRefused(f"requirer refused: {exc}") from exc
    record["spec"] = spec
    _refuse_if_target_is_dirty(spec)

    # 2. the specialist writes a patch, inside the spec's allowlist
    #
    # THE CONTEXT IS PASSED (8 Sep 2026). This called implement(spec, model=...)
    # and nothing else, so the cloud model was handed a specification and asked
    # to patch a repository it had never seen. On 2026-09-08 it wrote a
    # competent patch to src/ai/self_observer.py — a file, a class and a module
    # that do not exist anywhere in this repo. A model with no code in front of
    # it will invent code that fits the words.
    context = _read_allowed_files(spec)
    record["context_chars"] = len(context)

    # ── THE RETRY LOOP: A CODING AGENT VERIFIES ITS OWN WORK ───────────────
    # One shot at a patch, judged by a regex, is not a coding agent. This one
    # writes, asks git whether the diff applies to the real file, and if git
    # says no it is handed git's ACTUAL error — "while searching for: <the lines
    # it expected>" — and tries again. That error is the single most useful
    # thing a patch writer can be told, because it quotes what the file really
    # contains at the point the model got it wrong.
    #
    # Refuse only after MAX_PATCH_ATTEMPTS. A loop that never gives up is a loop
    # that burns the ladder's budget on a model that cannot do the job.
    built, feedback, attempts = None, "", []
    for attempt in range(1, MAX_PATCH_ATTEMPTS + 1):
        try:
            built = I.implement(spec, model=coder, context=context,
                                feedback=feedback)
        except (I.PatchOutOfScope, I.PatchUnusable) as exc:
            attempts.append({"attempt": attempt, "stage": "implementer",
                             "error": str(exc)[:400]})
            if attempt == MAX_PATCH_ATTEMPTS:
                record["attempts"] = attempts
                raise PipelineRefused(
                    f"implementer refused after {attempt} attempt(s): {exc}") from exc
            feedback = str(exc)
            continue

        ok, why = A.check_applies(built["diff"])
        attempts.append({"attempt": attempt, "stage": "git apply --check",
                         "ok": ok, "error": why[:400] if not ok else ""})
        if ok:
            break
        if attempt == MAX_PATCH_ATTEMPTS:
            record["attempts"] = attempts
            record["applies"] = False
            record["apply_error"] = why
            raise PipelineRefused(A.refusal(why))
        feedback = why

    record["attempts"] = attempts
    record["attempts_used"] = len(attempts)
    record["applies"] = True
    record["diff"] = built["diff"]
    record["changed_files"] = built["changed_files"]

    # 3. THE MERITS. Did the work meet the standard? Graded in a clean sandbox
    #    worktree of the fork branch, on evidence alone — no ceiling, no policy,
    #    nothing a switch can flip. This is the verdict that can differ between
    #    a good patch and a confabulated one, which is why it is the run's
    #    headline verdict.
    grade = M.grade(spec, built["diff"], built["changed_files"],
                    run_tests=run_tests)
    record["merits"] = grade
    record["verdict"] = grade["decision"]
    record["reason"] = grade["reason"]

    # 4. THE FORK ADVANCES. A PASS becomes a commit on its own branch off
    #    experimental/self-mod. Never main; never the fork branch itself.
    if advance and grade["decision"] == M.PASS:
        from core.self_improve import forkadvance as FA
        try:
            record["advanced"] = FA.advance(
                built["diff"], spec, run_id, grade,
                changed_files=built["changed_files"])
        except FA.AdvanceRefused as exc:
            record["advanced"] = {"refused": str(exc)}
    elif advance:
        record["advanced"] = {"refused": (
            f"{grade['decision']} on merits — nothing advances. A branch full of "
            f"near-misses is worse than no branch.")}

    # 5. THE PRODUCTION CEILING, asked separately and answered separately. It
    #    grants nothing here either; it gates ONE thing — the path to main, which
    #    a human walks by opening a pull request.
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
    record["production_verdict"] = decision
    record["production_reason"] = reason
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
                  "domain", "categories", "allowed_paths"):
        lines.append(f"  {field:<16} {spec.get(field)}")
    lines += ["", "=" * 72,
              f"DIFF  (cloud ladder — {len(record.get('changed_files') or [])} file(s))",
              "=" * 72,
              (record.get("diff") or "").rstrip(),
              "", "=" * 72,
              "MERITS  (core/self_improve/merits.grade — EVIDENCE, no ceiling)",
              "=" * 72]
    for m in (record.get("merits") or {}).get("merits") or []:
        lines.append(f"  {'PASS' if m.get('ok') else 'FAIL'}  {m.get('name'):<13} "
                     f"{str(m.get('why'))[:150]}")
    lines.append(f"  ---> {record.get('verdict')} on merits")

    adv = record.get("advanced")
    if adv:
        lines += ["", "=" * 72, "THE FORK  (a per-run branch off experimental/self-mod)",
                  "=" * 72]
        if adv.get("refused"):
            lines.append(f"  did not advance: {adv['refused'][:300]}")
        else:
            lines += [f"  branch   {adv['branch']}",
                      f"  commit   {adv['commit'][:12]}  (off {adv['base']} "
                      f"@ {adv['base_commit'][:12]})",
                      f"  files    {', '.join(adv['files'])}",
                      f"  to main  {adv['path_to_main']}"]

    lines += ["", "=" * 72,
              "PRODUCTION  (core/earning.verify — GATES THE PATH TO MAIN ONLY)",
              "=" * 72,
              f"  {record.get('production_verdict')}: {record.get('production_reason')}"]
    if record.get("policy_locked"):
        lines.append("  global_cap is LOCKED, so FAIL is the only production verdict "
                     "today. That is the designed state, and it no longer decides "
                     "whether the work was any good — the merits above do.")
    lines.append("  Nothing entered production. Only a human PR can move a fork "
                 "commit to main.")
    return "\n".join(lines)


def _fixture_models():
    """A spec and a diff good enough to reach a verdict, for --dry-run and the
    selftest. No model is called."""
    spec = {
        "problem": "The provider never resolves the series, so the axis defaults.",
        "root_cause": "The observation map has no entry for the series key.",
        "desired_change": "The provider resolves the series instead of defaulting.",
        # NAMES A REAL FILE — SPEC_METRIC_UNGROUNDED refuses anything else, and
        # a fixture the nets reject is a fixture that was fiction.
        "success_metric": "the number of rows in memory/goal_score_history.json",
        # GROUNDED BY THE PATH. plausible_axes() derives the axis from the
        # target filename (economy_work_provider.py -> ECONOMY_WORK_REVIEW),
        # so this fixture passes the axis net for a real reason rather than
        # because the net is off.
        "domain": "external",
        "categories": ["ECONOMY_WORK_REVIEW"],
        # A REAL, EXISTING file (8 Sep 2026). This said "data_providers/" — a
        # directory prefix — so _read_allowed_files() found nothing to read and
        # the fixture exercised an EMPTY context, which is exactly the state the
        # grounding commit exists to end. A fixture that cannot reach the code
        # path it is meant to cover proves nothing.
        "allowed_paths": [FIXTURE_FILE],
    }
    diff = append_diff(FIXTURE_FILE,
                       "# fixture line added by the self-improve pipeline dry run")
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
    ap.add_argument("--advance", action="store_true",
                    help="on a PASS on merits, commit the patch to "
                         "experimental/self-mod-run-<id>. Never main.")
    ap.add_argument("--runs", type=int, default=1,
                    help="repeat the SAME observation N times, for measuring "
                         "how stable the pipeline is rather than how lucky")
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
        for n in range(1, max(1, args.runs) + 1):
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{n}"
            if args.runs > 1:
                print("\n" + "#" * 72)
                print(f"# RUN {n} of {args.runs}  (run_id {run_id})")
                print("#" * 72)
            try:
                record = run_once(observation, brain=brain, coder=coder,
                                  advance=args.advance, run_id=run_id)
            except PipelineRefused as exc:
                print("=" * 72)
                print(f"REFUSED: {exc}")
                print("A refusal is the result of this run, not a step to continue "
                      "past. Nothing was applied and nothing was committed.")
                rc = 1
                continue
            print(render(record))
            if args.write:
                _assert_experimental(OUT_DIR).mkdir(parents=True, exist_ok=True)
                out = OUT_DIR / f"run_{run_id}.json"
                out.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                print(f"\n  saved -> {out.relative_to(REPO)}")
    return rc


def _selftest() -> int:
    print("tools/self_improve_pipeline.py --selftest")
    ok = True
    for label, mod in (("requirer", "core.self_improve.requirer"),
                       ("implementer", "core.self_improve.implementer"),
                       ("merits grader", "core.self_improve.merits"),
                       ("fork advance", "core.self_improve.forkadvance"),
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

    import subprocess

    def _branches():
        out = subprocess.run(["git", "branch", "--list",
                              "experimental/self-mod-run-*"], cwd=str(REPO),
                             capture_output=True, text=True).stdout
        return {l.strip("* ").strip() for l in out.splitlines() if l.strip()}

    def _head(ref):
        return subprocess.run(["git", "rev-parse", ref], cwd=str(REPO),
                              capture_output=True, text=True).stdout.strip()

    before_branches, before_main = _branches(), _head("master")

    brain, coder = _fixture_models()
    try:
        rec = run_once({"problem": "the economy work provider never resolves its series",
                          "component": "economy_work"},
                         brain=brain, coder=coder)
        print(f"  merits verdict: {rec['verdict']}")
        print(f"                  {rec['reason'][:70]}")
        print(f"  production    : {rec['production_verdict']} "
              f"({rec['production_reason'][:44]})")
        # THE SPLIT, ASSERTED: the two verdicts answer different questions, so a
        # locked ceiling must not be able to decide the merits. If they are
        # always equal the split has quietly collapsed back into one gate.
        split = not (rec["verdict"] == "FAIL" and rec["policy_locked"] and
                     rec["production_verdict"] == "FAIL" and
                     "global_cap" in rec["reason"])
        print(f"  the two are separate : "
              f"{'yes' if split else 'NO — the ceiling is deciding the merits'}")
        ok = ok and split
    except Exception as exc:                                     # noqa: BLE001
        print(f"  end to end    : BROKEN ({type(exc).__name__}: {exc})")
        ok = False

    # WITHOUT --advance, NOTHING IS COMMITTED. Measured, not asserted in prose.
    same = _branches() == before_branches
    print(f"  no --advance -> no branch : "
          f"{'confirmed' if same else 'A BRANCH APPEARED — wrong'}")
    ok = ok and same
    print(f"  master untouched          : "
          f"{'confirmed' if _head('master') == before_main else 'MASTER MOVED — wrong'}")
    ok = ok and _head("master") == before_main

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
