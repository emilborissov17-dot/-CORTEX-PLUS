# -*- coding: utf-8 -*-
"""test/test_institution0.py — the UCDP client and the witness-stage morning.

FIXTURE-DRIVEN, NO NETWORK. Every test builds its own three-file UCDP tree in
tmp_path. Nothing here reads data/ucdp/ or reaches ucdp.uu.se, so the outcome
moves with the code and not with the world — which is the `live_state` line this
repo draws in pytest.ini.

The failure paths come first, because they are the ones that would publish a
number about a war that nobody measured:

  * a missing column must RAISE, not become a zero;
  * an absent file must RAISE, not become an empty month;
  * the monthly candidate is INCREMENTAL and shares ids with the quarterly, so a
    naive concatenation double-counts — the merge is tested against that;
  * an unmapped reporter class must REFUSE, not default to "unknown";
  * a rise inside the actor's own range must NOT be published as a rise;
  * a place that rises with no commitment must still be published, with
    commitment_id explicitly null.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import ucdp_client as uc            # noqa: E402
import tools.institution0_morning as inst     # noqa: E402

COLUMNS = list(uc.REQUIRED_COLUMNS) + ["dyad_name", "conflict_name", "year"]


def _row(i, country, side_a, date, tov="3", deaths=1, adm="Adm"):
    return {"id": str(i), "type_of_violence": tov, "side_a": side_a, "side_b": "Civilians",
            "country": country, "date_start": date + " 00:00:00.000",
            "deaths_civilians": str(deaths), "adm_1": adm,
            "dyad_name": side_a + " - Civilians", "conflict_name": side_a + " - Civilians",
            "year": date[:4]}


def _write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    path.write_text(buf.getvalue(), encoding="utf-8")


@pytest.fixture
def tree(tmp_path):
    """release + quarterly + monthly, with the overlap the real files have."""
    d = tmp_path / "ucdp"
    # release: 2 years of Sudan, one event a month, plus a DRC series
    rel = []
    n = 0
    for y in (2024, 2025):
        for m in range(1, 13):
            n += 1
            rel.append(_row(n, "Sudan", "RSF", "%04d-%02d-05" % (y, m)))
            n += 1
            rel.append(_row(n, "DR Congo (Zaire)", "AFC", "%04d-%02d-06" % (y, m)))
    _write_csv(d / "GEDEvent_v26_1.csv", rel)
    # quarterly candidate: 2026-01..06
    qtr = []
    for m in range(1, 7):
        n += 1
        qtr.append(_row(n, "Sudan", "RSF", "2026-%02d-05" % m))
        n += 1
        qtr.append(_row(n, "DR Congo (Zaire)", "AFC", "2026-%02d-06" % m))
    _write_csv(d / "GEDEvent_v26_01_26_06.csv", qtr)
    # monthly candidate: July, PLUS one revision of a row the quarterly already had
    mon = [_row(9001, "Sudan", "RSF", "2026-07-05"),
           _row(9002, "Sudan", "RSF", "2026-07-06"),
           _row(9003, "Sudan", "RSF", "2026-07-07"),
           _row(qtr[0]["id"], "Sudan", "RSF", "2026-01-05", deaths=99)]   # revision
    _write_csv(d / "GEDEvent_v26_0_7.csv", mon)
    return d


# ── the client ─────────────────────────────────────────────────────────────
def test_the_merge_does_not_double_count_the_revision(tree):
    rows, as_of = uc.load_events(tree)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "an id appears twice — concatenation, not a merge"
    assert as_of.startswith("ucdp:")


def test_the_later_release_wins_on_a_revised_row(tree):
    """The monthly file revised one January row's deaths to 99. That must win."""
    rows, _ = uc.load_events(tree)
    jan = [r for r in rows if r["date_start"].startswith("2026-01")]
    assert len(jan) == 2, jan
    assert any(r["deaths_civilians"] == "99" for r in jan), (
        "the earlier quarterly row survived the later monthly revision")


