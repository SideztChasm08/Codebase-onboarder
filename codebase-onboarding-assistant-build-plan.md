# Build Plan: Codebase Onboarding Assistant (Python-only scope)

**Companion to:** `codebase-onboarding-assistant-spec.md`
**Scope decision:** Supports Python repositories only for v1. This simplifies chunking and symbol-graph construction — no need for multiple tree-sitter grammars or cross-language handling.

**Model decision:** Uses free, open-source models throughout — no paid API calls. LLM synthesis runs locally via Ollama (e.g., Qwen2.5-Coder or Llama 3.1 8B); embeddings run locally via `sentence-transformers` (e.g., `nomic-embed-text` or `bge-small-en`).

---

## Guiding Principle

Build the Python core (ingestion → RAG → symbol graph) as **standalone scripts first**, fully decoupled from any service infrastructure. This validates the hard, differentiating part of the project — chunking quality and hybrid retrieval — before investing time in API wiring, auth, or async queues.

Spring Boot and the async glue between services come later, since they follow comparatively standard, well-understood patterns.

---

## Step 1: Set Up Repos and Skeleton Services

Create two repos (or a monorepo with two folders): `spring-boot-service` and `python-service`. Get a bare "hello world" Spring Boot REST app and a bare FastAPI app running locally. Spin up Postgres and the vector DB (pgvector extension on Postgres, or standalone Chroma) via Docker Compose so the whole stack starts with one command.

## Step 2: Build the Ingestion + Chunking Pipeline (Python, standalone)

Clone a test Python repo, walk `.py` files, parse each with tree-sitter's Python grammar, chunk by function/class boundaries. Attach metadata to each chunk: file path, line range, containing class/module, docstring, and import list. Test on one real open-source Python repo (pick this now — you'll reuse it for every later step and for the final demo). Covers TICKET-201/202/203.

## Step 3: Build the Vector Index and Basic RAG Query (Python, standalone)

Embed the chunks from Step 2 using a local embedding model (`sentence-transformers` with `nomic-embed-text` or `bge-small-en`) and store them with metadata in the vector DB. Set up Ollama locally and pull a code-capable model (Qwen2.5-Coder recommended). Write a script that takes a question, retrieves top-k chunks, and calls the local LLM via Ollama's API to answer with citations. This is a working, if incomplete, RAG-over-code demo — a good checkpoint before adding complexity. Note: confirm your hardware can run the chosen model at usable speed before committing (7B–8B models want ~6–8GB VRAM; CPU-only works but is slower).

## Step 4: Build the Symbol Graph and Structural Queries

Since the repo scope is Python-only, use Python's built-in `ast` module (instead of tree-sitter queries) to parse function/class definitions and call sites into a graph. Support "find references to X" and "find definition of X" lookups. Build the query classifier that routes conceptual vs. structural questions to the right retrieval path. Covers TICKET-205/206/208. This is the differentiating piece of the project — don't rush it.

## Step 5: Wrap the Python Service in a Real API

Turn the scripts into FastAPI endpoints: `/index` (trigger indexing for a repo), `/query` (ask a question, get an answer + citations), `/status` (job state). Add token validation middleware (stub for now — real tokens arrive from Spring Boot in a later step).

## Step 6: Build the Spring Boot Control Plane

Auth (JWT), user/role model, repo CRUD, job status tracking. Covers TICKET-101–105. Spring Boot doesn't talk to Python yet at this point — it just manages its own state and exposes its own API.

## Step 7: Wire the Async Handoff

Add Kafka or RabbitMQ. Spring Boot publishes `IndexRequested` when a repo is submitted; Python consumes it, runs the pipeline from Steps 2–4, and publishes `IndexCompleted`/`IndexFailed` back. Spring Boot updates job status on receipt. Covers TICKET-106/107. Test the full loop: submit repo → status moves `pending → indexing → ready`.

## Step 8: Wire Token-Based Query Access

Spring Boot issues scoped tokens for repo access (TICKET-103); Python validates them on `/query` calls. A user can now only query repos they have a role on.

## Step 9: Build the Frontend

React app: repo submission form with live job status, and a chat interface for queries with expandable citations linking back to file/line. Keep it simple — functionality and citation clarity matter more than visual polish for a demo.

## Step 10: Prepare the Demo and Writeup

Use the same Python repo chosen in Step 2. Prepare 2–3 demo questions from the spec's Demo Plan section (one conceptual, one structural, optionally one combined). Write a short README covering architecture, key design decisions (why hybrid retrieval, why AST chunking, why `ast` module over tree-sitter given Python-only scope), and known limitations.

---

## Remaining Open Decisions

- **Specific model choice:** confirm Qwen2.5-Coder vs. Llama 3.1 8B (or another open-weight model) based on available hardware
- **Test repo for demos:** pick a real, mid-size open-source Python project (e.g., a Flask app, a mid-size Django project) — needs enough complexity to make "how does auth work" and "where is X used" genuinely interesting questions
