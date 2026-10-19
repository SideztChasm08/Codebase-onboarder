from vector_store import PgVectorStore


class EmptyCursor:
    description = []

    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters):
        self.calls.append((sql, parameters))

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self):
        self.cursor_instance = EmptyCursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance


def test_search_uses_one_statement_for_active_revision_and_model(monkeypatch):
    connection = FakeConnection()
    store = PgVectorStore("postgresql://unused", dimension=3)
    monkeypatch.setattr(store, "_connect", lambda: connection)

    assert store.search(
        "repo-1", [1.0, 0.0, 0.0], model_name="model@revision"
    ) == []

    assert len(connection.cursor_instance.calls) == 1
    sql, parameters = connection.cursor_instance.calls[0]
    normalized_sql = " ".join(sql.lower().split())
    assert "with active as" in normalized_sql
    assert "active_revision = c.revision" in normalized_sql
    assert "r.embedding_model = c.embedding_model" in normalized_sql
    assert "r.embedding_model = %s" in normalized_sql
    assert parameters[0] == "repo-1" and parameters[2] == "repo-1"
    assert parameters[3] == "model@revision"


def test_search_requires_query_model_identity():
    store = PgVectorStore("postgresql://unused", dimension=3)
    try:
        store.search("repo-1", [1.0, 0.0, 0.0])
    except ValueError as exc:
        assert "model_name is required" in str(exc)
    else:
        raise AssertionError("search accepted an unlabelled query vector")
