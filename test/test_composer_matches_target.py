"""An axis may not be scored on another axis's instrument, and a declared
indicator is not a measurement until it carries a value.

THE DEFECT, twice. On 11 Sep 2026 MATERIALS_WASTE_REVIEW's primary_metric in
config/target_config.json was changed from co2_ppm_mauna_loa to
adjusted_net_savings_pct, because the axis was being scored on CO2 — the identical
reading CLIMATE_GLOBAL_RISK_REVIEW is scored on. config/composer_specs.json was
NOT changed with it. For six more nights the composer kept filling the axis's
anchor from NOAA co2.co2_ppm, R7_SENSOR_REUSE kept reporting the pair, and the
config said one thing while the sensor did another.

The same day DEEP_TIME_RISKS_REVIEW was given "measured_by_indicator":
["usgs_m5plus_7d_count"] — it is a qualitative axis, watched through indicator
bands rather than a metric. core/deduction.py R5 reads levels and scores only, so
it called the axis a blind spot every night regardless.

WHAT THIS FILE REFUSES TO SAY. It does not claim every anchor is the right
instrument. Three of its registries below are lists of axes where correspondence
is NOT affirmed — five recorded mismatches and a set that cannot be checked
mechanically at all. Each entry carries its reason and is pinned: a mismatch that
changes, spreads, or is quietly added fails this file. What is unchecked is
named, never skipped.

THE CHECKS
  A  no two axes anchor on the same source unless target_config gives them the
     same primary_metric.
  B  every anchor source carrying an "extract" is classified: correspondence
     affirmed (ANCHOR_PINS), correspondence denied and recorded (KNOWN_MISMATCH),
     or not mechanically checkable and why (KNOWN_UNCHECKED). An unclassified
     source fails — a new anchor is a human decision, not a default.
  C  R5 does not fire for an axis whose declared indicator has a value; R5 fires
     AND names the indicator when it does not. Including when the bands file is
     absent: an unreadable measurement must never read as a present one.
"""
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import deduction as D    # noqa: E402

SPECS = REPO / "config" / "composer_specs.json"
TARGET = REPO / "config" / "target_config.json"


