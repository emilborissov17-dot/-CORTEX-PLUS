# -*- coding: utf-8 -*-
"""test/test_counterfactual_probe.py — point 13, understanding vs simulation (11 Sep 2026, #61).

The truth is arithmetic; the asker is a fake. Pinned:
  * mirror() always lands on the other side of the line, never on it
  * a parrot (same verdict whatever the number) is INSENSITIVE
  * an asker that changes its mind on a date change is NOISE_DRIVEN
  * a correct asker TRACKS; an inverted one is WRONG; None is SILENT
  * cases come only from bands/targets that HAVE a value
  * the log and the summary are written and readable
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import counterfactual_probe as CP  # noqa: E402


CASE = {"case": "indicator:x", "value": 2.23, "line": 3.0, "direction": "lower_better", "unit": "ppm",
        "date": "2026-09-11", "kind": "signed red line", "source": "t"}
HIGH = dict(CASE, case="target:y", value=40.0, line=80.0, direction="higher_better", kind="ratified target")


def _oracle(question, evidence, schema):
    """Reads the two numbers from the material — what understanding looks like."""
    lines = {l.split(":")[0].strip(): l for l in evidence.splitlines() if ":" in l}
    v = float(lines["value"].split(":")[1].split()[0])
    l = float(lines["line ({})".format("signed red line")].split("):")[1].split()[0]) \
        if "line (signed red line)" in lines else float(lines["line (ratified target)"].split("):")[1].split()[0])
    worse_high = "higher is worse" in evidence
    return {"verdict": "OVER" if (v > l if worse_high else v < l) else "UNDER", "reason": "read"}


def test_mirror_crosses_the_line_and_never_sits_on_it():
    assert CP.mirror(2.23, 3.0) == 3.77 and CP.mirror(3.77, 3.0) == 2.23
    assert CP.mirror(3.0, 3.0) != 3.0


def test_mirror_stays_inside_the_unit_domain():
    assert CP.mirror(8.5, 2.5, "percent of population") == 1.25          # not -3.5 %
    assert CP.mirror(10.4, 0.0, "percent of population") is None         # nothing below 0 %
    assert CP.mirror(73.7, 100.0, "percent of population") is None       # nothing above 100 %
    assert CP.mirror(27.8, 80.0, "percent of total energy") == 90.0      # 132 % clipped to (80+100)/2
    assert CP.mirror(38.0, 50.0, "events per 7 days") == 62.0
    assert CP.mirror(0.44, 1.0, "index 0-1") is None                     # an index of 1.0: nothing above it
    assert CP.mirror(0.44, 0.8, "") == 0.9                               # unitless, line <= 1: (0.8+1)/2
    assert CP.mirror(29429000.0, 1000000.0, "people") == 500000.0        # not -27 million refugees
    assert CP.mirror(-2.0, 1.0, "anomaly") == 4.0                        # signed quantities stay unbounded
    assert CP.variants(dict(CASE, value=10.4, line=0.0, unit="percent")) == {}


def test_cases_without_a_counterfactual_are_skipped_and_named(tmp_path):
    s = CP.run(ask=_oracle, case_list=[CASE, dict(CASE, case="target:P", value=10.4, line=0.0, unit="percent")],
               log=tmp_path / "l.jsonl", latest=tmp_path / "s.json")
    assert s["n"] == 1 and s["skipped_no_counterfactual"] == ["target:P"]
    assert CP.truth(2.23, 3.0, "lower_better") == CP.UNDER and CP.truth(3.77, 3.0, "lower_better") == CP.OVER
    assert CP.truth(40.0, 80.0, "higher_better") == CP.OVER


def test_variants_flip_the_truth_and_noise_keeps_it():
    vs = CP.variants(CASE)
    assert vs["base"]["truth"] != vs["flipped"]["truth"]
    assert vs["noise"]["truth"] == vs["base"]["truth"]
    assert "2026-09-10" in vs["noise"]["material"] and "2.23" in vs["noise"]["material"]


def test_an_oracle_tracks(tmp_path):
    s = CP.run(ask=_oracle, case_list=[CASE, HIGH], log=tmp_path / "l.jsonl", latest=tmp_path / "s.json")
    assert s["counts"][CP.TRACKS] == 2 and s["tracks_rate"] == 1.0


def test_a_parrot_is_insensitive(tmp_path):
    s = CP.run(ask=lambda q, e, sc: {"verdict": "UNDER"}, case_list=[CASE], log=tmp_path / "l.jsonl", latest=tmp_path / "s.json")
    assert s["counts"][CP.INSENSITIVE] == 1 and s["tracks_rate"] == 0.0


def test_a_date_reader_is_noise_driven(tmp_path):
    def ask(q, e, sc):
        # right on the number, but flips whenever the date is not the 11th
        o = _oracle(q, e, sc)
        if "2026-09-11" not in e:
            o["verdict"] = "OVER" if o["verdict"] == "UNDER" else "UNDER"
        return o
    s = CP.run(ask=ask, case_list=[CASE], log=tmp_path / "l.jsonl", latest=tmp_path / "s.json")
    assert s["counts"][CP.NOISE_DRIVEN] == 1


def test_an_inverted_reader_is_wrong_and_silence_is_silent(tmp_path):
    inv = lambda q, e, sc: {"verdict": "UNDER" if _oracle(q, e, sc)["verdict"] == "OVER" else "OVER"}  # noqa: E731
    s = CP.run(ask=inv, case_list=[CASE], log=tmp_path / "l.jsonl", latest=tmp_path / "s.json")
    assert s["counts"][CP.WRONG] == 1
    s = CP.run(ask=lambda q, e, sc: None, case_list=[CASE], log=tmp_path / "l.jsonl", latest=tmp_path / "s.json")
    assert s["counts"][CP.SILENT] == 1 and s["tracks_rate"] is None and s["answered"] == 0


def test_normalise_accepts_only_the_two_words():
    assert CP.normalise({"verdict": " over the line"}) == CP.OVER
    assert CP.normalise({"verdict": "Under"}) == CP.UNDER
    assert CP.normalise({"verdict": "maybe"}) is None and CP.normalise("OVER") is None


def test_cases_need_a_value(tmp_path):
    bands = {"a": {"rule": "fixed", "threshold": 3.0, "direction": "lower_better", "unit": "u"},
             "b": {"rule": "fixed", "threshold": 1.0, "direction": "lower_better"},          # no value
             "c": {"rule": "relative_median", "direction": "lower_better"}}                 # not fixed
    ic = CP.indicator_cases(bands=bands, series={"a": [("2026-09-01", 1.0), ("2026-09-11", 2.5)]})
    assert [c["case"] for c in ic] == ["indicator:a"] and ic[0]["value"] == 2.5 and ic[0]["date"] == "2026-09-11"
    t = tmp_path / "targets.json"
    t.write_text(json.dumps({"_meta": {}, "X": {"target_value": 80.0, "direction": "higher_better", "unit": "%"},
                             "Y": {"target_value": 5.0, "direction": "lower_better"}}), encoding="utf-8")
    tc = CP.target_cases(targets_path=t, values={"X": 40.0})
    assert [c["case"] for c in tc] == ["target:X"]
    # the real file is nested by group (the first live run produced 0 target cases because of this)
    t.write_text(json.dumps({"_meta": {}, "SAFETY": {"Z": {"target_value": 1.0, "direction": "higher_better"},
                                                     "W": {"target_value": 1.0, "direction": "stable_better"}}}), encoding="utf-8")
    tc = CP.target_cases(targets_path=t, values={"Z": 0.4, "W": 0.4})
    assert [c["case"] for c in tc] == ["target:Z"]


def test_the_model_that_answered_is_recorded(tmp_path):
    ask = lambda q, e, sc: dict(_oracle(q, e, sc), _model="qwen3:8b")  # noqa: E731
    CP.run(ask=ask, case_list=[CASE], log=tmp_path / "l.jsonl", latest=tmp_path / "s.json")
    row = json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["model"] == ["qwen3:8b"] and row["reason"]["base"] == "read"


def test_log_and_summary_are_written(tmp_path):
    log, latest = tmp_path / "l.jsonl", tmp_path / "s.json"
    CP.run(ask=_oracle, case_list=[CASE], log=log, latest=latest, now="2026-09-11T00:00:00+00:00")
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["outcome"] == CP.TRACKS and rows[0]["flipped_value"] == 3.77 and rows[0]["verdict"]["flipped"] == "OVER"
    assert json.loads(latest.read_text(encoding="utf-8"))["n"] == 1


def test_compare_runs_the_same_cases_through_several_minds(tmp_path, monkeypatch):
    monkeypatch.setattr(CP, "askers", lambda names: {"reader": _oracle, "parrot": lambda q, e, sc: {"verdict": "UNDER"}})
    r = CP.compare(["reader", "parrot"], case_list=[CASE, HIGH], out_path=tmp_path / "by_model.json", now="t")
    assert r["by_model"]["reader"]["tracks_rate"] == 1.0 and r["by_model"]["parrot"]["counts"]["INSENSITIVE"] == 2
    assert r["by_model"]["reader"]["per_case"] == {"indicator:x": "TRACKS", "target:y": "TRACKS"}
    assert json.loads((tmp_path / "by_model.json").read_text(encoding="utf-8"))["cases"] == 2


def test_a_groq_model_outside_the_free_list_is_refused_before_any_call():
    import pytest
    with pytest.raises(ValueError, match="GROQ_FREE_MODELS"):
        CP.groq_asker("some/paid-model")
    with pytest.raises(ValueError, match="unknown asker"):
        CP.askers(["gpt-anything"])



import tempfile as _tf
_TMP = Path(_tf.mkdtemp(prefix="probe_rl_"))


# ── a rate limit is not a silence (11 Sep 2026) ──────────────────────────────

def test_a_host_refusal_is_rate_limited_not_silent():
    """THE MISREADING, from the first cloud comparison. The [PROBE] line said

        nvidia-kimi n=9 answered=1 tracks_rate=1.0 ... SILENT 8

    which reads as a mind that would not speak, and a 1.0 rate over ONE answered
    case reads as perfect understanding. Replaying the same call by hand gave
    HTTP 429 {"title":"Too Many Requests"} — the host refused, the model never saw
    the question. Blaming the mind for the rate limiter is the wrong story to
    leave on disk, and `answered` must not count those cases either."""
    vs = {"base": {"truth": CP.OVER}, "flipped": {"truth": CP.UNDER}}
    assert CP.outcome(None, None, None, vs, refusals=["base: HTTP 429"]) == CP.RATE_LIMITED
    assert CP.outcome(None, None, None, vs, refusals=[]) == CP.SILENT
    assert CP.outcome(None, None, None, vs) == CP.SILENT


def test_a_refused_case_is_not_counted_as_answered():
    """The denominator matters more than the label: tracks_rate over a single
    answered case is not a measurement."""
    def refuse(question, evidence, schema):
        return {"_unavailable": "HTTP 429"}
    s = CP.run(ask=refuse, case_list=CP.cases()[:2],
               log=_TMP / "l.jsonl", latest=_TMP / "s.json")
    assert s["counts"][CP.RATE_LIMITED] == 2
    assert s["counts"][CP.SILENT] == 0
    assert s["answered"] == 0, "a refused call must not inflate `answered`"


def test_an_unparseable_reply_is_still_silent():
    """NEGATIVE CONTROL. The fix must not relabel every failure as a rate limit —
    a model that answers with prose really did stay silent on the question."""
    def prose(question, evidence, schema):
        return {"verdict": "it depends on the context"}
    s = CP.run(ask=prose, case_list=CP.cases()[:2],
               log=_TMP / "l2.jsonl", latest=_TMP / "s2.json")
    assert s["counts"][CP.SILENT] == 2
    assert s["counts"][CP.RATE_LIMITED] == 0


def test_unavailable_only_fires_on_the_named_field():
    """A normal answer must never be read as a host refusal."""
    assert CP.unavailable({"verdict": "OVER"}) is None
    assert CP.unavailable(None) is None
    assert CP.unavailable({"_unavailable": "HTTP 503"}) == "HTTP 503"
