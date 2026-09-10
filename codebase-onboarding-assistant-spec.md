# Project Spec: Codebase Onboarding Assistant

**Project Type:** Personal/Portfolio Project
**Status:** Planning
**Owner:** Shobhit

---

## 1. Overview

**Aim:** New engineers joining a codebase spend days figuring out things like "how does auth work here" or "where is this function used before I break something." This project builds a system that lets a developer ask natural-language questions about an unfamiliar codebase and get grounded, cited answers — combining semantic understanding (RAG) with structural understanding (symbol/call-graph search).

**Why it's worth building:** Most RAG demos work on prose/documents. Applying RAG to *code* forces harder problems — AST-aware chunking, distinguishing conceptual questions from structural ones, and returning citations precise enough to trust. It also gives a legitimate reason to split work across a Java (Spring Boot) control-plane service and a Python indexing/RAG service, connected asynchronously.

**High-level flow:**
1. User submits a repo URL via the frontend.
2. Spring Boot creates a `Repo` record and publishes an `IndexRequested` event.
3. Python service consumes the event, clones the repo, parses + chunks + embeds it, builds a symbol graph, and publishes `IndexCompleted`.
4. Spring Boot updates job status.
5. User queries the repo through the chat UI; queries are routed to Python service (authorized via token issued by Spring Boot).
6. Answers return with cited file/line references.

---

## 2. Architecture Components

| Component | Responsibility |
|---|---|
| Spring Boot service | Users, roles, repo/job orchestration, control plane |
| Python service | Ingestion, chunking, indexing (vector + symbol graph), query routing, answer synthesis |
| Message queue (Kafka/RabbitMQ) | Async handoff between Spring Boot and Python for indexing jobs |
| Frontend (React) | Chat interface with citation display |
| Vector DB (pgvector/Chroma) | Semantic chunk storage/retrieval |
| Symbol graph store | Structural reference storage (custom, in-memory or Postgres-backed) |

---

## 3. MUST-HAVE — Epics & Tickets

### EPIC 1: Auth & Access Control (Spring Boot)

- **TICKET-101**: Implement JWT-based authentication (signup/login/token refresh)
  - *AC:* Users can register, log in, receive a valid JWT, and refresh an expiring token.
- **TICKET-102**: Implement per-repo role model (`owner`, `contributor`, `viewer`)
  - *AC:* Roles are assignable per repo; API endpoints enforce role checks (e.g., only `owner`/`contributor` can trigger re-index; `viewer` can only query).
- **TICKET-103**: Issue scoped access tokens for Python service queries
  - *AC:* Spring Boot issues a short-lived token encoding user identity + repo access; Python service validates it before answering a query.

### EPIC 2: Repo & Job Management (Spring Boot)

- **TICKET-104**: CRUD endpoints for tracked repositories
  - *AC:* Create/list/delete a tracked repo record (URL, name, owner, created date).
- **TICKET-105**: Job status tracking
  - *AC:* Each indexing job has a status field: `pending → indexing → ready → failed`, queryable via API and reflected in the UI.
- **TICKET-106**: Publish `IndexRequested` event on repo submission
  - *AC:* Submitting a repo publishes an event to the queue with repo URL + job ID; event is durable (not lost if consumer is briefly down).
- **TICKET-107**: Consume `IndexCompleted`/`IndexFailed` events and update job status
  - *AC:* Spring Boot listens for completion events from Python and updates the corresponding job record.

### EPIC 3: Ingestion & Chunking (Python)

- **TICKET-201**: Repo cloning + file tree walk
  - *AC:* Given a repo URL, clone locally, enumerate source files, filter by supported language(s).
- **TICKET-202**: AST-aware chunking via tree-sitter
  - *AC:* Each file is parsed and chunked by function/class boundaries (not fixed token windows); no chunk splits a function/class body mid-way.
- **TICKET-203**: Chunk metadata attachment
  - *AC:* Every chunk stores file path, line range, containing class/module, docstring/comments, and import list.

### EPIC 4: Indexing (Python)

- **TICKET-204**: Embedding generation + vector store write
  - *AC:* Each chunk is embedded and stored in the vector DB with its metadata; retrievable by similarity search.
- **TICKET-205**: Symbol/call graph construction
  - *AC:* Build a graph of function/class definitions and call sites using tree-sitter queries or Python's `ast` module (scope: Python or JS repos to start).
  - *AC:* Graph supports "find all references to symbol X" and "find definition of symbol X."

### EPIC 5: Query Handling & Synthesis (Python)

- **TICKET-206**: Query classifier (conceptual vs. structural)
  - *AC:* Incoming question is classified and routed: conceptual → vector index; structural → symbol graph; ambiguous → both.
- **TICKET-207**: Conceptual answer synthesis via RAG
  - *AC:* Top-k relevant chunks retrieved, passed to LLM with instruction to answer only from provided context.
- **TICKET-208**: Structural answer synthesis via symbol graph
  - *AC:* Direct graph lookup for "where is X used/defined" style questions; LLM only used to phrase the final answer, not to retrieve.
- **TICKET-209**: Citation attachment
  - *AC:* Every answer includes specific file path(s) and line range(s) backing the claim.

### EPIC 6: Frontend

- **TICKET-301**: Repo submission + job status UI
  - *AC:* User can submit a repo URL and see live status (pending/indexing/ready/failed).
- **TICKET-302**: Chat interface
  - *AC:* User can ask questions about a `ready` repo and see answers with clickable/expandable citations.

---

## 4. GOOD-TO-HAVE — Epics & Tickets

*(Explicitly deprioritized — build only if the must-haves are complete and stable. Listed in priority order.)*

### EPIC 7: Auto-Reindexing

- **TICKET-401**: Webhook endpoint for repo push events
  - *AC:* Repo push triggers automatic re-indexing without manual user action.

### EPIC 8: Resilience

- **TICKET-402**: Circuit breaker for Python service calls
  - *AC:* If Python service is unavailable, Spring Boot degrades gracefully (queues request, does not hard-fail) using Resilience4j.
- **TICKET-403**: Message queue retry semantics
  - *AC:* Failed indexing jobs are retried with backoff before being marked `failed`.

### EPIC 9: Rate Limiting

- **TICKET-404**: Per-user query quotas
  - *AC:* Users are limited to N queries per time window; exceeding it returns a clear error rather than silently degrading.

---

## 5. Out of Scope (for now)

- Multi-language support beyond the initial 1–2 languages chosen
- Full static-analysis-grade call graph (deep interprocedural analysis)
- Team billing/subscription features
- Mobile client

---

## 6. Suggested Tech Stack Reference

| Layer | Choice |
|---|---|
| Control plane | Spring Boot, Spring Security (JWT), Postgres |
| Async | Kafka or RabbitMQ |
| Indexing/RAG | Python, tree-sitter, embedding model (API-based or local), pgvector/Chroma |
| Symbol graph | Custom, tree-sitter query captures or Python `ast` module |
| LLM (synthesis) | Swappable chat-completion API — do not hardcode a single provider |
| Frontend | React |

---

## 7. Demo Plan

Prepare 2–3 questions against a real mid-size open-source repo:
- One conceptual, multi-file question (shows RAG synthesis + citations)
- One structural "where is X used" question (shows symbol graph beating naive RAG)
- Optionally, one combined question ("how does X work, and what breaks if I change it")