# ── the two configs, read once ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def specs() -> dict:
    return json.loads(SPECS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def primary_metric() -> dict:
    """axis -> target_config primary_metric (None is a real answer, not a gap)."""
    tc = json.loads(TARGET.read_text(encoding="utf-8"))
    out = {}
    for dom, axes in tc.items():
        if str(dom).startswith("_") or not isinstance(axes, dict):
            continue
        for ax, spec in axes.items():
            if isinstance(spec, dict):
                out[ax] = spec.get("primary_metric")
    return out


def _anchor_sources(spec: dict) -> list:
    slot = spec.get("anchor_slot")
    return ((spec.get("portfolio") or {}).get(slot) or {}).get("sources") or []


def _address(src: dict) -> tuple:
    """What this source physically reads. Two sources with the same address
    return the same number, whatever their id, org or slot label says."""
    if src.get("path") is not None:
        return ("file", src.get("path"), src.get("extract"))
    if src.get("url") is not None:
        return ("http", src.get("url"), src.get("col"), src.get("extract"))
    return ("opaque", json.dumps(src, sort_keys=True, ensure_ascii=False))


def _axes(specs: dict):
    for ax, spec in specs.items():
        if not str(ax).startswith("_") and isinstance(spec, dict):
            yield ax, spec


# ── CHECK A — one instrument, one axis ───────────────────────────────────────

def test_no_two_axes_share_an_anchor_source(specs, primary_metric):
    """MATERIALS_WASTE and CLIMATE both anchored on NOAA co2.co2_ppm until
    17 Sep 2026. Sharing is allowed only where target_config declares the SAME
    primary_metric for both — two axes measuring the same declared quantity may
    read the same instrument; two axes measuring different quantities may not.
    A shared metric of None does not license sharing: it is the absence of a
    declaration, not agreement between two."""
    seen = {}
    for ax, spec in _axes(specs):
        for src in _anchor_sources(spec):
            seen.setdefault(_address(src), []).append(ax)

    offenders = []
    for addr, axes in seen.items():
        axes = sorted(set(axes))
        if len(axes) < 2:
            continue
        metrics = {a: primary_metric.get(a) for a in axes}
        agreed = len(set(metrics.values())) == 1 and None not in metrics.values()
        if not agreed:
            offenders.append((addr, metrics))

    assert not offenders, (
        "axes anchored on the same source without a shared primary_metric:\n"
        + "\n".join(f"  {a} -> {m}" for a, m in offenders))


def test_materials_waste_no_longer_anchors_on_co2(specs):
    """The specific corpse, named so it cannot come back quietly."""
    addrs = [_address(s) for s in _anchor_sources(specs["MATERIALS_WASTE_REVIEW"])]
    assert not any("co2" in str(a).lower() for a in addrs), \
        f"MATERIALS_WASTE_REVIEW anchors on a CO2 address again: {addrs}"


def test_materials_waste_daily_slot_is_empty_not_borrowed(specs):
    """No daily measurement of waste exists. The honest state is an empty slot.
    Re-filling it with a CO2 series to satisfy min=1 is the failure this guards."""
    port = specs["MATERIALS_WASTE_REVIEW"]["portfolio"]
    assert port["measurement_daily"]["sources"] == [], \
        "measurement_daily was refilled; if a real daily waste sensor was found, " \
        "update this test with its provenance"


# ── CHECK B — the anchor reads what the axis says it measures ────────────────
#
# Correspondence affirmed: the extracted field is the quantity target_config
# names, allowing for a different spelling or a different vintage of the same
# series. The recorded primary_metric is asserted against target_config, so the
# 11 Sep drift (metric changed, spec left behind) fails here.
ANCHOR_PINS = {
    "WATER_REVIEW": ("safe_water_access_pct",
                     {"world_bank.safe_water_access_pct"},
                     "same field name"),
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": ("forest_area_pct",
                                       {"world_bank.forest_area_pct"},
                                       "same field name"),
    "MATERIALS_WASTE_REVIEW": ("adjusted_net_savings_pct",
                               {"waste.adjusted_net_savings_pct"},
                               "same field name; World Bank NY.ADJ.SVNG.GN.ZS, set 17 Sep 2026"),
    "FOOD_REVIEW": ("food_insecurity_pct",
                    {"food.food_insecurity_severe_pct"},
                    "World Bank SN.ITK.SVFI.ZS, FAO FIES severe food insecurity — the "
                    "instrument the rationale names ('~10% severely food insecure'). "
                    "Switched 17 Sep 2026 from SN.ITK.DEFC.ZS (undernourishment), which "
                    "scored 29.4 against the new 24.6; break in config/series_breaks.json"),
    "ENERGY_REVIEW": ("renewable_energy_pct",
                      {"world_bank.renewable_energy_pct"},
                      "World Bank EG.FEC.RNEW.ZS, renewable share of TOTAL FINAL energy — "
                      "the denominator target_config's unit declares. Switched 17 Sep 2026 "
                      "from EG.ELC.RNEW.ZS (electricity only), which scored 34.8 against "
                      "the new 24.7; break recorded in config/series_breaks.json"),
    "ECONOMY_WORK_REVIEW": ("gdp_growth_pct",
                            {"economy.gdp_growth_annual_pct"},
                            "annual GDP growth; the field spells out the period"),
    "INFRASTRUCTURE_CITIES_REVIEW": ("urbanization_pct",
                                     {"cities.urban_population_pct"},
                                     "share of population urban — same quantity, different spelling"),
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": ("governance_rights_score_global",
                                         {"governance_rights_score"},
                                         "the composed WGI+V-Dem rights score; the metric name adds _global"),
    "GOVERNANCE_INSTITUTIONS_REVIEW": ("governance_institutions_score_global",
                                       {"governance_institutions_score"},
                                       "the composed WGI+V-Dem institutions score; the metric name adds _global"),
    "SOCIAL_RELATIONS_REVIEW": ("refugee_population",
                                {"displaced.refugees_millions"},
                                "UNHCR refugee stock. The composer records it in MILLIONS and "
                                "target_config states the metric in PERSONS; the scale is "
                                "reconciled in the scorer, not here — goal_score_calculator.py:214 "
                                "multiplies by 1_000_000 before the comparison, verified against "
                                "the live score on 17 Sep 2026 (1e6 / 29_429_000 = 0.034 -> 3.4, "
                                "which is the score on record). See "
                                "test_refugee_metric_reaches_the_scorer_in_persons below, which "
                                "holds that conversion in place"),
    "CLIMATE_GLOBAL_RISK_REVIEW": ("co2_ppm_mauna_loa",
                                   {"co2.co2_ppm", "co2_ppm_current"},
                                   "atmospheric CO2 in ppm. OPEN: the metric names the Mauna Loa "
                                   "station and the snapshot field carries NOAA's global mean; "
                                   "they differ by about 1 ppm. Same quantity, different station."),
}

