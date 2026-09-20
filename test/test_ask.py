# -*- coding: utf-8 -*-
"""
tools/ask.py — the three questions, and the wrong answers they make impossible.

THE DEFECT (20 September 2026, twice in one day)
------------------------------------------------
A question about the repo was answered with an ad-hoc grep for ONE literal
string, and the empty result was reported as the answer to a BROADER question.
"Does this file contain the string extracted_at" is not "does this record carry
an observation date": memory/browse_sources/*.json carry data_date, and five of
them carried one all along while being described as carrying none.

An empty grep is the most dangerous shape of wrong answer available, because it
is indistinguishable from a true negative. So every test below comes in threes:
  * a KNOWN-TRUE case, so the tool can find what is there;
  * a KNOWN-EMPTY case, so it does not find what is not;
  * a MUTATION case, where the right answer is deleted from the fixture and the
    tool must STOP reporting it — the net against a subcommand that passes by
    printing something plausible rather than by looking.

Plus two LIVE anchors, against this repo rather than a fixture, because a tool
that only works on fixtures answers no questions about the system it is for.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools import ask  # noqa: E402

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


# ── fixtures ────────────────────────────────────────────────────────────────

def _registry(tmp_path: Path, spellings=None) -> Path:
    """A field registry of our own, so these tests do not move when the real one
    grows a spelling."""
    spellings = spellings if spellings is not None else [
        {"spelling": "data_date", "shape": "iso_date"},
        {"spelling": "extracted_at", "shape": "iso_datetime"},
        {"spelling": "temp_anomaly_year", "shape": "year"},
    ]
    p = tmp_path / "field_names.json"
    p.write_text(json.dumps(
        {"concepts": {"OBSERVATION_DATE": {"spellings": spellings}}}),
        encoding="utf-8")
    return p


def _records(tmp_path: Path) -> Path:
    d = tmp_path / "recs"
    d.mkdir()
    (d / "has_data_date.json").write_text(json.dumps(
        {"metric": "x", "value": 1, "data_date": "2026-07-31"}), encoding="utf-8")
    (d / "has_none.json").write_text(json.dumps(
        {"metric": "y", "value": 2, "timestamp": "2026-09-20T00:00:00+00:00"}),
        encoding="utf-8")
    return d


# ── observation-date ────────────────────────────────────────────────────────

def test_observation_date_finds_a_registered_spelling(tmp_path):
    """KNOWN TRUE. The record spells it data_date, which the grep that started
    all this was not looking for."""
    res = ask.observation_date(_records(tmp_path) / "has_data_date.json",
                               registry=_registry(tmp_path), now=NOW)
    hit = res["records"][0]["hits"][0]
    assert hit["spelling"] == "data_date"
    assert hit["observed"] == "2026-07-31"
    assert hit["age_days"] == 51.5


def test_observation_date_reports_absence_as_absence_not_as_a_mtime(tmp_path):
    """KNOWN EMPTY, AND THE FORBIDDEN FALLBACK.

    The record carries a `timestamp` — when it was written — and no observation
    date. The file was created a second ago, so a tool that quietly fell back to
    st_mtime would report it as perfectly fresh. There must be NO age at all.
    """
    res = ask.observation_date(_records(tmp_path) / "has_none.json",
                               registry=_registry(tmp_path), now=NOW)
    assert res["records"][0]["hits"] == []
    assert res["nodes_examined"] > 0, (
        "an empty answer over zero examined nodes is not an answer")


def test_observation_date_stops_reporting_a_date_that_is_removed(tmp_path):
    """MUTATION. Delete the field from the fixture; the tool must go quiet about
    it rather than keep answering from anywhere else."""
    reg = _registry(tmp_path)
    d = _records(tmp_path)
    f = d / "has_data_date.json"
    before = ask.observation_date(f, registry=reg, now=NOW)
    assert before["records"][0]["hits"]

    body = json.loads(f.read_text(encoding="utf-8"))
    del body["data_date"]
    f.write_text(json.dumps(body), encoding="utf-8")

    after = ask.observation_date(f, registry=reg, now=NOW)
    assert after["records"][0]["hits"] == [], (
        "the date was deleted from the record and the tool still reports one")


def test_a_spelling_removed_from_the_registry_stops_being_found(tmp_path):
    """THE SECOND MUTATION, one level up: the tool must hold no spelling of its
    own. If data_date were hardcoded anywhere in ask.py, this would still pass
    with a registry that does not mention it."""
    d = _records(tmp_path)
    reg = _registry(tmp_path, spellings=[{"spelling": "extracted_at",
                                          "shape": "iso_datetime"}])
    res = ask.observation_date(d / "has_data_date.json", registry=reg, now=NOW)
    assert res["records"][0]["hits"] == []


def test_an_empty_registry_refuses_instead_of_answering_no(tmp_path):
    """FAIL LOUD, NOT QUIET. With no spellings every record would answer 'no
    observation date' — a confident wrong answer, which is worse than a crash."""
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"concepts": {"OBSERVATION_DATE": {"spellings": []}}}),
                 encoding="utf-8")
    with pytest.raises(SystemExit):
        ask.load_spellings(path=p)
    with pytest.raises(SystemExit):
        ask.load_spellings(path=tmp_path / "does_not_exist.json")


