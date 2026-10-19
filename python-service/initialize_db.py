"""Initialize the configured pgvector schema."""

import os

from vector_store import PgVectorStore


if __name__ == "__main__":
    dimension = int(os.getenv("VECTOR_DIMENSION", "384"))
    PgVectorStore(dimension=dimension).initialize()
    print(f"Initialized pgvector schema for {dimension}-dimension embeddings")
