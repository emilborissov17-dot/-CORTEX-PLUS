# -*- coding: utf-8 -*-
"""test/test_narration.py - the baton says what it does while it does it (Emil R60, C-NARRATE-2).

core/narration.py, its use by the two turns and by core/brain.think, the loop's
refusal to start with a test switch set, and the cockpit's /api/narration and
LIVE tab. Every path is under tmp_path; no model, no network, no real turn."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import narration as nr  # noqa: E402
# imported here, at collection: importing the cockpit reads memory/ once (its receptor
# baselines), which the live-data net below would rightly refuse inside a test
from cockpit import server as srv  # noqa: E402
# the brain turn's fixtures, reused as they are (the same tmp paths, model and engine stand-ins)
from test_symbols_and_brain_turn import (_model, _open_budgets, _space_engine, sp_paths,  # noqa: E402,F401
                                         turn_paths)
from test_turn_agents import t  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


@pytest.fixture(autouse=True)
def _closed(monkeypatch):
    """No narration is open before or after a test, whatever the test did."""
    nr.close_turn(0, "")
    monkeypatch.delenv("CORTEX_TURN_ID", raising=False)
    yield
    nr.close_turn(0, "")


def rows(d: Path, turn: str = None) -> list:
    fs = sorted(d.glob("*.jsonl")) if turn is None else [d / f"{turn}.jsonl"]
    assert len(fs) == 1, fs
    return [json.loads(l) for l in fs[0].read_text(encoding="utf-8").splitlines()]


# ── the narrator itself ─────────────────────────────────────────────────────

def test_outside_an_open_turn_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(nr, "NARR_DIR", tmp_path / "narr")
    with nr.step("x", "why") as s:
        s.said("done")
    nr.note("n")
    nr.model("r", "m", "q", "a", 1.0)
    nr.begin("y", "why")
    nr.end("r")
    assert not (tmp_path / "narr").exists()


def test_a_turn_says_open_start_end_close_in_order_with_what_it_read_and_wrote(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(nr, "BASE", tmp_path)
    (tmp_path / "in.json").write_text("{}", encoding="utf-8")
    d = tmp_path / "narr"
    nr.open_turn("BRAIN", "turn-brain-7-x", narr_dir=d)
    with nr.step("work", "because", reads=[tmp_path / "in.json", tmp_path / "absent.json"]) as s:
        (tmp_path / "in.json").read_text(encoding="utf-8")
        (tmp_path / "out.json").write_text("abc", encoding="utf-8")
        s.said("wrote one file")
    nr.close_turn(0, "all done")
    rs = rows(d, "turn-brain-7-x")
    assert [r["kind"] for r in rs] == ["OPEN", "START", "END", "CLOSE"]
    assert [r["n"] for r in rs] == [1, 2, 3, 4]
    start, end = rs[1], rs[2]
    assert start["why"] == "because" and start["reads"][0]["age_h"] is not None and start["reads"][1]["age_h"] is None
    assert "absent.json (MISSING)" in start["line"]
    assert end["status"] == "OK" and end["result"] == "wrote one file"
    assert end["wrote"] == [{"path": "out.json", "bytes": 3}]
    assert [r["path"] for r in end["read"]] == ["in.json"]
    assert rs[3]["exit"] == 0 and rs[3]["summary"] == "all done"
    out = capsys.readouterr().out
    assert out.count("[NARRATION]") == 4 and "END work OK" in out, "the log does not say what the file says"


def test_a_failing_step_ends_FAILED_with_its_exception_and_the_exception_goes_on(tmp_path):
    nr.open_turn("BRAIN", "t1", narr_dir=tmp_path)
    with pytest.raises(ValueError, match="boom"):
        with nr.step("bad", "why"):
            raise ValueError("boom")
    nr.close_turn(1, "")
    end = [r for r in rows(tmp_path) if r["kind"] == "END"][0]
    assert end["status"] == "FAILED" and end["error"] == "ValueError: boom"


def test_a_step_left_open_is_closed_FAILED_when_the_turn_ends(tmp_path):
    nr.open_turn("AGENTS", "t2", narr_dir=tmp_path)
    nr.begin("needs", "why")
    nr.close_turn("none", "")
    rs = rows(tmp_path)
    assert [r["kind"] for r in rs] == ["OPEN", "START", "END", "CLOSE"]
    assert rs[2]["status"] == "FAILED" and "still open" in rs[2]["error"]


def test_a_turn_opened_with_a_test_switch_says_so_on_its_first_line(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_NO_REAL_MODEL", "1")
    nr.open_turn("BRAIN", "t3", narr_dir=tmp_path)
    nr.close_turn(0, "")
    first = rows(tmp_path)[0]
    assert first["switches"]["CORTEX_NO_REAL_MODEL"] == "1"
    assert "WARNING" in first["line"] and "no request reaches the local model" in first["line"]


def test_the_turn_id_comes_from_the_loop_and_its_absence_is_said(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_TURN_ID", "turn-brain-88-2026-10-05T17:00:00Z")
    nr.open_turn("BRAIN", narr_dir=tmp_path)
    nr.close_turn(0, "")
    assert (tmp_path / "turn-brain-88-2026-10-05T17_00_00Z.jsonl").exists()
    monkeypatch.delenv("CORTEX_TURN_ID")
    nr.open_turn("AGENTS", narr_dir=tmp_path / "b")
    nr.close_turn(0, "")
    first = rows(tmp_path / "b")[0]
    assert first["turn"].startswith("turn-agents-noid-") and "no id from the loop" in first["line"]


def test_model_rows_name_the_outcome(tmp_path):
    nr.open_turn("BRAIN", "t4", narr_dir=tmp_path)
    nr.model("judge", "m", "Q?", '{"verdict": "STILL_OPEN"}', 5.2)
    nr.model("judge", "m", "Q?", None, 0.0, "RealModelRefused: REAL_MODEL_REFUSED: CORTEX_NO_REAL_MODEL=1")
    nr.model("judge", "m", "Q?", None, 30.0, "ReadTimeout: read timed out")
    nr.close_turn(0, "")
    ms = [r for r in rows(tmp_path) if r["kind"] == "MODEL"]
    assert [m["outcome"] for m in ms] == ["REPLIED", "REFUSED", "ERROR"]
    assert "said: {\"verdict\": \"STILL_OPEN\"}" in ms[0]["line"] and "CORTEX_NO_REAL_MODEL=1" in ms[1]["line"]


def test_the_asked_part_of_a_written_instruction_is_its_last_paragraph_and_keeps_both_ends(tmp_path):
    from core import brain_texts as T
    p = T.TEXT_C.format(question="Which country?", items='- "a fact"')
    assert nr.asked_part(p).startswith("YOUR QUESTION: Which country?")
    long = T.TEXT_B.format(heads=", ".join(f"head{i}" for i in range(80)), sentence="UNHCR counted 1.2 million.")
    nr.open_turn("BRAIN", "t8", narr_dir=tmp_path)
    nr.model("symbols", "m", nr.asked_part(long), "{}", 1.0)
    nr.close_turn(0, "")
    asked = [r for r in rows(tmp_path) if r["kind"] == "MODEL"][0]["asked"]
    assert asked.startswith("Suggested heads") and asked.endswith("SENTENCE: UNHCR counted 1.2 million. ANSWER:")


def test_read_serves_complete_rows_only_and_from_since(tmp_path):
    f = tmp_path / "t5.jsonl"
    f.write_text('{"n": 1, "line": "a"}\n{"n": 2, "line": "b"}\n{"n": 3, "li', encoding="utf-8")
    r = nr.read("t5", 0, tmp_path)
    assert [x["n"] for x in r["rows"]] == [1, 2] and r["next"] == 2
    assert nr.read("t5", 1, tmp_path)["rows"] == [{"n": 2, "line": "b"}]


# ── core/brain.think: every call is said, a refused one included ────────────

def _brain_ready(monkeypatch):
    from core import brain
    monkeypatch.setattr(brain, "_pick_model", lambda: ("cortex-l1b-3b:latest", "http://127.0.0.1:11434"))
    monkeypatch.setattr(brain, "_guard_local", lambda m, purpose: m)
    return brain


def test_a_refused_model_call_is_named_on_the_narration_not_swallowed(tmp_path, monkeypatch):
    """5 Oct 2026: core/llm_door refused every call (CORTEX_NO_REAL_MODEL=1 leaked into the
    loop) and core/brain.think turned each refusal into a silent "no reply"."""
    brain = _brain_ready(monkeypatch)
    from core import llm_door

    def refuse(caller, backend, model, url, **k):
        raise llm_door.RealModelRefused(f"REAL_MODEL_REFUSED: CORTEX_NO_REAL_MODEL=1 - no model request "
                                        f"leaves this process ({caller} -> {url})")
    monkeypatch.setattr(llm_door, "post", refuse)
    nr.open_turn("BRAIN", "t6", narr_dir=tmp_path)
    with nr.step("review", "why"):
        out = brain.think("did it answer my question", "YOUR QUESTION: Q?\nANSWER:", exact=True,
                          json_schema={"type": "object"}, remember_it=False)
    nr.close_turn(0, "")
    assert out is None
    m = [r for r in rows(tmp_path) if r["kind"] == "MODEL"]
    assert len(m) == 1 and m[0]["outcome"] == "REFUSED" and "REAL_MODEL_REFUSED" in m[0]["error"]
    assert m[0]["step"] == "review" and m[0]["asked"].startswith("YOUR QUESTION: Q?")


def test_a_model_reply_is_said_with_what_came_back(tmp_path, monkeypatch):
    brain = _brain_ready(monkeypatch)
    from core import llm_door

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "the answer"}}
    monkeypatch.setattr(llm_door, "post", lambda *a, **k: R())
    nr.open_turn("BRAIN", "t7", narr_dir=tmp_path)
    out = brain.think("role", "Q?", exact=True, remember_it=False)
    nr.close_turn(0, "")
    assert out["text"] == "the answer"
    m = [r for r in rows(tmp_path) if r["kind"] == "MODEL"][0]
    assert m["outcome"] == "REPLIED" and m["reply"] == "the answer" and m["model"] == "cortex-l1b-3b:latest"


# ── the two turns ───────────────────────────────────────────────────────────

def _brain_turn(turn_paths, engine=_space_engine):
    from scripts import turn_brain as tb
    return tb.run(think=_model([]), engine=engine, busy=lambda: None, bn_paths=turn_paths["bn"],
                  space_paths=turn_paths["space"], sym_paths=turn_paths["sym"], read=lambda q, k: [], linked={},
                  result_path=turn_paths["result"], expect_path=turn_paths["expect"],
                  records_dir=turn_paths["result"].parent / "records",
                  gained_path=turn_paths["result"].parent / "gained.json")


def test_the_brain_turn_says_each_step_in_order(turn_paths, tmp_path):
    d = tmp_path / "narr"
    nr.open_turn("BRAIN", "tb", narr_dir=d)
    r = _brain_turn(turn_paths)
    nr.close_turn(r["exit"], r["summary"])
    rs = rows(d)
    starts = [x["step"] for x in rs if x["kind"] == "START"]
    assert starts == ["space.build", "space.derive", "briefing", "review", "ask", "emit", "symbols", "record"]
    ends = [x for x in rs if x["kind"] == "END"]
    assert [x["status"] for x in ends] == ["OK"] * 8 and all(x["result"] for x in ends)
    assert rs[-1]["kind"] == "CLOSE" and rs[-1]["exit"] == 0 and "open need(s)" in rs[-1]["summary"]


def test_a_failed_engine_ends_the_derive_step_FAILED_and_the_turn_names_it(turn_paths, tmp_path):
    from core import space as sp

    def broken(program):
        raise sp.SpaceEngineFailed("hyperon exit 1")
    nr.open_turn("BRAIN", "tb3", narr_dir=tmp_path / "narr")
    r = _brain_turn(turn_paths, engine=broken)
    nr.close_turn(r["exit"], r["summary"])
    rs = rows(tmp_path / "narr")
    end = [x for x in rs if x["kind"] == "END" and x["step"] == "space.derive"][0]
    assert r["exit"] == 2 and end["status"] == "FAILED" and "hyperon exit 1" in end["error"]
    assert rs[-1]["exit"] == 2


def test_the_agents_turn_says_each_need_it_searched_and_what_it_gained(t, tmp_path):
    d = tmp_path / "narr"
    nr.open_turn("AGENTS", "ta", narr_dir=d)
    r = t["go"]()
    nr.close_turn(r["exit"], r["summary"])
    rs = rows(d)
    assert [x["step"] for x in rs if x["kind"] == "START"] == ["needs", "maintenance"]
    assert [x["status"] for x in rs if x["kind"] == "END"] == ["OK", "OK"]
    notes = [x["line"] for x in rs if x["kind"] == "NOTE"]
    assert any("BN-1" in n and "searching" in n for n in notes)
    assert any("BN-1 served in" in n and "statement(s) gained" in n for n in notes)
    assert any(n.startswith("  - portion: 3 need(s) taken") for n in notes)


# ── the loop ────────────────────────────────────────────────────────────────

def test_the_loop_refuses_to_start_with_a_test_switch_set(tmp_path, monkeypatch, capsys):
    from scripts import turns_loop as tl
    monkeypatch.setattr(tl, "PID", tmp_path / "loop.pid")
    monkeypatch.setattr(sys, "argv", ["turns_loop.py"])
    monkeypatch.setenv("CORTEX_NO_REAL_MODEL", "1")
    monkeypatch.setattr(tl, "loop", lambda **k: pytest.fail("the loop ran with a test switch set"))
    assert tl.main() == 4
    assert "REFUSED: CORTEX_NO_REAL_MODEL=1" in capsys.readouterr().out
    assert not (tmp_path / "loop.pid").exists()
    assert tl.live_switches({"CONTROL_NO_TELEGRAM": "0"}) == ["CONTROL_NO_TELEGRAM=0"]
    assert tl.live_switches({}) == []


def test_the_loop_gives_each_turn_its_id(monkeypatch, tmp_path):
    from scripts import turns_loop as tl
    seen = {}

    class Done:
        returncode = 0
    monkeypatch.setattr(tl.subprocess, "run", lambda argv, **k: (seen.update(k["env"]), Done())[1])
    monkeypatch.setattr(tl, "LOGS", tmp_path / "logs")
    tl.witnessed("BRAIN", "turn-brain-90-2026-10-05T18:00:00Z")
    assert seen["CORTEX_TURN_ID"] == "turn-brain-90-2026-10-05T18:00:00Z"


def test_turns_bat_refuses_in_the_window_where_the_switch_is_set():
    bat = (REPO / "tools" / "turns.bat").read_text(encoding="utf-8")
    for k in ("CORTEX_NO_REAL_MODEL", "CONTROL_NO_TELEGRAM"):
        assert f"if defined {k} (echo REFUSED: {k}" in bat and "exit /b 4" in bat
    assert bat.index("if defined CORTEX_NO_REAL_MODEL") < bat.index("launch_detached.ps1 -Exe")


# ── the cockpit ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    d = tmp_path / "narration"
    d.mkdir()
    monkeypatch.setattr(srv, "NARRATION_DIR", d)
    monkeypatch.setattr(srv, "BATON_STATE", tmp_path / "turn.json")
    (tmp_path / "turn.json").write_text(json.dumps({"holder": "BRAIN", "seq": 90}), encoding="utf-8")
    return srv.app.test_client(), d


def test_api_narration_with_nothing_narrated_says_why(client):
    c, _ = client
    r = c.get("/api/narration")
    assert r.status_code == 200 and r.get_json()["turn"] is None and "empty" in r.get_json()["why"]


def test_api_narration_serves_the_newest_turn_from_since_and_not_a_half_line(client):
    c, d = client
    (d / "turn-brain-90-x.jsonl").write_text('{"n": 1, "line": "a"}\n{"n": 2, "line": "b"}\n{"n": 3',
                                             encoding="utf-8")
    j = c.get("/api/narration?turn=latest&since=0").get_json()
    assert j["turn"] == "turn-brain-90-x" and [x["n"] for x in j["rows"]] == [1, 2] and j["next"] == 2
    assert j["baton"]["seq"] == 90 and j["turns"][0]["turn"] == "turn-brain-90-x"
    j = c.get("/api/narration?turn=turn-brain-90-x&since=1").get_json()
    assert [x["n"] for x in j["rows"]] == [2]


def test_api_narration_refuses_an_unknown_or_unsafe_turn_and_a_bad_since(client):
    c, d = client
    (d / "a.jsonl").write_text('{"n": 1}\n', encoding="utf-8")
    assert c.get("/api/narration?turn=nope").status_code == 404
    assert c.get("/api/narration?turn=../a").status_code == 404
    assert c.get("/api/narration?since=x").status_code == 400


def test_api_narration_is_a_read_and_not_a_write_endpoint():
    rules = {str(r): r.methods for r in srv.app.url_map.iter_rules()}
    assert "POST" not in rules["/api/narration"] and "/api/narration" not in srv.WRITE_ENDPOINTS


def test_the_page_has_a_live_tab_that_polls_only_while_open():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(encoding="utf-8")
    assert "{id:'live',       name:'LIVE'}" in html and "live:tabLive" in html
    assert "async function tabLive()" in html and "get('/api/narration?turn=latest&since=0')" in html
    assert "if(active === 'live'){ stopLive(); liveTimer = setInterval(drawLive, 2000); }" in html
    assert "if(!el || active !== 'live'){ stopLive(); return; }" in html
