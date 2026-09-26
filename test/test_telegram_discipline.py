# -*- coding: utf-8 -*-
"""
test/test_telegram_discipline.py — only four classes reach Telegram (C4 E, 26 Sep 2026).

THE RULE (Emil): morning_digest, sign_request, new_risks, alarm (a failed night,
an unexplained death, an eviction during a run). brain_relay, phase reports, the
daily rationale, cycle_review/cycle_report brain texts go to files only.

What a refusal must look like: alarm_human returns "refused: ...", posts nothing,
and the message is still on disk in the night log with its class. The forbidden
fallbacks: sending anyway, and returning "deferred", because a deferred message
is one a morning flush could still carry to the phone.

Three nets, each failing when its guard is removed:
  * behaviour — every class outside the four is refused, day and night;
  * AST pin — every live alarm_human call names a class, and the calls whose
    class may reach Telegram are exactly the ones listed here;
  * direct senders — a new file posting to sendMessage outside the gate fails.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import supervisor as sup  # noqa: E402

SKIP_DIRS = {"venv", "venv312_metta", "venv_train", "test", ".git", "Broker-bot",
             "node_modules", "__pycache__", "_to_delete_gitlock", "Claude outputs"}


@pytest.fixture
def phone(tmp_path, monkeypatch):
    """Real-looking credentials, a requests module that records, files in tmp."""
    ch = tmp_path / "notify_channel.json"
    ch.write_text(json.dumps({"channel": "telegram", "token": "t", "chat_id": "c"}),
                  encoding="utf-8")
    monkeypatch.setattr(sup, "NOTIFY_CHANNEL", ch)
    monkeypatch.setattr(sup, "ALARM_STAMP", tmp_path / "alarm_sent.json")
    monkeypatch.setattr(sup, "NIGHT_LOG", tmp_path / "night_events.jsonl")
    posted = []

    class _Requests:
        @staticmethod
        def post(url, json=None, timeout=None, **kw):
            posted.append(json or {})

            class _R:
                status_code = 200

                @staticmethod
                def json():
                    return {"ok": True}
            return _R()

    monkeypatch.setitem(sys.modules, "requests", _Requests)
    return posted


def _night(tmp_path) -> list:
    return [json.loads(l) for l in (tmp_path / "night_events.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]


FILES_ONLY = ["brain_relay", "phase_report", "phase_debrief", "rationale",
              "cycle_review", "cycle_report", "stagnation", "proposal_sla",
              "needs_auth", "language_purity", "institution_witness", None, "",
              "ALARM", "Alarm", "alarm ", "morning-digest"]


@pytest.mark.parametrize("quiet", [False, True])
@pytest.mark.parametrize("cls", FILES_ONLY)
def test_any_other_class_is_refused_by_alarm_human(phone, monkeypatch, tmp_path, cls, quiet):
    monkeypatch.setattr(sup, "_quiet_now", lambda: quiet)
    for trigger in (None, "MANUAL"):
        out = sup.alarm_human("s", "d", dedup_key=f"k:{cls}:{trigger}", trigger=trigger,
                              level=sup.ALARM, cls=cls)
        assert out.startswith("refused"), (cls, trigger, out)
    assert phone == [], f"class {cls!r} reached Telegram"
    rows = _night(tmp_path)
    assert len(rows) == 2 and all(r["cls"] == cls for r in rows), "not kept on disk"


@pytest.mark.parametrize("cls", sup.TELEGRAM_CLASSES)
def test_the_four_classes_are_delivered(phone, monkeypatch, cls):
    monkeypatch.setattr(sup, "_quiet_now", lambda: False)
    assert sup.alarm_human("s", "d", dedup_key=f"ok:{cls}", cls=cls) == "delivered"
    assert len(phone) == 1


def test_the_four_classes_are_exactly_these():
    assert set(sup.TELEGRAM_CLASSES) == {"morning_digest", "sign_request", "new_risks", "alarm"}
    assert set(sup.QUIET_HOURS_ALLOWED_CLASSES) <= set(sup.TELEGRAM_CLASSES)


def test_the_quiet_hours_queue_never_holds_a_files_only_class(phone, monkeypatch, tmp_path):
    """Deferred is reserved for the four classes. A files-only message in quiet
    hours is refused, so nothing waiting for the morning can carry it out."""
    monkeypatch.setattr(sup, "_quiet_now", lambda: True)
    assert sup.alarm_human("s", "d", dedup_key="q1", cls="brain_relay").startswith("refused")
    assert sup.alarm_human("s", "d", dedup_key="q2", cls="alarm") == "deferred"
    monkeypatch.setattr(sup, "_quiet_now", lambda: False)
    assert phone == []


def test_the_outbox_holds_a_file_without_an_allowed_class(phone, monkeypatch, tmp_path):
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    monkeypatch.setattr(sup, "OUTBOX", outbox)
    monkeypatch.setattr(sup, "OUTBOX_SENT", outbox / "sent")
    monkeypatch.setattr(sup, "OUTBOX_HELD", outbox / "held")
    monkeypatch.setattr(sup, "BASE", tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notify_channel.json").write_text(
        json.dumps({"token": "t", "chat_id": "c"}), encoding="utf-8")
    monkeypatch.setattr(sup, "log", lambda *a, **k: None)
    (outbox / "METTA_SILENT_2026-09-26.md").write_text("x", encoding="utf-8")
    (outbox / "brain_relay__note.md").write_text("y", encoding="utf-8")
    (outbox / "alarm__disk.md").write_text("z", encoding="utf-8")
    assert sup.send_outbox() == 1
    assert len(phone) == 1 and phone[0]["text"] == "z"
    assert sorted(p.name for p in (outbox / "held").iterdir()) == [
        "METTA_SILENT_2026-09-26.md", "brain_relay__note.md"]


def test_push_rationale_writes_a_file_and_never_posts(tmp_path, monkeypatch):
    from experiments.needs import needs_report as nr

    class _NoNet:
        @staticmethod
        def post(*a, **k):
            raise AssertionError("push_rationale reached the network")

    monkeypatch.setitem(sys.modules, "requests", _NoNet)
    monkeypatch.setattr(nr, "RATIONALE_DIR", tmp_path)
    out = nr.push_rationale()
    assert out.startswith("file:") or out == "skip:no_content", out
    if out.startswith("file:"):
        assert list(tmp_path.glob("RATIONALE_*.md"))


def test_the_needs_push_carries_sign_requests_only(tmp_path, monkeypatch):
    from experiments.needs import needs_report as nr
    monkeypatch.setattr(nr, "NOTIFY_CFG", tmp_path / "cfg.json")
    (tmp_path / "cfg.json").write_text(json.dumps({"channel": "telegram", "token": "t",
                                                   "chat_id": "c"}), encoding="utf-8")
    monkeypatch.setattr(nr, "PUSH_STATE", tmp_path / "state.json")
    high_only = [{"severity": "high", "need": "x", "domain": "d"}]
    monkeypatch.setattr(nr, "_actionable", lambda rep: high_only)
    assert nr._push_status({}) == "skip:no_actionable"


# --------------------------------------------------------------------------- #
# AST net: every live alarm_human call names its class
# --------------------------------------------------------------------------- #

# (file, class) of every live call whose class may reach Telegram. Adding a
# sender to the phone means adding a line here, in review.
EXPECTED_TELEGRAM_CALLS = {
    ("core/death_bell.py", "alarm"),
    ("core/survival_gate.py", "alarm"),
    ("supervisor.py", "alarm"),
    ("core/alarm_bands.py", "new_risks"),
    ("experiments/institution/register_forward_row.py", "sign_request"),
    ("experiments/institution/publish_revisions.py", "sign_request"),      # C4 B revision SIGN requests
    ("tools/morning_digest.py", "morning_digest"),
}


def _py_files():
    for p in REPO.rglob("*.py"):
        rel = p.relative_to(REPO)
        if set(rel.parts[:-1]) & SKIP_DIRS or "_ARCHIVE" in rel.parts:
            continue
        yield p, rel.as_posix()


def _alarm_calls():
    out = []
    for p, rel in _py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name != "alarm_human":
                continue
            kw = {k.arg: k.value for k in n.keywords}
            cls = kw.get("cls")
            val = cls.value if isinstance(cls, ast.Constant) else ("<expr>" if cls else None)
            out.append((rel, n.lineno, val))
    return out


def test_every_live_alarm_human_call_names_a_class():
    calls = _alarm_calls()
    assert len(calls) >= 10, f"the walk found only {len(calls)} calls; it is not looking"
    unnamed = [c for c in calls if c[2] is None]
    assert not unnamed, ("alarm_human calls without cls= (refused on the phone, "
                         "but say which class you mean):\n" + "\n".join(map(str, unnamed)))


def test_the_calls_that_reach_telegram_are_exactly_the_listed_ones():
    reaching = {(rel, cls) for rel, _ln, cls in _alarm_calls() if cls in sup.TELEGRAM_CLASSES}
    assert reaching == EXPECTED_TELEGRAM_CALLS, (
        f"new: {sorted(reaching - EXPECTED_TELEGRAM_CALLS)}  "
        f"gone: {sorted(EXPECTED_TELEGRAM_CALLS - reaching)}")


# --------------------------------------------------------------------------- #
# Direct senders: nothing new may post to sendMessage around the gate
# --------------------------------------------------------------------------- #

# file -> why it may post directly. Each either asks telegram_refusal itself or
# is a human-run reply inside a sign conversation.
DIRECT_SENDERS = {
    "supervisor.py": "alarm_human and send_outbox, both behind telegram_refusal",
    "experiments/needs/needs_report.py": "_push_status: approval candidates only, sign_request, gated",
    "experiments/needs/approve_reader.py": "reply to the human's own OK/SIGN message (sign_request)",
    "experiments/needs/setup_telegram.py": "human-run setup; one test message to the human running it",
    "experiments/institution/telegram_witness.py": "gated: institution_witness is refused",
}


def test_no_new_direct_sender():
    found = set()
    for p, rel in _py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and "sendMessage" in n.value:
                found.add(rel)
            elif isinstance(n, ast.Call) and any(
                    isinstance(a, ast.Constant) and a.value == "sendMessage" for a in n.args):
                found.add(rel)
    assert found, "the walk found no sender at all; it is not looking"
    assert found <= set(DIRECT_SENDERS), f"new direct Telegram sender(s): {sorted(found - set(DIRECT_SENDERS))}"
