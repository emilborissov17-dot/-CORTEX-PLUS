#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_glass.py — ZERO NEW PROBES. THAT IS THE ONLY TEST THAT MATTERS.

The command is explicit: "with the tab open, assert the number of sensor probes
per minute is unchanged from with it closed."

So it is a MEASUREMENT, not an inspection. core/event_bus.py counts every
guarded probe; this file takes the count with the tab shut, renders GLASS many
times, and takes it again. The two numbers must be identical.

    venv/Scripts/python.exe -m pytest test/test_glass.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cockpit import glass as gl          # noqa: E402
from core import event_bus as eb         # noqa: E402


# ═══ THE CONSTRAINT ═════════════════════════════════════════════════════════

def test_rendering_the_tab_adds_no_sensor_probes():
    """THE HEADLINE. Shut, then open, then compare."""
    eb.reset_probe_count()
    shut = eb.probe_count()

    for _ in range(60):                  # a minute of polling at 1 Hz
        gl.render()

    assert eb.probe_count() == shut == 0, eb.PROBES


def test_it_is_not_merely_that_the_counter_is_broken():
    """A test that can only pass is not a test. The counter must move when a
    real probe happens."""
    from core import homeostasis as h
    eb.reset_probe_count()
    gl.render()
    assert eb.probe_count() == 0
    h.read_ram_free_mb()
    assert eb.probe_count() == 1
    assert eb.probe_count("ram_free") == 1


def test_each_panel_individually_probes_nothing():
    eb.reset_probe_count()
    gl.stdout_tail()
    assert eb.probe_count() == 0, "panel 1 probed"
    gl.blocked_connections()
    assert eb.probe_count() == 0, "panel 2 probed"
    gl.traffic({"net_sent_mb": 1.0})
    assert eb.probe_count() == 0, "panel 3 probed"


def _names_touched(path, func=None):
    """Every attribute and name the CODE references, via AST.

    Text matching is wrong here and the first version of this test proved it:
    it flagged glass.py for the sentence in its own docstring explaining that
    it does NOT call net_io_counters. A comment saying "we never do X" is the
    opposite of doing X, and a checker that cannot tell them apart is a
    checker that gets switched off.
    """
    import ast
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    if func:
        tree = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == func)
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.alias):
            out.add(n.name.split(".")[-1])
            if n.asname:
                out.add(n.asname)
    return out


def test_the_module_never_imports_a_probe():
    """The static half: a module that imports a probe is one edit from calling
    it, and today's fixtures would not catch that."""
    touched = _names_touched(REPO / "cockpit" / "glass.py")
    for probe in ("probe", "read_ram_free_mb", "read_disk_free_pct",
                  "net_io_counters", "somatic"):
        assert probe not in touched, probe


def test_the_ast_check_would_actually_catch_a_probe(tmp_path):
    """A checker that can only pass is not a checker."""
    leaky = tmp_path / "leaky.py"
    leaky.write_text("import psutil\ndef traffic():\n"
                     "    return psutil.net_io_counters()\n", encoding="utf-8")
    assert "net_io_counters" in _names_touched(leaky, func="traffic")
    innocent = tmp_path / "ok.py"
    innocent.write_text('def traffic():\n    """never net_io_counters"""\n'
                        "    return {}\n", encoding="utf-8")
    assert "net_io_counters" not in _names_touched(innocent, func="traffic")


def test_the_endpoint_passes_the_cached_reading_rather_than_taking_one():
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8")
    block = src.split('@app.get("/api/glass")', 1)[1][:600]
    assert "_LAST_READING" in block, "the endpoint does not use the cache"
    assert "som.probe" not in block and "probe()" not in block


# ── it says what it is ──────────────────────────────────────────────────────

def test_the_banner_is_exact():
    assert gl.LABEL == ("Render of existing numbers. Mediation 1.0. "
                        "Not expression.")
    assert gl.render()["label"] == gl.LABEL
    assert gl.MEDIATION == 1.0


def test_every_panel_declares_its_mediation():
    d = gl.render()
    for key in ("stdout", "blocked", "traffic"):
        assert d[key]["mediation"] == 1.0, key


def test_the_banner_reaches_the_page():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    assert "esc(d.label)" in html, "the label is fetched but never drawn"


# ── panel 1: raw stdout ─────────────────────────────────────────────────────

def test_stdout_reads_the_newest_cycle_log(tmp_path):
    for name, body in (("cycle_2026-08-01_000000.log", "old\n"),
                       ("cycle_2026-08-23_030403.log", "a\nb\nc\n")):
        (tmp_path / name).write_text(body, encoding="utf-8")
    import os, time
    os.utime(tmp_path / "cycle_2026-08-01_000000.log", (1, 1))
    d = gl.stdout_tail(log_dir=tmp_path)
    assert d["lines"] == ["a", "b", "c"]
    assert d["path"].endswith("cycle_2026-08-23_030403.log")


