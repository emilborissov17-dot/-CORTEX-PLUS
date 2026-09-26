"""
test/test_prereg_gate.py — passage class human_signed_preregistration (task #9b).

A refusal looks like: evaluate() ok=False with the failing check named; may_act()
False with "class human_signed_preregistration refused — <check>: <why>". The
forbidden fallbacks: a missing signature read as consent, a silent MeTTa engine read
as "no contradiction", an undeclared prev_step read as "first step", and any of this
reaching a step or target the class does not name. One test per check fails if that
check is removed (the mutation run is in the task #9b commit message).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import merkle_memory as mm
from core import notary, passage_rules, prereg_gate as pg
from experiments.institution import forward_rows as fr

REPO = Path(__file__).resolve().parents[1]
REAL_ROW = REPO / "experiments" / "institution" / "forward" / "F-001.json"
CLS = passage_rules.load(strict=True)["classes"]["human_signed_preregistration"]
PASS = {"verdict": "PASS", "why": "", "engines_agree": True, "contradictions": [],
        "not_evaluated": [], "hyperon": {"ok": True, "version": "t"}}


@pytest.fixture
def world(tmp_path):
    fdir = tmp_path / "forward"
    fdir.mkdir()
    row = fdir / "F-001.json"
    shutil.copyfile(REAL_ROW, row)
    sha = hashlib.sha256(row.read_bytes()).hexdigest()
    seal = fr.seal(row, None, {"pid": 1, "process": "t", "commit": "x"})
    (fdir / "F-001.seal.json").write_text(json.dumps(seal), encoding="utf-8")
    roots = tmp_path / "merkle_roots.jsonl"
    roots.write_text(json.dumps({"root": seal["root"], "prev_root": None}) + "\n", encoding="utf-8")
    sigs = tmp_path / "signatures.jsonl"
    sigs.write_text(json.dumps({"signer": "Emil", "channel": "telegram", "date": "2026-09-25",
                                "row_id": "F-001", "row_sha256": sha}) + "\n", encoding="utf-8")
    return {"row": row, "sha": sha, "seal": seal, "roots": roots, "sigs": sigs, "fdir": fdir}


def _eval(w, prev=notary.PREV_NONE, witness=PASS, step="github_publish", target=None, ceiling=None):
    return pg.evaluate(CLS, step, target or w["row"], prev, ceiling=ceiling,
                       witness=witness, signatures=w["sigs"], roots_log=w["roots"])


def _failed(g):
    return {n for n, _w in g["failed"]}


def test_all_five_checks_holding_passes_at_level_2(world, monkeypatch):
    monkeypatch.setattr(pg, "applies", lambda cls, step, target: step == "github_publish")
    g = _eval(world)
    assert g["ok"] is True and g["level"] == 2, g
    assert [n for n, _ in g["passed"]] == ["signature", "seal", "prev_step", "metta", "unevaluated"]


# ── one test per check ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _applies_to_tmp_rows(monkeypatch):
    real = pg.applies
    monkeypatch.setattr(pg, "applies", lambda cls, step, target:
                        real(cls, step, target) or (step == cls["step"] and Path(str(target)).parent.name == "forward"))


def test_check_signature_refuses_a_missing_or_mismatched_signature(world):
    world["sigs"].write_text("", encoding="utf-8")
    assert "signature" in _failed(_eval(world))
    world["sigs"].write_text(json.dumps({"signer": "Emil", "channel": "telegram", "date": "2026-09-25",
                                         "row_id": "F-001", "row_sha256": "0" * 64}) + "\n", encoding="utf-8")
    assert "signature" in _failed(_eval(world))


def test_check_seal_refuses_an_edited_row_or_a_broken_chain(world):
    b = bytearray(world["row"].read_bytes())
    b[b.index(b"25")] = ord("3")
    world["row"].write_bytes(bytes(b))
    assert "seal" in _failed(_eval(world))


def test_check_seal_refuses_a_broken_root_chain(world):
    lines = world["roots"].read_text(encoding="utf-8")
    world["roots"].write_text(lines + json.dumps({"root": "b" * 64, "prev_root": "c" * 64}) + "\n",
                              encoding="utf-8")
    assert "seal" in _failed(_eval(world))


def test_check_prev_step_refuses_an_undeclared_predecessor(world):
    assert "prev_step" in _failed(_eval(world, prev=notary.PREV_UNKNOWN))
    assert "prev_step" in _failed(_eval(world, prev=None))
    assert "prev_step" not in _failed(_eval(world, prev=notary.PREV_NONE))


def test_check_metta_refuses_a_contradiction(world):
    w = dict(PASS, verdict="REFUSE", why="contradicted: RF4", contradictions=["RF4"])
    assert "metta" in _failed(_eval(world, witness=w))


def test_check_unevaluated_refuses_silence_and_unevaluated_rules(world):
    silent = dict(PASS, hyperon={"ok": False, "error": "sidecar absent"})
    assert "unevaluated" in _failed(_eval(world, witness=silent))
    partial = dict(PASS, verdict="REFUSE", not_evaluated=["RF5"], engines_agree=False)
    g = _eval(world, witness=partial)
    assert "unevaluated" in _failed(g) and "metta" in _failed(g)


# ── where the class does NOT apply ───────────────────────────────────────────

def test_the_class_names_one_step_and_one_target_glob():
    assert pg.applies(CLS, "github_publish", REAL_ROW)
    assert not pg.applies(CLS, "execute_patches", REAL_ROW)
    assert not pg.applies(CLS, "github_publish", REPO / "memory" / "x.json")
    assert not pg.applies(CLS, "github_publish", None)


def test_a_ceiling_below_the_class_level_still_binds(world):
    g = _eval(world, ceiling=1)
    assert g["ok"] is False and "ceiling" in _failed(g)


# ── the notary consults the class only after its vector refused ──────────────

def test_may_act_passes_through_the_class_and_refuses_naming_it(world, monkeypatch):
    rec = {"level": 0, "level_name": "level_0", "vector": {"witness": 0}, "why": {"witness": "MeTTa silent"},
           "inherited": 0, "own": 0, "inherited_from": None}
    monkeypatch.setattr(notary, "attest", lambda *a, **k: dict(rec))
    monkeypatch.setattr(pg, "evaluate", lambda *a, **k: {"applies": True, "ok": True, "level": 2,
                                                         "passed": [("signature", "s")], "failed": []})
    ok, why = notary.may_act("github_publish", notary.PREV_NONE, target=world["row"])
    assert ok is True and "human_signed_preregistration" in why
    monkeypatch.setattr(pg, "evaluate", lambda *a, **k: {"applies": True, "ok": False, "level": 2,
                                                         "passed": [], "failed": [("signature", "none")]})
    ok, why = notary.may_act("github_publish", notary.PREV_NONE, target=world["row"])
    assert ok is False and "class human_signed_preregistration refused" in why and "signature" in why
    ok, why = notary.may_act("github_publish", notary.PREV_NONE)
    assert ok is False and "human_signed_preregistration" not in why, "no target -> no class"


def test_the_class_is_ratified_in_the_passage_rules():
    assert CLS["step"] == "github_publish"
    assert CLS["target_glob"] == "experiments/institution/forward/*"
    assert CLS["level"] == 2 and len(CLS["requires_all"]) == 5


# ── the signature is written by the owner's reply, never by the model ────────

def test_apply_signature_writes_only_a_matching_sha(world, monkeypatch):
    import sys
    sys.path.insert(0, str(REPO / "experiments" / "needs"))
    import approve_reader as ar
    replies = []
    monkeypatch.setattr(ar, "_reply", lambda t, c, text: replies.append(text))
    monkeypatch.setattr(ar, "_ledger", lambda e: None)
    sigs = world["fdir"].parent / "sigs_out.jsonl"
    bad = ar.apply_signature(f"SIGN F-001 {'0' * 64}", "t", "c", signatures=sigs, forward_dir=world["fdir"])
    assert bad["ok"] is False and not sigs.exists()
    assert ar.apply_signature("SIGN F-001 abc", "t", "c", signatures=sigs,
                              forward_dir=world["fdir"])["ok"] is False and not sigs.exists()
    good = ar.apply_signature(f"sign F-001 {world['sha']}", "t", "c", update_id=7,
                              signatures=sigs, forward_dir=world["fdir"])
    assert good["ok"] is True
    row = json.loads(sigs.read_text(encoding="utf-8"))
    assert (row["signer"], row["channel"], row["row_sha256"]) == ("Emil", "telegram", world["sha"])


def test_the_dispatcher_routes_sign_to_the_signature_path():
    from experiments.institution import telegram_dispatcher as d
    assert d.route(f"SIGN F-001 {'a' * 64}") == "sign"
    assert d.route("signature please") == "unparsed"


# ── alarm_human says whether it delivered ────────────────────────────────────

def test_alarm_human_reports_its_outcome(tmp_path, monkeypatch):
    import requests
    import supervisor as sup
    ch = tmp_path / "notify.json"
    ch.write_text(json.dumps({"channel": "telegram", "token": "t", "chat_id": "1"}), encoding="utf-8")
    monkeypatch.setattr(sup, "NOTIFY_CHANNEL", ch)
    monkeypatch.setattr(sup, "ALARM_STAMP", tmp_path / "stamp.json")
    monkeypatch.setattr(sup, "note_night_event", lambda *a, **k: None)
    monkeypatch.setattr(sup, "_quiet_now", lambda: False)

    class R:
        def __init__(self, ok):
            self.status_code, self._ok = 200, ok

        def json(self):
            return {"ok": self._ok}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R(False))
    assert sup.alarm_human("s", "d", dedup_key="k1", cls="alarm").startswith("failed")
    monkeypatch.setattr(requests, "post", lambda *a, **k: R(True))
    assert sup.alarm_human("s", "d", dedup_key="k1", cls="alarm") == "delivered"
    assert sup.alarm_human("s", "d", dedup_key="k1", cls="alarm") == "suppressed"
    monkeypatch.setattr(sup, "_quiet_now", lambda: True)
    assert sup.alarm_human("s", "d", dedup_key="k2", cls="alarm") == "deferred"
    assert sup.alarm_human("s", "d", dedup_key="k3", trigger="MANUAL", cls="alarm") == "delivered"
    assert sup.alarm_human("s", "d", dedup_key="k4").startswith("refused")


# ── the real witness, end to end, on the real row with a test signature ──────

def test_the_real_witness_passes_rf1_to_rf6_once_signed(world):
    from core import ucdp_client as uc
    from experiments.institution import forward_witness as fw
    if not all((uc.DATA_DIR / n).exists() for n, _u, _k in uc.SOURCES) or not fw.SIDECAR_PY.exists():
        pytest.skip("UCDP release files or the MeTTa sidecar are not on this machine")
    w = fw.witness("F-001", write=False, forward_dir=world["fdir"], signatures=world["sigs"])
    assert w["verdict"] == "PASS", w["why"]
    assert all(v["python"] is True and v["hyperon"] is True for v in w["rules"].values())
    unsigned = fw.witness("F-001", write=False, forward_dir=world["fdir"],
                          signatures=world["fdir"] / "none.jsonl")
    assert unsigned["verdict"] == "REFUSE" and unsigned["not_evaluated"] == ["RF5"]
