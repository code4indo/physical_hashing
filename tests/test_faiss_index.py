"""Tests for the FAISS vector index wrapper."""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from arch_fingerprint.search.faiss_index import SearchResult, VectorIndex


@pytest.fixture
def index() -> VectorIndex:
    """Create a fresh 128-dim vector index for testing."""
    return VectorIndex(dimension=128)


def _random_vector(dim: int = 128) -> np.ndarray:
    """Generate a random L2-normalized vector."""
    vec = np.random.randn(dim).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec


class TestVectorIndex:
    """Test suite for FAISS VectorIndex operations."""

    def test_empty_index(self, index):
        """Empty index should have 0 vectors and return empty search results."""
        assert index.total_vectors == 0
        results = index.search(_random_vector(), top_k=5)
        assert results == []

    def test_add_single_vector(self, index):
        """Adding one vector increases count to 1."""
        vec = _random_vector()
        faiss_idx = index.add(doc_id=42, vector=vec)
        assert faiss_idx == 0
        assert index.total_vectors == 1

    def test_search_returns_exact_match(self, index):
        """Searching with the same vector returns similarity ~1.0."""
        vec = _random_vector()
        index.add(doc_id=1, vector=vec)

        results = index.search(vec, top_k=1)
        assert len(results) == 1
        assert results[0].doc_id == 1
        assert results[0].similarity_score > 0.99

    def test_search_ordering(self, index):
        """Results should be ordered by descending similarity."""
        target = _random_vector()
        similar = target + np.random.randn(128).astype(np.float32) * 0.1
        similar /= np.linalg.norm(similar)
        different = _random_vector()

        index.add(doc_id=1, vector=target)
        index.add(doc_id=2, vector=similar)
        index.add(doc_id=3, vector=different)

        results = index.search(target, top_k=3)
        assert len(results) == 3
        # Target itself should be the top match
        assert results[0].doc_id == 1
        # Scores should be descending
        scores = [r.similarity_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_dimension_mismatch_raises(self, index):
        """Adding a vector with wrong dimension should raise ValueError."""
        wrong_vec = np.random.randn(64).astype(np.float32)
        with pytest.raises(ValueError, match="dimension mismatch"):
            index.add(doc_id=1, vector=wrong_vec)

    def test_remove_existing_doc(self, index):
        """Removing an existing document should decrease the count."""
        vec1 = _random_vector()
        vec2 = _random_vector()
        index.add(doc_id=1, vector=vec1)
        index.add(doc_id=2, vector=vec2)

        assert index.total_vectors == 2
        removed = index.remove(doc_id=1)
        assert removed is True
        assert index.total_vectors == 1

        results = index.search(vec1, top_k=5)
        doc_ids = [r.doc_id for r in results]
        assert 1 not in doc_ids

    def test_remove_nonexistent_doc(self, index):
        """Removing a non-existent document returns False."""
        assert index.remove(doc_id=999) is False

    def test_save_and_load_roundtrip(self, index):
        """Index should be recoverable after save + load."""
        vec1 = _random_vector()
        vec2 = _random_vector()
        index.add(doc_id=10, vector=vec1)
        index.add(doc_id=20, vector=vec2)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.index"
            index.save(path)

            loaded_index = VectorIndex(dimension=128)
            loaded_index.load(path)

            assert loaded_index.total_vectors == 2

            results = loaded_index.search(vec1, top_k=1)
            assert results[0].doc_id == 10
            assert results[0].similarity_score > 0.99

    def test_top_k_capped_at_total(self, index):
        """top_k larger than total vectors should return all vectors."""
        for i in range(3):
            index.add(doc_id=i, vector=_random_vector())

        results = index.search(_random_vector(), top_k=100)
        assert len(results) == 3

    def test_load_nonexistent_path_starts_empty(self, index):
        """Loading from a non-existent path should leave index empty."""
        index.load("/nonexistent/path/index.faiss")
        assert index.total_vectors == 0