@pytest.mark.parametrize("value,shape,expected", [
    ("2026-07-31", "iso_date", "2026-07-31"),
    ("2026-09-20T00:27:58.517868+00:00", "iso_datetime", "2026-09-20"),
    (2025, "year", "2025-12-31"),
    ("2025", "year", "2025-12-31"),
    (2026.101, "year_fraction", "2026-02-06"),   # 0.101 * 365 = day 36
])
def test_every_registered_shape_parses(value, shape, expected):
    dt, _how = ask.parse_value(value, shape)
    assert dt is not None and dt.date().isoformat() == expected


@pytest.mark.parametrize("value,shape", [
    (None, "iso_date"), ("", "iso_date"), ("yesterday", "iso_date"),
    ("not-a-year", "year"), ({}, "year_map"),
])
def test_an_unparsable_value_yields_no_age(value, shape):
    """It is reported as unparsable and given no age. Guessing at it, or falling
    back to the file, would turn a broken record into a fresh one."""
    dt, why = ask.parse_value(value, shape)
    assert dt is None and why


def test_a_year_map_is_as_old_as_its_oldest_year():
    dt, how = ask.parse_value({"a": "2025", "b": "2020", "c": "2024"}, "year_map")
    assert dt.year == 2020, how


# ── readers ─────────────────────────────────────────────────────────────────

def _fake_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    if (root / "core" / "reader.py").exists():
        return root                      # already built once in this test
    (root / "core").mkdir(parents=True)
    (root / "test").mkdir()

    (root / "core" / "reader.py").write_text(
        'from pathlib import Path\n'
        'BASE = Path(".")\n'
        'TARGET = BASE / "memory" / "registry.json"\n'
        'def load():\n'
        '    return TARGET.read_text(encoding="utf-8")\n', encoding="utf-8")

    (root / "core" / "writer.py").write_text(
        'from pathlib import Path\n'
        'BASE = Path(".")\n'
        'TARGET = BASE / "memory" / "registry.json"\n'
        'def save(text):\n'
        '    TARGET.write_text(text, encoding="utf-8")\n', encoding="utf-8")

    (root / "core" / "prose_only.py").write_text(
        '"""This module explains memory/registry.json at length.\n\n'
        'It never opens memory/registry.json. It only talks about it.\n"""\n'
        'VALUE = 1\n', encoding="utf-8")

    (root / "core" / "lookalike.py").write_text(
        'from pathlib import Path\n'
        'BASE = Path(".")\n'
        'OTHER = BASE / "memory" / "feature_registry.json"\n'
        'def load():\n'
        '    return OTHER.read_text(encoding="utf-8")\n', encoding="utf-8")
    return root


def test_readers_finds_the_code_that_reads_it(tmp_path):
    """KNOWN TRUE, through a module constant and a local read."""
    res = ask.readers("memory/registry.json", base=_fake_repo(tmp_path))
    assert [h["file"] for h in res["direct"]] == ["core/reader.py"]
    assert res["files_searched"] == 4


def test_readers_does_not_count_a_docstring_as_a_reader(tmp_path):
    """KNOWN EMPTY, and the defect being kept out. prose_only.py names the path
    twice in its docstring and opens nothing. A grep returns it; a reader list
    that includes it is how 'who reads this' stops meaning anything."""
    res = ask.readers("memory/registry.json", base=_fake_repo(tmp_path))
    named = ([h["file"] for h in res["direct"]]
             + [h["file"] for h in res["indirect"]]
             + [h["file"] for h in res["writers_only"]])
    assert "core/prose_only.py" not in named


def test_readers_matches_whole_segments_not_substrings(tmp_path):
    """registry.json must not match feature_registry.json. A substring test
    passes silently and puts a file that reads something else on the list."""
    res = ask.readers("memory/registry.json", base=_fake_repo(tmp_path))
    named = ([h["file"] for h in res["direct"]]
             + [h["file"] for h in res["writers_only"]])
    assert "core/lookalike.py" not in named

    # ...and the same call for the OTHER path finds it, so this is not passing
    # by finding nothing at all.
    other = ask.readers("memory/feature_registry.json", base=_fake_repo(tmp_path))
    assert [h["file"] for h in other["direct"]] == ["core/lookalike.py"]


def test_readers_separates_a_writer_from_a_reader(tmp_path):
    res = ask.readers("memory/registry.json", base=_fake_repo(tmp_path))
    assert [h["file"] for h in res["writers_only"]] == ["core/writer.py"]


