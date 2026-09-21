# -*- coding: utf-8 -*-
"""
test/test_openclaw_wire_to_the_gate.py — the worker's output IS the gate's input.

WHAT WAS WRONG (verified 20 September 2026, with tools/ask.py, not with a grep)
------------------------------------------------------------------------------
scripts/openclaw_axis_worker.py wrote openclaw_queue/external_feeds.jsonl,
external_shadow.jsonl and external_refusals.jsonl. Asked who reads them:

    readers openclaw_queue/external_feeds.jsonl
      -> scripts/openclaw_axis_worker.py:277   (its own _peer_for)
    readers openclaw_queue/external_shadow.jsonl
      -> test/test_openclaw_axis_worker.py
    readers openclaw_queue/external_refusals.jsonl
      -> test/test_openclaw_axis_worker.py

core.card_intake.judge_inbox globs openclaw_queue/cards/*.jsonl and writes what
the quote gate ACCEPTS into memory/verified_observations.jsonl, which four
modules read. Different files. The worker's numbers never reached the gate, and
its three outputs carried one run, 20 Aug 21:19 UTC, a month old.

WHY THE TWO HALVES ARE TESTED TOGETHER HERE, AND THAT IS THE POINT
------------------------------------------------------------------
Both halves were green, separately, for a month, while the pipeline delivered
nothing. test/test_openclaw_axis_worker.py proves fetch_one produces a row;
test/test_quote_gate.py proves judge() accepts a well-formed card. Neither could
notice that fetch_one returned no `quote` at all, so every row it produced would
have been judged MALFORMED the moment the two were connected.

So the load-bearing test below takes ONE recorded raw body, runs fetch_one
against it, and hands the resulting card to quote_gate.judge against THAT SAME
body. A pass means the gate accepted a card this worker actually built, out of
bytes a server actually sent.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import card_intake as ci        # noqa: E402
from core import quote_gate as qg         # noqa: E402
from scripts import openclaw_axis_worker as W   # noqa: E402

# A FIXTURE, and said plainly rather than called a recording: this is a body in
# the shape config/openclaw_sources.json's `path: "count"` resolves against, and
# it is COMPACT on purpose. No space after the colon is the case a naive quote
# gets wrong, and no test here may fetch, so the body is written down instead of
# captured. The two forms below are the two the gate must handle.
USGS_BODY = '{"count":38,"maxAllowed":20000}'
SPACED_BODY = '{"count": 38, "maxAllowed": 20000}'

SOURCE = {"id": "usgs_quakes_m45_24h", "axis": "DEEP_TIME_RISKS_REVIEW",
          "key": "quakes_m45_last_24h", "path": "count", "unit": "events_24h",
          "org": "USGS", "url": "https://earthquake.usgs.gov/fdsnws/event/1/count"}


def _getter(body: str, status: int = 200):
    """A getter in the four-value form: the raw text comes back with the parse."""
    def _get(url, timeout):
        return status, json.loads(body), None, body
    return _get


# ── THE TEST THAT MATTERS ───────────────────────────────────────────────────

@pytest.mark.parametrize("body", [USGS_BODY, SPACED_BODY], ids=["compact", "spaced"])
def test_a_card_the_worker_built_is_accepted_by_the_gate_against_the_same_body(body):
    """The two halves, in one test, over one body. This is the whole change."""
    row = W.fetch_one(SOURCE, timeout=5, getter=_getter(body))
    card = W.card_from_row(row)
    assert card is not None, f"no card: {row.get('quote_missing')}"

    verdict = qg.judge(card, body)
    assert verdict["verdict"] == "ACCEPTED", (
        f"the gate refused a card this worker built: {verdict} / card={card}")
    assert verdict["value"] == 38.0


def test_the_quote_is_cut_from_the_body_and_not_rebuilt_from_the_parsed_value():
    """THE FORBIDDEN SHORTCUT, named and tested.

    A quote assembled from the number we already parsed would be found on the
    page every time, and the gate would be checking that a string is a string.
    The quote must be a literal substring of the bytes the server sent, so a
    body whose number is written in a notation we cannot quote verbatim yields
    NO card rather than a manufactured one."""
    row = W.fetch_one(SOURCE, timeout=5, getter=_getter(USGS_BODY))
    assert row["quote"] in USGS_BODY, (
        f"{row['quote']!r} is not a substring of the body it claims to quote")

    # 38 written as 3.8e1: parses to the same number, appears nowhere as "38"
    exotic = '{"count":3.8e1,"maxAllowed":20000}'
    row2 = W.fetch_one(SOURCE, timeout=5, getter=_getter(exotic))
    assert row2["value"] == 38.0
    assert row2["quote"] is None, (
        f"a quote was produced for a value the body never spells: {row2['quote']!r}")
    assert W.card_from_row(row2) is None
    assert "verbatim" in row2["quote_missing"]


def test_a_number_inside_a_longer_number_is_not_a_quote():
    """FOUND IN THE FIRST LIVE RUN, 20 Sep 2026, before card_intake ever saw it.

    The worker quoted "46.0016162, 169.0727185], [-46.0009526, 169.076" as
    evidence that there were 46 floods. That is a LATITUDE. The guard rejected a
    digit either side of the match and nothing else, so "46" followed by a dot
    passed — and the quote was genuinely on the page, which is what makes this
    the dangerous shape: the gate would have ACCEPTED it and a coordinate would
    have entered memory/verified_observations.jsonl as a flood count."""
    body = '{"events":[{"geometry":[{"coordinates":[46.0016162, 169.0727185]}]}]}'
    assert W.quote_from_body(body, 46.0) is None
    assert W.quote_from_body('{"a":1.2,"b":9}', 2.0) is None, (
        "the 2 of 1.2 is not a standalone 2")


def test_a_counted_value_is_never_quoted():
    """'#len' does not read a number off the body — it counts the body's own
    structure. The number appears nowhere in the bytes, so every match is an
    accident of decimal digits, and the honest answer is no card.

    celestrak escaped this on the live run only because no '250' happened to be
    in its 105 KB of orbital elements. Three EONET counts did not escape it."""
    body = '{"events":[{"id":"a"},{"id":"b"}]}'

    def getter(url, timeout):
        return 200, json.loads(body), None, body

    src = dict(SOURCE, path="events.#len")
    row = W.fetch_one(src, timeout=5, getter=getter)
    assert row["value"] == 2.0
    assert row["quote"] is None
    assert "COUNTED from the body's structure" in row["quote_missing"]
    assert W.card_from_row(row) is None


def test_the_worker_never_emits_a_quote_the_gate_would_refuse():
    """The last guard, asked through the gate's own regex rather than a copy of
    it: whatever quote comes back must satisfy the very test judge() applies."""
    for body, value in (('{"count":38,"maxAllowed":20000}', 38.0),
                        ('{"count": 38, "maxAllowed": 20000}', 38.0),
                        ('{"current":{"time":"2026-09-20T12:15","temperature_2m":27.3}}',
                         27.3)):
        q = W.quote_from_body(body, value)
        assert q is not None, (body, value)
        card = {"axis": "A", "key": "k", "value": value, "unit": "u",
                "url": "https://x/y", "quote": q}
        assert qg.judge(card, body)["verdict"] == "ACCEPTED", (q, body)


def test_a_row_with_no_raw_body_gets_no_card():
    """A getter that hands back only a parsed object leaves nothing to quote.
    The row is still written to the feed; the card is not invented."""
    def three_tuple(url, timeout):
        return 200, {"count": 38}, None
    row = W.fetch_one(SOURCE, timeout=5, getter=three_tuple)
    assert row["value"] == 38.0
    assert row["quote"] is None
    assert W.card_from_row(row) is None
    assert row["quote_missing"] == "no raw response text"


# ── the path, asserted rather than assumed ──────────────────────────────────

def test_the_workers_card_directory_is_the_gates_inbox():
    """The wire itself. If either side moves, this is the test that says so —
    and it compares the two modules' own constants, not two strings written
    twice."""
    assert W.CARDS == ci.INBOX, (
        f"the worker writes cards to {W.CARDS} and the gate reads {ci.INBOX}")


def _run(tmp_path, state, **kw):
    """ISOLATED, the same three redirects test_openclaw_axis_worker.py uses.

    Without them a test fetches the machine's live discovery list and promotes
    or demotes real sources in memory/source_lifecycle_ledger.jsonl — the 16 Aug
    2026 incident, in a new place."""
    return W.run(sources_path=_sources_file(tmp_path), queue_dir=tmp_path,
                 discovered_path=pathlib.Path("does-not-exist.json"),
                 lifecycle_state=state,
                 ledger=tmp_path.parent / "lifecycle_ledger.jsonl", **kw)


def _promote(tmp_path, body=USGS_BODY):
    """A source is a CANDIDATE until PROMOTE_AFTER clean observations, and only
    a TRUSTED source is a measurement. Returns the state and the last result."""
    from core import source_lifecycle as life

    state, res = {}, None
    for _ in range(life.PROMOTE_AFTER + 1):
        res = _run(tmp_path, state, getter=_getter(body))
    return state, res


def test_the_gate_globs_the_name_the_worker_writes(tmp_path):
    """The filename has to be picked up, not merely land in the right folder:
    judge_inbox globs '*.jsonl'."""
    _state, res = _promote(tmp_path)
    assert res["cards"], f"no cards after promotion: {res['lifecycle']}"
    written = sorted(f.name for f in (tmp_path / "cards").glob("*.jsonl"))
    assert written, f"no card file under {tmp_path / 'cards'}"
    assert all(n.endswith("_cards.jsonl") for n in written), written


def test_what_the_worker_wrote_is_what_the_gate_judges(tmp_path):
    """END TO END on disk, through card_intake's own reader rather than a
    re-parse: the file the worker left is globbed, judged against the same body
    and ACCEPTED into the accepted path."""
    _promote(tmp_path)
    accepted = tmp_path / "verified_observations.jsonl"
    refused = tmp_path / "card_refusals.jsonl"
    counts = ci.judge_inbox(inbox=tmp_path / "cards",
                            fetch=lambda url: USGS_BODY,
                            accepted_path=accepted, refused_path=refused)
    assert counts["accepted"] >= 1, (
        f"{counts} — nothing the worker wrote survived the gate; "
        f"refusals: {refused.read_text(encoding='utf-8') if refused.exists() else '(none)'}")
    rows = [json.loads(x) for x in
            accepted.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows and rows[0]["verdict"] == "ACCEPTED"
    assert rows[0]["record"]["key"] == SOURCE["key"]


def _sources_file(tmp_path) -> pathlib.Path:
    p = tmp_path / "sources.json"
    p.write_text(json.dumps({"timeout_sec": 5, "sources": [SOURCE]}),
                 encoding="utf-8")
    return p


# ── the card's identity ─────────────────────────────────────────────────────

def test_the_card_carries_only_the_gate_fields_and_the_observation_date():
    """card_intake._key() hashes the WHOLE record.

    A field that changes between runs while the reading does not gives the same
    measurement a new key every night: the gate re-fetches it, re-judges it and
    re-appends it, and the four readers of memory/verified_observations.jsonl
    count one observation many times. ts and latency_s are exactly such fields
    and they are on the feed row, two lines away."""
    row = W.fetch_one(SOURCE, timeout=5, getter=_getter(USGS_BODY))
    card = W.card_from_row(row)
    assert set(card) <= set(W.CARD_FIELDS) | {"data_date_missing"}, sorted(card)
    for leaky in ("ts", "latency_s", "source_id", "org", "path", "trust",
                  "origin", "measured", "status"):
        assert leaky not in card, f"{leaky} is on the card and changes per run"
    assert set(qg.REQUIRED) <= set(card), (
        f"the card is missing gate fields: {sorted(set(qg.REQUIRED) - set(card))}")


def test_the_same_reading_twice_produces_the_same_card_key():
    """The consequence, asserted through card_intake's own hash rather than
    described. Two runs over the same body must be ONE measurement."""
    a = W.card_from_row(W.fetch_one(SOURCE, timeout=5, getter=_getter(USGS_BODY)))
    b = W.card_from_row(W.fetch_one(SOURCE, timeout=5, getter=_getter(USGS_BODY)))
    assert ci._key(a) == ci._key(b), (
        "the same reading produced two card keys; something that changes per "
        "run is on the card")


def test_a_changed_reading_produces_a_different_card_key():
    """The other half, so the test above is not passing on a constant: a new
    number IS a new observation and must get its own key."""
    a = W.card_from_row(W.fetch_one(SOURCE, timeout=5, getter=_getter(USGS_BODY)))
    b = W.card_from_row(W.fetch_one(
        SOURCE, timeout=5, getter=_getter('{"count":39,"maxAllowed":20000}')))
    assert ci._key(a) != ci._key(b)


# ── the observation date ────────────────────────────────────────────────────

def test_an_absent_observation_date_is_named_and_is_never_today():
    """Today's date is the date of the FETCH, not of the reading. A card that
    carried it would claim a year-old figure was observed this morning."""
    import datetime as _dt

    row = W.fetch_one(SOURCE, timeout=5, getter=_getter(USGS_BODY))
    card = W.card_from_row(row)
    assert card["data_date"] is None
    assert card["data_date_missing"], "the absence is unexplained"
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    assert today not in json.dumps(card), (
        f"the card carries today's date ({today}): {card}")


def test_a_declared_data_date_path_is_read_from_the_payload():
    src = dict(SOURCE, data_date_path="as_of")
    body = '{"count":38,"as_of":"2026-08-03"}'
    row = W.fetch_one(src, timeout=5, getter=_getter(body))
    card = W.card_from_row(row)
    assert card["data_date"] == "2026-08-03"
    assert "data_date_missing" not in card


def test_a_data_date_path_that_does_not_resolve_is_missing_not_invented():
    src = dict(SOURCE, data_date_path="nope.deeper")
    row = W.fetch_one(src, timeout=5, getter=_getter(USGS_BODY))
    assert row["data_date"] is None
    assert "did not resolve" in row["data_date_missing"]


def test_the_spelling_is_the_one_the_registry_already_carries():
    """THE THIRTEENTH SPELLING, NOT A FOURTEENTH. config/field_names.json exists
    because this repo had thirteen names for one concept, each added by a writer
    that picked its own. This card uses a spelling already registered there."""
    reg = json.loads((REPO / "config" / "field_names.json").read_text(encoding="utf-8"))
    known = {e["spelling"]
             for e in reg["concepts"]["OBSERVATION_DATE"]["spellings"]}
    date_fields = [f for f in W.CARD_FIELDS if f not in qg.REQUIRED]
    assert date_fields, "the card carries no observation date at all"
    for f in date_fields:
        assert f in known, (
            f"the card spells the observation date {f!r}, which "
            f"config/field_names.json does not register. Register it there with "
            f"where it is written, or use one of: {sorted(known)}")


# ── shadows and refusals stay where they are ────────────────────────────────

def test_a_shadow_row_never_becomes_a_card(tmp_path):
    """The module's own rule: a candidate's number is stored beside the trusted
    ones and is NOT a measurement. A card is a claim to be filed into
    memory/verified_observations.jsonl, so an untrusted source must not make
    one."""
    res = _run(tmp_path, {}, getter=_getter(USGS_BODY))
    assert res["shadows"] and not res["feeds"], (
        "a first observation should still be a CANDIDATE; the lifecycle moved")
    assert res["cards"] == [], (
        f"{len(res['cards'])} card(s) from {len(res['shadows'])} shadow row(s) "
        f"— an untrusted number would enter memory/verified_observations.jsonl")
    assert not (tmp_path / "cards").exists(), (
        "the card directory was created for a run that produced no cards")

    # ...and once the same source is TRUSTED, the card appears. Without this
    # half the test above passes on a worker that never writes a card at all.
    _state, promoted = _promote(tmp_path)
    assert promoted["feeds"] and len(promoted["cards"]) == len(promoted["feeds"])


# ── a run that starts and never finishes ────────────────────────────────────
# Added 20 Sep 2026 with the schedule. A worker nobody can see stop is the
# defect this repo keeps finding; two rows per run is what makes stopping
# visible, and these are the assertions that keep the second row honest.

def _rows(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def test_a_start_without_a_finish_is_reported_as_unfinished(tmp_path):
    """KNOWN TRUE. This is the whole point of the file: the row that is ABSENT
    is the signal."""
    log = tmp_path / "task_runs.jsonl"
    W._task_row({"task": W.TASK_NAME, "event": "start", "run_id": "aaa",
                 "ts": "2026-09-20T05:50:00+00:00"}, path=log)
    open_runs = W.unfinished_runs(path=log)
    assert [r["run_id"] for r in open_runs] == ["aaa"]


def test_a_finished_run_is_not_reported(tmp_path):
    """KNOWN EMPTY, so the test above is not passing on everything."""
    log = tmp_path / "task_runs.jsonl"
    for ev in ("start", "finish"):
        W._task_row({"task": W.TASK_NAME, "event": ev, "run_id": "bbb",
                     "ts": "2026-09-20T05:50:00+00:00"}, path=log)
    assert W.unfinished_runs(path=log) == []


def test_removing_the_finish_row_makes_the_run_unfinished_again(tmp_path):
    """MUTATION. Delete the second row and the run must reappear as open —
    the net against a reader that decides by counting rows or by trusting the
    last one."""
    log = tmp_path / "task_runs.jsonl"
    for ev in ("start", "finish"):
        W._task_row({"task": W.TASK_NAME, "event": ev, "run_id": "ccc",
                     "ts": "2026-09-20T05:50:00+00:00"}, path=log)
    assert W.unfinished_runs(path=log) == []

    kept = [r for r in _rows(log) if r["event"] != "finish"]
    log.write_text("\n".join(json.dumps(r) for r in kept) + "\n",
                   encoding="utf-8")
    assert [r["run_id"] for r in W.unfinished_runs(path=log)] == ["ccc"]


def test_another_task_in_the_same_file_is_not_mistaken_for_this_one(tmp_path):
    """The file is named task_runs, not worker_runs: a second task writing here
    must not make this worker look like it never came back."""
    log = tmp_path / "task_runs.jsonl"
    W._task_row({"task": "somebody_else", "event": "start", "run_id": "ddd",
                 "ts": "x"}, path=log)
    assert W.unfinished_runs(path=log) == []


def test_a_torn_final_line_does_not_hide_an_open_run(tmp_path):
    """A process killed mid-write leaves half a line. That is exactly the case
    this file exists to catch, so the reader must skip the broken line and still
    report the run it belongs to."""
    log = tmp_path / "task_runs.jsonl"
    W._task_row({"task": W.TASK_NAME, "event": "start", "run_id": "eee",
                 "ts": "2026-09-20T05:50:00+00:00"}, path=log)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write('{"task": "openclaw_axis_worker", "event": "fin')
    assert [r["run_id"] for r in W.unfinished_runs(path=log)] == ["eee"]


def test_a_missing_log_is_no_unfinished_runs_not_a_crash(tmp_path):
    assert W.unfinished_runs(path=tmp_path / "never_written.jsonl") == []


# ── the chain: fetch then judge, as one event with one owner ────────────────
# Added 20 Sep 2026. Before this the judge ran once a day at 12:00 while the
# fetch ran four times, so three batches a day waited up to twenty hours.

from core import task_runs as TR        # noqa: E402
from core import card_intake as CI      # noqa: E402

CHAIN = REPO / "tools" / "openclaw_chain.bat"


def test_the_chain_runs_the_fetch_then_the_judge_in_that_order():
    """Order is the whole point: judging before fetching judges yesterday."""
    # COMMANDS ONLY. The rem header explains the race and names card_intake.py
    # in prose long before either step runs; an index over the raw text finds
    # that sentence and answers a question about a comment.
    cmds = [ln for ln in CHAIN.read_text(encoding="utf-8", errors="replace").splitlines()
            if not ln.strip().lower().startswith(("rem", "::"))]
    body = "\n".join(cmds)
    i = body.index("openclaw_axis_worker.py")
    j = body.index("card_intake.py")
    assert i < j, "the judge is invoked before the fetch"


def test_exactly_one_caller_owns_the_judge():
    """THE RACE, as an assertion. judge_inbox builds `seen` once, at the top,
    from the card_keys already accepted or refused; two judges running together
    both read it before either writes and both append the same card_key to
    memory/verified_observations.jsonl — the duplicate the key exists to
    prevent, in a file four modules count rows from.

    So there may be exactly one caller. If a second one is ever added, this
    names it rather than leaving the two to overlap on whatever gap the
    schedule happens to give them."""
    callers = []
    for bat in sorted((REPO / "tools").glob("*.bat")) + sorted(REPO.glob("*.bat")):
        text = bat.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("rem") or stripped.startswith("::"):
                continue
            if "card_intake.py" in line:
                callers.append(f"{bat.name}: {line.strip()[:70]}")
    assert len(callers) == 1, (
        f"{len(callers)} callers of card_intake.py; there must be exactly one "
        f"because judge_inbox is not safe to run concurrently:\n  "
        + "\n  ".join(callers))
    assert "openclaw_chain" in callers[0], callers[0]


def test_judge_inbox_skips_a_card_it_has_already_judged(tmp_path):
    """IDEMPOTENT ACROSS RUNS, which is what makes four runs a day free.

    Asserted rather than read off the source: the same inbox is judged twice and
    the second pass must skip what the first accepted."""
    inbox = tmp_path / "cards"
    inbox.mkdir()
    # A SPACED QUOTE, because quote_gate._NUM refuses a number whose preceding
    # character is a colon — the same trap that made the worker's first live
    # cards VALUE_MISMATCH. The card here has to be one the gate accepts, or
    # this test measures the trap instead of the idempotence.
    card = {"axis": "A", "key": "k", "value": 38.0, "unit": "u",
            "url": "https://x/y", "quote": '"count": 38'}
    (inbox / "a_cards.jsonl").write_text(json.dumps(card) + "\n",
                                         encoding="utf-8")
    acc, ref = tmp_path / "acc.jsonl", tmp_path / "ref.jsonl"

    page = '{"count": 38, "maxAllowed": 20000}'
    first = CI.judge_inbox(inbox=inbox, fetch=lambda u: page,
                           accepted_path=acc, refused_path=ref)
    assert first["accepted"] == 1 and first["skipped"] == 0

    second = CI.judge_inbox(inbox=inbox, fetch=lambda u: page,
                            accepted_path=acc, refused_path=ref)
    assert second["accepted"] == 0 and second["skipped"] == 1, second
    rows = [l for l in acc.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 1, "the second pass appended a duplicate"


def test_a_chain_whose_judge_dies_is_still_reported_unfinished(tmp_path):
    """THE REASON THE KEY IS (task, run_id) AND NOT run_id ALONE.

    The chain gives both halves ONE id on purpose. Keyed on the id alone, a
    chain whose fetch finished and whose judge died shows a start and a finish
    for that id and reads as complete — the half-dead chain hidden by the very
    field meant to make it legible."""
    log = tmp_path / "task_runs.jsonl"
    rid = "chain-20260920-145000"
    TR.row("openclaw_axis_worker", "start", rid, path=log)
    TR.row("openclaw_axis_worker", "finish", rid, path=log, ok=True)
    TR.row("card_intake", "start", rid, path=log)
    # ...and then the judge is killed: no finish row for it.

    open_runs = TR.unfinished(path=log)
    assert [r["task"] for r in open_runs] == ["card_intake"], open_runs
    assert TR.unfinished("openclaw_axis_worker", path=log) == []


def test_both_halves_of_a_chain_carry_the_same_run_id(monkeypatch):
    """The id is shared through the environment, which is how a .bat hands one
    value to two processes."""
    monkeypatch.setenv(TR.RUN_ID_ENV, "chain-abc123")
    assert TR.run_id("openclaw_axis_worker") == "chain-abc123"
    assert TR.run_id("card_intake") == "chain-abc123"


def test_a_step_run_alone_mints_its_own_id(monkeypatch):
    """Not in a chain, so it IS its own event. Two calls must not collide."""
    monkeypatch.delenv(TR.RUN_ID_ENV, raising=False)
    a = TR.run_id("openclaw_axis_worker")
    b = TR.run_id("card_intake")
    assert a and b and a != b
    assert not a.startswith("chain-")


def test_the_chain_exports_the_shared_id_before_it_runs_anything():
    body = CHAIN.read_text(encoding="utf-8", errors="replace")
    set_at = body.index("CORTEX_RUN_ID=")
    first_step = body.index("openclaw_axis_worker.py")
    assert set_at < first_step, "the id is set after the first step starts"


def test_the_chain_id_is_not_sliced_out_of_the_locale_date():
    """FOUND ON THE FIRST CHAIN RUN, 20 Sep 2026.

    The id was built as %DATE:~-4%%DATE:~3,2%%DATE:~0,2%, which assumes one
    locale's short-date layout. On this machine it produced

        chain-202600Su-193031

    the weekday where the month should be. The pairing still worked, because
    only equality matters to it, so nothing went red — the id was simply
    unreadable to the human it exists for. Get-Date with an explicit format
    string does not care what the short date looks like."""
    body = CHAIN.read_text(encoding="utf-8", errors="replace")
    cmds = "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().lower().startswith(("rem", "::")))
    assert "%DATE:~" not in cmds, (
        "the chain id is being sliced out of %DATE% by character position again")
    assert "yyyyMMdd-HHmmss" in cmds, (
        "the id is not minted with an explicit date format")


def test_the_live_log_carries_a_readable_chain_id():
    """The live file, not a fixture: whatever the last chain wrote must be
    readable as a date. LIVE_STATE-free because it asserts only about rows that
    exist; a log with no chain row yet skips."""
    rows = []
    log = REPO / "memory" / "task_runs.jsonl"
    if not log.exists():
        pytest.skip("no task_runs.jsonl on this machine yet")
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    chain_ids = [r["run_id"] for r in rows
                 if str(r.get("run_id", "")).startswith("chain-")]
    if not chain_ids:
        pytest.skip("no chain has run on this machine yet")

    # THE NEWEST ONE, not all of them, and that is deliberate. The log still
    # carries chain-202600Su-193031 from the run that FOUND the defect, and it
    # stays: it is a true record of a real run, and rewriting history to make a
    # test green is the opposite of what this file is for. The assertion is
    # about what the chain writes NOW.
    import re
    newest = chain_ids[-1]
    assert re.fullmatch(r"chain-\d{8}-\d{6}", newest), (
        f"the last chain id is not a readable timestamp: {newest!r}")


# ── the two BaseException handlers, exercised rather than declared ──────────
# Added 21 Sep 2026. test_no_bare_except flagged both sites and they were
# resolved by adding them to ALLOWED_BASE_EXCEPTION, which recorded the choice
# without checking it — and one of them sat in a __main__ block where no test
# could reach it at all. These are the checks the declaration now rests on.

import pytest as _pytest        # noqa: E402


def _isolate_run_log(monkeypatch, tmp_path):
    log = tmp_path / "task_runs.jsonl"
    monkeypatch.setattr(TR, "LOG", log)
    monkeypatch.delenv(TR.RUN_ID_ENV, raising=False)
    return log


@_pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit],
                          ids=["ctrl-c", "sys.exit"])
def test_the_worker_records_an_interrupt_and_re_raises_it(exc, tmp_path,
                                                          monkeypatch):
    """BOTH HALVES, because either alone would be a false comfort.

    If it did not RE-RAISE, a Ctrl-C would be swallowed and the shell would see
    a clean exit. If it did not RECORD, the run would leave a start with no
    finish — the row shape that means "killed by a reboot" — and nothing ever
    clears that, so unfinished_runs() would announce the phantom at the top of
    every future run for ever.
    """
    log = _isolate_run_log(monkeypatch, tmp_path)

    def _boom(*a, **k):
        raise exc("interrupted")

    monkeypatch.setattr(W, "run", _boom)
    monkeypatch.setattr(sys, "argv", ["openclaw_axis_worker.py"])
    with _pytest.raises(exc):
        W.main()

    rows = _rows(log)
    assert [r["event"] for r in rows] == ["start", "finish"], rows
    assert rows[1]["ok"] is False
    assert exc.__name__ in rows[1]["error"]
    assert TR.unfinished(path=log) == [], (
        "the interrupted run is still open; it was recorded, so it is closed")


@_pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit],
                          ids=["ctrl-c", "sys.exit"])
def test_the_judge_records_an_interrupt_and_re_raises_it(exc, tmp_path,
                                                         monkeypatch):
    """The same for the second half of the chain. This handler lived in a
    __main__ block until 21 Sep 2026 and could not be reached by any test."""
    log = _isolate_run_log(monkeypatch, tmp_path)

    def _boom(*a, **k):
        raise exc("interrupted")

    monkeypatch.setattr(CI, "judge_inbox", _boom)
    with _pytest.raises(exc):
        CI.main(argv=["card_intake.py"])

    rows = _rows(log)
    assert [r["event"] for r in rows] == ["start", "finish"], rows
    assert rows[1]["ok"] is False
    assert exc.__name__ in rows[1]["error"]
    assert TR.unfinished(path=log) == []


def test_an_ordinary_exception_is_recorded_and_re_raised_too(tmp_path,
                                                             monkeypatch):
    """The BaseException catch must not be the only path that records. A plain
    RuntimeError takes the same branch and must be treated identically."""
    log = _isolate_run_log(monkeypatch, tmp_path)
    monkeypatch.setattr(CI, "judge_inbox",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with _pytest.raises(RuntimeError):
        CI.main(argv=["card_intake.py"])
    rows = _rows(log)
    assert rows[-1]["event"] == "finish" and rows[-1]["ok"] is False
    assert "RuntimeError" in rows[-1]["error"]


def test_a_clean_judge_run_closes_its_own_row(tmp_path, monkeypatch):
    """The counter-example, so the tests above are not passing on a main() that
    fails every time."""
    log = _isolate_run_log(monkeypatch, tmp_path)
    monkeypatch.setattr(CI, "judge_inbox",
                        lambda *a, **k: {"accepted": 0, "refused": 0})
    out = CI.main(argv=["card_intake.py"])
    assert out == {"accepted": 0, "refused": 0}
    rows = _rows(log)
    assert rows[-1]["event"] == "finish" and rows[-1]["ok"] is True
    assert TR.unfinished(path=log) == []

