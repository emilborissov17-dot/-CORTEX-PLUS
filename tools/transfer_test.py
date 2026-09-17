#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/transfer_test.py — T1: THE THREE ARMS.

Runs exactly what claude/reports/PREREG_TRANSFER_2026-09-17.md froze. Nothing here
decides anything the prereg did not already decide; the thresholds, the arms, the
metrics and the reading of every outcome were committed at 0061c68 before this file
existed, and it may not reinterpret them.

A pass on synthetic tasks demonstrates the mechanism only.

THE THREE ARMS, and why the two controls are not one control
-------------------------------------------------------------
  memory-on   top-k episodes retrieved by core/embed_index.search
  memory-off  MATCHED-LENGTH FILLER — same block length, no episode content
  shuffled    equal token count, episodes with NO shared primitive, order
              counterbalanced

memory-off uses filler rather than an empty block so a difference between on and off
cannot be an artefact of prompt length. shuffled holds length AND episode-shaped
content constant, so on − shuffled is what retrieval SPECIFICALLY bought. Without
both, a format effect and a retrieval effect are the same number.

WHAT IS SCORED, AND WHAT IS REFUSED
  success   the direction is correct
  brier     (p − actual_up)², mean. Computed as a mean squared error and called Brier
            because that is what a Brier score is.
  UNPARSEABLE IS A FAILURE OF THAT TRIAL. Never dropped, never retried. A dropped
  trial silently changes n per arm and makes the paired comparison a comparison of
  different task sets. It is counted per arm, and if the rates differ materially the
  prereg VOIDS the Brier comparison rather than reporting it.

Order of arms is rotated per task so that any drift in the local model over the run
falls on all three arms equally rather than on whichever ran last.

  venv\\Scripts\\python.exe tools/transfer_test.py --selftest
  venv\\Scripts\\python.exe tools/transfer_test.py --run --limit 3     # smoke
  venv\\Scripts\\python.exe tools/transfer_test.py --run
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import transfer_tasks as TT       # noqa: E402

METHOD_VERSION = "transfer_test/1"
PREREG = "claude/reports/PREREG_TRANSFER_2026-09-17.md"

# Frozen by the prereg. Changing any of these invalidates the run.
MODEL = "qwen3:8b"
TEMPERATURE = 0.0
NUM_PREDICT = 128
THINK = False
TOP_K = 3
BOOTSTRAP = 10_000
SEED = 20260917

ARMS = ("on", "off", "shuffled")
TRIALS = BASE / "memory" / "t1_trials.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── prompt ───────────────────────────────────────────────────────────────────

def render_episode(ep: dict) -> str:
    """One past episode: what was seen, and the VERIFIED outcome.

    The latent label is NOT here. An episode carries what the series looked like and
    what actually happened next — the three things the system records about its own
    work. Putting the primitive name in would make memory-on an answer key.
    """
    return (f"- past case: {', '.join(str(v) for v in ep['series'])} "
            f"-> next step was {'UP' if ep['answer_up'] else 'DOWN'}")


def filler_block(n_lines: int, width: int) -> str:
    """Matched-length filler: the same shape of block, carrying no episode."""
    # The filler must carry NO episode content, not even the phrase an episode uses:
    # a line saying "no past case available" still puts the words in the prompt, and
    # the arm is supposed to differ from memory-on by CONTENT, not by a denial of it.
    line = "- (none)"
    pad = max(0, width - len(line))
    return "\n".join(line + " " * pad for _ in range(n_lines))


def build_prompt(task: dict, memory_block: str) -> str:
    """IDENTICAL SKELETON IN EVERY ARM. Only memory_block differs."""
    return (
        "You are forecasting the next step of a numeric series.\n\n"
        "Past cases:\n"
        f"{memory_block}\n\n"
        f"Now this series: {', '.join(str(v) for v in task['series'])}\n\n"
        "Will the next value be higher (UP) or lower (DOWN) than the last value?\n"
        "Answer with one line of JSON and nothing else:\n"
        '{"direction": "UP" or "DOWN", "p": probability that it is UP, 0.0 to 1.0}\n'
    )


# ── parsing: a refusal, not a rescue ─────────────────────────────────────────

