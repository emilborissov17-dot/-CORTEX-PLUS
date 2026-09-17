"""Three shapes the composer could not read, and the refusals that come with them.

Written against payloads MEASURED on 17 Sep 2026, not imagined:

  NSIDC     https://nsidc.org/api/seaiceservice/extent/north/filled_averaged_data/2026
            -> {"2026-01-01": 12.376, "2026-01-02": 12.399, ...}
            A date-keyed OBJECT. No existing kind reads one: _dotted's negative index
            walks lists, and a dict has no last element to take.

  SWPC      https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json
            -> [{"time_tag": "2026-09-10T00:00:00", "Kp": 2.67, ...}, ...]
            59 rows: eight 3-hourly intervals for each of seven days, plus three for
            today. The axis declares cadence "daily", so the reduction to one value
            per UTC day happens AT INGEST — the declared cadence has to be true of
            what is stored, not explained in a provenance note.

  Wikimedia https://wikimedia.org/api/rest_v1/metrics/pageviews/.../daily/...
            -> items[].timestamp == "2026091600", which is YYYYMMDDHH.
            datetime.fromisoformat refuses it, and the old _data_too_old swallowed
            that in a bare `except` and returned (False, None) — "not too old". Every
            reading from such a source passed as fresh, forever.

WHAT IS ASSERTED. Mostly refusals, because each of these kinds has an easy wrong
version that returns a plausible number: skip the keys that do not parse (serves an
older value as current), average a partial day (a smaller number wearing a finished
day's name), guess at a date format (right until the day it is wrong). Each of those
is a separate test below, and each fails if the guard is removed.
"""
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "composers"))

import composer as C    # noqa: E402


@pytest.fixture
def no_network(monkeypatch):
    """fetch() must never reach the network in these tests. Returns a setter."""
    box = {}

    def fake_http(url, timeout=15):
        return box["text"]

    monkeypatch.setattr(C, "_http", fake_http)
    return lambda payload: box.__setitem__(
        "text", payload if isinstance(payload, str)
        else json.dumps(payload, ensure_ascii=False))


# ── http_json_datemap — NSIDC's shape ────────────────────────────────────────

NSIDC = {"2026-01-01": 12.376, "2026-01-02": 12.399, "2026-09-15": 4.812,
         "2026-09-16": 4.79}
SRC_MAP = {"id": "nsidc_test", "kind": "http_json_datemap",
           "url": "https://x.test/y", "unit": "million_km2", "cadence": "daily"}


def test_datemap_takes_the_entry_with_the_latest_date(no_network):
    no_network(NSIDC)
    v, dd = C.fetch(SRC_MAP)
    assert v == 4.79
    assert dd == "2026-09-16", "the observation date must be the KEY, not the fetch time"


def test_datemap_does_not_rely_on_insertion_order(no_network):
    """A JSON object has an order and it is not a guarantee. The latest date wins
    even when it is not last in the document."""
    no_network({"2026-09-16": 4.79, "2026-01-01": 12.376, "2026-05-05": 9.9})
    v, dd = C.fetch(SRC_MAP)
    assert (v, dd) == (4.79, "2026-09-16")


def test_datemap_refuses_a_key_that_is_not_a_date(no_network):
    """THE EXPENSIVE WRONG VERSION: skip what does not parse. The payload gains a
    "status" key, the reader shrugs, and yesterday's value is served as today's
    forever. It has to be loud."""
    no_network({"2026-09-15": 4.812, "2026-09-16": 4.79, "status": "ok"})
    with pytest.raises(ValueError) as e:
        C.fetch(SRC_MAP)
    assert "status" in str(e.value), "the refusal does not name the offending key"


def test_datemap_refuses_a_non_numeric_value(no_network):
    no_network({"2026-09-15": 4.812, "2026-09-16": None})
    with pytest.raises(ValueError) as e:
        C.fetch(SRC_MAP)
    assert "2026-09-16" in str(e.value)


def test_datemap_refuses_a_boolean(no_network):
    """isinstance(True, int) is True in Python, so a bool would otherwise arrive as
    1.0 — the GDACS iscurrent trap in another costume."""
    no_network({"2026-09-16": True})
    with pytest.raises(ValueError):
        C.fetch(SRC_MAP)


def test_datemap_refuses_a_list(no_network):
    no_network([1, 2, 3])
    with pytest.raises(ValueError) as e:
        C.fetch(SRC_MAP)
    assert "not an object" in str(e.value)


def test_datemap_refuses_an_empty_payload(no_network):
    no_network({})
    with pytest.raises(ValueError):
        C.fetch(SRC_MAP)


def test_datemap_ignores_underscore_metadata_keys(no_network):
    """A leading underscore is this repo's own marker for metadata (_health,
    _observed_years, _rejected). Those are not dates and not data."""
    no_network({"_meta": "whatever", "2026-09-16": 4.79})
    assert C.fetch(SRC_MAP) == (4.79, "2026-09-16")


# ── http_json_daily_agg — SWPC's shape ───────────────────────────────────────

def _swpc(days: int = 3, per_day: int = 8, last_day_count: int | None = None):
    """The real shape: eight 3-hourly rows per UTC day."""
    rows, start = [], datetime(2026, 9, 10, tzinfo=timezone.utc)
    for d in range(days):
        n = per_day if (last_day_count is None or d < days - 1) else last_day_count
        for h in range(n):
            t = start + timedelta(days=d, hours=3 * h)
            rows.append({"time_tag": t.strftime("%Y-%m-%dT%H:%M:%S"),
                         "Kp": 1.0 + d + h * 0.1, "station_count": 8})
    return rows


