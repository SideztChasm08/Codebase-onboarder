"""Transactional PostgreSQL/pgvector storage for repository chunk generations."""

from __future__ import annotations

import json
import os
from pathlib import Path

from embeddings import validate_vectors


DEFAULT_DIMENSION = 384
SCHEMA_PATH = Path(__file__).parent / "schema" / "001_vector_index.sql"


class PgVectorStore:
    def __init__(self, database_url: str | None = None, dimension: int = DEFAULT_DIMENSION):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL must be set (see python-service/README.md)")
        if dimension < 1:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def _connect(self, register_vector_type=True):
        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as exc:
            raise RuntimeError("Install python-service requirements to use pgvector") from exc
        connection = psycopg.connect(self.database_url)
        if register_vector_type:
            register_vector(connection)
        return connection

    def initialize(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8").replace(
            "{{VECTOR_DIMENSION}}", str(self.dimension)
        )
        with self._connect(register_vector_type=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                from pgvector.psycopg import register_vector

                register_vector(connection)
                cursor.execute(
                    """SELECT format_type(a.atttypid, a.atttypmod)
                       FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                       WHERE c.relname='code_chunks' AND a.attname='embedding'
                         AND a.attnum > 0 AND NOT a.attisdropped"""
                )
                row = cursor.fetchone()
                expected = f"vector({self.dimension})"
                if not row or row[0] != expected:
                    raise ValueError(
                        f"Database embedding column is {row[0] if row else 'missing'}; "
                        f"configured dimension requires {expected}. Use a fresh database "
                        "or an explicit migration before changing dimensions."
                    )

    def replace_generation(self, repo_id, revision, model_name, records) -> None:
        """Atomically persist a complete generation and make it active."""
        for record in records:
            validate_vectors([record["embedding"]], 1, self.dimension)
            if record["chunk"]["repo_id"] != str(repo_id):
                raise ValueError("Chunk repository does not match generation repository")

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO repository_indexes (repo_id, active_revision, embedding_model)
                       VALUES (%s, NULL, %s) ON CONFLICT (repo_id) DO NOTHING""",
                    (str(repo_id), model_name),
                )
                for record in records:
                    chunk = record["chunk"]
                    metadata = {key: value for key, value in chunk.items()
                                if key not in {"source", "repo_id", "chunk_id"}}
                    cursor.execute(
                        """INSERT INTO code_chunks (
                               repo_id, revision, chunk_id, embedding_model, embedding,
                               file_path, chunk_type, symbol_name, qualified_name,
                               start_line, end_line, source, metadata
                           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                           ON CONFLICT (repo_id, revision, chunk_id) DO UPDATE SET
                               embedding_model = EXCLUDED.embedding_model,
                               embedding = EXCLUDED.embedding,
                               file_path = EXCLUDED.file_path,
                               chunk_type = EXCLUDED.chunk_type,
                               symbol_name = EXCLUDED.symbol_name,
                               qualified_name = EXCLUDED.qualified_name,
                               start_line = EXCLUDED.start_line,
                               end_line = EXCLUDED.end_line,
                               source = EXCLUDED.source,
                               metadata = EXCLUDED.metadata""",
                        (str(repo_id), revision, chunk["chunk_id"], model_name,
                         record["embedding"], chunk["file"], chunk["type"], chunk["name"],
                         chunk["qualified_name"], chunk["start_line"], chunk["end_line"],
                         chunk["source"], json.dumps(metadata)),
                    )
                current_ids = [record["chunk"]["chunk_id"] for record in records]
                if current_ids:
                    cursor.execute(
                        "DELETE FROM code_chunks WHERE repo_id=%s AND revision=%s AND NOT (chunk_id::text = ANY(%s::text[]))",
                        (str(repo_id), revision, current_ids),
                    )
                else:
                    cursor.execute(
                        "DELETE FROM code_chunks WHERE repo_id=%s AND revision=%s",
                        (str(repo_id), revision),
                    )
                cursor.execute(
                    """UPDATE repository_indexes SET active_revision=%s, embedding_model=%s,
                              indexed_at=now() WHERE repo_id=%s""",
                    (revision, model_name, str(repo_id)),
                )
            # The connection context commits only after all rows and activation succeed.

    def search(self, repo_id, query_embedding, limit=5, model_name=None):
        validate_vectors([query_embedding], 1, self.dimension)
        if limit < 1:
            raise ValueError("limit must be positive")
        if not model_name:
            raise ValueError("model_name is required to prevent cross-model vector search")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """WITH active AS (
                           SELECT active_revision, embedding_model
                           FROM repository_indexes WHERE repo_id = %s
                       )
                       SELECT c.chunk_id, c.file_path, c.chunk_type, c.symbol_name,
                              c.qualified_name, c.start_line, c.end_line, c.source,
                              c.metadata, c.embedding_model,
                              (c.embedding <=> %s) AS distance
                       FROM code_chunks c
                       JOIN active r ON r.active_revision = c.revision
                           AND r.embedding_model = c.embedding_model
                       WHERE c.repo_id = %s AND r.embedding_model = %s
                       ORDER BY c.embedding <=> %s LIMIT %s""",
                    (str(repo_id), query_embedding, str(repo_id), model_name,
                     query_embedding, limit),
                )
                columns = [description.name for description in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def count_chunks(self, repo_id, revision=None):
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if revision is None:
                    cursor.execute(
                        """SELECT count(*) FROM code_chunks c JOIN repository_indexes r
                           ON r.repo_id=c.repo_id AND r.active_revision=c.revision
                           WHERE c.repo_id=%s""", (str(repo_id),)
                    )
                else:
                    cursor.execute(
                        "SELECT count(*) FROM code_chunks WHERE repo_id=%s AND revision=%s",
                        (str(repo_id), revision),
                    )
                return cursor.fetchone()[0]
