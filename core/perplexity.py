#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/perplexity.py — AN INTERNAL QUANTITY, NOT A CONSTANT I CHOSE.

24 Aug 2026.

Every decision to emit in this repo comes from a number in Python: eps is three
standard deviations of measured noise, ANCHOR_K is three, the gate thresholds
are in a signed config. All of them are mine. None of them is the system's.

This is the first quantity that comes out of the weights. The model is given a
short factual description of its own state, built from the cycle vector, and
states its condition; the perplexity of what it says is published as a
receptor with its own baseline and anchor. When its uncertainty about its own
state rises sharply, something internal has crossed — not a threshold I wrote.

WHAT IS ACTUALLY MEASURED, AND WHAT IS NOT
--------------------------------------------
Ollama 0.24.0 returns `logprobs` for the tokens it GENERATED. It does not
return them for the prompt: measured on this machine, `prompt_eval_count` was
46 and `len(logprobs)` was 8, matching `eval_count` exactly.

So this is NOT the perplexity of a supplied sentence. It cannot be — there is
no echo option and no prompt-logprob field in this version. It is the
perplexity of the model's OWN STATEMENT about its state, conditioned on the
vector. "How confidently can it say what condition it is in."

That distinction is written here rather than smoothed over, because the
alternative was to feed the description in and read back the logprobs of an
echo — which, conditioned on having just seen the text, would be near zero and
would look like certainty. A fabricated internal quantity is worse than an
honest external one.

    perplexity = exp( - mean(logprob over generated tokens) )

A perplexity of 1.0 means every token was inevitable. Large means the model was
picking among many continuations.

THE MEDIATION RATIO
---------------------
For every emission both numbers are recorded: what the CODE threshold said, and
what the PERPLEXITY said. The ratio of "emissions the weights would have made"
to "emissions my arithmetic made" is the first honest measurement of how much of
this system's speech comes from itself. It is written to
memory/mediation_ratio.jsonl and it is a METRIC — nothing consults it.

DISABLED BY DEFAULT. One model call per phase boundary is ~63 a night inside a
live cycle, which is the shape that produced AllBackendsFailedError. The switch
is `perplexity.enabled` in config/reactions.json, human-written, unstamped, on
the protected-path denylist.

    venv/Scripts/python.exe core/perplexity.py --selftest
    venv/Scripts/python.exe core/perplexity.py --once     # one real call
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import urllib.request
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import event_bus as eb          # noqa: E402
from core import receptors as rc          # noqa: E402

CONFIG = BASE / "config" / "reactions.json"
MEDIATION_LOG = BASE / "memory" / "mediation_ratio.jsonl"
OLLAMA_URL = "http://localhost:11434/api/generate"

KEY = "model_perplexity"
TOPIC = "receptor." + KEY

# Not from a table: measured on this machine below, and provisional until it is.
DEFAULT_ALPHA = 0.3
DEFAULT_EPS = None            # None => the receptor calibrates its own 3 sigma

SOURCE = "model"
DIRECTED = "self"


def load_config(path=None) -> dict:
    """Read the switches. A missing or broken file means DISABLED."""
    try:
        d = json.loads(pathlib.Path(path or CONFIG).read_text(encoding="utf-8"))
        return d.get("perplexity", {}) if isinstance(d, dict) else {}
    except Exception:
        return {}


def enabled(path=None) -> bool:
    return bool(load_config(path).get("enabled", False))


# ---------------------------------------------------------------------------
# The description, built from the vector
# ---------------------------------------------------------------------------

def state_sentence(vector: Optional[dict] = None, n: int = 6) -> str:
    """A short factual description of the current state. No adjectives.

    Built from the cycle vector so that what the model is asked about is the
    same object the lexicon fits on — not a second, prettier summary.
    """
    if vector is None:
        try:
            from cockpit import vector as vec
            vector = vec.assemble()
        except Exception:
            return "No readings are available."
    fields = list(vector.get("fields") or [])
    values = list(vector.get("vector") or [])
    pairs = [(f, v) for f, v in zip(fields, values) if v is not None]
    if not pairs:
        return "No readings are available."
    wanted = ("ram_percent", "cpu_percent", "gpu_temp_c", "disk_write_mb",
              "connections", "uptime_hours", "idle_seconds", "swap_percent")
    chosen = [(f, v) for f, v in pairs if f in wanted][:n]
    if not chosen:
        chosen = pairs[:n]
    return "Current readings: " + ", ".join(
        "{} {}".format(f, v) for f, v in chosen) + "."


