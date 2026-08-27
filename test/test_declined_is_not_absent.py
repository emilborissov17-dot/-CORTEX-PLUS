"""A refusal is not an absence, and a cooldown says when it ends.

On 27 Aug the MIC ON toggle was green, the microphone was working — measured,
rms 1.4e-05 — and the panel said NOT AVAILABLE, because acoustic() had sampled
four seconds earlier and CAPTURE_COOLDOWN_SEC is 10. Both statements were true
and together they read as a lie. COMMAND 30 split DECLINED from NOT AVAILABLE.

This finishes it. DECLINED still left the reader with no way to know whether to
wait one second or a minute, so the next thing they did was refresh the page —
which is the exact behaviour the cooldown exists to prevent. A refusal that
knows when it ends now says so.

Both states are tested, and so is the third: a refusal that CANNOT name its end
— a cycle is running — must keep the bare word rather than invent a promise.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cockpit import somatic as so   # noqa: E402

PAGE = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(encoding="utf-8")


# -- the three states, at the source --------------------------------------

def test_a_cooldown_refusal_carries_its_seconds(monkeypatch):
    monkeypatch.setattr(so, "cycle_is_live", lambda: False)
    monkeypatch.setattr(so, "_cooldown_block", lambda kind, now=None: 6.4)
    rows = so.acoustic(enabled=True)

    r = rows[0].as_dict()
    assert r["available"] is False
    assert r["declined"] is True
    assert r["declined_kind"] == "cooldown"
    assert r["cooldown_sec_left"] == 6.4, (
        "the row knows it was refused but not for how long, so the reader's "
        "only move is to refresh — the thing the cooldown exists to stop")


def test_a_sensor_this_machine_does_not_have_is_absent_not_declined(monkeypatch):
    """The other half. A missing device must not borrow the cooldown's wording."""
    monkeypatch.setattr(so, "cycle_is_live", lambda: False)
    monkeypatch.setattr(so, "_cooldown_block", lambda kind, now=None: None)
    monkeypatch.setattr(so, "mic_rms_once",
                        lambda: (None, "no input device on this machine"))
    r = so.acoustic(enabled=True)[0].as_dict()

    assert r["available"] is False
    assert r["declined"] is False, (
        "a machine with no microphone was reported as having declined to use "
        "one")
    assert r["declined_kind"] == ""
    assert r["cooldown_sec_left"] is None


def test_a_refusal_that_cannot_name_its_end_promises_nothing(monkeypatch):
    """A cycle is running. That ends when the cycle does, and this module
    cannot put a number on it."""
    monkeypatch.setattr(so, "cycle_is_live", lambda: True)
    r = so.acoustic(enabled=True)[0].as_dict()

    assert r["declined"] is True
    assert r["declined_kind"] == "refused"
    assert r["cooldown_sec_left"] is None, (
        "a countdown was invented for a refusal with no known end")


def test_the_camera_says_the_same_thing(monkeypatch):
    monkeypatch.setattr(so, "cycle_is_live", lambda: False)
    monkeypatch.setattr(so, "_cooldown_block", lambda kind, now=None: 2.2)
    rows = [r.as_dict() for r in so.optic(enabled=True)]
    assert rows, "the camera returned no rows at all"
    for r in rows:
        assert r["declined_kind"] == "cooldown"
        assert r["cooldown_sec_left"] == 2.2


def test_a_disabled_device_is_neither(monkeypatch):
    """OFF is a third thing again: nobody asked, so nothing was refused."""
    r = so.acoustic(enabled=False)[0].as_dict()
    assert r["disabled"] is True
    assert r["declined"] is False
    assert r["cooldown_sec_left"] is None


# -- the page prints the difference ---------------------------------------

def _cells() -> str:
    i = PAGE.index("if(r.disabled)")
    return PAGE[i:PAGE.index("const tag", i)]


def test_the_row_shows_the_countdown_rather_than_hiding_it_in_a_tooltip():
    cells = _cells()
    assert "cooldown, next sample in" in cells, (
        "the seconds are not on the row")
    assert "cooldown_sec_left" in cells
    i = cells.index("cooldown, next sample in")
    j = cells.index("title=", max(0, i - 200))
    assert j < i, "the countdown is inside the title attribute, not the cell"


def test_the_three_states_are_three_branches_in_the_right_order():
    """A cooldown row also satisfies `declined`, so the specific branch has to
    come first or the general one swallows it."""
    cells = _cells()
    order = [cells.index(x) for x in (
        "r.disabled",
        "r.declined && r.cooldown_sec_left != null",
        "else if(r.declined)",
        "else if(!r.available)")]
    assert order == sorted(order), (
        "the branches are ordered so that a cooldown never reaches its own "
        "case: %s" % order)


def test_an_absent_sensor_still_says_not_available():
    assert "NOT AVAILABLE" in _cells()


def test_the_seconds_are_rounded_up_not_down():
    """0.4s left must not print as 'in 0s', which reads as 'now'."""
    assert "Math.ceil(r.cooldown_sec_left)" in _cells()


# -- the contract holds together ------------------------------------------

def test_the_api_exposes_both_new_fields():
    src = (REPO / "cockpit" / "somatic.py").read_text(encoding="utf-8-sig")
    i = src.index("def as_dict")
    body = src[i:i + 1200]
    for field in ('"declined_kind"', '"cooldown_sec_left"'):
        assert field in body, "as_dict does not publish %s" % field


def test_declined_kind_is_derived_and_not_stored():
    """One source of truth. A stored word can disagree with the seconds."""
    src = (REPO / "cockpit" / "somatic.py").read_text(encoding="utf-8-sig")
    i = src.index("def declined_kind")
    assert "@property" in src[max(0, i - 60):i]


def test_every_cooldown_site_passes_the_seconds():
    """ast-free but exact: each _cooldown_block guard must feed _na."""
    src = (REPO / "cockpit" / "somatic.py").read_text(encoding="utf-8-sig")
    guards = [m.start() for m in re.finditer(r"left = _cooldown_block\(", src)]
    assert len(guards) >= 2, "the cooldown guards moved"
    for g in guards:
        block = src[g:g + 700]
        assert "cooldown_left=" in block, (
            "a cooldown refusal at offset %d does not carry its seconds, so "
            "that row will say DECLINED with no end in sight" % g)
