"""An axis may not be scored on another axis's instrument, and a declared
indicator is not a measurement until it carries a value.

THE DEFECT, twice. On 11 Sep 2026 MATERIALS_WASTE_REVIEW's primary_metric in
config/target_config.json was changed from co2_ppm_mauna_loa to
adjusted_net_savings_pct, because the axis was being scored on CO2 — the identical
reading CLIMATE_GLOBAL_RISK_REVIEW is scored on. config/composer_specs.json was
NOT changed with it. For six more nights the composer kept filling the axis's
anchor from NOAA co2.co2_ppm, R7_SENSOR_REUSE kept reporting the pair, and the
config said one thing while the sensor did another.

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
"""
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

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
    "FOOD_REVIEW": ("food_insecurity_pct",
                    {"food.undernourishment_pct"},
                    "FAO prevalence of undernourishment (PoU) is not the FIES "
                    "food-insecurity rate the metric names; the two differ by a "
                    "factor of roughly three at the global level"),
    "ENERGY_REVIEW": ("renewable_energy_pct",
                      {"world_bank.renewable_elec_pct"},
                      "renewable share of ELECTRICITY, against a metric whose unit is "
                      "'percent of total energy' — a different denominator, and the "
                      "IEA 80% target the rationale cites is for total energy"),
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
    "SOCIAL_RELATIONS_REVIEW": ("refugee_population",
                                {"displaced.refugees_millions", "conflicts.active_armed_conflicts"},
                                "two faults in one slot: refugees are reported in MILLIONS against "
                                "a target expressed in persons (1,000,000), and the second anchor "
                                "source counts armed conflicts, which is not a refugee population"),
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
