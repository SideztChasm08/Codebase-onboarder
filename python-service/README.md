# Python indexing service

This folder contains the Python ingestion, indexing, and code-intelligence service. The FastAPI layer wraps the same standalone modules; Spring Boot and messaging remain outside this milestone.

## Chunk contract and indexing behavior

`chunk_schema.py` defines schema version 1. Each normalized chunk has a deterministic SHA-256 `chunk_id` based on repository ID, normalized relative path, chunk type, fully qualified lexical symbol (or module statement byte offset), and source hash. Records also retain revision, source, line range, docstring, imports, and comments. The chunker keeps its existing class and method chunks (which overlap) for now. Each top-level executable statement is emitted as a separate module chunk, so declarations between statements are not copied into module source. Comments are limited to the statement span; imports stay as metadata. Files containing only imports or declarations have no extra module chunk.

The index is scoped by `repo_id` and immutable revision (normally a Git commit SHA). Rows have a unique key `(repo_id, revision, chunk_id)`. A database transaction writes/upserts the complete revision and only then changes the active revision. Search joins to that active revision. Failed transactions roll back and leave the previous active revision available. Repeating a revision is idempotent and removes stale chunks for that revision after a successful write.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | none | PostgreSQL connection string, e.g. `postgresql://postgres:postgres@localhost:5432/codebase_assistant` for the checked-in Compose service |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Sentence Transformers model ID |
| `EMBEDDING_MODEL_REVISION` | none | Optional immutable Hugging Face revision (recommended for repeatable indexes) |
| `EMBEDDING_BATCH_SIZE` | `32` | Sentence Transformers' internal encode batch size when the process-scoped model adapter is first created |
| `VECTOR_DIMENSION` | `384` | Dimension of the pgvector column; must match the model output |
| `PGVECTOR_TEST_DATABASE_URL` | none | Enables real database integration tests; use a disposable test database |

The BGE small English model is a compact general English retrieval baseline, not a code-specialized model. BGE query encoding uses its recommended retrieval instruction; chunk/document encoding uses source text directly. Evaluate retrieval on representative code questions before treating the model choice as final. The first model load downloads model files from Hugging Face if they are not cached. This may require network access and several hundred MB of local storage. Set `EMBEDDING_MODEL_REVISION` to an immutable model revision for repeatable deployments. The adapter is cached per process by model ID, revision, and batch size; restart the process after changing model settings. Search uses one SQL statement to scope retrieval to the requested repository, active revision, and exact model identity. Model changes with a different dimension require a deliberate schema migration and a full re-index.

## Setup and schema initialization

From the repository root, start the existing PostgreSQL/pgvector service:

```powershell
docker compose up -d postgres
```

