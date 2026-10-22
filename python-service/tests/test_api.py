import asyncio
import json

from main import create_app


class ASGIClient:
    """Tiny dependency-free ASGI caller for these HTTP contract tests."""
    def __init__(self, app): self.app = app
    def request(self, method, path, body=None):
        raw = json.dumps(body or {}).encode()
        messages = [{"type": "http.request", "body": raw, "more_body": False}]
        response = {}
        async def receive(): return messages.pop(0)
        async def send(message): response.update(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                 "query_string": b"", "headers": [(b"host", b"test")],
                 "client": ("test", 1), "server": ("test", 80)}
        asyncio.run(self.app(scope, receive, send))
        return response["status"], json.loads(response.get("body", b"{}"))
    def post(self, path, json): return Response(*self.request("POST", path, json))
    def get(self, path): return Response(*self.request("GET", path))


class Response:
    def __init__(self, status_code, data): self.status_code, self.data = status_code, data
    def json(self): return self.data


class FakeGraph:
    repo_id = "repo-a"
    revision = "rev-1"
    symbols = []
    def find_definitions(self, name): return []
    def find_references(self, name): return []


class FakeLLM:
    def generate(self, prompt): return "Evidence-backed answer."


def test_index_status_query_and_repository_isolation(tmp_path):
    def index_fn(repo_id, path, revision):
        return {"chunk_count": 1, "embedding_model": "fake"}
    app = create_app(index_fn=index_fn, search_fn=lambda *a, **k: [{
        "file_path": "src/a.py", "start_line": 1, "end_line": 2,
        "source": "def authenticate(): pass",
    }], graph_builder=lambda path, repo_id, revision: FakeGraph(), llm_client=FakeLLM())
    client = ASGIClient(app)
    bad = client.post("/index", json={"repo_id": "repo-a", "repo_path": str(tmp_path / "missing"), "revision": "rev-1"})
    assert bad.status_code == 422
    indexed = client.post("/index", json={"repo_id": "repo-a", "repo_path": str(tmp_path), "revision": "rev-1"})
    assert indexed.status_code == 200 and indexed.json()["status"] == "ready"
    assert client.get("/status/repo-a").json()["revision"] == "rev-1"
    assert client.post("/query", json={"repo_id": "repo-a", "question": "How does authentication work?"}).json()["citations"][0]["revision"] == "rev-1"
    assert client.post("/query", json={"repo_id": "repo-b", "question": "How does authentication work?"}).status_code == 409
    assert client.post("/query", json={"repo_id": "repo-a", "revision": "old", "question": "How does authentication work?"}).status_code == 404
    assert client.post("/query", json={"repo_id": "repo-a", "question": "   "}).status_code == 422


def test_index_failure_is_visible_in_status(tmp_path):
    app = create_app(index_fn=lambda *a: (_ for _ in ()).throw(RuntimeError("db offline")),
                     graph_builder=lambda *a: FakeGraph())
    client = ASGIClient(app)
    response = client.post("/index", json={"repo_id": "repo-a", "repo_path": str(tmp_path), "revision": "rev-1"})
    assert response.status_code == 500
    assert client.get("/status/repo-a").json()["status"] == "failed"
