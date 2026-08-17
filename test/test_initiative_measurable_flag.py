"""A field that can only ever be false is not a field.

THE DEFECT (measured 17 Aug 2026)
----------------------------------
`initiative_tracker._update_progress_for_active` writes `measurable` in exactly
one place — the FAILURE branch:

    else:
        rec.setdefault("measurable",      False)
        rec.setdefault("progress_reason", ...)

The success branch, twelve lines above it, sets baseline_value, current_value,
delta, current_progress, measured_at and updated_at — and never touches the flag.
So every one of the 89 initiative records on disk read `measurable: false`, while
53 of them carried a live baseline, a current reading and a computed progress
percentage. Anything filtering `measurable == true` — a report, a dashboard, a
future scorer — saw an empty set and had no way to know it was wrong, because
the field existed and had a plausible value.

That is worse than a missing field. A missing field is obviously missing.

THE POSITIVE CONTROL IS THE WHOLE TEST
---------------------------------------
"a measured initiative says measurable:true" is satisfied perfectly by
`rec["measurable"] = True` written unconditionally, which would be the same bug
with the sign flipped and 36 records newly lying. So the file below always
asserts BOTH directions over the same run, and
test_the_flag_is_not_simply_always_true is the one that fails if the fix is lazy.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import initiative_tracker as it


# A milestone whose text matches _METRIC_MAP ("бедност" -> world_bank.poverty_190_pct)
MEASURABLE = {
    "id": "init_measurable",
    "status": "PROPOSED",
    "problem": "Растяща бедност в региона",
    "solution": "Програма за подпомагане",
    "milestone": "Намаляване на бедността с 25%",
    "created_at": "2026-07-01T00:00:00+00:00",
}
# Nothing in _METRIC_MAP matches this text, so it cannot be measured.
UNMEASURABLE = {
    "id": "init_unmeasurable",
    "status": "PROPOSED",
    "problem": "Философска неяснота в дефиницията на смисъл",
    "solution": "Разсъждение",
    "milestone": "По-добро разбиране",
    "created_at": "2026-07-01T00:00:00+00:00",
}
INDICATORS = {"world_bank": {"poverty_190_pct": 12.5}}


@pytest.fixture
def initiatives(tmp_path, monkeypatch):
    d = tmp_path / "initiatives"
    d.mkdir()
    for rec in (MEASURABLE, UNMEASURABLE):
        (d / f"{rec['id']}.json").write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(it, "INITIATIVES_DIR", d)
    return d


def _read(d: Path, name: str) -> dict:
    return json.loads((d / f"{name}.json").read_text(encoding="utf-8"))


def test_a_measured_initiative_says_measurable_true(initiatives):
    """The defect, directly."""
    it._update_progress_for_active(INDICATORS)
    rec = _read(initiatives, "init_measurable")

    assert rec.get("current_value") == 12.5, \
        "the fixture stopped being measurable; this test proves nothing now"
    assert rec.get("measurable") is True, (
        f"the record carries baseline={rec.get('baseline_value')} "
        f"current={rec.get('current_value')} measured_at={rec.get('measured_at')} "
        f"and still says measurable={rec.get('measurable')!r} — this is the bug "
        f"that made all 89 records on disk claim they could not be measured")


def test_the_flag_is_not_simply_always_true(initiatives):
    """POSITIVE CONTROL.

    `rec["measurable"] = True` written unconditionally passes the test above and
    is the same defect mirrored: 36 of the 89 genuinely have no matching
    indicator, and a flag that claims otherwise is exactly as useless as one that
    could only be false.
    """
    it._update_progress_for_active(INDICATORS)
    rec = _read(initiatives, "init_unmeasurable")

    assert rec.get("measurable") is False, (
        f"an initiative with no matching indicator was marked "
        f"measurable={rec.get('measurable')!r}")
    assert rec.get("progress_reason"), \
        "an unmeasurable initiative must say WHY it could not be measured"
    assert "current_value" not in rec, \
        "an unmeasurable initiative must not carry a measurement"


def test_the_flag_agrees_with_whether_a_measurement_exists(initiatives):
    """The invariant, over both records in one run.

    This is the property the field was supposed to have all along: `measurable`
    is true exactly when there is a measurement to show. Asserted across the set
    so neither constant — always-true or always-false — can satisfy it.
    """
    it._update_progress_for_active(INDICATORS)

    seen = {}
    for f in sorted(initiatives.glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        seen[rec["id"]] = (rec.get("measurable"), "current_value" in rec)

    assert seen == {"init_measurable": (True, True),
                    "init_unmeasurable": (False, False)}, seen
    assert len({v[0] for v in seen.values()}) == 2, \
        "the flag took the same value for both cases — it is still a constant"


def test_a_rerun_does_not_flip_the_flag_back(initiatives):
    """Idempotence. The success branch runs every cycle; the flag must hold.

    `setdefault` in the failure branch cannot un-set a True written by the
    success branch, but the two branches touch the same key and that is worth
    pinning rather than assuming.
    """
    it._update_progress_for_active(INDICATORS)
    it._update_progress_for_active(INDICATORS)
    assert _read(initiatives, "init_measurable").get("measurable") is True
    assert _read(initiatives, "init_unmeasurable").get("measurable") is False
