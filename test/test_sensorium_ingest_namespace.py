# -*- coding: utf-8 -*-
"""
Regression for the sensorium ingest crash of 16 Aug - 3 Sep 2026.

core/source_trust.commit_sections() drops one audit leaf per global_indicators section
under the namespace axis "indicators/<section>". ingest() routed it like an axis drop,
tried to write memory/browse_sources/indicators/co2.json into a directory that did not
exist, raised FileNotFoundError BEFORE writing the consumed-set, and so every night
re-crashed on the same leaf. Nothing was ingested for 18 nights, including the real
goal_impact drops that sat behind it.

Hermetic: every path the module writes is redirected to tmp_path. No live state is read
or written (conftest's _no_live_writes would catch it otherwise).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import experiments.sensorium.sensorium as S


def _leaf(axis, kind, path, i):
    return {"id": f"{axis}/{i}", "leaf": "0" * 64, "path": path, "axis": axis,
            "kind": kind, "ts": f"2026-09-03T00:00:0{i}+00:00", "collector": "t"}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    repo = tmp_path
    sens = repo / "memory" / "sensorium"
    sens.mkdir(parents=True)
    monkeypatch.setattr(S, "REPO", repo)
    monkeypatch.setattr(S, "SENS_DIR", sens)
    monkeypatch.setattr(S, "LEAVES", sens / "_merkle_leaves.jsonl")
    monkeypatch.setattr(S, "ROOT_FILE", sens / "_merkle_root.json")
    monkeypatch.setattr(S, "CONSUMED", sens / "_consumed.json")
    monkeypatch.setattr(S, "COMPOSER_IN", repo / "memory" / "browse_sources")
    monkeypatch.setattr(S, "SEMANTIC_IN", repo / "memory" / "semantic_inbox")
    monkeypatch.setattr(S, "GOALIMP_IN", repo / "memory" / "goal_impact_inbox")
    monkeypatch.setattr(S, "DEAD_LETTER", sens / "_dead_letter.jsonl")
    return repo


def _write_drop(repo: Path, rel: str, payload: dict):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"payload": payload, "ts": "2026-09-03T00:00:00+00:00"}),
                 encoding="utf-8")


def test_namespace_axis_is_audit_only():
    assert S._is_namespace_axis("indicators/co2")
    assert S._is_namespace_axis("indicator/gini")
    assert not S._is_namespace_axis("WATER_REVIEW")
    assert not S._is_namespace_axis(None)


def test_audit_leaf_does_not_crash_and_real_drop_behind_it_is_routed(sandbox):
    repo = sandbox
    # the exact shape that crashed: a numeric leaf whose axis is a path
    _write_drop(repo, "memory/sensorium/indicators/co2/a.json",
                {"section": "co2", "n_values": 3, "values": {"ppm": 426.9}})
    # a real goal_impact drop that was starved behind it for 18 nights
    _write_drop(repo, "memory/sensorium/ECONOMY_WORK_REVIEW/b.json",
                {"overall_signed_weighted": 0.12, "n": 4, "data_date": "2026-09-01"})
    leaves = [_leaf("indicators/co2", "numeric", "memory/sensorium/indicators/co2/a.json", 1),
              _leaf("ECONOMY_WORK_REVIEW", "goal_impact",
                    "memory/sensorium/ECONOMY_WORK_REVIEW/b.json", 2)]
    S.LEAVES.write_text("\n".join(json.dumps(l) for l in leaves) + "\n", encoding="utf-8")

    out = S.ingest()                      # must not raise

    assert out["audit_only"] == 1
    assert out["ingested"] == 1
    assert "ECONOMY_WORK_REVIEW" in out["axes"]
    # the audit leaf was NOT given a destination under browse_sources/
    assert not (S.COMPOSER_IN / "indicators").exists()
    # the real drop reached both consumers
    scalar = json.loads((S.COMPOSER_IN / "ECONOMY_WORK_REVIEW.json").read_text("utf-8"))
    assert scalar["value"] == 0.12 and scalar["metric"] == "goal_impact_signed_weighted"
    assert (S.GOALIMP_IN / "ECONOMY_WORK_REVIEW.json").is_file()
    # BOTH leaves are consumed: the crash used to leave the set unwritten
    consumed = set(json.loads(S.CONSUMED.read_text("utf-8"))["ids"])
    assert consumed == {"indicators/co2/1", "ECONOMY_WORK_REVIEW/2"}


def test_second_run_is_a_no_op(sandbox):
    repo = sandbox
    _write_drop(repo, "memory/sensorium/indicators/food/a.json", {"section": "food"})
    S.LEAVES.write_text(json.dumps(_leaf("indicators/food", "numeric",
                                         "memory/sensorium/indicators/food/a.json", 1)) + "\n",
                        encoding="utf-8")
    first = S.ingest()
    second = S.ingest()
    assert first["audit_only"] == 1
    assert second == {"ingested": 0, "axes": {}, "audit_only": 0, "dead_letter": 0}


def test_numeric_write_creates_the_file_parent_not_just_the_root(sandbox):
    """Defence in depth: even a routable axis that somehow carries a subdirectory
    must not raise — the parent of the FILE is created, not only the inbox root."""
    repo = sandbox
    _write_drop(repo, "memory/sensorium/x/a.json", {"metric": "m", "value": 1})
    S.LEAVES.write_text(json.dumps(_leaf("PLAIN_AXIS", "numeric",
                                         "memory/sensorium/x/a.json", 1)) + "\n",
                        encoding="utf-8")
    out = S.ingest()
    assert out["ingested"] == 1
    assert (S.COMPOSER_IN / "PLAIN_AXIS.json").is_file()


def test_explicit_audit_kind_is_recognised_without_a_path_axis(sandbox):
    """Kimi, 3 Sep: the schema must carry the semantics. kind="audit" wins even when the
    axis looks like a real one."""
    repo = sandbox
    _write_drop(repo, "memory/sensorium/a.json", {"section": "x"})
    S.LEAVES.write_text(json.dumps(_leaf("WATER_REVIEW", "audit", "memory/sensorium/a.json", 1))
                        + "\n", encoding="utf-8")
    out = S.ingest()
    assert out["audit_only"] == 1 and out["ingested"] == 0
    assert not (S.COMPOSER_IN / "WATER_REVIEW.json").exists()


def test_drop_accepts_audit_kind(sandbox, monkeypatch):
    monkeypatch.setattr(S, "PENUMBRA_DIR", sandbox / "memory" / "penumbra")
    monkeypatch.setattr(S, "PENUMBRA_LEAVES", sandbox / "memory" / "penumbra" / "_penumbra_leaves.jsonl")
    monkeypatch.setattr(S, "PENUMBRA_ROOT", sandbox / "memory" / "penumbra" / "_penumbra_root.json")
    did = S.drop("indicators/co2", "audit", {"section": "co2", "n_values": 1}, collector="t")
    leaves = S._read_leaves(S.LEAVES)
    assert leaves[-1]["id"] == did and leaves[-1]["kind"] == "audit"


def test_a_leaf_that_cannot_be_routed_is_dead_lettered_not_fatal(sandbox, monkeypatch):
    repo = sandbox
    _write_drop(repo, "memory/sensorium/ok/a.json", {"metric": "m", "value": 1})
    _write_drop(repo, "memory/sensorium/bad/b.json", {"metric": "m", "value": 2})
    S.LEAVES.write_text("\n".join([
        json.dumps(_leaf("GOOD_AXIS", "numeric", "memory/sensorium/ok/a.json", 1)),
        json.dumps(_leaf("BAD_AXIS", "numeric", "memory/sensorium/bad/b.json", 2))]) + "\n",
        encoding="utf-8")
    real = S._route_one

    def boom(axis, kind, lf, out):
        if axis == "BAD_AXIS":
            raise OSError("disk says no")
        return real(axis, kind, lf, out)

    monkeypatch.setattr(S, "_route_one", boom)
    monkeypatch.setattr(S, "DEAD_LETTER", S.SENS_DIR / "_dead_letter.jsonl")
    out = S.ingest()
    assert out["ingested"] == 1 and out["dead_letter"] == 1
    rows = [json.loads(l) for l in S.DEAD_LETTER.read_text("utf-8").splitlines()]
    assert rows[0]["id"] == "BAD_AXIS/2" and "disk says no" in rows[0]["error"]
    # both consumed: the bad one is in the queue, not in tomorrow's crash
    consumed = set(json.loads(S.CONSUMED.read_text("utf-8"))["ids"])
    assert consumed == {"GOOD_AXIS/1", "BAD_AXIS/2"}