def test_stdout_is_unfiltered_and_unformatted(tmp_path):
    """Raw means raw. No stripping, no colouring, no dropping blank lines."""
    body = "  indented\n\nERROR: something\n\ttabbed\n"
    (tmp_path / "cycle_2026-08-23_000000.log").write_text(body, encoding="utf-8")
    d = gl.stdout_tail(log_dir=tmp_path)
    assert d["lines"] == ["  indented", "", "ERROR: something", "\ttabbed"]


def test_stdout_truncation_says_it_truncated(tmp_path):
    (tmp_path / "cycle_2026-08-23_000000.log").write_text(
        "\n".join(str(i) for i in range(500)), encoding="utf-8")
    d = gl.stdout_tail(n=100, log_dir=tmp_path)
    assert len(d["lines"]) == 100
    assert d["truncated"] is True
    assert d["total_lines"] == 500


def test_no_cycle_log_is_reported_not_faked(tmp_path):
    d = gl.stdout_tail(log_dir=tmp_path)
    assert d["lines"] == []
    assert "no cycle log" in d["why"]


def test_it_reads_the_real_live_path():
    """Part 0 established memory/cycle_logs/ is where both launch paths write."""
    assert gl.CYCLE_LOG_DIR == REPO / "memory" / "cycle_logs"
    d = gl.stdout_tail()
    assert d["path"] is None or "cycle_logs" in d["path"]


# ── panel 2: blocked connections ────────────────────────────────────────────

def test_blocked_connections_parses_the_real_log():
    d = gl.blocked_connections()
    if not d["available"]:
        pytest.skip("no firewall log on this machine: {}".format(d["why"]))
    assert d["total"] > 0
    assert d["rows"], "the log has rows but none were parsed"


def test_it_shows_the_pid_column():
    """The log has one. A dropped connection nobody can attribute is noise."""
    d = gl.blocked_connections()
    if not d["rows"]:
        pytest.skip("no rows")
    assert "pid" in d["rows"][0]
    assert any(r["pid"] for r in d["rows"]), "every pid came back empty"


def test_it_is_never_called_an_attack_log():
    d = gl.blocked_connections()
    assert d["panel"] == "blocked connections"
    assert "attack" not in d["panel"].lower()
    assert "not an attack log" in d["note"]
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("async function tabGlass()", 1)[1].split(
        "async function render()", 1)[0]
    assert "attack" not in block.lower(), "the page calls them attacks"


def test_a_missing_firewall_log_is_reported_not_invented(tmp_path):
    d = gl.blocked_connections(path=tmp_path / "absent.log")
    assert d["available"] is False
    assert d["rows"] == []
    assert d["why"]


def test_a_row_carries_where_it_came_from_and_where_it_went(tmp_path):
    log = tmp_path / "pf.log"
    log.write_text(
        "#Version: 1.5\n"
        "#Fields: date time action protocol src-ip dst-ip src-port dst-port "
        "size tcpflags tcpsyn tcpack tcpwin icmptype icmpcode info path pid\n"
        "2026-08-23 14:47:47 DROP UDP 192.168.2.1 239.255.255.250 38511 1900 "
        "528 - - - - - - - RECEIVE 14052\n", encoding="utf-8")
    d = gl.blocked_connections(path=log)
    r = d["rows"][0]
    assert r["action"] == "DROP" and r["protocol"] == "UDP"
    assert r["src"] == "192.168.2.1" and r["dst"] == "239.255.255.250"
    assert r["dst_port"] == "1900" and r["pid"] == "14052"
    assert r["direction"] == "RECEIVE"


# ── panel 3: traffic, from the stream ───────────────────────────────────────

def test_traffic_prefers_the_cockpits_own_last_reading():
    d = gl.traffic({"net_sent_mb": 1598.7, "net_recv_mb": 7468.8})
    assert d["source"] == "the cockpit's own last reading"
    assert d["values"]["net_sent_mb"] == 1598.7


def test_traffic_falls_back_to_the_recorded_history():
    d = gl.traffic(None)
    assert d["source"] in (None, "memory/somatic_history.jsonl")
    if d["source"]:
        assert d["values"], "a source with no values"


def test_traffic_with_nothing_anywhere_says_so(tmp_path):
    empty = tmp_path / "h.jsonl"
    empty.write_text("", encoding="utf-8")
    d = gl.traffic(None, history_path=empty)
    assert d["values"] == {}
    assert "waits for a reading rather than taking one" in d["why"]


def test_traffic_never_calls_net_io_counters():
    touched = _names_touched(REPO / "cockpit" / "glass.py", func="traffic")
    assert "net_io_counters" not in touched
    assert "psutil" not in touched


# ── reachable in one click ──────────────────────────────────────────────────

def test_glass_is_a_top_level_tab_not_the_bottom_of_a_scroll():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    tabs = html.split("const TABS = [", 1)[1].split("];", 1)[0]
    assert "{id:'glass'" in tabs, "GLASS is not in the tab bar"
    assert "name:'GLASS'" in tabs


def test_it_is_wired_into_the_renderer():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    assert "glass:tabGlass" in html
    assert "async function tabGlass()" in html
    assert "/api/glass" in html


