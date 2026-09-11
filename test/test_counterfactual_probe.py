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


def test_log_and_summary_are_written(tmp_path):
    log, latest = tmp_path / "l.jsonl", tmp_path / "s.json"
    CP.run(ask=_oracle, case_list=[CASE], log=log, latest=latest, now="2026-09-11T00:00:00+00:00")
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["outcome"] == CP.TRACKS and rows[0]["flipped_value"] == 3.77 and rows[0]["verdict"]["flipped"] == "OVER"
    assert json.loads(latest.read_text(encoding="utf-8"))["n"] == 1
