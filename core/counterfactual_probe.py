# -*- coding: utf-8 -*-
"""
core/counterfactual_probe.py — POINT 13: understanding versus simulation.
(11 Sep 2026. Task #61. Claude accountable.)

THE TEST. Take a judgement the brain makes from a number — "is this indicator
over its signed red line?" — and ask it three times on the same material:

  base     the real number                         truth = T
  flipped  the number mirrored across the line     truth = not T
  noise    the real number, an irrelevant detail   truth = T
           changed (the observation date)

A system that UNDERSTANDS the material moves its verdict with the number and
only with the number: base right, flipped right, noise unchanged. A system that
SIMULATES understanding answers from the shape of the prompt: the verdict stays
put when the number flips (INSENSITIVE), or moves when only the date moved
(NOISE_DRIVEN). Nothing here is graded by an LLM; the truth is arithmetic on the
signed band, and the verdict is a two-word category the brain must pick.

Cases come from two places the cycle already writes:
  * fixed indicator bands (config/alarm_indicators.json) with an ACCEPTED value;
  * measurable targets (config/target_config.json) with a current goal-score value.
Nothing is invented; a case without a number is not a case.

Outputs:
  memory/counterfactual_probe.jsonl        one row per case per run (append)
  memory/counterfactual_probe_latest.json  summary of the last run
Reads by scripts/agi_scoreboard.py (point 13).

Usage:
  venv\\Scripts\\python.exe core\\counterfactual_probe.py            # run against the brain
  venv\\Scripts\\python.exe core\\counterfactual_probe.py --dry     # list the cases, ask nothing
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LOG = BASE / "memory" / "counterfactual_probe.jsonl"
LATEST = BASE / "memory" / "counterfactual_probe_latest.json"
TARGETS = BASE / "config" / "target_config.json"

OVER, UNDER = "OVER", "UNDER"
TRACKS, INSENSITIVE, NOISE_DRIVEN, WRONG, SILENT = "TRACKS", "INSENSITIVE", "NOISE_DRIVEN", "WRONG", "SILENT"
RATE_LIMITED = "RATE_LIMITED"   # the host refused the call; the mind never saw the question
SCHEMA = {"verdict": "exactly one word: OVER if the value is on the bad side of the line, UNDER if it is not",
          "reason": "one sentence, from the material"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ── cases ────────────────────────────────────────────────────────────────────

def truth(value: float, line: float, direction: str) -> str:
    """OVER = on the bad side. Arithmetic, no model."""
    if direction == "lower_better":
        return OVER if value > line else UNDER
    if direction == "higher_better":
        return OVER if value < line else UNDER
    raise ValueError(f"unusable direction {direction!r}")


def bounds(unit: str, value: float | None = None, line: float | None = None) -> tuple[float | None, float | None]:
    """The domain a counterfactual must stay inside: percentages 0..100; indices and
    scores 0..1 when the line itself is <= 1; any quantity observed non-negative with a
    non-negative line stays >= 0 (counts, ppm, people, rates). A flipped value outside
    the domain would test the brain on a number that cannot exist (-3.5 % undernourished,
    -27 million refugees)."""
    u = (unit or "").lower()
    if "percent" in u or "%" in u:
        return 0.0, 100.0
    lo = 0.0 if (value is None or value >= 0) and (line is None or line >= 0) else None
    if any(w in u for w in ("index", "score")) or (line is not None and 0 < line <= 1.0 and value is not None and 0 <= value <= 1.0):
        return lo, 1.0
    return lo, None


def mirror(value: float, line: float, unit: str = "") -> float | None:
    """The same distance from the line, on the other side (never exactly on it), kept
    inside the unit's domain; None when no value on the other side exists there
    (e.g. a higher_better line of 100 %: nothing above it)."""
    lo, hi = bounds(unit, value, line)
    m = line + (line - value)
    if m == line:
        m = line + (abs(line) * 0.1 or 1.0)
    if lo is not None and m < lo:
        m = (lo + line) / 2 if line > lo else None
    if m is not None and hi is not None and m > hi:
        m = (line + hi) / 2 if line < hi else None
    if m is None or m == line:
        return None
    return round(m, 4)


def indicator_cases(bands=None, series=None) -> list[dict]:
    """Fixed bands with an ACCEPTED value."""
    from core import alarm_bands as ab
    bands = ab.indicator_bands() if bands is None else bands
    try:
        series = ab.indicator_values() if series is None else series
    except Exception:
        series = {}
    out = []
    for key, band in bands.items():
        if band.get("rule") != "fixed" or band.get("direction") not in ("lower_better", "higher_better"):
            continue
        line, hist = _num(band.get("threshold")), series.get(key) or []
        if line is None or not hist:
            continue
        date, value = hist[-1]
        out.append({"case": f"indicator:{key}", "value": float(value), "line": line,
                    "direction": band["direction"], "unit": band.get("unit") or "", "date": date or "",
                    "kind": "signed red line", "source": "config/alarm_indicators.json + verified_observations"})
    return out


def target_cases(targets_path=None, values=None) -> list[dict]:
    """Measurable targets with a current value in the goal score."""
    from core import alarm_bands as ab
    try:
        cfg = json.loads((targets_path or TARGETS).read_text(encoding="utf-8"))
    except Exception:
        return []
    values = ab.values() if values is None else values
    # target_config is nested: {group: {axis: spec}}. The first live run (11 Sep) iterated the
    # groups, found no target_value, and produced 0 target cases; alarm_bands.axes() flattens
    # it the same way this does.
    flat = {}
    for key, spec in cfg.items():
        if key.startswith("_") or not isinstance(spec, dict):
            continue
        if "target_value" in spec or "primary_metric" in spec:
            flat[key] = spec
        else:
            for axis, sub in spec.items():
                if isinstance(sub, dict) and not axis.startswith("_"):
                    flat[axis] = sub
    out = []
    for axis, spec in flat.items():
        line, direction = _num(spec.get("target_value")), spec.get("direction")
        value = _num(values.get(axis))
        if line is None or value is None or direction not in ("lower_better", "higher_better"):
            continue
        out.append({"case": f"target:{axis}", "value": value, "line": line, "direction": direction,
                    "unit": spec.get("unit") or "", "date": "", "kind": "ratified target",
                    "source": "config/target_config.json + goal_score"})
    return out


def cases(**kw) -> list[dict]:
    return indicator_cases(kw.get("bands"), kw.get("series")) + target_cases(kw.get("targets_path"), kw.get("values"))


# ── the three prompts ────────────────────────────────────────────────────────

def material(c: dict, value: float, date: str) -> str:
    side = "higher is worse" if c["direction"] == "lower_better" else "lower is worse"
    when = f" observed on {date}" if date else ""
    return (f"{c['case']}\nvalue: {value} {c['unit']}{when}\n"
            f"line ({c['kind']}): {c['line']} {c['unit']} — {side}\n")


QUESTION = ("Is the value on the bad side of the line? Answer from the two numbers in the material only. "
            "OVER means it is on the bad side; UNDER means it is not.")


def _shift_date(date: str, days: int = 1) -> str:
    try:
        return (datetime.fromisoformat(date).date() - timedelta(days=days)).isoformat()
    except (TypeError, ValueError):
        return "2026-01-01"          # no date on the case: a date is still an irrelevant detail


def variants(c: dict) -> dict:
    """base / flipped / noise: material + truth for each."""
    v, line, d = c["value"], c["line"], c["direction"]
    flipped = mirror(v, line, c.get("unit", ""))
    if flipped is None:
        return {}
    return {"base": {"material": material(c, v, c["date"]), "truth": truth(v, line, d), "value": v},
            "flipped": {"material": material(c, flipped, c["date"]), "truth": truth(flipped, line, d), "value": flipped},
            "noise": {"material": material(c, v, _shift_date(c["date"] or "2026-01-02")), "truth": truth(v, line, d), "value": v}}


def unavailable(answer) -> str | None:
    """The host's reason for not answering, or None. Kept separate from a verdict
    so a rate limit can be counted apart from a mind that stayed quiet."""
    if isinstance(answer, dict) and answer.get("_unavailable"):
        return str(answer["_unavailable"])
    return None


def normalise(answer) -> str | None:
    if not isinstance(answer, dict):
        return None
    v = str(answer.get("verdict") or "").strip().upper()
    if v.startswith(OVER):
        return OVER
    if v.startswith(UNDER):
        return UNDER
    return None


def outcome(base: str | None, flipped: str | None, noise: str | None, vs: dict,
            refusals: list | None = None) -> str:
    if refusals:
        return RATE_LIMITED          # the host said no; nothing was asked of the mind
    if None in (base, flipped, noise):
        return SILENT
    if base == flipped:
        return INSENSITIVE               # the number flipped, the verdict did not
    if noise != base:
        return NOISE_DRIVEN              # only the date moved, the verdict moved
    if base == vs["base"]["truth"] and flipped == vs["flipped"]["truth"]:
        return TRACKS
    return WRONG                         # moved with the number, in the wrong direction


# ── asking ───────────────────────────────────────────────────────────────────

LEAN = "+lean"      # asker suffix: the same mind, the same question, without the self-wrapper


def brain_ask(question: str, evidence: str, schema: dict, lean: bool = False):
    """Default asker: the brain's MAIN model (the one that judges the cycle — the fast 3B
    model is known to fail numeric barriers, and a probe of it would test the wrong brain),
    nothing remembered (a probe is not a verdict). The answer carries `_model`."""
    from core import brain
    return brain.think("probe: read two numbers", question, evidence=evidence, schema=schema,
                       kind="counterfactual_probe", remember_it=False, fast=False, temperature=0.0, lean=lean)


def brain_fast_ask(question: str, evidence: str, schema: dict, lean: bool = False):
    """The brain's FAST model — the one used for per-indicator judgements dozens of times a night."""
    from core import brain
    return brain.think("probe: read two numbers", question, evidence=evidence, schema=schema,
                       kind="counterfactual_probe", remember_it=False, fast=True, temperature=0.0, lean=lean)