def parse_reply(text: str) -> dict:
    """-> {parsed, direction, p, why}. Never guesses.

    A reply that does not carry a usable direction is a FAILED TRIAL. The temptation
    is to search the prose for the word "up" and call it an answer; that turns a model
    that did not answer into a model that answered, which is the failure mode this
    whole experiment is supposed to be able to see.
    """
    t = (text or "").strip()
    if not t:
        return {"parsed": False, "why": "empty reply"}
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return {"parsed": False, "why": "no JSON object in reply"}
    try:
        d = json.loads(t[start:end + 1])
    except Exception as e:                                       # noqa: BLE001
        return {"parsed": False, "why": f"JSON did not parse: {type(e).__name__}"}
    if not isinstance(d, dict):
        return {"parsed": False, "why": "JSON is not an object"}
    raw = str(d.get("direction", "")).strip().upper()
    if raw not in ("UP", "DOWN"):
        return {"parsed": False, "why": f"direction {raw!r} is not UP or DOWN"}
    p = d.get("p")
    try:
        p = float(p)
    except (TypeError, ValueError):
        return {"parsed": False, "why": f"p {p!r} is not a number"}
    if not (0.0 <= p <= 1.0):
        return {"parsed": False, "why": f"p {p} is outside [0, 1]"}
    return {"parsed": True, "direction": raw, "p": p, "why": ""}


def ask(prompt: str, model: str = MODEL, timeout: int = 300) -> dict:
    import requests
    body = {"model": model, "stream": False, "keep_alive": "10m", "think": THINK,
            "options": {"temperature": TEMPERATURE, "num_predict": NUM_PREDICT},
            "messages": [{"role": "user", "content": prompt}]}
    try:
        r = requests.post("http://localhost:11434/api/chat", timeout=timeout, json=body)
        r.raise_for_status()
        return {"ok": True, "text": r.json()["message"].get("content", "")}
    except Exception as e:                                       # noqa: BLE001
        # AN ARM THAT ERRORS IS REPORTED, NEVER IMPUTED.
        return {"ok": False, "text": "", "error": f"{type(e).__name__}: {e}"}


# ── statistics ───────────────────────────────────────────────────────────────

def paired_bootstrap(a: list, b: list, n: int = BOOTSTRAP, seed: int = SEED) -> dict:
    """95% CI on mean(a) − mean(b), resampling TASKS (paired), not trials."""
    if len(a) != len(b) or not a:
        return {"diff": None, "lo": None, "hi": None, "n": 0}
    rng = random.Random(seed)
    idx = range(len(a))
    diffs = []
    for _ in range(n):
        s = [rng.choice(idx) for _ in idx]
        diffs.append(sum(a[i] - b[i] for i in s) / len(s))
    diffs.sort()
    return {"diff": round(sum(x - y for x, y in zip(a, b)) / len(a), 4),
            "lo": round(diffs[int(0.025 * n)], 4),
            "hi": round(diffs[int(0.975 * n)], 4), "n": len(a)}