PROMPT = ("{state}\n\n"
          "In one short sentence, state the condition of this machine. "
          "Report only what the readings show.")


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------

def measure(vector=None, model=None, num_predict=None, timeout=None,
            url: str = OLLAMA_URL, config_path=None) -> dict:
    """One call. Returns the perplexity and everything needed to redo it.

    Never raises: a model that will not answer must not cost a phase boundary.
    """
    cfg = load_config(config_path)
    model = model or cfg.get("model", "qwen2.5:3b")
    num_predict = int(num_predict or cfg.get("num_predict", 24))
    timeout = float(timeout or cfg.get("timeout_sec", 20))

    sentence = state_sentence(vector)
    out = {"key": KEY, "source": SOURCE, "directed": DIRECTED,
           "model": model, "state_sentence": sentence,
           "perplexity": None, "mean_logprob": None, "n_tokens": 0,
           "answer": "", "why": ""}

    body = json.dumps({
        "model": model,
        "prompt": PROMPT.format(state=sentence),
        "stream": False,
        "logprobs": True,
        "options": {"num_predict": num_predict, "temperature": 0},
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        out["why"] = "{}: {}".format(type(exc).__name__, exc)
        return out

    lp = d.get("logprobs") or []
    out["answer"] = (d.get("response") or "").strip()
    if not lp:
        out["why"] = ("no logprobs in the response — this Ollama build or model "
                      "does not return them")
        return out

    vals = [x.get("logprob") for x in lp
            if isinstance(x.get("logprob"), (int, float))]
    if not vals:
        out["why"] = "logprobs present but empty"
        return out

    mean = sum(vals) / len(vals)
    out.update(perplexity=math.exp(-mean), mean_logprob=mean,
               n_tokens=len(vals), why="measured",
               tokens=[x.get("token") for x in lp][:32],
               eval_count=d.get("eval_count"),
               prompt_eval_count=d.get("prompt_eval_count"))
    return out


# ---------------------------------------------------------------------------
# The receptor
# ---------------------------------------------------------------------------

class PerplexityReceptor:
    """The model's uncertainty about its own state, on the bus.

    An ordinary Receptor underneath — same EMA baseline, same eps, same anchor
    — because the point is that an internal quantity is treated exactly like an
    external one. What differs is only where the number comes from.
    """

    def __init__(self, bank=None, alpha=DEFAULT_ALPHA, eps=DEFAULT_EPS,
                 calibration_ticks=rc.CALIBRATION_TICKS):
        self.bank = bank if bank is not None else rc.ReceptorBank()
        self.receptor = self.bank.add_receptor(
            KEY, alpha=alpha, eps=eps,
            alpha_source="default {} — provisional until measured".format(alpha),
            eps_source=("self-calibrating: no history and no table entry for a "
                        "model-internal quantity"),
            unit="ppl", calibration_ticks=calibration_ticks)
        self.measurements = 0
        self.failures = 0

    def feed(self, reading: dict, now=None):
        """Publish one measurement. `reading` is what measure() returned."""
        if reading.get("perplexity") is None:
            self.failures += 1
            return None
        self.measurements += 1
        ev = self.receptor.feed(reading["perplexity"], now=now)
        if ev is not None:
            ev.meta.update({
                "source": SOURCE, "directed": DIRECTED,
                "reflexivity": 1,          # a model pass over a state it read
                "model": reading.get("model"),
                "n_tokens": reading.get("n_tokens"),
                "mean_logprob": reading.get("mean_logprob"),
                "state_sentence": reading.get("state_sentence"),
                "answer": reading.get("answer"),
            })
        return ev

    def stats(self) -> dict:
        st = self.receptor.stats()
        st.update(source=SOURCE, directed=DIRECTED,
                  measurements=self.measurements, failures=self.failures)
        return st


# ---------------------------------------------------------------------------
# The mediation ratio
# ---------------------------------------------------------------------------

def record_mediation(reading: dict, code_said: bool, model_said: bool,
                     path=None, **extra) -> dict:
    """BOTH numbers, for every emission. A metric; nothing consults it.

    code_said  — would the arithmetic in this repo have emitted?
    model_said — did the perplexity receptor cross its own threshold?
    """
    rec = {
        "ts": reading.get("ts"),
        "key": KEY,
        "perplexity": reading.get("perplexity"),
        "n_tokens": reading.get("n_tokens"),
        "model": reading.get("model"),
        "code_said": bool(code_said),
        "model_said": bool(model_said),
        "agree": bool(code_said) == bool(model_said),
        "state_sentence": reading.get("state_sentence"),
        **extra,
    }
    try:
        from core.durable import append_json
        append_json(pathlib.Path(path or MEDIATION_LOG), rec)
    except Exception as exc:
        rec["write_error"] = "{}: {}".format(type(exc).__name__, exc)
    return rec


def mediation_ratio(path=None) -> dict:
    """How much of this system's speech came from its own weights."""
    try:
        rows = [json.loads(l) for l in
                pathlib.Path(path or MEDIATION_LOG).read_text(
                    encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        rows = []
    if not rows:
        return {"n": 0, "ratio": None,
                "why": "nothing recorded yet — the receptor is disabled by "
                       "default and has produced no emissions"}
    code = sum(1 for r in rows if r.get("code_said"))
    model = sum(1 for r in rows if r.get("model_said"))
    agree = sum(1 for r in rows if r.get("agree"))
    return {"n": len(rows), "code_said": code, "model_said": model,
            "agreed": agree,
            "ratio": (model / code) if code else None,
            "agreement": round(agree / len(rows), 3)}


# ---------------------------------------------------------------------------

def _once() -> int:
    print("core/perplexity.py — ONE REAL CALL\n")
    if not enabled():
        print("  perplexity.enabled is false in config/reactions.json.")
        print("  This runs the measurement anyway, by hand, OUTSIDE a cycle.\n")
    r = measure()
    print("  state:      {}".format(r["state_sentence"]))
    print("  answer:     {!r}".format(r["answer"][:110]))
    if r["perplexity"] is None:
        print("  FAILED:     {}".format(r["why"]))
        return 1
    print("  tokens:     {} generated (prompt was {})".format(
        r["n_tokens"], r.get("prompt_eval_count")))
    print("  mean logp:  {:.4f}".format(r["mean_logprob"]))
    print("  PERPLEXITY: {:.4f}".format(r["perplexity"]))
    return 0


def _selftest() -> int:
    print("core/perplexity.py --selftest\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    check("disabled by default", enabled() is False)
    check("a missing config means disabled",
          load_config(BASE / "config" / "_absent.json") == {})

    v = {"fields": ["ram_percent", "cpu_percent", "gpu_temp_c"],
         "vector": [82.5, 6.0, None]}
    s = state_sentence(v)
    check("the sentence is built from the vector",
          "ram_percent 82.5" in s and "cpu_percent 6.0" in s)
    check("and a None dim is left out of it", "gpu_temp_c" not in s)

    check("an empty vector says so",
          state_sentence({"fields": [], "vector": []}) ==
          "No readings are available.")

    # the receptor, without any model call
    bank = rc.ReceptorBank(bus=eb.EventBus(), seed_path=BASE / "memory" / "_x")
    pr = PerplexityReceptor(bank=bank, eps=0.5, calibration_ticks=3)
    for x in (1.30, 1.31, 1.29):
        pr.feed({"perplexity": x, "model": "t"})
    check("it calibrates silently", pr.receptor.emitted == 0)
    ev = pr.feed({"perplexity": 4.0, "model": "t"})
    check("a jump in the model's own uncertainty emits", ev is not None)
    check("tagged source:model directed:self",
          ev and ev.meta["source"] == "model" and ev.meta["directed"] == "self")
    check("a failed measurement is counted, not published",
          pr.feed({"perplexity": None}) is None and pr.failures == 1)

    import tempfile
    log = pathlib.Path(tempfile.mkdtemp()) / "m.jsonl"
    record_mediation({"perplexity": 2.0}, code_said=True, model_said=False, path=log)
    record_mediation({"perplexity": 9.0}, code_said=False, model_said=True, path=log)
    m = mediation_ratio(log)
    check("the mediation ratio counts both", m["n"] == 2 and m["code_said"] == 1
          and m["model_said"] == 1)
    check("and reports agreement", m["agreement"] == 0.0)
    check("an empty log is reported, not divided by zero",
          mediation_ratio(pathlib.Path(tempfile.mkdtemp()) / "n.jsonl")["ratio"]
          is None)

    print("\n  {}".format("every check passed" if ok else "SOMETHING FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--once" in sys.argv:
        raise SystemExit(_once())
    print(json.dumps(mediation_ratio(), indent=2, default=str))
