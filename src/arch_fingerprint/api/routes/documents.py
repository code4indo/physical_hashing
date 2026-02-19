"""Document CRUD routes: list, detail, delete."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from arch_fingerprint.api.schemas import (
    DeleteResponse,
    DocumentDetail,
    DocumentListResponse,
)
from arch_fingerprint.api.state import get_vector_index
from arch_fingerprint.config import settings
from arch_fingerprint.db.models import Document
from arch_fingerprint.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    khazanah: str | None = Query(None, description="Filter by archive collection"),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List all registered documents with pagination and optional filtering.
    
    Excludes soft-deleted documents (status='deleted').
    """
    stmt = select(Document).where(Document.status != "deleted")
    count_stmt = select(func.count(Document.id)).where(Document.status != "deleted")

    if khazanah:
        stmt = stmt.where(Document.khazanah == khazanah)
        count_stmt = count_stmt.where(Document.khazanah == khazanah)

    # Get total count
    total = (await db.execute(count_stmt)).scalar_one()

    # Apply pagination
    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page).order_by(Document.created_at.desc())

    result = await db.execute(stmt)
    docs = result.scalars().all()

    return DocumentListResponse(
        documents=[DocumentDetail.model_validate(doc) for doc in docs],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
async def get_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    """Get full details of a registered document."""
    stmt = select(Document).where(Document.id == doc_id).where(Document.status != "deleted")
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document id={doc_id} not found.")

    return DocumentDetail.model_validate(doc)


@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
async def delete_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
) -> DeleteResponse:
    """Soft-delete a document by marking it as deleted.

    For production with millions of documents, this uses soft-delete:
    - Marks document status as 'deleted' in database
    - Sets deleted_at timestamp
    - Keeps vector in FAISS (vector_id can be reused for new docs)
    - Optional: Periodically run cleanup job to remove old deleted docs

    This avoids expensive FAISS index rebuilds on every deletion.
    """
    from datetime import datetime, timezone
    from sqlalchemy import update

    stmt = select(Document).where(Document.id == doc_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document id={doc_id} not found.")

    # Soft delete - mark as deleted instead of removing
    # Also clear vector_id to allow reuse by new documents (UNIQUE constraint)
    await db.execute(
        update(Document)
        .where(Document.id == doc_id)
        .values(
            status="deleted",
            deleted_at=datetime.now(timezone.utc),
            vector_id=None  # Clear to allow reuse by GapReuseAllocator
        )
    )
    await db.commit()

    logger.info("Soft-deleted document id=%d (vector_id=%s can be reused)", doc_id, doc.vector_id)

    return DeleteResponse(id=doc_id)


@router.get("/documents/{doc_id}/status")
async def get_document_status(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Check the processing status of a registered document."""
    from arch_fingerprint.db.models import Document
    from sqlalchemy import select

    stmt = select(Document).where(Document.id == doc_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    return {
        "id": doc.id,
        "status": doc.status,
        "error_message": doc.error_message,
        "vector_id": doc.vector_id,
        "text_content_length": len(doc.text_content) if doc.text_content else 0
    }

@router.get("/documents/{doc_id}/ocr")
async def get_document_ocr(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get the OCR content of a document."""
    from arch_fingerprint.db.models import Document
    from sqlalchemy import select

    stmt = select(Document).where(Document.id == doc_id).where(Document.status != "deleted")
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Status check
    ocr_status = "not_available"
    if doc.text_content and len(doc.text_content.strip()) > 0:
        ocr_status = "completed"
    elif doc.status == "processing":
        ocr_status = "processing"
    elif doc.status == "failed":
        ocr_status = "failed"
    elif doc.status == "pending":
        ocr_status = "pending"

    return {
        "id": doc.id,
        "status": ocr_status,
        "content": doc.text_content or "",
        "length": len(doc.text_content) if doc.text_content else 0
    }

@router.post("/documents/{doc_id}/ocr/process")
async def process_document_ocr(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Trigger OCR processing for a document that doesn't have OCR text."""
    import asyncio
    from sqlalchemy import update
    
    stmt = select(Document).where(Document.id == doc_id).where(Document.status != "deleted")
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document id={doc_id} not found.")

    if hasattr(doc, 'is_paleography') and doc.is_paleography:
        logger.info(f"Skipping OCR for document id={doc_id}: marked as paleography")
        return {
            "id": doc_id,
            "status": "skipped",
            "message": "Document is marked as paleography.",
            "reason": "paleography_not_supported"
        }

    # Check if document already has OCR
    if doc.text_content and len(doc.text_content.strip()) > 10:
        logger.info(f"Document id={doc_id} already has OCR text ({len(doc.text_content)} chars)")
        return {
            "id": doc_id,
            "status": "already_processed",
            "message": "Document already has OCR text",
            "text_length": len(doc.text_content)
        }

    # Image logic
    image_path = Path(settings.upload_dir) / doc.image_path.split('/')[-1]
    raw_image_path = str(image_path).replace('_clean.png', '_raw.png')
    
    if not Path(raw_image_path).exists():
        raw_image_path = str(image_path)
        if not Path(raw_image_path).exists():
            raise HTTPException(status_code=404, detail="Image file not found")

    logger.info(f"Processing OCR for document id={doc_id}, image={raw_image_path}")

    # Run OCR asynchronously using the optimized async function
    try:
        from arch_fingerprint.ai.ocr import run_ocr_async
        
        # Directly await the async OCR function
        ocr_text = await run_ocr_async(raw_image_path)
        
        if ocr_text and len(ocr_text.strip()) > 0:
            # Update document with OCR text
            await db.execute(
                update(Document)
                .where(Document.id == doc_id)
                .values(text_content=ocr_text)
            )
            await db.commit()
            
            logger.info(f"OCR completed for document id={doc_id}: {len(ocr_text)} chars extracted")
            
            return {
                "id": doc_id,
                "status": "success",
                "message": "OCR processing completed",
                "text_length": len(ocr_text),
                "preview": ocr_text[:100] + "..." if len(ocr_text) > 100 else ocr_text
            }
        else:
            logger.warning(f"OCR returned empty text for document id={doc_id}")
            return {
                "id": doc_id,
                "status": "no_text",
                "message": "OCR completed but no text was extracted"
            }
            
    except Exception as e:
        logger.error(f"OCR processing failed for document id={doc_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"OCR processing failed: {str(e)}"
        )
