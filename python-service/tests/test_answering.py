import pytest

from answering import answer_query
from structural_query import answer_structural_query
from symbol_graph import build_symbol_graph


class FakeLLM:
    def __init__(self, result="The handler checks credentials.", error=None):
        self.result, self.error, self.prompts = result, error, []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result


def chunk(file="auth.py", start=3, end=6):
    return {"file_path": file, "start_line": start, "end_line": end,
            "source": "def authenticate():\n    return True"}


def test_conceptual_retrieval_synthesis_and_citation_are_grounded():
    llm = FakeLLM()
    calls = []
    answer = answer_query("repo", "rev-a", "How does authentication work?", None,
                          lambda *a, **k: calls.append((a, k)) or [chunk()], llm)
    assert answer["status"] == "answered"
    assert "authenticate" in llm.prompts[0]
    assert calls[0][1] == {"limit": 5}
    assert answer["citations"] == [{"repository_id": "repo", "revision": "rev-a",
        "file_path": "auth.py", "start_line": 3, "end_line": 6, "source_type": "chunk"}]


def test_insufficient_evidence_skips_model():
    llm = FakeLLM()
    answer = answer_query("repo", "rev-a", "How does missing work?", None,
                          lambda *a, **k: [], llm)
    assert answer["status"] == "insufficient_evidence"
    assert answer["citations"] == [] and not llm.prompts


def test_structural_query_uses_graph_without_vector_retrieval(tmp_path):
    (tmp_path / "auth.py").write_text("def authenticate():\n    return True\n", encoding="utf-8")
    graph = build_symbol_graph(tmp_path, "repo", "rev-a")
    llm = FakeLLM("It is defined in auth.py.")
    calls = []
    answer = answer_query("repo", "rev-a", "Where is authenticate defined?", graph,
                          lambda *a, **k: calls.append(a) or [], llm)
    assert calls == []
    assert answer["citations"][0]["source_type"] == "symbol_graph"
    assert answer["citations"][0]["start_line"] == 1
    assert answer["citations"][0]["end_line"] == 2


def test_combined_query_includes_both_evidence_kinds(tmp_path):
    (tmp_path / "auth.py").write_text("def authenticate(): pass\ndef login():\n    authenticate()\n", encoding="utf-8")
    graph = build_symbol_graph(tmp_path, "repo", "rev-a")
    answer = answer_query("repo", "rev-a", "How does authenticate work and where is authenticate called?",
                          graph, lambda *a, **k: [chunk("auth.py", 1, 3)], FakeLLM())
    assert {citation["source_type"] for citation in answer["citations"]} == {"chunk", "symbol_graph"}
    assert answer["classification"]["routes"] == ["semantic", "structural"]


def test_model_failure_is_reported_and_graph_identity_is_enforced(tmp_path):
    graph = build_symbol_graph(tmp_path, "repo", "rev-a")
    with pytest.raises(RuntimeError, match="Answer synthesis failed"):
        answer_query("repo", "rev-a", "How does auth work?", None,
                     lambda *a, **k: [chunk()], FakeLLM(error=OSError("offline")))
    with pytest.raises(ValueError, match="does not match"):
        answer_query("other", "rev-a", "Where is auth defined?", graph,
                     lambda *a, **k: [], FakeLLM())


def test_stale_vector_revision_cannot_be_cited_as_current():
    stale = {**chunk(), "revision": "old-rev"}
    with pytest.raises(ValueError, match="chunk revision"):
        answer_query("repo", "rev-a", "How does authentication work?", None,
                     lambda *a, **k: [stale], FakeLLM())
