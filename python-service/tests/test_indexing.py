from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import indexing
from embeddings import FakeEmbedder
import embeddings


class MemoryStore:
    dimension = 8

    def __init__(self):
        self.active = {}
        self.calls = []

    def replace_generation(self, repo_id, revision, model_name, records):
        # Simulate the database's atomic commit: stage first, then activate.
        staged = {record["chunk"]["chunk_id"]: record for record in records}
        self.calls.append((repo_id, revision, model_name, staged))
        self.active[repo_id] = (revision, staged)

    def search(self, repo_id, query_embedding, limit=5, model_name=None):
        return [{"repo_id": repo_id, "model": model_name}]


def test_index_pipeline_normalizes_batches_and_is_idempotent(tmp_path, monkeypatch):
    (tmp_path / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    chunks = [{
        "file": "auth.py", "type": "function", "name": "login",
        "start_line": 1, "end_line": 2, "source": "def login(): return True",
        "imports": [], "comments": [],
    }]
    monkeypatch.setattr(indexing, "collect_chunks", lambda path, repo: [
        indexing.normalize_chunk(chunks[0], repo)
    ])
    embedder, store = FakeEmbedder(dimension=8, batch_size=1), MemoryStore()
    first = indexing.index_repository("r1", tmp_path, "abc", embedder, store)
    second = indexing.index_repository("r1", tmp_path, "abc", embedder, store)
    assert first["chunk_count"] == second["chunk_count"] == 1
    assert store.active["r1"][0] == "abc"
    assert len(store.active["r1"][1]) == 1
    assert len(store.calls) == 2


def test_failed_embedding_does_not_call_store_or_replace_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(indexing, "collect_chunks", lambda path, repo: [{
        "repo_id": repo, "file": "x.py", "type": "function", "name": "x",
        "qualified_name": "x", "chunk_id": "x", "start_line": 1,
        "end_line": 1, "source": "x()",
    }])

    class BrokenEmbedder(FakeEmbedder):
        def embed(self, texts):
            raise RuntimeError("model failed")

    store = MemoryStore()
    store.active["r1"] = ("old", {"known": "previous index"})
    with pytest.raises(RuntimeError, match="model failed"):
        indexing.index_repository("r1", tmp_path, "new", BrokenEmbedder(8), store)
    assert store.active["r1"][0] == "old"
    assert store.calls == []


def test_default_model_loader_is_reused_but_configuration_isolated(tmp_path, monkeypatch):
    loads = []

    class Model:
        def __init__(self, model_id, **kwargs):
            loads.append((model_id, kwargs))

        def get_sentence_embedding_dimension(self):
            return 8

        def encode(self, texts, **kwargs):
            return [[1.0] + [0.0] * 7 for _ in texts]

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(
        SentenceTransformer=Model
    ))
    monkeypatch.setenv("EMBEDDING_MODEL", "fixture-a")
    monkeypatch.delenv("EMBEDDING_MODEL_REVISION", raising=False)
    monkeypatch.setattr(embeddings, "_EMBEDDER_CACHE", {})
    monkeypatch.setattr(indexing, "collect_chunks", lambda path, repo: [
        indexing.normalize_chunk({
            "file": "auth.py", "type": "function", "name": "login",
            "start_line": 1, "end_line": 1, "source": "def login(): pass",
        }, repo)
    ])
    store = MemoryStore()

    indexing.index_repository("r1", tmp_path, "rev-a", store=store)
    indexing.index_repository("r1", tmp_path, "rev-a-retry", store=store)
    result = indexing.search_repository("r1", "login", store=store)
    assert result[0]["model"] == "fixture-a"
    assert loads == [("fixture-a", {})]

    monkeypatch.setenv("EMBEDDING_MODEL", "fixture-b")
    indexing.index_repository("r1", tmp_path, "rev-b", store=store)
    assert loads == [("fixture-a", {}), ("fixture-b", {})]
    second_model_embedder = embeddings.get_default_embedder()

    monkeypatch.setenv("EMBEDDING_MODEL_REVISION", "weights-v1")
    revision_embedder = embeddings.get_default_embedder()
    assert revision_embedder is not second_model_embedder
    assert revision_embedder.model_name == "fixture-b@weights-v1"
    indexing.index_repository("r1", tmp_path, "rev-c", store=store)
    assert loads[-1] == ("fixture-b", {"revision": "weights-v1"})


def test_default_embedder_cache_reuses_matching_batch_size_and_isolates_changes(
    monkeypatch,
):
    monkeypatch.setattr(embeddings, "_EMBEDDER_CACHE", {})
    monkeypatch.setenv("EMBEDDING_MODEL", "fixture-batch")
    monkeypatch.setenv("EMBEDDING_MODEL_REVISION", "weights-v1")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "8")

    first = embeddings.get_default_embedder()
    same_configuration = embeddings.get_default_embedder()

    assert same_configuration is first
    assert first.batch_size == 8

    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "16")
    different_batch_size = embeddings.get_default_embedder()

    assert different_batch_size is not first
    assert different_batch_size.batch_size == 16
    assert embeddings.get_default_embedder() is different_batch_size
