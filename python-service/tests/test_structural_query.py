from query_classifier import classify_query
from structural_query import answer_structural_query
from symbol_graph import build_symbol_graph


def test_definition_and_reference_evidence_have_exact_locations(tmp_path):
    (tmp_path / "defs.py").write_text(
        "def validate_token():\n    return True\n", encoding="utf-8"
    )
    (tmp_path / "use.py").write_text(
        "from defs import validate_token\n\ndef handler():\n    validate_token()\n",
        encoding="utf-8",
    )
    graph = build_symbol_graph(tmp_path, "repo", "rev")

    definition = answer_structural_query(graph, "Where is validate_token defined?")
    assert definition["status"] == "resolved"
    assert definition["evidence"] == [{
        "relationship": "definition", "symbol_id": graph.symbols[0]["symbol_id"],
        "symbol": "defs.validate_token", "file": "defs.py",
        "start_line": 1, "end_line": 2,
    }]

    references = answer_structural_query(graph, "Where is validate_token called?")
    assert references["status"] == "resolved"
    assert references["evidence"][0]["relationship"] == "call_reference"
    assert references["evidence"][0]["file"] == "use.py"
    assert references["evidence"][0]["line"] == 4
    assert references["evidence"][0]["caller"] == "use.handler"


def test_ambiguous_and_missing_symbols_are_not_fabricated(tmp_path):
    (tmp_path / "one.py").write_text("def helper(): pass\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("def helper(): pass\n", encoding="utf-8")
    graph = build_symbol_graph(tmp_path, "repo", "rev")

    ambiguous = answer_structural_query(graph, "Where is helper defined?")
    assert ambiguous["status"] == "ambiguous"
    assert {candidate["file"] for candidate in ambiguous["candidates"]} == {
        "one.py", "two.py"
    }
    absent = answer_structural_query(graph, "Where is missing_symbol defined?")
    assert absent["status"] == "not_found"
    assert absent["evidence"] == []


def test_combined_question_keeps_both_routes_and_structural_evidence(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def authenticate(): pass\n\ndef login():\n    authenticate()\n",
        encoding="utf-8",
    )
    graph = build_symbol_graph(tmp_path, "repo", "rev")
    answer = answer_structural_query(
        graph, "How does authenticate work and where is authenticate called?"
    )
    assert classify_query("How does authenticate work and where is authenticate called?")[
        "routes"
    ] == ["semantic", "structural"]
    assert answer["classification"]["classification"] == "ambiguous"
    assert answer["evidence"][0]["line"] == 4