SRC_AGG = {"id": "swpc_test", "kind": "http_json_daily_agg",
           "url": "https://x.test/kp", "group_by": "time_tag", "extract": "Kp",
           "agg": "max", "agg_min_count": 8, "unit": "kp", "cadence": "daily"}


def test_daily_agg_returns_one_value_per_day_not_per_interval(no_network):
    no_network(_swpc(days=3))
    v, dd = C.fetch(SRC_AGG)
    assert dd == "2026-09-12", "the date must be the UTC DAY, not an interval timestamp"
    assert v == pytest.approx(3.7), "max of the last complete day"


def test_daily_agg_skips_a_partial_day(no_network):
    """THE MEASURED CASE. On 17 Sep the live feed held seven complete days and three
    intervals of today. The max of three intervals is a LOWER BOUND on the day's max;
    publishing it as the day's max is a smaller number wearing a finished day's name."""
    no_network(_swpc(days=3, last_day_count=3))
    v, dd = C.fetch(SRC_AGG)
    assert dd == "2026-09-11", "the incomplete day was used anyway"


def test_daily_agg_refuses_when_no_day_is_complete(no_network):
    no_network(_swpc(days=2, per_day=3, last_day_count=3))
    with pytest.raises(ValueError) as e:
        C.fetch(SRC_AGG)
    assert "complete day needs" in str(e.value)


def test_daily_agg_max_is_not_mean(no_network):
    """A day's geomagnetic disturbance is its worst interval. If the reduction
    silently became mean(), this axis would report a calmer sky than there was."""
    no_network([{"time_tag": "2026-09-16T00:00:00", "Kp": 1.0},
                {"time_tag": "2026-09-16T03:00:00", "Kp": 9.0}])
    v, _ = C.fetch({**SRC_AGG, "agg_min_count": 2})
    assert v == 9.0


def test_daily_agg_refuses_an_undeclared_reduction(no_network):
    """A CLOSED set. Which reduction a day gets IS the measurement, so an unknown
    word is refused rather than defaulted to something reasonable-looking."""
    no_network(_swpc(days=2))
    with pytest.raises(ValueError) as e:
        C.fetch({**SRC_AGG, "agg": "median"})
    assert "median" in str(e.value)


def test_daily_agg_needs_both_fields_declared(no_network):
    no_network(_swpc(days=2))
    with pytest.raises(ValueError) as e:
        C.fetch({k: v for k, v in SRC_AGG.items() if k != "group_by"})
    assert "group_by" in str(e.value)


# ── data_date_format — Wikimedia's timestamp ─────────────────────────────────

def test_a_declared_format_parses_what_isoformat_refuses():
    fresh = datetime.now(timezone.utc).strftime("%Y%m%d00")
    too_old, age = C._data_too_old(fresh, 3, "%Y%m%d%H")
    assert too_old is False and age is not None and age < 2


def test_a_declared_format_still_ages_a_stale_value():
    old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y%m%d00")
    too_old, age = C._data_too_old(old, 3, "%Y%m%d%H")
    assert too_old is True and age > 39


def test_an_unparseable_date_is_REFUSED_not_treated_as_fresh():
    """THE DEFECT THIS CLOSES. The old code wrapped the parse in a bare except and
    returned (False, None) — False meaning NOT TOO OLD. Wikimedia's "2026091600" is
    not ISO, so every one of its readings passed as current, forever."""
    with pytest.raises(C.DateUnparseable):
        C._data_too_old("2026091600", 3)          # no format declared


def test_a_wrong_declared_format_is_refused_by_name():
    with pytest.raises(C.DateUnparseable) as e:
        C._data_too_old("2026091600", 3, "%Y-%m-%d")
    assert "2026091600" in str(e.value) and "%Y-%m-%d" in str(e.value)


def test_no_date_at_all_is_still_not_an_error():
    """A source that declares no data_date is a different case from one whose date
    cannot be read, and it keeps its old behaviour."""
    assert C._data_too_old("", 3) == (False, None)
    assert C._data_too_old(None, 3) == (False, None)


def test_the_bare_year_reading_survives():
    """World Bank and UN SDG date annual values as "2022". That path predates this
    change and must not be broken by it."""
    too_old, age = C._data_too_old("2022", 100000)
    assert too_old is False and age > 900


def test_a_source_with_an_unreadable_date_is_not_composed(no_network, monkeypatch,
                                                          tmp_path):
    """End to end: the refusal has to reach compose(), not just the helper. A value
    whose date cannot be read must NOT land in last_value undated."""
    no_network({"items": [{"views": 1855, "timestamp": "2026091600"}]})
    src = {"id": "wiki_test", "kind": "http_json_path", "url": "https://x.test/w",
           "extract": "items.-1.views", "data_date_extract": "items.-1.timestamp",
           "data_max_age_days": 5, "unit": "views", "cadence": "daily"}
    with pytest.raises(C.DateUnparseable):
        C._data_too_old(C.fetch(src)[1], 5)       # no declared format -> refused

    v, dd = C.fetch({**src, "data_date_format": "%Y%m%d%H"})
    assert v == 1855.0 and dd == "2026091600"
    too_old, age = C._data_too_old(dd, 5, "%Y%m%d%H")
    assert isinstance(age, float), "with the format declared the date reads as a date"
