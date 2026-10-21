"""Evidence-first structural query handling over a SymbolGraph."""

from __future__ import annotations

import re

from query_classifier import classify_query


_SYMBOL_PATTERNS = (
    r"[`'\"]([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)[`'\"]",
    r"(?:definition\s+of|defined|references?\s+to|callers?\s+of|calls?\s+to|"
    r"usages?\s+of|uses?\s+of|where\s+is|who\s+calls)\s+"
    r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)",
)
_REFERENCE_WORDS = re.compile(r"\b(reference|called|callers?|usages?|uses|used)\b", re.I)


def extract_symbol_name(question: str) -> str | None:
    for pattern in _SYMBOL_PATTERNS:
        match = re.search(pattern, question or "", re.I)
        if match:
            return match.group(1)
    return None


def answer_structural_query(graph, question: str) -> dict:
    """Return structured findings with source locations and honest ambiguity."""
    classification = classify_query(question)
    symbol_name = extract_symbol_name(question)
    base = {
        "classification": classification,
        "repo_id": graph.repo_id,
        "revision": graph.revision,
        "symbol": symbol_name,
        "evidence": [],
        "candidates": [],
        "message": None,
    }
    if "structural" not in classification["routes"]:
        base["status"] = "semantic_required"
        base["message"] = "This question is routed to semantic retrieval."
        return base
    if not symbol_name:
        base["status"] = "needs_symbol"
        base["message"] = "Name the symbol to look up; no symbol name was found in the question."
        ignored = {"where", "is", "are", "this", "that", "function", "method",
                   "class", "called", "defined", "find", "references", "callers"}
        words = {word.lower() for word in re.findall(r"[A-Za-z_]\w*", question)
                 if word.lower() not in ignored}
        base["candidates"] = [s for s in graph.symbols
                              if s["name"].lower() in words
                              or any(part.lower() in words
                                     for part in s["qualified_name"].split("."))]
        return base

    definitions = graph.find_definitions(symbol_name)
    if not definitions:
        base["status"] = "not_found"
        base["message"] = f"No indexed definition matched {symbol_name!r}."
        return base
    base["candidates"] = definitions
    if len(definitions) > 1:
        base["status"] = "ambiguous"
        base["message"] = f"{symbol_name!r} matches multiple definitions; select a qualified name."
        return base

    definition = definitions[0]
    base["symbol"] = definition["qualified_name"]
    definition_requested = bool(re.search(r"\b(definition|defined|where\s+is)\b",
                                          question, re.I)) and not _REFERENCE_WORDS.search(question)
    if definition_requested:
        base["evidence"].append({
            "relationship": "definition", "symbol_id": definition["symbol_id"],
            "symbol": definition["qualified_name"], "file": definition["file"],
            "start_line": definition["start_line"], "end_line": definition["end_line"],
        })
    else:
        for call in graph.find_references(definition["qualified_name"]):
            base["evidence"].append({
                "relationship": "call_reference", "symbol_id": definition["symbol_id"],
                "symbol": definition["qualified_name"], "file": call["file"],
                "line": call["line"], "caller": call["caller_qualified_name"],
                "expression": call["expression"],
            })
    base["status"] = "resolved" if base["evidence"] else "no_references"
    base["message"] = ("Structural evidence found." if base["evidence"] else
                       "Definition found, but no resolved call references were indexed.")
    return base
