# CORTEX++

An open-source AI safety research system: an autonomous agent that monitors
civilizational and planetary risk indicators, and serves as a live testbed for
a core safety question — **can a self-modifying AI improve itself within a
transparent, human-controlled boundary, without being able to disable its own
oversight?**

This repository is developed fully in the open. Progress, methodology, and
limitations are visible in real time through the public commit history — not
described after the fact.

---

## What it does today

CORTEX++ runs an autonomous cycle that:

- **Ingests real-world data** from institutional sources (World Bank, WHO,
  UNHCR, NASA, NOAA, USGS, GBIF, arXiv and others) across multiple
  civilizational axes — climate, governance, inequality, education, energy,
  and long-term risk.
- **Generates citation-checked hypotheses** about gaps between what major
  institutions formally commit to and what their measurable outcomes show.
  Verification uses real web fetches, not the model's own self-assessment.
- **Applies its own code changes through a safety layer** (`patch_guardian`):
  syntax check, backup, import test, and rollback before any change is kept.
- **Maintains persistent memory** across cycles (Merkle-committed), so the
  system builds on its own history rather than starting fresh each run.

## Current status (honest)

This is an early-stage, single-developer research project in active
development. Concretely:

- Real data integrations are live for a subset of axes; others are still
  placeholders pending data wiring.
- The self-modification safety layer works but is being hardened — we are
  actively closing paths by which the system could bypass its own guardian.
- The effect-measurement metric for self-applied changes is being reworked to
  measure impact honestly across cycles rather than within a single cycle.
- The system's memory is retrieval-based (RAG): it accumulates textual insights
  from past cycles and feeds them into future LLM prompts as context. It does
  not perform machine-learning training — no model weights are updated.

We document what works and what doesn't, deliberately. Epistemic honesty —
refusing to treat the model's own claims as evidence — is a design principle,
not an afterthought.

## Architecture

A hypergraph of autonomous agents synthesizes incoming data into a unified
assessment across five dimensions:

- **Sustainable Resources** — critical resource depletion risk
- **Healthy Environments** — ecological integrity and irreversible damage
- **Civilizational Stability** — conflict and systemic-collapse signals
- **Knowledge & Understanding** — scientific progress and epistemic health
- **Safety** — AI misalignment and high-consequence risk indicators

## Long-term vision

The full civilizational vision behind CORTEX++ is documented in
[`VISION.md`](./VISION.md). In short: an advanced, human-centric, transparent
AI that helps people make better long-term decisions, operating within a
controlled "bubble" so it can improve itself without becoming an instrument of
domination or harm.

This vision is the direction, not a claim about the system's current
capabilities.

## Principles

Human-centric. Transparent. Open source. Aligned with the long-term survival
and flourishing of intelligent life.

## License

MIT
