"""POST /api/v1/register — Register a new archival document.

Fire-and-forget: saves raw image + metadata immediately, then enqueues
AI processing (rembg + DINOv2) to the background worker.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from arch_fingerprint.api.schemas import RegisterResponse
from arch_fingerprint.config import settings
from arch_fingerprint.db.models import Document
from arch_fingerprint.db.session import get_db
from arch_fingerprint.worker.queue import ProcessingJob, enqueue

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", response_model=RegisterResponse, status_code=202)
async def register_document(
    image: UploadFile = File(..., description="High-resolution document image"),
    khazanah: str = Form(..., description="Archive collection name"),
    page_number: int | None = Form(None, description="Page number within collection"),
    description: str | None = Form(None, description="Document description"),
    scan_mode: str = Form("single", description="Scan mode: 'single' or 'book'"),
    writing_mode: str = Form("print", description="Content type: 'print' or 'handwriting'"),
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Register a document — returns immediately, processes in background."""
    # Read and validate image
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image file.")

    # Save RAW image to disk immediately (no AI processing yet)
    filename = f"{uuid.uuid4().hex}_raw.png"
    save_path = settings.upload_path / filename

    try:
        save_path.write_bytes(image_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save image: {e}")

    # Create DB record with pending status
    is_handwriting = True if writing_mode == "handwriting" else False
    
    doc = Document(
        khazanah=khazanah,
        page_number=page_number,
        description=description,
        image_path=str(save_path),
        status="pending",
        is_paleography=1 if is_handwriting else 0
    )
    db.add(doc)
    await db.flush()

    # Enqueue background AI processing
    await enqueue(ProcessingJob(
        doc_id=doc.id, 
        raw_image_path=str(save_path), 
        mode=scan_mode,
        is_handwriting=is_handwriting
    ))

    await db.commit()

    logger.info("Accepted doc_id=%d for processing, khazanah='%s'", doc.id, khazanah)

    return RegisterResponse(
        id=doc.id,
        fingerprint=doc.fingerprint,
        khazanah=doc.khazanah,
        page_number=doc.page_number,
        vector_id=doc.vector_id or -1,  # -1 indicates pending processing
    )
