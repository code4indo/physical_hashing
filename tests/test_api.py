"""Tests for the FastAPI endpoints using TestClient."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image


def _create_test_image_bytes() -> bytes:
    """Create a simple PNG image in memory for upload testing."""
    img = Image.new("RGB", (200, 200), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


@pytest.fixture
def mock_embedder():
    """Mock DINOv2 embedder that returns a fixed vector."""
    embedder = MagicMock()
    embedder.embedding_dim = 1024
    embedder.extract_embedding.return_value = np.random.randn(1024).astype(np.float32)
    return embedder


@pytest.fixture
def mock_index():
    """Mock FAISS vector index."""
    from arch_fingerprint.search.faiss_index import SearchResult

    index = MagicMock()
    index.total_vectors = 0
    index.add.return_value = 0
    index.search.return_value = []
    index.save.return_value = None
    return index


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_200(self, mock_embedder, mock_index):
        """Health check should return server status."""
        with patch("arch_fingerprint.api.state.embedder", mock_embedder):
            with patch("arch_fingerprint.api.state.vector_index", mock_index):
                # Import app after patching to avoid lifespan
                from arch_fingerprint.api.main import app

                # Override lifespan to avoid model loading
                app.router.lifespan_context = _noop_lifespan

                client = TestClient(app)
                resp = client.get("/health")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "healthy"
                assert "version" in data


class TestRegisterEndpoint:
    """Tests for POST /api/v1/register."""

    def test_register_rejects_empty_image(self, mock_embedder, mock_index):
        """Empty file upload should return 400."""
        with patch("arch_fingerprint.api.state.embedder", mock_embedder):
            with patch("arch_fingerprint.api.state.vector_index", mock_index):
                from arch_fingerprint.api.main import app

                app.router.lifespan_context = _noop_lifespan

                client = TestClient(app)
                resp = client.post(
                    "/api/v1/register",
                    data={"khazanah": "test_collection"},
                    files={"image": ("empty.png", b"", "image/png")},
                )
                assert resp.status_code == 400


class TestSearchEndpoint:
    """Tests for POST /api/v1/search."""

    def test_search_returns_empty_for_empty_index(self, mock_embedder, mock_index):
        """Search on empty index should return empty results."""
        with patch("arch_fingerprint.api.state.embedder", mock_embedder):
            with patch("arch_fingerprint.api.state.vector_index", mock_index):
                from arch_fingerprint.api.main import app

                app.router.lifespan_context = _noop_lifespan

                client = TestClient(app)
                img_bytes = _create_test_image_bytes()
                resp = client.post(
                    "/api/v1/search",
                    data={"top_k": "5"},
                    files={"image": ("query.png", img_bytes, "image/png")},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["total_results"] == 0
                assert data["results"] == []


from contextlib import asynccontextmanager


@asynccontextmanager
async def _noop_lifespan(app):
    """No-op lifespan for testing without loading models."""
    yield