def groq_asker(model: str):
    """An asker on GroqCloud's free plan. Only models in consult.GROQ_FREE_MODELS are allowed
    (Law of the brain, point 4: free or local only) — anything else raises before a call."""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("consult", BASE / "experiments" / "kimi_duel" / "consult.py")
    consult = _ilu.module_from_spec(spec)
    spec.loader.exec_module(consult)
    free = set(getattr(consult, "GROQ_FREE_MODELS", set()))
    try:                      # the cycle's own workhorse runs on the same free key every night
        import core.groq_backend as _gb
        free.add(_gb.GROQ_MODEL)
    except Exception:
        pass
    if model not in free:
        raise ValueError(f"{model!r} is not in GROQ_FREE_MODELS {sorted(free)} — refused, nothing called")

    def ask(question: str, evidence: str, schema: dict):
        import requests
        import core.groq_backend as gb
        key = gb._load_key("GROQ_API_KEY")
        if not key:
            return None
        fields = "\n".join(f'  "{k}": ... // {v}' for k, v in schema.items())
        prompt = f"{question}\n\nMATERIAL:\n{evidence}\nAnswer ONLY with JSON:\n{{\n{fields}\n}}"
        r = requests.post(consult.GROQ_URL, timeout=60,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"model": model, "temperature": 0, "max_tokens": 200,
                                "response_format": {"type": "json_object"},
                                "messages": [{"role": "user", "content": prompt}]})
        if r.status_code != 200:
            return None
        d = r.json()
        txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        try:
            out = json.loads(txt)
        except ValueError:
            return None
        if isinstance(out, dict):
            out["_model"] = f"groq:{d.get('model') or model}"
        return out
    return ask


