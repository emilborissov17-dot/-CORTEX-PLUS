"""A fallback that keeps the cycle running must say what it lost.

core/provenance.py needs normalize_upstream from core/catalog.py to give every
source ONE canonical upstream key. The import has always been wrapped:

    try:
        from core.catalog import normalize_upstream
    except Exception:
        def normalize_upstream(x): return x or "НЕРАЗПОЗНАТ"

The stub is correct — a missing catalog should not kill the night. What was wrong
is that it was SILENT. With the catalog gone, every section's upstream_key becomes
НЕРАЗПОЗНАТ, all sources collapse into one bucket, and the report comes out
looking complete: the concentration figures would read as a finding about the
world rather than as a missing file. Until 17 Sep 2026 the module was not even in
git, so the loss was one reset away and nothing would have announced it.

WHAT IS ASSERTED HERE. Not that the fallback exists — that it is AUDIBLE, and
that it names core/catalog.py rather than logging something generic a reader
cannot act on. And, in the other direction, that a healthy import stays quiet: a
degradation event that fires when nothing is wrong teaches people to ignore it.

These are behaviour tests, not prose checks: each drives build() and reads what
was recorded.
"""
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import provenance as P    # noqa: E402


SNAPSHOT = {
    "timestamp": "2026-09-17T00:00:00+00:00",
    "co2": {"co2_ppm": 426.08, "observed": "2026-09-16"},
    "waste": {"adjusted_net_savings_pct": 9.6359},
}


@pytest.fixture
def recorded(monkeypatch):
    """Capture core.blackbox.record without writing to memory/blackbox.jsonl."""
    calls = []

    import core.blackbox as bb
    monkeypatch.setattr(bb, "record",
                        lambda step, phase="mark", **extra:
                        calls.append({"step": step, "phase": phase, **extra}))
    return calls


@pytest.fixture
def catalog_gone(monkeypatch):
    """Make `from core.catalog import ...` raise, the way a deleted file does.

    A None in sys.modules is what the import machinery treats as a known-absent
    module, so this reproduces the real failure rather than simulating it.
    """
    monkeypatch.setitem(sys.modules, "core.catalog", None)


def test_the_missing_catalog_is_recorded_by_name(catalog_gone, recorded):
    P.build(json.loads(json.dumps(SNAPSHOT)))

    degraded = [c for c in recorded if c.get("phase") == "degraded"]
    assert degraded, "core/catalog.py went missing and nothing was recorded"
    assert any(c.get("missing_module") == "core/catalog.py" for c in degraded), \
        f"the event does not name the missing module: {degraded}"


def test_the_event_says_what_the_loss_costs(catalog_gone, recorded):
    """A reader of the ledger must learn the consequence, not only the cause —
    the numbers in the same report are affected and that is the actionable part."""
    P.build(json.loads(json.dumps(SNAPSHOT)))
    ev = [c for c in recorded if c.get("phase") == "degraded"][0]
    assert ev.get("missing_symbol") == "normalize_upstream"
    assert "НЕРАЗПОЗНАТ" in str(ev.get("effect", "")), \
        "the event does not say that every upstream_key degrades"


def test_the_fallback_still_works(catalog_gone, recorded):
    """Loud is not the same as fatal. The cycle keeps its provenance report."""
    doc = P.build(json.loads(json.dumps(SNAPSHOT)))
    assert "error" not in doc, f"build() failed instead of degrading: {doc}"
    assert doc, "build() returned nothing with the catalog missing"


def test_a_healthy_import_records_nothing(recorded):
    """The other half of the guard. core/catalog.py is present in this repo, so a
    degraded event here would be a false alarm — and an alarm that cries wolf is
    worse than none, because the real one gets skipped."""
    import core.catalog  # noqa: F401  — fail loudly here if it is genuinely gone

    P.build(json.loads(json.dumps(SNAPSHOT)))
    assert [c for c in recorded if c.get("phase") == "degraded"] == [], \
        "a degraded event fired while core/catalog.py imports fine"


def test_a_broken_blackbox_does_not_take_the_cycle_down(catalog_gone, monkeypatch, capsys):
    """The logger is not more important than the run. If recording the loss fails
    too, that is printed and swallowed."""
    import core.blackbox as bb

    def explode(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(bb, "record", explode)

    doc = P.build(json.loads(json.dumps(SNAPSHOT)))
    assert "error" not in doc
    out = capsys.readouterr().out
    assert "blackbox could not record" in out, \
        "the failure to record was swallowed without a word"


def test_the_stdout_line_names_the_module_too(catalog_gone, recorded, capsys):
    """blackbox.jsonl is queried later; the cycle log is read tonight. Both must
    carry the name, because whoever is looking will only have one of them open."""
    P.build(json.loads(json.dumps(SNAPSHOT)))
    assert "core/catalog.py" in capsys.readouterr().out
