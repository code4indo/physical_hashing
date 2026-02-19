"""FastAPI application with DINOv2 + FAISS lifespan management.

This is the main entry point for the ARCH-FINGERPRINT server.
On startup, it loads the DINOv2 model and FAISS index into memory.
On shutdown, it saves the FAISS index to disk.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from arch_fingerprint import __version__
from arch_fingerprint.ai.model import DINOv2Embedder
from arch_fingerprint.api import state
from arch_fingerprint.api.routes import documents, register, search
from arch_fingerprint.config import settings
from arch_fingerprint.db.models import Base
from arch_fingerprint.db.session import engine
from arch_fingerprint.search.faiss_index import VectorIndex
from arch_fingerprint.worker.queue import start_worker, shutdown_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: load model and index on startup, save on shutdown."""
    logger.info("=== ARCH-FINGERPRINT v%s starting ===", __version__)

    # Create database tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured.")

    # Load DINOv2 model
    embedder = DINOv2Embedder(
        model_name=settings.model_name,
        device=settings.model_device,
    )
    embedder.load()
    state.embedder = embedder

    # Load or create Visual FAISS index
    index = VectorIndex(dimension=embedder.embedding_dim)
    index.load(settings.faiss_index_path)
    state.vector_index = index

    # Load Text Model (SentenceTransformers)
    logger.info("Loading Text Model '%s'...", settings.text_model_name)
    from arch_fingerprint.ai.text_model import TextEmbedder
    text_embedder = TextEmbedder(
        model_name=settings.text_model_name,
        device=settings.model_device
    )
    # Try loading, if fail (e.g. download), just log error but continue?
    # No, semantic search is now core feature requested.
    text_embedder.load()
    state.text_embedder = text_embedder
    
    # Load or create Text FAISS index
    text_index = VectorIndex(dimension=text_embedder.embedding_dim)
    text_index.load(settings.faiss_text_index_path)
    state.text_vector_index = text_index

    # Ensure upload directory exists
    settings.upload_path.mkdir(parents=True, exist_ok=True)

    # Start background AI worker
    await start_worker()

    logger.info("Background AI worker started.")

    logger.info("=== ARCH-FINGERPRINT ready. FAISS: %d vectors ===", index.total_vectors)

    yield

    # Shutdown: drain queue, save FAISS index
    logger.info("Shutting down. Draining job queue...")
    await shutdown_worker()
    
    # Text index save (resilient)
    try:
        if state.text_vector_index is not None:
             text_index = state.get_text_vector_index()
             text_index.save(settings.faiss_text_index_path)
             logger.info("Text FAISS index saved.")
    except Exception as e:
        logger.warning(f"Resilient shutdown: could not save text index: {e}")
    
    logger.info("Shutdown complete. Goodbye.")


app = FastAPI(
    title="ARCH-FINGERPRINT",
    description=(
        "Sistem Identifikasi Otomatis Arsip Historis — "
        "Automated Historical Archive Identification via DINOv2 Visual Fingerprinting"
    ),
    version=__version__,
    lifespan=lifespan,
)

# CORS for Android client
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded images
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

# Register API routes
app.include_router(register.router, prefix="/api/v1", tags=["Register"])
app.include_router(search.router, prefix="/api/v1", tags=["Search"])
app.include_router(documents.router, prefix="/api/v1", tags=["Documents"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    index = state.get_vector_index()
    return {
        "status": "healthy",
        "version": __version__,
        "model": settings.model_name,
        "device": settings.model_device,
        "total_documents": index.total_vectors,
    }
