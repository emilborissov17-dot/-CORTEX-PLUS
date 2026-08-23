#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_stream.py — THE RAW STREAM, AND ITS SILENCE.

Two things matter here and the second is the unusual one:

  * zero new sensor probes with the panel open — the same measurement GLASS
    already passes;
  * an empty panel says WHY it is empty. "The body registered nothing" and
    "the panel is broken" are different statements, and a panel that cannot
    tell them apart gets ignored the first time it is wrong.

Assertions about code parse it. Never grep.

    venv/Scripts/python.exe -m pytest test/test_stream.py -v
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cockpit import stream as st        # noqa: E402
from core import event_bus as eb        # noqa: E402
from core import receptors as rc        # noqa: E402


@pytest.fixture
def rig(tmp_path):
    bus = eb.EventBus()
    tap = st.StreamTap(bus=bus, maxlen=20, name="test")
    bank = rc.ReceptorBank(bus=bus, seed_path=tmp_path / "s.json")
    return tap, bank


def _live(bank, key="ram_percent", eps=1.0, ticks=3, unit="%"):
    r = bank.add_receptor(key, 0.2, eps, calibration_ticks=ticks, unit=unit)
    for _ in range(ticks):
        r.feed(80.0)
    return r


# ═══ ZERO NEW PROBES ════════════════════════════════════════════════════════

def test_rendering_the_panel_adds_no_sensor_probes(rig):
    tap, bank = rig
    _live(bank)
    eb.reset_probe_count()
    for _ in range(60):
        tap.state(bank)
    assert eb.probe_count() == 0, eb.PROBES


def test_the_module_never_touches_a_probe():
    """Parsed. A subscriber module that imports a probe is one edit from
    calling it."""
    tree = ast.parse((REPO / "cockpit" / "stream.py").read_text(
        encoding="utf-8"))
    touched = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    touched |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for probe in ("probe", "read_ram_free_mb", "read_disk_free_pct",
                  "net_io_counters", "virtual_memory"):
        assert probe not in touched, probe