# Correspondence DENIED. These anchors do not read the quantity target_config
# names. Recorded, not repaired: repairing them changes what the axis scores and
# belongs to a human. Pinned so a mismatch cannot change, spread or be added
# silently — and so the list shrinks only by a deliberate edit.
KNOWN_MISMATCH = {
    "HUMAN_WELL_BEING_REVIEW": ("child_mortality_per_1000",
                                {"world_bank.infant_mortality_per1k"},
                                "infant mortality is under-1; SDG 3.2 and the axis target "
                                "of 25 are under-5. Different denominators, different series"),
    "COGNITION_LEARNING_REVIEW": ("literacy_rate_youth_pct",
                                  {"world_bank.literacy_rate_adult_pct"},
                                  "adult literacy against a metric that names youth literacy"),
    "INEQUALITY_POVERTY_REVIEW": ("extreme_poverty_rate_pct",
                                  {"world_bank.poverty_190_pct"},
                                  "the $1.90/day line, against a metric whose unit declares "
                                  "$2.15/day — the World Bank's current extreme-poverty line"),
}

# Not mechanically checkable, and why. Each entry is re-qualified by the test
# below, so an axis cannot be parked here once it becomes checkable.
NO_METRIC_DECLARED = {
    "TECHNOLOGY_AI_REVIEW", "TECHNOLOGY_INFRA_REVIEW", "CULTURE_MEDIA_REVIEW",
    "DEEP_TIME_RISKS_REVIEW", "LONG_TERM_FUTURE_REVIEW",
}

# An extract that addresses a row in an API response rather than naming a field.
# What the number IS was decided by the query when the source was promoted, and
# composer_specs does not record it — so no field name exists here to compare.
GENERIC_ADDRESSES = frozenset({"data", "1.0.value"})

# Self-referential: the axis reads the system's own last score by index.
SELF_REFERENTIAL = {"GOAL_PROGRESS_REVIEW": "-1.scores.GOAL_PROGRESS_REVIEW"}


def _classified_extracts(specs):
    """(axis, extract) for every anchor source that names a field at all."""
    for ax, spec in _axes(specs):
        for src in _anchor_sources(spec):
            ex = src.get("extract")
            if ex:
                yield ax, str(ex)


def _named_extracts(specs, axis):
    """The anchor extracts that NAME A FIELD. Generic row addresses and the
    self-referential score path are excused by their own registries above and are
    not part of what a pin affirms."""
    return {str(s["extract"]) for s in _anchor_sources(specs[axis])
            if s.get("extract")
            and str(s["extract"]) not in GENERIC_ADDRESSES
            and SELF_REFERENTIAL.get(axis) != str(s["extract"])}


def test_every_anchor_extract_is_classified(specs):
    """The mechanical net behind the three registries: a new anchor source that
    nobody classified fails, rather than defaulting to 'presumed fine'."""
    unclassified = []
    for ax, ex in _classified_extracts(specs):
        if ex in GENERIC_ADDRESSES:
            continue
        if SELF_REFERENTIAL.get(ax) == ex:
            continue
        if ax in NO_METRIC_DECLARED:
            continue
        if ax in ANCHOR_PINS and ex in ANCHOR_PINS[ax][1]:
            continue
        if ax in KNOWN_MISMATCH and ex in KNOWN_MISMATCH[ax][1]:
            continue
        unclassified.append((ax, ex))
    assert not unclassified, (
        "anchor source(s) nobody has classified against target_config — add each to "
        "ANCHOR_PINS, KNOWN_MISMATCH or a KNOWN_UNCHECKED set WITH A REASON:\n"
        + "\n".join(f"  {a}: {e}" for a, e in unclassified))


