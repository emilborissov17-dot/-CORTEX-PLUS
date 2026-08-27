"""Nothing in the stylesheet can out-specify being hidden.

THE CLOSE BUG, GENERALISED. #runwrap{display:flex} is an ID selector at (1,0,0).
The `hidden` attribute is only ever the user-agent rule [hidden]{display:none}
at (0,1,0). The author rule won, so setting .hidden flipped a property and moved
nothing on screen — and the test that guarded it asserted `wrap.hidden === true`
and passed for as long as the bug existed.

A DOM harness cannot catch this: it has no CSS engine. A renderer can, but only
for the states a sweep happens to visit. This check is neither — it reads the
stylesheet and compares specificity, which is the thing that actually decided
the outcome, for every element the page hides whether a sweep visits it or not.

NARROW ON PURPOSE. An earlier draft compared the UA rule against every element
that merely HAS a display rule and flagged eight — .spd.on, .tl .src, .bar>i,
.cols.dim — none of which the page ever hides. A check that cries wolf eight
times is a check somebody switches off, so this one only considers elements that
are really hidden: by the `hidden` attribute, or by a class some rule hides.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "test"))

import cockpit_surface as cs  # noqa: E402


def test_the_page_hides_things_at_all():
    """Guard on the guard: if nothing is detected as hidden, this file is inert
    and would pass no matter how broken the stylesheet became."""
    hidden = cs.hidden_elements()
    assert hidden, (
        "no hidden element detected — either the page stopped hiding anything, "
        "or the detector broke and every assertion below is now vacuous")
    assert "#runwrap" in hidden, (
        "the read-only overlay is no longer detected as hidden by attribute")


def test_no_author_rule_outranks_the_rule_that_hides_its_element():
    """THE HEADLINE. This is the check the CLOSE bug needed and did not have."""
    flagged = [f for f in cs.specificity_family() if f["author_wins"]]
    assert flagged == [], "\n".join(
        [""] + [
            f"  {f['element']}: {f['showing_rule']} {f['showing_spec']} "
            f"({f['showing_prop']}) OUTRANKS {f['hiding_rule']} "
            f"{f['hiding_spec']} — the element cannot be hidden"
            for f in flagged
        ] + [
            "",
            "Fix it the way #runwrap was fixed: add a rule that carries the",
            "hiding state in its own selector, so it outranks the one that shows",
            "the element. e.g.  #thing[hidden]{display:none}   at (1,1,0).",
        ])


def test_every_hidden_element_has_a_hider_that_can_win():
    """Stated the other way round, because the failure was an ABSENCE.

    #runwrap had no [hidden] rule at all. Nothing was 'wrong' in the stylesheet
    — something was missing from it, and only the cascade knew.
    """
    for base, mechanisms in cs.hidden_elements().items():
        if base.startswith("("):
            continue                      # inline styles outrank everything
        showers = [(s, p, sp) for s, p, sp in cs.css_rules()
                   if cs._tokens(base) <= cs._tokens(s.split()[-1])
                   and cs.shows(p)]
        if not showers:
            continue                      # nothing competes; the UA rule wins
        top_show = max(sp for _, _, sp in showers)
        hiders = []
        for mech in mechanisms:
            sel = base + mech if mech.startswith("[") else mech
            hiders += [sp for s, p, sp in cs.css_rules()
                       if s == sel and cs.hides(p)]
        assert hiders, (
            f"{base} is hidden by {mechanisms} but the stylesheet has no rule "
            f"that hides it — it relies on the user-agent rule at (0,1,0), "
            f"which loses to {top_show}")
        assert max(hiders) > top_show


# ── 1.3 the negative control ────────────────────────────────────────────────

def _with_stylesheet(monkeypatch, extra_css: str, extra_script: str) -> None:
    """Point cockpit_surface at a stylesheet of our own, for one test."""
    monkeypatch.setattr(cs, "CSS", cs.CSS + extra_css)
    monkeypatch.setattr(cs, "SCRIPT", cs.SCRIPT + extra_script)


def test_the_check_goes_red_on_a_deliberately_outranking_rule(monkeypatch):
    """NEGATIVE CONTROL. A rule that out-specifies hiding MUST be caught.

    Without this, a green result means nothing: the check could be passing
    because it looks at the wrong thing, which is exactly what the old
    `wrap.hidden === true` assertion did.
    """
    _with_stylesheet(
        monkeypatch,
        extra_css="\n  #trapdoor{display:flex}\n",
        extra_script="\nconst tr = $('#trapdoor'); tr.hidden = true;\n")

    hidden = cs.hidden_elements()
    assert "#trapdoor" in hidden, (
        "the detector did not even notice the trap element being hidden")

    flagged = [f for f in cs.specificity_family() if f["author_wins"]]
    names = {f["element"] for f in flagged}
    assert "#trapdoor" in names, (
        "a rule deliberately built with the CLOSE bug's exact shape — an ID "
        "setting display, hidden only by the UA [hidden] rule — was NOT "
        "flagged. The check cannot see the defect it exists for.")


def test_the_same_element_passes_once_it_is_fixed(monkeypatch):
    """And the negative control must go green again for the RIGHT reason."""
    _with_stylesheet(
        monkeypatch,
        extra_css="\n  #trapdoor[hidden]{display:none}\n  #trapdoor{display:flex}\n",
        extra_script="\nconst tr = $('#trapdoor'); tr.hidden = true;\n")

    flagged = [f["element"] for f in cs.specificity_family() if f["author_wins"]]
    assert "#trapdoor" not in flagged, (
        "adding the (1,1,0) hiding rule did not clear the flag, so the check "
        "cannot tell a fixed element from a broken one")


def test_opacity_and_visibility_count_too(monkeypatch):
    """display is not the only way to be visibly there."""
    _with_stylesheet(
        monkeypatch,
        extra_css="\n  .ghost{opacity:0}\n  .ghost.lit{opacity:1}\n",
        extra_script="\n  el.classList.add('ghost');\n")
    fam = cs.specificity_family()
    ghosts = [f for f in fam if f["element"] == ".ghost"]
    assert ghosts, "an opacity-hidden class was not considered at all"
    assert any(f["author_wins"] for f in ghosts), (
        ".ghost.lit{opacity:1} at (0,2,0) outranks .ghost{opacity:0} at "
        "(0,1,0) and was not flagged")
