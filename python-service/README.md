# Python indexing service

This folder contains the standalone Python ingestion, indexing, and code-intelligence core. It remains independent of FastAPI and Spring Boot; those API/service integrations are a later milestone.

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

`query_classifier.classify_query()` deterministically returns `conceptual`, `structural`, or `ambiguous`, plus `semantic`, `structural`, or both routes. `structural_query.answer_structural_query()` returns structured evidence with file and line locations; ambiguous names return candidates, and missing names produce no fabricated evidence. Conceptual retrieval and LLM phrasing are not implemented yet: questions routed to semantic retrieval are explicitly marked `semantic_required`, and combined questions include structural evidence while indicating both routes for the future hybrid handler.

## Tests

```powershell
python -m pytest -q tests
```

The focused ticket tests are under `tests/`. The two PostgreSQL integration cases use a real database only when `PGVECTOR_TEST_DATABASE_URL` points to a disposable pgvector database. They are skipped otherwise. Use a separate, empty test database because the integration tests initialize a 3-dimensional schema; each test removes only its uniquely named test rows. The older root-level `test_*.py` files are standalone scripts, not part of this pytest suite.
