import math

import pytest

from embeddings import FakeEmbedder, validate_vectors


def test_fake_embedder_batches_and_is_deterministic():
    embedder = FakeEmbedder(dimension=8, batch_size=2)
    vectors = embedder.embed(["alpha", "beta", "gamma"])
    assert [len(batch) for batch in embedder.batches] == [2, 1]
    assert len(vectors) == 3
    assert all(len(vector) == 8 for vector in vectors)
    assert vectors[0] == embedder.embed(["alpha"])[0]


@pytest.mark.parametrize("vectors,count,dimension", [
    ([[1.0]], 2, 1),
    ([[1.0, 2.0]], 1, 1),
    ([[math.nan]], 1, 1),
])
def test_invalid_embedding_outputs_are_rejected(vectors, count, dimension):
    with pytest.raises(ValueError):
        validate_vectors(vectors, count, dimension)
