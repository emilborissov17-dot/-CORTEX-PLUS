#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alignment/civilization_guard.py
Evaluates whether a proposal is aligned with the CORTEX++ civilization vision.
Fails CLOSED — if anything goes wrong, the proposal is blocked.
"""
from __future__ import annotations

import re
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Hard-blocked keywords — proposals containing these are always denied
# ---------------------------------------------------------------------------
HARD_BLOCK_PATTERNS = [
    r"\bweapon",
    r"\bexplosive",
    r"\bmalware",
    r"\bransomware",
    r"\bdisinformation",
    r"\bpropaganda",
    r"\bdomination",
    r"\bdeceiv",
    r"\bcoerce",
    r"\brm\s+-rf",
    r"\bformat\s+c",
    r"\bdrop\s+table",
    r"\bshutdown",
    r"\breboot",
]

# ---------------------------------------------------------------------------
# Positive alignment signals
# ---------------------------------------------------------------------------
ALIGNED_KEYWORDS = [
    "education", "healthcare", "clean water", "clean energy", "renewable",
    "food security", "transparency", "equality", "poverty", "biodiversity",
    "climate", "governance", "well-being", "wellbeing", "sustainability",
    "open source", "research", "monitoring", "analysis", "report",
    "snapshot", "memory", "scoring", "prediction", "data quality",
    "observation", "наблюдение", "анализ", "предсказание", "данни",
    "сканиране", "мониторинг", "самонаблюдение",
]

# Trusted internal sources — по-висок threshold
TRUSTED_SOURCES = {"self_observer", "system2", "predictor", "body_scan"}

RISK_THRESHOLD_DEFAULT = 0.55
RISK_THRESHOLD_TRUSTED = 0.80  # По-толерантен за вътрешни агенти


def _score_text(text: str, trusted: bool = False) -> float:
    """Returns a risk score 0.0–1.0 based on keyword analysis."""
    text_lower = text.lower()

    # Hard block — immediate max risk
    for pattern in HARD_BLOCK_PATTERNS:
        if re.search(pattern, text_lower):
            return 1.0

    risk = 0.0

    # Shell сигнали — само ако НЕ е trusted source
    if not trusted:
        shell_signals = ["os.system", "eval(", "exec(", "shutil.rmtree", "__import__"]
        for sig in shell_signals:
            if sig in text_lower:
                risk += 0.20

    # Reward alignment signals
    aligned_hits = sum(1 for kw in ALIGNED_KEYWORDS if kw in text_lower)
    risk -= aligned_hits * 0.05

    return max(0.0, min(1.0, risk))


def evaluate_proposal_alignment(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point.

    Returns:
        {
            "allowed": bool,
            "risk_score": float,
            "notes": str
        }
    """
    try:
        component = str(proposal.get("component", ""))
        problem   = str(proposal.get("problem", ""))
        solution  = str(proposal.get("solution", ""))
        code      = str(proposal.get("python_code", ""))
        source    = str(proposal.get("source", ""))

        combined = f"{component} {problem} {solution} {code}"
        trusted  = source in TRUSTED_SOURCES
        threshold = RISK_THRESHOLD_TRUSTED if trusted else RISK_THRESHOLD_DEFAULT

        # Hard block
        for pattern in HARD_BLOCK_PATTERNS:
            if re.search(pattern, combined.lower()):
                return {
                    "allowed": False,
                    "risk_score": 1.0,
                    "notes": f"hard_block: matched pattern '{pattern}'",
                }

        risk_score = _score_text(combined, trusted=trusted)
        allowed = risk_score < threshold
        notes = "aligned" if allowed else f"risk_score {risk_score:.2f} exceeds threshold {threshold}"

        return {
            "allowed": allowed,
            "risk_score": round(risk_score, 3),
            "notes": notes,
        }

    except Exception as e:
        return {
            "allowed": False,
            "risk_score": 1.0,
            "notes": f"alignment_guard_error (fail closed): {e}",
        }


if __name__ == "__main__":
    tests = [
        {"component": "EDUCATION", "problem": "Improve education data quality", "solution": "Add monitoring", "python_code": "", "source": "self_observer"},
        {"component": "SECURITY",  "problem": "Deploy surveillance system",     "solution": "Track users",    "python_code": "", "source": "unknown"},
        {"component": "PATCH",     "problem": "Fix scoring", "solution": "rewrite", "python_code": "import os; os.system('rm -rf /')", "source": "self_observer"},
        {"component": "CLIMATE",   "problem": "Track CO2 levels", "solution": "Parse API data", "python_code": "import requests", "source": "self_observer"},
        {"component": "SCAN",      "problem": "Наблюдение от self_observer: scan_network", "solution": "Резултат: данни от мрежата", "python_code": "", "source": "self_observer"},
    ]
    for t in tests:
        r = evaluate_proposal_alignment(t)
        icon = "✅" if r["allowed"] else "❌"
        print(f"{icon} [{t['component']}] risk={r['risk_score']:.2f} | {r['notes']}")