def nvidia_kimi_ask(question: str, evidence: str, schema: dict):
    """Kimi K2 on NVIDIA NIM's free developer tier (the Groq road closed 15 Apr 2026)."""
    import requests
    import core.groq_backend as gb
    key = gb._load_key("NVIDIA_API_KEY")
    if not key:
        return None
    model = gb._nvidia_model(key)
    fields = "\n".join(f'  "{k}": ... // {v}' for k, v in schema.items())
    prompt = f"{question}\n\nMATERIAL:\n{evidence}\nAnswer ONLY with JSON:\n{{\n{fields}\n}}"
    r = requests.post(gb.NVIDIA_API_URL, timeout=120,
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": model, "temperature": 0, "max_tokens": 300,
                            "messages": [{"role": "user", "content": prompt}]})
    if r.status_code != 200:
        # A REFUSAL BY THE HOST IS NOT A SILENCE BY THE MIND (11 Sep 2026).
        # This returned a bare None, identical to an unparseable reply, so the
        # probe counted SILENT and the [PROBE] line read
        #   nvidia-kimi n=9 answered=1 tracks_rate=1.0 ... SILENT 8
        # which looks like a mind that would not speak. The real cause, caught by
        # replaying the same call by hand: HTTP 429 {"title":"Too Many Requests"}.
        # A 1.0 rate over ONE answered case is not a measurement, and blaming the
        # model for the rate limiter is the wrong story to leave on disk.
        return {"_unavailable": f"HTTP {r.status_code}"}
    d = r.json()
    txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    txt = txt.split("</think>")[-1].strip()
    if txt.startswith("```"):
        txt = txt.strip("`").split("\n", 1)[-1]
    try:
        out = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
    except ValueError:
        return None
    if isinstance(out, dict):
        out["_model"] = f"nvidia:{d.get('model') or model}"
    return out


