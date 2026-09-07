# -*- coding: utf-8 -*-
"""
R52 item 3 — THE WORKED EXAMPLE CANNOT SILENTLY DRIFT FROM THE CONTRACT.

PREDICTION ONLY (§VI); nothing here trades.

The example in GROUNDED_PROMPT is the single concrete demonstration a 3B gets. Twice
now it has been the thing teaching the failure: in R48 it put DIRECTION first, and in
R50 it wrapped a field across two source lines so the second half would have been
dropped. Both times a test caught it only because I happened to write one.

So these tests DERIVE what they expect FROM GROUNDED_CONTRACT rather than hardcoding
field names. Reorder the contract and forget the example, and this file goes red.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import (BUCKETS, GROUNDED_CONTRACT,  # noqa: E402
                              GROUNDED_PROMPT, grounded_gate,
                              parse_grounded_completion)

D = "2026-09-08"


@dataclass(frozen=True)
class Sn:
    snippet: str = "CPI rose 0.3% in August, the BLS said on Friday."
    title: str = "US inflation ticks up"
    url: str = "https://www.reuters.com/x"
    published_utc: str = "2026-09-05T12:30:00+00:00"
    host: str = "reuters.com"
    source_class: str = "independent"
    source_kind: str = "wire"
    dated: bool = True


def _example() -> str:
    body = GROUNDED_PROMPT.format(sym="SPY", close=1, close_date="2026-09-04",
                                  evidence="", deadline=D)
    return body.split("A correct answer is:", 1)[1].split("Note what")[0]


def _example_keys() -> list:
    allowed = set(GROUNDED_CONTRACT) | {"DEADLINE"}
    out = []
    for line in _example().splitlines():
        if ":" not in line:
            continue
        key = line.split(":", 1)[0].strip().upper()
        if key in allowed:
            out.append(key)
    return out


def _gate(comp):
    return grounded_gate([parse_grounded_completion(comp)], "SPY", D, [Sn()])[0]


# ── the drift guard ─────────────────────────────────────────────────────────
def test_the_example_uses_exactly_the_contract_fields_in_the_contract_order():
    """DERIVED FROM GROUNDED_CONTRACT, never hardcoded. This is the whole point."""
    keys = [k for k in _example_keys() if k != "DEADLINE"]
    assert keys == list(GROUNDED_CONTRACT), (
        f"the worked example teaches {keys} but the contract is "
        f"{list(GROUNDED_CONTRACT)} — the example has drifted")


def test_the_example_parses_clean_through_the_real_parser():
    p = parse_grounded_completion(_example())
    assert p["order_problem"] is None, p["order_problem"]
    assert p["field_order"][-1] == "DIRECTION"


def test_the_example_carries_no_field_from_a_previous_round():
    """R50's EVENT / RELEVANCE / MECHANISM must be gone from the WHOLE prompt, not just
    from the example — a stale line anywhere in it still teaches."""
    for dead in ("EVENT:", "RELEVANCE:", "MECHANISM:", "RATIONALE:"):
        assert dead not in GROUNDED_PROMPT, dead


def test_every_example_field_sits_on_exactly_one_line():
    """R50 wrapped a field across two source lines for readability. The parser reads one
    line per field, so the example was teaching a shape whose second half would be
    silently dropped."""
    for key in _example_keys():
        matches = [ln for ln in _example().splitlines()
                   if ln.strip().upper().startswith(key + ":")]
        assert len(matches) == 1, key
    for line in _example().splitlines():
        if line.strip():
            assert ":" in line, f"continuation line in the example: {line!r}"


def test_the_examples_direction_comes_after_all_the_reasoning():
    keys = _example_keys()
    assert keys[-1] == "DIRECTION"
    for field in GROUNDED_CONTRACT[:-1]:
        assert keys.index(field) < keys.index("DIRECTION"), field


# ── item 6b: the example must not teach generic filler ──────────────────────
def test_the_examples_logic_names_a_concrete_channel():
    """A LOGIC line that would fit any fact teaches the model to write one that fits any
    fact. The prompt names the register — yields, flows, positioning, supply — and the
    example has to be an INSTANCE of it, not a paraphrase of the instruction."""
    logic = parse_grounded_completion(_example())["logic"].lower()
    channels = ("yield", "flow", "positioning", "supply", "rate", "discount",
                "inventory", "demand", "carry", "spread")
    assert any(c in logic for c in channels), logic


def test_the_examples_logic_is_not_contentless_filler():
    logic = parse_grounded_completion(_example())["logic"].lower()
    filler = ("moves the price", "affects the asset", "will react",
              "impacts the market", "causes a change", "influences the price",
              "has an effect on", "is relevant to the asset")
    for phrase in filler:
        assert phrase not in logic, phrase
    assert len(logic.split()) >= 6, logic


def test_the_examples_logic_is_not_echoed_from_the_instruction_line():
    """If the example's LOGIC is the instruction's own words, it demonstrates nothing
    and teaches the model to hand the prompt back."""
    logic = parse_grounded_completion(_example())["logic"].lower().rstrip(".")
    prompt = GROUNDED_PROMPT.lower()
    assert "yields, flows, positioning, supply" not in logic
    words = logic.split()
    for i in range(len(words) - 5):
        run = " ".join(words[i:i + 6])
        assert prompt.count(run) == 1, f"the example echoes the prompt: {run!r}"


# ── item 6a: bucket parsing, confirmed rather than assumed ─────────────────
def test_a_bucket_with_a_qualifier_parses_on_its_first_word():
    for raw, want in (("MACRO (rates)", "MACRO"), ("GEOPOL - war", "GEOPOL"),
                      ("macro", "MACRO"), ("FLOW, positioning", "FLOW")):
        p = parse_grounded_completion(
            f"DEADLINE: {D}\nSIGNAL: 2\nDRIVER: {raw}\nLOGIC: x\nDIRECTION: UP")
        first = (p["driver"] or "").upper().split()[0:1]
        assert first and first[0].rstrip(",") == want, raw


def test_an_empty_or_punctuated_bucket_refuses():
    """'SECTOR:' is a bucket with a stray colon and it REFUSES rather than being cleaned
    up. Stripping punctuation here would be the module deciding what the model meant —
    the habit the index parser already refuses — and the cost of refusing is one
    candidate, not a wrong bet."""
    for raw in ("SECTOR:", "", "   ", "VIBES"):
        r = _gate(f"DEADLINE: {D}\nSIGNAL: 2\nDRIVER: {raw}\n"
                  f"LOGIC: yields reprice it\nDIRECTION: UP")
        assert r["verdict"] == "REFUSED", raw
        assert "driver" in r["missing"] or "field_order" in r["missing"], raw


def test_all_four_buckets_are_accepted():
    for bucket in BUCKETS:
        r = _gate(f"DEADLINE: {D}\nSIGNAL: 2\nDRIVER: {bucket}\n"
                  f"LOGIC: yields reprice the basket\nDIRECTION: UP")
        assert r["verdict"] == "ADMITTED", (bucket, r.get("refusal"))
