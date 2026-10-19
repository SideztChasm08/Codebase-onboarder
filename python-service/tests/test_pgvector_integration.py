"""Real database tests; skipped unless PGVECTOR_TEST_DATABASE_URL is configured."""

import os
import uuid

import pytest

from vector_store import PgVectorStore


DATABASE_URL = os.getenv("PGVECTOR_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PGVECTOR_TEST_DATABASE_URL is not set")


def chunk(repo, chunk_id, name, source, line):
    return {
        "repo_id": repo, "chunk_id": chunk_id * 64, "file": f"{name}.py",
        "type": "function", "name": name, "qualified_name": name,
        "start_line": line, "end_line": line, "source": source,
        "schema_version": 1, "source_hash": "a" * 64,
    }


def test_upsert_generation_filtering_order_and_atomic_failure():
    store = PgVectorStore(DATABASE_URL, dimension=3)
    store.initialize()
    repo = f"test-{uuid.uuid4()}"
    records = [
        {"chunk": chunk(repo, "a", "alpha", "authentication login", 1), "embedding": [1, 0, 0]},
        {"chunk": chunk(repo, "b", "beta", "database pool", 2), "embedding": [0, 1, 0]},
    ]
    try:
        store.replace_generation(repo, "rev-1", "test-v1", records)
        store.replace_generation(repo, "rev-1", "test-v1", records)
        assert store.count_chunks(repo) == 2
        store.replace_generation(repo, "rev-1", "test-v1", [records[0]])
        assert store.count_chunks(repo) == 1
        results = store.search(repo, [1, 0, 0], limit=2, model_name="test-v1")
        assert [result["symbol_name"] for result in results] == ["alpha"]
        assert store.search(repo + "-other", [1, 0, 0], model_name="test-v1") == []
        assert store.search(repo, [1, 0, 0], model_name="wrong-model") == []

        store.replace_generation(repo, "rev-2", "test-v1", [records[1]])
        assert store.count_chunks(repo) == 1
        assert store.count_chunks(repo, "rev-1") == 1

        malformed = {"chunk": {"repo_id": repo, "chunk_id": "c" * 64},
                     "embedding": [0, 0, 1]}
        with pytest.raises(KeyError):
            store.replace_generation(repo, "rev-3", "test-v1", [records[0], malformed])
        # rev-2 remains active even though a new generation failed mid-transaction.
        assert store.count_chunks(repo) == 1
        assert store.search(repo, [0, 1, 0], limit=1,
                            model_name="test-v1")[0]["symbol_name"] == "beta"
    finally:
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM code_chunks WHERE repo_id=%s", (repo,))
                cursor.execute("DELETE FROM repository_indexes WHERE repo_id=%s", (repo,))


def test_concurrent_model_and_revision_switch_never_returns_other_model_rows():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store = PgVectorStore(DATABASE_URL, dimension=3)
    store.initialize()
    repo = f"concurrent-{uuid.uuid4()}"
    record_a = {"chunk": chunk(repo, "a", "alpha", "model a", 1),
                "embedding": [1, 0, 0]}
    record_b = {"chunk": chunk(repo, "b", "beta", "model b", 2),
                "embedding": [0, 1, 0]}
    store.replace_generation(repo, "rev-a", "model-a", [record_a])
    store.replace_generation(repo, "rev-b", "model-b", [record_b])
    store.replace_generation(repo, "rev-a", "model-a", [record_a])
    barrier = Barrier(2)

    def search_while_switching():
        barrier.wait()
        found = []
        for _ in range(30):
            found.extend(store.search(repo, [1, 0, 0], model_name="model-a"))
        return found

    def switch_active_revision():
        barrier.wait()
        for index in range(30):
            if index % 2:
                store.replace_generation(repo, "rev-a", "model-a", [record_a])
            else:
                store.replace_generation(repo, "rev-b", "model-b", [record_b])

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            search_future = executor.submit(search_while_switching)
            switch_future = executor.submit(switch_active_revision)
            rows = search_future.result()
            switch_future.result()
        store.replace_generation(repo, "rev-a", "model-a", [record_a])
        final_rows = store.search(repo, [1, 0, 0], model_name="model-a")
        assert final_rows and final_rows[0]["symbol_name"] == "alpha"
        assert all(row["embedding_model"] == "model-a" for row in rows)
        assert all(row["symbol_name"] == "alpha" for row in rows)
    finally:
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM code_chunks WHERE repo_id=%s", (repo,))
                cursor.execute("DELETE FROM repository_indexes WHERE repo_id=%s", (repo,))