def local_asker(model: str, lean: bool = False):
    """A named local Ollama model through the brain's own door (e.g. local:cortex-l1-3b, the
    L1 LoRA of qwen2.5:3b). If the model is not installed, brain.think says so and falls back —
    and the `model` field of every row shows which model really answered, so a fallback can
    never be mistaken for the fine-tuned mind."""
    # ── A FALLBACK IS NOT AN ANSWER FROM THE ASKED MIND (12 Sep 2026) ──────────
    # The first probe of cortex-l1-3b asked for "cortex-l1-3b"; Ollama lists it as
    # "cortex-l1-3b:latest", brain.think found no exact match, fell back to qwen3:8b,
    # and every "cortex-l1-3b" answer on file came from the 8B (llm_provenance:
    # requested=cortex-l1-3b, model=qwen3:8b, 16 of 16). The score would have credited
    # the fine-tune with the big brain's reading. Two guards: resolve the ":latest"
    # tag before asking, and if another model answered anyway, return it as
    # unavailable — never as the asked mind's verdict.
    def resolve() -> str:
        from core import brain
        have = brain.models()
        if model in have:
            return model
        if f"{model}:latest" in have:
            return f"{model}:latest"
        return model

    def ask(question: str, evidence: str, schema: dict):
        from core import brain
        name = resolve()
        out = brain.think("probe: read two numbers", question, evidence=evidence, schema=schema,
                          kind="counterfactual_probe", remember_it=False, fast=False, temperature=0.0,
                          model_override=name, lean=lean)
        answered = str((out or {}).get("_model") or "") if isinstance(out, dict) else ""
        if answered and answered.split("local:", 1)[-1] != name:
            return {"_unavailable": f"asked {name}, answered {answered} (fallback)"}
        return out
    return ask


def askers(names: list[str]) -> dict:
    """name -> ask function. 'brain' (main local model), 'brain-fast', 'nvidia-kimi', 'groq:<model>'."""
    out = {}
    for n in names:
        # "<asker>+lean": the same mind asked without the self-wrapper (BODY, the five
        # self-state rows, SPIRIT, MEMORY). Asking both is how "the long prompt drowns
        # the numbers" stops being a hypothesis and becomes two rows in the same table.
        base, lean = (n[:-len(LEAN)], True) if n.endswith(LEAN) else (n, False)
        if base == "brain":
            out[n] = (lambda q, e, sc, _l=lean: brain_ask(q, e, sc, lean=_l))
        elif base == "brain-fast":
            out[n] = (lambda q, e, sc, _l=lean: brain_fast_ask(q, e, sc, lean=_l))
        elif base.startswith("local:"):
            out[n] = local_asker(base.split(":", 1)[1], lean=lean)
        elif base == "nvidia-kimi":
            out[n] = nvidia_kimi_ask
        elif base.startswith("groq:"):
            out[n] = groq_asker(base.split(":", 1)[1])
        else:
            raise ValueError(f"unknown asker {n!r}")
    return out


