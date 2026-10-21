from query_classifier import classify_query


def test_conceptual_question_routes_to_semantic():
    result = classify_query("How does authentication work?")
    assert result["classification"] == "conceptual"
    assert result["routes"] == ["semantic"]


def test_structural_question_routes_to_graph():
    result = classify_query("Where is validate_token defined?")
    assert result["classification"] == "structural"
    assert result["routes"] == ["structural"]


def test_combined_question_routes_to_both():
    result = classify_query("How does validate_token work and where is it called?")
    assert result["classification"] == "ambiguous"
    assert result["routes"] == ["semantic", "structural"]
