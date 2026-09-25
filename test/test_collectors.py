"""
test/test_collectors.py — task #8 B.B: collectors before the spine, read through a manifest.

What a refusal looks like here: a collector that failed, ran out of budget, or asked
a model and got no answer is written UNVERIFIED WITH a reason. The forbidden
fallback is an entry with no level (unknown origin) or an UNVERIFIED with a blank
reason, and validate() must refuse both.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import collectors_runner as cr
import supervisor as sup
from core import collectors_manifest as cm

NOW = datetime(2026, 9, 26, 2, 30, tzinfo=timezone.utc)


# ── the three levels ─────────────────────────────────────────────────────────

def test_a_failed_collector_is_unverified_with_its_reason():
    lvl, why = cm.level_for("timeout", {"ok": 3})
    assert lvl == cm.UNVERIFIED and "timeout" in why


def test_a_collector_whose_model_never_answered_is_unverified_not_model_answered():
    lvl, why = cm.level_for("ok", {"ok": 0, "refused": 4, "error": 1,
                                   "reasons": ["warm core absent"]})
    assert lvl == cm.UNVERIFIED
    assert "4 refused" in why and "warm core absent" in why


def test_one_answer_is_model_answered_and_no_call_is_no_model_call():
    assert cm.level_for("ok", {"ok": 1, "refused": 9})[0] == cm.MODEL_ANSWERED
    assert cm.level_for("ok", {}) == (cm.NO_MODEL_CALL, None)


def test_model_calls_counts_only_this_step_since_the_start(tmp_path):
    prov = tmp_path / "prov.jsonl"
    rows = [
        {"ts": "2026-09-26T02:31:00+00:00", "step": "web_intelligence", "outcome": "refused",
         "error": "warm core absent"},
        {"ts": "2026-09-26T02:32:00+00:00", "step": "web_intelligence", "outcome": "ok"},
        {"ts": "2026-09-26T02:29:00+00:00", "step": "web_intelligence", "outcome": "ok"},
        {"ts": "2026-09-26T02:33:00+00:00", "step": "data_scout", "outcome": "ok"},
    ]
    prov.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    c = cm.model_calls("web_intelligence", NOW, prov)
    assert (c["ok"], c["refused"], c["error"]) == (1, 1, 0)


# ── the spine's reading ──────────────────────────────────────────────────────

def _manifest(tmp_path, entry: dict, name="web_intelligence"):
    d = tmp_path / "memory" / "collectors"
    d.mkdir(parents=True)
    p = d / "manifest_latest.json"
    p.write_text(json.dumps({"collector_run_id": "x", "collectors": {name: entry}}),
                 encoding="utf-8")
    return p


def _good(**kw):
    e = {"level": cm.MODEL_ANSWERED, "fetched_at": (NOW - timedelta(hours=1)).isoformat(),
         "outputs": []}
    e.update(kw)
    return e


def test_validate_accepts_a_good_entry(tmp_path):
    v = cm.validate("web_intelligence", NOW, _manifest(tmp_path, _good()))
    assert v["ok"] and v["problems"] == [] and v["age_h"] == 1.0


def test_validate_refuses_a_missing_manifest(tmp_path):
    v = cm.validate("web_intelligence", NOW, tmp_path / "nope.json")
    assert not v["ok"] and "never ran" in v["problems"][0]


def test_validate_refuses_an_unknown_origin(tmp_path):
    v = cm.validate("web_intelligence", NOW, _manifest(tmp_path, _good(level=None)))
    assert not v["ok"] and any("unknown origin" in p for p in v["problems"])


def test_validate_refuses_unverified_without_a_reason(tmp_path):
    v = cm.validate("web_intelligence", NOW, _manifest(tmp_path, _good(level=cm.UNVERIFIED)))
    assert not v["ok"] and any("without a reason" in p for p in v["problems"])


def test_validate_refuses_a_stale_or_undated_entry(tmp_path):
    old = _good(fetched_at=(NOW - timedelta(hours=30)).isoformat())
    assert any("stale" in p for p in cm.validate("web_intelligence", NOW,
                                                 _manifest(tmp_path, old))["problems"])
    v = cm.validate("web_intelligence", NOW, _manifest(tmp_path / "b", _good(fetched_at=None)))
    assert any("no observation date" in p for p in v["problems"])


def test_validate_refuses_an_entry_whose_outputs_are_gone(tmp_path):
    v = cm.validate("web_intelligence", NOW,
                    _manifest(tmp_path, _good(outputs=["memory/web_intelligence/x.json"])))
    assert not v["ok"] and any("missing" in p for p in v["problems"])


# ── the runner ───────────────────────────────────────────────────────────────

def test_run_writes_one_manifest_and_a_raising_collector_is_unverified(tmp_path):
    def wi(env):
        assert env["CORTEX_IN_CYCLE"]            # the core only, no loads
        out = tmp_path / "memory" / "web_intelligence" / "2026-09-26" / "a.json"
        out.parent.mkdir(parents=True)
        out.write_text("{}", encoding="utf-8")
        return "ok", ""

    def ds(env):
        raise RuntimeError("scout broke")

    m = cr.run("2026-09-26T02:00:00+03:00", runners={"web_intelligence": wi, "data_scout": ds},
               base=tmp_path, provenance=tmp_path / "none.jsonl")
    w, d = m["collectors"]["web_intelligence"], m["collectors"]["data_scout"]
    assert w["level"] == cm.NO_MODEL_CALL
    assert w["outputs"] == ["memory/web_intelligence/2026-09-26/a.json"]
    assert d["level"] == cm.UNVERIFIED and d["reason"] and "scout broke" in d["detail"]
    on_disk = json.loads((tmp_path / "memory" / "collectors" / "manifest_latest.json")
                         .read_text(encoding="utf-8"))
    assert on_disk == m
    assert (tmp_path / "memory" / "collectors" / "2026-09-26" / "manifest.json").exists()


# ── the supervisor: collectors -> spine ──────────────────────────────────────

CFG = {"daily_hour": 3, "catchup_grace_hours": 20}


def _local(h, m=0):
    return datetime(2026, 9, 26, h, m).astimezone()


def test_collectors_start_an_hour_before_the_spine():
    a = sup.decide(_local(2, 5), {}, None, None, CFG, collectors=None)
    assert a.kind == sup.COLLECTORS_START
    assert sup.decide(_local(1, 55), {}, None, None, CFG, collectors=None).kind == sup.NOTHING


def test_the_spine_waits_for_running_collectors_and_starts_after_them():
    assert sup.decide(_local(3, 2), {}, None, None, CFG, collectors="running").kind == sup.NOTHING
    assert sup.decide(_local(3, 2), {}, None, None, CFG, collectors="done").kind == sup.START


def test_collectors_state_reads_the_witness_and_gives_up_waiting(monkeypatch):
    now = datetime.now().astimezone()
    today = now.date().isoformat()
    fresh = {"date": today, "witness_id": "w#collectors", "pid": 42,
             "utc": datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(sup, "witness_exit_for", lambda cid: None)
    assert sup._collectors_state({}, now) is None
    assert sup._collectors_state({"collectors": dict(fresh, date="2000-01-01")}, now) is None
    assert sup._collectors_state({"collectors": fresh}, now) == "running"
    old = dict(fresh, utc=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
    assert sup._collectors_state({"collectors": old}, now) == "done"
    monkeypatch.setattr(sup, "witness_exit_for", lambda cid: {"event": "exit"})
    assert sup._collectors_state({"collectors": fresh}, now) == "done"
