"""A control that no renderer has seen cannot ship.

The sweep in test_cockpit_render_sweep.py was GREEN on its first full run — 57
passed — while exercising 8 of the cockpit's 24 controls. Green because it was
not looking, which is the same failure as a test asserting the wrong property:
a result that means nothing and reads like assurance.

So the inventory is the authority, and it is PARSED (test/cockpit_surface.py),
never listed. Every control it finds must be named by an assertion in the sweep.
Add a control to the page and this file goes red naming it, before anyone can
discover it is dead by clicking it.

This check needs no browser: it compares two files. It runs everywhere, so the
coverage rule holds even on a machine where the sweep itself skips.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "test"))

import cockpit_surface as cs  # noqa: E402

SWEEP = REPO / "test" / "test_cockpit_render_sweep.py"
SWEEP_SRC = SWEEP.read_text(encoding="utf-8")


def covered() -> set:
    """Every control the sweep names, from its own source.

    Names are taken from the CONTROLS table's keys and from any selector the
    file mentions, so a control asserted by hand in a bespoke test counts too.
    """
    names = set(re.findall(r'^\s{4}"([\w-]+)":', SWEEP_SRC, re.M))
    for sel in re.findall(r"""["'](#[\w-]+|\.[\w-]+)["']""", SWEEP_SRC):
        names.add(sel.lstrip("#."))
    return names


def test_every_control_in_the_inventory_is_exercised_by_the_sweep():
    """THE RULE. A control nobody has clicked in a renderer is not shipped."""
    have = covered()
    missing = [f"{kind}:{name} ({where})"
               for kind, name, where in cs.controls()
               if name not in have]
    assert not missing, (
        "these controls exist in the page and NO sweep assertion touches "
        "them:\n  " + "\n  ".join(missing) +
        "\n\nAdd each to CONTROLS in test_cockpit_render_sweep.py. A control "
        "that no renderer has seen cannot be said to work.")


def test_the_inventory_is_not_empty():
    """Guard on the guard: an inventory that finds nothing passes everything."""
    controls = cs.controls()
    assert len(controls) >= 20, (
        f"the parsed inventory found only {len(controls)} controls; the parser "
        f"is probably broken and this file is now vacuous")
    assert cs.tabs(), "no tabs parsed"
    assert cs.routes(), "no routes parsed"


def test_every_tab_is_exercised():
    missing = [t for t in cs.tabs() if t not in SWEEP_SRC]
    assert not missing, f"tabs no sweep assertion visits: {missing}"


def test_every_get_route_is_exercised():
    """The routes are parametrised from the inventory, so this asserts the
    parametrisation is actually wired to it rather than to a copied list."""
    assert "cs.routes()" in SWEEP_SRC, (
        "the sweep no longer derives its routes from the parsed inventory; a "
        "hand-copied list goes stale the first time a route is added")


def test_the_sweep_says_out_loud_when_no_renderer_is_available():
    """4.2. A sweep that passes for lack of a browser is worse than no sweep.

    This test ALWAYS runs — it needs no browser — so on a machine with no Chrome
    the suite still carries one visible line saying the renderer sweep did not
    run, and why. A skip alone is invisible in a plain `pytest -q`.
    """
    import warnings

    import cdp
    reason = cdp.why_unavailable()

    src = SWEEP.read_text(encoding="utf-8")
    assert "why_unavailable()" in src and "skipif" in src, (
        "the sweep no longer guards on renderer availability; on a machine "
        "without Chrome it would either error or, worse, quietly pass")
    assert "RENDER SWEEP SKIPPED" in src, (
        "the skip reason does not name itself, so a skipped sweep reads like "
        "any other skipped test")

    if reason is not None:
        warnings.warn(
            "RENDER SWEEP DID NOT RUN ON THIS MACHINE: " + reason
            + " — every control assertion in test_cockpit_render_sweep.py was "
              "skipped. The cockpit has NOT been judged by a renderer here.",
            stacklevel=1)


def test_the_sweep_never_accepts_an_in_memory_property_as_evidence():
    """THE RULE THAT MADE ALL OF THIS NECESSARY.

    `wrap.hidden === true` was true while the panel was 742px wide. If the sweep
    starts reading properties it becomes the test it replaced.
    """
    body = re.sub(r'"""[\s\S]*?"""', "", SWEEP_SRC)      # drop docstrings
    body = re.sub(r"#[^\n]*", "", body)                  # drop comments
    offenders = []
    for m in re.finditer(r"return\s+[^;\n]*\.(hidden|checked)\b", body):
        line = body[:m.start()].count("\n") + 1
        if "negative_control" in body[max(0, m.start() - 2000):m.start()]:
            continue          # the trap deliberately reads the property
        offenders.append(f"line {line}: {m.group(0).strip()}")
    assert not offenders, (
        "the sweep reads an in-memory property as evidence:\n  "
        + "\n  ".join(offenders))
