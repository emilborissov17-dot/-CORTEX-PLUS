# -*- coding: utf-8 -*-
"""
The gate contract, in ONE place, for every generator that produces proposals.

WHY THIS MODULE EXISTS (6 Sep 2026)
-----------------------------------
On 5 Sep the HyperClaw prompt was given the contract: what CORTEX++ CAN and
CANNOT do, which indicators are gradeable tonight, and the three lines every step
must carry. `core.proposal_intake` then refuses, by name, anything that arrives
without them.

But hyperclaw is not the only generator. `_strategist_to_proposals` and
`_growth_to_proposals` in fast_cycle_runner walk their snapshots to the SAME
door — `_inject_proposals` -> `proposal_intake.admit` — and their prompts never
said so. They were being judged against a contract they had never been shown,
which is not a gate, it is a trap.

The block lives here rather than in hyperclaw so three copies cannot drift apart.
hyperclaw keeps its own names as thin aliases.

NOTHING HERE CALLS A MODEL. It builds text and reads measured state; a generator
that cannot import it must fail loudly rather than send a prompt without the
contract.
"""
from __future__ import annotations

import json
import pathlib

BASE = pathlib.Path(__file__).resolve().parents[1]

# What the machine can actually do. The list is short on purpose: a step that
# names anything outside it is a step nobody can carry out, and a plan full of
# them reads like agency while producing nothing.
CAPABILITIES = (
    "CORTEX++ CAN: read public indicators (World Bank, NOAA, USGS, WHO, UNHCR, ACLED, "
    "arXiv, GitHub) once a night; write JSON snapshots and scores; register a "
    "prediction about an indicator and grade it later; publish a Markdown/JSON report "
    "to GitHub; propose a patch to its own code for a HUMAN to review.\n"
    "CORTEX++ CANNOT: send email, run surveys, fund, build, deploy, contact anyone, or "
    "change anything in the world without a human acting on its output."
)

# The three lines proposal_intake requires. Stated identically to every generator.
REQUIRED_KEYS = ("INDICATOR", "EXPECTED_DELTA", "DEADLINE")

REQUIRED_LINES = (
    "EVERY proposal MUST carry these three lines, or it is REFUSED at intake and "
    "enters nothing:\n"
    "  INDICATOR: one of the gradeable indicators listed above (exact name), or "
    "AXIS__metric where that metric is measured under that axis\n"
    "  EXPECTED_DELTA: a signed number, the change you expect in that indicator "
    "(a bare number - no units, no parenthetical)\n"
    "  DEADLINE: YYYY-MM-DD, within one year"
)


def gradeable_indicators() -> dict:
    """axis -> observed value, for axes MEASURED this cycle.

    The same gate as K1 and hypothesis_intake: only these can be graded, so only
    these may be named. An empty dict is an honest answer and says so in the
    block; it is never replaced with a default list.
    """
    import sys
    sys.path.insert(0, str(BASE))
    try:
        from core.hypothesis_intake import measured_axes
        return dict(measured_axes() or {})
    except Exception:                                            # noqa: BLE001
        return {}


def indicator_block(indicators: dict | None = None) -> str:
    ind = gradeable_indicators() if indicators is None else indicators
    if not ind:
        return ("GRADEABLE INDICATORS: none resolved this cycle - any INDICATOR you name "
                "will be refused at intake.\n")
    lines = [f"  {k}: {v}" for k, v in sorted(ind.items())]
    return ("GRADEABLE INDICATORS (axis: current value). INDICATOR must be one of these "
            "axes, or AXIS__metric where the metric is measured under that axis:\n"
            + "\n".join(lines) + "\n")


REFUSALS_PATH = BASE / "memory" / "proposal_intake_refusals.jsonl"
REFUSALS_HEADER = ("REFUSED LAST NIGHT (human-in-the-loop prompt refinement - this is not "
                   "learning)")


def refusals_block(path: pathlib.Path | None = None, limit: int = 10) -> str:
    """Last night's refusals, verbatim, for the prompt.

    LABELLED AS WHAT IT IS. Showing a generator its own refusals inside the next
    prompt is a human tightening a prompt by hand between runs; no weight
    changes, nothing is retained, and the next model instance starts blank. It is
    prompt refinement, and calling it learning would be the same overclaim the
    rest of this repo has been unpicking all week.

    An absent file yields an EMPTY STRING - no header, no placeholder. A section
    that says "none" when the file is simply missing would be asserting something
    nobody measured.
    """
    p = path or REFUSALS_PATH
    if not p.is_file():
        return ""
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:                                        # noqa: BLE001
            continue
    if not rows:
        return ""
    out = [REFUSALS_HEADER]
    for r in rows[-limit:]:
        src = str(r.get("source") or r.get("generated_by") or "?")
        missing = r.get("missing") or r.get("missing_fields") or []
        if isinstance(missing, (list, tuple)):
            missing = ", ".join(str(m) for m in missing)
        why = str(r.get("why") or r.get("reason") or "")
        out.append(f"  {src}: missing [{missing}] - {why}"[:300])
    return "\n".join(out) + "\n"


def contract_block(indicators: dict | None = None,
                   refusals: pathlib.Path | None = None) -> str:
    """The whole contract, in the order a generator should read it."""
    parts = [CAPABILITIES, "", indicator_block(indicators), REQUIRED_LINES]
    ref = refusals_block(refusals)
    if ref:
        parts += ["", ref.rstrip()]
    return "\n".join(parts) + "\n"
