"""What the model said, before anyone judged it.

Every other path a model's words take through this system is validated. That is
right for anything the system acts on, and it means there was nowhere in this
repo to read what the model ACTUALLY said — only what survived being checked.

Two things are tested here and they pull in opposite directions on purpose:

  the stream is unjudged      no gate, no verdict, no exemplar flag, and named
                              exemption from the purity census so it can never
                              be quietly gated by the back door.

  nothing consumes it         the instant something in the cycle reads
                              unvalidated text it stops being expression and
                              becomes an input nobody gated. The cockpit reads
                              it. Nothing else may.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import free_stream as fs        # noqa: E402
from core import language_gate as lg      # noqa: E402
from core import reaction as rx           # noqa: E402


@pytest.fixture
def freedir(tmp_path, monkeypatch):
    d = tmp_path / "free"
    monkeypatch.setattr(fs, "FREE_DIR", d)
    return d


def at(h, m=0, s=0):
    return datetime(2026, 8, 27, h, m, s, tzinfo=timezone.utc)


# -- one file per answer that came back ------------------------------------

def test_a_completed_answer_becomes_one_file(freedir, monkeypatch):
    monkeypatch.setattr(rx, "ask", lambda *a, **k: {
        "answer": "My RAM is high and my GPU has warmed a little.",
        "model": "qwen2.5:3b", "n_lines": 3, "why": "answered", "asked": True})
    monkeypatch.setattr(rx, "judge_language",
                        lambda a: {"exemplar_ok": True, "reason": "OK",
                                   "profile": {}})
    rec = rx.react([], path=freedir.parent / "reactions.jsonl")

    assert rec["free"]["written"] is True, rec["free"]
    files = list(freedir.glob("*.txt"))
    assert len(files) == 1
    assert "My RAM is high" in files[0].read_text(encoding="utf-8")


def test_an_answer_that_never_came_back_writes_nothing(freedir, monkeypatch):
    """SKIPPED_BUSY, a timeout, the switch being off — none of those is speech."""
    monkeypatch.setattr(rx, "ask", lambda *a, **k: {
        "answer": "", "why": "SKIPPED_BUSY: a model was mid-generation",
        "asked": False, "model": "qwen2.5:3b", "n_lines": 0})
    monkeypatch.setattr(rx, "judge_language",
                        lambda a: {"exemplar_ok": False, "reason": "empty",
                                   "profile": {}})
    rec = rx.react([], path=freedir.parent / "reactions.jsonl")
    assert rec["free"]["written"] is False
    assert not list(freedir.glob("*.txt"))


def test_a_dirty_answer_is_kept_anyway(freedir, monkeypatch):
    """The whole point. The gate's verdict decides the exemplar pool, not this."""
    monkeypatch.setattr(rx, "ask", lambda *a, **k: {
        "answer": "Паметта ми е висока.", "model": "q", "n_lines": 1,
        "why": "answered", "asked": True})
    monkeypatch.setattr(rx, "judge_language",
                        lambda a: {"exemplar_ok": False, "reason": "cyrillic",
                                   "profile": {}})
    rec = rx.react([], path=freedir.parent / "reactions.jsonl")
    assert rec["exemplar"] is False, "the gate did not reject it, so this proves nothing"
    assert rec["free"]["written"] is True, (
        "the free stream dropped an answer the gate disliked — it is gated "
        "after all")


def test_the_writer_is_not_the_judge():
    """ast: nothing in free_stream.py calls the language gate."""
    src = (REPO / "core" / "free_stream.py").read_text(encoding="utf-8-sig")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            assert name not in ("verdict", "is_english_enough", "entry_is_clean",
                                "judge_language"), (
                "the free stream judges what it stores, at line %d" % n.lineno)


# -- newest first ----------------------------------------------------------

def test_the_stream_reads_newest_first(freedir):
    for i, h in enumerate((10, 12, 11)):
        fs.write("answer %d" % i, directory=freedir, now=at(h), write=True)
    rows = fs.read(directory=freedir)
    assert [r["text"] for r in rows] == ["answer 1", "answer 2", "answer 0"], (
        "the stream is not newest first: %s" % [r["ts"] for r in rows])


def test_every_row_says_it_was_never_validated(freedir):
    fs.write("something", directory=freedir, now=at(10), write=True)
    row = fs.read(directory=freedir)[0]
    assert row["validated"] is False
    assert row["ts"], "the timestamp did not parse back out of the filename"


