"""FastAPI interface for the standalone indexing and query pipeline."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from answering import OllamaChatClient, answer_query
from indexing import index_repository, search_repository
from symbol_graph import build_symbol_graph


class IndexRequest(BaseModel):
    repo_id: str = Field(min_length=1, max_length=200)
    repo_path: str = Field(min_length=1, max_length=4096)
    revision: str = Field(min_length=1, max_length=200)


class QueryRequest(BaseModel):
    repo_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)
    revision: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)


def create_app(index_fn=index_repository, search_fn=search_repository,
               graph_builder=build_symbol_graph, llm_client=None):
    app = FastAPI(title="Codebase Onboarding Assistant")
    app.state.jobs = {}
    app.state.graphs = {}
    app.state.llm_client = llm_client

    @app.get("/health")
    def health():
        return {"status": "Python service is up"}

    @app.post("/index")
    def index(request: IndexRequest):
        repo_id = request.repo_id.strip()
        revision = request.revision.strip()
        path = Path(request.repo_path).expanduser().resolve()
        if not repo_id or not revision or not path.is_dir():
            raise HTTPException(status_code=422, detail="repo_id, revision, and an existing repository directory are required")
        app.state.jobs[repo_id] = {"status": "indexing", "revision": revision}
        try:
            result = index_fn(repo_id, path, revision)
            graph = graph_builder(path, repo_id, revision)
            app.state.graphs[repo_id] = graph
            app.state.jobs[repo_id] = {"status": "ready", "revision": revision,
                                       "chunk_count": result["chunk_count"]}
            return {**app.state.jobs[repo_id], "repo_id": repo_id,
                    "embedding_model": result.get("embedding_model")}
        except Exception as exc:
            app.state.jobs[repo_id] = {"status": "failed", "revision": revision,
                                       "error": str(exc)}
            raise HTTPException(status_code=500, detail=f"Indexing failed: {exc}") from exc

    @app.get("/status/{repo_id}")
    def status(repo_id: str):
        job = app.state.jobs.get(repo_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Repository has no indexing status")
        return {"repo_id": repo_id, **job}

    @app.post("/query")
    def query(request: QueryRequest):
        job = app.state.jobs.get(request.repo_id)
        if job is None or job.get("status") != "ready":
            raise HTTPException(status_code=409, detail="Repository is not indexed and ready")
        if request.revision and request.revision != job["revision"]:
            raise HTTPException(status_code=404, detail="Requested revision is not the active revision")
        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="question must not be blank")
        try:
            result = answer_query(request.repo_id, job["revision"], question,
                                  app.state.graphs.get(request.repo_id), search_fn,
                                  app.state.llm_client or OllamaChatClient(), request.limit)
            return result
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()
