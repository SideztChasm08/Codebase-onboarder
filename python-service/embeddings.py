"""Replaceable local embedding adapters for code chunks and search queries."""

from __future__ import annotations

import hashlib
import os
import threading
from typing import Protocol, Sequence


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """Sentence Transformers adapter; loads the configured model once per instance."""

    def __init__(
        self,
        model_name: str | None = None,
        batch_size: int = 32,
        model_revision: str | None = None,
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.model_id = model_name or os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        self.model_revision = (
            model_revision if model_revision is not None
            else os.getenv("EMBEDDING_MODEL_REVISION")
        ) or None
        self.model_name = (
            f"{self.model_id}@{self.model_revision}"
            if self.model_revision else self.model_id
        )
        self.batch_size = batch_size
        self._dimension = 384 if self.model_id == "BAAI/bge-small-en-v1.5" else None
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    model_id, separator, revision = self.model_name.partition("@")
                    options = {"revision": revision} if separator else {}
                    self._model = SentenceTransformer(model_id, **options)
                    actual_dimension = self._model.get_sentence_embedding_dimension()
                    if actual_dimension is None or actual_dimension < 1:
                        raise ValueError("Embedding model did not report a valid dimension")
                    if self._dimension and actual_dimension != self._dimension:
                        raise ValueError(
                            f"Expected {self._dimension} dimensions for {self.model_name}, "
                            f"got {actual_dimension}"
                        )
                    self._dimension = int(actual_dimension)
        return self._model

    @property
    def dimension(self):
        if self._dimension is None:
            self._load()
        return self._dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        result = [[float(value) for value in vector] for vector in vectors]
        validate_vectors(result, len(texts), self.dimension)
        return result

    def embed_query(self, text: str) -> list[float]:
        query = text
        if self.model_id == "BAAI/bge-small-en-v1.5":
            query = "Represent this sentence for searching relevant passages: " + text
        return self.embed([query])[0]


class FakeEmbedder:
    """Small deterministic embedder for tests and offline examples; not semantic."""

    model_name = "fake-hash-v1"

    def __init__(self, dimension: int = 16, batch_size: int = 32):
        if dimension < 1 or batch_size < 1:
            raise ValueError("dimension and batch_size must be positive")
        self.dimension = dimension
        self.batch_size = batch_size
        self.batches: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        result = []
        for offset in range(0, len(texts), self.batch_size):
            batch = list(texts[offset : offset + self.batch_size])
            self.batches.append(batch)
            for text in batch:
                raw = hashlib.shake_256(text.encode("utf-8")).digest(self.dimension * 4)
                result.append(
                    [int.from_bytes(raw[i : i + 4], "big") / 2147483647.5 - 1
                     for i in range(0, len(raw), 4)]
                )
        validate_vectors(result, len(texts), self.dimension)
        return result

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


def validate_vectors(vectors, expected_count: int, dimension: int) -> None:
    if len(vectors) != expected_count:
        raise ValueError(f"Expected {expected_count} vectors, got {len(vectors)}")
    if dimension < 1:
        raise ValueError("Embedding dimension must be positive")
    for index, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise ValueError(
                f"Vector {index} has dimension {len(vector)}; expected {dimension}"
            )
        if not all(isinstance(value, (int, float)) and float("-inf") < float(value) < float("inf") for value in vector):
            raise ValueError(f"Vector {index} contains a non-finite or non-numeric value")


_EMBEDDER_CACHE: dict[tuple[str, str | None, int], SentenceTransformerEmbedder] = {}
_EMBEDDER_CACHE_LOCK = threading.Lock()


def get_default_embedder() -> SentenceTransformerEmbedder:
    """Return the process-shared adapter for the current model configuration.

    Cache keys include the model ID, immutable revision, and batch size. The
    lock covers cache misses so concurrent first callers cannot create duplicate
    adapters/model loaders for the same configuration.
    """
    model_id = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    revision = os.getenv("EMBEDDING_MODEL_REVISION") or None
    batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    key = (model_id, revision, batch_size)
    with _EMBEDDER_CACHE_LOCK:
        if key not in _EMBEDDER_CACHE:
            _EMBEDDER_CACHE[key] = SentenceTransformerEmbedder(
                model_id, batch_size=batch_size, model_revision=revision
            )
        return _EMBEDDER_CACHE[key]