def test_the_endpoint_is_a_subscriber_not_a_prober():
    tree = ast.parse((REPO / "cockpit" / "server.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "api_stream")
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "probe" not in called
    assert "tap" in called or "state" in called


# ═══ THE SILENCE EXPLAINS ITSELF ════════════════════════════════════════════

def test_no_receptors_is_said_not_shown_as_an_empty_box(rig):
    tap, bank = rig
    s = tap.silence(bank)
    assert s["state"] == st.NO_RECEPTORS
    assert s["text"] == "NO RECEPTORS YET"
    assert s["detail"]


def test_warmup_says_how_many_ticks_remain(rig):
    tap, bank = rig
    r = bank.add_receptor("ram_percent", 0.2, 1.0, calibration_ticks=10)
    r.feed(80.0)
    s = tap.silence(bank)
    assert s["state"] == st.WARMUP
    assert "ticks remaining" in s["text"]
    assert "9" in s["text"], s["text"]
    assert "suppressing on purpose" in s["detail"]


def test_quiet_says_it_is_adapted_and_nothing_crossed(rig):
    tap, bank = rig
    _live(bank)
    s = tap.silence(bank)
    assert s["state"] == st.QUIET
    assert s["text"] == "QUIET (adapted, nothing crossed)"
    assert "noise floor" in s["detail"]


def test_the_three_silences_are_distinguishable(rig):
    tap, bank = rig
    assert tap.silence(bank)["state"] == st.NO_RECEPTORS
    r = bank.add_receptor("k", 0.2, 1.0, calibration_ticks=5)
    r.feed(1.0)
    assert tap.silence(bank)["state"] == st.WARMUP
    for _ in range(5):
        r.feed(1.0)
    assert tap.silence(bank)["state"] == st.QUIET
    assert len({st.NO_RECEPTORS, st.WARMUP, st.QUIET}) == 3


def test_the_page_draws_the_silence(rig):
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("async function drawStream()", 1)[1][:1400]
    assert "sil.text" in block, "the reason is fetched but never drawn"
    assert "sil.detail" in block


# ── the lines ───────────────────────────────────────────────────────────────

def test_a_crossing_produces_exactly_one_line(rig):
    tap, bank = rig
    r = _live(bank)
    r.feed(95.0)
    s = tap.state(bank)
    assert s["n"] == 1


def test_the_line_carries_everything_the_command_asks_for(rig):
    tap, bank = rig
    r = _live(bank)
    r.feed(95.0)
    line = tap.state(bank)["lines"][0]
    for k in ("ts", "topic", "channel", "value", "base", "crossed"):
        assert line[k] is not None, k
    assert line["topic"] == "receptor.ram_percent"
    assert line["channel"] == "R"
    assert isinstance(line["ts"], float)


def test_the_value_is_not_rounded_for_beauty(rig):
    tap, bank = rig
    r = _live(bank, eps=0.001)
    r.feed(80.123456789)
    line = tap.state(bank)["lines"][-1]
    assert line["value"] == 80.123456789


def test_an_anchor_crossing_names_the_drift(rig):
    tap, bank = rig
    r = bank.add_receptor("d", 0.2, 6.0, calibration_ticks=3)
    for _ in range(3):
        r.feed(100.0)
    v = 100.0
    for _ in range(25):
        v -= 1.0
        r.feed(v)
    lines = [l for l in tap.state(bank)["lines"] if l["why"] == "anchor"]
    assert lines, [l["why"] for l in tap.lines]
    assert "drift" in lines[0]["crossed"]


def test_a_setpoint_crossing_shows_the_levels(rig):
    tap, bank = rig
    sp = bank.add_setpoint("disk_free_pct", {"notice": 28, "action": 15,
                                             "gate": 5}, "%")
    sp.feed(50.0)
    sp.feed(14.0)
    lines = [l for l in tap.state(bank)["lines"] if l["channel"] == "S"]
    assert lines
    assert "->" in lines[-1]["crossed"]
    assert "action" in lines[-1]["crossed"]


def test_the_wildcard_tap_sees_every_topic(rig):
    tap, bank = rig
    a = _live(bank, "ram_percent")
    b = _live(bank, "cpu_percent")
    a.feed(95.0)
    b.feed(95.0)
    topics = {l["topic"] for l in tap.state(bank)["lines"]}
    assert topics == {"receptor.ram_percent", "receptor.cpu_percent"}


def test_the_ring_is_bounded_and_the_drops_are_counted(rig):
    tap, bank = rig
    r = _live(bank, eps=0.001)
    for i in range(200):
        r.feed(1000.0 + i * 100)
    s = tap.state(bank)
    assert s["n"] == 20
    assert s["dropped"] > 0, "a bounded ring that never reports a drop"
    assert s["seen"] >= 20


def test_nothing_is_aggregated_or_summarised(rig):
    """One event in, one line out. No roll-ups."""
    tap, bank = rig
    r = _live(bank, eps=0.001)
    for i in range(5):
        r.feed(100.0 + i * 10)
    assert tap.state(bank)["n"] == 5


# ── the label ───────────────────────────────────────────────────────────────

def test_it_is_labelled_source_hardware_mediation_code(rig):
    tap, bank = rig
    s = tap.state(bank)
    assert s["source"] == "hardware"
    assert s["mediation"] == "code"
    assert s["label"] == "source:hardware, mediation:code"


def test_the_speed_control_offers_both_readings():
    """Slow enough to read a line, or fast enough to become texture."""
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("function streamControls()", 1)[1][:400]
    assert "0.5" in block and "12" in block
    assert "texture" in block


def test_the_panel_is_on_the_glass_tab():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("async function tabGlass()", 1)[1].split(
        "async function render()", 1)[0]
    assert "panel('raw receptor stream'" in block
    assert "streamBody" in block


def test_the_selftest_passes():
    assert st._selftest() == 0