def compare(names: list[str], case_list=None, out_path=None, now=None) -> dict:
    """The same cases, several minds. Does reading the number scale with the model?
    Writes memory/counterfactual_probe_by_model.json; the nightly summary (LATEST) is not touched."""
    import tempfile
    case_list = cases() if case_list is None else case_list
    res = {"ts": now or _now(), "cases": len(case_list), "by_model": {}}
    for name, ask in askers(names).items():
        with tempfile.TemporaryDirectory() as d:
            s = run(ask=ask, case_list=case_list, log=Path(d) / "l.jsonl", latest=Path(d) / "s.json", now=res["ts"])
            rows = [json.loads(l) for l in (Path(d) / "l.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        res["by_model"][name] = {k: s[k] for k in ("n", "answered", "counts", "tracks_rate")}
        res["by_model"][name]["models_seen"] = sorted({m for r in rows for m in r.get("model", [])})
        res["by_model"][name]["per_case"] = {r["case"]: r["outcome"] for r in rows}
    try:
        p = out_path or (BASE / "memory" / "counterfactual_probe_by_model.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        res["write_error"] = f"{type(exc).__name__}: {exc}"
    return res


def run(ask=None, case_list=None, log=None, latest=None, now=None) -> dict:
    ask = ask or brain_ask
    case_list = cases() if case_list is None else case_list
    log, latest = log or LOG, latest or LATEST
    ts = now or _now()
    rows = []
    skipped = []
    for c in case_list:
        vs = variants(c)
        if not vs:
            skipped.append(c["case"])          # no counterfactual exists inside the unit's domain
            continue
        got, models, reasons = {}, set(), {}
        refusals = []            # the host said no — kept apart from a quiet mind
        for name in ("base", "flipped", "noise"):
            try:
                ans = ask(QUESTION, vs[name]["material"], SCHEMA)
                got[name] = normalise(ans)
                why = unavailable(ans)
                if why:
                    refusals.append(f"{name}: {why}")
                if isinstance(ans, dict):
                    if ans.get("_model"):
                        models.add(str(ans["_model"]))
                    reasons[name] = str(ans.get("reason") or "")[:160]
            except Exception:
                got[name] = None
        o = outcome(got["base"], got["flipped"], got["noise"], vs, refusals)
        if refusals:
            reasons["_unavailable"] = "; ".join(sorted(set(refusals)))
        rows.append({"ts": ts, "case": c["case"], "source": c["source"], "value": c["value"], "line": c["line"],
                     "direction": c["direction"], "flipped_value": vs["flipped"]["value"],
                     "truth": {k: vs[k]["truth"] for k in vs}, "verdict": got, "reason": reasons,
                     "model": sorted(models), "outcome": o})
    counts = {k: sum(1 for r in rows if r["outcome"] == k)
              for k in (TRACKS, INSENSITIVE, NOISE_DRIVEN, WRONG, SILENT, RATE_LIMITED)}
    answered = len(rows) - counts[SILENT] - counts[RATE_LIMITED]
    summary = {"ts": ts, "n": len(rows), "answered": answered, "counts": counts, "skipped_no_counterfactual": skipped,
               "tracks_rate": round(counts[TRACKS] / answered, 3) if answered else None,
               "reading": ("the verdict follows the number and only the number" if answered and counts[TRACKS] == answered
                           else "no case answered" if not answered
                           else f"{counts[INSENSITIVE]} case(s) kept the verdict when the number flipped, "
                                f"{counts[NOISE_DRIVEN]} moved on a date change, {counts[WRONG]} moved the wrong way")}
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        latest.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        summary["write_error"] = f"{type(exc).__name__}: {exc}"
    return summary


if __name__ == "__main__":
    if "--dry" in sys.argv:
        for c in cases():
            vs = variants(c)
            if not vs:
                print(f"{c['case']}: {c['value']} vs {c['line']} ({c['direction']}) — no counterfactual inside the domain, skipped")
                continue
            print(f"{c['case']}: {c['value']} vs {c['line']} ({c['direction']}) truth {vs['base']['truth']}, "
                  f"flipped {vs['flipped']['value']} -> {vs['flipped']['truth']}")
        sys.exit(0)
    if "--compare" in sys.argv:
        # e.g.  --compare brain brain-fast groq:openai/gpt-oss-120b nvidia-kimi
        names = [a for a in sys.argv[sys.argv.index("--compare") + 1:] if not a.startswith("--")] or ["brain", "brain-fast"]
        r = compare(names)
        for n, m in r["by_model"].items():
            print(f"[PROBE] {n:45s} n={m['n']} answered={m['answered']} tracks_rate={m['tracks_rate']} {m['counts']} models={m['models_seen']}")
        sys.exit(0 if r["cases"] else 2)
    s = run()
    print(json.dumps(s, ensure_ascii=False, indent=1))
    sys.exit(0 if s["n"] else 2)
