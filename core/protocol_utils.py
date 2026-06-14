#!/usr/bin/env python3
"""
core/protocol_utils.py
Wraps raw LLM review output in a standard CORTEX++ protocol header.
"""
from __future__ import annotations


def wrap_in_protocol(
    axis: str,
    today: str,
    review_agent: str,
    raw_block: str,
    review_index: int | None = None,
) -> str:
    idx = f"-{review_index:03d}" if review_index is not None else ""
    header = (
        f"# {axis} – {today}{idx}\n"
        f"_agent: {review_agent}_\n\n"
    )
    return header + raw_block
