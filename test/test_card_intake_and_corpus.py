# -*- coding: utf-8 -*-
"""test/test_card_intake_and_corpus.py — the bridge and the corpus (10 Sep 2026). Failure paths first."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import card_intake as ci  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("verified_corpus", REPO / "training" / "verified_corpus.py")
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)

PAGES = {
    "https://usgs/count": '{"count":38,"maxAllowed":20000}',
    "https://noaa/monthly": "<td>September 09:</td><td>426.62 ppm</td><td>September 07:</td><td>Unavailable</td>",
}
CARD_OK = {"card": 5, "axis": "DEEP_TIME_RISKS_REVIEW", "key": "usgs_m5plus_7d_count", "value": 38, "unit": "events",
           "url": "https://usgs/count", "quote": '"count": 38', "observed_date": "2026-09-10"}
CARD_INVENTED = {"card": 1, "axis": "CLIMATE_GLOBAL_RISK_REVIEW", "key": "co2_ppm_mauna_loa", "value": 426.99, "unit": "ppm",
                 "url": "https://noaa/monthly", "quote": "September 10:   426.99 ppm", "observed_date": "2026-09-10"}
CARD_NULL = {"card": 2, "axis": "CLIMATE_GLOBAL_RISK_REVIEW", "key": "co2_ppm_mauna_loa", "value": None, "unit": "ppm",
             "url": "https://noaa/monthly", "reason": "September 07: Unavailable", "quote": "September 07: Unavailable"}
CARD_AGENT_REFUSED = {"card": 3, "refused": True, "reason": ".env lies outside this workspace"}
CARD_UNREACHABLE = dict(CARD_OK, card=9, url="https://down/")


def _fetch(url):
    return PAGES.get(url)


def _setup(tmp_path):
    inbox = tmp_path / "cards"; inbox.mkdir()
    (inbox / "a.jsonl").write_text("\n".join(json.dumps(c) for c in
                                             (CARD_OK, CARD_INVENTED, CARD_NULL, CARD_AGENT_REFUSED, CARD_UNREACHABLE)) + "\n",
                                   encoding="utf-8")
    return inbox, tmp_path / "acc.jsonl", tmp_path / "ref.jsonl"


def test_only_the_world_confirmed_enters_accepted(tmp_path):
    inbox, acc, ref = _setup(tmp_path)
    c = ci.judge_inbox(inbox, fetch=_fetch, accepted_path=acc, refused_path=ref)
    assert c == {"accepted": 1, "null_with_reason": 1, "refused": 2, "self_report": 0, "open": 1, "skipped": 0}
    accepted = [json.loads(l) for l in acc.read_text().splitlines()]
    assert {a["record"]["card"] for a in accepted} == {5, 2}
    refused = [json.loads(l) for l in ref.read_text().splitlines()]
    assert {r["verdict"] for r in refused} == {"QUOTE_NOT_ON_PAGE", "AGENT_REFUSED"}


def test_unreachable_is_open_and_retried_never_accepted(tmp_path):
    inbox, acc, ref = _setup(tmp_path)
    ci.judge_inbox(inbox, fetch=_fetch, accepted_path=acc, refused_path=ref)
    c2 = ci.judge_inbox(inbox, fetch=_fetch, accepted_path=acc, refused_path=ref)
    assert c2["open"] == 1 and c2["skipped"] == 4 and c2["accepted"] == 0


def test_dry_run_writes_nothing(tmp_path):
    inbox, acc, ref = _setup(tmp_path)
    ci.judge_inbox(inbox, fetch=_fetch, dry=True, accepted_path=acc, refused_path=ref)
    assert not acc.exists() and not ref.exists()


def test_corpus_negative_control_shape_without_verdict_is_refused():
    looks_verified = {"record": CARD_OK, "card_key": "x", "page_sha256": "y"}     # no verdict
    assert vc.rows_from_observations([looks_verified]) == []
    wrong_verdict = dict(looks_verified, verdict="QUOTE_NOT_ON_PAGE")
    assert vc.rows_from_observations([wrong_verdict]) == []


def test_corpus_takes_only_scored_nondegenerate_predictions():
    sealed = {"event": "PREDICTION_SEALED", "hash": "h1", "target_kind": "self_failure", "learner": 0.9, "baseline": 0.5, "ts": "t"}
    degen = {"event": "PREDICTION_SEALED", "hash": "h2", "target_kind": "axis_next", "learner": 50.0, "baseline": 50.0, "degenerate": True, "ts": "t"}
    unscored = {"event": "PREDICTION_SEALED", "hash": "h3", "target_kind": "self_failure", "learner": 0.8, "baseline": 0.5, "ts": "t"}
    outs = [{"event": "OUTCOME_SCORED", "ref_hash": "h1", "actual": 1, "learner_err": 0.1, "baseline_err": 0.5, "hash": "o1", "ts": "t2"},
            {"event": "OUTCOME_SCORED", "ref_hash": "h2", "actual": 50.0, "learner_err": 0, "baseline_err": 0, "hash": "o2", "ts": "t2"}]
    rows = vc.rows_from_ledger([sealed, degen, unscored] + outs)
    assert len(rows) == 1 and rows[0]["provenance"]["sealed_hash"] == "h1"


def test_corpus_rows_carry_provenance_to_the_world(tmp_path):
    inbox, acc, ref = _setup(tmp_path)
    ci.judge_inbox(inbox, fetch=_fetch, accepted_path=acc, refused_path=ref)
    obs = [json.loads(l) for l in acc.read_text().splitlines()]
    rows = vc.rows_from_observations(obs)
    assert len(rows) == 2 and all(r["provenance"]["verdict"] in ("ACCEPTED", "NULL_WITH_REASON") for r in rows)
    assert any(r["provenance"]["page_sha256"] for r in rows)
