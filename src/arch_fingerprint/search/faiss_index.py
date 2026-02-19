"""FAISS-based vector index for document fingerprint similarity search.

Uses IndexFlatIP (inner product) on L2-normalized vectors, which is
mathematically equivalent to cosine similarity. This provides exact
nearest-neighbor search suitable for up to ~1M vectors.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result from the FAISS index."""

    doc_id: int
    similarity_score: float


class VectorIndex:
    """FAISS vector index for document fingerprint storage and retrieval.

    Internally maintains a mapping between sequential FAISS indices and
    application-level document IDs, since FAISS uses contiguous integer
    indices starting from 0.
    """

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension
        # Inner product on L2-normalized vectors = cosine similarity
        self._index = faiss.IndexFlatIP(dimension)
        # Maps FAISS sequential index → application document ID
        self._id_map: list[int] = []

    @property
    def total_vectors(self) -> int:
        return self._index.ntotal

    def add(self, doc_id: int, vector: np.ndarray) -> int:
        """Add a document vector to the index.

        Args:
            doc_id: Application-level document ID (from PostgreSQL).
            vector: L2-normalized float32 vector of shape (dimension,).

        Returns:
            The FAISS index position assigned to this vector.
        """
        if vector.shape != (self._dimension,):
            raise ValueError(
                f"Vector dimension mismatch: expected ({self._dimension},), "
                f"got {vector.shape}"
            )

        vec_2d = vector.reshape(1, -1).astype(np.float32)
        faiss_idx = self._index.ntotal
        self._index.add(vec_2d)
        self._id_map.append(doc_id)

        logger.debug("Added doc_id=%d at FAISS index %d. Total: %d", doc_id, faiss_idx, self.total_vectors)
        return faiss_idx

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> list[SearchResult]:
        """Search for the most similar documents to the query vector.

        Args:
            query_vector: L2-normalized float32 vector of shape (dimension,).
            top_k: Number of nearest neighbors to return.

        Returns:
            List of SearchResult sorted by descending similarity score.
        """
        if self._index.ntotal == 0:
            return []

        effective_k = min(top_k, self._index.ntotal)
        query_2d = query_vector.reshape(1, -1).astype(np.float32)

        # scores = inner product (cosine sim for normalized vectors)
        scores, indices = self._index.search(query_2d, effective_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results.append(SearchResult(
                doc_id=self._id_map[idx],
                similarity_score=float(score),
            ))

        return results

    def remove(self, doc_id: int) -> bool:
        """Remove a document from the index by rebuilding without it.

        FAISS IndexFlatIP does not support direct removal, so we rebuild
        the index excluding the target document. This is acceptable for
        infrequent deletions.

        Args:
            doc_id: Application document ID to remove.

        Returns:
            True if the document was found and removed, False otherwise.
        """
        if doc_id not in self._id_map:
            return False

        # Reconstruct all vectors except the target
        idx_to_remove = self._id_map.index(doc_id)
        all_vectors = faiss.rev_swig_ptr(
            self._index.get_xb(), self._index.ntotal * self._dimension
        ).reshape(self._index.ntotal, self._dimension).copy()

        keep_mask = np.ones(len(self._id_map), dtype=bool)
        keep_mask[idx_to_remove] = False

        kept_vectors = all_vectors[keep_mask]
        kept_ids = [did for i, did in enumerate(self._id_map) if keep_mask[i]]

        # Rebuild
        self._index = faiss.IndexFlatIP(self._dimension)
        self._id_map = []

        if len(kept_vectors) > 0:
            self._index.add(kept_vectors.astype(np.float32))
            self._id_map = kept_ids

        logger.info("Removed doc_id=%d. Remaining: %d vectors.", doc_id, self.total_vectors)
        return True

    def get_vector_by_doc_id(self, doc_id: int) -> np.ndarray | None:
        """Retrieve a stored vector from the index by its document ID.
        
        Args:
            doc_id: Application document ID to look up.
            
        Returns:
            The stored vector as a numpy array, or None if not found.
        """
        try:
            # Find all indices for this doc_id (visual index has 4, text index has 1)
            # For simplicity, we return the FIRST one found. 
            # In text index, there should only be one.
            idx = self._id_map.index(doc_id)
            # FAISS IndexFlat supports reconstruction
            return self._index.reconstruct(idx)
        except (ValueError, RuntimeError):
            # ValueError: doc_id not in list
            # RuntimeError: reconstruct not supported (should be fine for IndexFlat)
            return None

    def save(self, path: str | Path) -> None:
        """Persist the FAISS index and ID map to disk."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        faiss.write_index(self._index, str(path))
        id_map_path = path.with_suffix(".idmap.npy")
        np.save(str(id_map_path), np.array(self._id_map, dtype=np.int64))

        logger.info("Saved FAISS index (%d vectors) to %s", self.total_vectors, path)

    def load(self, path: str | Path) -> None:
        """Load a previously saved FAISS index and ID map from disk."""
        path = Path(path)
        if not path.exists():
            logger.warning("FAISS index file not found: %s. Starting with empty index.", path)
            return

        self._index = faiss.read_index(str(path))
        id_map_path = path.with_suffix(".idmap.npy")

        if id_map_path.exists():
            self._id_map = np.load(str(id_map_path)).tolist()
        else:
            # Fallback: assume sequential IDs if map is missing
            logger.warning("ID map file not found. Using sequential IDs as fallback.")
            self._id_map = list(range(self._index.ntotal))

        logger.info("Loaded FAISS index: %d vectors from %s", self.total_vectors, path)
