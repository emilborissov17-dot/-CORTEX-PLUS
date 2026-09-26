# -*- coding: utf-8 -*-
"""
test/test_institution_revisions.py — Institution 0 revisions (C4 B, 26 Sep 2026).

THE RULE for a refusal: append() must raise RevisionRefused and leave the file
unchanged; the gate's revision form must name the failed check; RF7 must
contradict a resolution whose filter or assumption is not the registered one.
The forbidden fallbacks: rewriting the row, a revision dated in the window, an
unsigned change to resolution semantics or signed wording taking effect, and a
resolution that moves the count to another dyad instead of saying
ASSUMPTION_BROKEN. Tests must write into tmp_path only, never the live forward/.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from experiments.institution import forward_witness as fw
from experiments.institution import resolve_forward_rows as rr
from experiments.institution import revisions as rv

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / "experiments" / "institution" / "forward"
TODAY = date(2026, 9, 26)


# ── arithmetic, on the rows' own data ────────────────────────────────────────

def test_laplace_is_the_rule_of_succession():
    assert rv.laplace(10, 13) == 11 / 15
    assert rv.laplace(0, 0) == 0.5 and rv.laplace(19, 19) == 20 / 21
    with pytest.raises(ValueError):
        rv.laplace(5, 4)


@pytest.mark.parametrize("row_id,k,n,p", [("F-001", 10, 13, 0.7333), ("F-002", 19, 19, 0.9524),
                                          ("F-003", 10, 14, 0.6875), ("F-004", 19, 19, 0.9524)])
def test_the_restated_baselines_are_computed_from_the_row_data(row_id, k, n, p):
    rev = rv.baseline_restatement(rv.row_of(row_id, LIVE), rv.threshold())
    v = rev["value"]
    assert (v["k"], v["n"], v["p_not_kept_laplace"]) == (k, n, p)
    assert rev["original"]["p_not_kept"] == rv.row_of(row_id, LIVE)["baseline"]["b_p_not_kept_post_commitment"]["p_not_kept"]


def test_f002_is_restated_on_the_successor_regime_only():
    v = rv.baseline_restatement(rv.row_of("F-002", LIVE), 25)["value"]
    assert v["window"].startswith("2025-02") and "successor" in v["regime"]


# ── append-only, dated, row untouched ────────────────────────────────────────

@pytest.fixture
def fdir(tmp_path):
    d = tmp_path / "forward"
    d.mkdir()
    for rid in ("F-001", "F-002"):
        shutil.copyfile(LIVE / f"{rid}.json", d / f"{rid}.json")
        shutil.copyfile(LIVE / f"{rid}.seal.json", d / f"{rid}.seal.json")
    return d


def _rest(value="x"):
    return {"kind": "restatement", "field": "label", "value": value, "original": None, "note": "t"}


def test_append_numbers_dates_and_leaves_the_row_bytes(fdir):
    before = (fdir / "F-002.json").read_bytes()
    a = rv.append("F-002", _rest("A"), fdir, TODAY)
    b = rv.append("F-002", _rest("B"), fdir, TODAY)
    assert (a["revision"], b["revision"], a["date"]) == (1, 2, "2026-09-26")
    assert (fdir / "F-002.json").read_bytes() == before


def test_a_revision_in_the_window_is_refused(fdir):
    with pytest.raises(rv.RevisionRefused):
        rv.append("F-002", _rest(), fdir, date(2026, 10, 1))
    assert not rv.log_path("F-002", fdir).exists()


def test_an_unknown_kind_and_a_duplicate_are_refused(fdir):
    with pytest.raises(rv.RevisionRefused):
        rv.append("F-002", dict(_rest(), kind="tweak"), fdir, TODAY)
    rv.append("F-002", _rest("A"), fdir, TODAY)
    with pytest.raises(rv.RevisionRefused):
        rv.append("F-002", _rest("A"), fdir, TODAY)
    assert len(rv.load("F-002", fdir)) == 1


def test_who_must_sign():
    row = rv.row_of("F-002", LIVE)
    assert rv.needs_signature({"kind": "restatement"}, row) is False
    assert rv.needs_signature({"kind": "semantics"}, row) is True
    assert rv.needs_signature({"kind": "signed_wording"}, row) is True
    assert rv.needs_signature({"kind": "made_up"}, row) is True, "an unknown kind is signed, not waved through"
    assert rv.needs_signature({"field": "addressee"}, row) is False     # F-001 r1, 25 Sep
    assert rv.needs_signature({"field": "sentences[1]"}, row) is True


def test_c4b_applies_once(fdir, monkeypatch):
    monkeypatch.setattr(rv, "ROWS", ("F-001", "F-002"))
    first = rv.apply_c4b(fdir, TODAY)
    assert [r["field"] for r in first["F-002"]] == [
        "baseline.b_p_not_kept_post_commitment", "assumption", "sentences[1]"]
    assert rv.apply_c4b(fdir, TODAY) == {"F-001": [], "F-002": []}


# ── signatures decide what is in force ───────────────────────────────────────

def _sign(sigs: Path, row_id: str, rev: dict):
    with sigs.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"signer": "Emil", "channel": "telegram", "date": "2026-09-26",
                             "row_id": row_id, "revision": rev["revision"],
                             "revision_sha256": rv.rev_hash(rev)}) + "\n")


@pytest.fixture
def signed_assumption(fdir, tmp_path, monkeypatch):
    sigs = tmp_path / "sigs.jsonl"
    sigs.write_text("", encoding="utf-8")
    monkeypatch.setattr(rv, "SIGNATURES", sigs)
    monkeypatch.setattr(rv, "ROWS", ("F-002",))
    revs = rv.apply_c4b(fdir, TODAY)["F-002"]
    return {"fdir": fdir, "sigs": sigs, "assumption": next(r for r in revs if r["field"] == "assumption")}


def test_an_unsigned_assumption_is_not_in_force(signed_assumption):
    w = signed_assumption
    assert rv.assumption("F-002", w["fdir"]) is None
    assert [r["field"] for r in rv.pending("F-002", w["fdir"])] == ["assumption", "sentences[1]"]


def test_a_signature_on_another_hash_does_not_count(signed_assumption):
    w = signed_assumption
    _sign(w["sigs"], "F-002", dict(w["assumption"], value={"tampered": True}))
    assert rv.assumption("F-002", w["fdir"]) is None


def test_a_signed_assumption_is_in_force(signed_assumption):
    w = signed_assumption
    _sign(w["sigs"], "F-002", w["assumption"])
    assert rv.assumption("F-002", w["fdir"])["outcome_if_broken"] == rv.ASSUMPTION_BROKEN


# ── the resolver and RF7 know the assumption ─────────────────────────────────

class Client:
    def __init__(self, same=(), other=()):
        self.same, self.other, self.requests = list(same), list(other), 0

    def released(self, version):
        self.requests += 1
        return True

    def events(self, version, condition):
        self.requests += 1
        return list(self.same)

    def events_any(self, version, query):
        self.requests += 1
        assert query == {"Country": 625, "TypeOfViolence": 1}
        return list(self.same) + list(self.other)


def _ev(i, best, dyad="18621", side_b="SFA", day="2026-10-10"):
    return {"id": str(i), "type_of_violence": "1", "dyad_new_id": dyad, "country": "Sudan",
            "adm_1": "Khartoum state", "date_start": day, "best": str(best),
            "side_a": "Government of Sudan", "side_b": side_b, "dyad_name": f"Government of Sudan - {side_b}"}


def _resolve(w, client):
    return rr.resolve_row(w["fdir"] / "F-002.json", client, today=date(2026, 11, 22),
                          roots_log=w["fdir"].parent / "roots.jsonl")


def test_events_coded_to_another_dyad_break_the_signed_assumption(signed_assumption):
    w = signed_assumption
    _sign(w["sigs"], "F-002", w["assumption"])
    out = _resolve(w, Client(same=[_ev(1, 10)], other=[_ev(2, 300, dyad="99999", side_b="RSF")]))
    rec = out["appended"]
    assert rec["verdict"] == rv.ASSUMPTION_BROKEN, rec
    assert rec["value"] == 10.0, "the count stays on the registered dyad"
    assert rec["filter"] == rv.row_of("F-002", w["fdir"])["condition"], "the filter moved"
    assert rec["assumption_evidence"]["99999"]["best"] == 300.0
    f = fw.rf7_facts(rv.row_of("F-002", w["fdir"]), rec, w["fdir"])
    assert fw.python_reference("RF7", f) is True


def test_an_unrelated_dyad_does_not_break_it(signed_assumption):
    w = signed_assumption
    _sign(w["sigs"], "F-002", w["assumption"])
    out = _resolve(w, Client(same=[_ev(1, 40)], other=[_ev(2, 300, dyad="555", side_b="SPLM-N")]))
    assert out["appended"]["verdict"] == "NOT_KEPT" and out["appended"]["assumption_evidence"] == {}


def test_without_the_signature_the_resolver_ignores_the_assumption(signed_assumption):
    w = signed_assumption
    out = _resolve(w, Client(same=[_ev(1, 10)], other=[_ev(2, 300, dyad="99999", side_b="RSF")]))
    assert out["appended"]["verdict"] == "KEPT" and "assumption" not in out["appended"]


def test_rf7_refuses_a_resolution_that_ignores_or_invents_an_assumption(signed_assumption):
    w = signed_assumption
    row = rv.row_of("F-002", w["fdir"])
    base = {"stage": "PROVISIONAL", "filter": row["condition"]}
    # unsigned: claiming the assumption is a contradiction
    assert fw.python_reference("RF7", fw.rf7_facts(row, dict(base, assumption=w["assumption"]["value"]),
                                                   w["fdir"])) is False
    _sign(w["sigs"], "F-002", w["assumption"])
    # signed: ignoring it is a contradiction
    assert fw.python_reference("RF7", fw.rf7_facts(row, base, w["fdir"])) is False
    # signed: moving the count to the other dyad is a contradiction
    moved = dict(base, filter=dict(row["condition"], dyad_new_id=99999), assumption=w["assumption"]["value"])
    assert fw.python_reference("RF7", fw.rf7_facts(row, moved, w["fdir"])) is False


# ── the gate's revision form ─────────────────────────────────────────────────

from core import passage_rules, prereg_gate as pg  # noqa: E402

CLS = passage_rules.load(strict=True)["classes"]["human_signed_preregistration"]
PASS = {"verdict": "PASS", "why": "", "engines_agree": True, "contradictions": [],
        "not_evaluated": [], "hyperon": {"ok": True, "version": "t"}}


@pytest.fixture
def gated(signed_assumption, monkeypatch):
    w = signed_assumption
    fd = w["fdir"]
    sha = hashlib.sha256((fd / "F-002.json").read_bytes()).hexdigest()
    with w["sigs"].open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"signer": "Emil", "channel": "telegram", "date": "2026-09-26",
                             "row_id": "F-002", "row_sha256": sha}) + "\n")
    for r in rv.pending("F-002", fd):
        _sign(w["sigs"], "F-002", r)
    roots = fd.parent / "roots.jsonl"
    rv.seal("F-002", fd, roots)
    real = pg.applies
    monkeypatch.setattr(pg, "applies", lambda cls, step, target:
                        real(cls, step, target) or (step == cls["step"] and Path(str(target)).parent.name == "forward"))
    root = json.loads((fd / "F-002.seal.json").read_text(encoding="utf-8"))["root"]
    return dict(w, roots=roots, root=root, log=rv.log_path("F-002", fd))


def _g(w, prev=None):
    return pg.evaluate(CLS, "github_publish", w["log"], w["root"] if prev is None else prev,
                       witness=PASS, roots_log=w["roots"], signatures=w["sigs"])


def _failed(g):
    return {n for n, _ in g["failed"]}


def test_a_signed_sealed_revisions_file_passes_every_check(gated):
    g = _g(gated)
    assert g["ok"] is True and g["form"] == "revision", g
    assert [n for n, _ in g["passed"]] == [n for n, _ in pg.CHECKS_REVISION]


def test_rev_signature_refuses_an_unsigned_semantic_revision(gated):
    rv.append("F-002", {"kind": "signed_wording", "field": "sentences[0]", "value": "new", "original": "x",
                        "note": "t"}, gated["fdir"], TODAY)
    rv.seal("F-002", gated["fdir"], gated["roots"])
    assert _failed(_g(gated)) == {"signature"}


def test_restatements_publish_without_a_signature(fdir, tmp_path, monkeypatch):
    sigs = tmp_path / "s.jsonl"
    sha = hashlib.sha256((fdir / "F-001.json").read_bytes()).hexdigest()
    sigs.write_text(json.dumps({"signer": "Emil", "channel": "telegram", "date": "2026-09-25",
                                "row_id": "F-001", "row_sha256": sha}) + "\n", encoding="utf-8")
    monkeypatch.setattr(rv, "SIGNATURES", sigs)
    rv.append("F-001", rv.baseline_restatement(rv.row_of("F-001", fdir), 25), fdir, TODAY)
    roots = fdir.parent / "roots.jsonl"
    rv.seal("F-001", fdir, roots)
    real = pg.applies
    monkeypatch.setattr(pg, "applies", lambda cls, step, target:
                        real(cls, step, target) or (step == cls["step"] and Path(str(target)).parent.name == "forward"))
    root = json.loads((fdir / "F-001.seal.json").read_text(encoding="utf-8"))["root"]
    g = pg.evaluate(CLS, "github_publish", rv.log_path("F-001", fdir), root, witness=PASS,
                    roots_log=roots, signatures=sigs)
    assert g["ok"] is True, g["failed"]


def test_rev_dated_refuses_a_revision_in_the_window(gated):
    log = gated["log"]
    lines = log.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0]); rec["date"] = "2026-10-01"; lines[0] = json.dumps(rec, ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rv.seal("F-002", gated["fdir"], gated["roots"])
    assert "dated" in _failed(_g(gated))


def test_rev_row_unchanged_refuses_edited_row_bytes(gated):
    p = gated["fdir"] / "F-002.json"
    p.write_bytes(p.read_bytes() + b" ")
    assert "row_unchanged" in _failed(_g(gated))


def test_rev_seal_refuses_an_edited_revisions_file(gated):
    b = bytearray(gated["log"].read_bytes())
    b[b.index(b"SENTINEL") if b"SENTINEL" in b else b.index(b"restatement")] = ord("X")
    gated["log"].write_bytes(bytes(b))
    assert "seal" in _failed(_g(gated))


def test_rev_prev_step_must_be_the_rows_root(gated):
    assert "prev_step" in _failed(_g(gated, prev="0" * 64))


# ── the SIGN reply for a revision ────────────────────────────────────────────

def test_a_revision_signature_is_written_only_for_the_exact_hash(signed_assumption, monkeypatch):
    from experiments.needs import approve_reader as ar
    w = signed_assumption
    monkeypatch.setattr(ar, "_reply", lambda *a, **k: None)
    monkeypatch.setattr(ar, "_ledger", lambda *a, **k: None)
    a = w["assumption"]
    bad = ar.apply_signature(f"SIGN F-002 R{a['revision']} {'0' * 64}", "t", "c",
                             signatures=w["sigs"], forward_dir=w["fdir"])
    assert bad["ok"] is False and w["sigs"].read_text(encoding="utf-8") == ""
    good = ar.apply_signature(f"SIGN F-002 R{a['revision']} {rv.rev_hash(a)}", "t", "c",
                              signatures=w["sigs"], forward_dir=w["fdir"])
    assert good["ok"] is True and "row_sha256" not in good, "a revision signature must not pass for a row one"
    assert rv.assumption("F-002", w["fdir"]) is not None


# ── the page ─────────────────────────────────────────────────────────────────

def test_the_page_reports_the_hit_rate_with_and_without_sentinel_rows(fdir, monkeypatch, tmp_path):
    rows = [rv.row_of("F-001", fdir), dict(rv.row_of("F-002", fdir), label="SENTINEL")]
    for r, verdict in (("F-001", "NOT_KEPT"), ("F-002", "NOT_KEPT")):
        (fdir / f"{r}.resolutions.jsonl").write_text(json.dumps({"verdict": verdict}) + "\n", encoding="utf-8")
    monkeypatch.setattr(rv, "SIGNATURES", tmp_path / "none.jsonl")
    # F-001 p 0.7692 -> call NOT_KEPT, a hit; F-002 p 0.4872 -> call KEPT, a miss
    assert rv.hit_rate(rows, fdir) == (1, 2)
    assert rv.hit_rate(rows, fdir, exclude_label="SENTINEL") == (1, 1)


def test_the_sealed_revision_bytes_are_lf_and_are_what_is_published(fdir, monkeypatch):
    """The seal hashes exact bytes. A CRLF written by Windows text mode is bytes git
    (eol=lf) and the publisher never carry, so the public seal would not verify."""
    rv.append("F-002", _rest("A"), fdir, TODAY)
    rv.append("F-002", _rest("B"), fdir, TODAY)
    raw = rv.log_path("F-002", fdir).read_bytes()
    assert b"\r" not in raw
    s = rv.seal("F-002", fdir, fdir.parent / "roots.jsonl")
    published = {}
    import github_publisher as gp
    monkeypatch.setattr(gp, "publish_institution0", lambda files, msg: published.update(files) or [])
    from core import notary
    monkeypatch.setattr(notary, "may_act", lambda *a, **k: (True, "test"))
    from experiments.institution import forward_rows as fr
    monkeypatch.setattr(fr, "PUBLISH_LEDGER", fdir.parent / "ledger.jsonl")
    from experiments.institution import register_forward_row as reg
    monkeypatch.setattr(reg, "page_all", lambda: "page")
    from experiments.institution import publish_revisions as pr
    pr.publish("F-002", fdir)
    body = published["institution0/F-002.revisions.jsonl"].encode("utf-8")
    assert fr._digest(body, s["prev_root"], s["writer"]) == s["root"], "the published file does not verify"
