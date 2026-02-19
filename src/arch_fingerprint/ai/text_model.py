
"""SentenceTransformer wrapper for semantic text fingerprinting."""

import logging
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class TextEmbedder:
    """Extracts semantic embeddings from text using SentenceTransformers.
    
    Produces dense vectors that capture the semantic meaning of document text,
    enabling search by conceptual similarity rather than just keywords.
    """

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        self._model_name = model_name
        self._device = device
        self._model: SentenceTransformer | None = None

    def load(self) -> None:
        """Load the SentenceTransformer model."""
        logger.info("Loading Text Model '%s' on device '%s'...", self._model_name, self._device)
        self._model = SentenceTransformer(self._model_name, device=self._device)
        # Normalize embeddings to allow dot product as cosine similarity
        self._model.max_seq_length = 512 # Standard for BERT-based models
        logger.info("Text Model loaded. Output dim: %d", self.embedding_dim)

    @property
    def embedding_dim(self) -> int:
        """Dimensionality of the output embedding vector."""
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        return self._model.get_sentence_embedding_dimension()

    def encode(self, texts: List[str] | str) -> np.ndarray:
        """Encode text or list of texts into embeddings.
        
        Args:
            texts: Single string or list of strings.
            
        Returns:
            Numpy array of embeddings (normalized).
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        # E5 models require "query: " or "passage: " prefix for asymmetric tasks.
        # For symmetric document similarity, we treat everything as "passage".
        # However, if we just want raw semantic content, no prefix is also fine for some models.
        # But E5 paper recommends prefixes.
        # For now, we assume raw text, but if using E5, we should be aware.
        # Let's check if model name implicitly handles it, no it doesn't.
        # We will encode as-is for now to be generic.
        
        embeddings = self._model.encode(
            texts, 
            normalize_embeddings=True, 
            convert_to_numpy=True,
            show_progress_bar=False
        )
        return embeddings.astype(np.float32)