@pytest.mark.parametrize("axis", sorted(ANCHOR_PINS))
def test_pinned_axis_still_declares_the_metric_it_was_pinned_against(axis, specs, primary_metric):
    """This is the 11 Sep regression, mechanised. If target_config's metric moves
    and composer_specs does not, the pin no longer matches and this fails."""
    metric, extracts, _why = ANCHOR_PINS[axis]
    assert primary_metric.get(axis) == metric, (
        f"{axis}: target_config primary_metric is {primary_metric.get(axis)!r}, "
        f"the anchor was affirmed against {metric!r}. The composer spec, this pin, "
        f"or both are now stale — re-check which field the anchor should read.")
    found = _named_extracts(specs, axis)
    assert found == extracts, (
        f"{axis}: anchor extracts changed from {sorted(extracts)} to {sorted(found)} "
        f"without the pin being re-affirmed")


@pytest.mark.parametrize("axis", sorted(KNOWN_MISMATCH))
def test_recorded_mismatch_has_not_changed_or_spread(axis, specs, primary_metric):
    """A recorded mismatch is frozen, not tolerated: it may be repaired by a
    deliberate edit to both the spec and this file, and it may not drift."""
    metric, extracts, _why = KNOWN_MISMATCH[axis]
    assert primary_metric.get(axis) == metric, (
        f"{axis}: primary_metric moved to {primary_metric.get(axis)!r}; the recorded "
        f"mismatch was against {metric!r} and must be re-examined")
    found = _named_extracts(specs, axis)
    assert found == extracts, (
        f"{axis}: anchor extracts moved from {sorted(extracts)} to {sorted(found)}; "
        f"if this repaired the mismatch, move the axis to ANCHOR_PINS")


@pytest.mark.parametrize("axis", sorted(NO_METRIC_DECLARED))
def test_unchecked_for_no_metric_still_has_no_metric(axis, primary_metric):
    """An axis parked here because target_config declares no primary_metric must
    still declare none. The day it gains one, it becomes checkable and this fails."""
    assert primary_metric.get(axis) is None, (
        f"{axis} now declares primary_metric={primary_metric.get(axis)!r} — it is no "
        f"longer unchecked-by-absence; classify its anchor in ANCHOR_PINS or KNOWN_MISMATCH")


def test_generic_addresses_are_still_generic(specs):
    """The escape hatch is exact: only these literal addresses are excused, and
    only because they name a row, not a field."""
    for ax, ex in _classified_extracts(specs):
        if ex in GENERIC_ADDRESSES:
            assert "." not in ex.strip(".") or ex == "1.0.value", \
                f"{ax}: {ex!r} is in GENERIC_ADDRESSES but looks like a field path"


# ── CHECK C — a declared indicator is not a measurement ──────────────────────

def _facts(axis="DEEP_TIME_RISKS_REVIEW", declared=("usgs_m5plus_7d_count",),
           values=None):
    """A minimal fact set: one canonical axis, no level, no score — the shape
    that reaches R5."""
    return {
        "levels": {}, "trends": {}, "scores": {}, "sources": {},
        "config_axes": {axis}, "composed": {},
        "measured_by": {axis: list(declared)} if declared else {},
        "indicator_values": dict(values or {}),
    }


def _r5(conclusions):
    return [c for c in conclusions if c["rule_id"] == "R5_BLIND_SPOT"]


def test_r5_silent_when_the_declared_indicator_has_a_value():
    fired = _r5(D.run_rules(_facts(values={"usgs_m5plus_7d_count": 38.0})))
    assert fired == [], f"R5 fired on a measured axis: {fired}"


def test_r5_silent_on_a_zero_value():
    """0.0 is a reading. Testing truthiness instead of None would make a quiet
    week look like a dead sensor."""
    assert _r5(D.run_rules(_facts(values={"usgs_m5plus_7d_count": 0.0}))) == []


