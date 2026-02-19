"""Tests for the DINOv2 model wrapper and embedding extraction."""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

from arch_fingerprint.ai.model import DINOv2Embedder


@pytest.fixture
def dummy_image() -> Image.Image:
    """Create a simple 518x518 RGB test image."""
    arr = np.random.randint(0, 255, (518, 518, 3), dtype=np.uint8)
    return Image.fromarray(arr)


@pytest.fixture
def different_image() -> Image.Image:
    """Create a distinctly different test image (solid color)."""
    arr = np.full((518, 518, 3), 128, dtype=np.uint8)
    return Image.fromarray(arr)


class TestDINOv2Embedder:
    """Test suite for the DINOv2 embedding extractor."""

    def test_model_not_loaded_raises(self):
        """Calling extract without load() should raise RuntimeError."""
        embedder = DINOv2Embedder(device="cpu")
        dummy = Image.new("RGB", (100, 100))
        with pytest.raises(RuntimeError, match="not loaded"):
            embedder.extract_embedding(dummy)

    def test_embedding_dim_not_loaded_raises(self):
        """Accessing embedding_dim without load() should raise RuntimeError."""
        embedder = DINOv2Embedder(device="cpu")
        with pytest.raises(RuntimeError, match="not loaded"):
            _ = embedder.embedding_dim

    @pytest.mark.skipif(
        not _torch_available(),
        reason="PyTorch not available or model download not feasible in CI",
    )
    def test_embedding_shape_and_normalization(self, dummy_image):
        """Embedding should be 1024-dim and L2-normalized."""
        embedder = DINOv2Embedder(model_name="dinov2_vits14", device="cpu")
        embedder.load()

        emb = embedder.extract_embedding(dummy_image)

        assert emb.shape == (embedder.embedding_dim,)
        assert emb.dtype == np.float32
        # L2 norm should be ~1.0
        norm = np.linalg.norm(emb)
        assert abs(norm - 1.0) < 1e-5, f"Expected L2 norm ~1.0, got {norm}"

    @pytest.mark.skipif(
        not _torch_available(),
        reason="PyTorch not available",
    )
    def test_identical_images_produce_identical_embeddings(self, dummy_image):
        """Same image should always produce the same embedding (deterministic)."""
        embedder = DINOv2Embedder(model_name="dinov2_vits14", device="cpu")
        embedder.load()

        emb1 = embedder.extract_embedding(dummy_image)
        emb2 = embedder.extract_embedding(dummy_image)

        np.testing.assert_array_almost_equal(emb1, emb2, decimal=6)

    @pytest.mark.skipif(
        not _torch_available(),
        reason="PyTorch not available",
    )
    def test_different_images_produce_different_embeddings(self, dummy_image, different_image):
        """Different images should produce distinct embeddings."""
        embedder = DINOv2Embedder(model_name="dinov2_vits14", device="cpu")
        embedder.load()

        emb1 = embedder.extract_embedding(dummy_image)
        emb2 = embedder.extract_embedding(different_image)

        cosine_sim = np.dot(emb1, emb2)
        assert cosine_sim < 0.99, f"Expected different embeddings, cosine sim = {cosine_sim}"

    def test_grayscale_image_converted_to_rgb(self):
        """Grayscale images should be auto-converted to RGB without error."""
        embedder = DINOv2Embedder(device="cpu")
        # Mock the model to avoid actual inference
        mock_model = MagicMock()
        mock_model.embed_dim = 1024

        import torch
        mock_output = torch.randn(1, 1024)
        mock_model.return_value = mock_output
        mock_model.to.return_value = mock_model

        embedder._model = mock_model
        gray_img = Image.new("L", (100, 100), color=128)

        # Should not raise
        emb = embedder.extract_embedding(gray_img)
        assert isinstance(emb, np.ndarray)


def _torch_available() -> bool:
    """Check if PyTorch is importable."""
    try:
        import torch
        return True
    except ImportError:
        return False