def test_the_file_itself_says_it_was_never_validated(freedir):
    fs.write("something", directory=freedir, now=at(10), write=True)
    body = next(freedir.glob("*.txt")).read_text(encoding="utf-8")
    assert "unvalidated" in body, (
        "a reader who finds this file alone cannot tell nothing checked it")


def test_the_directory_does_not_grow_for_ever(freedir):
    for i in range(8):
        fs.write("x%d" % i, directory=freedir, now=at(10, 0, i), write=True)
    fs.prune(keep=3, directory=freedir)
    rows = fs.read(directory=freedir)
    assert len(rows) == 3
    assert [r["text"] for r in rows] == ["x7", "x6", "x5"], (
        "pruning kept the OLDEST, which is backwards for a stream")


# -- exempt from the census, by name ---------------------------------------

def test_the_exemption_is_by_name_and_is_exactly_one():
    assert lg.PURITY_EXEMPT_KINDS == frozenset({"free_expression"}), (
        "an exemption you can add to by accident is a hole, not an exemption")


def test_the_exemption_says_why_it_exists():
    src = (REPO / "core" / "language_gate.py").read_text(encoding="utf-8-sig")
    i = src.index("PURITY_EXEMPT_KINDS")
    comment = src[max(0, i - 1400):i]
    assert "deliberately unvalidated" in comment, (
        "the exemption is stated without the reason, which is how an exemption "
        "becomes a hole nobody remembers agreeing to")


def test_free_expression_does_not_move_the_purity_ratio(tmp_path):
    j = tmp_path / "journal.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    j.write_text("".join(json.dumps(r) + "\n" for r in [
        {"ts": now, "kind": "constancy", "summary": "a plain english summary"},
        {"ts": now, "kind": "free_expression",
         "summary": "това изобщо не е английски"},
    ]), encoding="utf-8")
    ratio, total = lg.purity_ratio(24, j)
    assert (ratio, total) == (1.0, 1), (
        "unvalidated text was counted against the floor: %r over %r"
        % (ratio, total))


def test_free_expression_is_absent_from_the_breakdown(tmp_path):
    j = tmp_path / "journal.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    j.write_text("".join(json.dumps(r) + "\n" for r in [
        {"ts": now, "kind": "constancy", "summary": "plain english"},
        {"ts": now, "kind": "free_expression", "summary": "не е английски"},
    ]), encoding="utf-8")
    assert "free_expression" not in lg.purity_by_kind(24, j)


def test_nothing_else_slipped_into_the_exemption():
    """A ratchet. Anything new here is a decision somebody has to write down."""
    assert len(lg.PURITY_EXEMPT_KINDS) == 1


# -- only the cockpit reads it ---------------------------------------------