def test_r5_fires_and_names_the_indicator_when_it_has_no_value():
    fired = _r5(D.run_rules(_facts(values={})))
    assert len(fired) == 1, "an axis measured by nothing is still a blind spot"
    c = fired[0]
    assert "usgs_m5plus_7d_count" in c["conclusion"], \
        f"R5 fired without naming the missing indicator: {c['conclusion']}"
    assert any(p.get("file") == "memory/alarm_bands_latest.json" and p.get("value") is None
               for p in c["premises"]), \
        "the conclusion does not carry the empty band as a premise a human can check"


def test_r5_fires_when_the_indicator_row_exists_but_carries_null():
    """A row with value None is the bands file saying NO_VALUE. It must read as
    missing, not as present-because-the-row-is-there."""
    fired = _r5(D.run_rules(_facts(values={"usgs_m5plus_7d_count": None})))
    assert len(fired) == 1 and "usgs_m5plus_7d_count" in fired[0]["conclusion"]


def test_r5_names_only_the_indicators_that_are_missing():
    facts = _facts(declared=("usgs_m5plus_7d_count", "some_other_indicator"),
                   values={"usgs_m5plus_7d_count": None, "some_other_indicator": None})
    c = _r5(D.run_rules(facts))[0]
    assert "usgs_m5plus_7d_count" in c["conclusion"]
    assert "some_other_indicator" in c["conclusion"]


def test_one_live_indicator_is_enough():
    facts = _facts(declared=("usgs_m5plus_7d_count", "some_other_indicator"),
                   values={"usgs_m5plus_7d_count": 38.0})
    assert _r5(D.run_rules(facts)) == []


def test_r5_still_fires_for_an_axis_that_declares_nothing():
    """The mutation guard for the original rule: an axis with no level, no score
    and no declaration is the blind spot R5 was written for, and the new branch
    must not swallow it."""
    fired = _r5(D.run_rules(_facts(declared=())))
    assert len(fired) == 1
    assert "usgs" not in fired[0]["conclusion"]


def test_a_declaration_alone_does_not_excuse_an_axis(tmp_path, monkeypatch):
    """End to end through gather_facts with a repo whose alarm_bands file does
    not exist. The declaration is present, the measurement is not, and the
    absence must fire R5 rather than be read as agreement."""
    (tmp_path / "config").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "config" / "target_config.json").write_text(json.dumps({
        "SAFETY": {"DEEP_TIME_RISKS_REVIEW": {"primary_metric": None,
                                              "measured_by_indicator": ["usgs_m5plus_7d_count"]}}
    }), encoding="utf-8")
    monkeypatch.setattr(D, "BASE", tmp_path)

    fired = _r5(D.run_rules(D.gather_facts()))
    assert len(fired) == 1, "a missing alarm_bands file silenced R5"
    assert "usgs_m5plus_7d_count" in fired[0]["conclusion"]


def test_gather_facts_reads_the_value_out_of_the_real_bands_shape(tmp_path, monkeypatch):
    """The reader is pinned to the shape the bands step actually writes:
    indicators.rows[].indicator / .value. A rename there must fail here, not
    degrade into 'no indicator has a value'."""
    (tmp_path / "config").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "config" / "target_config.json").write_text(json.dumps({
        "SAFETY": {"DEEP_TIME_RISKS_REVIEW": {"measured_by_indicator": ["usgs_m5plus_7d_count"]}}
    }), encoding="utf-8")
    (tmp_path / "memory" / "alarm_bands_latest.json").write_text(json.dumps({
        "indicators": {"rows": [{"indicator": "usgs_m5plus_7d_count",
                                 "axis": "DEEP_TIME_RISKS_REVIEW", "value": 38.0}]}
    }), encoding="utf-8")
    monkeypatch.setattr(D, "BASE", tmp_path)

    f = D.gather_facts()
    assert f["measured_by"] == {"DEEP_TIME_RISKS_REVIEW": ["usgs_m5plus_7d_count"]}
    assert f["indicator_values"]["usgs_m5plus_7d_count"] == 38.0
    assert _r5(D.run_rules(f)) == []


def test_deep_time_risks_declaration_is_still_in_the_canon():
    """If the declaration is removed from target_config, the checks above keep
    passing against a fiction. This is the tie to the live file."""
    tc = json.loads(TARGET.read_text(encoding="utf-8"))
    spec = tc["SAFETY"]["DEEP_TIME_RISKS_REVIEW"]
    assert spec.get("measured_by_indicator"), \
        "DEEP_TIME_RISKS_REVIEW no longer declares measured_by_indicator"


