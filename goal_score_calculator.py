"""
goal_score_calculator.py
========================
Computes a weighted composite civilization goal score from:
  - trend vectors in cortex_memory/abstractions/trends.json  (MerkleMemory)
  - live observations in data/last_observations.json
  - scientific thresholds in config/target_config.json

Returns:
  {
    "composite_score":  float  0-1,
    "axis_scores":      {axis: score},
    "metric_details":   {metric: {current, target, score, tti_cycles}},
    "timestamp":        str,
  }

Time-to-threshold (TTI): linear extrapolation over last N trend points.
  positive tti  = cycles until target is reached at current rate
  negative tti  = already past target
  None          = no trend data or metric moving away from target
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── paths ─────────────────────────────────────────────────────────────────────
BASE                = Path(__file__).resolve().parent
TRENDS_FILE         = BASE / "cortex_memory" / "abstractions" / "trends.json"
LAST_OBS_FILE       = BASE / "data" / "last_observations.json"
TARGET_CFG_FILE     = BASE / "config" / "target_config.json"
WELLBEING_GLOBE_FILE = BASE / "output" / "wellbeing_globe.json"
GLOBAL_IND_FILE     = BASE / "snapshots" / "master" / "global_indicators_latest.json"
GLOBAL_IND_FRESHNESS_DAYS = 14
PROBED_FILE         = BASE / "memory" / "probed_signals.json"   # what the organism's own hands fetched

# How many trend points to use for linear extrapolation
TTI_WINDOW = 10

# Governance globals (from wellbeing_globe.py --governance-only) older than this
# are treated as unavailable rather than silently consumed as a frozen "real" score.
GOVERNANCE_FRESHNESS_DAYS = 90


# ── loaders ───────────────────────────────────────────────────────────────────

def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def load_trends() -> dict:
    return _load(TRENDS_FILE, {})


def load_last_obs() -> dict:
    return _load(LAST_OBS_FILE, {})


def load_targets() -> dict:
    return _load(TARGET_CFG_FILE, {})


def load_governance_globals() -> dict:
    """
    Load the two governance axis globals from output/wellbeing_globe.json,
    gated by a freshness check on governance_computed_at.

    Returns {} (axes fall back to qualitative 0.5) if the file is missing,
    has no timestamp, or the timestamp is older than GOVERNANCE_FRESHNESS_DAYS —
    always with a loud stderr warning, never a silent stale "real" score.
    """
    data = _load(WELLBEING_GLOBE_FILE, {})
    ts_str = data.get("governance_computed_at")
    if not ts_str:
        print(
            "[goal_score] WARNING: output/wellbeing_globe.json has no governance_computed_at "
            "— GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL / GOVERNANCE_INSTITUTIONS_REVIEW falling back to 0.5. "
            "Run: python wellbeing_globe.py --governance-only",
            file=sys.stderr,
        )
        return {}
    try:
        ts = datetime.fromisoformat(ts_str)
    except ValueError:
        print(
            f"[goal_score] WARNING: unparsable governance_computed_at={ts_str!r} "
            "— governance axes falling back to 0.5.",
            file=sys.stderr,
        )
        return {}

    age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
    if age_days > GOVERNANCE_FRESHNESS_DAYS:
        print(
            f"[goal_score] WARNING: governance globals are {age_days:.0f} days old "
            f"(> {GOVERNANCE_FRESHNESS_DAYS}d freshness threshold) — falling back to 0.5. "
            f"Run: python wellbeing_globe.py --governance-only",
            file=sys.stderr,
        )
        return {}

    # The two governance globals are DERIVED, not fetched: wellbeing_globe computes
    # them from WGI+VDEM. The honest observation date is when that computation ran —
    # 57 days before this line was written — not tonight's cycle timestamp.
    when = str(ts_str)[:10] if ts_str else None
    why = (f"wellbeing_globe governance_computed_at = {when} (derived from "
           f"WGI+VDEM, both annual); the value has not been recomputed since"
           if when else "output/wellbeing_globe.json carries no governance_computed_at")
    for k in ("governance_rights_score_global", "governance_institutions_score_global"):
        _OBS_DATES[k] = when
        _OBS_DATE_WHY[k] = why
    return {
        "governance_rights_score_global":       data.get("governance_rights_score"),
        "governance_institutions_score_global": data.get("governance_institutions_score"),
    }


# ── WHEN THE WORLD WAS OBSERVED (4 Sep 2026, ITEM B) ─────────────────────────
# axis_observations carried observed_value, observation_key, source_id — and
# nothing at all about WHEN the world was looked at. That is why the staleness was
# invisible: K1 could not tell a reading taken yesterday from one taken in 2021,
# because the field did not exist. Measured that day: 95 of the 105 "measured"
# weight had not changed once in 30 cycles; ENERGY was publishing a 2021 number
# nightly.
#
# NEVER A GUESS. A source that gives no date gets None and a reason. A bare year
# is resolved to 31 December of that year, which is the MOST GENEROUS reading and
# therefore a LOWER BOUND on the age — stated in the reason so nobody mistakes it
# for a day-precise observation.
_OBS_DATES: dict = {}
_OBS_DATE_WHY: dict = {}


def _year_to_date(year) -> str | None:
    """"2024" -> "2024-12-31". The generous end of the year: an annual figure is
    for the whole year, so the latest moment it could describe is its last day."""
    try:
        y = int(str(year).strip()[:4])
    except (TypeError, ValueError):
        return None
    return f"{y:04d}-12-31" if 1900 <= y <= 2999 else None


def observation_dates() -> tuple:
    """(dates, reasons) for the keys load_global_indicators() last produced."""
    return dict(_OBS_DATES), dict(_OBS_DATE_WHY)


def load_global_indicators() -> dict:
    """Adapt the LIVE global_indicators_latest.json (written each cycle by
    core.global_indicators.fetch_all) into the flat obs keys _resolve_metric
    expects. Fresh data overrides stale data/last_observations.json.
    Freshness-gated; loud stderr + {} if missing or too old."""
    data = _load(GLOBAL_IND_FILE, {})
    if not data:
        print("[goal_score] WARNING: global_indicators_latest.json missing — dead axes stay 0.5.", file=sys.stderr)
        return {}
    ts_str = data.get("timestamp")
    if ts_str:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts_str)).total_seconds() / 86400
            if age > GLOBAL_IND_FRESHNESS_DAYS:
                print(f"[goal_score] WARNING: global_indicators {age:.0f}d old (>{GLOBAL_IND_FRESHNESS_DAYS}d) — not used.", file=sys.stderr)
                return {}
        except ValueError:
            pass
    co2, wb   = data.get("co2", {}),   data.get("world_bank", {})
    food, dsp = data.get("food", {}),  data.get("displaced", {})
    econ, cty = data.get("economy", {}), data.get("cities", {})
    waste     = data.get("waste", {})
    out: dict = {}
    wb_years = wb.get("_observed_years") or {}

    def put(k, v, when=None, why=None):
        """Record the value AND when the world was observed for it.

        `when` is an ISO date or None. `why` says where the date came from, or why
        there is none - a null with a reason is a fact; a null on its own is the
        gap that hid five-year-old numbers behind a nightly timestamp.
        """
        if v is None:
            return
        out[k] = v
        _OBS_DATES[k] = when
        _OBS_DATE_WHY[k] = why or (
            "the source publishes no observation date for this indicator")

    def wb_put(k, field):
        """A World Bank indicator, dated from _observed_years (a bare year)."""
        yr = wb_years.get(field)
        put(k, wb.get(field), _year_to_date(yr),
            (f"World Bank _observed_years[{field}] = {yr}; a bare year is read as "
             f"31 Dec, so the age is a LOWER BOUND" if yr else
             f"World Bank returned no year for {field}"))
    put("noaa_co2_ppm", co2.get("co2_ppm"), co2.get("co2_date"),
        f"NOAA Mauna Loa co2_date = {co2.get('co2_date')}")
    wb_put("wb_AG.LND.FRST.ZS", "forest_area_pct")
    wb_put("wb_EG.ELC.RNEW.ZS", "renewable_elec_pct")
    wb_put("wb_SH.H2O.SMDW.ZS", "safe_water_access_pct")
    put("wb_SH.DYN.MORT",       wb.get("infant_mortality_per1k"))     # APPROX: infant vs under-5
    wb_put("wb_SI.POV.DDAY", "poverty_190_pct")
    put("wb_SE.ADT.1524.LT.ZS", wb.get("literacy_rate_adult_pct"))    # APPROX: adult vs youth
    put("wb_SN.ITK.DEFC.ZS", food.get("undernourishment_pct"), None,
        "World Bank WDI Food block carries no _observed_years; the source publishes annually but the fetch does not keep the year")
    r = dsp.get("refugees_millions")
    _uy = dsp.get("unhcr_year")
    put("unhcr_refugees", r * 1_000_000 if r is not None else None,
        _year_to_date(_uy),
        (f"UNHCR unhcr_year = {_uy}; a bare year is read as 31 Dec, so the age is "
         f"a LOWER BOUND" if _uy else "UNHCR returned no year"))
    put("wb_NY.GDP.MKTP.KD.ZG", econ.get("gdp_growth_annual_pct"), None,
        "World Bank WDI Economy block carries no _observed_years")
    put("wb_SP.URB.TOTL.IN.ZS", cty.get("urban_population_pct"), None,
        "World Bank WDI Cities block carries no _observed_years")
    # THE LAST TWO UNRESOLVED METRICS. _resolve_metric has mapped
    # protected_terrestrial_area_pct -> wb_ER.LND.PTLD.ZS and
    # primary_completion_rate -> wb_SE.PRM.CMPT.ZS since it was written; nothing
    # ever put those keys INTO last_obs, so both axes reported metric_unresolved
    # every cycle. 14 of the then-173 goal weight, waiting on two lines.
    # (167 across 24 axes since commit 8052397, 2026-08-21 — neither of these
    #  two axes left the tree, so the 14 is unchanged.)
    wb_put("wb_ER.LND.PTLD.ZS", "protected_terrestrial_area_pct")
    wb_put("wb_SE.PRM.CMPT.ZS", "primary_completion_rate")
    # MATERIALS_WASTE_REVIEW (11 Sep 2026). Until today this axis scored on
    # co2_ppm_mauna_loa — the same number as CLIMATE — which the brain reported
    # as a sensor conflict five nights running (7–11 Sep). Adjusted net savings
    # (World Bank NY.ADJ.SVNG.GN.ZS: net saving after depletion of natural
    # capital and pollution damage, % of GNI) is the Bank's own measure of
    # whether a society is eating its future — the closest published number to
    # "materials and waste, sustainably". The Waste block carries no
    # _observed_years, so the age is unknown and said so.
    put("wb_NY.ADJ.SVNG.GN.ZS", waste.get("adjusted_net_savings_pct"), None,
        "World Bank WDI Waste block carries no _observed_years")
    return out


def load_probed_signals() -> dict:
    """Signals the organism's OWN hands fetched (memory/probed_signals.json).
    ONLY the 'validated_obs' block feeds the score — self-discovered probes stay
    in the file's audit, pending semantic validation, so an unvalidated auto-found
    number can never move the goal. This is probe -> scoring, closed and gated."""
    data = _load(PROBED_FILE, {})
    obs = data.get("validated_obs", {}) if isinstance(data, dict) else {}
    return {k: v for k, v in obs.items() if isinstance(v, (int, float))}


# ── metric resolution ─────────────────────────────────────────────────────────

# WHICH FEED A KEY BELONGS TO. The prefix of an observation key already names
# its origin — noaa_, wb_, unhcr_ — and until 28 Aug 2026 that fact lived only
# in a reader's head. K1 (ITEM 7.1) has to say WHY an axis counts as measured,
# and "it has a number" is not a why; "NOAA, key noaa_co2_ppm, 424.61" is.
# FAIL-OPEN ON THE LABEL, NEVER ON THE KEY: an unrecognised prefix yields
# source_id "unattributed" and the axis still counts as measured, because the
# observation key IS named and checkable. A missing key is a different thing
# and is never measured.
_SOURCE_BY_PREFIX = (
    ("noaa_",   "NOAA"),
    ("wb_",     "WORLD_BANK"),
    ("unhcr_",  "UNHCR"),
    ("gbif_",   "GBIF"),
    ("owid_",   "OWID"),
    ("vdem_",   "V_DEM"),
    ("eia_",    "EIA"),
    ("ucdp_",   "UCDP"),
    # Not a feed prefix but a real, checkable origin: these two keys are
    # computed by wellbeing_globe.py and read from output/wellbeing_globe.json
    # under a freshness gate (load_governance_globals below).
    ("governance_", "WELLBEING_GLOBE"),
)


def _source_id_for(obs_key: str) -> str:
    """The feed an observation key came from, from its prefix. 'unattributed'
    when no prefix matches — a named gap, not a silent one."""
    k = str(obs_key or "")
    for prefix, name in _SOURCE_BY_PREFIX:
        if k.startswith(prefix):
            return name
    return "unattributed"


def _resolve_metric_origin(metric_name: str, trends: dict,
                           last_obs: dict) -> tuple[float | None, dict | None]:
    """
    Find the current value for a metric AND say where it came from.

    Returns (value, origin). origin is None whenever value is None — an
    unresolved metric has no provenance to report, and reporting one would be
    the exact confusion this function exists to end. When value is not None,
    origin carries: where ("trends" | "last_observations"), key (the literal
    key that resolved), source_id (the feed) and metric.

    _resolve_metric() below keeps its old signature and delegates here, so the
    call sites and test/test_k1_metrics_resolve.py that expect a bare float
    are untouched.
    """
    if not metric_name:
        return None, None

    # Trends keys (MerkleMemory naming)
    trend_map = {
        "co2_ppm_mauna_loa":          "co2_ppm",
        "co2_ppm":                    "co2_ppm",
        "refugee_population":         "refugees",
        "total_refugees":             "refugees",
        "species_observations_30d":   "gbif_30d",
        "goal_score":                 "goal_score",
        "kp_index":                   "kp_index",
    }
    trend_key = trend_map.get(metric_name)
    if trend_key and trends.get(trend_key):
        return float(trends[trend_key][-1]), {
            "where": "trends", "key": trend_key,
            "source_id": _source_id_for(trend_key), "metric": metric_name}

    # last_observations keys
    obs_map = {
        "co2_ppm_mauna_loa":          "noaa_co2_ppm",
        "co2_ppm":                    "noaa_co2_ppm",
        "child_mortality_per_1000":   "wb_SH.DYN.MORT",
        "safe_water_access_pct":      "wb_SH.H2O.SMDW.ZS",
        "extreme_poverty_rate_pct":   "wb_SI.POV.DDAY",
        "refugee_population":         "unhcr_refugees",
        "literacy_rate_youth_pct":    "wb_SE.ADT.1524.LT.ZS",
        "primary_completion_rate":    "wb_SE.PRM.CMPT.ZS",
        "forest_area_pct":            "wb_AG.LND.FRST.ZS",
        "protected_terrestrial_area_pct": "wb_ER.LND.PTLD.ZS",
        "urbanization_pct":           "wb_SP.URB.TOTL.IN.ZS",
        "gdp_growth_pct":             "wb_NY.GDP.MKTP.KD.ZG",
        "food_insecurity_pct":        "wb_SN.ITK.DEFC.ZS",
        "renewable_energy_pct":       "wb_EG.ELC.RNEW.ZS",
        "adjusted_net_savings_pct":   "wb_NY.ADJ.SVNG.GN.ZS",
    }
    obs_key = obs_map.get(metric_name, metric_name)
    val = last_obs.get(obs_key)
    if val is not None:
        if metric_name == "refugee_population" and float(val) == 0.0:
            return None, None  # sentinel zero, not a real count
        return float(val), {
            "where": "last_observations", "key": obs_key,
            "source_id": _source_id_for(obs_key), "metric": metric_name}

    return None, None


def _resolve_metric(metric_name: str, trends: dict, last_obs: dict) -> float | None:
    """The value alone. Kept because callers and tests ask only for the number;
    the provenance half is _resolve_metric_origin()."""
    return _resolve_metric_origin(metric_name, trends, last_obs)[0]


# ── scoring ───────────────────────────────────────────────────────────────────

def _normalize(
    current: float, target: float, direction: str, reference_worst: float | None = None
) -> float:
    """
    Returns a 0-1 score.
      1.0  = at or better than target
      0.0  = at or worse than reference_worst

    For lower_better:
      - If target > 0: score = target / current  (ratio; 1.0 at target, decays to 0)
      - If target = 0: score = 1 - current / reference_worst  (reference needed)
    For higher_better:
      - score = current / target  (capped at 1.0)
    For stable_better:
      - 0.5 (no directional pressure)
    """
    if direction == "lower_better":
        if current <= target:
            return 1.0
        if target > 0:
            return min(1.0, target / current)
        else:  # target = 0: use reference_worst as denominator
            worst = reference_worst if reference_worst else max(current * 2, 1.0)
            return max(0.0, 1.0 - current / worst)

    elif direction == "higher_better":
        if target <= 0:
            return 1.0 if current >= 0 else 0.0
        return min(1.0, current / target)

    else:  # stable_better
        return 0.5


def _time_to_threshold(
    metric_name: str,
    current: float,
    target: float,
    direction: str,
    trends: dict,
) -> float | None:
    """
    Linear extrapolation: how many cycles until target is reached?
    Returns None if not computable or moving wrong direction.
    """
    trend_map = {
        "co2_ppm_mauna_loa": "co2_ppm",
        "co2_ppm":           "co2_ppm",
        "refugee_population": "refugees",
        "goal_score":        "goal_score",
    }
    key = trend_map.get(metric_name)
    if not key:
        return None

    series = trends.get(key, [])
    if len(series) < 2:
        return None

    window = series[-TTI_WINDOW:]
    # Simple linear regression slope
    n = len(window)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(window) / n
    num = sum((xs[i] - x_mean) * (window[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    if abs(den) < 1e-12:
        return None

    slope = num / den  # units per cycle

    if direction == "lower_better":
        if slope >= 0:
            return None  # moving away from target
        gap = current - target
        return round(gap / (-slope), 1)

    elif direction == "higher_better":
        if slope <= 0:
            return None
        gap = target - current
        return round(gap / slope, 1)

    return None


# ── ДВЕТЕ КОЛОНИ (Kimi, 15 август 2026, стъпка 14 от 53) ─────────────────────
# „Мнение без вход е халюцинация, не данни. Отделна колона, без тегло в композита."
# „23.7% тегло без метрика е 23.7% лъжа. Концептуалните оси са легитимни като
#  семантични оценки, не като тегло в числов композит."
#
# КЛАСИФИКАЦИЯТА Е СТРУКТУРНА, НЕ ДНЕВНА. Ако решавах „семантична е онази ос, която
# днес няма число", тогава един счупен fetch щеше тихо да изважда оста от знаменателя
# и покритието щеше да СЕ ПОДОБРЯВА при повреда. Затова тук се пита само какво казва
# КОНФИГУРАЦИЯТА — а дневната несполука остава в измеримата колона и тежи, както
# трябва да тежи.
SEMANTIC_ASSESSMENTS = BASE / "memory" / "browse_sources"


WEIGHTS_VERSION = "v0"
WEIGHTS_V0_TOTAL = 167          # frozen 2026-09-10; see branch_shares.__doc__


def branch_shares(targets: dict) -> dict:
    """REPORTING ONLY. Per-branch weight sums, and those sums as percentages.

    ── PROGRESS 1.3, DECIDED 10 September 2026 ──
    The per-axis weights are FROZEN AS v0 exactly as they stand (untouched since
    21 Aug): climate 10, water 9, food 9 — the stated principle holds per axis,
    and no weight is changed by this decision.

    What this function exists to stop is a habit of quoting. The weights are on
    a declared 1-10 scale and sum to 167, and 167 was being read as if it were
    a percentage total. Normalised, the branches stand at:

        SUSTAINABLE_RESOURCES     38/167 = 22.8 %   (5 axes)
        HEALTHY_ENVIRONMENTS      25/167 = 15.0 %   (3 axes)
        CIVILIZATIONAL_STABILITY  60/167 = 35.9 %   (9 axes)
        KNOWLEDGE_UNDERSTANDING   14/167 =  8.4 %   (2 axes)
        SAFETY                    30/167 = 18.0 %   (5 axes)

    THE KNOWN DEFECT, NAMED RATHER THAN DEFENDED. Those shares are an artefact
    of how many axes a branch happens to contain, because the composite is a
    weighted mean over AXES (weighted_sum / measured_weight) and knows nothing
    about branches. So adding any axis to CIVILIZATIONAL_STABILITY raises that
    branch's share of the goal without anyone deciding to raise it — unowned
    drift of exactly the kind this project exists to catch. It is recorded as a
    defect, not as a property.

    WHAT WAS DELIBERATELY NOT DONE, and it is Emil's ruling of 10 Sep, confirmed
    rather than inferred: no gate refuses the nightly cycle until a human
    renormalises the weights. Taking the night down over a reporting cosmetic
    would cost more than the cosmetic. This function changes NO number that
    reaches composite_score — it is called by reporting and by
    test_axis_tree_contract, and the reversible default is that the weights stay
    exactly as they are until a human decides otherwise.
    """
    out = {}
    total = 0.0
    for branch, axes in sorted((targets or {}).items()):
        if str(branch).startswith("_"):
            continue
        s = sum(float(cfg.get("weight", 0) or 0)
                for cfg in axes.values() if isinstance(cfg, dict))
        out[branch] = {"weight_sum": round(s, 1), "n_axes": len(axes)}
        total += s
    for branch in out:
        out[branch]["share_pct"] = (round(100.0 * out[branch]["weight_sum"] / total, 1)
                                    if total else 0.0)
    return {"weights_version": WEIGHTS_VERSION, "total_weight": round(total, 1),
            "branches": out,
            "note": ("weights are on a 1-10 per-axis scale and do NOT sum to 100; "
                     "share_pct is a reporting-only normalisation. Branch shares "
                     "follow axis COUNT and are a known defect, not a decision — "
                     "the composite is a weighted mean over axes, not over branches.")}


def config_fingerprint(targets: dict) -> str:
    """Отпечатък на ТОВА, КОЕТО МЕРИМ — не на това, което днес сме успели.

    Kimi, 15 август 2026, стъпка 14→15, след като му предложих и двата варианта:
      „(Б). (А) е архитектурно чисто, но епистемично безполезно — замразява
       learning-а във вечно чакане. Структурният отпечатък казва «какво мерим»,
       не «какво успяхме днес» — това е принцип, не удобство."

    Затова тук влиза САМО конфигурацията: кои оси изобщо са допуснати до числото,
    с какви тегла и от какъв род. Днешната несполука на един източник НЕ къса
    сравнимостта (тя се вижда в coverage_of_measurable, което пътува отделно), но
    промяна като днешната — 59 тегло излиза от числителя — я къса, и трябва.

    Всеки, който сравнява два композита през времето (dream.goal_delta,
    prophecy._score_matured), е длъжен да сравнява само при ЕДНАКЪВ отпечатък.
    Различен отпечатък = различни светове."""
    rows = []
    for dom, axes in sorted((targets or {}).items()):
        if str(dom).startswith("_"):
            continue
        for ax, cfg in sorted(axes.items()):
            kind, _ = axis_kind(cfg)
            rows.append(f"{ax}|{float(cfg.get('weight', 1))}|{kind}")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:16]


def axis_kind(cfg: dict) -> tuple:
    """('measured'|'semantic', причина). Свойство на конфигурацията, не на деня."""
    metric = cfg.get("primary_metric")
    if not metric:
        return "semantic", ("no_primary_metric: концептуална ос без честен скалар "
                            "(достойнство, култура, риск) — оценява се, не се смята")
    if metric == "goal_score":
        return "semantic", ("self_reference: показателят на оста Е самият композит — "
                            "самооценка, не вход")
    if cfg.get("direction") == "stable_better" and cfg.get("target_value") is None:
        return "semantic", ("stable_better_unimplemented: постоянството иска мярка за "
                            "разсейване във времето; такава няма реализирана")
    return "measured", ""


def _semantic_reading(axis_name: str) -> dict:
    """Какво КАЗВА семантичната оценка за тази ос, ако изобщо има такава.

    Липсата се обявява. Празна колона, която мълчи, е същият гроб, за който
    Kimi предупреди — само че изкопан от друга страна."""
    import re as _re
    key = _re.sub(r"[^a-z0-9]+", "_", axis_name.lower())[:40]
    p = SEMANTIC_ASSESSMENTS / f"semantic_{key}.json"
    d = _load(p, {})
    if not d:
        return {"assessed": False,
                "why": ("няма семантична оценка на диск — semantic_scout още не се "
                        "вика от цикъла; осата е ЧИСТА ДУПКА, не 'стабилна'")}
    return {"assessed": True,
            "direction": d.get("direction"),
            "confidence": d.get("confidence"),
            "contested": d.get("contested"),
            "assessment": (d.get("assessment") or "")[:400],
            "counterview": (d.get("strongest_counterview") or "")[:300],
            "evidence_kept": len(d.get("key_evidence") or []),
            "evidence_dropped_ungrounded": d.get("evidence_dropped_ungrounded"),
            "assessed_at": d.get("assessed_at")}


def format_headline(res: dict) -> str:
    """ЕДИНСТВЕНИЯТ разрешен начин числото да излезе пред човек или в отчет.

    Kimi, 15 август 2026: „Число без семантика е театър (или «тъмна цифра» — едно
    и също). Консуматор, който иска само числото, получава пакета или нищо."
    Затова пакетът е СГЛОБЕН ТУК, а test/test_goal_score_package.py чупи билда,
    ако някой модул вземе composite_score и го покаже без покритието."""
    n_sem = len(res.get("semantic_axes") or {})
    n_unassessed = sum(1 for v in (res.get("semantic_axes") or {}).values()
                       if not (v.get("reading") or {}).get("assessed"))
    return (f"композит {res['composite_score']:.4f} "
            f"| {res['coverage_of_measurable']:.0%} от измеримото "
            f"(сетива {'ОК' if res['sensors_ok'] else 'НЕ'}) "
            f"| {res['coverage_of_goal']:.0%} от целта "
            f"(покрита {'ДА' if res['goal_covered'] else 'НЕ'}) "
            f"| {n_sem} семантични оси извън числото, {n_unassessed} от тях неоценени")


GOAL_SCORE_SNAPSHOT = BASE / "snapshots" / "master" / "goal_score_latest.json"


def persist(result: dict) -> Path:
    """Записва пакета там, където останалата система го чете.

    Съществува, защото записът беше разписан САМО в fast_cycle_runner, а
    core.reconsider преизчисляваше композита и ИЗХВЪРЛЯШЕ резултата. Всички
    останали действия на преправянето (нива, дедукция, постоянство) записват; това
    не записваше нищо — значи отпечатъкът, който решава дали връщането е било
    празно, не можеше да види ефекта му. Един път за запис, за да няма втори."""
    GOAL_SCORE_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    GOAL_SCORE_SNAPSHOT.write_text(
        json.dumps({**result, "axis": "GOAL_SCORE", "source_type": "CALCULATED"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return GOAL_SCORE_SNAPSHOT


# ── main calculator ───────────────────────────────────────────────────────────

def compute_goal_score(
    trends: dict | None = None,
    last_obs: dict | None = None,
    targets: dict | None = None,
) -> dict:
    """
    Computes weighted composite civilization goal score.

    Returns a dict with composite_score, per-axis scores, and metric details.
    """
    if trends is None:
        trends = load_trends()
    if last_obs is None:
        # ONE CLEAR PER ASSEMBLY. load_governance_globals() runs before
        # load_global_indicators() in this merge, so a clear inside either loader
        # wipes the other's dates — which is exactly what silently happened to the
        # two governance axes on the first attempt.
        _OBS_DATES.clear()
        _OBS_DATE_WHY.clear()
        last_obs = {**load_last_obs(), **load_governance_globals(),
                    **load_global_indicators(), **load_probed_signals()}
    if targets is None:
        targets = load_targets()

    metric_details: dict = {}
    axis_scores:    dict = {}
    # ── PROVENANCE, KEYED BY AXIS (28 Aug 2026, ITEM 7.1c) ──────────────────
    # metric_details is keyed by METRIC, and two axes can declare the same one:
    # MATERIALS_WASTE_REVIEW and CLIMATE_GLOBAL_RISK_REVIEW both point at
    # co2_ppm_mauna_loa, so the first was silently overwritten in that dict and
    # its 9 weight vanished from anything reading it per axis. K1 is a weight
    # sum, so a collision there is a wrong number, not a cosmetic loss. This
    # block is keyed by axis and cannot collide.
    axis_observations: dict = {}
    # The date register is filled by the loaders above (load_global_indicators and
    # load_governance_globals). Read once here so a caller that supplied its own
    # last_obs — a test — still gets a well-formed, empty register rather than a
    # crash or, worse, dates belonging to a different run.
    _obs_dates, _obs_why = observation_dates()

    total_weight    = 0.0
    weighted_sum    = 0.0
    unmeasured_reasons = {}          # ос -> {weight, why}: незнанието с ИМЕ
    measured_weight = 0.0      # теглото, зад което наистина стои число
    measurable_weight = 0.0    # теглото, зад което ИЗОБЩО МОЖЕ да стои число
    semantic_axes: dict = {}   # втората колона: оценява се, не се смята

    for domain_key, axes in targets.items():
        if domain_key.startswith("_"):
            continue
        for axis_name, cfg in axes.items():
            metric      = cfg.get("primary_metric")
            target_val  = cfg.get("target_value")
            direction   = cfg.get("direction", "higher_better")
            weight      = float(cfg.get("weight", 1))
            unit        = cfg.get("unit", "")
            kind, kind_why = axis_kind(cfg)

            # ── КРЪГЪТ (Kimi, 15 август 2026, стъпка 14 от 53) ───────────────
            # GOAL_PROGRESS_REVIEW има primary_metric = "goal_score", а в
            # _resolve_metric стои trend_map["goal_score"] = "goal_score". Тоест
            # вчерашният композит влизаше в днешния с тегло 8 от 173 (тогава;
            # 167 след 8052397, 2026-08-21) и композитът
            # частично измерваше САМ СЕБЕ СИ. Такава редица се влачи след
            # собственото си минало и изглежда стабилна независимо какво прави
            # светът — привидна стабилност, купена с автокорелация.
            #   Kimi: „Прекъсва се. goal_score се ражда от измерените оси;
            #          GOAL_PROGRESS_REVIEW е самооценка, не вход."
            self_reference = (metric == "goal_score")
            current_val, origin = ((None, None) if self_reference
                                   else (_resolve_metric_origin(metric, trends, last_obs)
                                         if metric else (None, None)))

            reference_worst = cfg.get("reference_worst")
            if self_reference:
                score = None      # самооценката не се самооценява
                tti   = None
            elif current_val is not None and target_val is not None:
                score = _normalize(current_val, target_val, direction, reference_worst)
                tti   = _time_to_threshold(metric, current_val, target_val, direction, trends)
            elif direction == "stable_better":
                # ── ОСТАНАЛОТО 0.5 (15 август 2026) ──────────────────────────
                # Вчера махнахме „няма данни -> 0.5". Този клон оцеля и вършеше
                # същото: ECONOMY_WORK_REVIEW и INFRASTRUCTURE_CITIES_REVIEW имат
                # target_value: null, значи ВИНАГИ падаха тук и ВИНАГИ даваха 0.5 —
                # 10 от 173 тегло (5.8%) константа — 173 е стойността от 15 авг;
                # 167 след 8052397 — при това броена за ИЗМЕРЕНА,
                # тоест надуваща покритието вместо да показва незнание.
                # „stable_better" иска мярка за ПОСТОЯНСТВО (разсейване във времето),
                # а такава тук няма реализирана. Липсващата мярка е None, не 0.5.
                score = None
                tti   = None
            else:
                # ── КОНСЕНСУС С KIMI, 15 август 2026 ─────────────────────────
                # Дотук тук пишеше: „Qualitative / no data -> neutral 0.5", и това
                # 0.5 влизаше в претеглената сума С ПЪЛНОТО СИ ТЕГЛО. Преброено:
                # 11 от 25 оси нямаха разрешено число, тоест 65 от 173 тегло
                # (дървото е 24 оси / 167 тегло след 8052397, 2026-08-21) —
                # 38% ОТ КОМПОЗИТА стоеше на константа. Първата от тях беше
                # CLIMATE_GLOBAL_RISK_REVIEW, с най-високото тегло в конфигурацията.
                #
                # Kimi, дословно:
                #   „Оси без числа не са 'неизмервани' — те са ИЗМЕРЕНИ ОТ LLM БЕЗ
                #    КОНТРОЛ, което е по-опасно от призната невежда."
                #   „Не махай 0.5 — замени го с NULL, но остави осите в знаменателя.
                #    Така липсата се вижда."
                #   „Сравнимост: двойка (score, coverage). Ден с 62% не е сравним с
                #    95% — това не е бъг, а истина."
                #   „Едно число при 38% незнание е СТАТИСТИЧЕСКА ЛЪЖА. Публикуваш
                #    score само при coverage >= праг, иначе 'insufficient data'."
                #
                # Затова: липсата вече е None, не 0.5. Тежестта ѝ НЕ влиза в
                # числителя (иначе незнанието щеше да оценява), но влиза в общото
                # тегло — така покритието се вижда, вместо да се крие.
                score = None
                tti   = None

            axis_scores[axis_name] = round(score, 4) if score is not None else None
            total_weight  += weight
            if kind == "measured":
                measurable_weight += weight
            else:
                # ВТОРАТА КОЛОНА. Тежи спрямо ЦЕЛТА, но не влиза в числото.
                semantic_axes[axis_name] = {
                    "weight": weight,
                    "share_of_goal": None,      # попълва се долу, щом знаем сбора
                    "why_not_numeric": kind_why,
                    "reading": _semantic_reading(axis_name),
                }
            if score is not None:
                weighted_sum  += score * weight
                measured_weight += weight
            elif kind == "measured":
                # ОСТА Е ИЗМЕРИМА, НО ДНЕС НЯМА ЧИСЛО — това е повреда, не природа,
                # и затова остава в измеримата колона и ТЕЖИ. (Семантичните оси имат
                # собствена колона и не се броят тук, за да не се смесва „няма как да
                # се измери" с „днес не се измери".)
                unmeasured_reasons[axis_name] = {
                    "weight": weight,
                    "why": (f"metric_unresolved: '{metric}' не се разрешава от "
                            f"trends/last_observations днес")}

            if origin:
                axis_observations[axis_name] = {
                    "metric":            metric,
                    "observation_key":   origin["key"],
                    "observation_where": origin["where"],
                    "source_id":         origin["source_id"],
                    "observed_value":    current_val,
                    # WHEN THE WORLD WAS OBSERVED (ITEM B, 4 Sep 2026). Without
                    # this field K1 cannot tell a reading taken yesterday from one
                    # taken in 2021, and on 4 Sep it could not: 95 of 105
                    # "measured" weight had not moved in 30 cycles. None is a fact
                    # here, not an omission — observed_at_why says which.
                    "observed_at":       _obs_dates.get(origin["key"]),
                    "observed_at_why":   _obs_why.get(
                        origin["key"], "no date register entry for this key"),
                    "weight":            weight,
                    # The metric resolving and the axis getting a score are two
                    # different events: a metric with no target_value resolves
                    # and still scores None. Both are recorded so a reader never
                    # has to guess which one a number counted.
                    "scored":            score is not None,
                }

            if metric:
                metric_details[metric] = {
                    "axis":         axis_name,
                    "current":      current_val,
                    "target":       target_val,
                    "unit":         unit,
                    "direction":    direction,
                    "score":        (round(score, 4) if score is not None else None),
                    "measured":     score is not None,
                    "weight":       weight,
                    "tti_cycles":   tti,
                    # THE WHY BEHIND "measured" (28 Aug 2026, ITEM 7.1c). Until
                    # today this dict said an axis was measured and gave no way
                    # to check the claim. These three name the external reading
                    # the number came from; all three are None when nothing
                    # resolved, and an axis with no observation_key is not
                    # measured whatever its score says.
                    "observation_key":   (origin or {}).get("key"),
                    "observation_where": (origin or {}).get("where"),
                    "source_id":         (origin or {}).get("source_id"),
                }

    # ── ДВАТА ЗНАМЕНАТЕЛЯ (Kimi, 15 август 2026) ────────────────────────────
    # „Да, двойният знаменател е честен." Едното число казва колко добре работят
    # СЕТИВАТА (измереното срещу измеримото). Другото казва колко от ЦЕЛТА изобщо
    # е в обхвата им (измереното срещу всичко). Едното без другото лъже: първото
    # се хвали, второто се самобичува.
    #
    # И защо флаговете са ДВА, а не един: ако единственият флаг се съди срещу целта,
    # той е False по построение — 49 от 173 тегло (167 след 8052397, 2026-08-21)
    # са структурно семантични и няма да
    # получат число нито утре, нито другиден. Сигнал, който не може да мигне, е мъртъв.
    #   Kimi: „Приемам двата флага. Един винаги-False сигнал е мъртъв — sensors_ok
    #          мигне, goal_covered казва истината за структурната дупка."
    coverage_of_goal = round(measured_weight / total_weight, 4) if total_weight > 0 else 0.0
    coverage_of_measurable = (round(measured_weight / measurable_weight, 4)
                              if measurable_weight > 0 else 0.0)
    measured_composite = (round(weighted_sum / measured_weight, 4)
                          if measured_weight > 0 else None)

    # Прагът, под който едно число е лъжа. 0.80 е предложението на Kimi; стои тук
    # като явна константа, за да може да се оспори, а не скрито в израз.
    COVERAGE_MIN = 0.80
    sensors_ok   = coverage_of_measurable >= COVERAGE_MIN
    goal_covered = coverage_of_goal >= COVERAGE_MIN
    unmeasured = sorted(unmeasured_reasons)

    semantic_weight = round(total_weight - measurable_weight, 1)
    for _a, _v in semantic_axes.items():
        _v["share_of_goal"] = round(_v["weight"] / total_weight, 4) if total_weight else 0.0
    unassessed = sorted(a for a, v in semantic_axes.items()
                        if not (v.get("reading") or {}).get("assessed"))

    # ЗА СЪВМЕСТИМОСТ: composite_score остава ЧИСЛО, защото цикълът, Merkle
    # ангажиментът и отчетите го четат — но вече е средно САМО от измереното, а не
    # разредено с константи и без семантичните оси. Дали бива да се чете като
    # истина, казват ДВАТА флага, и то само заедно.
    composite = measured_composite if measured_composite is not None else 0.0

    return {
        "composite_score": composite,
        # ── пакетът, без който числото е тъмна цифра ───────────────────────
        "sensors_ok":   sensors_ok,
        "goal_covered": goal_covered,
        "coverage_of_measurable": coverage_of_measurable,
        "coverage_of_goal":       coverage_of_goal,
        "coverage_min": COVERAGE_MIN,
        # Отпечатък на КОНФИГУРАЦИЯТА. Два композита с различен отпечатък не се
        # сравняват — те са средни от различни множества и разликата им не е
        # разлика в света. (Kimi, 15 авг 2026)
        "config_fingerprint": config_fingerprint(targets),
        "semantic_axes": semantic_axes,
        "semantic_weight": semantic_weight,
        "semantic_share_of_goal": (round(semantic_weight / total_weight, 4)
                                   if total_weight else 0.0),
        "semantic_unassessed": unassessed,
        # ── съвместимост със стария договор ────────────────────────────────
        # composite_valid остава, но вече е ЯВНО срещу целта, както отсъди Kimi:
        # „Прагът composite_valid се съди срещу целта (58%), не срещу измеримото
        #  (81%). Иначе плащаш пране на незнание."
        "composite_valid": goal_covered,
        "coverage": coverage_of_goal,
        "measured_weight":   round(measured_weight, 1),
        "measurable_weight": round(measurable_weight, 1),
        "unmeasured_axes": unmeasured,
        "unmeasured_reasons": unmeasured_reasons,
        "unmeasured_weight": round(measurable_weight - measured_weight, 1),
        "insufficient_data": (None if goal_covered else
                              f"покритие спрямо целта {coverage_of_goal:.0%} < "
                              f"{COVERAGE_MIN:.0%}. От тях {semantic_weight:.0f} тегло "
                              f"({(semantic_weight / total_weight if total_weight else 0):.0%}) "
                              f"е СТРУКТУРНО семантично — {len(unassessed)} от "
                              f"{len(semantic_axes)} такива оси нямат дори оценка. "
                              f"Останалите {len(unmeasured)} измерими оси днес нямат "
                              f"число: {', '.join(unmeasured[:4])}"
                              f"{'...' if len(unmeasured) > 4 else ''}."),
        "axis_scores":     axis_scores,
        "metric_details":  metric_details,
        "axis_observations": axis_observations,
        "total_weight":    total_weight,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
    }


# ── standalone run ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    result = compute_goal_score()

    print("\n" + "=" * 78)
    print("  " + format_headline(result))
    print("=" * 78)
    if not result["goal_covered"]:
        print("  " + str(result["insufficient_data"]))

    print("\n--- SEMANTIC COLUMN (assessed, not counted) ---")
    for _a, _v in result["semantic_axes"].items():
        _r = _v["reading"]
        _state = (f"{_r.get('direction')} / доверие {_r.get('confidence')}"
                  if _r.get("assessed") else "БЕЗ ОЦЕНКА")
        print(f"  {_a:<40} w={_v['weight']:>2.0f} ({_v['share_of_goal']:.1%} от целта)  {_state}")

    print("\n--- PER-AXIS SCORES (weight / score) ---")
    targets = load_targets()
    for domain_key, axes in targets.items():
        if domain_key.startswith("_"):
            continue
        print(f"\n  [{domain_key}]")
        for axis_name, cfg in axes.items():
            # ── ГЪРМЕЖЪТ (15 август 2026) ────────────────────────────────────
            # Тук стоеше `result["axis_scores"].get(axis_name, 0.5)` и после
            # `int(score * 20)`. Щом липсата стана None вместо 0.5, тази лента
            # УМИРАШЕ на първата неизмерена ос — TypeError: None * int — и
            # командата, с която ЧОВЕКЪТ гледа състоянието, спираше по средата на
            # PLANET. Библиотечният път беше здрав; счупен беше точно прозорецът.
            # И по-подлото: default-ът 0.5 щеше да покаже липсващата ос като
            # „наполовина добре" — същата константа, която махнахме от сметката,
            # оцеляла в картинката.
            score  = result["axis_scores"].get(axis_name)
            weight = cfg.get("weight", 1)
            if score is None:
                why = ((result.get("semantic_axes") or {}).get(axis_name, {})
                       .get("why_not_numeric")
                       or (result.get("unmeasured_reasons") or {})
                       .get(axis_name, {}).get("why") or "без число")
                print(f"    {axis_name:<40} w={weight:2}  [{'-' * 20}]  "
                      f"  —   {str(why).split(':')[0]}")
                continue
            filled = int(score * 20)
            bar    = "#" * filled + "." * (20 - filled)
            print(f"    {axis_name:<40} w={weight:2}  [{bar}]  {score:.3f}")

    print("\n--- METRICS WITH REAL DATA ---")
    for metric, detail in sorted(result["metric_details"].items()):
        if detail["current"] is None:
            continue
        tti_str = f"  TTI={detail['tti_cycles']} cycles" if detail["tti_cycles"] else ""
        # СТОЙНОСТ БЕЗ ОЦЕНКА Е ВЪЗМОЖНА: stable_better осите имат живо число, но
        # нямат праг, спрямо който то да значи нещо. Печатаме числото и казваме,
        # че оценка няма — вместо да гръмнем или, по-лошо, да измислим 0.5.
        sc = detail["score"]
        sc_str = f"{sc:.3f}" if isinstance(sc, (int, float)) else "  —  (без праг)"
        print(
            f"  {metric:<42} "
            f"current={detail['current']:>12.2f} {detail['unit']:<20} "
            f"target={str(detail['target']):<10} "
            f"score={sc_str}{tti_str}"
        )

    # Заглавието твърдеше „score=0.50" — константата, която махнахме от сметката,
    # още се рекламираше в прозореца. Сега казва какво наистина има: нищо.
    print("\n--- AXES WITH A DECLARED METRIC BUT NO VALUE TODAY ---")
    for metric, detail in sorted(result["metric_details"].items()):
        if detail["current"] is not None:
            continue
        why = ((result.get("unmeasured_reasons") or {}).get(detail["axis"], {}).get("why")
               or (result.get("semantic_axes") or {}).get(detail["axis"], {})
               .get("why_not_numeric") or "без число")
        print(f"  {detail['axis']:<45} {str(why)[:90]}")