def test_it_has_a_keyboard_shortcut_like_every_other_tab():
    """drawTabs numbers the tabs and the digit keys switch to them, so being in
    TABS is the whole of 'one click'. This pins the mechanism."""
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    assert "if(n >= 1 && n <= TABS.length) switchTo(TABS[n-1].id);" in html


def test_all_three_panels_are_drawn():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("async function tabGlass()", 1)[1].split(
        "async function render()", 1)[0]
    for title in ("raw stdout", "blocked connections", "traffic counters"):
        assert "panel('{}'".format(title) in block, title


def test_the_selftest_passes():
    assert gl._selftest() == 0


def test_the_firewall_panel_reports_a_definite_state(capsys):
    """Read, or skipped-with-a-reason. Never neither.

    This test used to be the 30th failure in a suite whose baseline is 29,
    because C:\\Windows\\System32\\LogFiles\\Firewall\\pfirewall.log cannot be
    read without elevation and the selftest counted that as a failed check.
    Running the suite as administrator would have been the wrong fix: a test
    that only passes with a privilege is a test that silently does not run.

    So the property is the one the panel can actually guarantee — that it says
    which of the two happened — and the errno travels so "no privilege" stays
    distinguishable from "the OS is not writing the log".
    """
    d = gl.blocked_connections()
    assert d["available"] is True or d["why"], (
        "the panel neither read the log nor said why not — that is the failure "
        "worth having, and it is the only one this check makes")
    if d["available"] is not True:
        assert d.get("errno") is not None, (
            "an OSError reason must carry its errno, not only its sentence")


def test_a_skip_is_counted_and_named_in_the_output(capsys):
    """A skip nobody can see is the same as a check that never existed."""
    gl._selftest()
    out = capsys.readouterr().out
    if "SKIP" in out:
        assert "check(s) SKIPPED, not run:" in out, "skips must be summarised"
        assert "every check that ran passed" in out, (
            "a run with skips must not read as a run where everything passed")
    else:
        assert "every check passed" in out


def test_an_unexplained_failure_is_still_a_failure(monkeypatch):
    """The negative control: available=False AND no reason must fail.

    Without this, turning the check into a skip would have made the selftest
    pass on a panel that returned nothing and explained nothing — which is a
    worse outcome than the failure it replaced.
    """
    real = gl.blocked_connections

    def _mute(*a, **k):
        d = dict(real(*a, **k))
        d["available"], d["why"], d["errno"] = False, "", None
        return d

    monkeypatch.setattr(gl, "blocked_connections", _mute)
    assert gl._selftest() == 1, (
        "a panel that reported neither a read nor a reason must fail")


# ── PART 8: blocked connections as they arrive ──────────────────────────────

def test_the_tail_is_incremental_so_only_new_rows_spark():
    d = gl.blocked_connections()
    if not d["available"]:
        pytest.skip("no firewall log")
    assert d["offset"] == d["total"]
    again = gl.blocked_connections(since=d["offset"])
    assert again["new"] == 0, "the same rows came back as new"


def test_a_new_row_is_reported_as_new(tmp_path):
    log = tmp_path / "pf.log"
    hdr = ("#Fields: date time action protocol src-ip dst-ip src-port "
           "dst-port size tcpflags tcpsyn tcpack tcpwin icmptype icmpcode "
           "info path pid\n")
    row = ("2026-08-24 10:00:0{} DROP UDP 192.168.2.1 239.255.255.250 1 1900 "
           "1 - - - - - - - RECEIVE 4\n")
    log.write_text(hdr + row.format(0), encoding="utf-8")
    first = gl.blocked_connections(path=log)
    assert first["new"] == 1 and first["offset"] == 1
    with log.open("a", encoding="utf-8") as fh:
        fh.write(row.format(1))
    nxt = gl.blocked_connections(path=log, since=first["offset"])
    assert nxt["new"] == 1
    assert nxt["offset"] == 2


def test_the_counters_exist_and_are_under_the_sparks():
    d = gl.blocked_connections()
    if not d["rows"]:
        pytest.skip("no rows")
    assert set(d["counters"]) == {"by_action", "by_protocol", "by_process",
                                  "by_port"}
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("async function drawBlocked()", 1)[1].split(
        "async function drawEntropy()", 1)[0]
    assert block.index("sparks") < block.index("counters"), (
        "the counters are drawn above the arrivals")


def test_the_spark_carries_source_destination_port_and_pid():
    d = gl.blocked_connections()
    if not d["rows"]:
        pytest.skip("no rows")
    r = d["rows"][-1]
    for k in ("src", "dst", "dst_port", "pid"):
        assert k in r, k
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("async function drawBlocked()", 1)[1][:1800]
    for k in ("r.src", "r.dst", "r.dst_port", "r.pid"):
        assert k in block, k


def test_the_arriving_panel_is_still_never_called_attacks():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("async function drawBlocked()", 1)[1].split(
        "async function drawEntropy()", 1)[0]
    assert "attack" not in block.lower()