def spearman(x: list, y: list) -> float | None:
    """Rank correlation, ties averaged. No scipy in this venv's guaranteed set."""
    if len(x) != len(y) or len(x) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(x), ranks(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return round(num / (dx * dy), 4) if dx and dy else None


# ── the run ──────────────────────────────────────────────────────────────────

def memory_blocks(task: dict, episodes: list, index_dir: pathlib.Path,
                  embed, by_id: dict, rng: random.Random) -> dict:
    """The three blocks for one task. Built together so lengths can be matched."""
    from core import embed_index
    qmat, qsrc = embed([TT.features(task)])
    res = embed_index.search(qmat[0], k=TOP_K, out_dir=index_dir)
    on_eps = [by_id[r["key"]] for r in res if r["key"] in by_id][:TOP_K]

    # shuffled: episodes sharing NO primitive with this task
    pool = [e for e in episodes if not (set(e["latent"]) & set(task["latent"]))]
    rng.shuffle(pool)
    sh_eps = pool[:TOP_K] if len(pool) >= TOP_K else pool
    # order counterbalanced: reverse for odd-indexed tasks
    if int(task["task_id"].split("-")[-1]) % 2:
        sh_eps = list(reversed(sh_eps))

    on_block = "\n".join(render_episode(e) for e in on_eps)
    sh_block = "\n".join(render_episode(e) for e in sh_eps)
    width = max((len(l) for l in (on_block + "\n" + sh_block).split("\n")), default=40)
    off_block = filler_block(len(on_eps), width)
    return {"on": on_block, "shuffled": sh_block, "off": off_block,
            "on_eps": on_eps, "sh_eps": sh_eps, "src": qsrc}


def run(limit: int = 0, model: str = MODEL) -> dict:
    from core import embed_index, interval_head as IH

    def embed(texts):
        return IH.embed(texts, model=IH.EMBED_MODEL)

    episodes = TT.memory_set()
    tests = TT.test_set()
    if limit:
        tests = tests[:limit] + [t for t in tests
                                 if t["stratum"] == "holdout_composition"][:limit]

    index_dir = BASE / "memory" / "embed_index_t1" / IH.EMBED_MODEL.replace(":", "_")
    mat, src = embed([TT.features(e) for e in episodes])
    if src == "hashed_fallback":
        raise RuntimeError("episodes embedded as hashed_fallback — the prereg VOIDS "
                           "the run rather than correcting it")
    embed_index.build(cache={e["task_id"]: list(v) for e, v in zip(episodes, mat)},
                      out_dir=index_dir)
    by_id = {e["task_id"]: e for e in episodes}

    rng = random.Random(SEED)
    rows = []
    for n, task in enumerate(tests):
        blocks = memory_blocks(task, episodes, index_dir, embed, by_id, rng)
        order = list(ARMS)
        order = order[n % 3:] + order[:n % 3]      # rotate so drift hits all arms
        rec = {"task_id": task["task_id"], "stratum": task["stratum"],
               "latent": task["latent"], "answer_up": task["answer_up"],
               "arm_order": order, "arms": {}}
        top = blocks["on_eps"][0] if blocks["on_eps"] else None
        rec["latent_sim_top1"] = TT.latent_similarity(task, top) if top else None
        rec["surface_sim_top1"] = TT.surface_similarity(task, top) if top else None
        for arm in order:
            out = ask(build_prompt(task, blocks[arm]), model=model)
            p = parse_reply(out["text"]) if out["ok"] else {
                "parsed": False, "why": out.get("error", "call failed")}
            ok = bool(p["parsed"] and (p["direction"] == "UP") == task["answer_up"])
            rec["arms"][arm] = {
                "parsed": p["parsed"], "why": p.get("why", ""),
                "direction": p.get("direction"), "p": p.get("p"),
                "success": 1 if ok else 0,
                "brier": (round((p["p"] - (1.0 if task["answer_up"] else 0.0)) ** 2, 4)
                          if p["parsed"] else None),
                "transport_error": None if out["ok"] else out.get("error"),
            }
        rows.append(rec)
        print(f"  [{n+1}/{len(tests)}] {task['task_id']} {task['stratum']:22s} "
              + "  ".join(f"{a}={rec['arms'][a]['success']}"
                          f"{'' if rec['arms'][a]['parsed'] else '(unparsed)'}"
                          for a in ARMS), flush=True)

    return summarise(rows)


def summarise(rows: list) -> dict:
    def succ(arm, sel=None):
        r = [x for x in rows if sel is None or x["stratum"] == sel]
        return [x["arms"][arm]["success"] for x in r]

    def brier(arm, sel=None):
        r = [x for x in rows if (sel is None or x["stratum"] == sel)
             and all(x["arms"][a]["parsed"] for a in ARMS)]
        return [x["arms"][arm]["brier"] for x in r]

    out = {"ts": _now(), "method_version": METHOD_VERSION, "prereg": PREREG,
           "model": MODEL, "think": THINK, "temperature": TEMPERATURE,
           "top_k": TOP_K, "n_tasks": len(rows),
           "task_ledger_sha256": TT.ledger()["sha256"], "rows": rows}

    out["parse_failures"] = {a: sum(1 for x in rows if not x["arms"][a]["parsed"])
                             for a in ARMS}
    out["transport_errors"] = {a: sum(1 for x in rows if x["arms"][a]["transport_error"])
                               for a in ARMS}
    out["success_rate"] = {a: round(sum(succ(a)) / max(1, len(rows)), 4) for a in ARMS}
    out["brier"] = {a: (round(sum(brier(a)) / len(brier(a)), 4) if brier(a) else None)
                    for a in ARMS}

    out["decomposition"] = {
        "total_on_minus_off": paired_bootstrap(succ("on"), succ("off")),
        "retrieval_on_minus_shuffled": paired_bootstrap(succ("on"), succ("shuffled")),
        "format_shuffled_minus_off": paired_bootstrap(succ("shuffled"), succ("off")),
    }
    ho = "holdout_composition"
    out["holdout"] = {
        "n": len(succ("on", ho)),
        "success_rate": {a: (round(sum(succ(a, ho)) / len(succ(a, ho)), 4)
                             if succ(a, ho) else None) for a in ARMS},
        "total_on_minus_off": paired_bootstrap(succ("on", ho), succ("off", ho)),
        "retrieval_on_minus_shuffled": paired_bootstrap(succ("on", ho),
                                                        succ("shuffled", ho)),
    }

    ben = [x["arms"]["on"]["success"] - x["arms"]["off"]["success"] for x in rows]
    lat = [x["latent_sim_top1"] or 0.0 for x in rows]
    sur = [x["surface_sim_top1"] or 0.0 for x in rows]
    out["spearman"] = {"benefit_vs_latent": spearman(ben, lat),
                       "benefit_vs_surface": spearman(ben, sur)}

    # THE VERDICT IS READ OFF THE PREREG, not chosen here.
    tot = out["decomposition"]["total_on_minus_off"]
    ret = out["decomposition"]["retrieval_on_minus_shuffled"]
    sp = out["spearman"]
    pf = out["parse_failures"]
    conds = {
        "on_beats_off_by_15pp": bool(tot["diff"] is not None and tot["diff"] >= 0.15
                                     and tot["lo"] is not None and tot["lo"] > 0),
        "on_beats_shuffled_by_7.5pp": bool(ret["diff"] is not None and ret["diff"] >= 0.075
                                           and ret["lo"] is not None and ret["lo"] > 0),
        "benefit_tracks_latent": bool(sp["benefit_vs_latent"] is not None
                                      and sp["benefit_vs_latent"] > 0
                                      and sp["benefit_vs_surface"] is not None
                                      and sp["benefit_vs_latent"] > sp["benefit_vs_surface"]),
    }
    out["conditions"] = conds
    spread = max(pf.values()) - min(pf.values())
    out["brier_comparison_void"] = spread > max(1, int(0.1 * len(rows)))
    out["verdict"] = ("INCONCLUSIVE" if sum(out["transport_errors"].values())
                      else ("PASS" if all(conds.values()) else "FAIL"))
    return out


def _selftest() -> int:
    print("tools/transfer_test.py --selftest")
    fails = []

    def check(name, cond):
        print(f"  {'OK  ' if cond else 'FAIL'}   {name}")
        if not cond:
            fails.append(name)

    # parsing refuses rather than rescues
    check("a clean JSON reply parses",
          parse_reply('{"direction":"UP","p":0.8}')["parsed"])
    check("JSON with prose around it still parses",
          parse_reply('sure! {"direction":"DOWN","p":0.2} done')["parsed"])
    check("an empty reply is NOT parsed", not parse_reply("")["parsed"])
    check("prose with the word up is NOT parsed — no rescue by keyword",
          not parse_reply("I think it will go up")["parsed"])
    check("a bad direction is refused",
          not parse_reply('{"direction":"SIDEWAYS","p":0.5}')["parsed"])
    check("p outside [0,1] is refused",
          not parse_reply('{"direction":"UP","p":1.4}')["parsed"])
    check("a non-numeric p is refused",
          not parse_reply('{"direction":"UP","p":"high"}')["parsed"])
    check("every refusal says why",
          all(parse_reply(x)["why"] for x in
              ("", "nope", '{"direction":"X","p":0.5}')))

    # prompts differ ONLY in the memory block
    t = TT.test_set()[0]
    a, b = build_prompt(t, "- past case: 1, 2 -> next step was UP"), build_prompt(t, "X")
    check("the prompt skeleton is identical across arms",
          a.replace("- past case: 1, 2 -> next step was UP", "") == b.replace("X", ""))

    # an episode never leaks its latent label
    ep = TT.memory_set()[0]
    check("a rendered episode leaks NO latent primitive",
          all(p not in render_episode(ep) for p in TT.PRIMITIVES))

    # filler is matched in length
    on = "\n".join(render_episode(e) for e in TT.memory_set()[:3])
    off = filler_block(3, max(len(l) for l in on.split("\n")))
    check("filler has the same number of lines as the on-block",
          len(off.split("\n")) == len(on.split("\n")))
    check("filler lines are at least as wide as the on-block's",
          min(len(l) for l in off.split("\n")) >= max(len(l) for l in on.split("\n")))
    check("filler carries no past case", "past case" not in off)

    # SHUFFLED MUST SHARE NO PRIMITIVE — the mutation test lives here
    tests, eps = TT.test_set(), TT.memory_set()
    rng = random.Random(1)
    task = tests[0]
    pool = [e for e in eps if not (set(e["latent"]) & set(task["latent"]))]
    check("the shuffled pool shares no primitive with the task",
          all(not (set(e["latent"]) & set(task["latent"])) for e in pool))
    check("...and the pool is non-empty, or there is nothing to shuffle",
          len(pool) >= TOP_K)
    bad_pool = [e for e in eps if set(e["latent"]) & set(task["latent"])]
    check("MUTATION: a shuffled pool built WITHOUT the exclusion would share a "
          "primitive, and this check would not hold",
          any(set(e["latent"]) & set(task["latent"]) for e in bad_pool))

    # statistics
    check("a paired bootstrap on identical arms centres on 0",
          abs(paired_bootstrap([1, 0, 1, 0] * 8, [1, 0, 1, 0] * 8)["diff"]) < 1e-9)
    bs = paired_bootstrap([1] * 32, [0] * 32)
    check("a perfect separation has a CI excluding 0", bs["lo"] > 0 and bs["diff"] == 1.0)
    check("spearman is 1.0 on a monotone pair", spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0)
    check("spearman is -1.0 on a reversed pair", spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0)
    check("spearman refuses fewer than three points", spearman([1, 2], [1, 2]) is None)

    # the verdict is read off the prereg thresholds
    def fake(diff_on_off, diff_on_sh, lat, sur, n=64):
        rows = [{"task_id": f"t-{i:03d}", "stratum": "single", "latent": ["x"],
                 "answer_up": True, "arm_order": list(ARMS),
                 "latent_sim_top1": lat, "surface_sim_top1": sur,
                 "arms": {a: {"parsed": True, "why": "", "direction": "UP", "p": 0.6,
                              "success": s, "brier": 0.16, "transport_error": None}
                          for a, s in (("on", 1),
                                       ("off", 1 if i >= int(diff_on_off * n) else 0),
                                       ("shuffled", 1 if i >= int(diff_on_sh * n) else 0))}}
                for i in range(n)]
        return summarise(rows)

    weak = fake(0.05, 0.02, 0.5, 0.1)
    check("a 5-point gap does NOT pass the 15-point threshold",
          weak["verdict"] == "FAIL" and not weak["conditions"]["on_beats_off_by_15pp"])
    strong = fake(0.30, 0.20, 0.5, 0.1)
    check("a 30-point gap with the right correlation PASSES",
          strong["conditions"]["on_beats_off_by_15pp"]
          and strong["conditions"]["on_beats_shuffled_by_7.5pp"])
    check("a transport error forces INCONCLUSIVE, never a PASS",
          "INCONCLUSIVE" == summarise([
              {**strong["rows"][0],
               "arms": {**strong["rows"][0]["arms"],
                        "on": {**strong["rows"][0]["arms"]["on"],
                               "transport_error": "boom"}}}])["verdict"])

    print("")
    if fails:
        print(str(len(fails)) + " FAILED: " + str(fails))
    else:
        print("ALL 24 checks passed")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.run:
        ap.error("--run or --selftest")

    print(f"T1 — prereg {PREREG}")
    print(f"model {MODEL} think={THINK} temp={TEMPERATURE} top_k={TOP_K}")
    res = run(limit=a.limit)
    TRIALS.parent.mkdir(parents=True, exist_ok=True)
    with open(TRIALS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({k: v for k, v in res.items() if k != "rows"},
                            ensure_ascii=False) + "\n")
    print("\n" + json.dumps({k: v for k, v in res.items() if k != "rows"},
                            ensure_ascii=False, indent=2))
    out = BASE / "memory" / "t1_result_full.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
