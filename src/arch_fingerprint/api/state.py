"""Shared application state: model, FAISS index, and dependencies."""

from arch_fingerprint.ai.model import DINOv2Embedder
from arch_fingerprint.ai.text_model import TextEmbedder
from arch_fingerprint.search.faiss_index import VectorIndex

# Singleton instances initialized during app lifespan
embedder: DINOv2Embedder | None = None
vector_index: VectorIndex | None = None

text_embedder: TextEmbedder | None = None
text_vector_index: VectorIndex | None = None


def get_embedder() -> DINOv2Embedder:
    """Get the loaded DINOv2 embedder instance."""
    if embedder is None:
        raise RuntimeError("Embedder not initialized. App lifespan not started.")
    return embedder


def get_vector_index() -> VectorIndex:
    """Get the loaded FAISS vector index instance."""
    if vector_index is None:
        raise RuntimeError("Vector index not initialized. App lifespan not started.")
    return vector_index


def get_text_embedder() -> TextEmbedder:
    """Get the loaded SentenceTransformer text embedder instance."""
    if text_embedder is None:
        raise RuntimeError("Text Embedder not initialized. App lifespan not started.")
    return text_embedder


def get_text_vector_index() -> VectorIndex:
    """Get the loaded FAISS text vector index instance."""
    if text_vector_index is None:
        raise RuntimeError("Text Vector index not initialized. App lifespan not started.")
    return text_vector_index