def test_only_three_files_touch_the_free_stream_at_all():
    """One writer, one reader, and the module itself.

    core/reaction.py writes it at the moment of the answer; cockpit/server.py
    reads it. Anything else is the cycle consuming unvalidated text, which is
    the thing this must never become.
    """
    allowed = {"core/free_stream.py", "core/reaction.py", "cockpit/server.py"}
    offenders = []
    for p in sorted(REPO.rglob("*.py")):
        # test/ is excluded, and that is not a loophole: a test that cannot
        # name this module cannot redirect it, and a test that cannot redirect
        # it writes fabricated model speech into the real stream. Eleven files
        # of it got there that way before the guard below caught them.
        if any(x in p.parts for x in ("venv", "venv312_metta", ".git",
                                      "__pycache__", "patches", "test")):
            continue
        rel = p.relative_to(REPO).as_posix()
        if rel in allowed:
            continue
        try:
            src = p.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        if "free_stream" not in src and "expression/free" not in src:
            continue
        # IMPORTS AND PATHS, not prose. core/language_gate.py names the
        # directory in the comment explaining its exemption, and a test that
        # greps raw text would forbid documenting the rule it enforces.
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        touches = False
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                touches |= any(a.name.endswith("free_stream") for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                touches |= ((n.module or "").endswith("free_stream")
                            or any(a.name == "free_stream" for a in n.names))
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                touches |= "expression/free" in n.value
        if touches:
            offenders.append(rel)
    assert not offenders, (
        "these touch the free stream and must not: %s" % offenders)


def test_the_writer_never_reads_it_back():
    """A writer that reads its own unvalidated output back into the cycle is
    the ungated input wearing the writer's badge."""
    src = (REPO / "core" / "reaction.py").read_text(encoding="utf-8-sig")
    calls = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if getattr(n.func.value, "id", None) == "fs":
                calls.add(n.func.attr)
    assert calls == {"write"}, (
        "core/reaction.py does more than write the free stream: %s" % calls)


def test_the_cockpit_reads_it_and_never_writes_it():
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8-sig")
    i = src.index("def api_free")
    body = src[i:i + 1200]
    assert "fs.read(" in body
    for banned in ("fs.write(", "fs.prune(", "guarded_extra_call"):
        assert banned not in body, (
            "the panel does more than read: %s" % banned)


def test_the_endpoint_names_it_for_what_it_is():
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8-sig")
    assert "FREE STREAM - unvalidated model expression" in src


def test_the_panel_exists_and_does_not_re_sort():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    assert "FREE STREAM - unvalidated model expression" in html
    i = html.index("/api/free")
    block = html[i:i + 900]
    assert ".sort(" not in block and ".reverse()" not in block, (
        "the panel re-orders what the server already ordered, so the two can "
        "disagree about which line is newest")
    assert "unvalidated" in block, "the panel does not label the rows"


# -- the first person ------------------------------------------------------

SECOND_PERSON = ("your own body", "your own state", "your RAM", "your GPU",
                 "your disk", "your memory")


def test_the_reaction_prompt_speaks_in_the_first_person():
    """It is its own body. The exemplar of 23 Aug says 'your RAM usage'."""
    q = rx.QUESTION.lower()
    found = [s for s in SECOND_PERSON if s.lower() in q]
    assert not found, (
        "the prompt addresses the machine in the second person about its own "
        "sensors, which is what produced 'your RAM usage': %s" % found)
    assert "my own body" in q and "first person" in q


def test_the_prompt_asks_for_the_answer_in_the_first_person_too():
    """Framing alone is not enough — the 23 Aug prompt said 'your own body'
    and the answer copied it back."""
    q = rx.QUESTION.lower()
    assert "my ram" in q, (
        "the prompt does not show the model what first person looks like for "
        "these readings")


def test_the_old_exemplar_is_kept_as_evidence():
    """Never rewrite a record. The bad answer stays; the prompt changed."""
    rec = REPO / "memory" / "reactions.jsonl"
    if not rec.exists():
        pytest.skip("no stored reactions on this machine")
    first = json.loads(rec.read_text(encoding="utf-8").splitlines()[0])
    assert "your RAM usage" in first["answer"], (
        "the 23 Aug exemplar was edited; history that lied is still evidence")


def test_no_new_second_person_self_prompts_appear():
    """A ratchet, not a sweep.

    core/brain.py and experiments/pulse/self_sense.py also address the machine
    as 'you' about its own state. Those are two other subsystems and changing
    them is not this part's job — but the count must not grow while nobody is
    looking.
    """
    known = {"core/brain.py", "experiments/pulse/self_sense.py"}
    found = set()
    for p in sorted(REPO.rglob("*.py")):
        if any(x in p.parts for x in ("venv", "venv312_metta", ".git",
                                      "__pycache__", "patches", "test")):
            continue
        try:
            src = p.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        if not any(s in src for s in ("your own body", "your own state")):
            continue
        # STRING LITERALS ONLY. core/reaction.py QUOTES the old prompt in the
        # comment explaining why it changed, and a test that greps raw text
        # would fail on the explanation of the defect rather than on the
        # defect. Docstrings are excluded for the same reason.
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        docs = {id(ast.get_docstring(n, clean=False))
                for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef))}
        for n in ast.walk(tree):
            if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n.value) not in docs
                    and any(s in n.value for s in ("your own body",
                                                   "your own state"))):
                found.add(p.relative_to(REPO).as_posix())
    assert found <= known, (
        "a new prompt addresses the machine in the second person about its "
        "own state: %s" % (found - known))
    assert "core/reaction.py" not in found


# -- it stays off live state ----------------------------------------------

def test_the_module_dry_runs_when_run_bare():
    src = (REPO / "core" / "free_stream.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    main = [n for n in tree.body if isinstance(n, ast.If)
            and getattr(getattr(n.test, "left", None), "id", None) == "__name__"]
    assert main, "no __main__ guard"
    called = {n.func.id for n in ast.walk(main[0])
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"write", "prune"}, (
        "running this module bare would write or delete: %s" % called)


def test_write_is_off_by_default():
    sig = [n for n in ast.walk(ast.parse(
        (REPO / "core" / "free_stream.py").read_text(encoding="utf-8-sig")))
        if isinstance(n, ast.FunctionDef) and n.name == "write"][0]
    default = sig.args.defaults[-1]
    assert default.value is False, "write=True is the default"


def test_these_tests_wrote_nothing_to_the_real_directory():
    live = REPO / "expression" / "free"
    assert not live.exists() or not list(live.glob("*.txt")), (
        "a test wrote into the real free stream")