def test_a_missing_column_raises_rather_than_becoming_a_zero(tree):
    p = tree / "GEDEvent_v26_0_7.csv"
    text = p.read_text(encoding="utf-8").splitlines()
    head = text[0].replace("deaths_civilians,", "")
    p.write_text("\n".join([head] + [",".join(l.split(",")[:-0] or l) for l in text[1:]]),
                 encoding="utf-8")
    with pytest.raises(uc.UcdpUnavailable) as e:
        uc.load_events(tree)
    assert "schema" in str(e.value) or "missing column" in str(e.value)


def test_an_absent_file_raises(tree):
    (tree / "GEDEvent_v26_0_7.csv").unlink()
    with pytest.raises(uc.UcdpUnavailable) as e:
        uc.load_events(tree)
    assert "not on disk" in str(e.value)


def test_the_anchor_is_the_data_not_the_clock(tree):
    rows, _ = uc.load_events(tree)
    assert uc.last_complete_month(rows) == "2026-07"


def test_actor_match_is_exact_never_fuzzy(tree):
    rows, _ = uc.load_events(tree)
    assert uc.osv_events(rows, "Sudan", "RSF")
    assert uc.osv_events(rows, "Sudan", "rsf") == []
    assert uc.osv_events(rows, "Sudan", "RS") == []
    assert uc.osv_events(rows, "Sudan", "RSF ") == []


def test_unknown_actors_are_recognised_by_shape():
    assert uc.is_unknown_actor("XXX666")
    assert uc.is_unknown_actor("XXX625")
    assert not uc.is_unknown_actor("RSF")
    assert not uc.is_unknown_actor("XXXFOO")


def test_prior_months_crosses_the_year_boundary():
    assert uc.prior_months("2026-02", 3) == ["2025-11", "2025-12", "2026-01"]


def test_percentile_of_an_empty_series_is_none_not_zero():
    assert uc.percentile([], 0.9) is None
    assert uc.percentile([2.0], 0.9) == 2.0


def test_a_month_with_an_empty_prior_window_contributes_no_ratio():
    """An absent ratio is not a ratio of zero. Zero would drag the p90 down and
    make the next real rise look ordinary.

    The first assertion is the one that matters: 2026-07's prior window is
    2026-04/05/06, all absent, so there is no ratio to have. The second is the
    control that keeps the first honest — 2026-08's prior window is 05/06/07,
    which is NOT empty because July has 5, so a genuine ratio of 0.0 IS produced
    and must be. An earlier version of this test asserted both were empty and was
    wrong about the second; the code was right.
    """
    counts = {"2026-07": 5}
    assert uc.ratio_series(counts, ["2026-07"], 3) == []
    assert uc.ratio_series(counts, ["2026-08"], 3) == [0.0]


# ── the register ───────────────────────────────────────────────────────────
def test_every_register_actor_is_an_exact_string_with_a_window():
    reg = json.loads((REPO / "config" / "commitments.json").read_text(encoding="utf-8"))
    assert reg["commitments"], "the register is empty"
    for c in reg["commitments"]:
        # A status is either a model's proposal or a human's ruling, and nothing
        # else. Emil confirmed all four on 18 Sep 2026; the test pins the SHAPE so
        # that a model cannot invent a third kind and so that "confirmed" alone —
        # which names nobody — never passes.
        assert re.match(r"^(proposed_by_claude|confirmed_by_[a-z]+)_\d{4}-\d{2}-\d{2}$",
                        c["status"]), (
            "%s has status %r, which names neither a proposer nor a confirming human"
            % (c["id"], c["status"]))
        for a in c["actor_strings"]["ucdp"]:
            assert a["side_a"] == a["side_a"].strip() and a["side_a"]
            assert a["link"] in ("verified", "unverified")
            assert "from" in a and "to" in a


