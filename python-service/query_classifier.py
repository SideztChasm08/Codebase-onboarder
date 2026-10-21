"""Transparent initial query routing rules for codebase questions."""

from __future__ import annotations

import re


STRUCTURAL_PATTERNS = (
    r"\bwhere\s+is\b", r"\bwhere\s+are\b", r"\bdefinition\b", r"\bdefined\b",
    r"\bfind\s+(?:all\s+)?(?:references|callers|usages|calls)\b",
    r"\breferences?\s+to\b", r"\bcalled\b", r"\bcallers?\s+of\b",
    r"\bwho\s+calls\b", r"\bused\s+where\b", r"\buses\s+of\b",
)
CONCEPTUAL_PATTERNS = (
    r"\bhow\b", r"\bwhy\b", r"\bexplain\b", r"\bwhat\s+happens\b",
    r"\bworkflow\b", r"\bflow\b", r"\barchitecture\b", r"\bwork\b",
)


def classify_query(question: str) -> dict:
    """Return ``conceptual``, ``structural`` or ``ambiguous`` and route list."""
    text = " ".join((question or "").lower().split())
    structural = any(re.search(pattern, text) for pattern in STRUCTURAL_PATTERNS)
    conceptual = any(re.search(pattern, text) for pattern in CONCEPTUAL_PATTERNS)
    if structural and conceptual:
        classification, routes = "ambiguous", ["semantic", "structural"]
    elif structural:
        classification, routes = "structural", ["structural"]
    else:
        classification, routes = "conceptual", ["semantic"]
    return {
        "classification": classification,
        "routes": routes,
        "reason": ("matched structural and conceptual cues" if structural and conceptual
                   else "matched structural cues" if structural
                   else "default semantic route"),
    }