def test_readers_stops_reporting_a_read_that_is_removed(tmp_path):
    """MUTATION. Take the read out of reader.py and the file must leave the
    reader list — not stay on it because it still names the path."""
    root = _fake_repo(tmp_path)
    assert [h["file"] for h in ask.readers("memory/registry.json", base=root)["direct"]]

    (root / "core" / "reader.py").write_text(
        'from pathlib import Path\n'
        'BASE = Path(".")\n'
        'TARGET = BASE / "memory" / "registry.json"\n'
        'def load():\n'
        '    return TARGET.exists()\n', encoding="utf-8")

    res = ask.readers("memory/registry.json", base=root)
    assert [h["file"] for h in res["direct"]] == [], (
        "the read was removed and the file is still listed as a reader")
    assert "core/reader.py" in [h["file"] for h in res["writers_only"]], (
        "it still names the path, so it must appear in the audit list")


def test_readers_reports_what_it_searched_even_when_it_finds_nothing(tmp_path):
    """An empty answer must be distinguishable from a question that could never
    have returned anything."""
    res = ask.readers("memory/nothing_names_this.json", base=_fake_repo(tmp_path))
    assert res["direct"] == [] and res["files_searched"] == 4


# ── callers ─────────────────────────────────────────────────────────────────

def _callers_repo(tmp_path: Path, live: bool = True) -> Path:
    root = tmp_path / "repo"
    (root / "core").mkdir(parents=True)
    (root / "test").mkdir()
    (root / "core" / "cadence.py").write_text(
        "def load_specs(path=None):\n    return {}\n", encoding="utf-8")
    (root / "test" / "test_cadence.py").write_text(
        "from core import cadence as cd\n"
        "def test_it():\n    assert cd.load_specs() == {}\n", encoding="utf-8")
    body = ("from core import cadence as cd\n"
            "def compose():\n    return cd.load_specs()\n" if live else
            "def compose():\n    return {}\n")
    (root / "core" / "composer.py").write_text(body, encoding="utf-8")
    return root


def test_callers_finds_a_live_caller(tmp_path):
    """KNOWN TRUE, and the classification that matters: one caller is a test and
    one is not."""
    res = ask.callers("core.cadence.load_specs", base=_callers_repo(tmp_path))
    assert res["defined_at"] == "core/cadence.py:1"
    assert sorted(h["file"] for h in res["hits"]) == [
        "core/composer.py", "test/test_cadence.py"]
    assert [h["file"] for h in res["live_outside_test"]] == ["core/composer.py"]


def test_callers_of_a_name_that_does_not_exist_says_so(tmp_path):
    """KNOWN EMPTY. No call sites AND no definition — reported as two separate
    facts, because 'nobody calls it' and 'there is no such function' want very
    different responses."""
    res = ask.callers("core.cadence.no_such_function", base=_callers_repo(tmp_path))
    assert res["hits"] == []
    assert res["defined_at"] is None
    assert res["files_searched"] == 3


def test_callers_says_when_every_call_site_is_a_test(tmp_path):
    """MUTATION, and the question the subcommand exists for. Remove the one live
    caller and the answer must change from 'called' to 'enforces nothing' —
    a function whose only callers are tests is not wired into the system."""
    root = _callers_repo(tmp_path, live=False)
    res = ask.callers("core.cadence.load_specs", base=root)
    assert [h["file"] for h in res["hits"]] == ["test/test_cadence.py"]
    assert res["live_outside_test"] == []


# ── LIVE ANCHORS, against this repo ─────────────────────────────────────────

def test_live_anchor_the_climate_record_carries_data_date():
    """THE RECORD THE GREP MISSED. It has no extracted_at, and it has an
    observation date: 2026-07-31, under data_date."""
    f = REPO / "memory" / "browse_sources" / "CLIMATE_GLOBAL_RISK_REVIEW.json"
    if not f.exists():
        pytest.skip("the live record is not on this disk")
    res = ask.observation_date(f, now=NOW)
    hits = res["records"][0]["hits"]
    assert [h["spelling"] for h in hits] == ["data_date"]
    assert hits[0]["observed"] == "2026-07-31"
    assert hits[0]["age_days"] == 51.5
    assert "extracted_at" in res["spellings"], (
        "the spelling that was grepped for is registered too; the point is that "
        "it is not the only one")


def test_live_anchor_the_readers_of_verified_observations():
    """The four the question was really about, found through a module constant,
    through a local helper, and through a local rebinding."""
    res = ask.readers("memory/verified_observations.jsonl")
    direct = {h["file"] for h in res["direct"]}
    for expected in ("core/alarm_bands.py", "scripts/agi_scoreboard.py",
                     "training/verified_corpus.py"):
        assert expected in direct, f"{expected} missing from {sorted(direct)}"
    indirect = {h["file"] for h in res["indirect"]}
    assert "core/counterfactual_probe.py" in direct | indirect, (
        "it reads the file through core.alarm_bands.indicator_values(); an "
        "answer that leaves it out is the reason 'readers' cannot be a grep")


def test_live_anchor_a_prose_mention_is_not_a_reader():
    """test/test_alarm_indicators.py names the path once, in a docstring. It
    must not be on the DIRECT reader list, which is where a grep would put it."""
    res = ask.readers("memory/verified_observations.jsonl")
    assert "test/test_alarm_indicators.py" not in {h["file"] for h in res["direct"]}
