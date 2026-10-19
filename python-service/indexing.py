"""Standalone repository -> canonical chunks -> embeddings -> pgvector pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from chunk_schema import normalize_chunk
from embeddings import get_default_embedder
from parser.tree_sitter_chunker import chunk_file
from repository_ingestion import discover_source_files
from vector_store import PgVectorStore


def collect_chunks(repo_path, repo_id):
    """Chunk supported files and normalize them to the versioned storage contract."""
    root = Path(repo_path).resolve()
    chunks = []
    for relative_path in discover_source_files(root):
        file_chunks = chunk_file(root / relative_path, repo_root=root)
        for chunk in file_chunks:
            chunks.append(normalize_chunk(chunk, repo_id))
    return chunks


def index_repository(
    repo_id,
    repo_path,
    revision,
    embedder=None,
    store=None,
    batch_size=32,
):
    """Index a complete revision; storage activates it only on transaction commit."""
    if not repo_id or not revision:
        raise ValueError("repo_id and revision are required")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    embedder = embedder or get_default_embedder()
    store = store or PgVectorStore(
        dimension=int(os.getenv("VECTOR_DIMENSION", "384"))
    )
    if embedder.dimension != store.dimension:
        raise ValueError(
            f"Embedder dimension {embedder.dimension} does not match "
            f"vector-store dimension {store.dimension}"
        )

    chunks = collect_chunks(repo_path, str(repo_id))
    records = []
    for offset in range(0, len(chunks), batch_size):
        batch = chunks[offset : offset + batch_size]
        vectors = embedder.embed([chunk["source"] for chunk in batch])
        if len(vectors) != len(batch):
            raise ValueError("Embedder returned a different number of vectors than inputs")
        for chunk, vector in zip(batch, vectors):
            records.append({"chunk": chunk, "embedding": vector})

    # An empty repo is still a successful empty generation and clears that revision.
    store.replace_generation(
        str(repo_id), str(revision), embedder.model_name, records
    )
    return {
        "repo_id": str(repo_id),
        "revision": str(revision),
        "chunk_count": len(records),
        "embedding_model": embedder.model_name,
    }


def search_repository(repo_id, query, embedder=None, store=None, limit=5):
    embedder = embedder or get_default_embedder()
    store = store or PgVectorStore(
        dimension=int(os.getenv("VECTOR_DIMENSION", "384"))
    )
    if embedder.dimension != store.dimension:
        raise ValueError("Embedder and vector-store dimensions do not match")
    return store.search(
        str(repo_id), embedder.embed_query(query), limit=limit,
        model_name=embedder.model_name,
    )
