"""FastAPI application with DINOv2 + FAISS lifespan management.

This is the main entry point for the ARCH-FINGERPRINT server.
On startup, it loads the DINOv2 model and FAISS index into memory.
On shutdown, it saves the FAISS index to disk.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

# ── Thumbnail endpoint (must be registered BEFORE StaticFiles mount) ─────
_THUMB_DIR = Path(settings.upload_dir) / ".thumbs"
_THUMB_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/uploads/thumb/{filename}")
def serve_thumbnail(
    filename: str,
    w: int = Query(400, ge=50, le=1200, description="Max thumbnail width"),
):
    """Serve a resized JPEG thumbnail with disk caching.

    Thumbnails are generated on first request and cached to disk.
    Cache is automatically invalidated when the source file is modified.
    """
    from PIL import Image as PILImage

    # Sanitise filename (prevent path traversal)
    safe_name = Path(filename).name
    src = Path(settings.upload_dir) / safe_name
    if not src.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    thumb_name = f"{src.stem}_w{w}.jpg"
    thumb_path = _THUMB_DIR / thumb_name

    # Serve from cache if it exists and is newer than the source
    if thumb_path.exists() and thumb_path.stat().st_mtime >= src.stat().st_mtime:
        return FileResponse(
            str(thumb_path),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Generate thumbnail
    try:
        img = PILImage.open(src)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        # Preserve aspect ratio; height limit = 3× width to handle tall docs
        img.thumbnail((w, w * 3), PILImage.Resampling.LANCZOS)
        img.save(thumb_path, format="JPEG", quality=80, optimize=True)
    except Exception as exc:
        logger.error("Thumbnail generation failed for %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail="Thumbnail generation failed")

    return FileResponse(
        str(thumb_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# Serve uploaded images (full resolution)
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