# ── CHECK D — the refugee metric reaches the scorer in PERSONS ───────────────
#
# SOCIAL_RELATIONS_REVIEW is the one axis where the composer and target_config
# state the same quantity in DIFFERENT UNITS: composed_indicators carries 29.429
# with unit "millions_persons", target_config declares refugee_population in
# persons with target_value 1_000_000. That looked like a live scoring bug on
# 17 Sep 2026 and it is not — the scorer converts — but nothing held the
# conversion in place, and the failure mode is silent and enormous: compared in
# millions the axis scores 100.0 instead of 3.4.

def _scorer():
    import goal_score_calculator as G
    return G


def test_refugee_metric_reaches_the_scorer_in_persons():
    """goal_score_calculator.py:214 multiplies refugees_millions by 1_000_000
    before it lands in last_observations. Remove that and the axis silently
    scores perfect."""
    G = _scorer()
    val, origin = G._resolve_metric_origin(
        "refugee_population", trends={}, last_obs={"unhcr_refugees": 29_429_000.0})
    assert val == 29_429_000.0, f"resolved {val!r}, not persons"
    assert origin["key"] == "unhcr_refugees"


def test_the_arithmetic_that_produced_the_score_on_record():
    """The live score was 3.4 on the nights of 15, 16 and 17 Sep. This is the
    sum that produced it, so a change to _normalize that moves this axis has to
    move this number too."""
    G = _scorer()
    persons = G._normalize(29_429_000.0, 1_000_000.0, "lower_better", 120_000_000.0)
    assert round(persons * 100, 1) == 3.4

    millions = G._normalize(29.429, 1_000_000.0, "lower_better", 120_000_000.0)
    assert millions == 1.0, "the wrong-unit branch no longer scores a perfect 100"
    assert millions != persons, "the two units are indistinguishable — the guard is dead"


def test_the_trends_path_would_bypass_the_conversion_and_is_empty():
    """THE LATENT FORK, pinned rather than fixed.

    _resolve_metric_origin consults trend_map BEFORE obs_map, and the trends
    branch returns the stored value with NO conversion. trends['refugees'] is
    empty today, so the fork cannot fire and the scorer takes the persons path.
    The day something fills that series in millions, this axis jumps from 3.4 to
    100 with nothing in the output to show why.

    This test fails when the series becomes non-empty. That is the intended
    alarm: fill it and the conversion must be applied on that path too. It is
    not fixed here because changing the resolver changes what the axis scores,
    and that is a decision with a diff of its own.
    """
    G = _scorer()
    bypassed, origin = G._resolve_metric_origin(
        "refugee_population", trends={"refugees": [29.429]},
        last_obs={"unhcr_refugees": 29_429_000.0})
    assert bypassed == 29.429 and origin["where"] == "trends", \
        "the trends branch no longer wins — re-check whether this hazard still exists"

    live = G.load_trends().get("refugees") or []
    assert live == [], (
        f"cortex_memory/abstractions/trends.json['refugees'] is no longer empty "
        f"({live[:3]}...). The scorer now takes the trends branch for "
        f"refugee_population, which does NOT multiply by 1_000_000 — "
        f"SOCIAL_RELATIONS_REVIEW will score 100 instead of 3.4. Apply the "
        f"conversion in _resolve_metric_origin's trends branch before this series "
        f"is used.")


def test_armed_conflicts_is_not_in_the_refugee_anchor(specs):
    """A count of active armed conflicts is not a refugee population. It
    constrains and explains one, which is what indirect_proxy is for."""
    port = specs["SOCIAL_RELATIONS_REVIEW"]["portfolio"]
    anchor_ids = {s["id"] for s in port["anchor_annual"]["sources"]}
    proxy_ids = {s["id"] for s in port["indirect_proxy"]["sources"]}
    assert "promoted_96302" not in anchor_ids, \
        "the armed-conflict count is back in the anchor slot"
    assert "promoted_96302" in proxy_ids, \
        "the armed-conflict count was dropped instead of demoted — it is evidence, keep it"
