CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS repository_indexes (
    repo_id TEXT PRIMARY KEY,
    active_revision TEXT,
    embedding_model TEXT NOT NULL,
    indexed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS code_chunks (
    repo_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    chunk_id CHAR(64) NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding VECTOR({{VECTOR_DIMENSION}}) NOT NULL,
    file_path TEXT NOT NULL,
    chunk_type TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    start_line INTEGER NOT NULL CHECK (start_line > 0),
    end_line INTEGER NOT NULL CHECK (end_line >= start_line),
    source TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (repo_id, revision, chunk_id)
);

CREATE INDEX IF NOT EXISTS code_chunks_repo_revision_idx
    ON code_chunks (repo_id, revision);