From `python-service`, install dependencies and configure the connection:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/codebase_assistant"
python initialize_db.py
```

Schema initialization creates the `vector` extension, `repository_indexes`, and `code_chunks` tables. It checks that an existing embedding column has the configured dimension; it does not silently migrate dimensions. The checked-in Compose credentials are for local development only.

## End-to-end indexing and search

Pass a local checkout and an immutable revision identifier (usually its commit SHA):

```powershell
python index_cli.py index --repo-id demo-repo --path "C:\path\to\python-repository" --revision "<git-commit-sha>"
python index_cli.py search --repo-id demo-repo --query "How does authentication validate a user?" --limit 5
```

The callable API is `indexing.index_repository(repo_id, repo_path, revision)` and `indexing.search_repository(repo_id, query)`. The lower-level `PgVectorStore.search` requires `model_name` so it can filter in the same SQL statement; `search_repository` supplies it from the query embedder. Tests can inject `FakeEmbedder` and a fake store; `FakeEmbedder` is deterministic for plumbing checks and must not be used to judge semantic relevance.

## Symbol graph and query routing (TICKET-205/206/208)

`symbol_graph.py` uses Python's built-in `ast` module and the same Python file discovery rules as repository ingestion. It builds deterministic definitions, call sites, resolved call edges, unresolved call sites, and syntax-error reports. Definitions include module-qualified names, methods, and nested functions. `find_definitions()`, `find_references()`, and `find_callers()` are available on the resulting `SymbolGraph`. Calls are resolved when local scope, same-module names, imported symbols/aliases, module aliases, or `self`/`cls` methods identify one definition. Ambiguous or dynamic calls stay unresolved; this is a best-effort graph, not complete static analysis.

The vector schema has no graph tables. Graph snapshots are therefore separate JSON artifacts tagged with `repo_id` and `revision`; the query CLI checks both before lookup. Rebuild the snapshot from the same checkout and immutable revision as the vector index:

```powershell
python graph_cli.py build --repo-id demo-repo --path "C:\path\to\python-repository" --revision "<git-commit-sha>" --output "graphs\demo-repo-<git-commit-sha>.json"
python graph_cli.py query --repo-id demo-repo --revision "<git-commit-sha>" --graph "graphs\demo-repo-<git-commit-sha>.json" --question "Where is validate_token defined?"
python graph_cli.py query --repo-id demo-repo --revision "<git-commit-sha>" --graph "graphs\demo-repo-<git-commit-sha>.json" --question "Where is validate_token called?"
```

`query_classifier.classify_query()` deterministically returns `conceptual`, `structural`, or `ambiguous`, plus `semantic`, `structural`, or both routes. `structural_query.answer_structural_query()` returns structured evidence with file and line locations; ambiguous names return candidates, and missing names produce no fabricated evidence. `answering.py` combines classifier routing with active-revision semantic search and graph lookup. Structural queries do not use vector search to identify definitions or references.

## Tests

```powershell
python -m pytest -q tests
```

The focused ticket tests are under `tests/`, including fake-client synthesis and FastAPI request/response coverage. The two PostgreSQL integration cases use a real database only when `PGVECTOR_TEST_DATABASE_URL` points to a disposable pgvector database. They are skipped otherwise. Use a separate, empty test database because the integration tests initialize a 3-dimensional schema; each test removes only its uniquely named test rows. The older root-level `test_*.py` files are standalone scripts, not part of this pytest suite.

## Local synthesis and HTTP API (TICKET-207/209)

Conceptual questions retrieve top-k chunks from the active vector revision and pass only retrieved evidence to an injectable chat client. The default adapter calls Ollama's local `/api/chat` endpoint. Structural questions use the AST symbol graph directly; combined questions send semantic and structural evidence to synthesis. Every response includes structured citations with `repository_id`, `revision`, `file_path`, `start_line`, `end_line`, and `source_type`; locations come from chunk metadata or graph evidence. With no evidence, the service returns `insufficient_evidence` without calling the model. Model failures surface as API 503.

Install Ollama separately, pull the default model, and start its local service:

```powershell
ollama pull qwen2.5-coder:7b
ollama serve
```

Set `OLLAMA_BASE_URL` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `qwen2.5-coder:7b`), and `OLLAMA_TIMEOUT_SECONDS` (default `120`). Ollama and model downloads are not needed by automated tests, which inject a fake client. Real LLM synthesis was not exercised as part of the automated suite; manually query the API after Ollama is running to verify local model setup.

After the database setup above, run from `python-service`:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Index a local checkout (use an immutable commit SHA as revision), then query it:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/index -ContentType 'application/json' -Body '{"repo_id":"demo-repo","repo_path":"C:\\path\\to\\repo","revision":"<git-commit-sha>"}'
Invoke-RestMethod http://127.0.0.1:8000/status/demo-repo
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/query -ContentType 'application/json' -Body '{"repo_id":"demo-repo","question":"How does authentication work?","limit":5}'
```

`POST /index` takes `repo_id`, local `repo_path`, and `revision`; `GET /status/{repo_id}` reports `indexing`, `ready`, or `failed`; `POST /query` takes `repo_id`, `question`, optional active `revision`, and `limit` (1–20). `GET /health` is also available. API status and graph snapshots are process-local and are lost on restart; re-index to restore them. This milestone intentionally has no authentication and accepts local paths, so run it only in a trusted local environment. It does not clone remote URLs or add Spring Boot/messaging infrastructure.
