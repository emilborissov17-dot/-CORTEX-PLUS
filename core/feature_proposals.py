# -*- coding: utf-8 -*-
"""
core/feature_proposals.py — E3: THE BRAIN CHOOSES WHAT TO LOOK AT; THE EXAM DECIDES.
(11 Sep 2026. Emil: "is it the brain, or mechanics? — introduce it NOW.")

The division of labour, stated once so nobody has to guess who chose what:
  BRAIN   (qwen3:8b, core/brain.think — the main model, never the 3B: on 11 Sep the 3B
          read the number 0/9 times, the 8B 9/9) reads the learner's own results and the
          feature catalogue and PROPOSES inputs: {target, feature, why}. Free to propose
          any feature in the grammar, for any target, with its own reason.
  LEARNER (core/direction_learner.py) fits how much each input matters. No human and no
          LLM sets a weight.
  EXAM    runs the learner walk-forward twice on the same days — with and without the
          proposed input — and ACCEPTS only if the per-day log-loss improves by >= 2 standard
          errors and the forced accuracy does not fall. Accepted inputs join that target's
          model in memory/feature_registry.json; every proposal, accepted or refused, is
          appended to memory/feature_proposals.jsonl with the brain's reason and the numbers.
The brain is never told what to propose; if it is silent the night records SILENT, and no
code proposes in its place.

Usage:
  venv\\Scripts\\python.exe core\\feature_proposals.py                       # ask the brain, judge, record
  venv\\Scripts\\python.exe core\\feature_proposals.py --propose TARGET=FEATURE [...]   # a human/Claude proposal, same exam
  venv\\Scripts\\python.exe core\\feature_proposals.py --report              # the current models, no proposals
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import direction_learner as DL  # noqa: E402

REGISTRY = BASE / "memory" / "feature_registry.json"
LOG = BASE / "memory" / "feature_proposals.jsonl"
REPORT = BASE / "claude" / "reports" / "DIRECTION_LEARNER.md"
REPORT_JSON = BASE / "claude" / "reports" / "DIRECTION_LEARNER.json"
HORIZON = 1
MAX_PROPOSALS = 3
Z_ACCEPT = 2.0
MIN_POINTS = 120

SCHEMA = {
    "proposals": "a list of at most 3 objects, each {\"target\": one of the target names, "
                 "\"feature\": one feature name from the catalogue grammar, \"why\": one sentence: what you "
                 "expect this input to tell the learner about the DIRECTION of that target, and why}",
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_series() -> dict:
    try:
        from core.daily_tier import series
        return {k: v for k, v in series().items() if len(v) >= MIN_POINTS}
    except Exception:
        return {}


def registry(path=None) -> dict:
    try:
        d = json.loads((path or REGISTRY).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def features_for(target: str, reg: dict) -> list:
    return list(DL.BASE_FEATURES) + [f for f in (reg.get(target) or {}).get("accepted", []) if f not in DL.BASE_FEATURES]


def judge(all_series: dict, target: str, feature: str, reg: dict, horizon: int = HORIZON) -> dict:
    """With vs without, on the same days. Accept on a paired log-loss improvement of >= 2 SE."""
    ok, why = DL.valid_feature(feature, list(all_series))
    if not ok:
        return {"verdict": "REFUSED", "why": why}
    if target not in all_series:
        return {"verdict": "REFUSED", "why": f"unknown or too-short target {target!r}"}
    base_f = features_for(target, reg)
    if feature in base_f:
        return {"verdict": "REFUSED", "why": "already in the model"}
    a = DL.walk(all_series, target, base_f, horizon)
    b = DL.walk(all_series, target, base_f + [feature], horizon)
    if a.get("error") or b.get("error"):
        return {"verdict": "REFUSED", "why": a.get("error") or b.get("error")}
    ra = {r["date"]: r for r in a["records"]}
    diffs = []
    for r in b["records"]:
        o = ra.get(r["date"])
        if not o:
            continue
        la = -math.log(max(1e-9, o["p_up"] if o["actual"] == "UP" else 1 - o["p_up"]))
        lb = -math.log(max(1e-9, r["p_up"] if r["actual"] == "UP" else 1 - r["p_up"]))
        diffs.append(la - lb)                     # > 0 : the proposal made that day's prediction better
    n = len(diffs)
    if n < 30:
        return {"verdict": "REFUSED", "why": f"only {n} common days"}
    m = sum(diffs) / n
    sd = (sum((d - m) ** 2 for d in diffs) / (n - 1)) ** 0.5 or 1e-9
    n_eff = max(1.0, n / max(1, horizon))
    z = m / (sd / n_eff ** 0.5)
    acc_a, acc_b = a["accuracy_forced"], b["accuracy_forced"]
    accept = z >= Z_ACCEPT and acc_b >= acc_a
    return {"verdict": "ACCEPTED" if accept else "REJECTED", "n_days": n, "logloss_gain_per_day": round(m, 5),
            "z": round(z, 2), "accuracy_without": acc_a, "accuracy_with": acc_b,
            "confident_accuracy_with": b.get("accuracy_when_confident"), "committed_share_with": b.get("committed_share"),
            "why": (f"log-loss better by {m:.4f}/day at z={z:.2f}, accuracy {acc_a} -> {acc_b}" if accept else
                    f"z={z:.2f} (needs {Z_ACCEPT}) and/or accuracy {acc_a} -> {acc_b}")}


def catalogue(all_series: dict) -> str:
    names = sorted(all_series)
    return ("FEATURE GRAMMAR (W is a number of days, 2..60):\n"
            "  own_lag1, own_lag2, own_lag3   the target's last three daily moves (always in the model)\n"
            "  ret_W    % change of the target over the last W days\n"
            "  vol_W    volatility: std of the target's daily moves over the last W days\n"
            "  zdev_W   how far today's value is from its W-day mean, in standard deviations\n"
            "  dow      day of the week\n"
            "  x_move:<series>     another series' last daily move\n"
            "  x_ret_W:<series>    another series' % change over W days\n"
            "SERIES: " + ", ".join(names))


def results_table(all_series: dict, reg: dict) -> tuple[str, dict]:
    lines, out = [], {}
    for t in sorted(all_series):
        r = DL.walk(all_series, t, features_for(t, reg), HORIZON)
        out[t] = {k: v for k, v in r.items() if k != "records"}
        if r.get("error"):
            lines.append(f"{t}: {r['error']}")
            continue
        lines.append(f"{t}: inputs={r['features']} accuracy={r['accuracy_forced']} vs baseline "
                     f"{r['baseline_hindsight_majority']} (z={r['z_vs_baseline']}), confident on "
                     f"{r['committed_share']} of days with accuracy {r['accuracy_when_confident']}, "
                     f"weights={r['weights']}")
    return "\n".join(lines), out


def brain_propose(table: str, cat: str, past: list) -> tuple[list, str]:
    """(proposals, status). The 8B brain; a silent brain is SILENT, never replaced by code."""
    try:
        from core import brain
    except Exception as exc:  # noqa: BLE001
        return [], f"NO_BRAIN: {type(exc).__name__}"
    history = "\n".join(f"{p.get('target')} + {p.get('feature')}: {p.get('verdict')} ({p.get('why', '')[:90]})"
                        for p in past[-12:]) or "(none yet)"
    q = ("You are the researcher of your own direction learner. It predicts, for each series, whether tomorrow "
         "is UP or DOWN, and it can abstain. Below: what it sees now and how it scores, the inputs you may add, "
         "and your earlier proposals with the exam's verdicts. Propose up to 3 inputs that you expect to improve "
         "the prediction of DIRECTION for a named target. Each will be tested on days the learner has not seen; "
         "only real improvement is kept. Do not repeat a refused proposal unless you say what is different.")
    ans = brain.think("researcher of the direction learner", q,
                      evidence=f"CURRENT MODELS:\n{table}\n\n{cat}\n\nYOUR EARLIER PROPOSALS:\n{history}",
                      schema=SCHEMA, kind="feature_proposal", remember_it=True, fast=False, temperature=0.4)
    if not isinstance(ans, dict):
        return [], "SILENT"
    props = ans.get("proposals")
    if not isinstance(props, list):
        return [], "MALFORMED"
    return [p for p in props if isinstance(p, dict)][:MAX_PROPOSALS], f"OK:{ans.get('_model', '?')}"


def _append(path: Path, row: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _past(path=None) -> list:
    try:
        return [json.loads(l) for l in (path or LOG).read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []


def run(all_series=None, proposals=None, proposer=None, reg_path=None, log_path=None, report=True) -> dict:
    """proposals=None -> ask the brain. Each proposal is judged; accepted ones enter the registry."""
    all_series = load_series() if all_series is None else all_series
    reg_path, log_path = reg_path or REGISTRY, log_path or LOG
    reg = registry(reg_path)
    table, models = results_table(all_series, reg)
    status, source = "GIVEN", "human/claude"
    if proposals is None:
        proposals, status = (proposer or brain_propose)(table, catalogue(all_series), _past(log_path))
        source = "brain"
    results = []
    for p in proposals:
        target, feature = str(p.get("target", "")), str(p.get("feature", ""))
        v = judge(all_series, target, feature, reg)
        row = {"ts": _now(), "source": source, "status": status, "target": target, "feature": feature,
               "brain_why": str(p.get("why", ""))[:300], **v}
        _append(log_path, row)
        results.append(row)
        if v["verdict"] == "ACCEPTED":
            e = reg.setdefault(target, {"accepted": [], "history": []})
            e["accepted"].append(feature)
            e["history"].append({"ts": row["ts"], "feature": feature, "source": source, "z": v["z"]})
    if any(r["verdict"] == "ACCEPTED" for r in results):
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
        table, models = results_table(all_series, reg)
    out = {"ts": _now(), "status": status, "proposals": results, "models": models}
    if report:
        _write_report(out)
    return out


def _write_report(out: dict):
    L = ["# DIRECTION LEARNER — who chose what", "",
         "**Постановка.** Question: will the series be UP or DOWN tomorrow? The learner (logistic regression, "
         "walk-forward, refitted every 5 days on past days only) outputs P(up); inside a band around 0.5, whose "
         "width it learns from its own past record, it answers UNCONFIDENT_TO_CHOOSE. The BRAIN (qwen3:8b) "
         "chooses which inputs to add; the EXAM keeps an input only if it improves the per-day log-loss by "
         ">= 2 SE on days not seen. Baseline: the better of always-up / always-down, in hindsight. "
         "Known weaknesses: linear in its inputs; one day ahead; inputs limited to the daily tier.", "",
         f"_{out['ts']} · proposals: {out['status']}_", "",
         "| target | inputs | accuracy | baseline | z | confident share | accuracy when confident | last decision (why) |",
         "|---|---|---:|---:|---:|---:|---:|---|"]
    for t, m in out["models"].items():
        if m.get("error"):
            L.append(f"| {t} | — | — | — | — | — | — | {m['error']} |")
            continue
        last = m.get("last") or {}
        L.append(f"| {t} | {', '.join(m['features'])} | {m['accuracy_forced']} | {m['baseline_hindsight_majority']} | "
                 f"{m['z_vs_baseline']} | {m['committed_share']} | {m['accuracy_when_confident']} | "
                 f"{last.get('date', '')} {last.get('decision', '')} p={last.get('p_up')} ({', '.join(f'{n} {c:+}' for n, c in last.get('why', []))}) |")
    L += ["", "## Proposals tonight", "", "| source | target | feature | brain's reason | verdict | numbers |", "|---|---|---|---|---|---|"]
    for p in out["proposals"]:
        L.append(f"| {p['source']} | {p['target']} | {p['feature']} | {p.get('brain_why', '')[:120]} | **{p['verdict']}** | {p.get('why', '')} |")
    if not out["proposals"]:
        L.append(f"| — | — | — | — | {out['status']} | no proposal |")
    try:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
        REPORT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--report" in args:
        o = run(proposals=[])
    elif "--propose" in args:
        given = [dict(zip(("target", "feature"), a.split("=", 1))) for a in args[args.index("--propose") + 1:] if "=" in a]
        o = run(proposals=given)
    else:
        o = run()
    for p in o["proposals"]:
        print(f"[E3] {p['source']:12s} {p['target']} + {p['feature']}: {p['verdict']} — {p.get('why')}")
    for t, m in o["models"].items():
        print(f"[E3] {t}: {m.get('features')} acc={m.get('accuracy_forced')} base={m.get('baseline_hindsight_majority')} "
              f"z={m.get('z_vs_baseline')} confident={m.get('committed_share')}@{m.get('accuracy_when_confident')}")
    print(f"[E3] proposals: {o['status']}")