def test_an_unverified_actor_link_is_never_presented_as_a_party():
    """SFA appears exactly as RSF's counts stop. Whether it IS the RSF is our
    guess, so it must not be labelled with a party name."""
    reg = json.loads((REPO / "config" / "commitments.json").read_text(encoding="utf-8"))
    for c in reg["commitments"]:
        for a in c["actor_strings"]["ucdp"]:
            if a["link"] == "unverified":
                assert a["party"] == "UNRESOLVED", (
                    "%s/%s claims a party for a link we have not verified"
                    % (c["id"], a["side_a"]))


def test_unsc_2735_is_not_in_the_register():
    """Rule (ii): a demand made ON an actor is not a commitment BY it."""
    raw = (REPO / "config" / "commitments.json").read_text(encoding="utf-8")
    reg = json.loads(raw)
    ids = [c["id"] for c in reg["commitments"]]
    assert not any("2735" in i for i in ids)
    assert "not_unsc_2735_because" in json.dumps(reg), (
        "the exclusion is not explained anywhere, so the next person will add it")


# ── the morning ────────────────────────────────────────────────────────────
def test_an_unmapped_reporter_class_refuses(tmp_path):
    p = tmp_path / "reporters.json"
    p.write_text(json.dumps({"confirmed": {}}), encoding="utf-8")
    with pytest.raises(inst.Unmapped) as e:
        inst.reporter_class(p)
    assert "refuses" in str(e.value)


def test_the_real_reporter_class_is_confirmed_and_named():
    cls, _why = inst.reporter_class()
    assert cls in ("self_reported", "independent", "adversarial", "unknown")


def test_a_ratio_inside_the_range_is_not_published_as_a_rise(tree):
    rows, _ = uc.load_events(tree)
    line = inst.actor_line(rows, "Sudan", "RSF", "2026-07", "2023-05-11")
    assert line["verdict"] in ("WITHIN_OWN_RANGE", "ABOVE_OWN_P90", "NO_NULL")
    if line["ratio"] is not None and line["null_p90"] is not None:
        assert (line["verdict"] == "ABOVE_OWN_P90") == (line["ratio"] > line["null_p90"])


def test_no_null_is_distinct_from_no_rise(tree):
    """An actor with an empty prior window says NO_NULL, not WITHIN_OWN_RANGE.
    Reporting 'no rise' when we could not form the comparison is a claim."""
    rows, _ = uc.load_events(tree)
    line = inst.actor_line(rows, "Sudan", "NOBODY_AT_ALL", "2026-07", None)
    assert line["verdict"] == "NO_NULL"
    assert line["ratio"] is None
    assert line["ucdp_events_osv_last_month"] == 0


def test_the_forecast_declares_itself_as_persistence(tree):
    rows, _ = uc.load_events(tree)
    line = inst.actor_line(rows, "Sudan", "RSF", "2026-07", "2023-05-11")
    assert line["forecast"] == "SAME"
    assert line["baseline_persistence"] == "SAME"
    assert line["forecast_version"] == "v0-persistence"
    assert line["p"] is None or 0.0 <= line["p"] <= 1.0
    assert "empirical" in line["p_basis"]


def test_a_rise_with_no_commitment_is_published_with_an_explicit_null(tree):
    """The register must not be able to confirm itself by only ever looking at
    the places it already watches."""
    rows, _ = uc.load_events(tree)
    reg = {"commitments": [{"ucdp_country": "Sudan"}]}
    ctx = inst.context_line(rows, "2026-07", reg)
    assert "commitment_id" in ctx
    if ctx.get("place"):
        assert ctx["commitment_id"] is None
        assert "watched_place" in ctx


def test_unknown_actor_events_are_never_charged_to_a_party(tree):
    rows, _ = uc.load_events(tree)
    u = inst.unknown_actor_line(rows, "Sudan", "2026-07")
    assert "never charged" in u["note"]
    assert u["side_a"].startswith("actor_unknown")


def test_the_name_is_the_locked_one():
    assert inst.NAME == "institution #0 (witness stage)"
