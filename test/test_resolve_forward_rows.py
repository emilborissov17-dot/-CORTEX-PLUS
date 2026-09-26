"""
test/test_resolve_forward_rows.py — the forward-row resolver (task #30 part 1).

A refusal looks like: action WAITING / ERROR with nothing written, or a witness
REFUSE naming RF7. The forbidden fallbacks: a resolution computed from a release
that does not cover the window, a verdict written before the source exists, an
earlier resolution rewritten, and a resolution whose filter differs from the row's
condition. No test here may reach the network (conftest points the UCDP client at a
closed local port).
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from core import ucdp_client as uc
from experiments.institution import resolve_forward_rows as rr

REPO = Path(__file__).resolve().parents[1]
ROW = REPO / "experiments" / "institution" / "forward" / "F-001.json"


class FakeClient:
    def __init__(self, released=(), events=None):
        self._released, self._events, self.requests = set(released), events or [], 0

    def released(self, version):
        self.requests += 1
        return version in self._released

    def events(self, version, condition):
        self.requests += 1
        return list(self._events)


def _ev(i, best, day="2026-10-10", adm="Nord Kivu province", dyad="17740", tov="1"):
    return {"id": str(i), "type_of_violence": tov, "dyad_new_id": dyad, "adm_1": adm,
            "date_start": day, "best": str(best)}


@pytest.fixture
def fdir(tmp_path):
    d = tmp_path / "forward"
    d.mkdir()
    shutil.copyfile(ROW, d / "F-001.json")
    return d


def _run(fdir, client, today):
    return rr.resolve_row(fdir / "F-001.json", client, today=today, roots_log=fdir.parent / "roots.jsonl")


def test_resolver_waiting_writes_nothing(fdir, capsys):
    out = _run(fdir, FakeClient(), date(2026, 10, 1))
    assert out["action"] == "WAITING" and out["next_expected"] == "2026-11-20"
    assert not (fdir / "F-001.resolutions.jsonl").exists()
    assert "WAITING" in capsys.readouterr().out


def test_resolver_appends_never_overwrites(fdir):
    log = fdir / "F-001.resolutions.jsonl"
    log.write_text(json.dumps({"stage": "EARLIER", "verdict": "X"}) + "\n", encoding="utf-8")
    first = log.read_bytes()
    c = FakeClient(released={"26.0.10"}, events=[_ev(1, 20), _ev(2, 10, adm="Sud Kivu province"),
                                                 _ev(3, 99, adm="Ituri province"),
                                                 _ev(4, 99, day="2026-09-30")])
    out = _run(fdir, c, date(2026, 11, 22))
    assert out["action"] == "RESOLVED"
    assert log.read_bytes().startswith(first), "an earlier resolution was rewritten"
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert (rec["stage"], rec["release_id"], rec["value"], rec["verdict"], rec["events_count"]) == (
        "PROVISIONAL", "26.0.10", 30.0, "NOT_KEPT", 2)
    for k in ("source", "as_of", "computed_at", "request_count", "filter"):
        assert k in rec, k
    assert rec["filter"] == json.loads(ROW.read_text(encoding="utf-8"))["condition"]


def test_resolver_kept_below_the_threshold(fdir):
    out = _run(fdir, FakeClient(released={"26.0.10"}, events=[_ev(1, 24)]), date(2026, 11, 22))
    assert out["appended"]["verdict"] == "KEPT" and out["appended"]["value"] == 24.0


def test_resolver_source_late(fdir):
    out = _run(fdir, FakeClient(), date(2027, 1, 2))
    assert out["action"] == "SOURCE_LATE"
    rec = json.loads((fdir / "F-001.resolutions.jsonl").read_text(encoding="utf-8"))
    assert (rec["stage"], rec["verdict"]) == ("PROVISIONAL", "SOURCE_LATE")


def test_resolver_not_applicable_coverage(fdir, monkeypatch):
    monkeypatch.setattr(rr, "stage_version", lambda row, stage: "26.0.9")
    out = _run(fdir, FakeClient(released={"26.0.9"}), date(2026, 11, 22))
    assert out["action"] == "NOT_APPLICABLE"
    rec = json.loads((fdir / "F-001.resolutions.jsonl").read_text(encoding="utf-8"))
    assert rec["verdict"] == "NOT_APPLICABLE" and "2026-10" in rec["reason"]


def test_resolver_rf7_filter_mismatch_refused(fdir):
    from experiments.institution import forward_witness as fw
    row = json.loads((fdir / "F-001.json").read_text(encoding="utf-8"))
    good = {"stage": "PROVISIONAL", "filter": row["condition"]}
    bad = {"stage": "PROVISIONAL", "filter": dict(row["condition"], adm_1=["Nord Kivu province"])}
    assert fw.rf7_facts(row, good)["filter_sha256"] == fw.rf7_facts(row, good)["condition_sha256"]
    f = fw.rf7_facts(row, bad)
    assert fw.python_reference("RF7", f) is False
    assert fw.python_reference("RF7", None) is None, "no resolution -> not evaluated -> refuse"


def test_resolver_no_network_in_tests(fdir):
    """Rule: under the conftest guard (closed local port, counter in tmp) the resolver
    must fail closed - ERROR, nothing written - asserted below."""
    assert uc.API_BASE.startswith("http://127.0.0.1:9/")
    out = rr.resolve_row(fdir / "F-001.json", rr.UcdpClient(), today=date(2026, 11, 22),
                         roots_log=fdir.parent / "roots.jsonl")
    assert out["action"] == "ERROR"
    assert not (fdir / "F-001.resolutions.jsonl").exists()


# ── the resolution form of the passage class (Emil, 26 Sep 2026) ─────────────

from core import notary, passage_rules, prereg_gate as pg  # noqa: E402

CLS = passage_rules.load(strict=True)["classes"]["human_signed_preregistration"]
PASS = {"verdict": "PASS", "why": "", "engines_agree": True, "contradictions": [],
        "not_evaluated": [], "hyperon": {"ok": True, "version": "t"}}


@pytest.fixture
def resolved(fdir, monkeypatch):
    shutil.copyfile(ROW.parent / "F-001.seal.json", fdir / "F-001.seal.json")
    roots = fdir.parent / "roots.jsonl"
    c = FakeClient(released={"26.0.10"}, events=[_ev(1, 20), _ev(2, 10, adm="Sud Kivu province")])
    out = rr.resolve_row(fdir / "F-001.json", c, today=date(2026, 11, 22), roots_log=roots)
    assert out["action"] == "RESOLVED"
    real = pg.applies
    monkeypatch.setattr(pg, "applies", lambda cls, step, target:
                        real(cls, step, target) or (step == cls["step"] and Path(str(target)).parent.name == "forward"))
    root = json.loads((fdir / "F-001.seal.json").read_text(encoding="utf-8"))["root"]
    return {"log": fdir / "F-001.resolutions.jsonl", "roots": roots, "root": root, "fdir": fdir}


def _geval(w, prev=None, witness=PASS):
    return pg.evaluate(CLS, "github_publish", w["log"], w["root"] if prev is None else prev,
                       witness=witness, roots_log=w["roots"])


def _failed(g):
    return {n for n, _ in g["failed"]}


def _rewrite_last(log, **change):
    lines = log.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[-1]); rec.update(change)
    for k, v in list(change.items()):
        if v is None:
            rec.pop(k)
    lines[-1] = json.dumps(rec, ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_computed_resolution_passes_all_checks_without_a_signature(resolved):
    g = _geval(resolved)
    assert g["ok"] is True and g["form"] == "resolution", g
    assert [n for n, _ in g["passed"]] == ["source", "release_id", "metta", "unevaluated", "seal", "prev_step"]
    assert "signature" not in {n for n, _ in pg.CHECKS_RESOLUTION}, "a resolution needs no human signature"


def test_res_source_refuses_another_source_or_a_missing_field(resolved):
    _rewrite_last(resolved["log"], source="UCDP something else")
    assert "source" in _failed(_geval(resolved))
    _rewrite_last(resolved["log"], source=json.loads(ROW.read_text(encoding="utf-8"))["resolution"]["provisional"]["source"],
                  events_count=None)
    assert "source" in _failed(_geval(resolved))


def test_res_release_id_refuses_an_unrecorded_release(resolved):
    _rewrite_last(resolved["log"], release_id=None)
    assert "release_id" in _failed(_geval(resolved))


def test_res_metta_refuses_an_rf7_contradiction(resolved):
    w = dict(PASS, verdict="REFUSE", why="contradicted: RF7", contradictions=["RF7"])
    assert "metta" in _failed(_geval(resolved, witness=w))


def test_res_unevaluated_refuses_a_silent_engine(resolved):
    w = dict(PASS, hyperon={"ok": False, "error": "sidecar absent"})
    assert "unevaluated" in _failed(_geval(resolved, witness=w))


def test_res_seal_refuses_an_edited_resolutions_file(resolved):
    b = bytearray(resolved["log"].read_bytes())
    b[b.index(b"NOT_KEPT")] = ord("M")
    resolved["log"].write_bytes(bytes(b))
    assert "seal" in _failed(_geval(resolved))


def test_res_prev_step_must_be_the_rows_merkle_root(resolved):
    assert "prev_step" in _failed(_geval(resolved, prev=notary.PREV_NONE))
    assert "prev_step" in _failed(_geval(resolved, prev="0" * 64))


def test_the_real_witness_in_resolution_mode_passes_rf1_to_rf7(resolved):
    from experiments.institution import forward_witness as fw
    if not all((uc.DATA_DIR / n).exists() for n, _u, _k in uc.SOURCES) or not fw.SIDECAR_PY.exists():
        pytest.skip("UCDP release files or the MeTTa sidecar are not on this machine")
    sigs = resolved["fdir"].parent / "sigs.jsonl"
    import hashlib
    sha = hashlib.sha256((resolved["fdir"] / "F-001.json").read_bytes()).hexdigest()
    sigs.write_text(json.dumps({"signer": "Emil", "channel": "telegram", "date": "2026-09-25",
                                "row_id": "F-001", "row_sha256": sha}) + "\n", encoding="utf-8")
    res = json.loads(resolved["log"].read_text(encoding="utf-8").splitlines()[-1])
    w = fw.witness("F-001", write=False, mode="resolution", resolution=res,
                   forward_dir=resolved["fdir"], signatures=sigs)
    assert w["verdict"] == "PASS", w["why"]
    assert w["rules"]["RF7"]["python"] is True and w["rules"]["RF7"]["hyperon"] is True
    bad = dict(res, filter=dict(res["filter"], adm_1=["Nord Kivu province"]))
    w2 = fw.witness("F-001", write=False, mode="resolution", resolution=bad,
                    forward_dir=resolved["fdir"], signatures=sigs)
    assert w2["verdict"] == "REFUSE" and "RF7" in w2["contradictions"]


def test_whole_country_needs_a_country():
    from experiments.institution import forward_rows as fr
    c = {"type_of_violence": 1, "dyad_new_id": 18621, "adm_1": "ALL"}
    with pytest.raises(ValueError):
        fr.matches({"type_of_violence": "1", "dyad_new_id": "18621", "country": "Sudan", "adm_1": "x"}, c)
    c["country"] = "Sudan"
    assert fr.matches({"type_of_violence": "1", "dyad_new_id": "18621", "country": "Sudan", "adm_1": None}, c)
    assert not fr.matches({"type_of_violence": "1", "dyad_new_id": "18621", "country": "Chad", "adm_1": None}, c)
